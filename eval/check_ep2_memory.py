"""Integración MANUAL real de continuidad con Groq entre dos procesos Python.

python -m eval.check_ep2_memory
Consume cuota de Groq. Usa SQLite EP2 temporal y el ITSM original solo en lectura.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

from src import config

PREGUNTAS = {
    "iniciar": "Consulta el estado y la prioridad del ticket INC-2026-0411 para retomar este caso después.",
    "continuar": "Retomemos el mismo ticket de esta sesión. Consulta su SLA según su prioridad y dime el identificador del ticket.",
}


def ejecutar_paso(paso: str, directorio: Path) -> dict:
    from src.ep2.agente import AgenteEP2
    from src.ep2.almacenamiento import AlmacenEP2
    from src.ep2.contratos import ContextoEjecucion
    from src.ep2.herramientas import HerramientasEP2

    contexto = ContextoEjecucion(usuario_id="memoria_integracion", sesion_id="continuidad_01", perfil="agente")
    almacen = AlmacenEP2(directorio)
    agente = AgenteEP2(HerramientasEP2(contexto, almacen))
    antes = agente.memoria.recuperar()
    respuesta = agente.responder(PREGUNTAS[paso])
    despues = agente.memoria.recuperar()
    with almacen._conexion() as c:
        notas = c.execute("SELECT COUNT(*) FROM notas").fetchone()[0]
        auditoria = c.execute("SELECT COUNT(*) FROM auditoria").fetchone()[0]
    return {"paso": paso, "pid": os.getpid(), "modelo": agente.opciones.modelo,
            "consulta": PREGUNTAS[paso], "estado": respuesta.estado,
            "memoria_estado": respuesta.memoria_estado, "respuesta": respuesta.texto,
            "herramientas": [t.model_dump() for t in respuesta.herramientas],
            "ticket_antes": antes.ticket_activo, "ticket_despues": despues.ticket_activo,
            "intercambios_antes": len(antes.intercambios), "intercambios_despues": len(despues.intercambios),
            "hechos": [h.model_dump(mode="json") for h in despues.hechos],
            "notas": notas, "auditoria": auditoria}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paso", choices=tuple(PREGUNTAS), help=argparse.SUPPRESS)
    parser.add_argument("--directorio", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    if args.paso:
        if not args.directorio or not args.directorio.resolve().is_relative_to(config.DIR_CACHE.resolve()):
            parser.error("El proceso de verificación necesita un directorio temporal bajo .cache.")
        print(json.dumps(ejecutar_paso(args.paso, args.directorio), ensure_ascii=False), flush=True)
        return
    config.DIR_CACHE.mkdir(parents=True, exist_ok=True)
    original = hashlib.sha256(config.RUTA_BD.read_bytes()).hexdigest()
    pasos = []
    with tempfile.TemporaryDirectory(dir=config.DIR_CACHE, prefix="ep2-memoria-real-") as temporal:
        assert Path(temporal).resolve().parent == config.DIR_CACHE.resolve()
        for paso in PREGUNTAS:
            proceso = subprocess.run([sys.executable, "-m", "eval.check_ep2_memory", "--paso", paso,
                                      "--directorio", temporal], cwd=config.RAIZ_PROYECTO,
                                     capture_output=True, text=True, encoding="utf-8", timeout=180,
                                     env={**os.environ, "PYTHONIOENCODING": "utf-8"})
            if proceso.returncode:
                # No imprimir stderr: podría contener excepciones de proveedores.
                pasos.append({"paso": paso, "estado": "error_proceso", "exit_code": proceso.returncode})
                break
            pasos.append(json.loads(proceso.stdout))
    completo = len(pasos) == 2 and all(p.get("estado") == "ok" for p in pasos)
    primero, segundo = (pasos + [{}, {}])[:2]
    sla = next((h for h in segundo.get("hechos", []) if h["clave"] == "sla:P2"), {})
    texto = segundo.get("respuesta", "").replace("\u2011", "-").replace("\u2010", "-")
    verificaciones = {
        "dos_turnos_reales_ok": completo,
        "procesos_distintos": bool(primero.get("pid")) and primero.get("pid") != segundo.get("pid"),
        "ticket_inicial_verificado": any(h["nombre"] == "consultar_ticket" and h["estado"] == "ok" for h in primero.get("herramientas", [])),
        "segunda_consulta_sin_identificador": "INC-2026-0411" not in PREGUNTAS["continuar"],
        "contexto_recuperado_antes_de_llm": segundo.get("ticket_antes") == "INC-2026-0411" and segundo.get("intercambios_antes") == 1,
        "sla_consultado_autonomamente": any(h["nombre"] == "consultar_sla" and h["estado"] == "ok" for h in segundo.get("herramientas", [])),
        "sla_correcto_del_ticket": sla.get("valor", {}).get("primera_respuesta_min") == 30 and sla.get("valor", {}).get("resolucion_horas") == 8,
        "identificador_en_respuesta": "INC-2026-0411" in texto,
        "persistencia_segundo_turno": segundo.get("memoria_estado") == "actualizada" and segundo.get("intercambios_despues") == 2,
        "sin_escrituras_de_negocio": completo and all(p.get("notas") == 0 and p.get("auditoria") == 0 for p in pasos),
        "itsm_intacto": hashlib.sha256(config.RUTA_BD.read_bytes()).hexdigest() == original,
    }
    intento = {"fecha_utc": datetime.now(timezone.utc).isoformat(),
               "versiones": {p: importlib.metadata.version(p) for p in ("langchain", "langchain-core", "langchain-openai")},
               "pasos": pasos, "verificaciones": verificaciones, "aprobado": all(verificaciones.values())}
    salida = config.DIR_CACHE / "ep2_memoria_real.json"
    informe = json.loads(salida.read_text(encoding="utf-8")) if salida.exists() else {"intentos": []}
    informe["intentos"].append(intento)
    salida.write_text(json.dumps(informe, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"aprobado": intento["aprobado"], "verificaciones": verificaciones,
                      "herramientas_por_paso": [[h["nombre"] for h in p.get("herramientas", [])] for p in pasos]}, ensure_ascii=False), flush=True)
    print("Evidencia local:", salida)
    if not intento["aprobado"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
