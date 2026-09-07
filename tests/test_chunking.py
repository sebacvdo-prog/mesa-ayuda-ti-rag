"""Pruebas del pipeline de ingesta: encabezados, normalización y fragmentación.

Ninguna prueba de este archivo llama a la API de embeddings: se ejercita solo la
parte determinista del pipeline, que es la que puede romperse en silencio.
"""

from __future__ import annotations

import pytest
from langchain_core.documents import Document

from src import config, ingest


# ---------------------------------------------------------------------------
# Encabezado YAML
# ---------------------------------------------------------------------------


def test_separar_frontmatter_extrae_metadatos_y_cuerpo() -> None:
    """El encabezado se separa del cuerpo y las comillas se descartan."""
    texto = (
        "---\n"
        'titulo: "KB-ACC-01 · Cuentas y accesos"\n'
        "fecha_vigencia: 2026-04-20\n"
        "nivel_acceso: restringido_agentes\n"
        "---\n"
        "# Cuerpo del artículo\n"
    )
    metadatos, cuerpo = ingest.separar_frontmatter(texto)

    assert metadatos["titulo"] == "KB-ACC-01 · Cuentas y accesos"
    assert metadatos["fecha_vigencia"] == "2026-04-20"
    assert metadatos["nivel_acceso"] == "restringido_agentes"
    assert cuerpo.startswith("# Cuerpo del artículo")
    assert "titulo:" not in cuerpo


def test_separar_frontmatter_sin_encabezado_devuelve_texto_intacto() -> None:
    """Un documento sin encabezado no pierde contenido."""
    metadatos, cuerpo = ingest.separar_frontmatter("# Solo cuerpo\n\nTexto.")

    assert metadatos == {}
    assert cuerpo == "# Solo cuerpo\n\nTexto."


# ---------------------------------------------------------------------------
# Normalización
# ---------------------------------------------------------------------------


def test_normalizar_texto_colapsa_lineas_y_limpia_espacios() -> None:
    """Se unifican saltos de línea y se colapsan las líneas en blanco de más."""
    crudo = "Primera línea   \r\n\r\n\r\n\r\nSegunda línea\t\n"
    normalizado = ingest.normalizar_texto(crudo)

    assert "\r" not in normalizado
    assert "\n\n\n" not in normalizado
    assert normalizado == "Primera línea\n\nSegunda línea"


def test_normalizar_texto_conserva_tablas_markdown() -> None:
    """La normalización no debe romper las tablas del corpus."""
    tabla = "| Prioridad | Respuesta |\n|---|---|\n| P1 | 15 minutos |"
    assert ingest.normalizar_texto(tabla) == tabla


# ---------------------------------------------------------------------------
# Fragmentación
# ---------------------------------------------------------------------------


@pytest.fixture()
def documento_largo() -> Document:
    """Documento sintético lo bastante extenso como para generar varios chunks."""
    parrafo = (
        "El agente de Nivel 1 verifica la conectividad del equipo antes de "
        "intervenir el cliente VPN, registra la IP privada asignada y deja "
        "constancia en el ticket correspondiente. "
    )
    return Document(
        page_content="\n\n".join(f"## Sección {i}\n\n{parrafo * 3}" for i in range(8)),
        metadata={
            "fuente": "interna",
            "documento": "kb_prueba.md",
            "titulo": "KB de prueba",
            "fecha_vigencia": "2026-01-01",
            "nivel_acceso": "publico_interno",
        },
    )


def test_splitter_usa_los_parametros_del_proyecto() -> None:
    """El splitter se construye con 900 caracteres y 150 de solape."""
    splitter = ingest.crear_splitter()

    assert splitter._chunk_size == config.TAMANO_CHUNK == 900
    assert splitter._chunk_overlap == config.SOLAPE_CHUNK == 150


def test_fragmentar_respeta_el_tamano_maximo(documento_largo: Document) -> None:
    """Ningún fragmento supera de forma significativa el tamaño configurado."""
    fragmentos = ingest.fragmentar([documento_largo])

    assert len(fragmentos) > 1
    # El splitter recursivo puede exceder levemente el tamaño cuando no encuentra
    # un separador; se tolera un 15 % antes de considerarlo un defecto.
    limite = int(config.TAMANO_CHUNK * 1.15)
    assert all(len(f.page_content) <= limite for f in fragmentos)


def test_fragmentar_propaga_y_enriquece_metadatos(documento_largo: Document) -> None:
    """Cada fragmento hereda los metadatos y suma su índice e identificador."""
    fragmentos = ingest.fragmentar([documento_largo])

    for indice, fragmento in enumerate(fragmentos):
        assert fragmento.metadata["fuente"] == "interna"
        assert fragmento.metadata["documento"] == "kb_prueba.md"
        assert fragmento.metadata["fecha_vigencia"] == "2026-01-01"
        assert fragmento.metadata["nivel_acceso"] == "publico_interno"
        assert fragmento.metadata["chunk"] == indice
        assert fragmento.metadata["id_fragmento"] == f"kb_prueba.md#{indice}"


def test_contar_por_documento(documento_largo: Document) -> None:
    """El conteo por documento coincide con la cantidad de fragmentos."""
    fragmentos = ingest.fragmentar([documento_largo])
    conteo = ingest.contar_por_documento(fragmentos)

    assert conteo == {"kb_prueba.md": len(fragmentos)}


# ---------------------------------------------------------------------------
# Idempotencia
# ---------------------------------------------------------------------------


def test_huella_estable_y_sensible_al_contenido(documento_largo: Document) -> None:
    """La huella no cambia sin motivo, y sí cambia si el corpus cambia."""
    huella_inicial = ingest.calcular_huella([documento_largo])
    assert huella_inicial == ingest.calcular_huella([documento_largo])

    modificado = Document(
        page_content=documento_largo.page_content + "\n\nPárrafo agregado.",
        metadata=dict(documento_largo.metadata),
    )
    assert ingest.calcular_huella([modificado]) != huella_inicial


# ---------------------------------------------------------------------------
# Corpus real del repositorio
# ---------------------------------------------------------------------------


def test_corpus_del_repositorio_esta_completo_y_bien_etiquetado() -> None:
    """El corpus tiene 6 documentos internos y 3 externos, con metadatos válidos."""
    internos = ingest.cargar_documentos(config.DIR_INTERNOS, "interna")
    externos = ingest.cargar_documentos(config.DIR_EXTERNOS, "externa")

    assert len(internos) == 6
    assert len(externos) == 3

    for documento in internos + externos:
        metadatos = documento.metadata
        assert metadatos["titulo"], f"{metadatos['documento']} sin título"
        assert metadatos["nivel_acceso"] in config.NIVELES_ACCESO
        assert len(metadatos["fecha_vigencia"]) == 10
        assert documento.page_content.strip()


def test_corpus_real_se_fragmenta_sin_perder_documentos() -> None:
    """Todos los documentos del corpus aportan al menos un fragmento."""
    documentos = ingest.cargar_corpus()
    fragmentos = ingest.fragmentar(documentos)
    conteo = ingest.contar_por_documento(fragmentos)

    assert len(conteo) == len(documentos)
    assert all(cantidad >= 1 for cantidad in conteo.values())
