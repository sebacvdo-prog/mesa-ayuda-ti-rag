"""Configuración exclusiva de EP2; EP1 conserva su fábrica y su LLM_MODEL."""

from __future__ import annotations

import os
from typing import Any

from pydantic import Field

from src import config
from src.ep2.contratos import Contrato


class ConfiguracionAgente(Contrato):
    modelo: str = Field(default="openai/gpt-oss-20b", min_length=1)
    max_iteraciones: int = Field(default=8, ge=1, le=30)
    max_segundos: float = Field(default=90, gt=0, le=300, allow_inf_nan=False)
    timeout_llm: float = Field(default=30, gt=0, le=60, allow_inf_nan=False)

    @classmethod
    def desde_entorno(cls) -> ConfiguracionAgente:
        return cls(
            modelo=os.getenv("EP2_LLM_MODEL", "openai/gpt-oss-20b"),
            max_iteraciones=os.getenv("EP2_MAX_ITERATIONS", "8"),
            max_segundos=os.getenv("EP2_MAX_SECONDS", "90"),
            timeout_llm=os.getenv("EP2_LLM_TIMEOUT", "30"),
        )


def crear_llm_ep2(opciones: ConfiguracionAgente) -> Any:
    problemas = config.validar_configuracion(requiere_llm=True, requiere_embeddings=False)
    if problemas:
        raise RuntimeError(" ".join(problemas))
    from langchain_openai import ChatOpenAI

    config.configurar_langsmith()
    return ChatOpenAI(
        model=opciones.modelo, api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL,
        temperature=config.TEMPERATURA, max_tokens=config.MAX_TOKENS,
        timeout=min(opciones.timeout_llm, opciones.max_segundos), max_retries=0,
    )
