"""Guardarraíles: enmascarado de datos sensibles, política y control de acceso.

Cuatro controles, en el orden en que los aplica el agente:

1. **Alcance.** Se rechaza lo que no es de la mesa de ayuda TI.
2. **Credenciales.** Se bloquea toda solicitud de contraseñas, claves de
   recuperación, PIN, tokens o códigos de verificación.
3. **Nivel de acceso.** El perfil ``usuario_final`` solo ve documentos marcados
   ``publico_interno``; el perfil ``agente`` ve todo el corpus.
4. **Enmascarado.** RUT, correos, teléfonos, direcciones IP y nombres de host se
   reemplazan por marcas **antes** de la llamada al modelo, nunca después.

El punto 4 es el que suele hacerse mal: enmascarar la respuesta en vez de la
entrada deja los datos igualmente enviados al proveedor. Acá se enmascara la
consulta, el contexto recuperado y los datos del ITSM antes de construir el
mensaje que sale del proceso.
"""

from __future__ import annotations

import re
from typing import Iterable, NamedTuple

from src import config

# ---------------------------------------------------------------------------
# Marcas de reemplazo
# ---------------------------------------------------------------------------

MARCA_RUT: str = "[RUT]"
MARCA_CORREO: str = "[CORREO]"
MARCA_TELEFONO: str = "[TELEFONO]"
MARCA_IP: str = "[IP]"
MARCA_HOST: str = "[HOST]"

# ---------------------------------------------------------------------------
# Patrones
# ---------------------------------------------------------------------------

PATRON_CORREO = re.compile(
    r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)
"""Correo electrónico. Se aplica primero para que el dominio no quede suelto."""

PATRON_RUT = re.compile(
    r"\b\d{1,2}\.\d{3}\.\d{3}-[\dkK]\b|\b\d{7,8}-[\dkK]\b"
)
"""RUT chileno con o sin puntos, siempre con guion y dígito verificador."""

PATRON_IP = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)\.){3}"
    r"(?:25[0-5]|2[0-4]\d|1\d{2}|[1-9]?\d)\b"
)
"""Dirección IPv4. La política exige enmascarar también las privadas."""

PATRON_HOSTNAME = re.compile(
    r"\b(?:NB|PC|MOV|SRV|IMP|FW|AP|SW|RTR|TERM)-[A-Z0-9]{2,8}-\d{2,4}\b"
)
"""Nombre de equipo según la convención de la CMDB (por ejemplo NB-STGO-041).

Deliberadamente **no** es un patrón genérico ``XXX-YYY-00``: uno así también
capturaría los códigos documentales (KB-ACC-01, CAT-SLA-00, POL-SEG-01) y
destruiría las citas, que son justamente lo que el sistema debe conservar.
"""

PATRON_FQDN = re.compile(r"\b[a-z0-9][a-z0-9-]*\.aconcagualog\.cl\b", re.IGNORECASE)
"""Nombre de host del dominio corporativo (se aplica después del correo)."""

PATRON_TELEFONO = re.compile(
    r"\+56\s?9\s?\d{4}\s?\d{4}\b|\b9\s?\d{4}\s?\d{4}\b|\b\+?56\s?2\s?\d{4}\s?\d{4}\b"
)
"""Teléfono chileno, móvil o fijo, con o sin código de país."""

# ---------------------------------------------------------------------------
# Solicitudes de credenciales
# ---------------------------------------------------------------------------

_SUSTANTIVOS_CREDENCIAL = (
    r"contrase[ñn]a|clave|password|pin|token|credencial(?:es)?|"
    r"c[oó]digo\s+de\s+verificaci[oó]n|c[oó]digo\s+otp"
)

PATRONES_CREDENCIALES: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"\b(?:dame|dime|d[ií]game|entr[eé]game|env[ií]ame|p[aá]same|mu[eé]strame|"
        r"comp[aá]rteme|comparte|ind[ií]came|dar|decir|entregar|enviar|pasar|"
        r"mostrar|revelar|filtrar|escribir|generar|generame|gen[eé]rame)"
        r"(?:\s+me)?\s+(?:la|el|mi|su|una|un|los|las)?\s*"
        rf"(?:{_SUSTANTIVOS_CREDENCIAL})\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\bcu[aá]l\s+es\s+(?:la|el|mi|su)\s+(?:{_SUSTANTIVOS_CREDENCIAL})\b",
        re.IGNORECASE,
    ),
    re.compile(
        rf"\bnecesito\s+(?:la|el|los|las)\s+(?:{_SUSTANTIVOS_CREDENCIAL})\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bclave\s+de\s+recuperaci[oó]n\b|\bbitlocker\b|"
        r"\b(?:clave|credencial)(?:es)?\s+temporal(?:es)?\s+(?:de|del|para)\b",
        re.IGNORECASE,
    ),
)
"""Patrones que identifican un pedido del **valor** de una credencial.

No confundir con una consulta legítima sobre el procedimiento: "cómo restablezco
mi contraseña" o "el usuario olvidó su contraseña" no coinciden con ninguno de
estos patrones, y deben seguir su curso normal.
"""

MENSAJE_CREDENCIALES: str = (
    "No puedo entregar contraseñas, claves de recuperación, PIN, tokens ni códigos "
    "de verificación por ningún canal. La Política de Seguridad TI (POL-SEG-01, "
    "sección 3) lo prohíbe de forma absoluta, sin excepción por urgencia ni por "
    "instrucción de una jefatura.\n\n"
    "Lo que corresponde hacer:\n"
    "1. Ofrecer al usuario el portal de autoservicio de contraseña.\n"
    "2. Si el autoservicio no está disponible, verificar la identidad del titular "
    "con al menos dos datos contrastables contra el directorio.\n"
    "3. Escalar a Nivel 2 para que genere la credencial temporal y la entregue al "
    "propio titular por llamada al teléfono registrado o de forma presencial.\n\n"
    "Fuente: [POL-SEG-01 · Política de Seguridad de la Información TI · 2026-03-01; "
    "KB-ACC-01 · Cuentas y accesos · 2026-04-20]"
)

# ---------------------------------------------------------------------------
# Alcance
# ---------------------------------------------------------------------------

TERMINOS_DEL_DOMINIO: tuple[str, ...] = (
    "ticket", "sla", "vpn", "correo", "outlook", "teams", "onedrive", "licencia",
    "contraseña", "contrasena", "clave", "cuenta", "acceso", "usuario", "bloqueo",
    "bloqueada", "terminal", "intune", "dispositivo", "equipo", "notebook",
    "impresora", "red", "wifi", "wi-fi", "conectividad", "certificado", "error",
    "escalamiento", "escalar", "nivel 2", "nivel 1", "prioridad", "incidente",
    "mesa de ayuda", "soporte", "sucursal", "cmdb", "activo", "erp", "buzón",
    "buzon", "sincroniza", "autenticación", "autenticacion", "segundo factor",
    "mfa", "phishing", "seguridad", "política", "politica", "procedimiento",
    "kb-", "cat-", "pol-", "inc-", "req-", "microsoft", "fortinet", "csirt",
    "conductor", "ruta", "enrolamiento", "licencias", "directorio",
)

TERMINOS_FUERA_DE_ALCANCE: tuple[str, ...] = (
    "receta", "cocina", "fútbol", "futbol", "poema", "poesía", "poesia", "chiste",
    "horóscopo", "horoscopo", "bitcoin", "criptomoneda", "apuesta", "casino",
    "novia", "cita romántica", "cita romantica", "película", "pelicula", "netflix",
    "vacaciones", "dieta", "entrenamiento de gimnasio", "tarea de matemáticas",
    "tarea de matematicas", "ensayo de historia", "letra de canción",
    "letra de cancion", "cuento infantil", "consejo médico", "consejo medico",
)

MENSAJE_FUERA_DE_ALCANCE: str = (
    "Esa consulta está fuera del ámbito de la mesa de ayuda TI de Aconcagua "
    "Logística. Puedo ayudarte con cuentas y accesos, correo y ofimática "
    "Microsoft 365, conectividad y VPN, terminales móviles en ruta, ERP de "
    "transporte, impresión, SLA del catálogo de servicios y política de seguridad."
)


# ---------------------------------------------------------------------------
# Enmascarado
# ---------------------------------------------------------------------------


class ResultadoEnmascarado(NamedTuple):
    """Salida del enmascarado.

    Attributes:
        texto: Texto con las marcas aplicadas.
        conteos: Cuántas ocurrencias se reemplazaron por tipo de dato.
    """

    texto: str
    conteos: dict[str, int]


def enmascarar(texto: str, incluir_fqdn: bool = True) -> ResultadoEnmascarado:
    """Reemplaza datos personales, IP y nombres de host por marcas.

    El orden importa: primero el correo (para que su dominio no se confunda con
    un host), después RUT, IP, host y por último el teléfono, cuyo patrón es el
    más laxo y podría morder cifras ya reemplazadas.

    Args:
        texto: Texto a enmascarar.
        incluir_fqdn: Si también se enmascaran los nombres de host del dominio
            corporativo (``vpn.aconcagualog.cl``).

    Returns:
        :class:`ResultadoEnmascarado` con el texto y el conteo por tipo.
    """
    conteos: dict[str, int] = {}

    def _reemplazar(patron: re.Pattern[str], marca: str, etiqueta: str, actual: str) -> str:
        nuevo, cantidad = patron.subn(marca, actual)
        if cantidad:
            conteos[etiqueta] = conteos.get(etiqueta, 0) + cantidad
        return nuevo

    resultado = texto
    resultado = _reemplazar(PATRON_CORREO, MARCA_CORREO, "correo", resultado)
    resultado = _reemplazar(PATRON_RUT, MARCA_RUT, "rut", resultado)
    resultado = _reemplazar(PATRON_IP, MARCA_IP, "ip", resultado)
    resultado = _reemplazar(PATRON_HOSTNAME, MARCA_HOST, "hostname", resultado)
    if incluir_fqdn:
        resultado = _reemplazar(PATRON_FQDN, MARCA_HOST, "hostname", resultado)
    resultado = _reemplazar(PATRON_TELEFONO, MARCA_TELEFONO, "telefono", resultado)

    return ResultadoEnmascarado(resultado, conteos)


def enmascarar_texto(texto: str) -> str:
    """Atajo que devuelve solo el texto enmascarado.

    Args:
        texto: Texto a enmascarar.

    Returns:
        Texto con las marcas aplicadas.
    """
    return enmascarar(texto).texto


def contiene_datos_sensibles(texto: str) -> bool:
    """Indica si el texto todavía tiene datos que deberían enmascararse.

    Sirve como aserción de seguridad antes de llamar al modelo.

    Args:
        texto: Texto a revisar.

    Returns:
        ``True`` si queda al menos un dato sensible sin enmascarar.
    """
    return bool(enmascarar(texto).conteos)


# ---------------------------------------------------------------------------
# Política
# ---------------------------------------------------------------------------


def solicita_credenciales(texto: str) -> bool:
    """Detecta si la consulta pide el valor de una credencial.

    Args:
        texto: Consulta del usuario.

    Returns:
        ``True`` si hay que bloquear la consulta.
    """
    return any(patron.search(texto) for patron in PATRONES_CREDENCIALES)


def esta_fuera_de_alcance(texto: str) -> bool:
    """Decide si la consulta escapa al ámbito de la mesa de ayuda TI.

    Criterio conservador: se rechaza solo cuando aparece un término claramente
    ajeno **y** no hay ningún término del dominio. Así una pregunta de seguimiento
    corta ("y si eso no funciona?") nunca se rechaza por error.

    Args:
        texto: Consulta del usuario.

    Returns:
        ``True`` si la consulta debe rechazarse por estar fuera de alcance.
    """
    minusculas = texto.lower()
    hay_ajeno = any(termino in minusculas for termino in TERMINOS_FUERA_DE_ALCANCE)
    hay_dominio = any(termino in minusculas for termino in TERMINOS_DEL_DOMINIO)
    return hay_ajeno and not hay_dominio


def niveles_visibles(perfil: str) -> tuple[str, ...]:
    """Niveles de acceso documental que puede ver un perfil.

    Args:
        perfil: ``agente`` o ``usuario_final``.

    Returns:
        Tupla con los valores admitidos del metadato ``nivel_acceso``.
    """
    if perfil == "agente":
        return config.NIVELES_ACCESO
    return ("publico_interno",)


def puede_ver(nivel_acceso: str, perfil: str) -> bool:
    """Indica si un perfil puede ver un documento de cierto nivel de acceso.

    Args:
        nivel_acceso: Metadato del documento.
        perfil: Perfil de quien consulta.

    Returns:
        ``True`` si el documento es visible para ese perfil.
    """
    return nivel_acceso in niveles_visibles(perfil)


def normalizar_perfil(perfil: str) -> str:
    """Valida el perfil y cae al más restrictivo si no se reconoce.

    Args:
        perfil: Perfil declarado por la interfaz.

    Returns:
        ``agente`` o ``usuario_final``.
    """
    perfil = (perfil or "").strip().lower()
    return perfil if perfil in config.PERFILES_VALIDOS else "usuario_final"


# ---------------------------------------------------------------------------
# Evaluación integral de la consulta
# ---------------------------------------------------------------------------


class VeredictoGuardarrail(NamedTuple):
    """Resultado de aplicar los guardarraíles de entrada.

    Attributes:
        permitida: Si la consulta puede continuar hacia el pipeline RAG.
        motivo: Etiqueta corta del bloqueo (``credenciales``, ``fuera_de_alcance``
            o ``ok``), útil para las trazas y las métricas.
        mensaje: Respuesta lista para mostrar cuando la consulta se bloquea.
    """

    permitida: bool
    motivo: str
    mensaje: str


def evaluar_consulta(consulta: str) -> VeredictoGuardarrail:
    """Aplica los controles de entrada sobre la consulta del usuario.

    El orden no es casual: primero credenciales, porque un pedido de contraseña
    disfrazado de tema ajeno debe bloquearse como credencial y no como fuera de
    alcance.

    Args:
        consulta: Texto crudo del usuario.

    Returns:
        :class:`VeredictoGuardarrail` con la decisión y el mensaje asociado.
    """
    if solicita_credenciales(consulta):
        return VeredictoGuardarrail(False, "credenciales", MENSAJE_CREDENCIALES)
    if esta_fuera_de_alcance(consulta):
        return VeredictoGuardarrail(False, "fuera_de_alcance", MENSAJE_FUERA_DE_ALCANCE)
    return VeredictoGuardarrail(True, "ok", "")


def filtrar_documentos_por_perfil(
    documentos: Iterable[object], perfil: str, atributo: str = "nivel_acceso"
) -> list[object]:
    """Filtra objetos con metadatos según el nivel de acceso del perfil.

    Acepta tanto ``Document`` de LangChain como diccionarios de metadatos, para
    poder usarse desde el retriever y desde las pruebas sin adaptadores.

    Args:
        documentos: Objetos a filtrar.
        perfil: Perfil de quien consulta.
        atributo: Nombre de la clave de nivel de acceso.

    Returns:
        Lista con los objetos visibles para el perfil.
    """
    permitidos = niveles_visibles(perfil)
    visibles: list[object] = []
    for documento in documentos:
        metadatos = getattr(documento, "metadata", documento)
        if not isinstance(metadatos, dict):
            continue
        if metadatos.get(atributo, "publico_interno") in permitidos:
            visibles.append(documento)
    return visibles
