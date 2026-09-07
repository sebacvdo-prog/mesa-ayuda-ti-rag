"""Utilidades compartidas para las pruebas."""

from __future__ import annotations

from langchain_core.documents import Document
from src.retriever import FragmentoRecuperado


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
