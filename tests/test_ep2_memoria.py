"""Memoria real en SQLite temporal; modelos guionados, sin APIs externas."""

from __future__ import annotations

import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
from threading import Barrier
from unittest.mock import Mock

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, ToolMessage
from pydantic import Field, ValidationError

from data import seed_db
from src.ep2.agente import AgenteEP2
from src.ep2.almacenamiento import AlmacenEP2
from src.ep2.contratos import (
    ConsultaSLA, ConsultaTicket, ContextoEjecucion, DecisionConfirmacion,
    RespuestaAgenteEP2, ResultadoHerramienta,
)
from src.ep2.herramientas import HerramientasEP2
from src.ep2.memoria import LimitesMemoria, MemoriaEP2
from src.retriever import ConectorITSM


class Modelo(FakeMessagesListChatModel):
    entradas: list = Field(default_factory=list)

    def bind_tools(self, herramientas, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.entradas.append(messages)
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def llamada(nombre="consultar_ticket", **args):
    return AIMessage(content="", tool_calls=[{"name": nombre, "args": args or {"ticket_id": "INC-2026-0411"}, "id": "c"}])


def modelo(*mensajes):
    return Modelo(responses=list(mensajes))


@pytest.fixture()
def entorno(tmp_path):
    ruta = tmp_path / "itsm.db"
    seed_db.crear_base(ruta)
    almacen = AlmacenEP2(tmp_path / "ep2")
    contexto = ContextoEjecucion(usuario_id="a", sesion_id="s", perfil="agente")
    servicio = HerramientasEP2(contexto, almacen, ConectorITSM(ruta))
    memoria = MemoriaEP2(almacen, contexto)
    return servicio, memoria, ruta


def registrar(memoria, servicio, *, resultado=None, herramienta="consultar_ticket", **kwargs):
    r = resultado or servicio.consultar_ticket(ConsultaTicket(ticket_id="INC-2026-0411"))
    observacion = memoria.observar(herramienta, r)
    return memoria.registrar_turno("Consulta de ticket", RespuestaAgenteEP2(estado="ok", texto="No guardar texto libre."),
                                  [observacion], **kwargs)


def contenido(memoria):
    with memoria.almacen._conexion() as c:
        fila = c.execute("SELECT contenido FROM ep2_memoria_sesiones WHERE usuario_id=? AND sesion_id=? AND perfil=?",
                         memoria._clave).fetchone()
        return fila[0] if fila else ""


def hecho(estado, clave="ticket:INC-2026-0411"):
    return next(h for h in estado.hechos if h.clave == clave)


def test_continuidad_entre_turnos_con_historial_sin_scratchpad_anterior(entorno):
    servicio, memoria, _ = entorno
    llm = modelo(llamada(), AIMessage(content="Resultado inicial no persistido."),
                 llamada("consultar_sla", prioridad="P2"), AIMessage(content="SLA del mismo ticket."))
    agente = AgenteEP2(servicio, llm=llm, memoria=memoria)
    agente.responder("Revisa INC-2026-0411.")
    r = agente.responder("¿Y su SLA?")
    primera_entrada_segundo_turno = llm.entradas[2]
    assert r.memoria_estado == "actualizada"
    assert "INC-2026-0411" in str(primera_entrada_segundo_turno)
    assert "P2" in str(primera_entrada_segundo_turno)
    assert not any(isinstance(m, ToolMessage) for m in primera_entrada_segundo_turno)
    assert "Resultado inicial no persistido." not in contenido(memoria)
    assert len(memoria.recuperar().intercambios) == 2


def test_reabrir_agente_y_sqlite_recupera_ticket_sin_repetir_identificador(entorno):
    servicio, memoria, ruta = entorno
    AgenteEP2(servicio, llm=modelo(llamada(), AIMessage(content="Listo."))).responder("Revisa INC-2026-0411.")
    nuevo_almacen = AlmacenEP2(memoria.almacen.ruta.parent)
    nuevo_servicio = HerramientasEP2(servicio.contexto, nuevo_almacen, ConectorITSM(ruta))
    llm = modelo(llamada("consultar_sla", prioridad="P2"), AIMessage(content="SLA recuperado."))
    r = AgenteEP2(nuevo_servicio, llm=llm).responder("Continúa con su SLA.")
    assert r.estado == "ok"
    assert "INC-2026-0411" in str(llm.entradas[0])
    assert MemoriaEP2(nuevo_almacen, servicio.contexto).recuperar().ticket_activo == "INC-2026-0411"


@pytest.mark.parametrize("cambio", [{"usuario_id": "b"}, {"sesion_id": "otra"}, {"perfil": "usuario_final"}])
def test_aislamiento_por_usuario_sesion_y_perfil(entorno, cambio):
    servicio, memoria, _ = entorno
    registrar(memoria, servicio)
    contexto = servicio.contexto.model_copy(update=cambio)
    otra = MemoriaEP2(memoria.almacen, contexto)
    assert otra.recuperar().hechos == ()
    assert otra.recuperar().ticket_activo is None
    assert "INC-2026-0411" not in str(otra.mensajes(otra.recuperar()))


def test_no_se_puede_inyectar_memoria_de_otro_contexto(entorno):
    servicio, memoria, _ = entorno
    ajena = MemoriaEP2(memoria.almacen, servicio.contexto.model_copy(update={"sesion_id": "otra"}))
    with pytest.raises(ValueError, match="contexto"):
        AgenteEP2(servicio, memoria=ajena)


def test_hechos_identicos_se_actualizan_sin_duplicar_ni_crear_revision(entorno):
    servicio, memoria, _ = entorno
    inicial = registrar(memoria, servicio)
    final = registrar(memoria, servicio)
    assert len(final.hechos) == 1
    assert hecho(final).revision == 1
    assert hecho(final).anterior is None
    assert hecho(final).observado_en >= hecho(inicial).observado_en


def test_actualizacion_contradictoria_conserva_una_version_anterior_y_procedencia(entorno):
    servicio, memoria, ruta = entorno
    inicial = registrar(memoria, servicio)
    with closing(sqlite3.connect(ruta)) as c, c:
        c.execute("UPDATE tickets SET estado='resuelto', prioridad='P1' WHERE id='INC-2026-0411'")
    final = registrar(memoria, servicio)
    h = hecho(final)
    assert h.valor["estado"] == "resuelto"
    assert h.valor["prioridad"] == "P1"
    assert h.revision == 2
    assert h.anterior.valor == hecho(inicial).valor
    assert h.anterior.procedencia == ("itsm:ticket:INC-2026-0411",)
    assert h.observado_en >= h.anterior.observado_en
    with closing(sqlite3.connect(ruta)) as c, c:
        c.execute("UPDATE tickets SET prioridad='P3' WHERE id='INC-2026-0411'")
    tercera = hecho(registrar(memoria, servicio))
    assert tercera.revision == 3
    assert tercera.anterior.valor["prioridad"] == "P1"


def test_afirmaciones_de_usuario_y_razonamiento_modelo_no_son_hechos(entorno):
    servicio, memoria, _ = entorno
    llm = modelo(llamada(), AIMessage(content="La prioridad es P1.", additional_kwargs={"reasoning_content": "RAZONAMIENTO_PRIVADO"}),
                 AIMessage(content="Confirmado por mi razonamiento: P1."))
    agente = AgenteEP2(servicio, llm=llm)
    agente.responder("Consulta INC-2026-0411.")
    agente.responder("Yo afirmo que ahora la prioridad del ticket es P1.")
    assert hecho(memoria.recuperar()).valor["prioridad"] == "P2"
    assert hecho(memoria.recuperar()).revision == 1
    assert "RAZONAMIENTO_PRIVADO" not in contenido(memoria)
    assert "Confirmado por mi razonamiento" not in contenido(memoria)


def test_ticket_actualizado_invalida_triage_contradictorio_hasta_reconsultar(entorno):
    servicio, memoria, ruta = entorno
    triage = servicio.analizar_incidente(ConsultaTicket(ticket_id="INC-2026-0411"))
    registrar(memoria, servicio, resultado=triage, herramienta="analizar_incidente")
    with closing(sqlite3.connect(ruta)) as c, c:
        c.execute("UPDATE tickets SET estado='resuelto' WHERE id='INC-2026-0411'")
    registrar(memoria, servicio)
    assert hecho(memoria.recuperar(), "triage:INC-2026-0411").vigencia == "requiere_revalidacion"
    triage_nuevo = servicio.analizar_incidente(ConsultaTicket(ticket_id="INC-2026-0411"))
    nuevo = registrar(memoria, servicio, resultado=triage_nuevo, herramienta="analizar_incidente")
    assert hecho(nuevo, "triage:INC-2026-0411").vigencia == "observado"
    assert hecho(nuevo, "triage:INC-2026-0411").valor["decision"] == "caso_resuelto"


def test_observacion_lenta_anterior_no_revierte_datos_mas_nuevos(entorno):
    servicio, memoria, ruta = entorno
    vieja = memoria.observar("consultar_ticket", servicio.consultar_ticket(ConsultaTicket(ticket_id="INC-2026-0411")))
    with closing(sqlite3.connect(ruta)) as c, c:
        c.execute("UPDATE tickets SET prioridad='P1' WHERE id='INC-2026-0411'")
    registrar(memoria, servicio)
    memoria.registrar_turno("Respuesta antigua", RespuestaAgenteEP2(estado="ok", texto="Antigua"), [vieja])
    assert hecho(memoria.recuperar()).valor["prioridad"] == "P1"


def test_observacion_antigua_de_otro_ticket_no_cambia_ticket_activo(entorno):
    servicio, memoria, _ = entorno
    memoria = MemoriaEP2(memoria.almacen, memoria.contexto,
                        reloj=lambda: datetime(2026, 10, 15, tzinfo=timezone.utc))
    otro_id = servicio._conector._consultar("SELECT id FROM tickets WHERE id != ? LIMIT 1", ("INC-2026-0411",))[0]["id"]
    vieja = memoria.observar("consultar_ticket", servicio.consultar_ticket(ConsultaTicket(ticket_id=otro_id)))
    registrar(memoria, servicio)
    memoria.registrar_turno("Terminó consulta anterior", RespuestaAgenteEP2(estado="ok", texto="OK"), [vieja])
    assert memoria.recuperar().ticket_activo == "INC-2026-0411"
    # Una observación nueva con la MISMA fecha sí debe cambiar el ticket activo.
    nueva = memoria.observar("consultar_ticket", servicio.consultar_ticket(ConsultaTicket(ticket_id=otro_id)))
    memoria.registrar_turno("Nuevo ticket", RespuestaAgenteEP2(estado="ok", texto="OK"), [nueva])
    assert memoria.recuperar().ticket_activo == otro_id


def test_reintento_del_mismo_turno_no_duplica_intercambios_ni_eventos(entorno):
    servicio, memoria, _ = entorno
    registrar(memoria, servicio, id_turno="turno-1")
    registrar(memoria, servicio, id_turno="turno-1")
    assert len(memoria.recuperar().intercambios) == 1
    assert len(memoria.recuperar().eventos) == 1


def test_limites_de_turnos_hechos_eventos_y_ticket_activo(entorno):
    servicio, memoria, _ = entorno
    memoria = MemoriaEP2(memoria.almacen, memoria.contexto, limites=LimitesMemoria(turnos=2, hechos=3, eventos=2))
    registrar(memoria, servicio)
    for p in ("P1", "P2", "P3", "P4"):
        registrar(memoria, servicio, resultado=servicio.consultar_sla(ConsultaSLA(prioridad=p)), herramienta="consultar_sla")
    estado = memoria.recuperar()
    assert len(estado.intercambios) == 2
    assert len(estado.eventos) == 2
    assert len(estado.hechos) == 3
    assert estado.ticket_activo == "INC-2026-0411"


def test_limites_de_bytes_y_contexto_con_documentos_y_consultas_largas(entorno):
    servicio, memoria, _ = entorno
    memoria = MemoriaEP2(memoria.almacen, memoria.contexto,
                        limites=LimitesMemoria(bytes_sesion=4096, caracteres_contexto=4096))
    for n in range(20):
        r = ResultadoHerramienta(estado="ok", codigo="PROCEDIMIENTO_RECUPERADO", mensaje="OK",
            datos={"fragmentos": [{"documento": f"documento_{n}.md", "titulo": "á" * 160,
                                    "fecha": "2026-10-15", "puntaje": 0.8, "texto": "no almacenar" * 300}]})
        memoria.registrar_turno("VPN " + "á" * 380, RespuestaAgenteEP2(estado="ok", texto="Libre"),
                               [memoria.observar("buscar_procedimiento", r)])
    estado = memoria.recuperar()
    assert len(contenido(memoria).encode("utf-8")) <= 4096
    assert sum(len(str(m.content)) for m in memoria.mensajes(estado)) <= 4096
    assert "no almacenar" not in contenido(memoria)


def test_capacidad_global_no_elimina_sesiones_activas_y_expiracion_libera_espacio(entorno):
    servicio, memoria, _ = entorno
    tiempo = [datetime(2026, 10, 15, tzinfo=timezone.utc)]
    limites = LimitesMemoria(sesiones=2, dias=1)
    memorias = [MemoriaEP2(memoria.almacen, memoria.contexto.model_copy(update={"sesion_id": str(i)}),
                         limites=limites, reloj=lambda: tiempo[0]) for i in range(3)]
    registrar(memorias[0], servicio)
    registrar(memorias[1], servicio)
    with pytest.raises(ValueError, match="Capacidad"):
        registrar(memorias[2], servicio)
    assert memorias[0].recuperar().ticket_activo == "INC-2026-0411"
    tiempo[0] += timedelta(days=2)
    assert memorias[0].recuperar().hechos == ()
    registrar(memorias[2], servicio)
    with memoria.almacen._conexion() as c:
        assert c.execute("SELECT COUNT(*) FROM ep2_memoria_sesiones").fetchone()[0] == 1


def test_hechos_antiguos_expiran_aunque_sesion_siga_en_uso(entorno):
    servicio, memoria, _ = entorno
    tiempo = [datetime(2026, 10, 15, tzinfo=timezone.utc)]
    memoria = MemoriaEP2(memoria.almacen, memoria.contexto, limites=LimitesMemoria(dias=1), reloj=lambda: tiempo[0])
    registrar(memoria, servicio)
    tiempo[0] += timedelta(hours=20)
    registrar(memoria, servicio, resultado=servicio.consultar_sla(ConsultaSLA(prioridad="P2")), herramienta="consultar_sla")
    tiempo[0] += timedelta(hours=6)
    assert all(h.clave != "ticket:INC-2026-0411" for h in memoria.recuperar().hechos)
    assert memoria.recuperar().ticket_activo is None


def test_version_anterior_expira_aunque_hecho_actual_sea_reciente(entorno):
    servicio, memoria, ruta = entorno
    tiempo = [datetime(2026, 10, 15, tzinfo=timezone.utc)]
    memoria = MemoriaEP2(memoria.almacen, memoria.contexto, limites=LimitesMemoria(dias=1), reloj=lambda: tiempo[0])
    registrar(memoria, servicio)
    tiempo[0] += timedelta(hours=20)
    with closing(sqlite3.connect(ruta)) as c, c:
        c.execute("UPDATE tickets SET prioridad='P1' WHERE id='INC-2026-0411'")
    assert hecho(registrar(memoria, servicio)).anterior is not None
    tiempo[0] += timedelta(hours=6)
    assert hecho(memoria.recuperar()).valor["prioridad"] == "P1"
    assert hecho(memoria.recuperar()).anterior is None


def test_actualizaciones_concurrentes_se_fusionan_sin_perder_hechos(entorno):
    servicio, memoria, _ = entorno
    memoria.recuperar()
    barrera = Barrier(3)
    def escribir(p):
        propia = MemoriaEP2(memoria.almacen, memoria.contexto)
        resultado = servicio.consultar_sla(ConsultaSLA(prioridad=p))
        barrera.wait(timeout=5)
        registrar(propia, servicio, resultado=resultado, herramienta="consultar_sla")
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(escribir, ("P1", "P2", "P3")))
    estado = memoria.recuperar()
    assert {h.clave for h in estado.hechos} == {"sla:P1", "sla:P2", "sla:P3"}
    assert len(estado.intercambios) == 3


@pytest.mark.parametrize("consulta", ["password=secreto", "gsk_ficticia1234567890", "token: muysecreto"])
def test_credenciales_no_llegan_al_modelo_ni_a_la_memoria(entorno, consulta):
    servicio, memoria, _ = entorno
    llm = Mock()
    r = AgenteEP2(servicio, llm=llm).responder(consulta)
    assert r.estado == "denegado"
    assert r.memoria_estado == "sin_cambios"
    llm.bind_tools.assert_not_called()
    assert memoria.recuperar().intercambios == ()
    with pytest.raises(ValueError, match="credenciales"):
        memoria.registrar_turno(consulta, r, [])


def test_datos_personales_se_enmascaran_y_datos_extra_no_se_persisten(entorno):
    servicio, memoria, _ = entorno
    llm = modelo(llamada(), AIMessage(content="No almacenar libre"))
    AgenteEP2(servicio, llm=llm).responder("Consulta ticket INC-2026-0411 de persona@example.com con IP 10.1.2.3.")
    datos = contenido(memoria)
    assert "persona@example.com" not in datos
    assert "10.1.2.3" not in datos
    assert "[CORREO]" in datos
    assert "notas_ep2" not in datos


def test_nota_pendiente_no_persiste_contenido_tokens_ni_autorizacion_y_reinicio_invalida(entorno):
    servicio, memoria, ruta = entorno
    llm = modelo(llamada("registrar_nota_ticket", ticket_id="INC-2026-0411", texto="Texto libre de la nota NO_PERSISTIR"))
    r = AgenteEP2(servicio, llm=llm).responder("Propón la nota Texto libre de la nota NO_PERSISTIR.")
    solicitud = r.confirmaciones[0]
    datos = contenido(memoria)
    assert "NO_PERSISTIR" not in datos
    assert str(solicitud.solicitud_id) not in datos
    assert str(solicitud.id_operacion) not in datos
    assert solicitud.huella not in datos
    assert memoria.recuperar().ticket_activo == "INC-2026-0411"
    assert memoria.recuperar().tarea.pendientes == ("solicitar_nueva_vista_previa_y_confirmacion",)
    nuevo = HerramientasEP2(servicio.contexto, memoria.almacen, ConectorITSM(ruta))
    decision = DecisionConfirmacion(solicitud_id=solicitud.solicitud_id, huella=solicitud.huella, decision="confirmar")
    assert AgenteEP2(nuevo, llm=Mock()).confirmar_nota(decision).estado == "denegado"
    with memoria.almacen._conexion() as c:
        assert c.execute("SELECT COUNT(*) FROM notas").fetchone()[0] == 0


@pytest.mark.parametrize(("decision", "estado_tarea", "cantidad"), [("confirmar", "nota_registrada", 1), ("cancelar", "cancelada", 0)])
def test_evento_humano_actualiza_estado_y_procedencia_sin_texto_de_nota(entorno, decision, estado_tarea, cantidad):
    servicio, memoria, _ = entorno
    agente = AgenteEP2(servicio, llm=modelo(llamada("registrar_nota_ticket", ticket_id="INC-2026-0411", texto="No guardar en memoria.")))
    r = agente.responder("Propón una nota.")
    s = r.confirmaciones[0]
    resultado = agente.confirmar_nota(DecisionConfirmacion(solicitud_id=s.solicitud_id, huella=s.huella, decision=decision))
    estado = memoria.recuperar()
    assert estado.tarea.estado == estado_tarea
    assert not estado.tarea.pendientes
    assert "No guardar en memoria." not in contenido(memoria)
    if decision == "confirmar":
        h = hecho(estado, f"nota:{resultado.datos['id']}")
        assert h.valor["origen"] == "confirmacion_explicita_usuario"
    with memoria.almacen._conexion() as c:
        assert c.execute("SELECT COUNT(*) FROM notas").fetchone()[0] == cantidad


def test_memoria_corrupta_falla_sin_llamar_llm_ni_borrar_datos_y_se_recupera(entorno):
    servicio, memoria, _ = entorno
    registrar(memoria, servicio)
    correcto = contenido(memoria)
    with memoria.almacen._conexion() as c:
        c.execute("UPDATE ep2_memoria_sesiones SET contenido='JSON_CORRUPTO'")
    llm = modelo(llamada(), AIMessage(content="Listo"))
    agente = AgenteEP2(servicio, llm=llm)
    r = agente.responder("¿Y su SLA?")
    assert r.estado == "error"
    assert r.memoria_estado == "no_disponible"
    assert not llm.entradas
    assert contenido(memoria) == "JSON_CORRUPTO"
    with memoria.almacen._conexion() as c:
        c.execute("UPDATE ep2_memoria_sesiones SET contenido=?", (correcto,))
    assert agente.responder("Retoma el ticket.").memoria_estado == "actualizada"


def test_error_temporal_lectura_no_contamina_contexto_y_permite_reintentar(entorno, monkeypatch):
    servicio, memoria, _ = entorno
    original = memoria.recuperar
    monkeypatch.setattr(memoria, "recuperar", Mock(side_effect=sqlite3.OperationalError("detalle privado")))
    llm = modelo(llamada(), AIMessage(content="Listo"))
    agente = AgenteEP2(servicio, llm=llm, memoria=memoria)
    r = agente.responder("Consulta INC-2026-0411.")
    assert r.estado == "error" and not llm.entradas
    assert "privado" not in r.model_dump_json()
    monkeypatch.setattr(memoria, "recuperar", original)
    assert agente.responder("Consulta INC-2026-0411.").memoria_estado == "actualizada"


def test_fallo_transaccional_al_guardar_conserva_memoria_anterior_y_avisa(entorno):
    servicio, memoria, _ = entorno
    registrar(memoria, servicio)
    antes = contenido(memoria)
    with memoria.almacen._conexion() as c:
        c.execute("CREATE TRIGGER falla_memoria BEFORE UPDATE ON ep2_memoria_sesiones BEGIN SELECT RAISE(ABORT, 'fallo interno'); END")
    r = AgenteEP2(servicio, llm=modelo(llamada("consultar_sla", prioridad="P2"), AIMessage(content="Resultado"))).responder("SLA del ticket.")
    assert r.estado == "ok"
    assert r.memoria_estado == "no_disponible"
    assert r.aviso_memoria
    assert "interno" not in r.model_dump_json()
    assert contenido(memoria) == antes


def test_fallo_memoria_no_autoriza_nota_ni_descarta_solicitud_humana(entorno, monkeypatch):
    servicio, memoria, _ = entorno
    monkeypatch.setattr(memoria, "registrar_turno", Mock(side_effect=sqlite3.OperationalError("disco")))
    agente = AgenteEP2(servicio, memoria=memoria, llm=modelo(llamada("registrar_nota_ticket", ticket_id="INC-2026-0411", texto="Seguimiento.")))
    r = agente.responder("Propón una nota.")
    assert r.estado == "requiere_confirmacion" and r.confirmaciones
    assert r.memoria_estado == "no_disponible"
    with memoria.almacen._conexion() as c:
        assert c.execute("SELECT COUNT(*) FROM notas").fetchone()[0] == 0


def test_confirmacion_tardia_no_cambia_estado_de_otra_tarea_actual(entorno):
    servicio, memoria, _ = entorno
    llm = modelo(llamada("registrar_nota_ticket", ticket_id="INC-2026-0411", texto="Seguimiento."),
                 llamada("consultar_sla", prioridad="P2"), AIMessage(content="SLA obtenido"))
    agente = AgenteEP2(servicio, llm=llm)
    solicitud = agente.responder("Propón una nota.").confirmaciones[0]
    agente.responder("Consulta SLA P2.")
    objetivo = memoria.recuperar().tarea.objetivo
    agente.confirmar_nota(DecisionConfirmacion(solicitud_id=solicitud.solicitud_id, huella=solicitud.huella, decision="confirmar"))
    assert memoria.recuperar().tarea.objetivo == objetivo
    assert memoria.recuperar().tarea.estado == "ok"


def test_fallo_memoria_despues_de_confirmar_no_afirma_rollback_de_nota(entorno, monkeypatch):
    servicio, memoria, _ = entorno
    agente = AgenteEP2(servicio, memoria=memoria, llm=modelo(llamada("registrar_nota_ticket", ticket_id="INC-2026-0411", texto="Seguimiento.")))
    s = agente.responder("Propón una nota.").confirmaciones[0]
    monkeypatch.setattr(memoria, "registrar_confirmacion", Mock(side_effect=sqlite3.OperationalError("disco")))
    r = agente.confirmar_nota(DecisionConfirmacion(solicitud_id=s.solicitud_id, huella=s.huella, decision="confirmar"))
    assert r.estado == "ok"
    assert "No se pudo actualizar la memoria" in r.mensaje
    with memoria.almacen._conexion() as c:
        assert c.execute("SELECT COUNT(*) FROM notas").fetchone()[0] == 1


def test_version_futura_de_memoria_se_rechaza_sin_migracion_destructiva(entorno):
    servicio, memoria, _ = entorno
    registrar(memoria, servicio)
    antes = contenido(memoria)
    with memoria.almacen._conexion() as c:
        c.execute("UPDATE ep2_memoria_esquema SET version=99")
    with pytest.raises(ValueError, match="Versión"):
        memoria.recuperar()
    assert contenido(memoria) == antes


def test_ampliacion_de_esquema_preserva_notas_y_auditoria_de_etapa1(entorno):
    servicio, memoria, _ = entorno
    from uuid import uuid4
    from src.ep2.contratos import RegistrarNota
    r = servicio.preparar_nota(RegistrarNota(ticket_id="INC-2026-0411", id_operacion=uuid4(), texto="Conservar esta nota."))
    servicio.confirmar_nota(DecisionConfirmacion(solicitud_id=r.datos["solicitud_id"], huella=r.datos["huella"], decision="confirmar"))
    with memoria.almacen._conexion() as c:
        antes = [tuple(f) for f in c.execute("SELECT * FROM notas").fetchall()]
        auditoria = [tuple(f) for f in c.execute("SELECT * FROM auditoria").fetchall()]
    registrar(memoria, servicio)
    with memoria.almacen._conexion() as c:
        assert antes == [tuple(f) for f in c.execute("SELECT * FROM notas").fetchall()]
        assert auditoria == [tuple(f) for f in c.execute("SELECT * FROM auditoria").fetchall()]
        assert c.execute("PRAGMA user_version").fetchone()[0] == 1


@pytest.mark.parametrize(("campo", "valor"), [("turnos", 0), ("hechos", 0), ("eventos", 101),
                                              ("sesiones", 0), ("dias", 0), ("bytes_sesion", 100),
                                              ("caracteres_contexto", 100)])
def test_limites_invalidos_rechazados(campo, valor):
    with pytest.raises(ValidationError):
        LimitesMemoria(**{campo: valor})


def test_limites_configurables_por_entorno(monkeypatch):
    monkeypatch.setenv("EP2_MEMORY_TURNS", "3")
    monkeypatch.setenv("EP2_MEMORY_DAYS", "7")
    assert LimitesMemoria.desde_entorno().turnos == 3
    assert LimitesMemoria.desde_entorno().dias == 7


def test_cli_se_cierra_y_reabre_con_mismos_identificadores(entorno, monkeypatch, capsys):
    from src.ep2 import cli

    servicio, memoria, _ = entorno
    llm = modelo(llamada(), AIMessage(content="Ticket obtenido"), llamada("consultar_sla", prioridad="P2"), AIMessage(content="SLA retomado"))
    constructor = AgenteEP2
    monkeypatch.setattr(cli, "AlmacenEP2", lambda: memoria.almacen)
    monkeypatch.setattr(cli, "AgenteEP2", lambda nuevo_servicio: constructor(
        HerramientasEP2(nuevo_servicio.contexto, memoria.almacen, servicio._conector), llm=llm))
    monkeypatch.setattr("sys.argv", ["ep2.cli", "--usuario", "a", "--sesion", "s"])
    for consulta in ("Consulta INC-2026-0411.", "¿Y su SLA?"):
        entradas = iter((consulta, "/salir"))
        monkeypatch.setattr("builtins.input", lambda _: next(entradas))
        cli.main()
    assert "SLA retomado" in capsys.readouterr().out
    assert "INC-2026-0411" in str(llm.entradas[2])
