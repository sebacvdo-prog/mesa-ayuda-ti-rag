"""Prueba MANUAL real de Groq y CLI en tres procesos, con SQLite EP2 temporal.

python -m eval.check_ep2_plan
Consume cuota. No confirma notas, no altera el ITSM ni reconstruye FAISS.
"""

from __future__ import annotations

import argparse
import builtins
from contextlib import redirect_stdout
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from src import config

PREGUNTAS = {
    "inicial": "Consulta el ticket INC-2026-0411 y su SLA. Busca el procedimiento documentado para conectar la VPN corporativa con FortiClient y verificar el acceso a los recursos internos. No propongas notas todavía.",
    "impacto": "Ahora hay varios usuarios afectados. Reevalúa el impacto reportado del mismo ticket, distingue prioridad registrada y propuesta y propón una nota de seguimiento. No he confirmado ninguna escritura.",
    "reanudar": "Retoma el plan pendiente de esta sesión y muestra su estado desde la memoria, sin ejecutar acciones ni preparar nuevas notas. Explica qué falta para confirmar humanamente.",
}


def paso_real(fase: str, directorio: Path, intervalo: int) -> dict:
    from src.ep2 import cli
    from src.ep2.agente import AgenteEP2
    from src.ep2.almacenamiento import AlmacenEP2
    from src.ep2.contratos import ContextoEjecucion
    from src.ep2.memoria import MemoriaEP2
    from src.ep2.configuracion import ConfiguracionAgente, crear_llm_ep2
    from langchain_core.rate_limiters import InMemoryRateLimiter

    almacen = AlmacenEP2(directorio)
    contexto = ContextoEjecucion(usuario_id="plan_integracion", sesion_id="caso_vpn", perfil="agente")
    memoria = MemoriaEP2(almacen, contexto)
    antes = memoria.recuperar()
    respuestas, vistas, modelos = [], {}, []
    mostrar = cli.mostrar_trazabilidad
    def registrar_vista(tipo, valor):
        if tipo.startswith("plan_"):
            vistas[tipo] = valor.model_dump(mode="json")
        mostrar(tipo, valor)
    def crear(servicio):
        opciones = ConfiguracionAgente.desde_entorno().model_copy(update={"max_segundos": 300})
        llm = crear_llm_ep2(opciones)
        if intervalo:
            limitador = InMemoryRateLimiter(requests_per_second=1/intervalo, check_every_n_seconds=0.1, max_bucket_size=1)
            limitador.available_tokens = 1  # Primera petición inmediata, sin ráfagas posteriores.
            llm.rate_limiter = limitador
        agente = AgenteEP2(servicio, llm=llm, opciones=opciones)
        modelos.append(agente.opciones.modelo)
        responder = agente.responder
        def capturar(consulta):
            respuesta = responder(consulta)  # Un único ciclo real.
            respuestas.append(respuesta)
            return respuesta
        agente.responder = capturar
        return agente
    # Adaptadores de prueba solo para ubicación SQLite, entrada humana guionada
    # y captura de evidencia. LLM, herramientas, FAISS y CLI son los reales.
    cli.AlmacenEP2 = lambda: almacen
    cli.AgenteEP2 = crear
    cli.mostrar_trazabilidad = registrar_vista
    entregada = False
    def entrada(prompt):
        nonlocal entregada
        if prompt.startswith("Escribe CONFIRMAR"):
            return "POSPONER"
        if not entregada:
            entregada = True
            return PREGUNTAS[fase]
        return "/salir"
    builtins.input = entrada
    sys.argv = ["ep2.cli", "--usuario", contexto.usuario_id, "--sesion", contexto.sesion_id, "--perfil", contexto.perfil]
    salida = io.StringIO()
    with redirect_stdout(salida):
        cli.main()
    despues = memoria.recuperar()
    r = respuestas[-1]
    with almacen._conexion() as c:
        notas = c.execute("SELECT COUNT(*) FROM notas").fetchone()[0]
        auditoria = c.execute("SELECT COUNT(*) FROM auditoria").fetchone()[0]
    return {"fase": fase, "pid": os.getpid(), "modelo": modelos[-1],
            "intervalo_llm_segundos": intervalo, "presupuesto_evaluacion_segundos": 300,
            "consulta": PREGUNTAS[fase], "estado": r.estado, "memoria_estado": r.memoria_estado,
            "respuesta": r.texto, "herramientas": [t.model_dump() for t in r.herramientas],
            "plan_recuperado_antes": antes.plan.model_dump(mode="json") if antes.plan else None,
            "plan_inicial": vistas["plan_inicial"], "plan_final": despues.plan.model_dump(mode="json"),
            "cantidad_confirmaciones": len(r.confirmaciones), "notas": notas, "auditoria": auditoria,
            "traza_cli": salida.getvalue()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fase", choices=tuple(PREGUNTAS), help=argparse.SUPPRESS)
    parser.add_argument("--directorio", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--pausa-segundos", type=int, default=60, choices=range(0,61),
                        help="Pausa entre fases para respetar la cuota por minuto; predeterminado 60.")
    parser.add_argument("--intervalo-llm-segundos", type=int, default=35, choices=range(0,61),
                        help="Ritmo del LLM solo en esta prueba manual; predeterminado 35 segundos.")
    args = parser.parse_args()
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    if args.fase:
        if not args.directorio or args.directorio.resolve().parent != config.DIR_CACHE.resolve() or not args.directorio.name.startswith("ep2-plan-real-"):
            parser.error("Se requiere un directorio temporal ep2-plan-real-* bajo .cache.")
        print(json.dumps(paso_real(args.fase, args.directorio, args.intervalo_llm_segundos), ensure_ascii=False), flush=True)
        return
    config.DIR_CACHE.mkdir(parents=True, exist_ok=True)
    original = hashlib.sha256(config.RUTA_BD.read_bytes()).hexdigest()
    pasos = []
    with tempfile.TemporaryDirectory(dir=config.DIR_CACHE, prefix="ep2-plan-real-") as temporal:
        assert Path(temporal).resolve().parent == config.DIR_CACHE.resolve()
        for numero, fase in enumerate(PREGUNTAS):
            if numero and args.pausa_segundos:
                print(json.dumps({"pausa_entre_fases_segundos": args.pausa_segundos}), flush=True)
                time.sleep(args.pausa_segundos)
            proceso = subprocess.run([sys.executable, "-m", "eval.check_ep2_plan", "--fase", fase, "--directorio", temporal,
                                     "--intervalo-llm-segundos", str(args.intervalo_llm_segundos)],
                cwd=config.RAIZ_PROYECTO, capture_output=True, text=True, encoding="utf-8", timeout=360,
                env={**os.environ, "PYTHONIOENCODING": "utf-8"})
            if proceso.returncode:
                pasos.append({"fase": fase, "estado": "error_proceso", "exit_code": proceso.returncode})
                print(json.dumps(pasos[-1]), flush=True)
                break  # No imprimir excepciones del proveedor.
            dato = json.loads(proceso.stdout)
            pasos.append(dato)
            print(json.dumps({"fase": fase, "estado": dato["estado"], "herramientas": dato["herramientas"]}, ensure_ascii=False), flush=True)
    primero, segundo, tercero = (pasos + [{}, {}, {}])[:3]
    p1, p2, p3 = [p.get("plan_final") or {} for p in (primero, segundo, tercero)]
    ejecutadas = lambda p: {t["nombre"] for t in p.get("herramientas", []) if t["estado"] == "ok"}
    verificaciones = {
        "tres_procesos_distintos": len({p.get("pid") for p in pasos if p.get("pid")}) == 3,
        "consulta_ticket_sla_faiss": {"consultar_ticket", "consultar_sla", "buscar_procedimiento"} <= ejecutadas(primero),
        "caso_inicial_ok": primero.get("estado") == "ok" and all(s["estado"] == "completado" for s in p1.get("pasos", [])),
        "mismo_plan_tras_reportar": bool(p1.get("id")) and p1.get("id") == p2.get("id"),
        "revision_avanza": p2.get("revision", 0) > p1.get("revision", 0),
        "impacto_reportado_no_verificado": p2.get("impacto_reportado") == "multiples_usuarios" and p2.get("impacto_verificado") is False,
        "registrada_y_propuesta_p2": p2.get("prioridad_registrada") == "P2" and p2.get("prioridad_propuesta") == "P2",
        "reevaluacion_real": {"consultar_ticket", "consultar_sla", "analizar_incidente"} <= ejecutadas(segundo),
        "nota_pendiente_sin_autorizar": segundo.get("estado") == "requiere_confirmacion" and segundo.get("cantidad_confirmaciones") == 1,
        "reapertura_recupera_plan": bool(p3.get("id")) and p3.get("id") == p2.get("id") and tercero.get("estado") == "ok",
        "reapertura_conserva_pendiente": any(s["herramienta"] == "registrar_nota_ticket" and s["estado"] == "bloqueado" for s in p3.get("pasos", [])),
        "sin_nueva_propuesta_al_reanudar": tercero.get("cantidad_confirmaciones") == 0 and not tercero.get("herramientas"),
        "sin_escrituras_de_negocio": len(pasos) == 3 and all(p.get("notas") == 0 and p.get("auditoria") == 0 for p in pasos),
        "itsm_intacto": hashlib.sha256(config.RUTA_BD.read_bytes()).hexdigest() == original,
        "memoria_guardada": len(pasos) == 3 and all(p.get("memoria_estado") == "actualizada" for p in pasos),
    }
    intento = {"fecha_utc": datetime.now(timezone.utc).isoformat(), "pasos": pasos,
               "versiones": {p: importlib.metadata.version(p) for p in ("langchain", "langchain-core", "langchain-openai")},
               "fuentes_sha256": {p: hashlib.sha256((config.RAIZ_PROYECTO / p).read_bytes()).hexdigest() for p in (
                   "src/ep2/agente.py", "src/ep2/planificacion.py", "src/ep2/memoria.py",
                   "src/ep2/contratos.py", "src/ep2/cli.py", "src/ep2/herramientas.py", "eval/check_ep2_plan.py")},
               "verificaciones": verificaciones, "aprobado": all(verificaciones.values())}
    salida = config.DIR_CACHE / "ep2_plan_real.json"
    informe = json.loads(salida.read_text(encoding="utf-8")) if salida.exists() else {"intentos": []}
    informe["intentos"].append(intento)
    salida.write_text(json.dumps(informe, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"aprobado": intento["aprobado"], "verificaciones": verificaciones}, ensure_ascii=False), flush=True)
    if not intento["aprobado"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
