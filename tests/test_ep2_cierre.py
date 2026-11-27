"""Cierre determinista de planes completos; Groq y HTTP siempre simulados."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from unittest.mock import Mock

import httpx
import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from pydantic import Field

from data import seed_db
from src.ep2.agente import AgenteEP2
from src.ep2.almacenamiento import AlmacenEP2
from src.ep2.configuracion import ConfiguracionAgente
from src.ep2.contratos import ContextoEjecucion
from src.ep2.planificacion import Planificador
from src.ep2 import reintentos
from src.ep2.herramientas import HerramientasEP2
from src.retriever import ConectorITSM, RecuperadorVectorial
from tests.utilidades import construir_fragmento_de_prueba, crear_faiss_de_prueba

TICKET = "INC-2026-0411"
CONSULTA = f"Consulta ticket {TICKET}, su SLA y busca el procedimiento KB-RED-02 para VPN."


class CuotaAgotada(Exception):
    status_code = 429


class ModeloAcotado(FakeMessagesListChatModel):
    llamadas: int = 0
    max_llamadas: int
    enlaces: list = Field(default_factory=list)

    def bind_tools(self, herramientas, **kwargs):
        self.enlaces.append(([h.name for h in herramientas], kwargs))
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.llamadas += 1
        if self.llamadas > self.max_llamadas:
            raise CuotaAgotada("CUOTA_SIMULADA")
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def llamar(nombre, **args):
    return AIMessage(content="", tool_calls=[{"name": nombre, "args": args, "id": nombre}])


def lecturas():
    return [llamar("consultar_ticket", ticket_id=TICKET), llamar("consultar_sla", prioridad="P2"),
            llamar("buscar_procedimiento", consulta="KB-RED-02")]


@pytest.fixture(autouse=True)
def sin_espera_real(monkeypatch):
    monkeypatch.setattr(reintentos, "sleep", Mock())


@pytest.fixture()
def entorno(tmp_path):
    ruta = tmp_path / "itsm.db"
    seed_db.crear_base(ruta)
    servicio = HerramientasEP2(ContextoEjecucion(usuario_id="prueba", sesion_id="cierre", perfil="agente"),
                               AlmacenEP2(tmp_path / "ep2"), ConectorITSM(ruta))
    doc = construir_fragmento_de_prueba(documento="kb_conectividad_vpn.md", titulo="KB-RED-02 · VPN",
        texto="EVIDENCIA_RAG_VERIFICADA: consultar el procedimiento de VPN.").documento
    recuperador = RecuperadorVectorial(almacen=crear_faiss_de_prueba([(doc, [-1.0, 0.0])]))
    return servicio, recuperador, ruta


def test_plan_completo_no_hace_peticion_final_que_agotaria_cuota(entorno):
    servicio, recuperador, ruta = entorno
    antes = ruta.read_bytes()
    llm = ModeloAcotado(responses=lecturas(), max_llamadas=3)
    agente = AgenteEP2(servicio, recuperador=recuperador, llm=llm)
    r = agente.responder(CONSULTA)
    assert r.estado == "ok" and llm.llamadas == 3
    assert all(p.estado == "completado" for p in r.plan_final.pasos)
    assert "EVIDENCIA_RAG_VERIFICADA" in r.texto and "P2" in r.texto
    assert "corpus:kb_conectividad_vpn.md" in r.fuentes
    assert agente.decisiones[-1]["codigo"] == "RESPUESTA_FINAL"
    assert not agente.decisiones[-1]["modelo_respondio"]
    assert r.memoria_estado == "actualizada" and ruta.read_bytes() == antes


def test_replanificacion_cuatro_herramientas_se_cierra_con_cuatro_llamadas(entorno):
    servicio, recuperador, ruta = entorno
    primero = AgenteEP2(servicio, recuperador=recuperador,
                       llm=ModeloAcotado(responses=lecturas(), max_llamadas=3))
    assert primero.responder(CONSULTA).estado == "ok"
    previo = primero.memoria.recuperar().plan
    antes = ruta.read_bytes()
    respuestas = lecturas()[:2] + [llamar("analizar_incidente", ticket_id=TICKET)] + lecturas()[2:]
    llm = ModeloAcotado(responses=respuestas, max_llamadas=4)
    agente = AgenteEP2(servicio, recuperador=recuperador, llm=llm)
    r = agente.responder("Ahora varios usuarios de la misma sucursal están afectados por la VPN.")
    assert r.estado == "ok" and llm.llamadas == 4
    assert r.plan_final.id == previo.id and r.plan_final.prioridad_registrada == "P2"
    assert len(r.plan_final.pasos) == 4 and all(p.estado == "completado" for p in r.plan_final.pasos)
    assert len(agente.herramientas) == 6 and all(d["tool_choice"] == "auto" for d in agente.decisiones[:-1])
    assert "EVIDENCIA_RAG_VERIFICADA" in r.texto and ruta.read_bytes() == antes


@pytest.mark.parametrize("iteraciones,estado", [(1, "limite"), (2, "ok")])
def test_cierre_respeta_presupuesto_y_solo_completa_si_no_hay_pendientes(entorno, iteraciones, estado):
    servicio, recuperador, _ = entorno
    llm = ModeloAcotado(responses=lecturas()[:2], max_llamadas=iteraciones)
    r = AgenteEP2(servicio, recuperador=recuperador, llm=llm,
        opciones=ConfiguracionAgente(max_iteraciones=iteraciones)).responder(f"Consulta ticket {TICKET} y su SLA.")
    assert r.estado == estado and llm.llamadas == iteraciones
    assert all(p.estado == "completado" for p in r.plan_final.pasos) == (estado == "ok")


def test_429_durante_seleccion_sigue_siendo_error(entorno):
    servicio, recuperador, _ = entorno
    llm = ModeloAcotado(responses=lecturas(), max_llamadas=2)
    agente = AgenteEP2(servicio, recuperador=recuperador, llm=llm)
    r = agente.responder(CONSULTA)
    assert r.estado == "error" and llm.llamadas == 5  # Dos reintentos de la tercera decisión.
    assert agente.decisiones[-1]["codigo"] == "HTTP_429"
    assert any(p.estado != "completado" for p in r.plan_final.pasos)


def test_confirmacion_humana_no_se_convierte_en_cierre_exitoso(entorno):
    servicio, recuperador, _ = entorno
    respuestas = lecturas()[:2] + [llamar("registrar_nota_ticket", ticket_id=TICKET, texto="Seguimiento documentado.")]
    llm = ModeloAcotado(responses=respuestas, max_llamadas=3)
    r = AgenteEP2(servicio, recuperador=recuperador, llm=llm).responder(f"Consulta ticket {TICKET}, su SLA y propón una nota.")
    assert r.estado == "requiere_confirmacion" and llm.llamadas == 3
    assert r.confirmaciones and r.plan_final.pasos[-1].estado == "bloqueado"
    with servicio.almacen._conexion() as c:
        assert c.execute("SELECT COUNT(*) FROM notas").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM auditoria").fetchone()[0] == 0


def test_modo_flexible_conserva_decision_final_del_modelo(entorno):
    servicio, recuperador, _ = entorno
    llm = ModeloAcotado(responses=[llamar("consultar_sla", prioridad="P2"), AIMessage(content="SLA consultado.")], max_llamadas=2)
    agente = AgenteEP2(servicio, recuperador=recuperador, llm=llm)
    assert agente.responder("Consulta SLA P2.").estado == "ok" and llm.llamadas == 2
    assert agente.decisiones[-1]["modelo_respondio"]


def test_error_de_ultima_herramienta_no_se_oculta_con_cierre_local(entorno):
    servicio, recuperador, _ = entorno
    servicio.consultar_sla = Mock(side_effect=RuntimeError("detalle interno"))
    llm = ModeloAcotado(responses=lecturas()[:2], max_llamadas=2)
    agente = AgenteEP2(servicio, recuperador=recuperador, llm=llm)
    r = agente.responder(f"Consulta ticket {TICKET} y su SLA.")
    assert r.estado == "error" and llm.llamadas == 2
    assert r.herramientas[-2].codigo == "ERROR_HERRAMIENTA"
    assert r.plan_final.pasos[-1].estado == "bloqueado"
    assert not any(d["codigo"] == "RESPUESTA_FINAL" for d in agente.decisiones)


def test_nuevo_turno_no_reutiliza_cierre_anterior(entorno):
    servicio, recuperador, _ = entorno
    respuestas = lecturas()[:2] + [llamar("consultar_sla", prioridad="P3"), AIMessage(content="Nueva lectura P3.")]
    llm = ModeloAcotado(responses=respuestas, max_llamadas=4)
    agente = AgenteEP2(servicio, recuperador=recuperador, llm=llm)
    assert agente.responder(f"Consulta ticket {TICKET} y su SLA.").estado == "ok"
    r = agente.responder("Consulta SLA P3.")
    assert r.estado == "ok" and "Nueva lectura P3" in r.texto and llm.llamadas == 4
    assert agente.decisiones[-1]["modelo_respondio"]


def test_http_real_simulado_no_recibe_quinta_peticion_de_cierre(entorno):
    from langchain_openai import ChatOpenAI
    servicio, recuperador, _ = entorno
    respuestas = iter(lecturas()[:2] + [llamar("analizar_incidente", ticket_id=TICKET)] + lecturas()[2:])
    peticiones = []
    def enviar(request):
        peticiones.append(json.loads(request.content))
        if len(peticiones) > 4:
            return httpx.Response(429, json={"error": {"message": "Cuota simulada", "code": "rate_limit_exceeded"}})
        salida = next(respuestas)
        llamada = salida.tool_calls[0]
        mensaje = {"role": "assistant", "content": "", "tool_calls": [{"id": llamada["id"], "type": "function",
            "function": {"name": llamada["name"], "arguments": json.dumps(llamada["args"])}}]}
        return httpx.Response(200, json={"id": "local", "model": "simulado", "object": "chat.completion", "created": 1,
            "choices": [{"index": 0, "message": mensaje, "finish_reason": "tool_calls"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}})
    with httpx.Client(transport=httpx.MockTransport(enviar)) as cliente:
        llm = ChatOpenAI(model="openai/gpt-oss-20b", api_key="falsa", base_url="https://sin-red.invalid/v1",
                         http_client=cliente, max_retries=0)
        r = AgenteEP2(servicio, recuperador=recuperador, llm=llm).responder(
            f"Consulta ticket {TICKET}, su SLA, analiza el incidente y busca el procedimiento KB-RED-02.")
    assert r.estado == "ok" and len(peticiones) == 4
    assert all(p["tools"] and p["tool_choice"] == "auto" for p in peticiones)


@pytest.mark.parametrize("texto,permitida", [
    ("Prepara una nota sin registrarla todavía.", True),
    ("Necesito preparar una nota; no la registres todavía.", True),
    ("Prepárame una nota sin guardarla.", True),
    ("Redacta una nota para revisión humana.", True),
    ("Quiero proponer una nota.", True),
    ("No prepares una nota.", False),
    ("No quiero preparar una nota.", False),
    ("Sin preparar una nota, muestra el estado.", False),
    ("No propongas notas todavía.", False),
    ("Varios usuarios afectados por VPN, no prepares ninguna nota.", False),
    ("Muestra el plan sin ejecutar acciones ni preparar una nota.", False),
    ("No modifiques el ticket ni prepares una nota.", False),
    ("No registres nada, pero prepara una nota para revisión.", True),
])
def test_intencion_de_preparacion_no_es_autorizacion_de_escritura(texto, permitida):
    planificador = Planificador(texto, ticket_activo=TICKET)
    assert planificador.permite_nota == permitida
    assert any(p.herramienta == "registrar_nota_ticket" for p in planificador.plan.pasos) == permitida


@pytest.mark.parametrize("reiniciar", [False, True], ids=("misma_instancia", "nueva_instancia"))
@pytest.mark.parametrize("peticion", ["Prepara una nota", "Necesito preparar una nota"])
def test_preparar_nota_tras_impacto_completado_muestra_confirmacion_sin_escribir(entorno, capsys, reiniciar, peticion):
    from src.ep2.cli import resolver_confirmaciones

    servicio, recuperador, ruta = entorno
    antes = ruta.read_bytes()
    revalidar = lecturas()[:2] + [llamar("analizar_incidente", ticket_id=TICKET)] + lecturas()[2:]
    texto_nota = "Reporte de varios usuarios de la misma sucursal afectados por VPN; alcance pendiente de verificación."
    preparar = revalidar + [llamar("registrar_nota_ticket", ticket_id=TICKET, texto=texto_nota)]
    respuestas = lecturas() + revalidar + ([] if reiniciar else preparar)
    llm = ModeloAcotado(responses=respuestas, max_llamadas=len(respuestas))
    agente = AgenteEP2(servicio, recuperador=recuperador, llm=llm)
    assert agente.responder(CONSULTA).estado == "ok"
    impacto = agente.responder("Ahora varios usuarios de la misma sucursal están afectados por la VPN.")
    assert impacto.estado == "ok" and len(impacto.plan_final.pasos) == 4
    assert all(p.estado == "completado" for p in impacto.plan_final.pasos)
    previo = impacto.plan_final
    if reiniciar:
        almacen = AlmacenEP2(servicio.almacen.ruta.parent)
        servicio = HerramientasEP2(servicio.contexto, almacen, ConectorITSM(ruta))
        llm = ModeloAcotado(responses=preparar, max_llamadas=5)
        agente = AgenteEP2(servicio, recuperador=recuperador, llm=llm)
    r = agente.responder(f"{peticion} para {TICKET} sobre varios usuarios afectados por VPN, sin registrarla todavía.")
    assert r.estado == "requiere_confirmacion" and len(r.confirmaciones) == 1
    assert r.plan_final.id == previo.id and r.plan_final.prioridad_registrada == previo.prioridad_registrada == "P2"
    assert [t.nombre for t in r.herramientas] == ["consultar_ticket", "consultar_sla",
        "analizar_incidente", "buscar_procedimiento", "registrar_nota_ticket"]
    assert llm.enlaces[-1][0] == ["registrar_nota_ticket"]
    assert llm.llamadas == (5 if reiniciar else 12)
    assert all(d["tool_choice"] == "auto" for d in agente.decisiones)
    nota = next(p for p in r.plan_final.pasos if p.herramienta == "registrar_nota_ticket")
    assert nota.estado == "bloqueado" and nota.codigo == "CONFIRMACION_REQUERIDA"
    assert set(nota.dependencias) == {p.id for p in r.plan_final.pasos if p.herramienta != "registrar_nota_ticket"}
    assert r.confirmaciones[0].texto == texto_nota and texto_nota in r.texto
    assert "todavía no se ha registrado" in r.texto
    assert not any(d["codigo"] == "RESPUESTA_FINAL" for d in agente.decisiones)
    persistido = agente.memoria.recuperar()
    assert persistido.plan.model_dump_json() == r.plan_final.model_dump_json()
    assert texto_nota not in persistido.model_dump_json()
    confirmar = Mock(wraps=agente.confirmar_nota)
    agente.confirmar_nota = confirmar
    preguntas = []
    def posponer(pregunta):
        preguntas.append(pregunta)
        return "POSPONER"
    resolver_confirmaciones(agente, r, leer=posponer)
    confirmar.assert_not_called()
    assert len(preguntas) == 1 and "CONFIRMAR" in preguntas[0]
    assert texto_nota in capsys.readouterr().out
    assert r.escrituras_realizadas == 0 and ruta.read_bytes() == antes
    with servicio.almacen._conexion() as c:
        assert c.execute("SELECT COUNT(*) FROM notas").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM auditoria").fetchone()[0] == 0


def test_preparar_nota_no_elude_perfil_usuario_final(entorno):
    servicio, recuperador, _ = entorno
    usuario = HerramientasEP2(servicio.contexto.model_copy(update={"perfil": "usuario_final"}), servicio.almacen)
    llm = ModeloAcotado(responses=[llamar("registrar_nota_ticket", ticket_id=TICKET, texto="Propuesta.")], max_llamadas=0)
    r = AgenteEP2(usuario, recuperador=recuperador, llm=llm).responder(f"Prepara una nota para {TICKET}, sin registrarla.")
    assert r.estado == "denegado" and llm.llamadas == 0 and not r.confirmaciones


def test_demo_replanificar_y_preparar_en_un_turno_reduce_doce_llamadas_a_ocho(entorno):
    servicio, recuperador, ruta = entorno
    antes = ruta.read_bytes()
    revalidar = lecturas()[:2] + [llamar("analizar_incidente", ticket_id=TICKET)] + lecturas()[2:]
    preparar = llamar("registrar_nota_ticket", ticket_id=TICKET, texto="Reporte de impacto VPN; alcance pendiente de verificación.")
    llm = ModeloAcotado(responses=lecturas() + revalidar + [preparar], max_llamadas=8)
    agente = AgenteEP2(servicio, recuperador=recuperador, llm=llm)
    inicial = agente.responder(CONSULTA)
    assert inicial.estado == "ok" and llm.llamadas == 3
    r = agente.responder("Ahora varios usuarios de la misma sucursal están afectados por la VPN. "
        "Reevalúa el reporte y prepara una nota de seguimiento para ese ticket, sin registrarla todavía.")
    assert r.estado == "requiere_confirmacion" and llm.llamadas == 8
    assert r.plan_final.id == inicial.plan_final.id and r.plan_final.prioridad_registrada == "P2"
    assert [t.nombre for t in r.herramientas] == ["consultar_ticket", "consultar_sla", "analizar_incidente",
        "buscar_procedimiento", "registrar_nota_ticket"]
    assert all(p.estado == "completado" for p in r.plan_final.pasos if p.herramienta != "registrar_nota_ticket")
    nota = next(p for p in r.plan_final.pasos if p.herramienta == "registrar_nota_ticket")
    assert nota.codigo == "CONFIRMACION_REQUERIDA" and nota.estado == "bloqueado"
    assert set(nota.dependencias) == {p.id for p in r.plan_final.pasos if p.herramienta != "registrar_nota_ticket"}
    assert len(r.confirmaciones) == 1 and r.escrituras_realizadas == 0
    assert all(d["tool_choice"] == "auto" for d in agente.decisiones)
    assert llm.enlaces[-1][0] == ["registrar_nota_ticket"]
    assert ruta.read_bytes() == antes
    with servicio.almacen._conexion() as c:
        assert c.execute("SELECT COUNT(*) FROM notas").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM auditoria").fetchone()[0] == 0


@pytest.mark.parametrize("cambio", ["ticket", "documento"])
def test_memoria_reciente_no_sustituye_revalidacion_de_fuentes_mutables(entorno, cambio):
    servicio, recuperador, ruta = entorno
    revalidar = lecturas()[:2] + [llamar("analizar_incidente", ticket_id=TICKET)] + lecturas()[2:]
    agente = AgenteEP2(servicio, recuperador=recuperador,
        llm=ModeloAcotado(responses=lecturas() + revalidar, max_llamadas=7))
    assert agente.responder(CONSULTA).estado == "ok"
    assert agente.responder("Ahora varios usuarios de la misma sucursal están afectados por la VPN.").estado == "ok"
    guardado = agente.memoria.recuperar()
    assert all(p.estado == "completado" for p in guardado.plan.pasos)
    assert next(h for h in guardado.hechos if h.clave == f"ticket:{TICKET}").valor["prioridad"] == "P2"
    if cambio == "ticket":
        with closing(sqlite3.connect(ruta)) as c, c:
            c.execute("UPDATE tickets SET prioridad='P3' WHERE id=?", (TICKET,))
        prioridad = "P3"
    else:
        prioridad = "P2"
        for identificador in recuperador.almacen.index_to_docstore_id.values():
            recuperador.almacen.docstore.search(identificador).page_content = "PROCEDIMIENTO_ACTUALIZADO_SIN_CAMBIAR_TITULO_NI_FECHA"
        assert "PROCEDIMIENTO_ACTUALIZADO" not in guardado.model_dump_json()
    respuestas = [llamar("consultar_ticket", ticket_id=TICKET), llamar("consultar_sla", prioridad=prioridad),
        llamar("analizar_incidente", ticket_id=TICKET), llamar("buscar_procedimiento", consulta="KB-RED-02"),
        llamar("registrar_nota_ticket", ticket_id=TICKET, texto="Preparar seguimiento con las fuentes actuales.")]
    llm = ModeloAcotado(responses=respuestas, max_llamadas=5)
    siguiente = AgenteEP2(servicio, recuperador=recuperador, llm=llm)
    r = siguiente.responder(f"Prepara una nota para {TICKET} sobre varios usuarios afectados por VPN, sin registrarla.")
    assert r.estado == "requiere_confirmacion" and llm.llamadas == 5
    assert r.plan_final.id == guardado.plan.id and r.plan_final.prioridad_registrada == prioridad
    assert [t.nombre for t in r.herramientas] == ["consultar_ticket", "consultar_sla", "analizar_incidente",
        "buscar_procedimiento", "registrar_nota_ticket"]
    assert siguiente._resultados[0].datos["prioridad"] == prioridad
    if cambio == "documento":
        actual = next(o for o in siguiente._observaciones if o.herramienta == "buscar_procedimiento")
        assert "PROCEDIMIENTO_ACTUALIZADO" in actual.resultado.datos["fragmentos"][0]["texto"]
    with servicio.almacen._conexion() as c:
        assert c.execute("SELECT COUNT(*) FROM notas").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM auditoria").fetchone()[0] == 0


def test_429_antes_de_preparar_tercera_consulta_no_se_convierte_en_exito(entorno):
    servicio, recuperador, _ = entorno
    revalidar = lecturas()[:2] + [llamar("analizar_incidente", ticket_id=TICKET)] + lecturas()[2:]
    preparar = llamar("registrar_nota_ticket", ticket_id=TICKET, texto="Seguimiento VPN.")
    llm = ModeloAcotado(responses=lecturas() + revalidar + revalidar + [preparar], max_llamadas=11)
    agente = AgenteEP2(servicio, recuperador=recuperador, llm=llm)
    assert agente.responder(CONSULTA).estado == "ok"
    assert agente.responder("Ahora varios usuarios de la misma sucursal están afectados por la VPN.").estado == "ok"
    r = agente.responder("Prepara una nota sobre varios usuarios afectados por VPN, sin registrarla todavía.")
    assert r.estado == "error" and llm.llamadas == 14  # La duodécima decisión se reintenta dos veces.
    assert agente.decisiones[-1]["codigo"] == "HTTP_429"
    assert not r.confirmaciones and not any(t.nombre == "registrar_nota_ticket" for t in r.herramientas)
    assert next(p for p in r.plan_final.pasos if p.herramienta == "registrar_nota_ticket").estado != "completado"
    with servicio.almacen._conexion() as c:
        assert c.execute("SELECT COUNT(*) FROM notas").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM auditoria").fetchone()[0] == 0


@pytest.mark.parametrize("rechazos,agotado", [(1, False), (2, False), (3, True)])
def test_429_antes_de_nota_solo_repite_inferencia_y_conserva_verificaciones(
    entorno, monkeypatch, caplog, rechazos, agotado,
):
    from langchain_openai import ChatOpenAI
    servicio, recuperador, ruta = entorno
    itsm_antes = ruta.read_bytes()
    reloj = [100.0]
    esperas = []
    def esperar(segundos):
        esperas.append(segundos)
        reloj[0] += segundos
    monkeypatch.setattr(reintentos, "sleep", esperar)
    monkeypatch.setattr(reintentos, "monotonic", lambda: reloj[0])
    monkeypatch.setattr("src.ep2.agente.monotonic", lambda: reloj[0])
    confirmar = Mock(side_effect=AssertionError("La inferencia no autoriza escrituras."))
    monkeypatch.setattr(servicio, "confirmar_nota", confirmar)
    respuestas = iter(lecturas() + lecturas()[:2] + [llamar("analizar_incidente", ticket_id=TICKET)]
        + lecturas()[2:] + [llamar("registrar_nota_ticket", ticket_id=TICKET,
            texto="Reporte de varios afectados por VPN; alcance pendiente de verificación.")])
    peticiones, planes, resultados = [], [], []
    def enviar(request):
        assert request.url.host == "sin-red.invalid"
        peticiones.append(request.content)
        if len(peticiones) >= 8:
            assert {t["function"]["name"] for t in json.loads(request.content)["tools"]} == {"registrar_nota_ticket"}
            planes.append(agente._planificador.plan.model_dump(mode="json"))
            resultados.append([r.model_dump(mode="json") for r in agente._resultados])
            if len(peticiones) - 7 <= rechazos:
                return httpx.Response(429, headers={"retry-after": "2.91", "authorization": "NO_PUBLICAR"},
                    json={"error": {"code": "rate_limit_exceeded", "message": "NO_PUBLICAR Please try again in 2.91s."}})
        llamada = next(respuestas).tool_calls[0]
        mensaje = {"role": "assistant", "content": "", "tool_calls": [{"id": llamada["id"], "type": "function",
            "function": {"name": llamada["name"], "arguments": json.dumps(llamada["args"])}}]}
        return httpx.Response(200, json={"id": "simulado", "object": "chat.completion", "created": 1,
            "model": "openai/gpt-oss-20b", "choices": [{"index": 0, "message": mensaje, "finish_reason": "tool_calls"}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}})
    with httpx.Client(transport=httpx.MockTransport(enviar)) as cliente:
        llm = ChatOpenAI(model="openai/gpt-oss-20b", api_key="falsa", base_url="https://sin-red.invalid/v1",
            http_client=cliente, max_retries=0)
        agente = AgenteEP2(servicio, recuperador=recuperador, llm=llm,
            opciones=ConfiguracionAgente(max_iteraciones=5))
        inicial = agente.responder(CONSULTA)
        assert inicial.estado == "ok" and len(peticiones) == 3
        r = agente.responder("Ahora varios usuarios de la misma sucursal están afectados por la VPN. "
            "Reevalúa el reporte y prepara una nota de seguimiento para ese ticket, sin registrarla todavía.")
    assert len(peticiones) == 8 + min(rechazos, 2)
    assert esperas == [2.91] * min(rechazos, 2)
    assert all(p == peticiones[7] for p in peticiones[7:])
    assert all(p == planes[0] for p in planes)
    assert all(o == resultados[0] for o in resultados) and len(resultados[0]) == 4
    assert r.plan_final.id == inicial.plan_final.id and r.plan_final.prioridad_registrada == "P2"
    lecturas_finales = [p.model_dump(mode="json") for p in r.plan_final.pasos if p.herramienta != "registrar_nota_ticket"]
    assert lecturas_finales == [p for p in planes[0]["pasos"] if p["herramienta"] != "registrar_nota_ticket"]
    assert all(p["estado"] == "completado" and p["intentos"] == 1 for p in lecturas_finales)
    assert [t.nombre for t in r.herramientas[:4]] == ["consultar_ticket", "consultar_sla", "analizar_incidente", "buscar_procedimiento"]
    nota = next(p for p in r.plan_final.pasos if p.herramienta == "registrar_nota_ticket")
    assert set(nota.dependencias) == {p["id"] for p in lecturas_finales}
    assert len(agente.decisiones) == 5 and all(d["tool_choice"] == "auto" for d in agente.decisiones)
    if agotado:
        assert r.estado == "error" and "HTTP 429" in r.texto
        assert agente.decisiones[-1]["codigo"] == "HTTP_429"
        assert nota.estado == "bloqueado" and nota.codigo == "EJECUCION_INTERRUMPIDA"
        assert nota.intentos == 0 and not r.confirmaciones and len(r.herramientas) == 4
    else:
        assert r.estado == "requiere_confirmacion" and len(r.confirmaciones) == 1
        assert nota.estado == "bloqueado" and nota.codigo == "CONFIRMACION_REQUERIDA"
        assert nota.intentos == 1 and len(r.herramientas) == 5
        assert r.herramientas[-1].nombre == "registrar_nota_ticket"
    guardado = agente.memoria.recuperar()
    assert guardado.plan == r.plan_final and r.memoria_estado == "actualizada"
    assert "NO_PUBLICAR" not in caplog.text + str(agente.decisiones) + guardado.model_dump_json()
    assert caplog.text.count("EP2 HTTP 429") == min(rechazos, 2)
    assert ruta.read_bytes() == itsm_antes and r.escrituras_realizadas == 0
    confirmar.assert_not_called()
    with servicio.almacen._conexion() as c:
        assert c.execute("SELECT COUNT(*) FROM notas").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM auditoria").fetchone()[0] == 0
