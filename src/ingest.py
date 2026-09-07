"""Pipeline de ingesta: documentos Markdown a índice vectorial FAISS.

Flujo:

    carga -> normalización -> fragmentación -> metadatos -> embeddings -> FAISS

Solo se indexan **documentos**. Los tickets y la CMDB viven en SQLite y se
consultan por SQL (ver :mod:`src.retriever`), porque son datos estructurados,
cambiantes y con identificadores exactos: vectorizarlos degradaría la búsqueda y
expondría datos personales al proveedor de embeddings.

La ingesta es idempotente: se guarda un manifiesto con el hash del corpus y de
los parámetros de fragmentación. Si nada cambió, no se recalculan embeddings.

Uso:
    python -m src.ingest
    python -m src.ingest --forzar
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any, Iterable

from langchain_core.documents import Document

from src import config

try:  # LangChain 0.3 separa los splitters en su propio paquete
    from langchain_text_splitters import RecursiveCharacterTextSplitter
except ImportError:  # pragma: no cover - compatibilidad con instalaciones viejas
    from langchain.text_splitter import RecursiveCharacterTextSplitter

# Separadores en orden de preferencia: primero se intenta cortar por encabezado
# de sección, luego por párrafo, y solo al final por carácter. Así un fragmento
# rara vez parte un procedimiento numerado por la mitad.
SEPARADORES: list[str] = ["\n## ", "\n### ", "\n\n", "\n", ". ", " ", ""]

_PATRON_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


# ---------------------------------------------------------------------------
# Carga y normalización
# ---------------------------------------------------------------------------


def separar_frontmatter(texto: str) -> tuple[dict[str, str], str]:
    """Separa el encabezado YAML simple de un documento de su cuerpo.

    Se implementa un parser mínimo (``clave: valor`` por línea) en vez de usar
    PyYAML, para no agregar una dependencia por seis campos de texto plano.

    Args:
        texto: Contenido completo del archivo Markdown.

    Returns:
        Tupla ``(metadatos, cuerpo)``. Si no hay encabezado, los metadatos son un
        diccionario vacío y el cuerpo es el texto original.
    """
    coincidencia = _PATRON_FRONTMATTER.match(texto)
    if not coincidencia:
        return {}, texto

    metadatos: dict[str, str] = {}
    for linea in coincidencia.group(1).splitlines():
        if ":" not in linea:
            continue
        clave, _, valor = linea.partition(":")
        metadatos[clave.strip()] = valor.strip().strip('"').strip("'")
    return metadatos, texto[coincidencia.end():]


def normalizar_texto(texto: str) -> str:
    """Normaliza un documento antes de fragmentarlo.

    Unifica saltos de línea, elimina espacios al final de cada línea y colapsa
    las líneas en blanco repetidas. No toca las tablas ni las listas: cambiar su
    estructura empeoraría la legibilidad del fragmento recuperado.

    Args:
        texto: Cuerpo del documento.

    Returns:
        Texto normalizado.
    """
    texto = texto.replace("\r\n", "\n").replace("\r", "\n")
    texto = "\n".join(linea.rstrip() for linea in texto.split("\n"))
    texto = re.sub(r"\n{3,}", "\n\n", texto)
    return texto.strip()


def cargar_documentos(directorio: Path, fuente: str) -> list[Document]:
    """Carga los ``.md`` de un directorio como documentos de LangChain.

    Args:
        directorio: Carpeta a recorrer (``data/internos`` o ``data/externos``).
        fuente: Valor del metadato ``fuente``: ``interna`` o ``externa``.

    Returns:
        Lista de documentos con su texto normalizado y sus metadatos.

    Raises:
        FileNotFoundError: Si el directorio no existe.
    """
    if not directorio.exists():
        raise FileNotFoundError(f"No existe el directorio de corpus: {directorio}")

    documentos: list[Document] = []
    for ruta in sorted(directorio.glob("*.md")):
        crudo = ruta.read_text(encoding="utf-8")
        encabezado, cuerpo = separar_frontmatter(crudo)
        documentos.append(
            Document(
                page_content=normalizar_texto(cuerpo),
                metadata={
                    "fuente": fuente,
                    "documento": ruta.name,
                    "titulo": encabezado.get("titulo", ruta.stem),
                    "fecha_vigencia": encabezado.get("fecha_vigencia", "1970-01-01"),
                    "nivel_acceso": encabezado.get("nivel_acceso", "publico_interno"),
                    "fuente_url": encabezado.get("fuente_url", ""),
                    "ruta": str(ruta.relative_to(config.RAIZ_PROYECTO)),
                },
            )
        )
    return documentos


def cargar_corpus() -> list[Document]:
    """Carga el corpus completo: documentos internos y externos.

    Returns:
        Lista de documentos sin fragmentar.
    """
    return cargar_documentos(config.DIR_INTERNOS, "interna") + cargar_documentos(
        config.DIR_EXTERNOS, "externa"
    )


# ---------------------------------------------------------------------------
# Fragmentación
# ---------------------------------------------------------------------------


def crear_splitter() -> RecursiveCharacterTextSplitter:
    """Construye el fragmentador con los parámetros del proyecto.

    Returns:
        ``RecursiveCharacterTextSplitter`` de 900 caracteres con 150 de solape.
    """
    return RecursiveCharacterTextSplitter(
        chunk_size=config.TAMANO_CHUNK,
        chunk_overlap=config.SOLAPE_CHUNK,
        separators=SEPARADORES,
        length_function=len,
        keep_separator=True,
    )


def fragmentar(documentos: Iterable[Document]) -> list[Document]:
    """Fragmenta documentos y enriquece los metadatos de cada trozo.

    A cada fragmento se le agrega ``chunk`` (índice dentro del documento) y
    ``id_fragmento`` (identificador estable ``documento#n``), útiles para citar y
    para depurar la recuperación.

    Args:
        documentos: Documentos completos ya normalizados.

    Returns:
        Lista de fragmentos listos para vectorizar.
    """
    splitter = crear_splitter()
    fragmentos: list[Document] = []
    for documento in documentos:
        trozos = splitter.split_documents([documento])
        for indice, trozo in enumerate(trozos):
            trozo.metadata = dict(trozo.metadata)
            trozo.metadata["chunk"] = indice
            trozo.metadata["id_fragmento"] = f"{trozo.metadata['documento']}#{indice}"
            fragmentos.append(trozo)
    return fragmentos


def contar_por_documento(fragmentos: Iterable[Document]) -> dict[str, int]:
    """Cuenta cuántos fragmentos aportó cada documento.

    Args:
        fragmentos: Fragmentos generados por :func:`fragmentar`.

    Returns:
        Diccionario ``nombre_de_documento -> cantidad de fragmentos``.
    """
    conteo: dict[str, int] = {}
    for fragmento in fragmentos:
        nombre = fragmento.metadata.get("documento", "desconocido")
        conteo[nombre] = conteo.get(nombre, 0) + 1
    return conteo


# ---------------------------------------------------------------------------
# Idempotencia
# ---------------------------------------------------------------------------


def calcular_huella(documentos: Iterable[Document]) -> str:
    """Calcula una huella del corpus y de los parámetros de fragmentación.

    Si la huella no cambió, el índice existente sigue siendo válido y no hace
    falta gastar cuota de embeddings.

    Args:
        documentos: Documentos completos del corpus.

    Returns:
        Hash hexadecimal SHA-256.
    """
    hasher = hashlib.sha256()
    hasher.update(
        f"{config.TAMANO_CHUNK}|{config.SOLAPE_CHUNK}|{config.MODELO_EMBEDDINGS}|"
        f"{config.DIMENSION_EMBEDDINGS}".encode("utf-8")
    )
    for documento in sorted(documentos, key=lambda d: d.metadata["documento"]):
        hasher.update(documento.metadata["documento"].encode("utf-8"))
        hasher.update(documento.page_content.encode("utf-8"))
    return hasher.hexdigest()


def leer_manifiesto() -> dict[str, Any]:
    """Lee el manifiesto de la última ingesta.

    Returns:
        Contenido del manifiesto, o diccionario vacío si no existe.
    """
    if not config.RUTA_MANIFIESTO_INGESTA.exists():
        return {}
    try:
        return json.loads(config.RUTA_MANIFIESTO_INGESTA.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def escribir_manifiesto(datos: dict[str, Any]) -> None:
    """Guarda el manifiesto de la ingesta.

    Args:
        datos: Diccionario con la huella y las estadísticas de la corrida.
    """
    config.RUTA_MANIFIESTO_INGESTA.parent.mkdir(parents=True, exist_ok=True)
    config.RUTA_MANIFIESTO_INGESTA.write_text(
        json.dumps(datos, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Ingesta
# ---------------------------------------------------------------------------


def ingestar(forzar: bool = False) -> dict[str, Any]:
    """Ejecuta la ingesta completa y persiste el índice FAISS en disco.

    Args:
        forzar: Si es ``True``, reconstruye el índice aunque el corpus no haya
            cambiado.

    Returns:
        Resumen de la corrida: huella, totales y fragmentos por documento.

    Raises:
        RuntimeError: Si falta ``GOOGLE_API_KEY``.
        config.ErrorDeCuota: Si el proveedor de embeddings agota la cuota.
    """
    documentos = cargar_corpus()
    if not documentos:
        raise RuntimeError(
            "El corpus está vacío. Verificá que existan archivos .md en "
            f"{config.DIR_INTERNOS} y {config.DIR_EXTERNOS}."
        )

    huella = calcular_huella(documentos)
    manifiesto = leer_manifiesto()
    indice_existe = (config.DIR_INDICE_FAISS / "index.faiss").exists()

    print("=" * 70)
    print("INGESTA DEL CORPUS · Mesa de Ayuda TI")
    print("=" * 70)
    print(f"Documentos internos: {sum(1 for d in documentos if d.metadata['fuente'] == 'interna')}")
    print(f"Documentos externos: {sum(1 for d in documentos if d.metadata['fuente'] == 'externa')}")

    if indice_existe and manifiesto.get("huella") == huella and not forzar:
        print("\nEl corpus no cambió desde la última ingesta: el índice sigue vigente.")
        print("No se recalcularon embeddings (se cuida la cuota diaria de Gemini).")
        print("Usá --forzar si querés reconstruirlo de todos modos.")
        print(f"\nÍndice vigente en: {config.DIR_INDICE_FAISS}")
        return manifiesto

    fragmentos = fragmentar(documentos)
    conteo = contar_por_documento(fragmentos)

    print(f"\nFragmentación: chunk_size={config.TAMANO_CHUNK}, "
          f"chunk_overlap={config.SOLAPE_CHUNK}")
    print("-" * 70)
    print(f"{'documento':<34}{'fuente':<10}{'vigencia':<13}{'chunks':>7}")
    print("-" * 70)
    for documento in documentos:
        nombre = documento.metadata["documento"]
        print(
            f"{nombre:<34}{documento.metadata['fuente']:<10}"
            f"{documento.metadata['fecha_vigencia']:<13}{conteo.get(nombre, 0):>7}"
        )
    print("-" * 70)
    print(f"{'TOTAL':<57}{len(fragmentos):>7}")

    longitudes = [len(f.page_content) for f in fragmentos]
    print(
        f"\nLongitud de fragmento: mínima {min(longitudes)}, "
        f"media {sum(longitudes) // len(longitudes)}, máxima {max(longitudes)} caracteres."
    )

    print("\nCalculando embeddings con "
          f"{config.MODELO_EMBEDDINGS} ({config.DIMENSION_EMBEDDINGS} dimensiones)...")
    embeddings = config.crear_embeddings()

    from langchain_community.vectorstores import FAISS  # import diferido

    almacen = FAISS.from_documents(fragmentos, embeddings)

    if config.DIR_INDICE_FAISS.exists():
        shutil.rmtree(config.DIR_INDICE_FAISS)
    config.DIR_INDICE_FAISS.parent.mkdir(parents=True, exist_ok=True)
    almacen.save_local(str(config.DIR_INDICE_FAISS))

    aciertos = getattr(embeddings, "aciertos", 0)
    fallos = getattr(embeddings, "fallos", 0)
    if aciertos or fallos:
        print(f"Caché de embeddings: {aciertos} reutilizados, {fallos} calculados.")

    resumen: dict[str, Any] = {
        "huella": huella,
        "modelo_embeddings": config.MODELO_EMBEDDINGS,
        "dimension": config.DIMENSION_EMBEDDINGS,
        "chunk_size": config.TAMANO_CHUNK,
        "chunk_overlap": config.SOLAPE_CHUNK,
        "documentos": len(documentos),
        "fragmentos": len(fragmentos),
        "fragmentos_por_documento": conteo,
    }
    escribir_manifiesto(resumen)

    print(f"\nÍndice FAISS guardado en: {config.DIR_INDICE_FAISS}")
    print("Listo. Siguiente paso: python -m src.cli")
    return resumen


def main() -> None:
    """Punto de entrada de consola."""
    parser = argparse.ArgumentParser(
        description="Construye el índice FAISS del corpus de la mesa de ayuda."
    )
    parser.add_argument(
        "--forzar",
        action="store_true",
        help="Reconstruye el índice aunque el corpus no haya cambiado.",
    )
    argumentos = parser.parse_args()

    problemas = config.validar_configuracion(
        requiere_llm=False, requiere_embeddings=True
    )
    if problemas:
        print("No se puede ingestar todavía:")
        for problema in problemas:
            print(f"  - {problema}")
        raise SystemExit(1)

    try:
        ingestar(forzar=argumentos.forzar)
    except config.ErrorDeCuota as error:
        print(f"\n{error}")
        raise SystemExit(2) from error


if __name__ == "__main__":
    main()
