"""Diagnóstico RAG local: python -m eval.check_ep2_retrieval --consulta KB-RED-02.

No construye un LLM, no escribe en la caché de embeddings ni en el ITSM.
Solo usa Hugging Face ya descargado; toda conexión de red queda bloqueada.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from unittest.mock import patch

from langsmith import tracing_context

from src import config
from src.ep2.almacenamiento import AlmacenEP2
from src.ep2.contratos import ConsultaProcedimiento, ContextoEjecucion
from src.ep2.herramientas import HerramientasEP2
from src.retriever import RecuperadorVectorial


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--consulta", default="KB-RED-02")
    parser.add_argument("--fuente", choices=("automatica", "interna", "externa", "mixta"), default="automatica")
    parser.add_argument("--perfil", choices=("agente", "usuario_final"), default="agente")
    args = parser.parse_args(argv)
    if config.PROVEEDOR_EMBEDDINGS != "huggingface":
        parser.error("El diagnóstico sin red requiere el proveedor local configurado; no cambia la configuración.")
    entrada = ConsultaProcedimiento(consulta=args.consulta, fuente=args.fuente)
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    intentos = []
    activo = True

    def sin_red(evento, argumentos):
        if activo and evento in ("socket.connect", "socket.getaddrinfo", "socket.sendto"):
            intentos.append(evento)
            raise RuntimeError("RED_BLOQUEADA_EN_DIAGNOSTICO")

    sys.addaudithook(sin_red)
    crear_embeddings = config.crear_embeddings
    try:
        with tracing_context(enabled=False), patch.object(config, "configurar_langsmith", lambda: False), patch.object(
            config, "crear_embeddings", lambda: crear_embeddings(usar_cache=False)
        ), tempfile.TemporaryDirectory(prefix="ep2-rag-") as temporal:
            trazas = []
            recuperador = RecuperadorVectorial()
            recuperador.diagnosticar = trazas.append
            # Control que reproduce la ruta semántica anterior con el mismo índice.
            recuperador.buscar(entrada.consulta, perfil=args.perfil,
                               clasificacion=None if entrada.fuente == "automatica" else entrada.fuente)
            servicio = HerramientasEP2(ContextoEjecucion(usuario_id="diagnostico", sesion_id="local", perfil=args.perfil),
                                      AlmacenEP2(temporal))
            resultado = servicio.buscar_procedimiento(entrada, recuperador)
            print(json.dumps({"diagnosticos": trazas, "resultado": resultado.codigo,
                              "fuentes": list(resultado.procedencia), "intentos_red": len(intentos)},
                             ensure_ascii=False, indent=2, allow_nan=False))
            return int(resultado.estado != "ok" or bool(intentos))
    except Exception:
        # No imprimir excepción, texto de consulta, credenciales ni contenido documental.
        print(json.dumps({"resultado": "ERROR_DIAGNOSTICO_LOCAL", "intentos_red": len(intentos)}))
        return 1
    finally:
        # Los audit hooks no pueden quitarse: desactivar al salir evita que este
        # diagnóstico altere herramientas posteriores dentro del mismo proceso.
        activo = False


if __name__ == "__main__":
    raise SystemExit(main())
