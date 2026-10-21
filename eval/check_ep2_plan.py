"""Prueba MANUAL real de Groq y CLI en tres procesos, con SQLite EP2 temporal.

python -m eval.check_ep2_plan
Consume cuota. No confirma notas, no altera el ITSM ni reconstruye FAISS.
"""

from __future__ import annotations

import argparse
import builtins
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

import httpx

from src import config

PREGUNTAS = {
    "inicial": "Consulta el ticket INC-2026-0411 y su SLA. Busca el procedimiento documentado para conectar la VPN corporativa con FortiClient y verificar el acceso a los recursos internos. No propongas notas todavía.",
    "impacto": "Ahora hay varios usuarios afectados. Reevalúa el impacto reportado del mismo ticket, distingue prioridad registrada y propuesta y propón una nota de seguimiento. No he confirmado ninguna escritura.",
    "reanudar": "Retoma el plan pendiente de esta sesión y muestra su estado desde la memoria, sin ejecutar acciones ni preparar nuevas notas. Explica qué falta para confirmar humanamente.",
}

HERRAMIENTAS = frozenset(("consultar_ticket", "consultar_sla", "consultar_activo",
                         "buscar_procedimiento", "analizar_incidente", "registrar_nota_ticket"))
ESTADOS_PASO = frozenset(("pendiente", "en_ejecucion", "completado", "bloqueado", "cancelado"))
FUENTES = ("src/ep2/agente.py", "src/ep2/planificacion.py", "src/ep2/memoria.py",
           "src/ep2/contratos.py", "src/ep2/cli.py", "src/ep2/herramientas.py", __file__)
LIMITACION_ESTIMACION = (
    "Estimacion operativa, no consumo real: bytes UTF-8 del payload mas 256 para entrada; "
    "reserva del maximo de salida cuando falta su uso. No es el tokenizador del modelo "
    "ni acredita facturacion, cache o saldo de cuota de la organizacion."
)

# Estos límites solo acotan observabilidad, nunca solicitudes, tokens o fases.
MAX_JSON_DIAGNOSTICO = 65_536
MAX_MENSAJE_DIAGNOSTICO = 4096
MAX_ROLES_DIAGNOSTICO = 128
CODIGOS_PROVEEDOR = frozenset(("tool_use_failed", "invalid_request_error", "invalid_parameter",
                              "unsupported_parameter", "context_length_exceeded", "rate_limit_exceeded"))
TIPOS_PROVEEDOR = frozenset(("invalid_request_error", "rate_limit_error", "api_error", "server_error"))
ROLES_DIAGNOSTICO = frozenset(("system", "developer", "user", "assistant", "tool", "function"))
PARAMETROS_DIAGNOSTICO = frozenset(("tools", "tool_choice", "parallel_tool_calls", "max_tokens",
                                   "max_completion_tokens", "response_format", "model", "temperature"))
PATRONES_DIAGNOSTICO = (
    ("HERRAMIENTA_NO_OFRECIDA", "TOOL_FUERA_OFERTA",
     r"\btool\b.{0,160}\bnot (?:in|present in|found in|listed in) (?:the )?(?:request\.tools|provided tools|available tools)\b"),
    ("HERRAMIENTA_NO_OFRECIDA", "TOOL_NO_DISPONIBLE",
     r"\btool\b.{0,160}\b(?:was not|is not) (?:provided|offered|available)\b"),
    ("ARGUMENTOS_JSON_INVALIDOS", "ARGUMENTOS_JSON",
     r"\b(?:tool call arguments|function arguments|arguments)\b.{0,100}\b(?:not (?:a )?valid json|invalid json|malformed json)\b"),
    ("ARGUMENTOS_JSON_INVALIDOS", "JSON_ARGUMENTOS",
     r"\b(?:invalid|malformed) json\b.{0,100}\b(?:arguments|tool call|function)\b"),
    ("ARGUMENTOS_JSON_INVALIDOS", "PARSEO_ARGUMENTOS",
     r"\b(?:failed|unable) to parse (?:the )?(?:tool |function )?arguments (?:as |to )?json\b"),
    ("HERRAMIENTA_REQUERIDA_AUSENTE", "REQUIRED_SIN_LLAMADA",
     r"\btool[_ ]choice (?:is )?required\b.{0,100}\b(?:did not|does not|didn't) call (?:a |any )?tool\b"),
    ("MENSAJES_INVALIDOS", "MENSAJES_MALFORMADOS", r"\b(?:invalid|malformed) messages\b"),
    ("PARAMETROS_INVALIDOS", "PARAMETRO_RECHAZADO", r"\b(?:unsupported|unrecognized|unknown|invalid) parameter\b"),
    ("PARAMETROS_INVALIDOS", "PARAMETRO_NO_ADMITIDO",
     r"\bparameter\b.{0,80}\b(?:not supported|not allowed)\b"),
)


def _valor_permitido(valor, permitidos) -> str:
    return valor if isinstance(valor, str) and valor in permitidos else "DESCONOCIDO"


def _json_acotado(contenido: bytes):
    if len(contenido) > MAX_JSON_DIAGNOSTICO:
        return None, "EXCESIVO"
    try:
        dato = json.loads(contenido)
    except (ValueError, RecursionError):
        return None, "NO_JSON"
    return (dato, "JSON_OBJETO") if isinstance(dato, dict) else (None, "JSON_NO_OBJETO")


def metadatos_solicitud(contenido: bytes) -> dict:
    """Solo estructura: nunca copia mensajes, argumentos, esquemas o cabeceras."""
    dato, estructura = _json_acotado(contenido)
    meta = {"bytes": len(contenido), "estructura": estructura, "cantidad_mensajes": None,
            "roles": [], "roles_truncados": False, "herramientas_ofrecidas": [],
            "tool_choice": "no_especificado", "funcion_elegida": None, "parallel_tool_calls": None}
    if dato is None:
        return meta
    mensajes = dato.get("messages")
    if isinstance(mensajes, list):
        meta["cantidad_mensajes"] = len(mensajes)
        meta["roles_truncados"] = len(mensajes) > MAX_ROLES_DIAGNOSTICO
        meta["roles"] = [_valor_permitido(m.get("role"), ROLES_DIAGNOSTICO)
                         if isinstance(m, dict) else "DESCONOCIDO"
                         for m in mensajes[:MAX_ROLES_DIAGNOSTICO]]
    herramientas = dato.get("tools")
    if isinstance(herramientas, list):
        for h in herramientas:
            funcion = h.get("function") if isinstance(h, dict) and h.get("type") == "function" else None
            nombre = funcion.get("name") if isinstance(funcion, dict) else None
            if isinstance(nombre, str) and nombre in HERRAMIENTAS and nombre not in meta["herramientas_ofrecidas"]:
                meta["herramientas_ofrecidas"].append(nombre)
    if "tool_choice" in dato:
        eleccion = dato["tool_choice"]
        meta["tool_choice"] = _valor_permitido(eleccion, ("auto", "required", "none"))
        if isinstance(eleccion, dict) and eleccion.get("type") == "function":
            meta["tool_choice"] = "funcion"
            funcion = eleccion.get("function")
            meta["funcion_elegida"] = _valor_permitido(
                funcion.get("name") if isinstance(funcion, dict) else None, HERRAMIENTAS)
    if type(dato.get("parallel_tool_calls")) is bool:
        meta["parallel_tool_calls"] = dato["parallel_tool_calls"]
    return meta


def diagnostico_http(respuesta: httpx.Response) -> dict:
    """Clasificación local orientativa; jamás serializa texto libre del proveedor."""
    cuerpo, estructura = _json_acotado(respuesta.content)
    diagnostico = {"codigo_proveedor": "DESCONOCIDO", "tipo_proveedor": "DESCONOCIDO",
                   "categoria": "NO_CLASIFICADO", "failed_generation_presente": None,
                   "fundamento": {"estructura": estructura, "fuente": "ninguna", "regla": "SIN_DETALLE"}}
    if cuerpo is None:
        return diagnostico
    error = cuerpo.get("error", cuerpo)
    if not isinstance(error, dict):
        diagnostico["fundamento"]["estructura"] = "ERROR_NO_OBJETO"
        return diagnostico
    diagnostico.update(codigo_proveedor=_valor_permitido(error.get("code"), CODIGOS_PROVEEDOR),
                       tipo_proveedor=_valor_permitido(error.get("type"), TIPOS_PROVEEDOR),
                       failed_generation_presente="failed_generation" in error)
    if respuesta.status_code != 400:
        diagnostico["fundamento"]["regla"] = "ESTADO_DISTINTO_DE_400"
        return diagnostico
    coincidencias = {}
    mensaje = error.get("message")
    if isinstance(mensaje, str) and len(mensaje) <= MAX_MENSAJE_DIAGNOSTICO:
        mensaje = re.sub(r"\s+", " ", mensaje).lower()
        for categoria, regla, patron in PATRONES_DIAGNOSTICO:
            if re.search(patron, mensaje):
                coincidencias.setdefault(categoria, ("patron_mensaje", regla))
    parametro = error.get("param")
    if isinstance(parametro, str) and parametro == "messages":
        coincidencias.setdefault("MENSAJES_INVALIDOS", ("parametro", "PARAM_MESSAGES"))
    elif isinstance(parametro, str) and parametro in PARAMETROS_DIAGNOSTICO:
        coincidencias.setdefault("PARAMETROS_INVALIDOS", ("parametro", "PARAM_CONOCIDO"))
    if diagnostico["codigo_proveedor"] in ("invalid_parameter", "unsupported_parameter"):
        coincidencias.setdefault("PARAMETROS_INVALIDOS", ("codigo_proveedor", "CODIGO_PARAMETRO"))
    if len(coincidencias) == 1:
        categoria, (fuente, regla) = next(iter(coincidencias.items()))
        diagnostico.update(categoria=categoria)
        diagnostico["fundamento"].update(fuente=fuente, regla=regla)
    else:
        diagnostico["fundamento"]["regla"] = "SENALES_AMBIGUAS" if coincidencias else "SIN_SENAL_ESPECIFICA"
    return diagnostico


@dataclass(frozen=True)
class Limites:
    max_solicitudes: int = 14
    presupuesto_tokens: int = 80_000
    max_tokens_salida: int = 2000
    segundos_fase: int = 300
    timeout_llm: int = 30
    timeout_proceso: int = 360
    intervalo_llm_segundos: int = 35
    pausa_segundos: int = 60


def guardar_json(ruta: Path, dato: dict) -> None:
    temporal = ruta.with_suffix(".tmp")
    temporal.write_text(json.dumps(dato, ensure_ascii=False, indent=2), encoding="utf-8")
    temporal.replace(ruta)


class DetencionEvaluacion(RuntimeError):
    """Codigo constante, sin cuerpos ni mensajes del proveedor."""


class Consumo:
    """Estado compartido por los tres procesos secuenciales, nunca en produccion."""

    def __init__(self, ruta: Path):
        self.ruta = ruta

    def leer(self) -> dict:
        return json.loads(self.ruta.read_text(encoding="utf-8"))

    def detener(self, motivo: str) -> None:
        dato = self.leer()
        dato["motivo_detencion"] = dato["motivo_detencion"] or motivo
        guardar_json(self.ruta, dato)

    def iniciar(self, fase: str, contenido: bytes) -> int:
        dato = self.leer()
        if dato["motivo_detencion"]:
            raise DetencionEvaluacion(dato["motivo_detencion"])
        limites = dato["limites"]
        entrada = len(contenido) + 256  # Reserva conservadora; no se guarda el payload.
        salida = limites["max_tokens_salida"]
        if fase != dato["fase_activa"]:
            motivo = "ORDEN_FASE_INVALIDO"
        elif len(dato["solicitudes"]) >= limites["max_solicitudes"]:
            motivo = "MAX_SOLICITUDES"
        elif self.total(dato) + entrada + salida > limites["presupuesto_tokens"]:
            motivo = "PRESUPUESTO_TOKENS"
        else:
            dato["solicitudes"].append({
                "fase": fase, "estado": "en_curso", "http_status": None,
                "entrada_informada": None, "salida_informada": None, "total_informado": None,
                "entrada_estimada": entrada, "salida_estimada": salida,
                "tokens_operativos": entrada + salida, "origen": "estimacion",
                "duracion_segundos": None,
                "solicitud": metadatos_solicitud(contenido), "diagnostico_proveedor": None,
            })
            # Se reserva ANTES de enviar: incluso un timeout o proceso muerto deja evidencia.
            guardar_json(self.ruta, dato)
            return len(dato["solicitudes"]) - 1
        self.detener(motivo)
        raise DetencionEvaluacion(motivo)

    @staticmethod
    def total(dato: dict) -> int:
        return sum(s["tokens_operativos"] for s in dato["solicitudes"])

    def terminar(self, numero: int, respuesta: httpx.Response | None, segundos: float) -> None:
        dato = self.leer()
        s = dato["solicitudes"][numero]
        s["duracion_segundos"] = round(segundos, 3)
        s["estado"] = "respuesta" if respuesta is not None else "error_transporte"
        if respuesta is not None:
            s["http_status"] = respuesta.status_code
            try:
                cuerpo = respuesta.json()
                uso = cuerpo.get("usage") or {}
                if not isinstance(uso, dict):
                    uso = {}
            except (ValueError, AttributeError, RecursionError):
                uso = {}
            for campo, opciones in (
                ("entrada_informada", ("prompt_tokens", "input_tokens")),
                ("salida_informada", ("completion_tokens", "output_tokens")),
                ("total_informado", ("total_tokens",)),
            ):
                s[campo] = next((uso[k] for k in opciones if type(uso.get(k)) is int and uso[k] >= 0), None)
            entrada, salida, total = (s[k] for k in ("entrada_informada", "salida_informada", "total_informado"))
            if total is not None or entrada is not None and salida is not None:
                s["tokens_operativos"] = max(total or 0, (entrada or 0) + (salida or 0))
                s["origen"] = "proveedor"
            else:
                s["tokens_operativos"] = ((entrada if entrada is not None else s["entrada_estimada"])
                                          + (salida if salida is not None else s["salida_estimada"]))
                s["origen"] = "mixto" if entrada is not None or salida is not None else "estimacion"
            if respuesta.status_code >= 400:
                s["diagnostico_proveedor"] = diagnostico_http(respuesta)
                dato["motivo_detencion"] = "HTTP_429" if respuesta.status_code == 429 else "ERROR_HTTP"
                espera = respuesta.headers.get("retry-after", "")
                if re.fullmatch(r"[0-9]{1,8}(?:\.[0-9]{1,3})?", espera):
                    s["retry_after_segundos"] = float(espera)
        else:
            dato["motivo_detencion"] = dato["motivo_detencion"] or "ERROR_TRANSPORTE"
        guardar_json(self.ruta, dato)


class TransporteControlado(httpx.BaseTransport):
    def __init__(self, delegado: httpx.BaseTransport, consumo: Consumo, fase: str):
        self.delegado, self.consumo, self.fase = delegado, consumo, fase

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        numero = self.consumo.iniciar(self.fase, request.read())
        inicio, respuesta, completa = time.monotonic(), None, False
        try:
            respuesta = self.delegado.handle_request(request)
            if respuesta.status_code == 429:
                self.consumo.detener("HTTP_429")
            respuesta.read()
            completa = True
            return respuesta
        except KeyboardInterrupt:
            self.consumo.detener("INTERRUMPIDO")
            raise
        finally:
            self.consumo.terminar(numero, respuesta if completa else None, time.monotonic() - inicio)

    def close(self) -> None:
        self.delegado.close()


def _codigo(valor) -> str | None:
    return valor if isinstance(valor, str) and re.fullmatch(r"[A-Z][A-Z0-9_]{0,63}", valor) else None


def plan_publico(plan: dict | None) -> dict | None:
    """Solo estructura del plan; sin objetivos, notas, motivos, documentos ni razonamiento."""
    if not plan:
        return None
    from uuid import UUID
    identificador = str(UUID(plan["id"]))
    return {
        "id": identificador, "revision": int(plan["revision"]),
        "impacto_reportado": plan.get("impacto_reportado") if plan.get("impacto_reportado") in
            ("no_informado", "multiples_usuarios") else None,
        "impacto_verificado": plan.get("impacto_verificado") if type(plan.get("impacto_verificado")) is bool else None,
        "prioridad_registrada": plan.get("prioridad_registrada") if plan.get("prioridad_registrada") in ("P1", "P2", "P3", "P4") else None,
        "prioridad_propuesta": plan.get("prioridad_propuesta") if plan.get("prioridad_propuesta") in ("P1", "P2", "P3", "P4") else None,
        "pasos": [{"id": p["id"] if re.fullmatch(r"p[0-9]{1,3}", p["id"]) else None,
                   "herramienta": p["herramienta"] if p["herramienta"] in HERRAMIENTAS else None,
                   "estado": p["estado"] if p["estado"] in ESTADOS_PASO else None,
                   "prioridad": int(p["prioridad"]), "codigo": _codigo(p.get("codigo")),
                   "intentos": int(p.get("intentos", 0)),
                   "dependencias": [d for d in p.get("dependencias", []) if re.fullmatch(r"p[0-9]{1,3}", d)]}
                  for p in plan.get("pasos", [])],
    }


def fase_publica(dato: dict) -> dict:
    return {
        "fase": dato["fase"] if dato["fase"] in PREGUNTAS else None,
        "pid": int(dato.get("pid", 0)),
        "estado": dato.get("estado") if dato.get("estado") in ("ok", "error", "limite", "requiere_confirmacion", "sin_contexto", "denegado") else "error",
        "memoria_estado": "actualizada" if dato.get("memoria_estado") == "actualizada" else "no_disponible",
        "http_429": dato.get("http_429") is True or bool(re.search(r"\bHTTP\s+429\b", str(dato.get("respuesta", "")), re.I)),
        "herramientas": [{"nombre": t["nombre"] if t["nombre"] in HERRAMIENTAS else "decision_rechazada",
                           "estado": t["estado"] if t["estado"] in ("ok", "error", "denegado", "requiere_confirmacion") else "error",
                           "codigo": _codigo(t.get("codigo"))} for t in dato.get("herramientas", [])],
        **{k: plan_publico(dato.get(k)) for k in ("plan_recuperado_antes", "plan_inicial", "plan_final")},
        **{k: int(dato.get(k, -1)) for k in ("cantidad_confirmaciones", "notas", "auditoria")},
        "decisiones": [decision_publica(d) for d in dato.get("decisiones", [])],
    }


def decision_publica(dato: dict) -> dict:
    """Lista permitida; descarta argumentos, textos del modelo y campos desconocidos."""
    return {"indice": int(dato["indice"]),
            "seleccion": [n if isinstance(n, str) and n in HERRAMIENTAS else "fuera_registro" for n in dato.get("seleccion", [])],
            "estado": dato["estado"] if dato.get("estado") in (
                "en_curso", "rechazada", "ejecutada", "respuesta", "error") else "error",
            "codigo": _codigo(dato.get("codigo")), "ejecutada": dato.get("ejecutada") is True,
            "modelo_respondio": dato.get("modelo_respondio") is True,
            "correccion": "_Exception" if dato.get("correccion") == "_Exception" else None,
            "habilitadas": [n for n in dato.get("habilitadas", []) if isinstance(n, str) and n in HERRAMIENTAS],
            "herramientas_ofrecidas": [n for n in dato.get("herramientas_ofrecidas", [])
                                       if isinstance(n, str) and n in HERRAMIENTAS],
            "estado_oferta": dato.get("estado_oferta") if dato.get("estado_oferta") in (
                "solo_estado", "sin_permisos", "consulta_flexible", "acciones_obligatorias",
                "plan_bloqueado", "plan_completado") else None,
            "tool_choice": dato.get("tool_choice") if dato.get("tool_choice") in ("auto", "required", "none") else None,
            "dependencias_faltantes": [d for d in dato.get("dependencias_faltantes", [])
                                       if isinstance(d, str) and re.fullmatch(r"p[0-9]{1,3}", d)],
            "prioridad_pendiente": dato.get("prioridad_pendiente") if type(dato.get("prioridad_pendiente")) is int
                and 1 <= dato["prioridad_pendiente"] <= 5 else None,
            **{k: plan_publico(dato.get(k)) for k in ("plan_antes", "plan_despues")}}


def paso_real(fase: str, directorio: Path, limites: Limites) -> dict:
    from src.ep2 import cli
    from src.ep2.agente import AgenteEP2
    from src.ep2.almacenamiento import AlmacenEP2
    from src.ep2.contratos import ContextoEjecucion
    from src.ep2.memoria import MemoriaEP2
    from src.ep2.configuracion import ConfiguracionAgente, crear_llm_ep2
    from langchain_core.rate_limiters import InMemoryRateLimiter

    consumo = Consumo(directorio / "control.json")
    almacen = AlmacenEP2(directorio)
    contexto = ContextoEjecucion(usuario_id="plan_integracion", sesion_id="caso_vpn", perfil="agente")
    memoria = MemoriaEP2(almacen, contexto)
    antes = memoria.recuperar()
    respuestas, vistas, decisiones = [], {}, []
    recursos = ExitStack()
    mostrar = cli.mostrar_trazabilidad
    resolver = cli.resolver_confirmaciones
    def registrar_vista(tipo, valor):
        if tipo.startswith("plan_"):
            vistas[tipo] = valor.model_dump(mode="json")
        mostrar(tipo, valor)
    def crear(servicio):
        opciones = ConfiguracionAgente.desde_entorno().model_copy(update={
            "max_segundos": limites.segundos_fase, "timeout_llm": limites.timeout_llm})
        llm = crear_llm_ep2(opciones)
        recursos.callback(llm.root_client.close)
        # Se cambia solo el cliente de esta prueba. El agente y su fabrica quedan intactos.
        transporte = TransporteControlado(httpx.HTTPTransport(retries=0), consumo, fase)
        cliente = recursos.enter_context(httpx.Client(transport=transporte, timeout=limites.timeout_llm,
                                                     follow_redirects=False))
        llm.root_client = llm.root_client.with_options(http_client=cliente, max_retries=0)
        llm.client = llm.root_client.chat.completions
        llm.max_retries, llm.max_tokens, llm.streaming = 0, limites.max_tokens_salida, False
        if limites.intervalo_llm_segundos:
            limitador = InMemoryRateLimiter(requests_per_second=1/limites.intervalo_llm_segundos,
                                            check_every_n_seconds=0.1, max_bucket_size=1)
            limitador.available_tokens = 1  # Primera petición inmediata, sin ráfagas posteriores.
            llm.rate_limiter = limitador
        agente = AgenteEP2(servicio, llm=llm, opciones=opciones)
        responder = agente.responder
        def capturar(consulta):
            respuesta = responder(consulta)  # Un único ciclo real.
            decisiones.extend(agente.decisiones)
            respuestas.append(respuesta)
            return respuesta
        agente.responder = capturar
        return agente
    # Adaptadores de prueba solo para ubicación SQLite, entrada humana guionada
    # y captura de evidencia. LLM, herramientas, FAISS y CLI son los reales.
    entregada = False
    def entrada(prompt):
        nonlocal entregada
        if prompt.startswith("Escribe CONFIRMAR"):
            return "POSPONER"
        if not entregada:
            entregada = True
            return PREGUNTAS[fase]
        return "/salir"
    salida = io.StringIO()
    with recursos, patch.object(cli, "AlmacenEP2", lambda: almacen), patch.object(cli, "AgenteEP2", crear), \
            patch.object(cli, "mostrar_trazabilidad", registrar_vista), patch.object(builtins, "input", entrada), \
            patch.object(cli, "resolver_confirmaciones", lambda agente, respuesta:
                         resolver(agente, respuesta, leer=entrada)), \
            patch.object(sys, "argv", ["ep2.cli", "--usuario", contexto.usuario_id, "--sesion", contexto.sesion_id,
                                       "--perfil", contexto.perfil]), redirect_stdout(salida), redirect_stderr(io.StringIO()):
        cli.main()
    despues = memoria.recuperar()
    r = respuestas[-1] if respuestas else None
    with almacen._conexion() as c:
        notas = c.execute("SELECT COUNT(*) FROM notas").fetchone()[0]
        auditoria = c.execute("SELECT COUNT(*) FROM auditoria").fetchone()[0]
    return fase_publica({"fase": fase, "pid": os.getpid(),
            "estado": r.estado if r else "error", "memoria_estado": r.memoria_estado if r else "no_disponible",
            "http_429": consumo.leer()["motivo_detencion"] == "HTTP_429" or bool(r and "HTTP 429" in r.texto),
            "herramientas": [t.model_dump() for t in r.herramientas] if r else [],
            "plan_recuperado_antes": antes.plan.model_dump(mode="json") if antes.plan else None,
            "plan_inicial": vistas.get("plan_inicial"), "plan_final": despues.plan.model_dump(mode="json") if despues.plan else None,
            "cantidad_confirmaciones": len(r.confirmaciones) if r else 0, "notas": notas, "auditoria": auditoria,
            "decisiones": decisiones})


def verificaciones(pasos: list[dict], itsm_intacto: bool) -> dict[str, bool]:
    primero, segundo, tercero = (pasos + [{}, {}, {}])[:3]
    p1, p2, p3 = [p.get("plan_final") or {} for p in (primero, segundo, tercero)]
    ejecutadas = lambda p: {t["nombre"] for t in p.get("herramientas", []) if t["estado"] == "ok"}
    verificaciones = {
        "tres_procesos_distintos": len({p.get("pid") for p in pasos if p.get("pid")}) == 3,
        "consulta_ticket_sla_faiss": {"consultar_ticket", "consultar_sla", "buscar_procedimiento"} <= ejecutadas(primero),
        "caso_inicial_ok": primero.get("estado") == "ok" and bool(p1.get("id")) and bool(p1.get("pasos")) and all(s["estado"] == "completado" for s in p1.get("pasos", [])),
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
        "itsm_intacto": itsm_intacto,
        "memoria_guardada": len(pasos) == 3 and all(p.get("memoria_estado") == "actualizada" for p in pasos),
    }
    return verificaciones


def fallo_fase(pasos: list[dict], itsm_intacto: bool) -> str | None:
    ultimo = pasos[-1]
    if ultimo["http_429"]:
        return "HTTP_429"
    if ultimo["estado"] == "limite":
        return "LIMITE_EJECUCION"
    if ultimo["estado"] not in ("ok", "requiere_confirmacion"):
        return "FASE_FALLIDA"
    if ultimo["notas"] != 0 or ultimo["auditoria"] != 0:
        return "ESCRITURAS_DETECTADAS"
    if ultimo["memoria_estado"] != "actualizada" or not itsm_intacto:
        return "INTEGRIDAD_O_MEMORIA"
    v = verificaciones(pasos, itsm_intacto)
    exigidas = {
        "inicial": ("consulta_ticket_sla_faiss", "caso_inicial_ok"),
        "impacto": ("mismo_plan_tras_reportar", "revision_avanza", "impacto_reportado_no_verificado",
                    "registrada_y_propuesta_p2", "reevaluacion_real", "nota_pendiente_sin_autorizar"),
        "reanudar": tuple(v),
    }
    return None if all(v[k] for k in exigidas[ultimo["fase"]]) else "VERIFICACIONES_FASE"


def clasificar_verificaciones(pasos: list[dict], valores: dict[str, bool]) -> dict[str, str]:
    """Clasificacion adicional: no cambia los quince predicados ni la aprobacion integral."""
    fases = {p["fase"] for p in pasos}
    inicial = {"consulta_ticket_sla_faiss", "caso_inicial_ok"}
    impacto = {"mismo_plan_tras_reportar", "revision_avanza", "impacto_reportado_no_verificado",
               "registrada_y_propuesta_p2", "reevaluacion_real", "nota_pendiente_sin_autorizar"}
    reanudar = {"reapertura_recupera_plan", "reapertura_conserva_pendiente", "sin_nueva_propuesta_al_reanudar"}
    clasificacion = {}
    for nombre, valor in valores.items():
        if valor:
            estado = "aprobada"
        elif nombre in ("sin_escrituras_de_negocio", "memoria_guardada") and len(pasos) < 3:
            favorable = bool(pasos) and all(
                p.get("notas") == 0 and p.get("auditoria") == 0 if nombre == "sin_escrituras_de_negocio"
                else p.get("memoria_estado") == "actualizada" for p in pasos)
            estado = "evidencia_parcial_favorable" if favorable else "fallida" if pasos else "no_ejecutada"
        elif nombre == "tres_procesos_distintos" and len(pasos) < 3:
            estado = "no_ejecutada"
        elif (nombre in inicial and "inicial" not in fases
              or nombre in impacto and "impacto" not in fases
              or nombre in reanudar and "reanudar" not in fases):
            estado = "no_ejecutada"
        else:
            estado = "fallida"
        clasificacion[nombre] = estado
    return clasificacion


def ejecutar_proceso(comando: list[str], timeout: int) -> subprocess.CompletedProcess:
    with subprocess.Popen(comando, cwd=config.RAIZ_PROYECTO, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, encoding="utf-8", env={**os.environ, "PYTHONIOENCODING": "utf-8"}) as proceso:
        try:
            salida, error = proceso.communicate(timeout=timeout)
        except BaseException:
            proceso.kill()
            proceso.communicate()
            raise
        return subprocess.CompletedProcess(comando, proceso.returncode, salida, error)


def ejecutar_integral(limites: Limites) -> int:
    config.DIR_CACHE.mkdir(parents=True, exist_ok=True)
    intento = {"fecha_utc": datetime.now(timezone.utc).isoformat(), "pasos": [], "aprobado": False,
               "motivo_detencion": None, "limites": asdict(limites),
               "limitacion_estimacion": LIMITACION_ESTIMACION,
               "versiones": {p: importlib.metadata.version(p) for p in ("langchain", "langchain-core", "langchain-openai")},
               "fuentes_sha256": {Path(p).name if Path(p).is_absolute() else p:
                   hashlib.sha256((config.RAIZ_PROYECTO / p).read_bytes()).hexdigest() for p in FUENTES}}
    with tempfile.TemporaryDirectory(dir=config.DIR_CACHE, prefix="ep2-plan-real-") as temporal:
        directorio = Path(temporal)
        consumo = Consumo(directorio / "control.json")
        guardar_json(consumo.ruta, {"limites": asdict(limites), "fase_activa": None,
                                   "solicitudes": [], "motivo_detencion": None})
        original = None
        try:
            original = hashlib.sha256(config.RUTA_BD.read_bytes()).hexdigest()
            for numero, fase in enumerate(PREGUNTAS):
                if numero:
                    dato = consumo.leer()
                    if len(dato["solicitudes"]) >= limites.max_solicitudes:
                        consumo.detener("MAX_SOLICITUDES")
                        break
                    if consumo.total(dato) >= limites.presupuesto_tokens:
                        consumo.detener("PRESUPUESTO_TOKENS")
                        break
                    time.sleep(limites.pausa_segundos)
                dato = consumo.leer()
                dato["fase_activa"] = fase
                guardar_json(consumo.ruta, dato)
                registro = {"fase": fase, "estado": "error", "duracion_segundos": 0}
                inicio = time.monotonic()
                try:
                    comando = [sys.executable, "-m", "eval.check_ep2_plan", "--fase", fase,
                               "--directorio", temporal]
                    proceso = ejecutar_proceso(comando, limites.timeout_proceso)
                    # El estado JSON y el contador prevalecen sobre un exit code cero.
                    try:
                        registro.update(fase_publica(json.loads(proceso.stdout)))
                        if registro["fase"] != fase:
                            raise ValueError("fase")
                    except (ValueError, TypeError, KeyError, AttributeError):
                        consumo.detener("RESULTADO_INVALIDO")
                    if registro.get("http_429"):
                        consumo.detener("HTTP_429")
                    if registro.get("estado") == "limite":
                        consumo.detener("LIMITE_EJECUCION")
                    registro["exit_code"] = proceso.returncode
                    if proceso.returncode:
                        consumo.detener("ERROR_PROCESO")
                    estado_consumo = consumo.leer()
                    if not estado_consumo["motivo_detencion"] and not any(
                            s["fase"] == fase for s in estado_consumo["solicitudes"]):
                        consumo.detener("SIN_SOLICITUDES_MODELO")
                    if not consumo.leer()["motivo_detencion"]:
                        intacto = hashlib.sha256(config.RUTA_BD.read_bytes()).hexdigest() == original
                        motivo = fallo_fase([*intento["pasos"], registro], intacto)
                        if motivo:
                            consumo.detener(motivo)
                except subprocess.TimeoutExpired:
                    consumo.detener("TIMEOUT_PROCESO")
                except KeyboardInterrupt:
                    consumo.detener("INTERRUMPIDO")
                except Exception:
                    consumo.detener("ERROR_EVALUADOR")
                finally:
                    registro["duracion_segundos"] = round(time.monotonic() - inicio, 3)
                    registro["consumo"] = [s for s in consumo.leer()["solicitudes"] if s["fase"] == fase]
                    registro["cantidad_solicitudes"] = len(registro["consumo"])
                    intento["pasos"].append(registro)
                if consumo.leer()["motivo_detencion"]:
                    break
        except KeyboardInterrupt:
            consumo.detener("INTERRUMPIDO")
        except Exception:
            consumo.detener("ERROR_EVALUADOR")
        finally:
            dato = consumo.leer()
            intento["motivo_detencion"] = dato["motivo_detencion"]
            intento["solicitudes"] = dato["solicitudes"]
            intento["cantidad_solicitudes"] = len(dato["solicitudes"])
            intento["tokens_operativos_acumulados"] = consumo.total(dato)
            intento["tokens_informados"] = {k: sum(s[k] or 0 for s in dato["solicitudes"])
                if any(s[k] is not None for s in dato["solicitudes"]) else None
                for k in ("entrada_informada", "salida_informada", "total_informado")}
            intento["solicitudes_con_estimacion"] = sum(s["origen"] != "proveedor" for s in dato["solicitudes"])
            try:
                intacto = original is not None and hashlib.sha256(config.RUTA_BD.read_bytes()).hexdigest() == original
                intento["verificaciones"] = verificaciones(intento["pasos"], intacto)
                intento["clasificacion_verificaciones"] = clasificar_verificaciones(
                    intento["pasos"], intento["verificaciones"])
                intento["aprobado"] = not intento["motivo_detencion"] and all(intento["verificaciones"].values())
            except (ValueError, TypeError, KeyError):
                intento["motivo_detencion"] = intento["motivo_detencion"] or "RESULTADO_INVALIDO"
            if not intento["aprobado"]:
                intento["motivo_detencion"] = intento["motivo_detencion"] or "VALIDACION_INCOMPLETA"
            # Archivo nuevo: no altera ni mezcla la evidencia historica de los 11 intentos.
            salida = config.DIR_CACHE / "ep2_plan_controlado.json"
            informe = json.loads(salida.read_text(encoding="utf-8")) if salida.exists() else {"intentos": []}
            informe["intentos"].append(intento)
            guardar_json(salida, informe)
    print(json.dumps({k: intento[k] for k in ("aprobado", "motivo_detencion", "cantidad_solicitudes",
                                              "tokens_operativos_acumulados")}), flush=True)
    return 0 if intento["aprobado"] else 130 if intento["motivo_detencion"] == "INTERRUMPIDO" else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--fase", choices=tuple(PREGUNTAS), help=argparse.SUPPRESS)
    parser.add_argument("--directorio", type=Path, help=argparse.SUPPRESS)
    ayudas = {
        "max_solicitudes": "Maximo global de solicitudes HTTP al modelo, sin reintentos.",
        "presupuesto_tokens": "Presupuesto operativo global de entrada y salida, con reserva previa.",
        "max_tokens_salida": "Maximo de salida de cada solicitud de esta prueba.",
        "segundos_fase": "Tiempo cooperativo del agente por fase (hasta 300 s).",
        "timeout_llm": "Timeout HTTP del modelo (hasta 60 s).",
        "timeout_proceso": "Tiempo maximo del proceso hijo; debe superar segundos-fase.",
        "intervalo_llm_segundos": "Intervalo minimo entre solicitudes dentro de una fase.",
        "pausa_segundos": "Pausa entre fases aprobadas; no provoca reintentos.",
    }
    for campo, valor in asdict(Limites()).items():
        parser.add_argument("--" + campo.replace("_", "-"), type=int, default=valor, help=ayudas[campo])
    args = parser.parse_args(argv)
    limites = Limites(**{k: getattr(args, k) for k in asdict(Limites())})
    if any(getattr(limites, k) <= 0 for k in asdict(limites) if k not in ("intervalo_llm_segundos", "pausa_segundos")) \
            or limites.intervalo_llm_segundos < 0 or limites.pausa_segundos < 0 \
            or limites.segundos_fase > 300 or limites.timeout_llm > 60 \
            or limites.timeout_proceso <= limites.segundos_fase:
        parser.error("Limites invalidos: valores positivos, fase <=300 s, LLM <=60 s y proceso > fase.")
    os.environ.update(LANGCHAIN_TRACING_V2="false", LANGSMITH_TRACING="false",
                      HF_HUB_OFFLINE="1", TRANSFORMERS_OFFLINE="1")
    if args.fase:
        if not args.directorio or args.directorio.resolve().parent != config.DIR_CACHE.resolve() \
                or not args.directorio.name.startswith("ep2-plan-real-"):
            parser.error("Se requiere un directorio temporal ep2-plan-real-* bajo .cache.")
        consumo = Consumo(args.directorio / "control.json")
        try:
            dato = consumo.leer()
            if dato["fase_activa"] != args.fase or dato["motivo_detencion"]:
                raise DetencionEvaluacion("ORDEN_FASE_INVALIDO")
            limites = Limites(**dato["limites"])
            resultado = paso_real(args.fase, args.directorio, limites)
            print(json.dumps(resultado, ensure_ascii=False), flush=True)
            esperado = "requiere_confirmacion" if args.fase == "impacto" else "ok"
            return int(bool(consumo.leer()["motivo_detencion"]) or resultado["estado"] != esperado)
        except KeyboardInterrupt:
            consumo.detener("INTERRUMPIDO")
            return 130
        except Exception:
            print(json.dumps({"fase": args.fase, "estado": "error"}), flush=True)
            return 1
    try:
        return ejecutar_integral(limites)
    except KeyboardInterrupt:
        print(json.dumps({"aprobado": False, "motivo_detencion": "INTERRUMPIDO"}), flush=True)
        return 130
    except Exception:
        print(json.dumps({"aprobado": False, "motivo_detencion": "ERROR_EVIDENCIA"}), flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
