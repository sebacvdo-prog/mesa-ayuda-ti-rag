"""Configuración central del asistente RAG de la mesa de ayuda TI.

Este módulo concentra cuatro responsabilidades para que el resto del código no
tenga que preocuparse por ellas:

1. Carga de variables de entorno desde ``.env`` y constantes del pipeline.
2. Validación de las claves de API con mensajes accionables.
3. Fábricas de modelos (chat y embeddings), incluida la caché de embeddings en
   disco que evita recalcular vectores en cada corrida.
4. Reintento con retroceso exponencial ante HTTP 429 (cuota agotada), con un
   error propio que distingue "quedaste sin cuota" de "hay un bug".

Ninguna función de este módulo lanza excepción al importarlo: la ausencia de
claves solo se reporta cuando se llama a :func:`validar_configuracion` o a las
fábricas de modelos. Eso permite que las pruebas corran sin API keys.
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable, Iterable, TypeVar

from dotenv import load_dotenv
from langchain_core.embeddings import Embeddings

# ---------------------------------------------------------------------------
# Rutas del proyecto
# ---------------------------------------------------------------------------

RAIZ_PROYECTO: Path = Path(__file__).resolve().parent.parent
"""Directorio raíz del repositorio (la carpeta que contiene ``src/``)."""

load_dotenv(RAIZ_PROYECTO / ".env")

DIR_DATOS: Path = RAIZ_PROYECTO / "data"
DIR_INTERNOS: Path = DIR_DATOS / "internos"
DIR_EXTERNOS: Path = DIR_DATOS / "externos"
DIR_EVALUACION: Path = DIR_DATOS / "evaluacion"
RUTA_DATASET: Path = DIR_EVALUACION / "dataset.json"
RUTA_BD: Path = DIR_DATOS / "itsm.db"

DIR_ALMACENAMIENTO: Path = RAIZ_PROYECTO / "storage"
DIR_INDICE_FAISS: Path = DIR_ALMACENAMIENTO / "faiss_index"
RUTA_MANIFIESTO_INGESTA: Path = DIR_ALMACENAMIENTO / "manifiesto_ingesta.json"

DIR_CACHE: Path = RAIZ_PROYECTO / ".cache"
RUTA_CACHE_EMBEDDINGS: Path = DIR_CACHE / "embeddings.sqlite"

DIR_RESULTADOS_EVAL: Path = RAIZ_PROYECTO / "eval" / "resultados"


def ruta_segura(ruta: Path | str) -> str:
    """Devuelve la ruta absoluta manejando rutas largas en Windows."""
    p = str(Path(ruta).resolve())
    if os.name == "nt" and len(p) >= 200 and not p.startswith("\\\\?\\"):
        return f"\\\\?\\{p}"
    return p


def archivo_existe(ruta: Path | str) -> bool:
    """Comprueba si un archivo existe manejando rutas largas en Windows."""
    return os.path.exists(ruta_segura(ruta))

# ---------------------------------------------------------------------------
# Modelos y credenciales
# ---------------------------------------------------------------------------

LLM_API_KEY: str = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "https://api.groq.com/openai/v1")
MODELO_CHAT: str = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")

GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")
MODELO_EMBEDDINGS: str = os.getenv("EMBEDDING_MODEL", "models/gemini-embedding-001")
DIMENSION_EMBEDDINGS: int = int(os.getenv("EMBEDDING_DIM", "768"))

# ---------------------------------------------------------------------------
# Constantes del pipeline RAG
# ---------------------------------------------------------------------------

TAMANO_CHUNK: int = 900
"""Tamaño de cada fragmento en caracteres (justificado en docs/pipeline.md)."""

SOLAPE_CHUNK: int = 150
"""Solape entre fragmentos consecutivos, ~17 % del tamaño del chunk."""

TOP_K: int = 4
"""Cantidad de fragmentos que se recuperan por consulta."""

UMBRAL_SIMILITUD: float = 0.72
"""Puntaje mínimo de relevancia (0-1). Debajo de esto el fragmento se descarta."""

MARGEN_REORDENAMIENTO: float = 0.05
"""Dos fragmentos cuyos puntajes difieren menos que esto se consideran
equivalentes en pertinencia; entre ellos manda la fecha_vigencia más nueva."""

TEMPERATURA: float = 0.1
"""Temperatura del modelo de chat: baja, porque se busca respuesta procedimental."""

MAX_TOKENS: int = int(os.getenv("MAX_TOKENS", "2000"))
"""Tokens máximos de salida del modelo (permite razonamiento en modelos que lo requieren)."""

TEMPERATURA_JUEZ: float = 0.0
"""El LLM juez de la evaluación se ejecuta determinista."""

VENTANA_TURNOS: int = 6
"""Cantidad de intercambios (usuario + asistente) que se conservan literales."""

PERFILES_VALIDOS: tuple[str, ...] = ("agente", "usuario_final")
NIVELES_ACCESO: tuple[str, ...] = ("publico_interno", "restringido_agentes")

RESPUESTA_SIN_PROCEDIMIENTO: str = (
    "No dispongo de un procedimiento documentado para este caso; escalar a Nivel 2"
)
"""Respuesta literal exigida cuando el contexto no cubre la consulta."""

# ---------------------------------------------------------------------------
# Manejo de cuotas y reintentos
# ---------------------------------------------------------------------------


class ErrorDeCuota(RuntimeError):
    """Se agotó la cuota del proveedor (HTTP 429), no es un error de código."""


_MARCAS_DE_CUOTA: tuple[str, ...] = (
    "429",
    "rate limit",
    "rate_limit",
    "quota",
    "resource_exhausted",
    "resource has been exhausted",
    "too many requests",
)

T = TypeVar("T")


def es_error_de_cuota(error: BaseException) -> bool:
    """Indica si una excepción corresponde a un límite de cuota del proveedor.

    Args:
        error: Excepción capturada al llamar al proveedor.

    Returns:
        True si el mensaje o el atributo ``status_code`` indican HTTP 429.
    """
    if getattr(error, "status_code", None) == 429:
        return True
    texto = str(error).lower()
    return any(marca in texto for marca in _MARCAS_DE_CUOTA)


def reintentar_con_backoff(
    funcion: Callable[..., T],
    *args: Any,
    intentos: int = 5,
    espera_base: float = 2.0,
    espera_maxima: float = 60.0,
    **kwargs: Any,
) -> T:
    """Ejecuta ``funcion`` reintentando con retroceso exponencial ante HTTP 429.

    Las esperas siguen la serie ``espera_base ** n`` más una fracción aleatoria
    (jitter) para no sincronizar reintentos, con un techo de ``espera_maxima``.
    Cualquier error que no sea de cuota se propaga de inmediato: reintentarlo
    solo escondería un bug.

    Args:
        funcion: Callable a ejecutar.
        *args: Argumentos posicionales de ``funcion``.
        intentos: Número máximo de ejecuciones (incluida la primera).
        espera_base: Base de la progresión exponencial, en segundos.
        espera_maxima: Techo de espera entre intentos, en segundos.
        **kwargs: Argumentos por nombre de ``funcion``.

    Returns:
        Lo que devuelva ``funcion``.

    Raises:
        ErrorDeCuota: Si se agotaron los intentos y el proveedor sigue en 429.
    """
    ultimo_error: BaseException | None = None
    for intento in range(intentos):
        try:
            return funcion(*args, **kwargs)
        except Exception as error:  # noqa: BLE001 - se re-lanza si no es de cuota
            if not es_error_de_cuota(error):
                raise
            ultimo_error = error
            if intento == intentos - 1:
                break
            espera = min(espera_base ** (intento + 1), espera_maxima)
            espera += random.uniform(0, 0.5 * espera)
            print(
                "[cuota] El proveedor respondió 429 "
                f"(intento {intento + 1}/{intentos}). "
                f"Reintentando en {espera:.1f} s...",
                flush=True,
            )
            time.sleep(espera)

    raise ErrorDeCuota(
        "Se agotó la cuota gratuita del proveedor (HTTP 429). Esto NO es un error "
        "de código: el sistema está bien, la API rechazó la petición por límite de "
        "uso. Groq entrega 100.000 tokens diarios y Gemini 1.000 peticiones de "
        "embeddings por día. Esperá a que se reponga la cuota o usá otra clave. "
        f"Detalle del proveedor: {ultimo_error}"
    ) from ultimo_error


# ---------------------------------------------------------------------------
# Caché de embeddings en disco
# ---------------------------------------------------------------------------


class EmbeddingsConCache(Embeddings):
    """Envoltura que memoriza vectores en SQLite para no recalcularlos.

    La clave de caché es el hash SHA-256 de ``modelo | tipo | texto``, así que un
    cambio de modelo invalida automáticamente las entradas viejas. Cada llamada
    real al proveedor pasa por :func:`reintentar_con_backoff`.

    Attributes:
        modelo_base: Instancia de embeddings de LangChain a la que se delega.
        nombre_modelo: Identificador del modelo, usado en la clave de caché.
        ruta_cache: Archivo SQLite donde se guardan los vectores.
        aciertos: Cantidad de vectores servidos desde la caché.
        fallos: Cantidad de vectores que hubo que pedirle al proveedor.
    """

    def __init__(
        self,
        modelo_base: Embeddings,
        nombre_modelo: str,
        ruta_cache: Path = RUTA_CACHE_EMBEDDINGS,
    ) -> None:
        """Inicializa la caché y crea la tabla si no existe.

        Args:
            modelo_base: Embeddings reales (por ejemplo, Gemini).
            nombre_modelo: Nombre del modelo, para versionar la caché.
            ruta_cache: Ruta del archivo SQLite de caché.
        """
        self.modelo_base = modelo_base
        self.nombre_modelo = nombre_modelo
        self.ruta_cache = Path(ruta_cache)
        self.aciertos = 0
        self.fallos = 0
        self.ruta_cache.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self._ruta_str()) as conexion:
            conexion.execute(
                "CREATE TABLE IF NOT EXISTS embeddings ("
                "  clave TEXT PRIMARY KEY,"
                "  vector TEXT NOT NULL"
                ")"
            )

    def _ruta_str(self) -> str:
        """Devuelve la ruta absoluta manejando rutas largas en Windows."""
        p = str(self.ruta_cache.resolve())
        if os.name == "nt" and len(p) >= 200 and not p.startswith("\\\\?\\"):
            return f"\\\\?\\{p}"
        return p

    def _clave(self, texto: str, tipo: str) -> str:
        """Calcula la clave de caché de un texto.

        Args:
            texto: Contenido a vectorizar.
            tipo: ``documento`` o ``consulta`` (los modelos los tratan distinto).

        Returns:
            Hash hexadecimal SHA-256.
        """
        crudo = f"{self.nombre_modelo}|{tipo}|{texto}".encode("utf-8")
        return hashlib.sha256(crudo).hexdigest()

    def _leer(self, claves: Iterable[str]) -> dict[str, list[float]]:
        """Lee de la caché los vectores de un conjunto de claves.

        Args:
            claves: Claves a buscar.

        Returns:
            Diccionario ``clave -> vector`` solo con las claves encontradas.
        """
        claves = list(claves)
        if not claves:
            return {}
        marcadores = ",".join("?" for _ in claves)
        with sqlite3.connect(self._ruta_str()) as conexion:
            filas = conexion.execute(
                f"SELECT clave, vector FROM embeddings WHERE clave IN ({marcadores})",
                claves,
            ).fetchall()
        return {clave: json.loads(vector) for clave, vector in filas}

    def _guardar(self, pares: dict[str, list[float]]) -> None:
        """Persiste vectores nuevos en la caché.

        Args:
            pares: Diccionario ``clave -> vector`` a insertar.
        """
        if not pares:
            return
        with sqlite3.connect(self._ruta_str()) as conexion:
            conexion.executemany(
                "INSERT OR REPLACE INTO embeddings (clave, vector) VALUES (?, ?)",
                [(clave, json.dumps(vector)) for clave, vector in pares.items()],
            )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Vectoriza documentos, usando la caché para los ya conocidos.

        Args:
            texts: Fragmentos de texto a vectorizar.

        Returns:
            Lista de vectores en el mismo orden que ``texts``.
        """
        claves = [self._clave(texto, "documento") for texto in texts]
        conocidos = self._leer(claves)
        faltantes = [i for i, clave in enumerate(claves) if clave not in conocidos]
        self.aciertos += len(texts) - len(faltantes)
        self.fallos += len(faltantes)

        if faltantes:
            nuevos = reintentar_con_backoff(
                self.modelo_base.embed_documents,
                [texts[i] for i in faltantes],
            )
            recien_calculados = {
                claves[i]: vector for i, vector in zip(faltantes, nuevos)
            }
            self._guardar(recien_calculados)
            conocidos.update(recien_calculados)

        return [conocidos[clave] for clave in claves]

    def embed_query(self, text: str) -> list[float]:
        """Vectoriza una consulta, usando la caché si ya se preguntó lo mismo.

        Args:
            text: Consulta del usuario.

        Returns:
            Vector de la consulta.
        """
        clave = self._clave(text, "consulta")
        conocidos = self._leer([clave])
        if clave in conocidos:
            self.aciertos += 1
            return conocidos[clave]
        self.fallos += 1
        vector = reintentar_con_backoff(self.modelo_base.embed_query, text)
        self._guardar({clave: vector})
        return vector


# ---------------------------------------------------------------------------
# Validación y fábricas
# ---------------------------------------------------------------------------


def validar_configuracion(
    requiere_llm: bool = True, requiere_embeddings: bool = True
) -> list[str]:
    """Revisa que estén las claves necesarias y devuelve los problemas hallados.

    No lanza excepción: devolver la lista permite que la CLI, Streamlit y la
    evaluación decidan cómo presentar el error.

    Args:
        requiere_llm: Si la operación necesita el modelo de chat.
        requiere_embeddings: Si la operación necesita el modelo de embeddings.

    Returns:
        Lista de mensajes de error en español. Vacía si todo está en orden.
    """
    problemas: list[str] = []
    if requiere_llm and not LLM_API_KEY:
        problemas.append(
            "Falta LLM_API_KEY en el archivo .env (clave de Groq, se obtiene gratis "
            "en https://console.groq.com/keys)."
        )
    if requiere_llm and not LLM_BASE_URL:
        problemas.append(
            "Falta LLM_BASE_URL en el archivo .env "
            "(usar https://api.groq.com/openai/v1)."
        )
    if requiere_embeddings and not GOOGLE_API_KEY:
        problemas.append(
            "Falta GOOGLE_API_KEY en el archivo .env (clave de Google AI Studio, "
            "se obtiene gratis en https://aistudio.google.com/app/apikey)."
        )
    return problemas


def configurar_langsmith() -> bool:
    """Activa la trazabilidad de LangSmith solo si el entorno la define.

    Returns:
        True si LangSmith quedó activo; False si el sistema corre sin trazas
        (comportamiento normal y soportado).
    """
    activado = os.getenv("LANGCHAIN_TRACING_V2", "").lower() == "true"
    if not activado or not os.getenv("LANGCHAIN_API_KEY"):
        os.environ.pop("LANGCHAIN_TRACING_V2", None)
        return False
    os.environ.setdefault("LANGCHAIN_PROJECT", "mesa-ayuda-ti-rag")
    os.environ.setdefault("LANGCHAIN_ENDPOINT", "https://api.smith.langchain.com")
    return True


def crear_llm(temperatura: float = TEMPERATURA, max_tokens: int = MAX_TOKENS) -> Any:
    """Construye el modelo de chat de Groq a través del conector compatible.

    Args:
        temperatura: Temperatura de muestreo.
        max_tokens: Techo de tokens de la respuesta.

    Returns:
        Instancia de ``ChatOpenAI`` apuntada al endpoint de Groq.

    Raises:
        RuntimeError: Si falta alguna variable de entorno obligatoria.
    """
    problemas = validar_configuracion(requiere_llm=True, requiere_embeddings=False)
    if problemas:
        raise RuntimeError(" ".join(problemas))

    from langchain_openai import ChatOpenAI  # import diferido: acelera los tests

    configurar_langsmith()
    return ChatOpenAI(
        model=MODELO_CHAT,
        api_key=LLM_API_KEY,
        base_url=LLM_BASE_URL,
        temperature=temperatura,
        max_tokens=max_tokens,
        timeout=60,
        max_retries=0,  # el reintento lo maneja reintentar_con_backoff
    )


def crear_embeddings(usar_cache: bool = True) -> Embeddings:
    """Construye el modelo de embeddings de Gemini, con caché en disco.

    Se pide explícitamente ``output_dimensionality=768`` porque
    ``gemini-embedding-001`` entrega 3072 dimensiones por defecto y el índice
    FAISS del proyecto está dimensionado a 768. Si la versión instalada del
    conector no acepta ese parámetro, se cae con elegancia al constructor simple.

    Args:
        usar_cache: Si se envuelve el modelo en :class:`EmbeddingsConCache`.

    Returns:
        Instancia de embeddings lista para usar.

    Raises:
        RuntimeError: Si falta GOOGLE_API_KEY.
    """
    problemas = validar_configuracion(requiere_llm=False, requiere_embeddings=True)
    if problemas:
        raise RuntimeError(" ".join(problemas))

    from langchain_google_genai import GoogleGenerativeAIEmbeddings

    configurar_langsmith()
    try:
        base: Embeddings = GoogleGenerativeAIEmbeddings(
            model=MODELO_EMBEDDINGS,
            google_api_key=GOOGLE_API_KEY,
            output_dimensionality=DIMENSION_EMBEDDINGS,
        )
    except TypeError:
        base = GoogleGenerativeAIEmbeddings(
            model=MODELO_EMBEDDINGS,
            google_api_key=GOOGLE_API_KEY,
        )

    if not usar_cache:
        return base
    return EmbeddingsConCache(base, f"{MODELO_EMBEDDINGS}@{DIMENSION_EMBEDDINGS}")
