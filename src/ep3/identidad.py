"""Claves HMAC explícitas; nunca crea claves efímeras ni imprime su contenido."""
from pathlib import Path
import os
import secrets

def leer_clave(ruta: Path) -> bytes:
    ruta = Path(ruta)
    if ruta.suffix != '.key' or ruta.is_symlink() or not ruta.is_file():
        raise ValueError('Archivo de clave no válido.')
    if ruta.stat().st_size != 32:
        raise ValueError('Longitud de clave no válida.')
    return ruta.read_bytes()

def crear_clave(ruta: Path) -> None:
    """Operación explícita de preparación; O_EXCL impide sobrescribir claves."""
    ruta = Path(ruta)
    if ruta.suffix != '.key':
        raise ValueError('Utiliza extensión .key, excluida de Git.')
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(ruta, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as f:
        f.write(secrets.token_bytes(32))
        f.flush()
        os.fsync(f.fileno())
