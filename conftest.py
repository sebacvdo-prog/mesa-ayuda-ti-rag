"""Configuración de pytest para todo el repositorio.

Su única función es asegurar que la raíz del proyecto esté en ``sys.path``, de
modo que ``from src import ...`` funcione al ejecutar ``pytest`` desde cualquier
directorio y sin instalar el paquete.

Las pruebas **no llaman a ninguna API**: el LLM y los embeddings se reemplazan
por dobles en cada caso que los necesita.
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ_PROYECTO = Path(__file__).resolve().parent
if str(RAIZ_PROYECTO) not in sys.path:
    sys.path.insert(0, str(RAIZ_PROYECTO))
