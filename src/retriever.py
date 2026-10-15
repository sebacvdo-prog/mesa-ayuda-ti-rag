"""Recuperación híbrida: índice vectorial FAISS + conector SQL al ITSM.

El módulo resuelve cuatro cosas:

1. **Enrutador de consulta.** Clasifica la pregunta en ``interna``, ``externa`` o
   ``mixta`` y filtra el índice por el metadato ``fuente``.
2. **Búsqueda vectorial con umbral.** ``top_k=4`` y umbral según el proveedor:
   lo que no llega al umbral se descarta en vez de rellenar el contexto con ruido.
3. **Re-ranking por vigencia.** Entre fragmentos de pertinencia equivalente manda
   el documento con ``fecha_vigencia`` más reciente. Es lo que hace que un aviso
   del CSIRT de julio de 2026 pese más que un procedimiento interno de febrero.
4. **Conector SQL parametrizado.** Tickets, SLA y CMDB se consultan con
   ``sqlite3`` y marcadores ``?``. **Nunca** se interpola texto del usuario en el
   SQL: eso sería una inyección esperando ocurrir.
"""

from __future__ import annotations

import os
import re
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Sequence

from langchain_core.documents import Document
from pydantic import BaseModel, ConfigDict, Field

from src import config
from src.guardrails import niveles_visibles  # la política de acceso vive allí

# ---------------------------------------------------------------------------
# Modelo de resultado
# ---------------------------------------------------------------------------


class FragmentoRecuperado(BaseModel):
    """Fragmento devuelto por la búsqueda vectorial junto con su puntaje.

    Attributes:
        documento: Fragmento de LangChain con su texto y metadatos.
        puntaje: Score de relevancia de LangChain; mayor es mejor. No es probabilidad.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    documento: Document
    puntaje: float = Field(ge=-1.0, le=1.0)

    @property
    def titulo(self) -> str:
        """Título del documento de origen."""
        return str(self.documento.metadata.get("titulo", "documento sin título"))

    @property
    def nombre_documento(self) -> str:
        """Nombre del archivo de origen."""
        return str(self.documento.metadata.get("documento", "desconocido"))

    @property
    def fecha_vigencia(self) -> date:
        """Fecha de vigencia del documento, o ``date.min`` si falta o es inválida."""
        return _parsear_fecha(self.documento.metadata.get("fecha_vigencia"))

    @property
    def cita(self) -> str:
        """Cita corta lista para el bloque ``Fuente:`` de la respuesta."""
        return f"{self.titulo} · {self.documento.metadata.get('fecha_vigencia', 's/f')}"


def _parsear_fecha(valor: Any) -> date:
    """Convierte una fecha ISO a ``date``, tolerando valores ausentes o rotos.

    Args:
        valor: Texto con formato ``AAAA-MM-DD``, u otra cosa.

    Returns:
        La fecha correspondiente, o ``date.min`` si no se puede interpretar.
    """
    if isinstance(valor, date):
        return valor
    try:
        return date.fromisoformat(str(valor))
    except (TypeError, ValueError):
        return date.min


# ---------------------------------------------------------------------------
# Enrutador de consulta
# ---------------------------------------------------------------------------

TERMINOS_EXTERNOS: tuple[str, ...] = (
    "microsoft", "outlook 365", "fortinet", "forticlient", "fabricante",
    "proveedor", "csirt", "aviso de seguridad", "alerta de seguridad",
    "documentación oficial", "documentacion oficial", "vulnerabilidad",
    "código de error del cliente", "codigo de error del cliente",
    "0x8004010f", "0x800ccc0e", "-7200", "-455", "-20199",
    "mfa fatigue", "fatiga de segundo factor", "campaña", "campana de phishing",
)

TERMINOS_INTERNOS: tuple[str, ...] = (
    "sla", "catálogo", "catalogo", "prioridad", "p1", "p2", "p3", "p4",
    "escalamiento", "escalar", "nivel 2", "nivel 1", "política", "politica",
    "procedimiento", "kb-", "aconcagua", "sucursal", "centro de distribución",
    "centro de distribucion", "ticket", "cmdb", "activo", "horario de atención",
    "horario de atencion", "primera respuesta", "mesa de ayuda", "interno",
)


def clasificar_consulta(consulta: str) -> str:
    """Clasifica la consulta según el tipo de fuente que debería responderla.

    Heurística por palabras clave, deliberadamente simple y auditable: una
    clasificación equivocada solo cambia el filtro de fuente, y ``mixta`` (el
    valor por defecto) nunca deja fuera documentos.

    Args:
        consulta: Pregunta del usuario en lenguaje natural.

    Returns:
        ``"interna"``, ``"externa"`` o ``"mixta"``.
    """
    texto = consulta.lower()
    hay_externo = any(termino in texto for termino in TERMINOS_EXTERNOS)
    hay_interno = any(termino in texto for termino in TERMINOS_INTERNOS)

    if hay_externo and hay_interno:
        return "mixta"
    if hay_externo:
        return "externa"
    if hay_interno:
        return "interna"
    return "mixta"


def filtro_de_fuente(clasificacion: str) -> str | None:
    """Traduce la clasificación al valor del metadato ``fuente``.

    Args:
        clasificacion: Salida de :func:`clasificar_consulta`.

    Returns:
        ``"interna"``, ``"externa"``, o ``None`` cuando no hay que filtrar.
    """
    return None if clasificacion == "mixta" else clasificacion


# ---------------------------------------------------------------------------
# Post-procesamiento de resultados
# ---------------------------------------------------------------------------


def filtrar_por_metadatos(
    fragmentos: Iterable[FragmentoRecuperado],
    fuente: str | None = None,
    perfil: str = "agente",
) -> list[FragmentoRecuperado]:
    """Filtra fragmentos por fuente y por nivel de acceso del perfil.

    Args:
        fragmentos: Resultados crudos de la búsqueda vectorial.
        fuente: ``interna``, ``externa`` o ``None`` para no filtrar.
        perfil: Perfil que hace la consulta.

    Returns:
        Fragmentos que el perfil puede ver y que corresponden a la fuente pedida.
    """
    permitidos = niveles_visibles(perfil)
    resultado: list[FragmentoRecuperado] = []
    for fragmento in fragmentos:
        metadatos = fragmento.documento.metadata
        if fuente is not None and metadatos.get("fuente") != fuente:
            continue
        if metadatos.get("nivel_acceso", "publico_interno") not in permitidos:
            continue
        resultado.append(fragmento)
    return resultado


def aplicar_umbral(
    fragmentos: Iterable[FragmentoRecuperado],
    umbral: float | None = None,
) -> list[FragmentoRecuperado]:
    """Descarta los fragmentos que no alcanzan el umbral de relevancia.

    Args:
        fragmentos: Fragmentos recuperados.
        umbral: Puntaje mínimo aceptable; por defecto, el del proveedor activo.

    Returns:
        Solo los fragmentos con ``puntaje >= umbral``.
    """
    minimo = config.umbral_similitud() if umbral is None else umbral
    return [fragmento for fragmento in fragmentos if fragmento.puntaje >= minimo]


def reordenar_por_vigencia(
    fragmentos: Sequence[FragmentoRecuperado],
    margen: float = config.MARGEN_REORDENAMIENTO,
) -> list[FragmentoRecuperado]:
    """Reordena privilegiando la vigencia entre fragmentos igual de pertinentes.

    Se agrupan los fragmentos cuya diferencia de puntaje respecto del mejor del
    grupo no supera ``margen`` (es decir, que cubren el mismo procedimiento con
    pertinencia equivalente) y dentro de cada grupo se ordena por
    ``fecha_vigencia`` descendente. Entre grupos manda siempre el puntaje.

    Args:
        fragmentos: Fragmentos ya filtrados por umbral.
        margen: Diferencia máxima de puntaje para considerarlos equivalentes.

    Returns:
        Lista reordenada.
    """
    ordenados = sorted(fragmentos, key=lambda f: f.puntaje, reverse=True)
    resultado: list[FragmentoRecuperado] = []
    grupo: list[FragmentoRecuperado] = []

    for fragmento in ordenados:
        if grupo and (grupo[0].puntaje - fragmento.puntaje) > margen:
            resultado.extend(sorted(grupo, key=lambda f: f.fecha_vigencia, reverse=True))
            grupo = []
        grupo.append(fragmento)

    if grupo:
        resultado.extend(sorted(grupo, key=lambda f: f.fecha_vigencia, reverse=True))
    return resultado


def formatear_contexto(fragmentos: Sequence[FragmentoRecuperado]) -> str:
    """Arma el bloque CONTEXTO que se inserta en el prompt.

    Cada fragmento se rotula con su título, fecha de vigencia, tipo de fuente y
    puntaje, para que el modelo pueda citar con precisión y para que el agente
    entienda de dónde salió cada afirmación.

    Args:
        fragmentos: Fragmentos ya filtrados y reordenados.

    Returns:
        Texto del contexto, o una marca explícita de contexto vacío.
    """
    if not fragmentos:
        return "[SIN CONTEXTO RECUPERADO]"

    bloques: list[str] = []
    for indice, fragmento in enumerate(fragmentos, start=1):
        metadatos = fragmento.documento.metadata
        bloques.append(
            f"--- FRAGMENTO {indice} ---\n"
            f"Documento: {fragmento.titulo}\n"
            f"Archivo: {fragmento.nombre_documento}\n"
            f"Fuente: {metadatos.get('fuente', 'desconocida')}\n"
            f"Fecha de vigencia: {metadatos.get('fecha_vigencia', 's/f')}\n"
            f"Nivel de acceso: {metadatos.get('nivel_acceso', 'publico_interno')}\n"
            f"Relevancia: {fragmento.puntaje:.3f}\n"
            f"Contenido:\n{fragmento.documento.page_content}"
        )
    return "\n\n".join(bloques)


# ---------------------------------------------------------------------------
# Recuperador vectorial
# ---------------------------------------------------------------------------


def _ruta_str(ruta: Path | str) -> str:
    """Devuelve la ruta absoluta manejando rutas largas en Windows."""
    p = str(Path(ruta).resolve())
    if os.name == "nt" and len(p) >= 200 and not p.startswith("\\\\?\\"):
        return f"\\\\?\\{p}"
    return p


class RecuperadorVectorial:
    """Envoltura del índice FAISS con umbral, filtros y re-ranking.

    Attributes:
        ruta_indice: Carpeta donde está persistido el índice.
        top_k: Cantidad de fragmentos a devolver.
        umbral: Puntaje mínimo de relevancia.
    """

    def __init__(
        self,
        almacen: Any | None = None,
        ruta_indice: Path = config.DIR_INDICE_FAISS,
        top_k: int = config.TOP_K,
        umbral: float | None = None,
    ) -> None:
        """Inicializa el recuperador.

        Args:
            almacen: Vector store ya construido. Si es ``None``, se carga de disco
                la primera vez que se busca (útil para inyectar dobles en pruebas).
            ruta_indice: Carpeta del índice FAISS.
            top_k: Cantidad de fragmentos a devolver.
            umbral: Puntaje mínimo de relevancia.
        """
        self._almacen = almacen
        self.ruta_indice = Path(ruta_indice)
        self.top_k = top_k
        self.umbral = config.umbral_similitud() if umbral is None else umbral

    @property
    def almacen(self) -> Any:
        """Vector store FAISS, cargado de forma perezosa.

        Returns:
            Instancia de ``FAISS``.

        Raises:
            FileNotFoundError: Si el índice no fue construido todavía.
        """
        if self._almacen is None:
            self._almacen = self.cargar_indice(self.ruta_indice)
        return self._almacen

    @staticmethod
    def cargar_indice(ruta_indice: Path = config.DIR_INDICE_FAISS) -> Any:
        """Carga el índice FAISS persistido.

        Args:
            ruta_indice: Carpeta del índice.

        Returns:
            Instancia de ``FAISS``.

        Raises:
            FileNotFoundError: Si falta el índice.
        """
        ruta_faiss = _ruta_str(ruta_indice)
        if not (Path(ruta_faiss) / "index.faiss").exists():
            raise FileNotFoundError(
                f"No existe el índice FAISS en {ruta_indice}. "
                "Construilo primero con: python -m src.ingest"
            )
        if not config.indice_embeddings_compatible(Path(ruta_indice)):
            raise RuntimeError(
                "El índice FAISS está incompleto, no tiene metadatos de embeddings "
                "o fue creado con otro proveedor, modelo o dimensión. "
                "Reconstruilo con: python -m src.ingest"
            )
        from langchain_community.vectorstores import FAISS  # import diferido

        embeddings = config.crear_embeddings()
        almacen = FAISS.load_local(
            ruta_faiss,
            embeddings,
            allow_dangerous_deserialization=True,  # índice generado localmente
        )
        if almacen.index.d != config.DIMENSION_EMBEDDINGS:
            raise RuntimeError(
                "La dimensión real del índice FAISS no coincide con EMBEDDING_DIM. "
                "Reconstruilo con: python -m src.ingest"
            )
        return almacen

    def _buscar_crudo(
        self, consulta: str, k: int, filtro: dict[str, str] | None
    ) -> list[FragmentoRecuperado]:
        """Ejecuta la búsqueda por similitud contra FAISS.

        Args:
            consulta: Texto de la consulta.
            k: Cantidad de candidatos a pedir.
            filtro: Filtro de metadatos, o ``None``.

        Returns:
            Fragmentos con su puntaje de relevancia normalizado.
        """
        try:
            crudos = self.almacen.similarity_search_with_relevance_scores(
                consulta, k=k, filter=filtro
            )
        except TypeError:
            # Versiones que no aceptan el filtro por metadatos: se filtra después.
            crudos = self.almacen.similarity_search_with_relevance_scores(consulta, k=k)

        return [
            FragmentoRecuperado(documento=documento, puntaje=float(puntaje))
            for documento, puntaje in crudos
        ]

    def buscar(
        self,
        consulta: str,
        perfil: str = "agente",
        clasificacion: str | None = None,
    ) -> list[FragmentoRecuperado]:
        """Recupera los fragmentos pertinentes para una consulta.

        Orden de operaciones: enrutamiento -> búsqueda ampliada -> filtro por
        fuente y nivel de acceso -> umbral -> re-ranking por vigencia -> top_k.

        Se piden más candidatos de los necesarios (``top_k * 5``) porque el
        filtrado por metadatos y el umbral descartan resultados; sin ese margen,
        una consulta de perfil ``usuario_final`` podría quedarse sin contexto
        aunque el corpus lo tenga.

        Args:
            consulta: Pregunta del usuario.
            perfil: ``agente`` o ``usuario_final``.
            clasificacion: Fuerza la clasificación en vez de calcularla.

        Returns:
            Hasta ``top_k`` fragmentos, ordenados por pertinencia y vigencia.
        """
        clasificacion = clasificacion or clasificar_consulta(consulta)
        fuente = filtro_de_fuente(clasificacion)

        filtro: dict[str, str] | None = {"fuente": fuente} if fuente else None
        candidatos = self._buscar_crudo(consulta, k=self.top_k * 5, filtro=filtro)

        candidatos = filtrar_por_metadatos(candidatos, fuente=fuente, perfil=perfil)
        candidatos = aplicar_umbral(candidatos, self.umbral)
        candidatos = reordenar_por_vigencia(candidatos)
        return candidatos[: self.top_k]


# ---------------------------------------------------------------------------
# Conector SQL al ITSM y la CMDB
# ---------------------------------------------------------------------------

_PATRON_TICKET = re.compile(r"\b((?:INC|REQ)-\d{4}-\d{3,5})\b", re.IGNORECASE)
_PATRON_PRIORIDAD = re.compile(r"\bP([1-4])\b", re.IGNORECASE)
_PATRON_RUT = re.compile(r"\b\d{1,2}\.\d{3}\.\d{3}-[\dkK]\b|\b\d{7,8}-[\dkK]\b")


class ConectorITSM:
    """Consultas de solo lectura a la base SQLite del ITSM y la CMDB.

    Todas las consultas usan marcadores ``?``: no se interpola nunca texto del
    usuario en el SQL. La conexión se abre en modo solo lectura lógico (el
    conector no expone ningún método de escritura), coherente con la regla de que
    el asistente no ejecuta acciones.

    Attributes:
        ruta_bd: Ruta del archivo SQLite.
    """

    def __init__(self, ruta_bd: Path = config.RUTA_BD) -> None:
        """Inicializa el conector.

        Args:
            ruta_bd: Ruta de ``itsm.db``.
        """
        self.ruta_bd = Path(ruta_bd)

    def disponible(self) -> bool:
        """Indica si la base de datos existe.

        Returns:
            ``True`` si el archivo está creado.
        """
        return self.ruta_bd.exists()

    def _consultar(self, sql: str, parametros: Sequence[Any] = ()) -> list[dict[str, Any]]:
        """Ejecuta una consulta parametrizada y devuelve filas como diccionarios.

        Args:
            sql: Sentencia SQL con marcadores ``?``.
            parametros: Valores para los marcadores.

        Returns:
            Lista de filas. Vacía si la base no existe.
        """
        if not self.disponible():
            return []
        # Se abre por URI en modo solo lectura. ``as_uri`` resuelve el escapado de
        # rutas de Windows (unidades, espacios), que un f-string rompería.
        uri = f"{self.ruta_bd.resolve().as_uri()}?mode=ro"
        conexion = sqlite3.connect(uri, uri=True)
        try:
            conexion.row_factory = sqlite3.Row
            filas = conexion.execute(sql, tuple(parametros)).fetchall()
        finally:
            conexion.close()
        return [dict(fila) for fila in filas]

    def estado_de_ticket(self, id_ticket: str) -> dict[str, Any] | None:
        """Devuelve el estado y los datos de un ticket.

        Args:
            id_ticket: Identificador, por ejemplo ``INC-2026-0412``.

        Returns:
            Diccionario con los datos del ticket, o ``None`` si no existe.
        """
        filas = self._consultar(
            """
            SELECT t.id, t.asunto, t.descripcion, t.estado, t.prioridad,
                   t.categoria, c.nombre AS categoria_nombre, t.agente_asignado,
                   t.nivel_atencion, t.fecha_apertura, t.fecha_primera_respuesta,
                   t.fecha_cierre, t.solucion, t.activo_id,
                   u.nombre AS usuario, u.sucursal
            FROM tickets t
            JOIN usuarios u ON u.id = t.usuario_id
            JOIN categorias_servicio c ON c.codigo = t.categoria
            WHERE UPPER(t.id) = UPPER(?)
            """,
            (id_ticket,),
        )
        return filas[0] if filas else None

    def tickets_de_usuario(
        self, rut: str, estado: str | None = None, limite: int = 10
    ) -> list[dict[str, Any]]:
        """Lista los tickets de un usuario identificado por RUT.

        Args:
            rut: RUT con formato ``30.100.001-K``.
            estado: Filtra por estado (``abierto``, ``en curso``, ``escalado``,
                ``resuelto``). ``None`` devuelve todos.
            limite: Máximo de filas.

        Returns:
            Lista de tickets, del más reciente al más antiguo.
        """
        if estado is None:
            return self._consultar(
                """
                SELECT t.id, t.asunto, t.estado, t.prioridad, t.categoria,
                       t.fecha_apertura, t.fecha_cierre
                FROM tickets t
                JOIN usuarios u ON u.id = t.usuario_id
                WHERE u.rut = ?
                ORDER BY t.fecha_apertura DESC
                LIMIT ?
                """,
                (rut, limite),
            )
        return self._consultar(
            """
            SELECT t.id, t.asunto, t.estado, t.prioridad, t.categoria,
                   t.fecha_apertura, t.fecha_cierre
            FROM tickets t
            JOIN usuarios u ON u.id = t.usuario_id
            WHERE u.rut = ? AND t.estado = ?
            ORDER BY t.fecha_apertura DESC
            LIMIT ?
            """,
            (rut, estado, limite),
        )

    def sla_de_prioridad(self, prioridad: str) -> dict[str, Any] | None:
        """Devuelve los tiempos comprometidos de una prioridad.

        Args:
            prioridad: ``P1``, ``P2``, ``P3`` o ``P4``.

        Returns:
            Diccionario con los tiempos, o ``None`` si la prioridad no existe.
        """
        filas = self._consultar(
            """
            SELECT prioridad, nombre, primera_respuesta_min, resolucion_horas,
                   tipo_reloj, cumplimiento_minimo, descripcion
            FROM sla
            WHERE UPPER(prioridad) = UPPER(?)
            """,
            (prioridad,),
        )
        return filas[0] if filas else None

    def activo_de_usuario(self, rut: str) -> list[dict[str, Any]]:
        """Lista los activos de la CMDB asignados a un usuario.

        Args:
            rut: RUT del colaborador.

        Returns:
            Lista de activos asignados.
        """
        return self._consultar(
            """
            SELECT a.id, a.tipo, a.marca_modelo, a.numero_serie, a.hostname,
                   a.ip_asignada, a.sucursal, a.estado, a.fecha_alta
            FROM activos_cmdb a
            JOIN usuarios u ON u.id = a.usuario_id
            WHERE u.rut = ?
            ORDER BY a.id
            """,
            (rut,),
        )

    def usuario_por_rut(self, rut: str) -> dict[str, Any] | None:
        """Busca un colaborador por RUT.

        Args:
            rut: RUT con formato ``30.100.001-K``.

        Returns:
            Datos del usuario, o ``None``.
        """
        filas = self._consultar(
            """
            SELECT id, rut, nombre, cargo, sucursal, correo, telefono,
                   perfil_licencia, estado
            FROM usuarios
            WHERE rut = ?
            """,
            (rut,),
        )
        return filas[0] if filas else None

    def resumen_por_estado(self) -> list[dict[str, Any]]:
        """Cuenta los tickets agrupados por estado.

        Returns:
            Lista de ``{estado, cantidad}``.
        """
        return self._consultar(
            "SELECT estado, COUNT(*) AS cantidad FROM tickets "
            "GROUP BY estado ORDER BY estado"
        )


def detectar_entidades(consulta: str) -> dict[str, list[str]]:
    """Extrae identificadores estructurados presentes en la consulta.

    Args:
        consulta: Texto del usuario.

    Returns:
        Diccionario con las listas ``tickets``, ``prioridades`` y ``ruts``.
    """
    return {
        "tickets": [t.upper() for t in _PATRON_TICKET.findall(consulta)],
        "prioridades": [f"P{n}" for n in _PATRON_PRIORIDAD.findall(consulta)],
        "ruts": _PATRON_RUT.findall(consulta),
    }


def consultar_datos_estructurados(
    consulta: str, conector: ConectorITSM | None = None
) -> str:
    """Arma el bloque DATOS DEL ITSM con lo que se pueda resolver por SQL.

    Se dispara solo cuando la consulta menciona un identificador reconocible
    (ticket, prioridad o RUT). Si no hay nada que consultar devuelve cadena
    vacía, y el agente trabaja únicamente con el contexto documental.

    Args:
        consulta: Texto del usuario, todavía sin enmascarar.
        conector: Conector a usar. Si es ``None`` se crea uno por defecto.

    Returns:
        Texto formateado con los datos encontrados, o cadena vacía.
    """
    conector = conector or ConectorITSM()
    if not conector.disponible():
        return ""

    entidades = detectar_entidades(consulta)
    bloques: list[str] = []

    for id_ticket in entidades["tickets"][:3]:
        ticket = conector.estado_de_ticket(id_ticket)
        if ticket is None:
            bloques.append(f"Ticket {id_ticket}: no existe en el ITSM.")
            continue
        bloques.append(
            f"Ticket {ticket['id']} · {ticket['asunto']}\n"
            f"  Estado: {ticket['estado']} · Prioridad: {ticket['prioridad']} · "
            f"Categoría: {ticket['categoria']} ({ticket['categoria_nombre']})\n"
            f"  Atendido por: {ticket['agente_asignado']} (Nivel "
            f"{ticket['nivel_atencion']}) · Sucursal: {ticket['sucursal']}\n"
            f"  Apertura: {ticket['fecha_apertura']} · "
            f"Primera respuesta: {ticket['fecha_primera_respuesta'] or 'pendiente'} · "
            f"Cierre: {ticket['fecha_cierre'] or 'pendiente'}\n"
            f"  Solución registrada: {ticket['solucion'] or 'sin solución registrada'}"
        )

    for prioridad in dict.fromkeys(entidades["prioridades"]):
        sla = conector.sla_de_prioridad(prioridad)
        if sla is None:
            continue
        bloques.append(
            f"SLA {sla['prioridad']} · {sla['nombre']}\n"
            f"  Primera respuesta: {sla['primera_respuesta_min']} minutos · "
            f"Resolución objetivo: {sla['resolucion_horas']} horas "
            f"{sla['tipo_reloj']}\n"
            f"  Cumplimiento mínimo mensual: {sla['cumplimiento_minimo'] * 100:.0f} %\n"
            f"  Aplica a: {sla['descripcion']}"
        )

    for rut in entidades["ruts"][:2]:
        usuario = conector.usuario_por_rut(rut)
        if usuario is None:
            bloques.append(f"RUT {rut}: sin registro en el directorio del ITSM.")
            continue
        activos = conector.activo_de_usuario(rut)
        tickets = conector.tickets_de_usuario(rut, limite=5)
        detalle_activos = (
            "; ".join(f"{a['id']} {a['tipo']} ({a['estado']})" for a in activos)
            or "sin activos asignados"
        )
        detalle_tickets = (
            "; ".join(f"{t['id']} [{t['estado']}]" for t in tickets)
            or "sin tickets registrados"
        )
        bloques.append(
            f"Colaborador {usuario['nombre']} · {usuario['cargo']} · "
            f"{usuario['sucursal']}\n"
            f"  Cuenta: {usuario['estado']} · Licencia: {usuario['perfil_licencia']}\n"
            f"  Activos en CMDB: {detalle_activos}\n"
            f"  Últimos tickets: {detalle_tickets}"
        )

    return "\n\n".join(bloques)
