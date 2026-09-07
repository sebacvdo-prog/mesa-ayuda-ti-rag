"""Crea y puebla ``data/itsm.db``, la base SQLite que simula el ITSM y la CMDB.

La base reemplaza a la plataforma real de gestión de servicios: **no se conecta a
ningún sistema productivo**. Contiene cinco tablas (``usuarios``, ``tickets``,
``categorias_servicio``, ``sla`` y ``activos_cmdb``) que el asistente consulta por
SQL parametrizado, nunca por búsqueda vectorial.

Los datos son ficticios:

* Los RUT usan números del tramo 30.000.000 en adelante, que no está asignado en
  Chile, y su dígito verificador se **calcula en código** con el algoritmo módulo 11,
  de modo que son formalmente válidos pero no corresponden a ninguna persona.
* Las direcciones IP pertenecen a rangos privados (RFC 1918).
* Los correos usan el dominio interno de ejemplo ``aconcagualog.cl``.

Uso:
    python data/seed_db.py
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

RUTA_BD: Path = Path(__file__).resolve().parent / "itsm.db"


# ---------------------------------------------------------------------------
# Utilidades de RUT
# ---------------------------------------------------------------------------


def digito_verificador(numero: int) -> str:
    """Calcula el dígito verificador de un RUT chileno con el algoritmo módulo 11.

    Args:
        numero: Parte numérica del RUT, sin puntos ni dígito verificador.

    Returns:
        El dígito verificador como texto: un dígito del 0 al 9, o ``K``.
    """
    suma = 0
    multiplicador = 2
    for digito in reversed(str(numero)):
        suma += int(digito) * multiplicador
        multiplicador = 2 if multiplicador == 7 else multiplicador + 1
    resto = 11 - (suma % 11)
    if resto == 11:
        return "0"
    if resto == 10:
        return "K"
    return str(resto)


def formatear_rut(numero: int) -> str:
    """Devuelve un RUT ficticio con puntos y dígito verificador válido.

    Args:
        numero: Parte numérica del RUT.

    Returns:
        RUT en formato ``30.100.001-K``.
    """
    return f"{numero:,}".replace(",", ".") + "-" + digito_verificador(numero)


# ---------------------------------------------------------------------------
# Definición del esquema
# ---------------------------------------------------------------------------

ESQUEMA: tuple[str, ...] = (
    """
    CREATE TABLE usuarios (
        id              INTEGER PRIMARY KEY,
        rut             TEXT    NOT NULL UNIQUE,
        nombre          TEXT    NOT NULL,
        cargo           TEXT    NOT NULL,
        sucursal        TEXT    NOT NULL,
        correo          TEXT    NOT NULL UNIQUE,
        telefono        TEXT    NOT NULL,
        perfil_licencia TEXT    NOT NULL CHECK (perfil_licencia IN ('E1', 'E3')),
        estado          TEXT    NOT NULL CHECK (estado IN ('activo', 'suspendido', 'baja')),
        fecha_ingreso   TEXT    NOT NULL
    )
    """,
    """
    CREATE TABLE categorias_servicio (
        codigo         TEXT PRIMARY KEY,
        nombre         TEXT NOT NULL,
        descripcion    TEXT NOT NULL,
        prioridad_base TEXT NOT NULL REFERENCES sla (prioridad)
    )
    """,
    """
    CREATE TABLE sla (
        prioridad             TEXT PRIMARY KEY,
        nombre                TEXT    NOT NULL,
        primera_respuesta_min INTEGER NOT NULL,
        resolucion_horas      INTEGER NOT NULL,
        tipo_reloj            TEXT    NOT NULL,
        cumplimiento_minimo   REAL    NOT NULL,
        descripcion           TEXT    NOT NULL
    )
    """,
    """
    CREATE TABLE activos_cmdb (
        id              TEXT PRIMARY KEY,
        tipo            TEXT NOT NULL,
        marca_modelo    TEXT NOT NULL,
        numero_serie    TEXT NOT NULL UNIQUE,
        usuario_id      INTEGER REFERENCES usuarios (id),
        sucursal        TEXT NOT NULL,
        ip_asignada     TEXT,
        hostname        TEXT NOT NULL UNIQUE,
        estado          TEXT NOT NULL,
        fecha_alta      TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE tickets (
        id                     TEXT PRIMARY KEY,
        usuario_id             INTEGER NOT NULL REFERENCES usuarios (id),
        categoria              TEXT    NOT NULL REFERENCES categorias_servicio (codigo),
        asunto                 TEXT    NOT NULL,
        descripcion            TEXT    NOT NULL,
        prioridad              TEXT    NOT NULL REFERENCES sla (prioridad),
        estado                 TEXT    NOT NULL
                               CHECK (estado IN ('abierto', 'en curso', 'escalado', 'resuelto')),
        canal                  TEXT    NOT NULL,
        agente_asignado        TEXT    NOT NULL,
        nivel_atencion         INTEGER NOT NULL,
        fecha_apertura         TEXT    NOT NULL,
        fecha_primera_respuesta TEXT,
        fecha_cierre           TEXT,
        activo_id              TEXT REFERENCES activos_cmdb (id),
        solucion               TEXT
    )
    """,
    "CREATE INDEX idx_tickets_usuario ON tickets (usuario_id)",
    "CREATE INDEX idx_tickets_estado ON tickets (estado)",
    "CREATE INDEX idx_tickets_categoria ON tickets (categoria)",
    "CREATE INDEX idx_activos_usuario ON activos_cmdb (usuario_id)",
)


# ---------------------------------------------------------------------------
# Datos
# ---------------------------------------------------------------------------

SLA: tuple[tuple[Any, ...], ...] = (
    (
        "P1",
        "Crítica",
        15,
        4,
        "corridas",
        0.95,
        "Servicio caído para una sucursal, el centro de distribución o la flota en "
        "ruta; pérdida o robo de terminal; incidente de seguridad confirmado.",
    ),
    (
        "P2",
        "Alta",
        30,
        8,
        "corridas",
        0.90,
        "Grupo de usuarios sin servicio, o un usuario en ruta bloqueado para operar; "
        "bajas de personal pendientes de ejecutar.",
    ),
    (
        "P3",
        "Media",
        120,
        24,
        "hábiles",
        0.90,
        "Un usuario con el servicio degradado pero con alternativa de trabajo.",
    ),
    (
        "P4",
        "Baja",
        240,
        40,
        "hábiles",
        0.85,
        "Consultas, solicitudes de información y requerimientos programables sin "
        "impacto operativo.",
    ),
)

CATEGORIAS: tuple[tuple[Any, ...], ...] = (
    ("CAT-ACC", "Cuentas y accesos",
     "Alta, baja, bloqueo, restablecimiento de contraseña y permisos.", "P3"),
    ("CAT-M365", "Correo y ofimática",
     "Outlook, Teams, OneDrive y licencias Microsoft 365.", "P3"),
    ("CAT-RED", "Conectividad y VPN",
     "Enlaces de sucursal, Wi-Fi y VPN corporativa FortiClient.", "P2"),
    ("CAT-MOV", "Terminales móviles en ruta",
     "Terminales Android de reparto, Intune y SIM de datos.", "P2"),
    ("CAT-ERP", "ERP de transporte",
     "Módulos de hojas de ruta, facturación y flota.", "P2"),
    ("CAT-IMP", "Impresión y guías",
     "Impresoras de sucursal e impresoras térmicas de guías de despacho.", "P3"),
)

# (id, rut_numero, nombre, cargo, sucursal, usuario_correo, telefono, licencia,
#  estado, fecha_ingreso)
USUARIOS: tuple[tuple[Any, ...], ...] = (
    (1, 30100001, "María Fernanda Rojas Pinto", "Analista de Operaciones",
     "Casa Matriz Santiago", "maria.rojas", "+56 9 6100 0011", "E3", "activo", "2021-03-15"),
    (2, 30100002, "Diego Ignacio Salazar Mena", "Conductor de reparto",
     "Centro de Distribución Pudahuel", "diego.salazar", "+56 9 6100 0022", "E1", "activo", "2023-07-01"),
    (3, 30100003, "Carolina Andrea Muñoz Vega", "Jefa de Sucursal",
     "Sucursal Valparaíso", "carolina.munoz", "+56 9 6100 0033", "E3", "activo", "2019-11-04"),
    (4, 30100004, "Rodrigo Esteban Fuentes Lara", "Conductor de reparto",
     "Sucursal Rancagua", "rodrigo.fuentes", "+56 9 6100 0044", "E1", "activo", "2022-02-21"),
    (5, 30100005, "Javiera Paz Contreras Soto", "Administrativa de sucursal",
     "Sucursal Concepción", "javiera.contreras", "+56 9 6100 0055", "E1", "activo", "2024-01-08"),
    (6, 30100006, "Luis Alberto Tapia Reyes", "Especialista de Soporte Nivel 2",
     "Casa Matriz Santiago", "luis.tapia", "+56 9 6100 0066", "E3", "activo", "2018-05-30"),
    (7, 30100007, "Camila Antonia Vergara Ríos", "Agente Mesa de Ayuda Nivel 1",
     "Casa Matriz Santiago", "camila.vergara", "+56 9 6100 0077", "E3", "activo", "2023-09-11"),
    (8, 30100008, "Sebastián Andrés Norambuena Díaz", "Peoneta",
     "Centro de Distribución Pudahuel", "sebastian.norambuena", "+56 9 6100 0088", "E1", "activo", "2024-06-17"),
    (9, 30100009, "Paula Alejandra Herrera Campos", "Analista de Facturación",
     "Casa Matriz Santiago", "paula.herrera", "+56 9 6100 0099", "E3", "activo", "2020-08-03"),
    (10, 30100010, "Cristián Eduardo Bustos Miranda", "Jefe de Flota",
     "Sucursal La Serena", "cristian.bustos", "+56 9 6100 0110", "E3", "activo", "2017-04-12"),
    (11, 30100011, "Valentina Ignacia Cáceres Ortiz", "Administrativa de sucursal",
     "Sucursal La Serena", "valentina.caceres", "+56 9 6100 0121", "E1", "suspendido", "2022-10-24"),
    (12, 30100012, "Matías Nicolás Poblete Aravena", "Conductor de reparto",
     "Sucursal Valparaíso", "matias.poblete", "+56 9 6100 0132", "E1", "baja", "2021-01-18"),
)

# (id, tipo, marca_modelo, numero_serie, usuario_id, sucursal, ip, hostname,
#  estado, fecha_alta)
ACTIVOS: tuple[tuple[Any, ...], ...] = (
    ("ACT-0001", "Notebook", "Lenovo ThinkPad L14", "SN-LN-7741221", 1,
     "Casa Matriz Santiago", "192.168.10.41", "NB-STGO-041", "en uso", "2024-03-05"),
    ("ACT-0002", "Terminal móvil", "Zebra TC22", "SN-ZB-3320145", 2,
     "Centro de Distribución Pudahuel", "10.20.4.12", "MOV-CD-012", "en uso", "2025-01-20"),
    ("ACT-0003", "Notebook", "HP ProBook 450", "SN-HP-5590318", 3,
     "Sucursal Valparaíso", "192.168.20.15", "NB-VALP-015", "en uso", "2023-11-14"),
    ("ACT-0004", "Terminal móvil", "Zebra TC22", "SN-ZB-3320188", 4,
     "Sucursal Rancagua", "10.20.6.31", "MOV-RANC-031", "en uso", "2025-01-20"),
    ("ACT-0005", "Equipo de escritorio", "Dell OptiPlex 3000", "SN-DL-9012776", 5,
     "Sucursal Concepción", "192.168.30.22", "PC-CONC-022", "en uso", "2024-07-09"),
    ("ACT-0006", "Notebook", "Lenovo ThinkPad L14", "SN-LN-7741290", 6,
     "Casa Matriz Santiago", "192.168.10.58", "NB-STGO-058", "en uso", "2024-03-05"),
    ("ACT-0007", "Notebook", "Lenovo ThinkPad L14", "SN-LN-7741302", 7,
     "Casa Matriz Santiago", "192.168.10.62", "NB-STGO-062", "en uso", "2024-03-05"),
    ("ACT-0008", "Terminal móvil", "Zebra TC22", "SN-ZB-3320201", 8,
     "Centro de Distribución Pudahuel", "10.20.4.27", "MOV-CD-027", "en uso", "2025-02-11"),
    ("ACT-0009", "Notebook", "HP ProBook 450", "SN-HP-5590402", 9,
     "Casa Matriz Santiago", "192.168.10.77", "NB-STGO-077", "en uso", "2023-11-14"),
    ("ACT-0010", "Notebook", "Dell Latitude 5540", "SN-DL-4471905", 10,
     "Sucursal La Serena", "192.168.40.11", "NB-SERE-011", "en uso", "2024-09-30"),
    ("ACT-0011", "Equipo de escritorio", "Dell OptiPlex 3000", "SN-DL-9012801", 11,
     "Sucursal La Serena", "192.168.40.23", "PC-SERE-023", "bloqueado", "2024-07-09"),
    ("ACT-0012", "Terminal móvil", "Zebra TC22", "SN-ZB-3320233", None,
     "Sucursal Valparaíso", None, "MOV-VALP-044", "pendiente de devolución", "2025-02-11"),
    ("ACT-0013", "Terminal móvil", "Zebra TC22", "SN-ZB-3320240", None,
     "Centro de Distribución Pudahuel", None, "MOV-CD-050", "en bodega", "2025-02-11"),
    ("ACT-0014", "Terminal móvil", "Zebra TC22", "SN-ZB-3320255", None,
     "Sucursal Rancagua", None, "MOV-RANC-055", "en bodega", "2025-02-11"),
    ("ACT-0015", "Impresora térmica", "Zebra ZD421", "SN-ZP-1180067", None,
     "Centro de Distribución Pudahuel", "10.20.4.200", "IMP-CD-200", "en uso", "2023-05-22"),
    ("ACT-0016", "Impresora multifuncional", "HP LaserJet M428", "SN-HP-2240991", None,
     "Sucursal Concepción", "192.168.30.200", "IMP-CONC-200", "en uso", "2022-12-01"),
    ("ACT-0017", "Servidor", "Dell PowerEdge R450", "SN-DL-6650012", None,
     "Casa Matriz Santiago", "192.168.10.5", "SRV-STGO-005", "en uso", "2022-08-19"),
    ("ACT-0018", "Concentrador VPN", "FortiGate 100F", "SN-FG-8890034", None,
     "Casa Matriz Santiago", "192.168.10.1", "FW-STGO-001", "en uso", "2022-08-19"),
    ("ACT-0019", "Punto de acceso", "Ubiquiti U6-Pro", "SN-UB-7710556", None,
     "Sucursal Valparaíso", "192.168.20.250", "AP-VALP-250", "en uso", "2024-04-02"),
    ("ACT-0020", "Notebook", "HP ProBook 450", "SN-HP-5590415", None,
     "Casa Matriz Santiago", None, "NB-STGO-090", "en bodega", "2023-11-14"),
)

# (id, usuario_id, categoria, asunto, descripcion, prioridad, estado, canal,
#  agente, nivel, apertura, primera_respuesta, cierre, activo_id, solucion)
TICKETS: tuple[tuple[Any, ...], ...] = (
    ("INC-2026-0401", 1, "CAT-M365", "Outlook no sincroniza desde ayer",
     "La usuaria reporta que el último correo recibido es de las 18:00 de ayer.",
     "P3", "resuelto", "telefono", "Camila Vergara", 1,
     "2026-08-10 08:42", "2026-08-10 09:05", "2026-08-10 11:20", "ACT-0001",
     "Modo sin conexión activado. Se desactivó y sincronizó."),
    ("INC-2026-0402", 2, "CAT-MOV", "Terminal no abre la aplicación de ruta",
     "Conductor en el CD, salida de ruta a las 07:00.",
     "P2", "resuelto", "telefono", "Camila Vergara", 1,
     "2026-08-10 06:35", "2026-08-10 06:48", "2026-08-10 07:10", "ACT-0002",
     "Sesión vencida. Reinicio y nuevo inicio de sesión."),
    ("INC-2026-0403", 3, "CAT-RED", "VPN entrega error de credenciales",
     "Jefa de sucursal intentando conectar desde su domicilio.",
     "P2", "resuelto", "portal", "Camila Vergara", 1,
     "2026-08-11 09:15", "2026-08-11 09:30", "2026-08-11 10:02", "ACT-0003",
     "Ingresaba el usuario con dominio. Se corrigió el formato."),
    ("REQ-2026-0404", 5, "CAT-ACC", "Solicitud de restablecimiento de contraseña",
     "Administrativa sin acceso al portal de autoservicio.",
     "P3", "resuelto", "telefono", "Camila Vergara", 2,
     "2026-08-11 10:05", "2026-08-11 10:22", "2026-08-11 12:40", "ACT-0005",
     "Verificación de identidad y credencial temporal entregada por Nivel 2."),
    ("INC-2026-0405", 4, "CAT-MOV", "Terminal sin datos móviles en ruta",
     "Conductor reporta pérdida de señal en tramo rural.",
     "P2", "resuelto", "telefono", "Rodrigo Cerda", 1,
     "2026-08-12 11:20", "2026-08-12 11:35", "2026-08-12 13:15", "ACT-0004",
     "Zona sin cobertura. Se reanudó la captura al volver a zona urbana."),
    ("INC-2026-0406", 9, "CAT-M365", "Buzón lleno, no puede enviar correo",
     "Analista de facturación con buzón al 99 % de la cuota.",
     "P3", "resuelto", "portal", "Rodrigo Cerda", 1,
     "2026-08-12 14:50", "2026-08-12 15:40", "2026-08-13 09:30", "ACT-0009",
     "Limpieza de adjuntos y activación de archivado en línea por Nivel 2."),
    ("INC-2026-0407", 10, "CAT-RED", "Enlace intermitente en Sucursal La Serena",
     "Cortes de 2 a 3 minutos cada media hora, afecta a toda la sucursal.",
     "P1", "resuelto", "telefono", "Luis Tapia", 2,
     "2026-08-13 08:05", "2026-08-13 08:12", "2026-08-13 11:45", "ACT-0010",
     "Falla del proveedor de enlace. Se coordinó reemplazo del módem."),
    ("REQ-2026-0408", 8, "CAT-ACC", "Alta de colaborador nuevo en el CD",
     "Ingreso de peoneta con formulario de Personas adjunto.",
     "P3", "resuelto", "portal", "Camila Vergara", 2,
     "2026-08-13 09:40", "2026-08-13 10:50", "2026-08-14 10:00", None,
     "Cuenta creada, licencia E1 asignada y terminal registrado en CMDB."),
    ("INC-2026-0409", 7, "CAT-M365", "Teams no inicia, queda en pantalla de carga",
     "Agente de mesa de ayuda sin acceso a Teams.",
     "P3", "resuelto", "chat", "Rodrigo Cerda", 1,
     "2026-08-14 08:20", "2026-08-14 08:35", "2026-08-14 09:05", "ACT-0007",
     "Caché local corrupta. Se limpió tras advertir la pérdida de borradores."),
    ("INC-2026-0410", 11, "CAT-ACC", "Cuenta bloqueada por intentos fallidos",
     "El teléfono de la usuaria seguía reintentando con la contraseña anterior.",
     "P3", "resuelto", "telefono", "Camila Vergara", 1,
     "2026-08-14 09:10", "2026-08-14 09:25", "2026-08-14 10:15", "ACT-0011",
     "Se retiró la cuenta del cliente de correo del teléfono y se esperó el desbloqueo."),
    ("INC-2026-0411", 3, "CAT-RED", "Advertencia de certificado al conectar la VPN",
     "Jefa de sucursal conectada desde el Wi-Fi de un hotel en Viña del Mar.",
     "P2", "escalado", "telefono", "Camila Vergara", 2,
     "2026-08-17 19:30", "2026-08-17 19:44", None, "ACT-0003",
     None),
    ("INC-2026-0412", 2, "CAT-MOV", "Terminal extraviado en ruta",
     "El conductor no encuentra el terminal tras la última entrega del día.",
     "P1", "escalado", "telefono", "Luis Tapia", 2,
     "2026-08-18 18:05", "2026-08-18 18:12", None, "ACT-0012",
     None),
    ("INC-2026-0413", 1, "CAT-M365", "OneDrive dejó de sincronizar",
     "Carpeta de documentación de ruta con nombres de archivo muy largos.",
     "P3", "resuelto", "portal", "Rodrigo Cerda", 1,
     "2026-08-18 10:15", "2026-08-18 11:30", "2026-08-18 15:20", "ACT-0001",
     "Rutas de más de 400 caracteres. Se renombraron las carpetas."),
    ("REQ-2026-0414", 12, "CAT-ACC", "Baja de colaborador desvinculado",
     "Notificación de Personas con fecha efectiva del 20 de agosto.",
     "P2", "resuelto", "portal", "Luis Tapia", 2,
     "2026-08-19 09:00", "2026-08-19 09:20", "2026-08-20 09:05", None,
     "Cuenta deshabilitada, sesiones revocadas y accesos retirados."),
    ("INC-2026-0415", 5, "CAT-IMP", "Impresora de guías no responde",
     "La impresora térmica del CD no imprime las guías de despacho.",
     "P2", "resuelto", "telefono", "Rodrigo Cerda", 1,
     "2026-08-19 07:40", "2026-08-19 07:55", "2026-08-19 08:50", "ACT-0015",
     "Cola de impresión trabada. Se reinició el servicio."),
    ("INC-2026-0416", 6, "CAT-ERP", "ERP lento al cerrar hojas de ruta",
     "Demora de más de 40 segundos por hoja de ruta en horario punta.",
     "P2", "en curso", "portal", "Luis Tapia", 2,
     "2026-08-20 16:10", "2026-08-20 16:28", None, "ACT-0017",
     None),
    ("INC-2026-0417", 4, "CAT-MOV", "Terminal no cumple políticas de Intune",
     "Mensaje de dispositivo no conforme al iniciar la aplicación de ruta.",
     "P2", "resuelto", "telefono", "Camila Vergara", 1,
     "2026-08-20 06:50", "2026-08-20 07:02", "2026-08-20 07:40", "ACT-0004",
     "PIN eliminado por el usuario. Se reconfiguró el PIN de 6 dígitos."),
    ("INC-2026-0418", 9, "CAT-M365", "Producto sin licencia en Excel",
     "La usuaria puede usar el correo web pero no las aplicaciones de escritorio.",
     "P3", "resuelto", "chat", "Rodrigo Cerda", 2,
     "2026-08-21 11:05", "2026-08-21 12:15", "2026-08-21 16:30", "ACT-0009",
     "La cuenta tenía E1. Se asignó E3 con aprobación de jefatura."),
    ("INC-2026-0419", 10, "CAT-RED", "VPN error E-13 permiso denegado",
     "Jefe de flota recién trasladado de área.",
     "P2", "resuelto", "telefono", "Camila Vergara", 2,
     "2026-08-21 08:30", "2026-08-21 08:45", "2026-08-21 10:10", "ACT-0010",
     "Faltaba pertenencia al grupo VPN-Usuarios. Nivel 2 la asignó."),
    ("REQ-2026-0420", 3, "CAT-ACC", "Solicitud de acceso al módulo de facturación",
     "Requiere aprobación de la jefatura de Administración y Finanzas.",
     "P4", "en curso", "portal", "Camila Vergara", 1,
     "2026-08-24 10:00", "2026-08-24 12:30", None, None,
     None),
    ("INC-2026-0421", 7, "CAT-ACC", "Notificaciones de segundo factor no solicitadas",
     "La agente recibió seis solicitudes de aprobación durante la madrugada.",
     "P1", "escalado", "telefono", "Luis Tapia", 2,
     "2026-08-24 08:05", "2026-08-24 08:11", None, "ACT-0007",
     None),
    ("INC-2026-0422", 8, "CAT-MOV", "Terminal con batería que no dura la jornada",
     "Equipo con 26 meses de uso, se apaga a media ruta.",
     "P3", "en curso", "telefono", "Rodrigo Cerda", 1,
     "2026-08-25 12:20", "2026-08-25 13:40", None, "ACT-0008",
     None),
    ("INC-2026-0423", 5, "CAT-M365", "Correo rebotado por buzón lleno del destinatario",
     "Consulta sobre mensaje devuelto al enviar a un contacto interno.",
     "P4", "resuelto", "chat", "Camila Vergara", 1,
     "2026-08-25 15:10", "2026-08-25 16:50", "2026-08-26 09:20", "ACT-0005",
     "Se orientó al destinatario a liberar espacio en su buzón."),
    ("INC-2026-0424", 1, "CAT-RED", "Sin acceso a recursos internos con VPN conectada",
     "El router domiciliario entrega el mismo rango que la red de casa matriz.",
     "P2", "resuelto", "telefono", "Luis Tapia", 2,
     "2026-08-26 09:35", "2026-08-26 09:50", "2026-08-26 11:25", "ACT-0001",
     "Conflicto de rango 192.168.10.x. Se usó el hotspot del teléfono."),
    ("REQ-2026-0425", 6, "CAT-ERP", "Solicitud de reporte de flota mensual",
     "Requerimiento programable sin impacto operativo.",
     "P4", "abierto", "portal", "Rodrigo Cerda", 1,
     "2026-08-26 17:40", None, None, None,
     None),
    ("INC-2026-0426", 11, "CAT-ACC", "Cuenta suspendida tras licencia médica extensa",
     "Reactivación pendiente de confirmación de Personas.",
     "P3", "en curso", "portal", "Camila Vergara", 1,
     "2026-08-27 09:15", "2026-08-27 10:40", None, "ACT-0011",
     None),
    ("INC-2026-0427", 2, "CAT-MOV", "Terminal de reemplazo sin aplicación de ruta",
     "Equipo de contingencia entregado sin sincronizar el portal de empresa.",
     "P2", "resuelto", "telefono", "Camila Vergara", 1,
     "2026-08-27 06:40", "2026-08-27 06:55", "2026-08-27 07:35", "ACT-0013",
     "Se forzó la sincronización desde el portal de empresa."),
    ("INC-2026-0428", 3, "CAT-M365", "Teams sin audio en reunión con clientes",
     "Micrófono seleccionado incorrecto tras conectar audífonos nuevos.",
     "P3", "resuelto", "chat", "Rodrigo Cerda", 1,
     "2026-08-28 10:20", "2026-08-28 10:35", "2026-08-28 10:55", "ACT-0003",
     "Se seleccionó el dispositivo correcto en la configuración de Teams."),
    ("INC-2026-0429", 4, "CAT-RED", "Error -5 al conectar la VPN desde red de cliente",
     "La red del cliente bloquea el puerto TCP 10443.",
     "P3", "resuelto", "telefono", "Camila Vergara", 1,
     "2026-08-28 15:05", "2026-08-28 15:20", "2026-08-28 16:00", "ACT-0004",
     "Se conectó por hotspot del teléfono corporativo."),
    ("INC-2026-0430", 9, "CAT-IMP", "Impresora multifuncional con atasco recurrente",
     "Atascos de papel en la bandeja 2 de la sucursal Concepción.",
     "P3", "escalado", "portal", "Rodrigo Cerda", 2,
     "2026-08-31 09:50", "2026-08-31 11:10", None, "ACT-0016",
     None),
    ("INC-2026-0431", 10, "CAT-ERP", "No se generan guías desde el ERP",
     "Afecta a los despachos de la mañana en La Serena.",
     "P1", "resuelto", "telefono", "Luis Tapia", 2,
     "2026-09-01 07:15", "2026-09-01 07:22", "2026-09-01 09:40", "ACT-0010",
     "Servicio de generación de folios detenido. Se reinició el servicio."),
    ("REQ-2026-0432", 5, "CAT-ACC", "Solicitud de cambio de método de verificación",
     "La usuaria cambió de número de teléfono.",
     "P3", "escalado", "telefono", "Camila Vergara", 2,
     "2026-09-01 11:30", "2026-09-01 12:05", None, "ACT-0005",
     None),
    ("INC-2026-0433", 7, "CAT-M365", "Regla de reenvío automático no reconocida",
     "La agente encontró una regla que reenvía correos a un dominio externo.",
     "P1", "escalado", "chat", "Luis Tapia", 2,
     "2026-09-02 08:40", "2026-09-02 08:47", None, "ACT-0007",
     None),
    ("INC-2026-0434", 8, "CAT-MOV", "Terminal no captura firmas",
     "Pantalla con protector dañado en el terminal del peoneta.",
     "P2", "en curso", "telefono", "Rodrigo Cerda", 1,
     "2026-09-02 07:05", "2026-09-02 07:20", None, "ACT-0008",
     None),
    ("INC-2026-0435", 1, "CAT-M365", "Archivo eliminado por error en OneDrive",
     "Planilla de programación de rutas borrada hace 45 días.",
     "P3", "escalado", "portal", "Camila Vergara", 2,
     "2026-09-03 10:10", "2026-09-03 11:15", None, "ACT-0001",
     None),
    ("INC-2026-0436", 4, "CAT-MOV", "Terminal enrolado a nombre de otro colaborador",
     "Equipo reasignado sin retirar el registro previo en Intune.",
     "P2", "escalado", "telefono", "Camila Vergara", 2,
     "2026-09-03 06:50", "2026-09-03 07:05", None, "ACT-0014",
     None),
    ("INC-2026-0437", 3, "CAT-RED", "Wi-Fi caído en Sucursal Valparaíso",
     "Ningún equipo de la sucursal se conecta a la red inalámbrica.",
     "P1", "en curso", "telefono", "Luis Tapia", 2,
     "2026-09-04 08:30", "2026-09-04 08:38", None, "ACT-0019",
     None),
    ("REQ-2026-0438", 6, "CAT-ACC", "Revisión trimestral de permisos del ERP",
     "Requerimiento programado de la Subgerencia de TI.",
     "P4", "abierto", "portal", "Camila Vergara", 1,
     "2026-09-04 16:20", None, None, None,
     None),
    ("INC-2026-0439", 2, "CAT-ACC", "Llamada sospechosa pidiendo la contraseña",
     "El conductor recibió una llamada de alguien que dijo ser de la mesa de ayuda.",
     "P1", "escalado", "telefono", "Luis Tapia", 2,
     "2026-09-04 13:40", "2026-09-04 13:46", None, "ACT-0002",
     None),
    ("INC-2026-0440", 9, "CAT-M365", "Outlook pide contraseña de forma repetida",
     "Ventanas de inicio de sesión que reaparecen cada pocos minutos.",
     "P3", "abierto", "portal", "Rodrigo Cerda", 1,
     "2026-09-05 09:05", None, None, "ACT-0009",
     None),
)


# ---------------------------------------------------------------------------
# Construcción de la base
# ---------------------------------------------------------------------------


def crear_base(ruta: Path = RUTA_BD) -> dict[str, int]:
    """Crea la base desde cero y la puebla con los datos de demostración.

    La operación es idempotente: elimina las tablas existentes antes de crearlas,
    de modo que ejecutar el script dos veces deja el mismo resultado.

    Args:
        ruta: Ubicación del archivo SQLite a crear.

    Returns:
        Diccionario con la cantidad de filas insertadas por tabla.
    """
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(ruta) as conexion:
        conexion.execute("PRAGMA foreign_keys = OFF")
        for tabla in ("tickets", "activos_cmdb", "categorias_servicio", "sla", "usuarios"):
            conexion.execute(f"DROP TABLE IF EXISTS {tabla}")
        for sentencia in ESQUEMA:
            conexion.execute(sentencia)

        conexion.executemany(
            "INSERT INTO sla (prioridad, nombre, primera_respuesta_min, "
            "resolucion_horas, tipo_reloj, cumplimiento_minimo, descripcion) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            SLA,
        )
        conexion.executemany(
            "INSERT INTO categorias_servicio (codigo, nombre, descripcion, "
            "prioridad_base) VALUES (?, ?, ?, ?)",
            CATEGORIAS,
        )
        conexion.executemany(
            "INSERT INTO usuarios (id, rut, nombre, cargo, sucursal, correo, "
            "telefono, perfil_licencia, estado, fecha_ingreso) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    identificador,
                    formatear_rut(rut_numero),
                    nombre,
                    cargo,
                    sucursal,
                    f"{usuario_correo}@aconcagualog.cl",
                    telefono,
                    licencia,
                    estado,
                    fecha_ingreso,
                )
                for (
                    identificador,
                    rut_numero,
                    nombre,
                    cargo,
                    sucursal,
                    usuario_correo,
                    telefono,
                    licencia,
                    estado,
                    fecha_ingreso,
                ) in USUARIOS
            ],
        )
        conexion.executemany(
            "INSERT INTO activos_cmdb (id, tipo, marca_modelo, numero_serie, "
            "usuario_id, sucursal, ip_asignada, hostname, estado, fecha_alta) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ACTIVOS,
        )
        conexion.executemany(
            "INSERT INTO tickets (id, usuario_id, categoria, asunto, descripcion, "
            "prioridad, estado, canal, agente_asignado, nivel_atencion, "
            "fecha_apertura, fecha_primera_respuesta, fecha_cierre, activo_id, "
            "solucion) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            TICKETS,
        )
        conexion.execute("PRAGMA foreign_keys = ON")

        conteos = {
            tabla: conexion.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]
            for tabla in ("usuarios", "categorias_servicio", "sla", "activos_cmdb", "tickets")
        }
    return conteos


def main() -> None:
    """Punto de entrada de consola: crea la base e imprime el resumen."""
    conteos = crear_base()
    print(f"Base de datos creada en: {RUTA_BD}")
    print("-" * 62)
    for tabla, cantidad in conteos.items():
        print(f"  {tabla:<22} {cantidad:>3} filas")
    print("-" * 62)

    with sqlite3.connect(RUTA_BD) as conexion:
        print("Tickets por estado:")
        for estado, cantidad in conexion.execute(
            "SELECT estado, COUNT(*) FROM tickets GROUP BY estado ORDER BY estado"
        ):
            print(f"  {estado:<22} {cantidad:>3}")
        print("Tickets por prioridad:")
        for prioridad, cantidad in conexion.execute(
            "SELECT prioridad, COUNT(*) FROM tickets GROUP BY prioridad ORDER BY prioridad"
        ):
            print(f"  {prioridad:<22} {cantidad:>3}")
    print("\nListo. Siguiente paso: python -m src.ingest")


if __name__ == "__main__":
    main()
