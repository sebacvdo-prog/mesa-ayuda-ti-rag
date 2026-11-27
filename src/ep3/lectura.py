"""Lectura estricta y sanitizada. No importa agentes, configuración ni proveedores."""
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
import sqlite3
from uuid import UUID
from src.ep3.almacenamiento import APPLICATION_ID
from src.ep3.contratos import Contadores
from src.ep3.contratos_v2 import Evaluacion, leer_evento

class DatosNoDisponibles(ValueError):
    pass

@dataclass
class Datos:
    eventos: list[dict]
    evaluaciones: list[dict]
    salud: list[dict]
    invalidos: int
    recortado: bool
    version: int
    retencion_dias: int

def cargar(ruta: Path, limite: int = 50000) -> Datos:
    ruta = Path(ruta)
    if type(limite) is not int or not 1 <= limite <= 100000:
        raise DatosNoDisponibles('Límite de lectura inválido.')
    try:
        if ruta.is_symlink() or not ruta.is_file():
            raise DatosNoDisponibles('Base de observabilidad ausente o no accesible.')
        with closing(sqlite3.connect(ruta.resolve().as_uri()+'?mode=ro', uri=True, timeout=0.2)) as c:
            c.execute('PRAGMA query_only=ON')
            if c.execute('PRAGMA application_id').fetchone()[0] != APPLICATION_ID:
                raise DatosNoDisponibles('El archivo no es una base EP3.')
            version = c.execute('PRAGMA user_version').fetchone()[0]
            if version not in (1,2): raise DatosNoDisponibles('Versión de base no soportada.')
            eventos, evaluaciones, salud, invalidos = [], [], [], 0
            filas = c.execute('SELECT contenido_json FROM eventos ORDER BY rowid DESC LIMIT ?', (limite+1,)).fetchall()
            recortado = len(filas) > limite
            for (texto,) in reversed(filas[:limite]):
                try: eventos.append(leer_evento(texto).model_dump(mode='json'))
                except Exception: invalidos += 1
            for identificador, texto in c.execute('SELECT recolector_id,contadores_json FROM salud_telemetria'):
                try:
                    salud.append({'recolector_id':str(UUID(identificador)), **Contadores.model_validate_json(texto).model_dump()})
                except Exception: invalidos += 1
            dias = 30
            if version == 2:
                for (texto,) in c.execute('SELECT contenido_json FROM evaluaciones ORDER BY rowid DESC LIMIT 20000'):
                    try: evaluaciones.append(Evaluacion.model_validate_json(texto).model_dump(mode='json'))
                    except Exception: invalidos += 1
                fila = c.execute('SELECT valor FROM politica WHERE clave=?',('retencion_dias',)).fetchone()
                if fila and type(fila[0]) is int and 1 <= fila[0] <= 3650: dias = fila[0]
            return Datos(eventos,evaluaciones,salud,invalidos,recortado,version,dias)
    except DatosNoDisponibles: raise
    except (sqlite3.Error, OSError, ValueError):
        raise DatosNoDisponibles('No se pudo leer la base: permisos, bloqueo o esquema incompleto.') from None
