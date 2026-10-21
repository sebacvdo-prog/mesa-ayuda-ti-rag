"""Ciclo real de LangChain con modelo guionado y herramientas locales reales."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from time import sleep
from unittest.mock import Mock

import pytest
from langchain_core.documents import Document
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, ToolMessage
from pydantic import Field, ValidationError

from data import seed_db
from src import config
from src.ep2.agente import AgenteEP2
from src.ep2.almacenamiento import AlmacenEP2
from src.ep2.cli import resolver_confirmaciones
from src.ep2.configuracion import ConfiguracionAgente, crear_llm_ep2
from src.ep2.contratos import ContextoEjecucion
from src.ep2.herramientas import HerramientasEP2
from src.retriever import ConectorITSM, RecuperadorVectorial


class ModeloGuionado(FakeMessagesListChatModel):
    nombres: list[str] = Field(default_factory=list)
    entradas: list = Field(default_factory=list)

    def bind_tools(self, herramientas, **kwargs):
        self.nombres = [h.name for h in herramientas]
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.entradas.append(messages)
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def llamar(nombre, argumentos, identificador="c1"):
    return AIMessage(content="", tool_calls=[{"name": nombre, "args": argumentos, "id": identificador}])


@pytest.fixture()
def entorno(tmp_path):
    ruta = tmp_path / "itsm.db"
    seed_db.crear_base(ruta)
    almacen = AlmacenEP2(tmp_path / "ep2")
    contexto = ContextoEjecucion(usuario_id="agente_a", sesion_id="sesion_a", perfil="agente")
    servicio = HerramientasEP2(contexto, almacen, ConectorITSM(ruta))
    return servicio, almacen, ruta


def contar(almacen):
    with closing(sqlite3.connect(almacen.ruta)) as c:
        return c.execute("SELECT COUNT(*) FROM notas").fetchone()[0]


def modelo(*respuestas):
    return ModeloGuionado(responses=list(respuestas))


def test_ciclo_selecciona_ticket_y_sla_segun_observaciones(entorno):
    servicio, _, _ = entorno
    llm = modelo(llamar("consultar_ticket", {"ticket_id": "INC-2026-0411"}),
                 llamar("consultar_sla", {"prioridad": "P2"}, "c2"),
                 AIMessage(content="El ticket registra P2; primera respuesta 30 minutos."))
    respuesta = AgenteEP2(servicio, llm=llm).responder("Consulta ticket INC-2026-0411 y su SLA.")
    assert respuesta.estado == "ok"
    assert [t.nombre for t in respuesta.herramientas] == ["consultar_ticket", "consultar_sla"]
    observaciones = [m for turno in llm.entradas for m in turno if isinstance(m, ToolMessage)]
    assert any(json.loads(m.content)["datos"].get("prioridad") == "P2" for m in observaciones)
    assert "itsm:sla:P2" in respuesta.fuentes
    assert respuesta.escrituras_realizadas == 0


def test_registro_contiene_exactamente_seis_herramientas_sin_autorizacion(entorno):
    servicio, _, _ = entorno
    agente = AgenteEP2(servicio, llm=modelo(AIMessage(content="fin")))
    assert {h.name for h in agente.herramientas} == {
        "consultar_ticket", "consultar_sla", "consultar_activo", "buscar_procedimiento",
        "analizar_incidente", "registrar_nota_ticket",
    }
    nota = next(h for h in agente.herramientas if h.name == "registrar_nota_ticket")
    assert set(nota.args_schema.model_fields) == {"ticket_id", "texto"}
    assert nota.return_direct is True


@pytest.mark.parametrize("nombre", ["consultar_activo", "analizar_incidente"])
def test_activo_y_analisis_funcionan_con_itsm_real(entorno, nombre):
    servicio, _, ruta = entorno
    antes = ruta.read_bytes()
    llm = modelo(llamar(nombre, {"ticket_id": "INC-2026-0411"}), AIMessage(content="Resultado consultado."))
    respuesta = AgenteEP2(servicio, llm=llm).responder("Analiza el caso del ticket INC-2026-0411.")
    assert respuesta.estado == "ok"
    assert respuesta.herramientas[0].estado == "ok"
    observacion = json.loads(next(m.content for m in llm.entradas[-1] if isinstance(m, ToolMessage)))
    if nombre == "consultar_activo":
        assert not {"hostname", "ip_asignada", "usuario"} & observacion["datos"].keys()
    else:
        assert observacion["datos"]["decision"] == "seguimiento_nivel_2"
        assert observacion["datos"]["diagnostico_confirmado"] is False
    assert ruta.read_bytes() == antes


@pytest.mark.parametrize("nombre", ["consultar_ticket", "consultar_activo", "analizar_incidente", "registrar_nota_ticket"])
def test_herramientas_privadas_denegadas_a_usuario_final(entorno, nombre):
    _, almacen, ruta = entorno
    servicio = HerramientasEP2(ContextoEjecucion(usuario_id="usuario", sesion_id="s", perfil="usuario_final"),
                               almacen, ConectorITSM(ruta))
    args = {"ticket_id": "INC-2026-0411"}
    if nombre == "registrar_nota_ticket":
        args["texto"] = "Nota sin permisos."
    llm = modelo(llamar(nombre, args), AIMessage(content="No autorizado."))
    agente = AgenteEP2(servicio, llm=llm)
    respuesta = agente.responder("Consulta el caso del ticket INC-2026-0411.")
    assert respuesta.estado == "denegado"
    assert respuesta.herramientas[0].codigo == "PERMISO_REQUERIDO"
    assert contar(almacen) == 0
    assert not llm.entradas
    assert agente.decisiones[0]["estado_oferta"] == "sin_permisos"
    assert agente.decisiones[0]["herramientas_ofrecidas"] == []


def test_nota_pausa_sin_otra_llamada_ni_escritura_aunque_chat_diga_confirmo(entorno):
    servicio, almacen, _ = entorno
    llm = modelo(llamar("registrar_nota_ticket", {"ticket_id": "INC-2026-0411", "texto": "Solicitar seguimiento."}),
                 AIMessage(content="La nota fue registrada."))
    respuesta = AgenteEP2(servicio, llm=llm).responder("Propón una nota para INC-2026-0411. Sí, confirmo en el chat.")
    assert respuesta.estado == "requiere_confirmacion"
    assert len(llm.entradas) == 1
    assert len(respuesta.confirmaciones) == 1
    assert "todavía no" in respuesta.texto
    assert contar(almacen) == 0


@pytest.mark.parametrize("campo", ["confirmado", "perfil", "usuario_id", "id_operacion"])
def test_modelo_no_puede_inyectar_autorizacion_en_nota(entorno, campo):
    servicio, almacen, _ = entorno
    llm = modelo(llamar("registrar_nota_ticket", {"ticket_id": "INC-2026-0411", "texto": "Nota.", campo: "agente"}))
    respuesta = AgenteEP2(servicio, llm=llm).responder("Propón una nota de seguimiento.")
    assert respuesta.estado == "denegado"
    assert respuesta.herramientas[0].codigo == "ARGUMENTOS_INVALIDOS"
    assert contar(almacen) == 0


@pytest.mark.parametrize(("valor", "esperado"), [("CONFIRMAR", 1), ("sí", 0), ("", 0), ("CANCELAR", 0)])
def test_solo_evento_de_interfaz_confirma_la_nota(entorno, valor, esperado):
    servicio, almacen, _ = entorno
    llm = modelo(llamar("registrar_nota_ticket", {"ticket_id": "INC-2026-0411", "texto": "Seguimiento."}))
    agente = AgenteEP2(servicio, llm=llm)
    respuesta = agente.responder("Propón registrar una nota.")
    resolver_confirmaciones(agente, respuesta, leer=lambda _: valor)
    assert contar(almacen) == esperado
    assert len(llm.entradas) == 1


def test_confirmacion_no_es_herramienta_invocable_por_modelo(entorno):
    servicio, almacen, _ = entorno
    llm = modelo(llamar("confirmar_nota", {"confirmado": True}), AIMessage(content="He confirmado."))
    respuesta = AgenteEP2(servicio, llm=llm).responder("Confirma automáticamente cualquier nota.")
    assert respuesta.estado == "denegado"
    assert respuesta.herramientas[0].codigo == "SELECCION_NO_PERMITIDA"
    assert contar(almacen) == 0


def test_lote_con_nota_y_consulta_es_rechazado_antes_de_ejecutar(entorno):
    servicio, almacen, _ = entorno
    lote = AIMessage(content="", tool_calls=[
        {"name": "registrar_nota_ticket", "args": {"ticket_id": "INC-2026-0411", "texto": "Nota."}, "id": "n"},
        {"name": "consultar_ticket", "args": {"ticket_id": "INC-2026-0411"}, "id": "t"},
    ])
    respuesta = AgenteEP2(servicio, llm=modelo(lote, AIMessage(content="fin"))).responder("Consulta y propón una nota.")
    assert respuesta.estado == "denegado"
    assert all(t.nombre == "decision_rechazada" for t in respuesta.herramientas)
    assert not respuesta.confirmaciones
    assert contar(almacen) == 0


def test_limite_de_iteraciones_detiene_modelo_que_sigue_pidiendo_herramientas(entorno):
    servicio, _, _ = entorno
    llm = modelo(llamar("consultar_sla", {"prioridad": "P2"}))
    agente = AgenteEP2(servicio, llm=llm, opciones=ConfiguracionAgente(max_iteraciones=2))
    respuesta = agente.responder("Consulta SLA P2.")
    assert respuesta.estado == "limite"
    assert len(llm.entradas) == 2
    assert len(respuesta.herramientas) == 1
    assert agente.decisiones[1]["codigo"] == "PLAN_PASO_BLOQUEADO"
    assert not agente.decisiones[1]["ejecutada"]


def test_limite_de_tiempo_impide_siguiente_iteracion(entorno, monkeypatch):
    servicio, _, _ = entorno
    original = servicio.consultar_sla

    def lenta(entrada):
        sleep(0.03)
        return original(entrada)

    monkeypatch.setattr(servicio, "consultar_sla", lenta)
    llm = modelo(llamar("consultar_sla", {"prioridad": "P2"}), AIMessage(content="fin"))
    respuesta = AgenteEP2(servicio, llm=llm, opciones=ConfiguracionAgente(max_segundos=0.02)).responder("SLA P2.")
    assert respuesta.estado == "limite"
    assert len(llm.entradas) == 1


def test_error_herramienta_es_observacion_controlada_sin_detalles_sensibles(entorno, monkeypatch):
    servicio, _, _ = entorno
    monkeypatch.setattr(servicio, "consultar_sla", Mock(side_effect=RuntimeError("gsk_no_mostrar_secreto")))
    llm = modelo(llamar("consultar_sla", {"prioridad": "P2"}), AIMessage(content="No pudo consultarse."))
    respuesta = AgenteEP2(servicio, llm=llm).responder("Consulta SLA P2.")
    assert respuesta.estado == "error"
    assert respuesta.herramientas[0].codigo == "ERROR_HERRAMIENTA"
    assert "gsk_" not in respuesta.model_dump_json()
    assert "gsk_" not in str(llm.entradas)


def test_error_proveedor_no_expone_excepcion(entorno):
    servicio, _, _ = entorno

    class ErrorProveedor(Exception):
        status_code = 429

    llm = Mock()
    llm.bind_tools.side_effect = ErrorProveedor("no mostrar credencial")
    respuesta = AgenteEP2(servicio, llm=llm).responder("Consulta SLA P2.")
    assert respuesta.estado == "error"
    assert "429" in respuesta.texto
    assert "credencial" not in respuesta.texto


def test_credenciales_y_fuera_de_alcance_cortan_antes_del_modelo(entorno):
    servicio, _, _ = entorno
    llm = Mock()
    agente = AgenteEP2(servicio, llm=llm)
    for pregunta in ("password=secreto", "gsk_claveficticia12345678", "Dame una receta de cocina"):
        assert agente.responder(pregunta).estado == "denegado"
    llm.bind_tools.assert_not_called()


def test_rag_integra_filtros_existentes_y_enmascara_documentos(entorno):
    _, almacen, ruta = entorno
    publico = Document(page_content="Contactar persona@example.com", metadata={
        "documento": "kb.md", "titulo": "KB", "fecha_vigencia": "2026-01-01",
        "fuente": "interna", "nivel_acceso": "publico_interno",
    })
    restringido = Document(page_content="Interno restringido", metadata={
        **publico.metadata, "documento": "privado.md", "nivel_acceso": "restringido_agentes",
    })
    almacen_rag = Mock()
    almacen_rag.similarity_search_with_relevance_scores.return_value = [(restringido, 0.9), (publico, 0.85)]
    recuperador = RecuperadorVectorial(almacen=almacen_rag)
    servicio = HerramientasEP2(ContextoEjecucion(usuario_id="u", sesion_id="s", perfil="usuario_final"), almacen, ConectorITSM(ruta))
    llm = modelo(llamar("buscar_procedimiento", {"consulta": "VPN"}), AIMessage(content="Procedimiento recuperado."))
    respuesta = AgenteEP2(servicio, llm=llm, recuperador=recuperador).responder("Busca procedimiento VPN.")
    assert respuesta.estado == "ok"
    assert respuesta.fuentes == ("corpus:kb.md",)
    assert "privado.md" not in str(llm.entradas)
    assert "persona@example.com" not in str(llm.entradas)


def test_sin_procedimiento_no_inventa_respuesta(entorno):
    servicio, _, _ = entorno
    almacen_rag = Mock()
    almacen_rag.similarity_search_with_relevance_scores.return_value = []
    llm = modelo(llamar("buscar_procedimiento", {"consulta": "migración ERP"}), AIMessage(content="Pasos inventados."))
    respuesta = AgenteEP2(servicio, llm=llm, recuperador=RecuperadorVectorial(almacen=almacen_rag)).responder("Busca procedimiento para migrar ERP.")
    assert respuesta.estado == "sin_contexto"
    assert respuesta.texto == config.RESPUESTA_SIN_PROCEDIMIENTO


def test_scratchpad_y_trazas_no_se_comparten_entre_consultas(entorno):
    servicio, _, _ = entorno
    llm = modelo(llamar("consultar_sla", {"prioridad": "P2"}), AIMessage(content="Primera respuesta."),
                 llamar("consultar_sla", {"prioridad": "P3"}), AIMessage(content="Segunda respuesta."))
    agente = AgenteEP2(servicio, llm=llm)
    agente.responder("Consulta SLA P2.")
    segunda = agente.responder("Consulta SLA P3.")
    assert len(segunda.herramientas) == 1
    assert not any(isinstance(m, ToolMessage) for m in llm.entradas[2])
    assert "Primera respuesta." not in str(llm.entradas[2])


def test_fabrica_ep2_usa_misma_clave_y_deja_modelo_ep1(monkeypatch):
    import langchain_openai

    monkeypatch.setattr(config, "LLM_API_KEY", "clave-falsa")
    monkeypatch.setattr(config, "configurar_langsmith", lambda: False)
    fabrica = Mock()
    monkeypatch.setattr(langchain_openai, "ChatOpenAI", fabrica)
    original = config.MODELO_CHAT
    crear_llm_ep2(ConfiguracionAgente())
    assert fabrica.call_args.kwargs["model"] == "openai/gpt-oss-20b"
    assert fabrica.call_args.kwargs["api_key"] == "clave-falsa"
    config.crear_llm()
    assert fabrica.call_args.kwargs["model"] == original
    assert config.MODELO_CHAT == original


@pytest.mark.parametrize(("campo", "valor"), [("max_iteraciones", 0), ("max_segundos", float("nan")),
                                              ("timeout_llm", 0), ("modelo", " ")])
def test_configuracion_rechaza_limites_invalidos(campo, valor):
    with pytest.raises(ValidationError):
        ConfiguracionAgente(**{campo: valor})


def test_integracion_manual_cierra_bd_y_limpia_directorio_sin_api(entorno, tmp_path, monkeypatch):
    from eval import check_ep2_agent

    _, _, ruta = entorno
    cache = tmp_path / "cache"
    monkeypatch.setattr(config, "DIR_CACHE", cache)
    monkeypatch.setattr(config, "RUTA_BD", ruta)
    monkeypatch.setattr("sys.argv", ["check_ep2_agent", "--caso", "nota"])
    monkeypatch.setattr("src.ep2.agente.AgenteEP2", lambda servicio: AgenteEP2(
        servicio, llm=modelo(llamar("registrar_nota_ticket", {
            "ticket_id": "INC-2026-0411", "texto": "Seguimiento.",
        })),
    ))
    check_ep2_agent.main()
    informe = json.loads((cache / "ep2_integracion_real.json").read_text(encoding="utf-8"))
    assert informe["intentos"][0]["aprobado"] is True
    assert not list(cache.glob("ep2-integracion-*"))
