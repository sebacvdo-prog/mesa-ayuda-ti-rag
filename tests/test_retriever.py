"""Pruebas del recuperador: enrutador, umbral, re-ranking y conector SQL.

El índice FAISS se reemplaza por un doble en memoria, así que estas pruebas no
calculan embeddings ni llaman a ninguna API. La base SQLite sí se crea de verdad,
en un directorio temporal, porque el punto de las pruebas del conector es que las
consultas parametrizadas se comporten como en producción.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from langchain_core.documents import Document

from src import config, retriever

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "data"))
import seed_db  # noqa: E402 - se importa tras ajustar el path


# ---------------------------------------------------------------------------
# Utilidades de prueba
# ---------------------------------------------------------------------------


def construir_fragmento(
    texto: str = "contenido",
    puntaje: float = 0.9,
    documento: str = "kb.md",
    fuente: str = "interna",
    fecha: str = "2026-01-01",
    nivel: str = "publico_interno",
) -> retriever.FragmentoRecuperado:
    """Crea un fragmento sintético con los metadatos que usa el pipeline.

    Args:
        texto: Contenido del fragmento.
        puntaje: Relevancia asignada.
        documento: Nombre del archivo de origen.
        fuente: ``interna`` o ``externa``.
        fecha: Fecha de vigencia en formato ISO.
        nivel: Nivel de acceso del documento.

    Returns:
        Fragmento listo para usar en las aserciones.
    """
    return retriever.FragmentoRecuperado(
        documento=Document(
            page_content=texto,
            metadata={
                "documento": documento,
                "titulo": f"Título de {documento}",
                "fuente": fuente,
                "fecha_vigencia": fecha,
                "nivel_acceso": nivel,
            },
        ),
        puntaje=puntaje,
    )


class AlmacenFalso:
    """Doble del vector store: devuelve resultados fijos y registra el filtro."""

    def __init__(self, resultados: list[tuple[Document, float]]) -> None:
        """Guarda los resultados que devolverá la búsqueda.

        Args:
            resultados: Pares ``(documento, puntaje)``.
        """
        self.resultados = resultados
        self.filtros_recibidos: list[Any] = []

    def similarity_search_with_relevance_scores(
        self, consulta: str, k: int = 4, filter: Any = None  # noqa: A002
    ) -> list[tuple[Document, float]]:
        """Devuelve los resultados preconfigurados.

        Args:
            consulta: Texto de la consulta (se ignora).
            k: Cantidad de resultados pedidos.
            filter: Filtro de metadatos, que se registra para poder afirmarlo.

        Returns:
            Los primeros ``k`` resultados configurados.
        """
        self.filtros_recibidos.append(filter)
        return self.resultados[:k]


# ---------------------------------------------------------------------------
# Enrutador
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("consulta", "esperado"),
    [
        ("¿Cuál es el SLA de un ticket P2 según el catálogo?", "interna"),
        ("¿Qué dice el aviso del CSIRT sobre la campaña de fatiga de MFA?", "externa"),
        ("¿Qué significa el código de error del cliente -7200 de FortiClient?", "externa"),
        ("El aviso del CSIRT contradice el procedimiento interno de escalamiento", "mixta"),
        ("Se cayó todo", "mixta"),
    ],
)
def test_clasificar_consulta(consulta: str, esperado: str) -> None:
    """El enrutador reconoce consultas internas, externas y mixtas."""
    assert retriever.clasificar_consulta(consulta) == esperado


def test_filtro_de_fuente_no_filtra_en_consultas_mixtas() -> None:
    """Una consulta mixta no debe restringir el índice."""
    assert retriever.filtro_de_fuente("mixta") is None
    assert retriever.filtro_de_fuente("interna") == "interna"
    assert retriever.filtro_de_fuente("externa") == "externa"


# ---------------------------------------------------------------------------
# Umbral
# ---------------------------------------------------------------------------


def test_aplicar_umbral_descarta_lo_que_no_llega() -> None:
    """El umbral de 0,72 descarta los fragmentos por debajo y conserva el resto."""
    fragmentos = [
        construir_fragmento(puntaje=0.91, documento="a.md"),
        construir_fragmento(puntaje=0.72, documento="b.md"),
        construir_fragmento(puntaje=0.7199, documento="c.md"),
        construir_fragmento(puntaje=0.10, documento="d.md"),
    ]
    conservados = retriever.aplicar_umbral(fragmentos, config.UMBRAL_SIMILITUD)

    assert [f.nombre_documento for f in conservados] == ["a.md", "b.md"]


def test_umbral_puede_dejar_el_contexto_vacio() -> None:
    """Si nada alcanza el umbral, el contexto queda vacío en vez de traer ruido."""
    fragmentos = [construir_fragmento(puntaje=0.4), construir_fragmento(puntaje=0.5)]

    assert retriever.aplicar_umbral(fragmentos, umbral=0.72) == []
    assert retriever.formatear_contexto([]) == "[SIN CONTEXTO RECUPERADO]"


# ---------------------------------------------------------------------------
# Re-ranking por vigencia
# ---------------------------------------------------------------------------


def test_reordenar_prioriza_el_documento_mas_reciente_a_igual_pertinencia() -> None:
    """Con puntajes equivalentes, manda la fecha de vigencia más nueva."""
    antiguo = construir_fragmento(
        puntaje=0.88, documento="kb_conectividad_vpn.md", fecha="2026-02-10"
    )
    reciente = construir_fragmento(
        puntaje=0.86, documento="csirt_avisos_seguridad.md", fecha="2026-07-28"
    )
    ordenados = retriever.reordenar_por_vigencia([antiguo, reciente], margen=0.05)

    assert [f.nombre_documento for f in ordenados] == [
        "csirt_avisos_seguridad.md",
        "kb_conectividad_vpn.md",
    ]


def test_reordenar_respeta_el_puntaje_cuando_la_diferencia_es_grande() -> None:
    """Una diferencia de pertinencia mayor al margen no se corrige por vigencia."""
    muy_pertinente = construir_fragmento(
        puntaje=0.95, documento="kb_conectividad_vpn.md", fecha="2026-02-10"
    )
    poco_pertinente = construir_fragmento(
        puntaje=0.75, documento="csirt_avisos_seguridad.md", fecha="2026-07-28"
    )
    ordenados = retriever.reordenar_por_vigencia(
        [poco_pertinente, muy_pertinente], margen=0.05
    )

    assert ordenados[0].nombre_documento == "kb_conectividad_vpn.md"


def test_reordenar_documento_sin_fecha_no_desplaza_a_uno_vigente() -> None:
    """Una fecha ausente se trata como la más antigua posible."""
    sin_fecha = construir_fragmento(puntaje=0.90, documento="sin_fecha.md", fecha="")
    con_fecha = construir_fragmento(puntaje=0.89, documento="vigente.md", fecha="2026-05-05")
    ordenados = retriever.reordenar_por_vigencia([sin_fecha, con_fecha])

    assert ordenados[0].nombre_documento == "vigente.md"


# ---------------------------------------------------------------------------
# Filtro por nivel de acceso
# ---------------------------------------------------------------------------


def test_filtrar_por_metadatos_aplica_perfil_y_fuente() -> None:
    """El usuario final no ve documentos restringidos; el filtro de fuente actúa."""
    publico = construir_fragmento(documento="publico.md", nivel="publico_interno")
    restringido = construir_fragmento(documento="restringido.md", nivel="restringido_agentes")
    externo = construir_fragmento(documento="externo.md", fuente="externa")
    todos = [publico, restringido, externo]

    como_agente = retriever.filtrar_por_metadatos(todos, perfil="agente")
    assert len(como_agente) == 3

    como_usuario = retriever.filtrar_por_metadatos(todos, perfil="usuario_final")
    assert [f.nombre_documento for f in como_usuario] == ["publico.md", "externo.md"]

    solo_internos = retriever.filtrar_por_metadatos(todos, fuente="interna", perfil="agente")
    assert [f.nombre_documento for f in solo_internos] == ["publico.md", "restringido.md"]


# ---------------------------------------------------------------------------
# Recuperador completo (con doble del vector store)
# ---------------------------------------------------------------------------


def test_buscar_aplica_umbral_perfil_y_top_k_sin_llamar_a_la_api() -> None:
    """La búsqueda integra filtro, umbral, re-ranking y recorte a top_k."""
    documentos = [
        (construir_fragmento(documento="restringido.md", nivel="restringido_agentes").documento, 0.95),
        (construir_fragmento(documento="reciente.md", fecha="2026-07-28").documento, 0.88),
        (construir_fragmento(documento="antiguo.md", fecha="2026-01-01").documento, 0.87),
        (construir_fragmento(documento="irrelevante.md").documento, 0.30),
    ]
    almacen = AlmacenFalso(documentos)
    recuperador = retriever.RecuperadorVectorial(almacen=almacen, top_k=2)

    resultados = recuperador.buscar("¿Cómo restablezco una cuenta?", perfil="usuario_final")

    nombres = [f.nombre_documento for f in resultados]
    assert "restringido.md" not in nombres, "el perfil usuario_final no debe verlo"
    assert "irrelevante.md" not in nombres, "no supera el umbral"
    assert nombres == ["reciente.md", "antiguo.md"]
    assert len(resultados) <= 2


def test_buscar_pasa_el_filtro_de_fuente_al_indice() -> None:
    """Una consulta externa filtra el índice por el metadato fuente."""
    almacen = AlmacenFalso([(construir_fragmento(fuente="externa").documento, 0.9)])
    recuperador = retriever.RecuperadorVectorial(almacen=almacen)

    recuperador.buscar("¿Qué dice el aviso del CSIRT sobre la campaña de MFA?")

    assert almacen.filtros_recibidos[-1] == {"fuente": "externa"}


# ---------------------------------------------------------------------------
# Conector SQL
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def conector(tmp_path_factory: pytest.TempPathFactory) -> retriever.ConectorITSM:
    """Crea una base ITSM real en un directorio temporal.

    Args:
        tmp_path_factory: Fábrica de directorios temporales de pytest.

    Returns:
        Conector apuntado a la base recién creada.
    """
    ruta = tmp_path_factory.mktemp("itsm") / "itsm.db"
    seed_db.crear_base(ruta)
    return retriever.ConectorITSM(ruta)


def test_semilla_crea_los_volumenes_esperados(conector: retriever.ConectorITSM) -> None:
    """La base semilla tiene 12 usuarios, 40 tickets y 20 activos."""
    assert len(conector._consultar("SELECT id FROM usuarios")) == 12
    assert len(conector._consultar("SELECT id FROM tickets")) == 40
    assert len(conector._consultar("SELECT id FROM activos_cmdb")) == 20

    estados = {fila["estado"] for fila in conector.resumen_por_estado()}
    assert estados == {"abierto", "en curso", "escalado", "resuelto"}


@pytest.mark.parametrize(
    ("numero", "digito"),
    [(11111111, "1"), (12345678, "5"), (1, "9"), (7, "8")],
)
def test_digito_verificador_de_rut(numero: int, digito: str) -> None:
    """El dígito verificador coincide con el algoritmo módulo 11 estándar."""
    assert seed_db.digito_verificador(numero) == digito


def test_formato_de_rut_ficticio() -> None:
    """Los RUT del corpus llevan puntos, guion y un dígito verificador válido."""
    rut = seed_db.formatear_rut(30100001)

    assert rut.startswith("30.100.001-")
    assert rut[-1] in "0123456789K"


def test_estado_de_ticket_devuelve_datos_completos(conector: retriever.ConectorITSM) -> None:
    """Se puede consultar el estado de un ticket por su identificador."""
    ticket = conector.estado_de_ticket("INC-2026-0412")

    assert ticket is not None
    assert ticket["estado"] == "escalado"
    assert ticket["prioridad"] == "P1"
    assert ticket["categoria"] == "CAT-MOV"
    assert conector.estado_de_ticket("INC-9999-9999") is None


def test_sla_por_prioridad(conector: retriever.ConectorITSM) -> None:
    """Los tiempos comprometidos coinciden con el catálogo de servicios."""
    sla = conector.sla_de_prioridad("P2")

    assert sla is not None
    assert sla["primera_respuesta_min"] == 30
    assert sla["resolucion_horas"] == 8
    assert conector.sla_de_prioridad("P9") is None


def test_activo_asignado_a_un_usuario(conector: retriever.ConectorITSM) -> None:
    """La CMDB devuelve los activos del colaborador consultado."""
    rut = seed_db.formatear_rut(30100002)
    activos = conector.activo_de_usuario(rut)

    assert [a["id"] for a in activos] == ["ACT-0002"]
    assert activos[0]["tipo"] == "Terminal móvil"
    assert activos[0]["hostname"] == "MOV-CD-012"
    # Un RUT sin activos no rompe: devuelve lista vacía.
    assert conector.activo_de_usuario(seed_db.formatear_rut(30999999)) == []


def test_consultas_parametrizadas_resisten_inyeccion(
    conector: retriever.ConectorITSM,
) -> None:
    """Un intento de inyección se trata como dato, no como SQL."""
    malicioso = "INC-2026-0412' OR '1'='1"

    assert conector.estado_de_ticket(malicioso) is None
    # La tabla sigue intacta después del intento.
    assert len(conector._consultar("SELECT id FROM tickets")) == 40


def test_detectar_entidades_en_la_consulta() -> None:
    """Se reconocen tickets, prioridades y RUT dentro del texto libre."""
    entidades = retriever.detectar_entidades(
        "El ticket INC-2026-0412 del RUT 30.100.002-3 quedó como P1"
    )

    assert entidades["tickets"] == ["INC-2026-0412"]
    assert entidades["prioridades"] == ["P1"]
    assert entidades["ruts"] == ["30.100.002-3"]


def test_datos_estructurados_se_arman_solo_si_hay_identificadores(
    conector: retriever.ConectorITSM,
) -> None:
    """Sin identificadores no se consulta el ITSM; con uno, se devuelve su ficha."""
    assert retriever.consultar_datos_estructurados("¿Cómo conecto la VPN?", conector) == ""

    bloque = retriever.consultar_datos_estructurados(
        "¿En qué estado está el ticket INC-2026-0412?", conector
    )
    assert "INC-2026-0412" in bloque
    assert "escalado" in bloque
