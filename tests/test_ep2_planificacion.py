"""Planes, transiciones y ciclo único LangChain con SQLite temporal, sin API."""

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
from pydantic import Field, ValidationError

from data import seed_db
from src.ep2.agente import AgenteEP2
from src.ep2.almacenamiento import AlmacenEP2
from src.ep2.configuracion import ConfiguracionAgente
from src.ep2.contratos import ConsultaSLA, ConsultaTicket, ContextoEjecucion, DecisionConfirmacion, PasoPlan, PlanEjecucion, RespuestaAgenteEP2, ResultadoHerramienta
from src.ep2.herramientas import HerramientasEP2
from src.ep2.memoria import MemoriaEP2
from src.ep2.planificacion import Planificador, multiples_usuarios
from src.retriever import ConectorITSM, RecuperadorVectorial

TICKET = "INC-2026-0411"
SOLICITUD = f"Consulta ticket {TICKET}, su SLA y recupera el procedimiento VPN FortiClient."


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


def modelo(*salidas):
    return Modelo(responses=list(salidas))


@pytest.fixture()
def entorno(tmp_path):
    ruta = tmp_path / "itsm.db"
    seed_db.crear_base(ruta)
    almacen = AlmacenEP2(tmp_path / "ep2")
    ctx = ContextoEjecucion(usuario_id="a", sesion_id="s", perfil="agente")
    servicio = HerramientasEP2(ctx, almacen, ConectorITSM(ruta))
    return servicio, MemoriaEP2(almacen, ctx), ruta


def ejecutar(p, nombre, resultado, **args):
    assert p.preparar(nombre, args) is None
    p.observar(nombre, resultado)


def ticket_sla(p, servicio):
    ejecutar(p, "consultar_ticket", servicio.consultar_ticket(ConsultaTicket(ticket_id=TICKET)), ticket_id=TICKET)
    ejecutar(p, "consultar_sla", servicio.consultar_sla(ConsultaSLA(prioridad="P2")), prioridad="P2")


def procedimiento():
    return ResultadoHerramienta(estado="ok", codigo="PROCEDIMIENTO_RECUPERADO", mensaje="OK",
                                procedencia=("corpus:kb_conectividad_vpn.md",), datos={"fragmentos": []})


def test_plan_identidad_objetivo_prioridades_dependencias_y_estado_inicial():
    p = Planificador(SOLICITUD).plan
    assert p.id and p.objetivo == SOLICITUD
    assert [s.herramienta for s in p.pasos] == ["consultar_ticket", "consultar_sla", "buscar_procedimiento"]
    assert p.pasos[1].dependencias == (p.pasos[0].id,)
    assert set(p.pasos[2].dependencias) == {p.pasos[0].id, p.pasos[1].id}
    assert all(s.estado == "pendiente" for s in p.pasos)


@pytest.mark.parametrize("mutacion", ["duplicados", "dependencia_ausente", "ciclo", "completado_sin_verificar", "prioridad", "herramienta"])
def test_validacion_rechaza_planes_invalidos(mutacion):
    datos = Planificador(SOLICITUD).plan.model_dump()
    pasos = datos["pasos"]
    if mutacion == "duplicados":
        pasos[1]["id"] = pasos[0]["id"]
    elif mutacion == "dependencia_ausente":
        pasos[1]["dependencias"] = ("p99",)
    elif mutacion == "ciclo":
        pasos[0]["dependencias"] = (pasos[1]["id"],)
    elif mutacion == "completado_sin_verificar":
        pasos[1]["estado"] = "completado"
    elif mutacion == "prioridad":
        pasos[0]["prioridad"] = 0
    else:
        pasos[0]["herramienta"] = "confirmar_nota"
    with pytest.raises(ValidationError):
        PlanEjecucion.model_validate(datos)


def test_dependencias_impiden_ejecutar_sla_antes_de_ticket():
    p = Planificador(SOLICITUD)
    assert p.preparar("consultar_sla", {"prioridad": "P2"}).codigo == "PLAN_DEPENDENCIA_PENDIENTE"
    assert all(s.estado == "pendiente" for s in p.plan.pasos)


def test_transiciones_solo_completan_despues_de_resultado_real(entorno):
    servicio, _, _ = entorno
    p = Planificador(SOLICITUD)
    assert p.preparar("consultar_ticket", {"ticket_id": TICKET}) is None
    assert p.plan.pasos[0].estado == "en_ejecucion"
    p.observar("consultar_ticket", servicio.consultar_ticket(ConsultaTicket(ticket_id=TICKET)))
    assert p.plan.pasos[0].estado == "completado"
    assert p.plan.observaciones[-1].procedencia == (f"itsm:ticket:{TICKET}",)
    assert p.plan.prioridad_registrada == "P2"


def test_no_repite_un_paso_ya_ejecutado_en_el_mismo_turno(entorno):
    servicio, _, _ = entorno
    p = Planificador(SOLICITUD)
    ejecutar(p, "consultar_ticket", servicio.consultar_ticket(ConsultaTicket(ticket_id=TICKET)), ticket_id=TICKET)
    assert p.preparar("consultar_ticket", {"ticket_id": TICKET}).codigo == "PLAN_PASO_YA_EJECUTADO"


def test_prioridad_impide_tarea_menos_urgente_aunque_este_disponible():
    p = Planificador("Consulta SLA P2 y el activo del caso.")
    pasos = list(p.plan.pasos)
    pasos[0] = pasos[0].model_copy(update={"prioridad": 1})
    p._actualizar(pasos=tuple(pasos))
    assert [s.herramienta for s in p.disponibles()] == ["consultar_sla"]
    assert p.preparar("consultar_activo", {"ticket_id": TICKET}).codigo == "PLAN_PRIORIDAD_PENDIENTE"


def test_prioridad_sla_debe_ser_la_registrada_no_inventada(entorno):
    servicio, _, _ = entorno
    p = Planificador(SOLICITUD)
    ejecutar(p, "consultar_ticket", servicio.consultar_ticket(ConsultaTicket(ticket_id=TICKET)), ticket_id=TICKET)
    assert p.preparar("consultar_sla", {"prioridad": "P1"}).codigo == "PLAN_PRIORIDAD_NO_COINCIDE"


@pytest.mark.parametrize(("texto", "esperado"), [("Ahora hay varios usuarios afectados", True),
    ("Hay 8 usuarios afectados", True), ("Hay 1 usuarios afectados", False),
    ("No hay varios usuarios afectados", False), ("El usuario sigue afectado", False)])
def test_interpreta_reporte_de_impacto_sin_inferir_confirmacion(texto, esperado):
    assert multiples_usuarios(texto) == esperado


def test_replanifica_impacto_reabre_verificaciones_y_distingue_prioridades(entorno):
    servicio, _, _ = entorno
    p = Planificador(SOLICITUD)
    ticket_sla(p, servicio)
    ejecutar(p, "buscar_procedimiento", procedimiento())
    previo = p.plan.model_copy(deep=True)
    q = Planificador("Ahora hay varios usuarios afectados. Propón una nota de seguimiento.", anterior=previo, ticket_activo=TICKET)
    assert q.plan.id == previo.id
    assert q.plan.revision > previo.revision
    assert q.plan.impacto_reportado == "multiples_usuarios"
    assert "Reevaluar impacto reportado" in q.plan.objetivo
    assert "confirmación humana" in q.plan.objetivo
    assert q.plan.impacto_verificado is False
    assert q.plan.prioridad_registrada == "P2"
    assert q.plan.prioridad_propuesta is None
    assert [s.herramienta for s in q.disponibles()] == ["consultar_ticket"]
    assert q.plan.observaciones[-1].origen == "usuario"
    ticket_sla(q, servicio)
    assert q.plan.prioridad_propuesta == "P2"
    assert q.plan.prioridad_propuesta != "P1"
    assert "sujeta" in q.plan.criterio_prioridad
    assert q.preparar("registrar_nota_ticket", {"ticket_id": TICKET}).codigo == "PLAN_DEPENDENCIA_PENDIENTE"


def test_procedimiento_ausente_bloquea_nota_y_propone_triage(entorno):
    servicio, _, _ = entorno
    p = Planificador(SOLICITUD + " Propón una nota.")
    ticket_sla(p, servicio)
    ejecutar(p, "buscar_procedimiento", ResultadoHerramienta(estado="no_encontrado", codigo="SIN_PROCEDIMIENTO", mensaje="Sin contexto"))
    assert next(s for s in p.plan.pasos if s.herramienta == "registrar_nota_ticket").estado == "bloqueado"
    assert "analizar_incidente" in [s.herramienta for s in p.disponibles()]
    assert any(c.codigo == "ESCALAMIENTO_PROPUESTO" for c in p.plan.cambios)


@pytest.mark.parametrize(("estado", "codigo"), [("error", "ERROR_HERRAMIENTA"), ("no_encontrado", "TICKET_NO_ENCONTRADO"), ("denegado", "PERMISO_REQUERIDO")])
def test_error_datos_faltantes_y_permisos_bloquean_descendientes(estado, codigo):
    p = Planificador(SOLICITUD)
    ejecutar(p, "consultar_ticket", ResultadoHerramienta(estado=estado, codigo=codigo, mensaje="No disponible"), ticket_id=TICKET)
    assert all(s.estado == "bloqueado" for s in p.plan.pasos)
    assert not p.disponibles()


def test_reanudar_reintenta_error_sin_bucle_y_maximo_dos_intentos():
    p = Planificador(f"Consulta ticket {TICKET}.")
    ejecutar(p, "consultar_ticket", ResultadoHerramienta(estado="error", codigo="ERROR_HERRAMIENTA", mensaje="Error"), ticket_id=TICKET)
    q = Planificador("Retoma el caso pendiente.", anterior=p.plan, ticket_activo=TICKET)
    assert q.disponibles()
    ejecutar(q, "consultar_ticket", ResultadoHerramienta(estado="error", codigo="ERROR_HERRAMIENTA", mensaje="Error"), ticket_id=TICKET)
    r = Planificador("Retoma el caso pendiente.", anterior=q.plan, ticket_activo=TICKET)
    assert not r.disponibles()


def test_limites_bloquean_pendientes_y_se_recuperan_sin_ejecutar():
    p = Planificador(SOLICITUD)
    p.finalizar("limite")
    assert all(s.estado == "bloqueado" for s in p.plan.pasos)
    q = Planificador("Continua el plan pendiente.", anterior=p.plan, ticket_activo=TICKET)
    assert q.plan.id == p.plan.id
    assert q.disponibles()[0].herramienta == "consultar_ticket"


def test_tiempo_agotado_previo_a_herramienta_se_atribuye_al_sistema(entorno):
    servicio, _, _ = entorno
    a = AgenteEP2(servicio)
    a._planificador = Planificador(SOLICITUD)
    ejecutar_real = Mock()
    resultado = json.loads(a._ejecutar("consultar_ticket", ejecutar_real, TICKET))
    assert resultado["codigo"] == "TIEMPO_AGOTADO"
    ejecutar_real.assert_not_called()
    assert a._planificador.plan.observaciones[-1].origen == "sistema"
    assert a._planificador.plan.pasos[0].estado == "pendiente"


def test_persistencia_del_plan_y_aislamiento_por_sesion(entorno):
    servicio, memoria, _ = entorno
    p = Planificador(SOLICITUD)
    ticket_sla(p, servicio)
    memoria.registrar_turno(SOLICITUD, RespuestaAgenteEP2(estado="ok", texto="OK", plan_final=p.plan), [])
    nueva = MemoriaEP2(AlmacenEP2(memoria.almacen.ruta.parent), servicio.contexto)
    assert nueva.recuperar().plan == p.plan
    otra = MemoriaEP2(memoria.almacen, servicio.contexto.model_copy(update={"sesion_id": "otra"}))
    assert otra.recuperar().plan is None


def test_recuperar_plan_pendiente_sin_hechos_de_herramientas(entorno):
    servicio, memoria, _ = entorno
    p = Planificador(SOLICITUD)
    p.finalizar("error")  # El proveedor falló antes de obtener hechos.
    memoria.registrar_turno(SOLICITUD, RespuestaAgenteEP2(estado="error", texto="Interrupción", plan_final=p.plan), [])
    restaurado = MemoriaEP2(memoria.almacen, servicio.contexto).recuperar()
    assert restaurado.ticket_activo is None and not restaurado.hechos
    q = Planificador("Retoma el plan pendiente.", anterior=restaurado.plan, ticket_activo=restaurado.ticket_activo)
    assert q.plan.id == p.plan.id and q.plan.ticket_id == TICKET
    assert q.disponibles()[0].herramienta == "consultar_ticket"


def test_reanudar_nota_tras_error_del_proveedor_exige_nueva_propuesta_sin_escribir(entorno):
    servicio, memoria, _ = entorno
    p = Planificador(SOLICITUD + " Propón una nota.")
    ticket_sla(p, servicio)
    ejecutar(p, "buscar_procedimiento", procedimiento())
    p.finalizar("error")
    memoria.registrar_turno(SOLICITUD, RespuestaAgenteEP2(estado="error", texto="Proveedor interrumpido", plan_final=p.plan), [])
    a = AgenteEP2(servicio, memoria=memoria, llm=modelo(llamada("registrar_nota_ticket", ticket_id=TICKET, texto="Seguimiento pendiente de revisión humana")))
    r = a.responder("Retoma el plan y propón una nota de seguimiento.")
    assert r.estado == "requiere_confirmacion" and len(r.confirmaciones) == 1
    assert r.plan_final.id == p.plan.id
    assert r.plan_final.pasos[-1].codigo == "CONFIRMACION_REQUERIDA"
    with memoria.almacen._conexion() as c:
        assert c.execute("SELECT COUNT(*) FROM notas").fetchone()[0] == 0


def test_nueva_solicitud_de_nota_invalida_vista_previa_aunque_falle_el_modelo(entorno):
    servicio, memoria, _ = entorno
    a = AgenteEP2(servicio, memoria=memoria, llm=modelo(llamada("registrar_nota_ticket", ticket_id=TICKET, texto="Vista anterior")))
    anterior = a.responder("Propón una nota.").confirmaciones[0]
    a._llm = Mock()
    a._llm.bind_tools.side_effect = RuntimeError("Proveedor interrumpido")
    assert a.responder("Retoma el plan y propón una nota nueva.").estado == "error"
    r = a.confirmar_nota(DecisionConfirmacion(solicitud_id=anterior.solicitud_id, huella=anterior.huella, decision="confirmar"))
    assert r.estado == "denegado"
    with memoria.almacen._conexion() as c:
        assert c.execute("SELECT COUNT(*) FROM notas").fetchone()[0] == 0


def test_rechaza_sobrescribir_plan_con_revision_antigua(entorno):
    servicio, memoria, _ = entorno
    p = Planificador(SOLICITUD)
    viejo = p.plan
    ticket_sla(p, servicio)
    memoria.registrar_turno(SOLICITUD, RespuestaAgenteEP2(estado="ok", texto="OK", plan_final=p.plan), [])
    with pytest.raises(ValueError, match="actualizó"):
        memoria.registrar_turno("Otra respuesta", RespuestaAgenteEP2(estado="ok", texto="OK", plan_final=viejo), [])
    assert memoria.recuperar().plan == p.plan


def test_llm_no_completa_plan_con_afirmaciones_sin_ejecutar(entorno):
    servicio, _, _ = entorno
    llm = modelo(AIMessage(content="Completé ticket y SLA sin herramientas."))
    r = AgenteEP2(servicio, llm=llm, opciones=ConfiguracionAgente(max_iteraciones=2)).responder(SOLICITUD)
    assert r.estado == "limite"
    assert all(s.estado != "completado" for s in r.plan_final.pasos)


def test_ciclo_unico_corrige_nota_prematura_y_solo_propone_al_final(entorno):
    servicio, memoria, _ = entorno
    llm = modelo(llamada("registrar_nota_ticket", ticket_id=TICKET, texto="Seguimiento"),
        llamada("consultar_ticket", ticket_id=TICKET), llamada("consultar_sla", prioridad="P2"),
        llamada("registrar_nota_ticket", ticket_id=TICKET, texto="Seguimiento"))
    contar = Mock(wraps=servicio.preparar_nota)
    servicio.preparar_nota = contar
    r = AgenteEP2(servicio, llm=llm).responder(f"Consulta ticket {TICKET}, su SLA y propón una nota.")
    assert r.estado == "requiere_confirmacion"
    assert contar.call_count == 1
    assert len(llm.entradas) == 4
    assert any("AHORA según el plan: consultar_ticket." in str(m.content) for m in llm.entradas[1])
    assert [t.nombre for t in r.herramientas] == ["consultar_ticket", "consultar_sla", "registrar_nota_ticket"]
    assert r.plan_final.pasos[-1].estado == "bloqueado"
    with memoria.almacen._conexion() as c:
        assert c.execute("SELECT COUNT(*) FROM notas").fetchone()[0] == 0


def test_reinicio_no_recupera_autorizacion_y_confirmacion_nueva_es_humana(entorno):
    servicio, memoria, ruta = entorno
    llm = modelo(llamada("registrar_nota_ticket", ticket_id=TICKET, texto="No persistir cuerpo"))
    a = AgenteEP2(servicio, llm=llm)
    r = a.responder("Propón una nota: No persistir cuerpo.")
    s = r.confirmaciones[0]
    restaurado = memoria.recuperar()
    contenido = restaurado.model_dump_json()
    assert str(s.solicitud_id) not in contenido and s.huella not in contenido
    assert "No persistir cuerpo" not in contenido
    nuevo_servicio = HerramientasEP2(servicio.contexto, memoria.almacen, ConectorITSM(ruta))
    nuevo = AgenteEP2(nuevo_servicio, llm=modelo(llamada("registrar_nota_ticket", ticket_id=TICKET, texto="Nueva vista")))
    assert nuevo.confirmar_nota(DecisionConfirmacion(solicitud_id=s.solicitud_id, huella=s.huella, decision="confirmar")).estado == "denegado"
    nueva = nuevo.responder("Retoma el plan y propón una nota nueva.")
    assert nueva.plan_final.id == r.plan_final.id
    assert nueva.confirmaciones[0].solicitud_id != s.solicitud_id
    with memoria.almacen._conexion() as c:
        assert c.execute("SELECT COUNT(*) FROM notas").fetchone()[0] == 0
    n = nueva.confirmaciones[0]
    recibo = nuevo.confirmar_nota(DecisionConfirmacion(solicitud_id=n.solicitud_id, huella=n.huella, decision="confirmar"))
    assert recibo.estado == "ok"
    assert memoria.recuperar().plan.pasos[-1].estado == "completado"


def test_trazabilidad_emite_plan_antes_de_herramientas_y_fuentes_verificables(entorno):
    servicio, _, _ = entorno
    eventos = []
    llm = modelo(llamada("consultar_ticket", ticket_id=TICKET), AIMessage(content="Hecho"))
    r = AgenteEP2(servicio, llm=llm, trazador=lambda tipo, dato: eventos.append((tipo, dato))).responder(f"Consulta ticket {TICKET}.")
    assert eventos[0][0] == "plan_inicial" and eventos[0][1].pasos[0].estado == "pendiente"
    assert eventos[-1][0] == "plan_final"
    assert any(t == "observacion" and d.procedencia == (f"itsm:ticket:{TICKET}",) for t,d in eventos)
    assert r.plan_final.pasos[0].estado == "completado"


def test_cambio_de_ticket_crea_plan_distinto_y_no_reutiliza_verificaciones(entorno):
    servicio, _, _ = entorno
    p = Planificador(SOLICITUD)
    ticket_sla(p, servicio)
    q = Planificador("Consulta ticket INC-2026-0401 y su SLA.", anterior=p.plan, ticket_activo=TICKET)
    assert q.plan.id != p.plan.id
    assert all(s.estado == "pendiente" for s in q.plan.pasos)


def test_recuperar_lectura_en_ejecucion_la_deja_pendiente_sin_acciones():
    p = Planificador(f"Consulta ticket {TICKET}.")
    assert p.preparar("consultar_ticket", {"ticket_id": TICKET}) is None
    q = Planificador("Retoma el caso pendiente.", anterior=p.plan, ticket_activo=TICKET)
    assert q.plan.pasos[0].estado == "pendiente"
    assert not q.ejecutadas


def test_nota_no_solicitada_no_invoca_servicio(entorno):
    servicio, memoria, _ = entorno
    servicio.preparar_nota = Mock(wraps=servicio.preparar_nota)
    llm = modelo(llamada("registrar_nota_ticket", ticket_id=TICKET, texto="No pedida"))
    r = AgenteEP2(servicio, llm=llm).responder(f"Consulta ticket {TICKET}.")
    assert r.herramientas[0].codigo == "PLAN_NOTA_NO_SOLICITADA"
    servicio.preparar_nota.assert_not_called()
    with memoria.almacen._conexion() as c:
        assert c.execute("SELECT COUNT(*) FROM notas").fetchone()[0] == 0


def test_ticket_distinto_se_rechaza_sin_consultar_datos(entorno):
    servicio, _, _ = entorno
    servicio.consultar_ticket = Mock(wraps=servicio.consultar_ticket)
    llm = modelo(llamada("consultar_ticket", ticket_id="INC-2026-0401"), AIMessage(content="Sin resultados"))
    r = AgenteEP2(servicio, llm=llm).responder(f"Consulta ticket {TICKET}.")
    assert r.herramientas[0].codigo == "PLAN_TICKET_DISTINTO"
    servicio.consultar_ticket.assert_not_called()


def test_posponer_en_cli_conserva_pendiente_sin_confirmar(entorno):
    from src.ep2.cli import resolver_confirmaciones
    servicio, memoria, _ = entorno
    a = AgenteEP2(servicio, llm=modelo(llamada("registrar_nota_ticket", ticket_id=TICKET, texto="Seguimiento")))
    r = a.responder("Propón una nota de seguimiento.")
    a.confirmar_nota = Mock(wraps=a.confirmar_nota)
    resolver_confirmaciones(a, r, leer=lambda _: "POSPONER")
    a.confirmar_nota.assert_not_called()
    assert memoria.recuperar().plan.pasos[-1].estado == "bloqueado"


def test_solicitud_de_mostrar_plan_no_autoriza_propuesta():
    p = Planificador("Muestra el plan sin registrar ninguna nota.")
    assert not p.permite_nota


def test_replanificar_en_misma_instancia_invalida_vista_previa_anterior(entorno):
    servicio, memoria, _ = entorno
    llm = modelo(llamada("registrar_nota_ticket", ticket_id=TICKET, texto="Primera propuesta"),
        llamada("consultar_ticket", ticket_id=TICKET), llamada("consultar_sla", prioridad="P2"),
        llamada("analizar_incidente", ticket_id=TICKET),
        llamada("registrar_nota_ticket", ticket_id=TICKET, texto="Nueva propuesta tras reporte"))
    a = AgenteEP2(servicio, llm=llm)
    primera = a.responder("Propón una nota de seguimiento.").confirmaciones[0]
    nueva = a.responder("Ahora hay varios usuarios afectados. Propón una nota actualizada.")
    assert nueva.estado == "requiere_confirmacion"
    assert a.confirmar_nota(DecisionConfirmacion(solicitud_id=primera.solicitud_id, huella=primera.huella, decision="confirmar")).estado == "denegado"
    with memoria.almacen._conexion() as c:
        assert c.execute("SELECT COUNT(*) FROM notas").fetchone()[0] == 0


def test_mostrar_plan_no_reanuda_ni_ejecuta_lecturas_bloqueadas():
    p = Planificador(SOLICITUD)
    p.finalizar("limite")
    q = Planificador("Retoma el plan y muestra el estado sin ejecutar acciones.", anterior=p.plan, ticket_activo=TICKET)
    assert all(s.estado == "bloqueado" for s in q.plan.pasos)
    assert q.preparar("consultar_ticket", {"ticket_id": TICKET}).codigo == "PLAN_SOLO_ESTADO"


def test_cancelacion_humana_cancela_paso_de_nota(entorno):
    servicio, memoria, _ = entorno
    a = AgenteEP2(servicio, llm=modelo(llamada("registrar_nota_ticket", ticket_id=TICKET, texto="Seguimiento")))
    s = a.responder("Propón una nota de seguimiento.").confirmaciones[0]
    r = a.confirmar_nota(DecisionConfirmacion(solicitud_id=s.solicitud_id, huella=s.huella, decision="cancelar"))
    assert r.estado == "cancelada"
    assert memoria.recuperar().plan.pasos[-1].estado == "cancelado"


def test_nuevo_plan_invalida_propuesta_incluso_si_fallo_guardar_memoria(entorno, monkeypatch):
    servicio, memoria, _ = entorno
    llm = modelo(llamada("registrar_nota_ticket", ticket_id=TICKET, texto="Propuesta antigua"),
                 llamada("consultar_sla", prioridad="P2"), AIMessage(content="SLA"))
    a = AgenteEP2(servicio, llm=llm, memoria=memoria)
    guardar = memoria.registrar_turno
    monkeypatch.setattr(memoria, "registrar_turno", Mock(side_effect=OSError("disco")))
    s = a.responder("Propón una nota.").confirmaciones[0]
    monkeypatch.setattr(memoria, "registrar_turno", guardar)
    a.responder("Consulta SLA P2.")
    r = a.confirmar_nota(DecisionConfirmacion(solicitud_id=s.solicitud_id, huella=s.huella, decision="confirmar"))
    assert r.estado == "denegado"


def test_confirmacion_tras_consulta_rechazada_conserva_trazabilidad_del_plan(entorno):
    servicio, memoria, _ = entorno
    a = AgenteEP2(servicio, llm=modelo(llamada("registrar_nota_ticket", ticket_id=TICKET, texto="Seguimiento")))
    s = a.responder("Propón una nota.").confirmaciones[0]
    assert a.responder("Dame una receta de cocina.").estado == "denegado"
    r = a.confirmar_nota(DecisionConfirmacion(solicitud_id=s.solicitud_id, huella=s.huella, decision="confirmar"))
    assert r.estado == "ok"
    assert memoria.recuperar().plan.pasos[-1].estado == "completado"


def test_observacion_real_de_prioridad_nueva_replantea_sin_duplicar_sla(entorno):
    servicio, _, ruta = entorno
    p = Planificador(SOLICITUD + " Analiza el incidente.")
    ticket_sla(p, servicio)
    with closing(sqlite3.connect(ruta)) as c, c:
        c.execute("UPDATE tickets SET prioridad='P1' WHERE id=?", (TICKET,))
    resultado = servicio.analizar_incidente(ConsultaTicket(ticket_id=TICKET))
    ejecutar(p, "analizar_incidente", resultado, ticket_id=TICKET)
    assert p.plan.prioridad_registrada == "P1"
    assert p.plan.prioridad_propuesta is None
    assert next(s for s in p.plan.pasos if s.herramienta == "consultar_sla").codigo == "SLA_VERIFICADO_EN_ANALISIS"
    assert any(c.codigo == "REPLANIFICACION_PRIORIDAD_REGISTRADA" for c in p.plan.cambios)


def test_reportar_nuevo_impacto_no_obliga_a_proponer_nota_no_solicitada(entorno):
    servicio, _, _ = entorno
    p = Planificador("Propón una nota de seguimiento.", ticket_activo=TICKET)
    q = Planificador("Ahora hay varios usuarios afectados.", anterior=p.plan, ticket_activo=TICKET)
    ticket_sla(q, servicio)
    ejecutar(q, "analizar_incidente", servicio.analizar_incidente(ConsultaTicket(ticket_id=TICKET)), ticket_id=TICKET)
    assert not q.permite_nota
    assert not q.disponibles()
    assert next(s for s in q.plan.pasos if s.herramienta == "registrar_nota_ticket").estado == "pendiente"


def test_correccion_de_decision_indica_herramientas_disponibles_sin_salida_interna(entorno):
    from langchain_core.exceptions import OutputParserException
    servicio, _, _ = entorno
    a = AgenteEP2(servicio)
    a._planificador = Planificador(SOLICITUD + " Propón una nota.")
    error = OutputParserException("contenido interno que no debe reproducirse")
    primera = a._corregir_decision(error)
    assert "AHORA según el plan: consultar_ticket." in primera
    assert "contenido interno" not in primera
    ticket_sla(a._planificador, servicio)
    segunda = a._corregir_decision(error)
    assert "AHORA según el plan: buscar_procedimiento." in segunda
    assert "No propongas la nota" in segunda


def test_modelo_conserva_registro_y_recibe_eleccion_del_plan_actual(entorno):
    servicio, _, _ = entorno
    llm = modelo(llamada("consultar_ticket", ticket_id=TICKET), llamada("consultar_sla", prioridad="P2"), AIMessage(content="Fuentes verificadas"))
    r = AgenteEP2(servicio, llm=llm).responder(f"Consulta ticket {TICKET} y su SLA.")
    assert r.estado == "ok"
    registro = [h.name for h in AgenteEP2(servicio).herramientas]
    assert llm.enlaces == [(registro, {}), (registro, {})]
    assert "CONTROL DEL SERVIDOR" in llm.entradas[0][-1].content
    assert "herramientas: consultar_sla." in llm.entradas[1][-1].content


def test_seleccion_autonoma_entre_herramientas_con_igual_prioridad(entorno):
    servicio, _, _ = entorno
    llm = modelo(llamada("consultar_activo", ticket_id=TICKET), llamada("consultar_sla", prioridad="P2"), AIMessage(content="Activo y SLA verificados"))
    r = AgenteEP2(servicio, llm=llm).responder(f"Consulta SLA P2 y activo de {TICKET}.")
    assert r.estado == "ok"
    assert llm.enlaces[0][1] == {}
    assert "herramientas: consultar_sla, consultar_activo." in llm.entradas[0][-1].content
    assert [t.nombre for t in r.herramientas] == ["consultar_activo", "consultar_sla"]


def test_scratchpad_de_correccion_excluye_log_del_modelo_y_errores_obsoletos():
    from langchain_core.agents import AgentAction
    from src.ep2.agente import _formatear_observaciones
    pasos = [(AgentAction("_Exception", "", "razonamiento interno"), "Corrección anterior"),
             (AgentAction("_Exception", "", "otra salida interna"), "Corrección vigente")]
    mensajes = _formatear_observaciones(pasos)
    assert [m.content for m in mensajes] == ["Corrección vigente"]
