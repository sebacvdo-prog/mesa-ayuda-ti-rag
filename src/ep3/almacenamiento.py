"""SQLite exclusiva EP3, con marca de aplicación y escritura fuera del agente."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from uuid import UUID
from uuid import uuid4

from src.ep3.contratos import Contadores, Evento, VERSION_ESQUEMA
from src.ep3.contratos_v2 import VERSION_BD, Evaluacion


RAIZ = Path(__file__).resolve().parents[2]
DIRECTORIO_EP3 = RAIZ / 'storage' / 'ep3'
APPLICATION_ID = 0x45503331


class AlmacenObservabilidad:
    def __init__(self, directorio: Path, retencion_dias: int = 30):
        if type(retencion_dias) is not int or not 1 <= retencion_dias <= 3650:
            raise ValueError('Retención fuera de rango.')
        directorio = Path(directorio).resolve()
        self.ruta = directorio / 'observabilidad.db'
        if directorio.is_relative_to(RAIZ / 'data') or directorio.is_relative_to(RAIZ / 'storage' / 'ep2'):
            raise ValueError('La telemetría requiere un directorio independiente.')
        protegidas = (RAIZ / 'data/itsm.db', RAIZ / 'storage/ep2/agent.db', RAIZ / '.cache/embeddings.sqlite')
        if self.ruta.is_symlink() or any(self.ruta.exists() and p.exists() and self.ruta.samefile(p) for p in protegidas):
            raise ValueError('La base EP3 no puede ser un enlace a otro archivo.')
        directorio.mkdir(parents=True, exist_ok=True)
        nueva = not self.ruta.exists()
        self.conexion = sqlite3.connect(self.ruta.as_uri() + ('?mode=rwc' if nueva else '?mode=rw'),
                                       uri=True, timeout=0.1)
        try:
            marca = self.conexion.execute('PRAGMA application_id').fetchone()[0]
            version = self.conexion.execute('PRAGMA user_version').fetchone()[0]
            if not nueva and marca == APPLICATION_ID:
                tablas = {r[0] for r in self.conexion.execute('SELECT name FROM sqlite_master WHERE type="table"')}
                if not {'trazas', 'eventos', 'salud_telemetria'} <= tablas or version not in (1, VERSION_BD):
                    raise ValueError('Esquema de observabilidad incompatible.')
                if version == 1:
                    # Copia consistente antes de cualquier DDL. Nunca se sobreescribe.
                    respaldo = directorio / f'observabilidad.v1.{uuid4().hex}.bak'
                    destino = sqlite3.connect(respaldo)
                    try:
                        self.conexion.backup(destino)
                    finally:
                        destino.close()
            with self.conexion as c:
                c.execute('BEGIN IMMEDIATE')
                marca = c.execute('PRAGMA application_id').fetchone()[0]
                if marca == APPLICATION_ID:
                    if c.execute('PRAGMA user_version').fetchone()[0] not in (1, VERSION_BD):
                        raise ValueError('Versión de observabilidad incompatible.')
                elif nueva and marca == 0 and not c.execute('SELECT name FROM sqlite_master').fetchone():
                    c.execute(f'PRAGMA application_id={APPLICATION_ID}')
                    c.execute(f'PRAGMA user_version={VERSION_ESQUEMA}')
                    c.execute('''CREATE TABLE trazas (
                        ejecucion_id TEXT PRIMARY KEY, version_esquema INTEGER NOT NULL,
                        sesion_ref TEXT NOT NULL, tipo_ejecucion TEXT NOT NULL,
                        pipeline TEXT NOT NULL, inicio_utc TEXT NOT NULL)''')
                    c.execute('''CREATE TABLE eventos (
                        evento_id TEXT PRIMARY KEY, ejecucion_id TEXT NOT NULL REFERENCES trazas(ejecucion_id),
                        secuencia INTEGER NOT NULL, fecha_utc TEXT NOT NULL, evento TEXT NOT NULL,
                        componente TEXT NOT NULL, duracion_ms REAL, estado TEXT NOT NULL,
                        codigo TEXT NOT NULL, contenido_json TEXT NOT NULL,
                        UNIQUE(ejecucion_id,secuencia))''')
                    c.execute('CREATE INDEX eventos_ejecucion ON eventos(ejecucion_id,secuencia)')
                    c.execute('''CREATE TABLE salud_telemetria (
                        recolector_id TEXT PRIMARY KEY, actualizado_utc TEXT NOT NULL,
                        contadores_json TEXT NOT NULL)''')
                else:
                    raise ValueError('La base existente no pertenece a EP3.')
                columnas = {r[1] for r in c.execute('PRAGMA table_info(trazas)')}
                for nombre, definicion in [('categoria', "TEXT NOT NULL DEFAULT 'interactiva'"),
                                           ('correlacion', "TEXT NOT NULL DEFAULT 'legado_no_estable'"),
                                           ('clave_id', 'TEXT'), ('operacion', "TEXT NOT NULL DEFAULT 'consulta'")]:
                    if nombre not in columnas:
                        c.execute(f'ALTER TABLE trazas ADD COLUMN {nombre} {definicion}')
                c.execute('''CREATE TABLE IF NOT EXISTS evaluaciones (
                    evaluacion_id TEXT PRIMARY KEY, ejecucion_id TEXT, tipo_ejecucion TEXT NOT NULL,
                    caso TEXT NOT NULL, metrica TEXT NOT NULL, valor REAL NOT NULL, contenido_json TEXT NOT NULL)''')
                c.execute('CREATE INDEX IF NOT EXISTS trazas_origen_fecha ON trazas(tipo_ejecucion,inicio_utc)')
                c.execute('CREATE INDEX IF NOT EXISTS eventos_tipo_fecha ON eventos(evento,fecha_utc)')
                c.execute('CREATE INDEX IF NOT EXISTS eventos_codigo ON eventos(codigo)')
                c.execute('CREATE TABLE IF NOT EXISTS politica (clave TEXT PRIMARY KEY, valor INTEGER NOT NULL)')
                c.execute('INSERT OR REPLACE INTO politica VALUES (?,?)', ('retencion_dias', retencion_dias))
                c.execute(f'PRAGMA user_version={VERSION_BD}')
        except BaseException:
            self.conexion.close()
            raise

    def guardar(self, eventos: list[Evento], recolector_id: UUID, contadores: dict[str, int]) -> None:
        salud = Contadores.model_validate(contadores)
        with self.conexion as c:
            for e in eventos:
                c.execute('INSERT OR IGNORE INTO trazas VALUES (?,?,?,?,?,?,?,?,?,?)',
                          (str(e.ejecucion_id), e.version_esquema, e.sesion_ref or '',
                           e.tipo_ejecucion, e.pipeline, e.inicio_utc.isoformat(),
                           getattr(e, 'categoria', 'interactiva'), getattr(e, 'correlacion', 'legado_no_estable'),
                           getattr(e, 'clave_id', None), getattr(e, 'operacion', 'consulta')))
                c.execute('INSERT INTO eventos VALUES (?,?,?,?,?,?,?,?,?,?)',
                          (str(e.evento_id), str(e.ejecucion_id), e.secuencia, e.fecha_utc.isoformat(),
                           e.evento, e.componente, e.duracion_ms, e.estado, e.codigo,
                           e.model_dump_json(exclude_none=True)))
            c.execute('INSERT OR REPLACE INTO salud_telemetria VALUES (?,?,?)',
                      (str(recolector_id), datetime.now(timezone.utc).isoformat(), salud.model_dump_json()))

    def guardar_evaluaciones(self, filas: list[Evaluacion]) -> None:
        # Validar de nuevo en la frontera de persistencia, no admitir dict libres.
        datos = [Evaluacion.model_validate_json(f.model_dump_json()) for f in filas]
        with self.conexion as c:
            for f in datos:
                c.execute('INSERT INTO evaluaciones VALUES (?,?,?,?,?,?,?)',
                          (str(f.evaluacion_id), str(f.ejecucion_id) if f.ejecucion_id else None,
                           f.tipo_ejecucion, f.caso, f.metrica, f.valor, f.model_dump_json()))

    def cerrar(self) -> None:
        self.conexion.close()
