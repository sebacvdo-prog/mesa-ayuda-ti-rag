"""Integración MANUAL real de EP2 con Groq y herramientas locales.

python -m eval.check_ep2_agent --offline-embeddings
python -m eval.check_ep2_agent --caso consultas
Consume cuota de Groq. No confirma notas ni modifica el ITSM original.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import sqlite3
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from src import config

CASOS = {
    "consultas": (
        "Revisa INC-2026-0411: consulta su estado y prioridad, después los tiempos "
        "de primera respuesta y resolución correspondientes y el activo asociado al ticket.",
        {"consultar_ticket", "consultar_sla", "consultar_activo"}, "ok",
    ),
    "analisis": (
        "Analiza el incidente INC-2026-0411 aplicando el triage disponible y explica "
        "qué decisión permite su estado registrado. No propongas cambios.",
        {"analizar_incidente"}, "ok",
    ),
    "rag": (
        "Busca el procedimiento documentado para conectar la VPN corporativa con "
        "FortiClient y verificar el acceso a los recursos internos.",
        {"buscar_procedimiento"}, "ok",
    ),
    "nota": (
        "Propón registrar en INC-2026-0411 la nota: 'Se solicita seguimiento del caso.' "
        "Presenta la vista previa. No he confirmado ninguna escritura.",
        {"registrar_nota_ticket"}, "requiere_confirmacion",
    ),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--caso", choices=tuple(CASOS), action="append")
    parser.add_argument("--offline-embeddings", action="store_true")
    argumentos = parser.parse_args()
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    if argumentos.offline_embeddings:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
    # LangChain puede importar huggingface_hub; el modo offline debe fijarse
    # antes de que ese paquete lea y almacene las variables de entorno.
    from src.ep2.agente import AgenteEP2
    from src.ep2.almacenamiento import AlmacenEP2
    from src.ep2.contratos import ContextoEjecucion
    from src.ep2.herramientas import HerramientasEP2

    config.DIR_CACHE.mkdir(parents=True, exist_ok=True)
    salida = config.DIR_CACHE / "ep2_integracion_real.json"
    informe = json.loads(salida.read_text(encoding="utf-8")) if salida.exists() else {"intentos": []}
    versiones = {p: importlib.metadata.version(p) for p in
                 ("langchain", "langchain-core", "langchain-openai", "langchain-huggingface")}
    original = hashlib.sha256(config.RUTA_BD.read_bytes()).hexdigest()
    aprobado = True
    with tempfile.TemporaryDirectory(dir=config.DIR_CACHE, prefix="ep2-integracion-") as temporal:
        assert Path(temporal).resolve().is_relative_to(config.DIR_CACHE.resolve())
        almacen = AlmacenEP2(Path(temporal))
        servicio = HerramientasEP2(
            ContextoEjecucion(usuario_id="agente_integracion", sesion_id="sesion_integracion", perfil="agente"),
            almacen,
        )
        agente = AgenteEP2(servicio)
        for nombre in argumentos.caso or CASOS:
            pregunta, esperadas, estado = CASOS[nombre]
            respuesta = agente.responder(pregunta)
            # El context manager de sqlite3 confirma/revierte, pero no cierra
            # la conexión. Cerrarla permite limpiar el directorio en Windows.
            with closing(sqlite3.connect(almacen.ruta)) as c:
                notas = c.execute("SELECT COUNT(*) FROM notas").fetchone()[0]
            ejecutadas = {t.nombre for t in respuesta.herramientas if t.estado in ("ok", "requiere_confirmacion")}
            verificaciones = {
                "estado_esperado": respuesta.estado == estado,
                "herramientas_esperadas": esperadas <= ejecutadas,
                "sin_escrituras": notas == 0 and respuesta.escrituras_realizadas == 0,
                "itsm_intacto": hashlib.sha256(config.RUTA_BD.read_bytes()).hexdigest() == original,
                "pausa_si_nota": nombre != "nota" or bool(respuesta.confirmaciones),
                "fuentes_si_rag": nombre != "rag" or any(f.startswith("corpus:") for f in respuesta.fuentes),
            }
            intento = {"fecha_utc": datetime.now(timezone.utc).isoformat(), "caso": nombre,
                       "modelo": agente.opciones.modelo, "versiones": versiones,
                       "consulta_sintetica": pregunta, "estado": respuesta.estado,
                       "respuesta": respuesta.texto,
                       "herramientas": [t.model_dump() for t in respuesta.herramientas],
                       "fuentes": list(respuesta.fuentes),
                       "verificaciones": verificaciones, "aprobado": all(verificaciones.values())}
            informe["intentos"].append(intento)
            salida.write_text(json.dumps(informe, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({k: intento[k] for k in ("caso", "modelo", "estado", "herramientas", "aprobado")}, ensure_ascii=False), flush=True)
            aprobado = aprobado and intento["aprobado"]
    print("Evidencia local:", salida)
    if not aprobado:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
