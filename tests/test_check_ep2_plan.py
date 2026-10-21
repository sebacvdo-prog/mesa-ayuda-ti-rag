"""Controles de la prueba manual: HTTP simulado, sin llamadas a proveedores."""

from __future__ import annotations

from dataclasses import asdict, replace
import json
from pathlib import Path
import subprocess
from unittest.mock import Mock

import httpx
import pytest

from eval import check_ep2_plan as evaluador


@pytest.fixture()
def control(tmp_path):
    def crear(**opciones):
        limites = replace(evaluador.Limites(), **opciones)
        consumo = evaluador.Consumo(tmp_path / "control.json")
        evaluador.guardar_json(consumo.ruta, {"limites": asdict(limites), "fase_activa": "inicial",
                                            "solicitudes": [], "motivo_detencion": None})
        return consumo
    return crear


def consultar(consumo, respuesta=None, fase="inicial", fallo=None):
    def enviar(request):
        if fallo:
            raise fallo
        return respuesta if respuesta is not None else httpx.Response(200, json={"usage": {
            "prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}})
    delegado = Mock(wraps=httpx.MockTransport(enviar))
    transporte = evaluador.TransporteControlado(delegado, consumo, fase)
    with httpx.Client(transport=transporte) as cliente:
        resultado = cliente.post("https://sin-red.invalid/chat/completions", json={"messages": []})
    return resultado, delegado


def test_tope_de_solicitudes_bloquea_antes_de_enviar(control):
    consumo = control(max_solicitudes=1)
    consultar(consumo)
    with pytest.raises(evaluador.DetencionEvaluacion, match="MAX_SOLICITUDES"):
        consultar(consumo)
    assert len(consumo.leer()["solicitudes"]) == 1
    assert consumo.leer()["motivo_detencion"] == "MAX_SOLICITUDES"


def test_presupuesto_insuficiente_no_envia_ninguna_peticion(control):
    consumo = control(presupuesto_tokens=1)
    enviar = Mock()
    transporte = evaluador.TransporteControlado(httpx.MockTransport(enviar), consumo, "inicial")
    with httpx.Client(transport=transporte) as cliente, pytest.raises(
            evaluador.DetencionEvaluacion, match="PRESUPUESTO_TOKENS"):
        cliente.post("https://sin-red.invalid", json={})
    enviar.assert_not_called()
    assert consumo.leer()["solicitudes"] == []


def test_consumo_exacto_se_acumula_entre_instancias_y_fases(control):
    consumo = control()
    consultar(consumo)
    dato = consumo.leer()
    dato["fase_activa"] = "impacto"
    evaluador.guardar_json(consumo.ruta, dato)
    nuevo = evaluador.Consumo(consumo.ruta)
    consultar(nuevo, fase="impacto")
    dato = nuevo.leer()
    assert nuevo.total(dato) == 24
    assert [s["fase"] for s in dato["solicitudes"]] == ["inicial", "impacto"]
    assert all(s["origen"] == "proveedor" for s in dato["solicitudes"])
    assert all(s["duracion_segundos"] >= 0 for s in dato["solicitudes"])


@pytest.mark.parametrize("uso,origen", [
    (None, "estimacion"),
    ({"prompt_tokens": 7}, "mixto"),
    ({"completion_tokens": 3}, "mixto"),
    ({"total_tokens": 17}, "proveedor"),
    ({"input_tokens": 8, "output_tokens": 4}, "proveedor"),
    ({"prompt_tokens": -1, "completion_tokens": "2", "total_tokens": True}, "estimacion"),
    ("dato invalido", "estimacion"),
])
def test_uso_ausente_parcial_o_invalido_no_se_presenta_como_real(control, uso, origen):
    consumo = control()
    consultar(consumo, httpx.Response(200, json={"usage": uso, "choices": [{"message": {"content": "privado"}}]}))
    s = consumo.leer()["solicitudes"][0]
    assert s["origen"] == origen
    if origen != "proveedor":
        assert s["tokens_operativos"] > 0
        assert s["entrada_estimada"] > 0 and s["salida_estimada"] == 2000
    if uso is None:
        assert s["total_informado"] is None
        assert s["tokens_operativos"] == s["entrada_estimada"] + s["salida_estimada"]
    assert "privado" not in consumo.ruta.read_text()


def test_reserva_se_conserva_si_el_proceso_no_recibe_respuesta(control):
    consumo = control()
    consumo.iniciar("inicial", b"payload")
    dato = evaluador.Consumo(consumo.ruta).leer()
    assert dato["solicitudes"][0]["estado"] == "en_curso"
    assert consumo.total(dato) == len(b"payload") + 256 + 2000


def test_consumo_acumulado_impide_siguiente_peticion(control):
    consumo = control(presupuesto_tokens=2300)
    consultar(consumo, httpx.Response(200, json={"usage": {"total_tokens": 2290}}))
    with pytest.raises(evaluador.DetencionEvaluacion, match="PRESUPUESTO_TOKENS"):
        consultar(consumo)
    assert len(consumo.leer()["solicitudes"]) == 1


def test_uso_inconsistente_conserva_el_mayor_total_para_el_presupuesto(control):
    consumo = control()
    consultar(consumo, httpx.Response(200, json={"usage": {
        "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 3}}))
    assert consumo.total(consumo.leer()) == 15


def test_fase_fuera_de_orden_no_envia(control):
    consumo = control()
    with pytest.raises(evaluador.DetencionEvaluacion, match="ORDEN_FASE_INVALIDO"):
        consultar(consumo, fase="impacto")
    assert consumo.leer()["solicitudes"] == []


def test_http_429_detiene_y_no_guarda_cuerpo_cabeceras_o_credenciales(control):
    consumo = control()
    respuesta = httpx.Response(429, json={"error": {"message": "gsk_secreto persona@empresa.cl"}},
                               headers={"retry-after": "440", "authorization": "Bearer secreto"})
    _, delegado = consultar(consumo, respuesta)
    assert delegado.handle_request.call_count == 1
    assert consumo.leer()["motivo_detencion"] == "HTTP_429"
    s = consumo.leer()["solicitudes"][0]
    assert s["http_status"] == 429 and s["retry_after_segundos"] == 440
    with pytest.raises(evaluador.DetencionEvaluacion, match="HTTP_429"):
        consultar(consumo)
    guardado = consumo.ruta.read_text()
    assert "secreto" not in guardado and "persona@" not in guardado and "authorization" not in guardado


@pytest.mark.parametrize("fallo,motivo", [(httpx.ReadTimeout("detalle secreto"), "ERROR_TRANSPORTE"),
                                          (KeyboardInterrupt(), "INTERRUMPIDO")])
def test_timeout_o_interrupcion_no_reintenta_y_conserva_reserva(control, fallo, motivo):
    consumo = control()
    with pytest.raises(type(fallo)):
        consultar(consumo, fallo=fallo)
    dato = consumo.leer()
    assert dato["motivo_detencion"] == motivo
    assert len(dato["solicitudes"]) == 1 and consumo.total(dato) > 0


def plan(revision=1, nota=False):
    herramientas = ["consultar_ticket", "consultar_sla", "buscar_procedimiento"]
    if nota:
        herramientas.extend(("analizar_incidente", "registrar_nota_ticket"))
    return {"id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "revision": revision,
            "impacto_reportado": "multiples_usuarios" if nota else "no_informado",
            "impacto_verificado": False, "prioridad_registrada": "P2", "prioridad_propuesta": "P2" if nota else None,
            "objetivo": "persona@empresa.cl", "criterio_prioridad": "gsk_secreto",
            "pasos": [{"id": f"p{i}", "herramienta": h, "prioridad": 2,
                       "estado": "bloqueado" if h == "registrar_nota_ticket" else "completado",
                       "codigo": "COMPLETADO", "dependencias": [], "motivo": "privado"}
                      for i, h in enumerate(herramientas, 1)]}


def fases_validas():
    fases = []
    for i, fase in enumerate(evaluador.PREGUNTAS):
        p = plan(i + 1, nota=i > 0)
        herramientas = [] if i == 2 else [{"nombre": s["herramienta"], "estado": "ok", "codigo": "COMPLETADO"}
                                          for s in p["pasos"] if s["herramienta"] != "registrar_nota_ticket"]
        fases.append({"fase": fase, "pid": i + 100, "estado": "requiere_confirmacion" if i == 1 else "ok",
                      "memoria_estado": "actualizada", "herramientas": herramientas,
                      "plan_inicial": p, "plan_final": p, "plan_recuperado_antes": p if i else None,
                      "cantidad_confirmaciones": int(i == 1), "notas": 0, "auditoria": 0,
                      "respuesta": "persona@empresa.cl gsk_secreto", "traza_cli": "privado"})
    return fases


@pytest.fixture()
def integral(tmp_path, monkeypatch):
    monkeypatch.setattr(evaluador.config, "DIR_CACHE", tmp_path / ".cache")
    bd = tmp_path / "itsm.db"
    bd.write_bytes(b"ITSM protegido")
    monkeypatch.setattr(evaluador.config, "RUTA_BD", bd)
    ejecutadas, directorios = [], []
    def simular(datos=None, error=None, returncode=0, por_fase=1):
        datos = datos or fases_validas()
        def ejecutar(comando, timeout):
            fase = comando[comando.index("--fase") + 1]
            directorio = Path(comando[comando.index("--directorio") + 1])
            ejecutadas.append(fase)
            directorios.append(directorio)
            consumo = evaluador.Consumo(directorio / "control.json")
            for _ in range(por_fase):
                consultar(consumo, fase=fase)
            if error:
                raise error
            return subprocess.CompletedProcess(comando, returncode,
                json.dumps(datos[list(evaluador.PREGUNTAS).index(fase)]), "detalle privado de stderr")
        monkeypatch.setattr(evaluador, "ejecutar_proceso", ejecutar)
    return simular, ejecutadas, directorios


def correr():
    return evaluador.main(["--pausa-segundos", "0", "--intervalo-llm-segundos", "0"])


def evidencia():
    return json.loads((evaluador.config.DIR_CACHE / "ep2_plan_controlado.json").read_text(encoding="utf-8"))["intentos"][-1]


def test_corrida_integral_15_de_15_orden_sqlite_comun_consumo_y_exit_zero(integral):
    simular, ejecutadas, directorios = integral
    simular()
    assert correr() == 0
    intento = evidencia()
    assert ejecutadas == list(evaluador.PREGUNTAS) and len(set(directorios)) == 1
    assert intento["aprobado"] and sum(intento["verificaciones"].values()) == 15
    assert intento["cantidad_solicitudes"] == 3 and intento["tokens_operativos_acumulados"] == 36
    assert intento["tokens_informados"] == {"entrada_informada": 30, "salida_informada": 6, "total_informado": 36}
    assert all(p["duracion_segundos"] >= 0 and p["cantidad_solicitudes"] == 1 for p in intento["pasos"])
    contenido = json.dumps(intento)
    assert all(secreto not in contenido for secreto in ("persona@", "gsk_secreto", "privado", "stderr"))


@pytest.mark.parametrize("fase", [0, 1, 2])
@pytest.mark.parametrize("error", ["429", "estado", "verificacion", "memoria", "escritura"])
def test_no_continua_si_falla_una_fase_aunque_exit_code_sea_cero(integral, fase, error):
    simular, ejecutadas, _ = integral
    datos = fases_validas()
    if error == "429":
        datos[fase].update(estado="error", respuesta="No se pudo completar (HTTP 429).")
    elif error == "estado":
        datos[fase]["estado"] = "limite"
    elif error == "verificacion":
        if fase == 0:
            datos[fase]["herramientas"] = []
        elif fase == 1:
            datos[fase]["cantidad_confirmaciones"] = 0
        else:
            datos[fase]["herramientas"] = [{"nombre": "consultar_ticket", "estado": "ok"}]
    elif error == "memoria":
        datos[fase]["memoria_estado"] = "no_disponible"
    else:
        datos[fase]["notas"] = 1
    simular(datos)
    assert correr() == 1
    assert len(ejecutadas) == fase + 1
    assert not evidencia()["aprobado"] and evidencia()["motivo_detencion"]
    if error == "429":
        assert evidencia()["motivo_detencion"] == "HTTP_429"


def test_429_json_con_exit_no_cero_conserva_causa(integral):
    simular, ejecutadas, _ = integral
    datos = fases_validas()
    datos[0].update(estado="error", respuesta="HTTP 429")
    simular(datos, returncode=1)
    assert correr() == 1
    assert ejecutadas == ["inicial"] and evidencia()["motivo_detencion"] == "HTTP_429"


def test_campo_de_impacto_ausente_no_se_convierte_en_evidencia_verificada(integral):
    simular, ejecutadas, _ = integral
    datos = fases_validas()
    del datos[1]["plan_final"]["impacto_verificado"]
    simular(datos)
    assert correr() == 1
    assert ejecutadas == ["inicial", "impacto"]
    assert evidencia()["motivo_detencion"] == "VERIFICACIONES_FASE"


@pytest.mark.parametrize("fallo,motivo,codigo", [
    (subprocess.TimeoutExpired("privado", 1), "TIMEOUT_PROCESO", 1),
    (KeyboardInterrupt(), "INTERRUMPIDO", 130),
    (OSError("gsk_secreto"), "ERROR_EVALUADOR", 1),
])
def test_fallo_timeout_interrupcion_conservan_fase_consumo_y_codigo(integral, fallo, motivo, codigo):
    simular, ejecutadas, _ = integral
    simular(error=fallo)
    assert correr() == codigo
    intento = evidencia()
    assert ejecutadas == ["inicial"] and intento["motivo_detencion"] == motivo
    assert intento["cantidad_solicitudes"] == 1 and len(intento["pasos"]) == 1
    assert "gsk_secreto" not in json.dumps(intento)


def test_presupuesto_de_solicitudes_es_global_y_detiene_entre_fases(integral):
    simular, ejecutadas, _ = integral
    simular()
    assert evaluador.main(["--max-solicitudes", "1", "--pausa-segundos", "0"]) == 1
    assert ejecutadas == ["inicial"] and evidencia()["motivo_detencion"] == "MAX_SOLICITUDES"


def test_presupuesto_de_tokens_es_global_y_no_ejecuta_http(integral):
    simular, ejecutadas, _ = integral
    simular()
    assert evaluador.main(["--presupuesto-tokens", "1", "--pausa-segundos", "0"]) == 1
    assert ejecutadas == ["inicial"] and evidencia()["cantidad_solicitudes"] == 0
    assert evidencia()["motivo_detencion"] == "PRESUPUESTO_TOKENS"


def test_no_sobrescribe_evidencia_historica_y_acumula_intentos_nuevos(integral):
    simular, _, _ = integral
    simular()
    evaluador.config.DIR_CACHE.mkdir()
    historico = evaluador.config.DIR_CACHE / "ep2_plan_real.json"
    historico.write_bytes(b"evidencia historica intacta")
    assert correr() == 0 and correr() == 0
    assert historico.read_bytes() == b"evidencia historica intacta"
    informe = json.loads((evaluador.config.DIR_CACHE / "ep2_plan_controlado.json").read_text())
    assert len(informe["intentos"]) == 2


@pytest.mark.parametrize("contenido", ["no JSON gsk_secreto", "null", "[]", '{"fase":"inicial","estado":"ok"}'])
def test_stdout_invalido_no_continua_y_no_se_guarda(integral, monkeypatch, contenido):
    _, ejecutadas, _ = integral
    def ejecutar(comando, timeout):
        ejecutadas.append("inicial")
        return subprocess.CompletedProcess(comando, 0, contenido, "privado")
    monkeypatch.setattr(evaluador, "ejecutar_proceso", ejecutar)
    assert correr() == 1
    assert ejecutadas == ["inicial"]
    assert "gsk_secreto" not in json.dumps(evidencia())


def test_resultado_aparentemente_valido_sin_solicitudes_reales_no_aprueba(integral):
    simular, ejecutadas, _ = integral
    simular(por_fase=0)
    assert correr() == 1
    assert ejecutadas == ["inicial"] and evidencia()["motivo_detencion"] == "SIN_SOLICITUDES_MODELO"


def test_falta_de_uso_no_se_agrega_como_consumo_real_cero(integral, monkeypatch):
    simular, _, _ = integral
    simular()
    enviar_original = consultar
    def sin_uso(consumo, respuesta=None, fase="inicial", fallo=None):
        return enviar_original(consumo, httpx.Response(200, json={}), fase, fallo)
    monkeypatch.setitem(consultar.__globals__, "consultar", sin_uso)
    assert correr() == 0
    intento = evidencia()
    assert intento["tokens_informados"] == {"entrada_informada": None, "salida_informada": None, "total_informado": None}
    assert intento["solicitudes_con_estimacion"] == 3
    assert intento["tokens_operativos_acumulados"] > 0


def test_interrupcion_durante_pausa_no_inicia_siguiente_fase(integral, monkeypatch):
    simular, ejecutadas, _ = integral
    simular()
    monkeypatch.setattr(evaluador.time, "sleep", Mock(side_effect=KeyboardInterrupt()))
    assert correr() == 130
    assert ejecutadas == ["inicial"] and evidencia()["motivo_detencion"] == "INTERRUMPIDO"


@pytest.mark.parametrize("args", [["--max-solicitudes", "0"], ["--presupuesto-tokens", "-1"],
                                  ["--segundos-fase", "301"], ["--timeout-llm", "61"],
                                  ["--timeout-proceso", "299"], ["--pausa-segundos", "-1"]])
def test_argumentos_invalidos_salen_antes_de_crear_cliente(args):
    with pytest.raises(SystemExit) as error:
        evaluador.main(args)
    assert error.value.code == 2


@pytest.mark.parametrize("fallo", [KeyboardInterrupt(), subprocess.TimeoutExpired("simulado", 1)])
def test_subproceso_se_termina_antes_de_propagar_interrupcion(monkeypatch, fallo):
    proceso = Mock()
    proceso.communicate.side_effect = [fallo, ("", "")]
    proceso.__enter__ = Mock(return_value=proceso)
    proceso.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(evaluador.subprocess, "Popen", Mock(return_value=proceso))
    with pytest.raises(type(fallo)):
        evaluador.ejecutar_proceso(["simulado"], 1)
    proceso.kill.assert_called_once()
    assert proceso.communicate.call_count == 2


def test_cliente_openai_real_sobre_http_simulado_no_reintenta_429(control):
    from langchain_openai import ChatOpenAI
    consumo = control()
    delegado = httpx.MockTransport(lambda request: httpx.Response(
        429, json={"error": {"message": "detalle secreto", "type": "rate_limit_exceeded"}}))
    transporte = evaluador.TransporteControlado(delegado, consumo, "inicial")
    with httpx.Client(transport=transporte) as cliente:
        modelo = ChatOpenAI(model="openai/gpt-oss-20b", api_key="falsa", base_url="https://sin-red.invalid/v1",
                            http_client=cliente, max_retries=0)
        with pytest.raises(Exception) as error:
            modelo.invoke("simulado")
    assert getattr(error.value, "status_code", None) == 429
    assert len(consumo.leer()["solicitudes"]) == 1


@pytest.fixture()
def cli_simulada(tmp_path, monkeypatch):
    """CLI, agente, planificador y SQLite reales; solo HTTP, ITSM y RAG de prueba."""
    from data import seed_db
    from langchain_openai import ChatOpenAI
    from src.ep2 import agente, cli, configuracion, herramientas
    from src.ep2.contratos import ResultadoHerramienta
    from src.retriever import ConectorITSM

    itsm = tmp_path / "itsm-prueba.db"
    seed_db.crear_base(itsm)
    monkeypatch.setattr(evaluador.config, "RUTA_BD", itsm)
    monkeypatch.setattr(herramientas, "ConectorITSM", lambda: ConectorITSM(itsm))
    monkeypatch.setattr(agente, "RecuperadorVectorial", Mock)
    monkeypatch.setattr(herramientas.HerramientasEP2, "buscar_procedimiento", lambda *args: ResultadoHerramienta(
        estado="ok", codigo="PROCEDIMIENTO_RECUPERADO", mensaje="OK",
        procedencia=("corpus:kb_conectividad_vpn.md",), datos={"fragmentos": []}))
    confirmar = Mock(side_effect=AssertionError("No debe invocarse confirmacion"))
    monkeypatch.setattr(herramientas.HerramientasEP2, "confirmar_nota", confirmar)
    modelos, peticiones = [], []
    def fabricar(opciones):
        modelo = ChatOpenAI(model=opciones.modelo, api_key="falsa", base_url="https://sin-red.invalid/v1",
                            max_retries=0)
        modelos.append(modelo)
        return modelo
    monkeypatch.setattr(configuracion, "crear_llm_ep2", fabricar)
    def simular(mensajes, codigo=200, validar_herramientas=True, error_proveedor=None):
        respuestas = iter(mensajes)
        def enviar(request):
            peticiones.append(json.loads(request.content))
            assert request.url.host == "sin-red.invalid"
            mensaje = next(respuestas)
            if error_proveedor is not None:
                return httpx.Response(codigo, json=error_proveedor)
            ofrecidas = {t["function"]["name"] for t in peticiones[-1].get("tools", [])}
            if codigo == 200 and validar_herramientas and any(
                    c["function"]["name"] not in ofrecidas for c in mensaje.get("tool_calls", [])):
                return httpx.Response(400, json={"error": {"message": "Herramienta excluida gsk_secreto",
                                                           "type": "invalid_request_error", "code": "tool_use_failed"}})
            return httpx.Response(codigo, json={
                "id": "simulado", "model": "openai/gpt-oss-20b", "object": "chat.completion", "created": 1,
                "choices": [{"index": 0, "message": mensaje, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}})
        monkeypatch.setattr(evaluador.httpx, "HTTPTransport", lambda **kwargs: httpx.MockTransport(enviar))
    return simular, confirmar, modelos, peticiones, cli.AlmacenEP2


def mensaje_herramienta(nombre, **argumentos):
    return {"role": "assistant", "content": "", "tool_calls": [{"id": "simulado", "type": "function",
            "function": {"name": nombre, "arguments": json.dumps(argumentos)}}]}


def test_instrumentacion_cli_real_posponer_memoria_y_diez_peticiones_simuladas(tmp_path, cli_simulada):
    import builtins
    from src.ep2 import cli
    simular, confirmar, modelos, peticiones, almacen_original = cli_simulada
    lectura_original = builtins.input
    ticket = "INC-2026-0411"
    simular([
        mensaje_herramienta("consultar_ticket", ticket_id=ticket),
        mensaje_herramienta("consultar_sla", prioridad="P2"),
        mensaje_herramienta("buscar_procedimiento", consulta="VPN FortiClient"),
        {"role": "assistant", "content": "Datos consultados."},
        mensaje_herramienta("consultar_ticket", ticket_id=ticket),
        mensaje_herramienta("consultar_sla", prioridad="P2"),
        mensaje_herramienta("analizar_incidente", ticket_id=ticket),
        mensaje_herramienta("buscar_procedimiento", consulta="VPN FortiClient"),
        mensaje_herramienta("registrar_nota_ticket", ticket_id=ticket, texto="Solicitar seguimiento Nivel 2."),
        {"role": "assistant", "content": "Pendiente de confirmacion humana nueva."},
    ])
    limites = replace(evaluador.Limites(), intervalo_llm_segundos=0, max_tokens_salida=321)
    directorio = tmp_path / "ep2"
    directorio.mkdir()
    consumo = evaluador.Consumo(directorio / "control.json")
    evaluador.guardar_json(consumo.ruta, {"limites": asdict(limites), "fase_activa": None,
                                        "solicitudes": [], "motivo_detencion": None})
    fases = []
    for fase in evaluador.PREGUNTAS:
        dato = consumo.leer()
        dato["fase_activa"] = fase
        evaluador.guardar_json(consumo.ruta, dato)
        fases.append(evaluador.paso_real(fase, directorio, limites))
    assert [p["estado"] for p in fases] == ["ok", "requiere_confirmacion", "ok"]
    assert all(p["notas"] == p["auditoria"] == 0 for p in fases)
    assert fases[1]["cantidad_confirmaciones"] == 1 and fases[2]["cantidad_confirmaciones"] == 0
    assert fases[2]["plan_recuperado_antes"]["id"] == fases[1]["plan_final"]["id"]
    assert len(peticiones) == 10 and consumo.total(consumo.leer()) == 120
    assert [len(p["decisiones"]) for p in fases] == [4, 5, 1]
    assert all(d["modelo_respondio"] for p in fases for d in p["decisiones"])
    assert fases[2]["decisiones"][0]["codigo"] == "RESPUESTA_FINAL"
    assert all("texto" not in d and "argumentos" not in d for p in fases for d in p["decisiones"])
    assert all(p.get("max_tokens", p.get("max_completion_tokens")) == 321 for p in peticiones)
    assert all(m.root_client.max_retries == 0 for m in modelos)
    assert not consumo.leer()["motivo_detencion"]
    esperadas = [[n] for n in ("consultar_ticket", "consultar_sla", "buscar_procedimiento")]
    esperadas += [[]] + [[n] for n in ("consultar_ticket", "consultar_sla", "analizar_incidente", "buscar_procedimiento", "registrar_nota_ticket")] + [[]]
    assert [[t["function"]["name"] for t in p.get("tools", [])] for p in peticiones] == esperadas
    assert [d["herramientas_ofrecidas"] for f in fases for d in f["decisiones"]] == esperadas
    assert all(p.get("tool_choice") == "required" and p.get("parallel_tool_calls") is False
               for p in peticiones if p.get("tools"))
    assert all("tool_choice" not in p for p in peticiones if not p.get("tools"))
    # El resultado de ticket sigue en el historial cuando solo se ofrece SLA.
    assert any(m.get("role") == "assistant" and any(c["function"]["name"] == "consultar_ticket"
               for c in m.get("tool_calls", [])) for m in peticiones[1]["messages"])
    assert any(m.get("role") == "tool" for m in peticiones[1]["messages"])
    assert fases[0]["decisiones"][-1]["estado_oferta"] == "plan_completado"
    assert fases[2]["decisiones"][0]["estado_oferta"] == "solo_estado"
    confirmar.assert_not_called()
    assert cli.AlmacenEP2 is almacen_original and builtins.input is lectura_original


def test_429_en_cliente_instrumentado_aunque_agente_capture_error(tmp_path, cli_simulada):
    simular, confirmar, _, peticiones, _ = cli_simulada
    simular([{"role": "assistant", "content": "privado"}], codigo=429)
    limites = replace(evaluador.Limites(), intervalo_llm_segundos=0)
    directorio = tmp_path / "ep2"
    directorio.mkdir()
    consumo = evaluador.Consumo(directorio / "control.json")
    evaluador.guardar_json(consumo.ruta, {"limites": asdict(limites), "fase_activa": "inicial",
                                        "solicitudes": [], "motivo_detencion": None})
    respuesta = evaluador.paso_real("inicial", directorio, limites)
    assert respuesta["estado"] == "error" and respuesta["http_429"]
    assert len(respuesta["decisiones"]) == 1 and respuesta["decisiones"][0]["codigo"] == "HTTP_429"
    assert not respuesta["decisiones"][0]["modelo_respondio"]
    assert consumo.leer()["motivo_detencion"] == "HTTP_429" and len(peticiones) == 1
    assert respuesta["notas"] == respuesta["auditoria"] == 0
    confirmar.assert_not_called()


def test_clasificacion_parcial_distingue_incumplimiento_de_fases_no_ejecutadas():
    datos = fases_validas()[:2]
    datos[1].update(estado="limite", cantidad_confirmaciones=0)
    valores = evaluador.verificaciones(datos, True)
    clasificacion = evaluador.clasificar_verificaciones(datos, valores)
    assert clasificacion["consulta_ticket_sla_faiss"] == "aprobada"
    assert clasificacion["nota_pendiente_sin_autorizar"] == "fallida"
    assert clasificacion["tres_procesos_distintos"] == "no_ejecutada"
    assert all(clasificacion[n] == "no_ejecutada" for n in (
        "reapertura_recupera_plan", "reapertura_conserva_pendiente", "sin_nueva_propuesta_al_reanudar"))
    assert clasificacion["sin_escrituras_de_negocio"] == "evidencia_parcial_favorable"
    assert clasificacion["memoria_guardada"] == "evidencia_parcial_favorable"
    assert valores["sin_escrituras_de_negocio"] is False and valores["memoria_guardada"] is False
    assert not all(valores.values())


@pytest.mark.parametrize("campo,valor,verificacion", [
    ("notas", 1, "sin_escrituras_de_negocio"),
    ("auditoria", 1, "sin_escrituras_de_negocio"),
    ("memoria_estado", "no_disponible", "memoria_guardada"),
])
def test_evidencia_parcial_adversa_no_se_clasifica_como_favorable(campo, valor, verificacion):
    datos = fases_validas()[:1]
    datos[0][campo] = valor
    valores = evaluador.verificaciones(datos, True)
    assert evaluador.clasificar_verificaciones(datos, valores)[verificacion] == "fallida"


def test_cero_fases_no_acreditan_escrituras_memoria_ni_exito():
    valores = evaluador.verificaciones([], True)
    clasificacion = evaluador.clasificar_verificaciones([], valores)
    assert clasificacion["sin_escrituras_de_negocio"] == clasificacion["memoria_guardada"] == "no_ejecutada"
    assert clasificacion["consulta_ticket_sla_faiss"] == "no_ejecutada"
    assert not all(valores.values())


def test_clasificacion_integral_no_debilita_las_quince_verificaciones():
    datos = fases_validas()
    valores = evaluador.verificaciones(datos, True)
    assert len(valores) == 15 and all(valores.values())
    assert set(evaluador.clasificar_verificaciones(datos, valores).values()) == {"aprobada"}
    datos[2]["pid"] = datos[1]["pid"]
    valores = evaluador.verificaciones(datos, True)
    assert evaluador.clasificar_verificaciones(datos, valores)["tres_procesos_distintos"] == "fallida"
    assert not all(valores.values())


@pytest.mark.parametrize("returncode", [0, 1])
def test_limite_conserva_motivo_especifico_y_detiene_antes_de_reanudar(integral, returncode):
    simular, ejecutadas, _ = integral
    datos = fases_validas()
    datos[0].update(estado="limite")
    simular(datos, returncode=returncode)
    assert correr() == 1
    assert ejecutadas == ["inicial"] and evidencia()["motivo_detencion"] == "LIMITE_EJECUCION"
    assert not evidencia()["aprobado"]


def test_sanitizacion_de_decision_descarta_textos_argumentos_y_nombres_desconocidos():
    dato = {"indice": 1, "seleccion": ["analizar_incidente", "secreto@empresa.cl", {"api_key": "gsk_secreto"}],
            "estado": "rechazada", "codigo": "PLAN_DEPENDENCIA_PENDIENTE", "correccion": "_Exception",
            "habilitadas": ["consultar_ticket", "secreto@empresa.cl"], "dependencias_faltantes": ["p1", "gsk_secreto"],
            "herramientas_ofrecidas": ["consultar_ticket", {"api_key": "gsk_secreto"}, "secreto@empresa.cl"],
            "tool_choice": "gsk_secreto", "estado_oferta": "interno_privado",
            "argumentos": {"texto": "cuerpo_privado"}, "razonamiento": "interno_privado",
            "plan_antes": plan(), "plan_despues": plan()}
    publico = evaluador.decision_publica(dato)
    assert publico["seleccion"] == ["analizar_incidente", "fuera_registro", "fuera_registro"]
    assert publico["habilitadas"] == ["consultar_ticket"] and publico["dependencias_faltantes"] == ["p1"]
    assert publico["correccion"] == "_Exception"
    assert publico["herramientas_ofrecidas"] == ["consultar_ticket"]
    assert publico["tool_choice"] is None and publico["estado_oferta"] is None
    assert all(texto not in json.dumps(publico) for texto in (
        "gsk_secreto", "secreto@", "cuerpo_privado", "interno_privado", "persona@"))


def test_trazas_se_preservan_en_evidencia_del_padre_tras_error_de_fase(integral):
    simular, ejecutadas, _ = integral
    datos = fases_validas()
    datos[1].update(estado="limite", cantidad_confirmaciones=0, decisiones=[{
        "indice": i, "seleccion": ["registrar_nota_ticket"], "estado": "rechazada",
        "codigo": "PLAN_DEPENDENCIA_PENDIENTE", "correccion": "_Exception", "ejecutada": False,
        "plan_antes": plan(), "plan_despues": plan(), "argumentos": {"texto": "cuerpo_privado"}}
        for i in range(1, 9)])
    simular(datos)
    assert correr() == 1
    intento = evidencia()
    assert ejecutadas == ["inicial", "impacto"] and intento["motivo_detencion"] == "LIMITE_EJECUCION"
    assert len(intento["pasos"][1]["decisiones"]) == 8
    assert all(d["correccion"] == "_Exception" and not d["ejecutada"] for d in intento["pasos"][1]["decisiones"])
    assert intento["clasificacion_verificaciones"]["memoria_guardada"] == "evidencia_parcial_favorable"
    assert "cuerpo_privado" not in json.dumps(intento)


@pytest.fixture()
def integral_cli(tmp_path, monkeypatch, cli_simulada):
    """Padre y CLI reales, HTTP simulado; sustituye solo subprocess y sus PID."""
    from unittest.mock import patch
    simular, confirmar, modelos, peticiones, _ = cli_simulada
    monkeypatch.setattr(evaluador.config, "DIR_CACHE", tmp_path / ".cache")
    fases, directorios = [], []
    def ejecutar(comando, timeout):
        fase = comando[comando.index("--fase") + 1]
        directorio = Path(comando[comando.index("--directorio") + 1])
        fases.append(fase)
        directorios.append(directorio)
        limites = evaluador.Limites(**evaluador.Consumo(directorio / "control.json").leer()["limites"])
        with patch.object(evaluador.os, "getpid", return_value=1000 + len(fases)):
            dato = evaluador.paso_real(fase, directorio, limites)
        esperado = "requiere_confirmacion" if fase == "impacto" else "ok"
        return subprocess.CompletedProcess(comando, int(dato["estado"] != esperado), json.dumps(dato), "")
    monkeypatch.setattr(evaluador, "ejecutar_proceso", ejecutar)
    return simular, confirmar, modelos, peticiones, fases, directorios


def mensajes_integrales():
    ticket = "INC-2026-0411"
    return [mensaje_herramienta("consultar_ticket", ticket_id=ticket),
            mensaje_herramienta("consultar_sla", prioridad="P2"),
            mensaje_herramienta("buscar_procedimiento", consulta="VPN FortiClient"),
            {"role": "assistant", "content": "Consultado."},
            mensaje_herramienta("consultar_ticket", ticket_id=ticket),
            mensaje_herramienta("consultar_sla", prioridad="P2"),
            mensaje_herramienta("analizar_incidente", ticket_id=ticket),
            mensaje_herramienta("buscar_procedimiento", consulta="VPN FortiClient"),
            mensaje_herramienta("registrar_nota_ticket", ticket_id=ticket, texto="Solicitar seguimiento Nivel 2."),
            {"role": "assistant", "content": "Pendiente de nueva confirmacion humana."}]


def test_integral_completo_con_cli_payloads_filtrados_y_memoria_real_temporal(integral_cli):
    simular, confirmar, _, peticiones, fases, directorios = integral_cli
    simular(mensajes_integrales())
    assert correr() == 0
    intento = evidencia()
    assert intento["aprobado"] and all(intento["verificaciones"].values())
    assert len(intento["verificaciones"]) == 15
    assert fases == ["inicial", "impacto", "reanudar"] and len(set(directorios)) == 1
    assert intento["cantidad_solicitudes"] == len(peticiones) == 10
    assert intento["tokens_informados"]["total_informado"] == 120
    assert intento["solicitudes_con_estimacion"] == 0
    assert all(p["notas"] == p["auditoria"] == 0 for p in intento["pasos"])
    assert intento["pasos"][2]["plan_recuperado_antes"]["id"] == intento["pasos"][1]["plan_final"]["id"]
    decisiones = [d for p in intento["pasos"] for d in p["decisiones"]]
    assert [d["herramientas_ofrecidas"] for d in decisiones] == [
        [t["function"]["name"] for t in p.get("tools", [])] for p in peticiones]
    assert [d["tool_choice"] for d in decisiones] == ["required"] * 3 + ["none"] + ["required"] * 5 + ["none"]
    confirmar.assert_not_called()


@pytest.mark.parametrize("fase", ["inicial", "impacto"])
def test_modelo_que_insiste_en_analisis_excluido_provoca_400_sin_reintentos(integral_cli, fase):
    simular, confirmar, modelos, peticiones, fases, _ = integral_cli
    previos = mensajes_integrales()[:4] if fase == "impacto" else []
    # Simula validacion del proveedor: no se acepta una funcion ausente del schema.
    simular(previos + [mensaje_herramienta("analizar_incidente", ticket_id="INC-2026-0411")] * 8)
    assert correr() == 1
    intento = evidencia()
    assert intento["motivo_detencion"] == "ERROR_HTTP"
    assert fases == (["inicial", "impacto"] if fase == "impacto" else ["inicial"])
    assert len(peticiones) == len(previos) + 1
    assert intento["solicitudes"][-1]["http_status"] == 400
    ultima = intento["pasos"][-1]
    assert ultima["estado"] == "error" and ultima["decisiones"][-1]["codigo"] == "HTTP_400"
    assert ultima["decisiones"][-1]["herramientas_ofrecidas"] == ["consultar_ticket"]
    assert not ultima["decisiones"][-1]["modelo_respondio"] and not ultima["herramientas"]
    assert all(m.root_client.max_retries == 0 for m in modelos)
    assert all(p["notas"] == p["auditoria"] == 0 for p in intento["pasos"])
    assert "gsk_secreto" not in json.dumps(intento)
    confirmar.assert_not_called()


def test_respuesta_200_invalida_no_elude_filtrado_ni_ejecuta_analisis(tmp_path, cli_simulada):
    simular, confirmar, _, peticiones, _ = cli_simulada
    simular([mensaje_herramienta("analizar_incidente", ticket_id="INC-2026-0411")] * 8,
            validar_herramientas=False)
    directorio = tmp_path / "ep2"
    directorio.mkdir()
    limites = replace(evaluador.Limites(), intervalo_llm_segundos=0)
    consumo = evaluador.Consumo(directorio / "control.json")
    evaluador.guardar_json(consumo.ruta, {"limites": asdict(limites), "fase_activa": "inicial",
                                        "solicitudes": [], "motivo_detencion": None})
    dato = evaluador.paso_real("inicial", directorio, limites)
    assert dato["estado"] == "limite" and len(peticiones) == len(dato["decisiones"]) == 8
    assert not dato["herramientas"] and dato["notas"] == dato["auditoria"] == 0
    assert all(d["herramientas_ofrecidas"] == ["consultar_ticket"] and not d["ejecutada"]
               and d["codigo"] == "PLAN_NO_PREVISTO" for d in dato["decisiones"])
    confirmar.assert_not_called()


@pytest.mark.parametrize("error,categoria,fuente", [
    ({"message": "Attempted to call tool 'analizar_incidente', which was not in request.tools"},
     "HERRAMIENTA_NO_OFRECIDA", "patron_mensaje"),
    ({"message": "Tool 'analizar_incidente' was not offered"}, "HERRAMIENTA_NO_OFRECIDA", "patron_mensaje"),
    ({"message": "Tool call arguments are not valid JSON"}, "ARGUMENTOS_JSON_INVALIDOS", "patron_mensaje"),
    ({"message": "Invalid JSON in function arguments"}, "ARGUMENTOS_JSON_INVALIDOS", "patron_mensaje"),
    ({"message": "Failed to parse arguments as JSON"}, "ARGUMENTOS_JSON_INVALIDOS", "patron_mensaje"),
    ({"message": "Tool choice is required, but model did not call a tool"},
     "HERRAMIENTA_REQUERIDA_AUSENTE", "patron_mensaje"),
    ({"message": "Invalid messages: expected an assistant message"}, "MENSAJES_INVALIDOS", "patron_mensaje"),
    ({"message": "Rejected", "param": "messages"}, "MENSAJES_INVALIDOS", "parametro"),
    ({"message": "Unsupported parameter: tool_choice"}, "PARAMETROS_INVALIDOS", "patron_mensaje"),
    ({"message": "Parameter temperature is not supported"}, "PARAMETROS_INVALIDOS", "patron_mensaje"),
    ({"message": "Rejected", "param": "tool_choice"}, "PARAMETROS_INVALIDOS", "parametro"),
    ({"message": "Rejected", "code": "unsupported_parameter"}, "PARAMETROS_INVALIDOS", "codigo_proveedor"),
])
def test_diagnostico_400_por_patrones_o_campos_permitidos(control, error, categoria, fuente):
    consumo = control()
    error = {"code": "tool_use_failed", "type": "invalid_request_error", **error,
             "failed_generation": {"arguments": "gsk_privado", "reasoning": "razonamiento_privado"}}
    error["message"] += " persona@empresa.cl"
    respuesta, delegado = consultar(consumo, httpx.Response(400, json={"error": error}))
    dato = consumo.leer()
    diagnostico = dato["solicitudes"][0]["diagnostico_proveedor"]
    assert diagnostico["categoria"] == categoria and diagnostico["fundamento"]["fuente"] == fuente
    assert diagnostico["codigo_proveedor"] == error["code"]
    assert diagnostico["tipo_proveedor"] == "invalid_request_error"
    assert diagnostico["failed_generation_presente"] is True
    assert dato["motivo_detencion"] == "ERROR_HTTP" and delegado.handle_request.call_count == 1
    # Observar no modifica la respuesta que recibira el SDK.
    assert respuesta.json()["error"] == error
    with pytest.raises(evaluador.DetencionEvaluacion, match="ERROR_HTTP"):
        consultar(consumo)
    guardado = consumo.ruta.read_text(encoding="utf-8")
    assert all(s not in guardado for s in ("gsk_privado", "razonamiento_privado", "persona@", error["message"]))


@pytest.mark.parametrize("error,regla", [
    ({"code": "tool_use_failed", "message": "Failed to call a function"}, "SIN_SENAL_ESPECIFICA"),
    ({"message": "Tool was not offered. Arguments are not valid JSON"}, "SENALES_AMBIGUAS"),
    ({"message": "Invalid messages", "param": "temperature"}, "SENALES_AMBIGUAS"),
    ({"code": "gsk_privado", "type": "persona@empresa.cl", "message": ["secreto"]}, "SIN_SENAL_ESPECIFICA"),
    ({"code": {"secreto": "privado"}, "type": ["secreto"], "param": {"secreto": "privado"}}, "SIN_SENAL_ESPECIFICA"),
    ({"message": "Invalid messages " + "x" * evaluador.MAX_MENSAJE_DIAGNOSTICO}, "SIN_SENAL_ESPECIFICA"),
])
def test_diagnostico_ambiguo_desconocido_o_mensaje_excesivo_no_inventa_causa(control, error, regla):
    consumo = control()
    consultar(consumo, httpx.Response(400, json={"error": error}))
    d = consumo.leer()["solicitudes"][0]["diagnostico_proveedor"]
    assert d["categoria"] == "NO_CLASIFICADO" and d["fundamento"]["regla"] == regla
    assert d["failed_generation_presente"] is False
    assert all(s not in consumo.ruta.read_text() for s in ("gsk_privado", "persona@", "secreto"))


@pytest.mark.parametrize("contenido,estructura", [
    (b"<html>gsk_privado</html>", "NO_JSON"),
    (b'["gsk_privado"]', "JSON_NO_OBJETO"),
    (b'{"error":"gsk_privado"}', "ERROR_NO_OBJETO"),
    (b"x" * (evaluador.MAX_JSON_DIAGNOSTICO + 1), "EXCESIVO"),
    (b"\xff", "NO_JSON"),
], ids=["no-json", "json-lista", "error-no-objeto", "excesivo", "utf8-invalido"])
def test_diagnostico_cuerpos_no_json_malformados_o_excesivos(control, contenido, estructura):
    consumo = control()
    respuesta, _ = consultar(consumo, httpx.Response(400, content=contenido))
    d = consumo.leer()["solicitudes"][0]["diagnostico_proveedor"]
    assert d["categoria"] == "NO_CLASIFICADO" and d["fundamento"]["estructura"] == estructura
    assert d["failed_generation_presente"] is None
    assert d["codigo_proveedor"] == d["tipo_proveedor"] == "DESCONOCIDO"
    assert respuesta.content == contenido and "gsk_privado" not in consumo.ruta.read_text()


def test_diagnostico_no_inspecciona_contenido_de_failed_generation(control):
    consumo = control()
    consultar(consumo, httpx.Response(400, json={"error": {
        "code": "tool_use_failed", "message": "Failed to call a function",
        "failed_generation": {"reason": "Arguments are not valid JSON", "texto": "cuerpo_privado"}}}))
    d = consumo.leer()["solicitudes"][0]["diagnostico_proveedor"]
    assert d["categoria"] == "NO_CLASIFICADO" and d["failed_generation_presente"] is True
    assert "cuerpo_privado" not in consumo.ruta.read_text() and "Arguments" not in consumo.ruta.read_text()


def test_json_que_agota_recursion_conserva_detencion_y_reserva(control, monkeypatch):
    consumo = control()
    contenido = b"[[[]]]"
    original = evaluador.json.loads
    def decodificar(dato, *args, **kwargs):
        if dato == contenido:
            raise RecursionError("gsk_privado")
        return original(dato, *args, **kwargs)
    monkeypatch.setattr(evaluador.json, "loads", decodificar)
    consultar(consumo, httpx.Response(400, content=contenido))
    dato = consumo.leer()
    s = dato["solicitudes"][0]
    assert dato["motivo_detencion"] == "ERROR_HTTP" and s["origen"] == "estimacion"
    assert s["tokens_operativos"] == s["entrada_estimada"] + s["salida_estimada"]
    assert s["diagnostico_proveedor"]["fundamento"]["estructura"] == "NO_JSON"
    assert "gsk_privado" not in consumo.ruta.read_text()


def test_cuerpo_excesivo_no_altera_contabilidad_existente_de_usage(control):
    consumo = control()
    consultar(consumo, httpx.Response(400, json={"usage": {"total_tokens": 21}, "error": {
        "message": "Invalid messages", "failed_generation": "x" * evaluador.MAX_JSON_DIAGNOSTICO}}))
    s = consumo.leer()["solicitudes"][0]
    assert s["total_informado"] == s["tokens_operativos"] == 21 and s["origen"] == "proveedor"
    assert s["diagnostico_proveedor"]["fundamento"]["estructura"] == "EXCESIVO"


def test_solicitud_solo_persiste_estructura_y_opciones_sin_argumentos_o_credenciales(control):
    consumo = control()
    payload = {"messages": [{"role": "system", "content": "razonamiento_privado"},
                             {"role": "user", "content": "persona@empresa.cl"},
                             {"role": "gsk_privado", "content": "nota_privada"}],
               "tools": [{"type": "function", "function": {"name": "consultar_ticket",
                           "parameters": {"secreto": "gsk_privado"}}},
                         {"type": "function", "function": {"name": "persona@empresa.cl"}}],
               "tool_choice": {"type": "function", "function": {"name": "consultar_ticket", "arguments": "nota_privada"}},
               "parallel_tool_calls": False, "api_key": "gsk_privado"}
    delegado = httpx.MockTransport(lambda r: httpx.Response(200, json={"usage": {"total_tokens": 12}}))
    with httpx.Client(transport=evaluador.TransporteControlado(delegado, consumo, "inicial")) as c:
        c.post("https://sin-red.invalid", json=payload, headers={"authorization": "Bearer gsk_privado"})
    s = consumo.leer()["solicitudes"][0]
    assert s["solicitud"] == {"bytes": s["entrada_estimada"] - 256, "estructura": "JSON_OBJETO",
        "cantidad_mensajes": 3, "roles": ["system", "user", "DESCONOCIDO"], "roles_truncados": False,
        "herramientas_ofrecidas": ["consultar_ticket"], "tool_choice": "funcion",
        "funcion_elegida": "consultar_ticket", "parallel_tool_calls": False}
    assert s["diagnostico_proveedor"] is None and s["tokens_operativos"] == 12
    assert all(x not in consumo.ruta.read_text() for x in (
        "gsk_privado", "razonamiento_privado", "persona@", "nota_privada", "authorization", "arguments", "parameters", "api_key"))


@pytest.mark.parametrize("choice", ["auto", "required", "none", "gsk_privado", {"type": "function", "function": {"name": "gsk_privado"}}, ["secreto"]])
def test_opciones_solicitud_se_filtran_por_lista_permitida(choice):
    contenido = json.dumps({"messages": [{"role": {"dato": "secreto"}}], "tools": [None, "secreto"],
                            "tool_choice": choice, "parallel_tool_calls": "gsk_privado"}).encode()
    meta = evaluador.metadatos_solicitud(contenido)
    assert meta["roles"] == ["DESCONOCIDO"] and meta["parallel_tool_calls"] is None
    assert all(x not in json.dumps(meta) for x in ("gsk_privado", "secreto"))
    assert meta["tool_choice"] in ("auto", "required", "none", "funcion", "DESCONOCIDO")


def test_metadatos_limitan_roles_y_no_inventan_estructura_de_payload_excesivo():
    contenido = json.dumps({"messages": [{"role": "user", "content": "secreto"}] * 150}).encode()
    meta = evaluador.metadatos_solicitud(contenido)
    assert meta["cantidad_mensajes"] == 150 and len(meta["roles"]) == evaluador.MAX_ROLES_DIAGNOSTICO
    assert meta["roles_truncados"] is True
    excesivo = evaluador.metadatos_solicitud(b"x" * (evaluador.MAX_JSON_DIAGNOSTICO + 1))
    assert excesivo["estructura"] == "EXCESIVO" and excesivo["cantidad_mensajes"] is None
    assert excesivo["roles"] == []


def test_timeout_y_429_conservan_rutas_y_diagnosticos_distintos(control):
    timeout = control()
    with pytest.raises(httpx.ReadTimeout):
        consultar(timeout, fallo=httpx.ReadTimeout("gsk_privado"))
    t = timeout.leer()
    assert t["motivo_detencion"] == "ERROR_TRANSPORTE"
    assert t["solicitudes"][0]["http_status"] is None and t["solicitudes"][0]["diagnostico_proveedor"] is None
    cuota = control()
    consultar(cuota, httpx.Response(429, json={"error": {"code": "rate_limit_exceeded", "type": "rate_limit_error",
                                                       "message": "Invalid messages gsk_privado"}}))
    q = cuota.leer()
    assert q["motivo_detencion"] == "HTTP_429" and q["solicitudes"][0]["http_status"] == 429
    assert q["solicitudes"][0]["diagnostico_proveedor"]["codigo_proveedor"] == "rate_limit_exceeded"
    assert q["solicitudes"][0]["diagnostico_proveedor"]["categoria"] == "NO_CLASIFICADO"


def test_integral_400_guarda_diagnostico_sanitizado_y_preserva_historicos(integral_cli):
    simular, confirmar, _, peticiones, fases, _ = integral_cli
    previo = {"fecha_utc": "historico", "aprobado": False, "motivo_detencion": "ERROR_HTTP"}
    evaluador.config.DIR_CACHE.mkdir(parents=True)
    evaluador.guardar_json(evaluador.config.DIR_CACHE / "ep2_plan_controlado.json", {"intentos": [previo]})
    historico = evaluador.config.DIR_CACHE / "ep2_plan_real.json"
    historico.write_bytes(b"historico protegido")
    simular([{"role": "assistant", "content": "no guardar"}], codigo=400, error_proveedor={"error": {
        "code": "tool_use_failed", "type": "invalid_request_error",
        "message": "Tool choice is required, but model did not call a tool. persona@empresa.cl",
        "failed_generation": "razonamiento_privado gsk_privado"}})
    assert correr() == 1
    intento = evidencia()
    assert fases == ["inicial"] and len(peticiones) == intento["cantidad_solicitudes"] == 1
    assert intento["motivo_detencion"] == "ERROR_HTTP" and not intento["aprobado"]
    s = intento["solicitudes"][0]
    assert s["http_status"] == 400 and s["origen"] == "estimacion" and s["total_informado"] is None
    assert s["diagnostico_proveedor"]["categoria"] == "HERRAMIENTA_REQUERIDA_AUSENTE"
    assert intento["pasos"][0]["consumo"][0] == s
    assert s["solicitud"]["herramientas_ofrecidas"] == ["consultar_ticket"]
    assert s["solicitud"]["tool_choice"] == "required"
    assert s["solicitud"]["cantidad_mensajes"] == len(peticiones[0]["messages"])
    assert json.loads((evaluador.config.DIR_CACHE / "ep2_plan_controlado.json").read_text())["intentos"][0] == previo
    assert historico.read_bytes() == b"historico protegido"
    assert all(x not in json.dumps(intento) for x in ("persona@", "razonamiento_privado", "gsk_privado"))
    assert intento["pasos"][0]["notas"] == intento["pasos"][0]["auditoria"] == 0
    confirmar.assert_not_called()
