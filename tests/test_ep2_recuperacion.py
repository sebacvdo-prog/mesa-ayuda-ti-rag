"""Código KB exacto y diagnóstico RAG de la CLI, con FAISS real y sin APIs."""

from __future__ import annotations

import json
import sys
from unittest.mock import Mock

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from src import config
from src.ep2.agente import AgenteEP2
from src.ep2.almacenamiento import AlmacenEP2
from src.ep2.contratos import ConsultaProcedimiento, ContextoEjecucion
from src.ep2.herramientas import HerramientasEP2
from src.retriever import RecuperadorVectorial
from tests.utilidades import construir_fragmento_de_prueba, crear_faiss_de_prueba


@pytest.fixture()
def caso(tmp_path):
    from data import seed_db
    from src.retriever import ConectorITSM
    kb = construir_fragmento_de_prueba(documento="kb_conectividad_vpn.md",
        titulo="KB-RED-02 · Conectividad y VPN", texto="Evidencia documental VPN.").documento
    otro = construir_fragmento_de_prueba(documento="politica_seguridad_ti.md",
        titulo="Política", texto="Otro documento sin el identificador solicitado.").documento
    indice = crear_faiss_de_prueba([(otro, [1.0, 0.0]), (kb, [0.33, (1 - 0.33**2)**0.5])])
    recuperador = RecuperadorVectorial(almacen=indice, umbral=0.471764)
    almacen = AlmacenEP2(tmp_path / "ep2")
    itsm = tmp_path / "itsm.db"
    seed_db.crear_base(itsm)
    servicio = HerramientasEP2(ContextoEjecucion(usuario_id="prueba", sesion_id="rag", perfil="agente"), almacen, ConectorITSM(itsm))
    return servicio, recuperador, indice


def test_codigo_kb_se_resuelve_por_titulo_sin_inventar_score(caso):
    servicio, recuperador, _ = caso
    resultado = servicio.buscar_procedimiento(ConsultaProcedimiento(consulta="KB-RED-02"), recuperador)
    assert resultado.codigo == "PROCEDIMIENTO_RECUPERADO"
    assert resultado.procedencia == ("corpus:kb_conectividad_vpn.md",)
    assert resultado.datos["fragmentos"][0]["puntaje"] is None
    assert resultado.datos["fragmentos"][0]["coincidencia"] == "identificador"
    assert recuperador.umbral == 0.471764


@pytest.mark.parametrize("fuente", ["automatica", "interna", "mixta"])
def test_codigo_no_llama_embeddings_y_no_depende_de_su_vecino_semantico(caso, fuente):
    servicio, recuperador, indice = caso
    indice.embedding_function.embed_query = Mock(side_effect=AssertionError("Un código se resuelve por metadatos"))
    resultado = servicio.buscar_procedimiento(ConsultaProcedimiento(
        consulta="Busca el procedimiento KB-RED-02 para VPN", fuente=fuente), recuperador)
    assert resultado.codigo == "PROCEDIMIENTO_RECUPERADO"
    indice.embedding_function.embed_query.assert_not_called()


def test_codigo_con_fuente_incompatible_no_recupera_otro_documento(caso):
    servicio, recuperador, _ = caso
    resultado = servicio.buscar_procedimiento(ConsultaProcedimiento(consulta="KB-RED-02", fuente="externa"), recuperador)
    assert resultado.codigo == "SIN_PROCEDIMIENTO" and not resultado.procedencia


def test_codigo_inexistente_no_hace_fallback_a_otro_documento(caso):
    servicio, recuperador, _ = caso
    resultado = servicio.buscar_procedimiento(ConsultaProcedimiento(consulta="KB-RED-99"), recuperador)
    assert resultado.codigo == "SIN_PROCEDIMIENTO" and not resultado.procedencia


def test_codigo_privado_conserva_permisos(caso):
    servicio, recuperador, indice = caso
    for identificador in indice.index_to_docstore_id.values():
        documento = indice.docstore.search(identificador)
        if documento.metadata["documento"] == "kb_conectividad_vpn.md":
            documento.metadata["nivel_acceso"] = "restringido_agentes"
    usuario = HerramientasEP2(servicio.contexto.model_copy(update={"perfil": "usuario_final"}), servicio.almacen)
    assert usuario.buscar_procedimiento(ConsultaProcedimiento(consulta="KB-RED-02"), recuperador).codigo == "SIN_PROCEDIMIENTO"


def test_ep1_conserva_busqueda_semantica_y_umbral(caso):
    _, recuperador, _ = caso
    resultado = recuperador.buscar("KB-RED-02")
    assert [f.nombre_documento for f in resultado] == ["politica_seguridad_ti.md"]


def test_diagnostico_muestra_etapas_y_omite_textos_sensibles(caso):
    servicio, recuperador, _ = caso
    trazas = []
    recuperador.diagnosticar = trazas.append
    consulta = "VPN persona@empresa.cl token=secreto"
    servicio.buscar_procedimiento(ConsultaProcedimiento(consulta=consulta, fuente="mixta"), recuperador)
    serializado = json.dumps(trazas)
    assert all(t not in serializado for t in (consulta, "persona@empresa.cl", "token=secreto", "Evidencia documental VPN", "Otro documento"))
    assert len(trazas) == 1
    diagnostico = trazas[0]
    assert diagnostico["argumentos"]["consulta"] == "TEXTO_OMITIDO"
    assert diagnostico["argumentos"]["fuente"] == "mixta"
    assert diagnostico["candidatos_antes_filtros"]
    assert diagnostico["conteos"]["umbral"] == 1


def test_diagnostico_registra_argumento_codigo_y_filtro_efectivo(caso):
    servicio, recuperador, _ = caso
    trazas = []
    recuperador.diagnosticar = trazas.append
    servicio.buscar_procedimiento(ConsultaProcedimiento(consulta="KB-RED-02", fuente="externa"), recuperador)
    assert trazas[0]["argumentos"]["consulta"] == "KB-RED-02"
    assert trazas[0]["filtro_fuente"] == {"fuente": "externa"}
    assert trazas[0]["motivo"] == "FILTRO_FUENTE"


@pytest.mark.parametrize("diagnostico", [False, True])
def test_cli_real_recibe_codigo_solo_y_completa_plan_sin_groq(caso, monkeypatch, capsys, diagnostico):
    from src.ep2 import cli

    class Modelo(FakeMessagesListChatModel):
        def bind_tools(self, herramientas, **kwargs):
            return self

    def llamada(nombre, **args):
        return AIMessage(content="", tool_calls=[{"name": nombre, "args": args, "id": nombre}])

    servicio, recuperador, _ = caso
    llm = Modelo(responses=[llamada("consultar_ticket", ticket_id="INC-2026-0411"),
        llamada("consultar_sla", prioridad="P2"), llamada("buscar_procedimiento", consulta="KB-RED-02"),
        AIMessage(content="Se recuperó KB-RED-02 con evidencia documental.")])
    agente = AgenteEP2(servicio, llm=llm, recuperador=recuperador)
    monkeypatch.setattr(cli, "AlmacenEP2", lambda: servicio.almacen)
    monkeypatch.setattr(cli, "HerramientasEP2", lambda *args: servicio)
    monkeypatch.setattr(cli, "AgenteEP2", lambda *args: agente)
    consultas = iter(["Consulta el ticket INC-2026-0411, revisa su SLA y busca el procedimiento KB-RED-02 para diagnosticar la falla de VPN. No modifiques el ticket.", "/salir"])
    monkeypatch.setattr("builtins.input", lambda *args: next(consultas))
    monkeypatch.setattr(sys, "argv", ["ep2", "--usuario", "prueba", "--sesion", "rag"] + (["--diagnostico-rag"] if diagnostico else []))
    cli.main()
    salida = capsys.readouterr().out
    assert "PROCEDIMIENTO_RECUPERADO" in salida and "SIN_PROCEDIMIENTO" not in salida
    assert ("Diagnóstico RAG:" in salida) == diagnostico
    if diagnostico:
        traza = json.loads(next(l.split("Diagnóstico RAG:", 1)[1] for l in salida.splitlines() if l.startswith("Diagnóstico RAG:")))
        assert traza["argumentos"]["consulta"] == "KB-RED-02"
        assert traza["argumentos"]["fuente"] == "automatica"
        assert traza["metodo"] == "identificador" and traza["motivo"] == "RECUPERADO"
    estado = agente.memoria.recuperar()
    assert all(p.estado == "completado" for p in estado.plan.pasos)
    assert "consulta_sha256" not in estado.model_dump_json()
    assert all(d["tool_choice"] == "auto" for d in agente.decisiones[:-1])
    assert len(agente.herramientas) == 6
    with servicio.almacen._conexion() as c:
        assert c.execute("SELECT COUNT(*) FROM notas").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM auditoria").fetchone()[0] == 0


def test_diagnostico_no_expone_nombre_de_documento_no_autorizado(caso):
    servicio, recuperador, indice = caso
    for identificador in indice.index_to_docstore_id.values():
        indice.docstore.search(identificador).metadata["nivel_acceso"] = "restringido_agentes"
    trazas = []
    recuperador.diagnosticar = trazas.append
    recuperador.buscar("VPN", perfil="usuario_final")
    salida = json.dumps(trazas)
    assert "kb_conectividad_vpn.md" not in salida and "politica_seguridad_ti.md" not in salida
    assert all(c["documento"] == "OMITIDO" for c in trazas[0]["candidatos_antes_filtros"])
    assert trazas[0]["motivo"] == "FILTRO_PERMISOS"


def test_codigo_ambiguo_no_elige_documento_arbitrario(caso):
    servicio, recuperador, indice = caso
    for identificador in indice.index_to_docstore_id.values():
        indice.docstore.search(identificador).metadata["titulo"] = "KB-RED-02 · Título duplicado"
    assert servicio.buscar_procedimiento(ConsultaProcedimiento(consulta="KB-RED-02"), recuperador).codigo == "SIN_PROCEDIMIENTO"


def test_diagnostico_offline_usa_mismo_servicio_y_omite_contenido(caso, monkeypatch, capsys):
    from eval import check_ep2_retrieval

    _, _, indice = caso
    monkeypatch.setattr(config, "PROVEEDOR_EMBEDDINGS", "huggingface")
    monkeypatch.setattr(RecuperadorVectorial, "cargar_indice", staticmethod(lambda *args: indice))
    assert check_ep2_retrieval.main(["--consulta", "KB-RED-02"]) == 0
    salida = json.loads(capsys.readouterr().out)
    assert salida["resultado"] == "PROCEDIMIENTO_RECUPERADO" and salida["intentos_red"] == 0
    assert [d["metodo"] for d in salida["diagnosticos"]] == ["semantica", "identificador"]
    assert "Evidencia documental VPN" not in json.dumps(salida)


def test_diagnostico_no_altera_resultados_ni_duplica_embeddings(caso):
    _, recuperador, indice = caso
    anterior = recuperador.buscar("VPN", clasificacion="mixta")
    indice.embedding_function.embed_query = Mock(wraps=indice.embedding_function.embed_query)
    recuperador.diagnosticar = Mock(side_effect=RuntimeError("detalle interno que no debe propagarse"))
    actual = recuperador.buscar("VPN", clasificacion="mixta")
    assert [(f.nombre_documento, f.puntaje) for f in anterior] == [(f.nombre_documento, f.puntaje) for f in actual]
    indice.embedding_function.embed_query.assert_called_once_with("VPN")
