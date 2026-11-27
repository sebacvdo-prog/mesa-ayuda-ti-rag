"""Utilidades compartidas para las pruebas."""

from __future__ import annotations

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from src.retriever import FragmentoRecuperado


def crear_faiss_de_prueba(pares: list[tuple[Document, list[float]]]):
    """FAISS real con vectores explícitos; ninguna API ni modelo descargado."""
    from langchain_community.vectorstores import FAISS

    class ConsultaFija(Embeddings):
        def embed_documents(self, texts):
            raise AssertionError("Los documentos ya tienen vectores de prueba")

        def embed_query(self, text):
            return [1.0, 0.0]

    return FAISS.from_embeddings(
        [(d.page_content, vector) for d, vector in pares], ConsultaFija(),
        metadatas=[d.metadata for d, _ in pares],
    )


def construir_fragmento_de_prueba(
    texto: str = "contenido de prueba",
    puntaje: float = 0.9,
    documento: str = "kb_prueba.md",
    titulo: str = "KB-TEST-01 · Título de prueba",
    fuente: str = "interna",
    fecha: str = "2026-01-01",
    nivel: str = "publico_interno",
) -> FragmentoRecuperado:
    """Crea un FragmentoRecuperado sintético para pruebas unitarias."""
    doc = Document(
        page_content=texto,
        metadata={
            "documento": documento,
            "titulo": titulo,
            "fuente": fuente,
            "fecha_vigencia": fecha,
            "nivel_acceso": nivel,
        },
    )
    return FragmentoRecuperado(documento=doc, puntaje=puntaje)
