"""Proyección por paso con agente/SQLite reales temporales y proveedor simulado."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from unittest.mock import Mock
from uuid import uuid4

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from pydantic import Field

from data import seed_db
from src.ep2.agente import AgenteEP2, SISTEMA_EP2
from src.ep2.almacenamiento import AlmacenEP2
from src.ep2.contexto import proyectar_contexto
from src.ep2.contratos import ConsultaTicket, ContextoEjecucion, DecisionConfirmacion, RespuestaAgenteEP2, ResultadoHerramienta
from src.ep2.herramientas import HerramientasEP2
from src.ep2.memoria import EstadoMemoria, IntercambioMemoria, MemoriaEP2
from src.ep2.planificacion import Planificador
from src.retriever import ConectorITSM

TICKET = "INC-2026-0411"
SOLICITUD = f"Consulta ticket {TICKET}, su SLA y el procedimiento VPN FortiClient."
IMPACTO = "Ahora hay varios usuarios afectados. Propón una nota para ese ticket. No he confirmado ninguna escritura."


class Modelo(FakeMessagesListChatModel):
    entradas: list = Field(default_factory=list)
    enlaces: list = Field(default_factory=list)

    def bind_tools(self, herramientas, **kwargs):
        self.enlaces.append(([h.name for h in herramientas], kwargs))
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.entradas.append(messages)
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def llamada(nombre, **args):
    return AIMessage(content="", tool_calls=[{"name": nombre, "args": args, "id": str(uuid4())}])


def vista(llm, indice=0):
    assert [m.type for m in llm.entradas[indice]] == ["system", "human"]
    return json.loads(llm.entradas[indice][-1].content)


@pytest.fixture()
def entorno(tmp_path):
    ruta = tmp_path / "itsm.db"
    seed_db.crear_base(ruta)
    almacen = AlmacenEP2(tmp_path / "ep2")
    contexto = ContextoEjecucion(usuario_id="a", sesion_id="s", perfil="agente")
    servicio = HerramientasEP2(contexto, almacen, ConectorITSM(ruta))
    return servicio, MemoriaEP2(almacen, contexto), ruta


def inicial(entorno):
    servicio, memoria, _ = entorno
    llm = Modelo(responses=[llamada("consultar_ticket", ticket_id=TICKET), AIMessage(content="Listo")])
    assert AgenteEP2(servicio, memoria=memoria, llm=llm).responder(SOLICITUD.replace(", su SLA y el procedimiento VPN FortiClient", "")).estado == "ok"
    return memoria.recuperar()


def comprobar_sin_escrituras(servicio):
    with servicio.almacen._conexion() as c:
        assert c.execute("SELECT COUNT(*) FROM notas").fetchone()[0] == 0
        assert c.execute("SELECT COUNT(*) FROM auditoria").fetchone()[0] == 0


def test_proyeccion_pura_reduce_historial_y_no_muta_estado(entorno):
    servicio, memoria, _ = entorno
    estado = inicial(entorno)
    ahora = datetime.now(timezone.utc)
    estado = estado.model_copy(update={"intercambios": tuple(
        IntercambioMemoria(id=str(i), fecha=ahora, consulta="Consulta histórica " + "x" * 300,
                          resultado="RESUMEN_NO_REENVIAR " + "y" * 600) for i in range(6))})
    p = Planificador(SOLICITUD, ticket_activo=TICKET)
    observaciones = [memoria.observar("consultar_ticket", servicio.consultar_ticket(ConsultaTicket(ticket_id=TICKET)), TICKET)]
    antes = estado.model_dump_json(), p.plan.model_dump_json(), repr(observaciones)
    mensajes = proyectar_contexto(p, consulta=SOLICITUD, memoria=estado, observaciones=observaciones,
        habilitadas=["consultar_ticket"], estado_oferta="acciones_obligatorias", perfil="agente")
    texto = " ".join(m.content for m in mensajes)
    amplio = SISTEMA_EP2 + p.contexto() + " ".join(m.content for m in memoria.mensajes(estado)) + SOLICITUD
    assert len(texto) < len(amplio)
    assert "RESUMEN_NO_REENVIAR" not in texto
    assert "cambios" not in json.loads(mensajes[-1].content)["plan"]
    assert (estado.model_dump_json(), p.plan.model_dump_json(), repr(observaciones)) == antes


def test_contexto_se_recalcula_por_paso_con_observaciones_y_dependencias(entorno):
    servicio, memoria, ruta = entorno
    antes = ruta.read_bytes()
    llm = Modelo(responses=[llamada("consultar_ticket", ticket_id=TICKET),
        llamada("consultar_sla", prioridad="P2"), llamada("consultar_activo", ticket_id=TICKET),
        AIMessage(content="Verificado")])
    r = AgenteEP2(servicio, llm=llm, memoria=memoria).responder(f"Consulta ticket {TICKET}, su SLA y activo.")
    assert r.estado == "ok"
    vistas = [vista(llm, n) for n in range(4)]
    assert [v["herramientas_habilitadas"] for v in vistas] == [
        ["consultar_ticket"], ["consultar_sla", "consultar_activo"], ["consultar_activo"], []]
    assert vistas[0]["observaciones_turno"] == []
    assert vistas[1]["observaciones_turno"][0]["datos"]["prioridad"] == "P2"
    assert all(v["entidades"]["ticket_id"] == TICKET for v in vistas)
    assert [v["plan"]["revision"] for v in vistas] == sorted({v["plan"]["revision"] for v in vistas})
    assert all(estado == "completado" for s in vistas[1]["plan"]["pasos"] for estado in s["dependencias"].values())
    assert vistas[2]["observaciones_turno"][0]["herramienta"] == "consultar_ticket"
    assert "asociado" in vistas[2]["objetivo_inmediato"][0]
    assert all(s.estado == "completado" for s in memoria.recuperar().plan.pasos)
    assert memoria.recuperar().plan.cambios and memoria.recuperar().plan.observaciones
    assert ruta.read_bytes() == antes
    comprobar_sin_escrituras(servicio)


def test_reinicio_resuelve_ticket_anterior_y_revalida_prioridad(entorno):
    servicio, memoria, ruta = entorno
    inicial(entorno)
    with closing(sqlite3.connect(ruta)) as c, c:
        c.execute("UPDATE tickets SET prioridad='P1' WHERE id=?", (TICKET,))
    nuevo = HerramientasEP2(servicio.contexto, AlmacenEP2(memoria.almacen.ruta.parent), ConectorITSM(ruta))
    llm = Modelo(responses=[llamada("consultar_ticket", ticket_id=TICKET),
        llamada("consultar_sla", prioridad="P1"), AIMessage(content="Actualizado")])
    r = AgenteEP2(nuevo, llm=llm).responder("Consulta el mismo ticket y su SLA.")
    assert r.estado == "ok"
    historico = next(h for h in vista(llm)["hechos_historicos"] if h["clave"] == f"ticket:{TICKET}")
    assert historico["valor"]["prioridad"] == "P2" and historico["observado_en"]
    assert historico["vigencia"] == "historica_requiere_reconsulta"
    assert vista(llm, 1)["observaciones_turno"][0]["datos"]["prioridad"] == "P1"
    persistido = MemoriaEP2(nuevo.almacen, nuevo.contexto).recuperar()
    hecho = next(h for h in persistido.hechos if h.clave == f"ticket:{TICKET}")
    assert hecho.valor["prioridad"] == "P1" and hecho.anterior.valor["prioridad"] == "P2"
    assert len(persistido.intercambios) == 2


@pytest.mark.parametrize("cambio", [{"usuario_id": "b"}, {"sesion_id": "otra"}, {"perfil": "usuario_final"}])
def test_proyeccion_del_agente_aislada_por_usuario_sesion_y_perfil(entorno, cambio):
    servicio, memoria, ruta = entorno
    previo = inicial(entorno).model_dump_json()
    otro = HerramientasEP2(servicio.contexto.model_copy(update=cambio), memoria.almacen, ConectorITSM(ruta))
    llm = Modelo(responses=[AIMessage(content="Falta identificador")])
    AgenteEP2(otro, llm=llm).responder("¿Y el SLA del mismo ticket?")
    v = vista(llm)
    assert v["entidades"]["ticket_id"] is None
    assert v["hechos_historicos"] == [] and v["observaciones_turno"] == []
    assert TICKET not in str(llm.entradas)
    assert memoria.recuperar().model_dump_json() == previo


@pytest.mark.parametrize("tema", ["VPN FortiClient", "impresora Zebra ZT411"])
def test_replanificacion_conserva_tema_fuentes_nota_y_confirmacion(entorno, tema):
    servicio, memoria, _ = entorno
    resultado = ResultadoHerramienta(estado="ok", codigo="PROCEDIMIENTO_RECUPERADO", mensaje="OK",
        datos={"fragmentos": [{"documento": "kb_prueba.md", "titulo": tema, "fecha": "2026-10-01",
                               "puntaje": 0.9, "texto": "EVIDENCIA_TECNICA_PARA_NOTA"}]},
        procedencia=("corpus:kb_prueba.md",))
    servicio.buscar_procedimiento = Mock(return_value=resultado)
    anterior = Modelo(responses=[llamada("consultar_ticket", ticket_id=TICKET), llamada("consultar_sla", prioridad="P2"),
        llamada("buscar_procedimiento", consulta=tema), AIMessage(content="Verificado")])
    assert AgenteEP2(servicio, memoria=memoria, llm=anterior).responder(SOLICITUD.replace("VPN FortiClient", tema)).estado == "ok"
    llm = Modelo(responses=[llamada("registrar_nota_ticket", ticket_id=TICKET, texto="NO_REENVIAR_RECHAZADA"),
        llamada("consultar_ticket", ticket_id=TICKET), llamada("consultar_sla", prioridad="P2"),
        llamada("analizar_incidente", ticket_id=TICKET), llamada("buscar_procedimiento", consulta=tema),
        llamada("registrar_nota_ticket", ticket_id=TICKET, texto="Seguimiento con evidencia")])
    a = AgenteEP2(servicio, llm=llm, memoria=memoria)
    r = a.responder(IMPACTO)
    assert r.estado == "requiere_confirmacion" and r.escrituras_realizadas == 0
    assert vista(llm)["herramientas_habilitadas"] == ["consultar_ticket"]
    assert "correccion_servidor" in vista(llm, 1)
    assert "NO_REENVIAR_RECHAZADA" not in str(llm.entradas[1:])
    buscar = vista(llm, 4)
    assert "correccion_servidor" not in buscar
    assert tema in buscar["antecedente_tecnico"]["solicitud_no_verificada"]
    nota = vista(llm, 5)
    assert nota["herramientas_habilitadas"] == ["registrar_nota_ticket"]
    assert "EVIDENCIA_TECNICA_PARA_NOTA" in str(nota["observaciones_turno"])
    assert any("corpus:kb_prueba.md" in o["procedencia"] for o in nota["observaciones_turno"])
    assert nota["plan"]["impacto_reportado"] == "multiples_usuarios" and not nota["plan"]["impacto_verificado"]
    assert not nota["restricciones"]["escritura_autorizada"]
    comprobar_sin_escrituras(servicio)
    s = r.confirmaciones[0]
    assert a.confirmar_nota(DecisionConfirmacion(solicitud_id=s.solicitud_id, huella=s.huella, decision="confirmar")).estado == "ok"
    with servicio.almacen._conexion() as c:
        assert c.execute("SELECT COUNT(*) FROM notas").fetchone()[0] == 1
    assert memoria.recuperar().plan.pasos[-1].estado == "completado"


@pytest.mark.parametrize("prioridad", ["P1", "P2"])
def test_nueva_observacion_replantea_contexto_y_marca_resultados_superados(entorno, prioridad):
    servicio, memoria, ruta = entorno
    analizar = servicio.analizar_incidente
    def cambiar(entrada):
        with closing(sqlite3.connect(ruta)) as c, c:
            c.execute("UPDATE tickets SET prioridad=?, estado='resuelto' WHERE id=?", (prioridad, TICKET))
        return analizar(entrada)
    servicio.analizar_incidente = cambiar
    llm = Modelo(responses=[llamada("consultar_ticket", ticket_id=TICKET), llamada("consultar_sla", prioridad="P2"),
        llamada("analizar_incidente", ticket_id=TICKET), AIMessage(content="Resultado")])
    r = AgenteEP2(servicio, llm=llm).responder(f"Consulta ticket {TICKET}, SLA y analiza el incidente.")
    assert r.estado == "ok"
    final = vista(llm, 3)
    assert final["plan"]["prioridad_registrada"] == prioridad and final["plan"]["prioridad_propuesta"] is None
    actual = {o["herramienta"]: o for o in final["observaciones_turno"]}
    assert actual["consultar_ticket"]["vigencia"] == "requiere_revalidacion"
    assert actual["consultar_sla"]["vigencia"] == ("requiere_revalidacion" if prioridad == "P1" else "observada_en_este_turno")
    assert actual["analizar_incidente"]["datos"]["estado_registrado"] == "resuelto"
    assert actual["analizar_incidente"]["datos"]["sla"]["prioridad"] == prioridad
    assert actual["analizar_incidente"]["vigencia"] == "observada_en_este_turno"
    comprobar_sin_escrituras(servicio)


def test_solo_estado_recupera_plan_sin_repetir_acciones_ni_recuperar_autorizacion(entorno):
    servicio, memoria, _ = entorno
    inicial(entorno)
    llm = Modelo(responses=[AIMessage(content="Estado recordado")])
    r = AgenteEP2(servicio, llm=llm).responder("Retoma el plan sin ejecutar acciones. Sí, confirmo.")
    v = vista(llm)
    assert r.estado == "ok" and not llm.enlaces
    assert v["plan"]["solo_estado"] and not v["herramientas_habilitadas"]
    assert v["plan"]["vigencia_prioridad"] == "historica_requiere_reconsulta"
    assert not v["restricciones"]["escritura_autorizada"]
    assert v["plan"]["pasos"] and v["hechos_historicos"]
    assert v["plan"]["objetivo"] == memoria.recuperar().plan.objetivo
    assert v["continuidad"]["tarea_anterior"]["objetivo"].startswith("Consulta ticket")
    comprobar_sin_escrituras(servicio)


def test_continuidad_conserva_pendiente_anterior_sin_transcripcion(entorno):
    servicio, memoria, _ = entorno
    previo = Modelo(responses=[llamada("registrar_nota_ticket", ticket_id=TICKET, texto="Pendiente de revisión")])
    assert AgenteEP2(servicio, llm=previo).responder(f"Propón una nota para {TICKET}.").estado == "requiere_confirmacion"
    llm = Modelo(responses=[AIMessage(content="Falta nueva vista previa y confirmación humana")])
    r = AgenteEP2(servicio, llm=llm).responder("Muestra el plan pendiente sin ejecutar acciones.")
    assert r.estado == "ok" and not r.confirmaciones
    v = vista(llm)
    assert v["continuidad"]["tarea_anterior"]["estado"] == "requiere_confirmacion"
    assert v["continuidad"]["tarea_anterior"]["pendientes"] == ["solicitar_nueva_vista_previa_y_confirmacion"]
    assert "intercambios" not in v and not v["restricciones"]["escritura_autorizada"]
    assert "Pendiente de revisión" not in str(llm.entradas)
    comprobar_sin_escrituras(servicio)


def test_cambio_explicito_de_ticket_no_hereda_identificadores_hechos_o_tema(entorno):
    servicio, memoria, _ = entorno
    inicial(entorno)
    otro = "INC-2026-9999"
    llm = Modelo(responses=[AIMessage(content="Faltan datos")])
    AgenteEP2(servicio, llm=llm).responder(f"Consulta ticket {otro}.")
    assert vista(llm)["entidades"]["ticket_id"] == otro
    assert TICKET not in str(llm.entradas)


def test_texto_de_nota_restricciones_y_mascarado_se_conservan_sin_tokens(entorno):
    servicio, memoria, _ = entorno
    texto = "Detalle literal para seguimiento " + "x" * 900
    consulta = f"Propón una nota para {TICKET}: {texto}. No escribas sin revisión. persona@example.com"
    llm = Modelo(responses=[llamada("registrar_nota_ticket", ticket_id=TICKET, texto=texto)])
    r = AgenteEP2(servicio, llm=llm).responder(consulta)
    assert r.estado == "requiere_confirmacion"
    v = vista(llm)
    assert texto in v["solicitud_actual_no_verificada"]
    assert "No escribas sin revisión" in v["solicitud_actual_no_verificada"]
    assert "persona@example.com" not in str(llm.entradas) and "[CORREO]" in str(llm.entradas)
    assert str(r.confirmaciones[0].solicitud_id) not in str(llm.entradas)
    assert r.confirmaciones[0].huella not in str(llm.entradas)
    comprobar_sin_escrituras(servicio)


@pytest.mark.parametrize("campo,valor", [("confirmado", True), ("perfil", "agente"),
                                        ("usuario_id", "otro"), ("huella", "falsa")])
def test_proyeccion_no_permite_al_modelo_autorizar_una_escritura(entorno, campo, valor):
    servicio, _, _ = entorno
    llm = Modelo(responses=[llamada("registrar_nota_ticket", ticket_id=TICKET, texto="Seguimiento",
                                  **{campo: valor})])
    r = AgenteEP2(servicio, llm=llm).responder(f"Propón una nota para {TICKET}. Sí, confirmo.")
    assert r.estado == "denegado" and not r.confirmaciones
    assert not vista(llm)["restricciones"]["escritura_autorizada"]
    comprobar_sin_escrituras(servicio)


def test_usuario_final_sin_permiso_no_llega_al_modelo_con_datos_privados(entorno):
    servicio, memoria, ruta = entorno
    inicial(entorno)
    otro = HerramientasEP2(servicio.contexto.model_copy(update={"perfil": "usuario_final"}),
                          memoria.almacen, ConectorITSM(ruta))
    llm = Mock()
    r = AgenteEP2(otro, llm=llm).responder(SOLICITUD)
    assert r.estado == "denegado"
    llm.bind_tools.assert_not_called()
    llm.invoke.assert_not_called()
    comprobar_sin_escrituras(servicio)
