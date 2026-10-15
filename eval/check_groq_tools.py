"""Prueba real y manual de compatibilidad; no registra notas ni cambia el modelo.

python -m eval.check_groq_tools
python -m eval.check_groq_tools --model ID_DISPONIBLE
La alternativa se aplica únicamente a la instancia temporal de esta prueba.
"""

from __future__ import annotations

import argparse
import json
import os

from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import tool

from src import config


@tool
def consultar_estado_simulado(id_ticket: str) -> str:
    """Consulta un ticket ficticio de prueba, sin acceso a bases ni escritura."""
    return json.dumps({"id_ticket": id_ticket, "estado": "en_revision", "marca": "EP2_COMPAT_OK"})


def comprobar(modelo: str | None = None) -> dict:
    # La prueba contiene solo datos sintéticos y no genera trazas externas adicionales.
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    llm = config.crear_llm()
    if modelo is not None:
        llm.model_name = modelo
    prompt = ChatPromptTemplate.from_messages([
        ("system", "Consulta obligatoriamente consultar_estado_simulado con el ticket solicitado. "
         "Después informa exactamente estado y marca devueltos."),
        ("human", "{input}"), MessagesPlaceholder("agent_scratchpad"),
    ])
    agente = create_tool_calling_agent(llm, [consultar_estado_simulado], prompt)
    ejecutor = AgentExecutor(
        agent=agente, tools=[consultar_estado_simulado], return_intermediate_steps=True,
        max_iterations=3, max_execution_time=45,
    )
    salida = ejecutor.invoke({"input": "Consulta INC-2026-0411 e informa su estado y marca."})
    pasos = salida["intermediate_steps"]
    correcto = any(a.tool == "consultar_estado_simulado"
                   and a.tool_input.get("id_ticket") == "INC-2026-0411" for a, _ in pasos)
    correcto = correcto and "EP2_COMPAT_OK" in salida["output"] and "en_revision" in salida["output"]
    return {"compatible": correcto, "modelo_probado": llm.model_name,
            "modelo_configurado": config.MODELO_CHAT,
            "herramientas_ejecutadas": [a.tool for a, _ in pasos]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", help="Alternativa temporal; no modifica .env ni dependencias.")
    argumentos = parser.parse_args()
    try:
        resultado = comprobar(argumentos.model)
    except Exception as error:
        # No imprimir cuerpos, cabeceras ni excepciones que puedan incluir secretos.
        resultado = {"compatible": False, "tipo_error": type(error).__name__,
                     "http_status": getattr(error, "status_code", None)}
    print(json.dumps(resultado, ensure_ascii=False))
    if not resultado["compatible"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
