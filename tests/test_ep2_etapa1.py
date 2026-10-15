"""Etapa 1: SQLite e ITSM reales temporales; sin LLM ni llamadas a APIs."""

from __future__ import annotations

import hashlib
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from threading import Barrier, Event
from uuid import uuid4

import pytest
from pydantic import ValidationError

from data import seed_db
from src import config
from src.ep2.almacenamiento import AlmacenEP2
from src.ep2.contratos import (
    ConsultaSLA, ConsultaTicket, ContextoEjecucion, DecisionConfirmacion, RegistrarNota,
)
from src.ep2.herramientas import HerramientasEP2
from src.retriever import ConectorITSM


@pytest.fixture()
def entorno(tmp_path):
    ruta_itsm = tmp_path / "itsm.db"
    seed_db.crear_base(ruta_itsm)
    almacen = AlmacenEP2(tmp_path / "ep2")
    contexto = ContextoEjecucion(usuario_id="agente_a", sesion_id="sesion_a", perfil="agente")
    servicio = HerramientasEP2(contexto, almacen, ConectorITSM(ruta_itsm))
    return servicio, almacen, ruta_itsm, contexto


def entrada(**valores):
    return RegistrarNota(**{"ticket_id": "INC-2026-0411", "id_operacion": uuid4(),
                            "texto": "Se verificó el enlace y se solicitó seguimiento.", **valores})


def decidir(solicitud, valor="confirmar"):
    return DecisionConfirmacion(solicitud_id=solicitud.datos["solicitud_id"],
                                huella=solicitud.datos["huella"], decision=valor)


def conteos(almacen):
    with sqlite3.connect(almacen.ruta) as conexion:
        return tuple(conexion.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                     for t in ("notas", "auditoria"))


def test_consultas_reales_minimizan_datos_y_conservan_itsm(entorno):
    servicio, _, ruta, _ = entorno
    original = hashlib.sha256(ruta.read_bytes()).digest()
    ticket = servicio.consultar_ticket(ConsultaTicket(ticket_id=" inc-2026-0411 "))
    assert ticket.estado == "ok"
    assert ticket.datos["id"] == "INC-2026-0411"
    assert not {"usuario", "rut", "correo", "descripcion"} & ticket.datos.keys()
    assert servicio.consultar_sla(ConsultaSLA(prioridad="p2")).datos["primera_respuesta_min"] == 30
    assert hashlib.sha256(ruta.read_bytes()).digest() == original


def test_preparar_no_escribe_y_solo_confirmacion_explicita_registra(entorno):
    servicio, almacen, ruta, _ = entorno
    original = ruta.read_bytes()
    solicitud = servicio.preparar_nota(entrada())
    assert solicitud.estado == "requiere_confirmacion"
    assert conteos(almacen) == (0, 0)
    assert "INC-2026-0411" in solicitud.mensaje
    registro = servicio.confirmar_nota(decidir(solicitud))
    assert registro.codigo == "NOTA_REGISTRADA"
    assert registro.datos["origen"] == "confirmacion_explicita_usuario"
    assert registro.datos["confirmado_en"]
    assert conteos(almacen) == (1, 1)
    assert ruta.read_bytes() == original


def test_cancelacion_y_confirmacion_posterior_no_escriben(entorno):
    servicio, almacen, _, _ = entorno
    solicitud = servicio.preparar_nota(entrada())
    assert servicio.confirmar_nota(decidir(solicitud, "cancelar")).estado == "cancelada"
    assert servicio.confirmar_nota(decidir(solicitud)).estado == "denegado"
    assert conteos(almacen) == (0, 0)


def test_cancelar_despues_del_commit_no_afirma_revertir_la_nota(entorno):
    servicio, almacen, _, _ = entorno
    solicitud = servicio.preparar_nota(entrada())
    servicio.confirmar_nota(decidir(solicitud))
    resultado = servicio.confirmar_nota(decidir(solicitud, "cancelar"))
    assert resultado.codigo == "NOTA_YA_REGISTRADA"
    assert conteos(almacen) == (1, 1)


def test_usuario_final_no_puede_consultar_ticket_ni_preparar_confirmar_o_leer_notas(entorno):
    agente, almacen, ruta, _ = entorno
    solicitud = agente.preparar_nota(entrada())
    contexto = ContextoEjecucion(usuario_id="colaborador", sesion_id="sesion_a", perfil="usuario_final")
    usuario = HerramientasEP2(contexto, almacen, ConectorITSM(ruta))
    assert usuario.consultar_ticket(ConsultaTicket(ticket_id="INC-2026-0411")).estado == "denegado"
    assert usuario.preparar_nota(entrada()).estado == "denegado"
    assert usuario.confirmar_nota(decidir(solicitud)).estado == "denegado"
    assert usuario.consultar_notas(ConsultaTicket(ticket_id="INC-2026-0411")).estado == "denegado"
    assert usuario.consultar_sla(ConsultaSLA(prioridad="P2")).estado == "ok"
    assert conteos(almacen) == (0, 0)


@pytest.mark.parametrize("campo", ["confirmado", "perfil", "usuario_id", "sesion_id", "huella"])
def test_argumentos_del_modelo_no_pueden_suplantar_autorizacion(campo):
    datos = entrada().model_dump()
    datos[campo] = True if campo == "confirmado" else "agente"
    with pytest.raises(ValidationError):
        RegistrarNota.model_validate(datos)


@pytest.mark.parametrize(("usuario", "sesion"), [("agente_b", "sesion_a"), ("agente_a", "sesion_b")])
def test_confirmacion_y_notas_aisladas_por_usuario_y_sesion(entorno, usuario, sesion):
    servicio, almacen, ruta, _ = entorno
    solicitud = servicio.preparar_nota(entrada())
    otro = HerramientasEP2(ContextoEjecucion(usuario_id=usuario, sesion_id=sesion, perfil="agente"),
                           almacen, ConectorITSM(ruta))
    assert otro.confirmar_nota(decidir(solicitud)).estado == "denegado"
    servicio.confirmar_nota(decidir(solicitud))
    assert otro.consultar_notas(ConsultaTicket(ticket_id="INC-2026-0411")).datos["notas"] == []
    assert len(servicio.consultar_notas(ConsultaTicket(ticket_id="INC-2026-0411")).datos["notas"]) == 1


def test_confirmacion_desconocida_no_escribe(entorno):
    servicio, almacen, _, _ = entorno
    assert servicio.confirmar_nota(DecisionConfirmacion(
        solicitud_id=uuid4(), huella="0" * 64, decision="confirmar"
    )).estado == "denegado"
    assert conteos(almacen) == (0, 0)


def test_confirmacion_expirada_no_escribe(entorno):
    _, almacen, ruta, contexto = entorno
    ahora = [datetime(2026, 10, 15, tzinfo=timezone.utc)]
    servicio = HerramientasEP2(contexto, almacen, ConectorITSM(ruta), reloj=lambda: ahora[0])
    solicitud = servicio.preparar_nota(entrada())
    ahora[0] += timedelta(minutes=5)
    assert servicio.confirmar_nota(decidir(solicitud)).estado == "expirada"
    assert conteos(almacen) == (0, 0)


def test_preview_no_se_puede_alterar_y_se_confirma_el_contenido_original(entorno):
    servicio, almacen, _, _ = entorno
    solicitud = servicio.preparar_nota(entrada(texto="Nota original."))
    solicitud.datos["texto"] = "Contenido distinto que el servidor no aprobó."
    resultado = servicio.confirmar_nota(decidir(solicitud))
    assert resultado.datos["texto"] == "Nota original."
    assert conteos(almacen) == (1, 1)


def test_huella_alterada_no_autoriza_escritura(entorno):
    servicio, almacen, _, _ = entorno
    solicitud = servicio.preparar_nota(entrada())
    decision = DecisionConfirmacion(solicitud_id=solicitud.datos["solicitud_id"],
                                    huella="0" * 64, decision="confirmar")
    assert servicio.confirmar_nota(decision).codigo == "CONTENIDO_NO_CONFIRMADO"
    assert conteos(almacen) == (0, 0)


def test_permiso_revocado_antes_de_confirmar_impide_registro(entorno):
    servicio, almacen, _, contexto = entorno
    solicitud = servicio.preparar_nota(entrada())
    servicio._contexto = contexto.model_copy(update={"perfil": "usuario_final"})
    assert servicio.confirmar_nota(decidir(solicitud)).estado == "denegado"
    assert conteos(almacen) == (0, 0)


def test_reintentos_y_nueva_instancia_reutilizan_sin_duplicar(entorno):
    servicio, almacen, ruta, contexto = entorno
    nota = entrada()
    solicitud = servicio.preparar_nota(nota)
    primero = servicio.confirmar_nota(decidir(solicitud))
    segundo = servicio.confirmar_nota(decidir(solicitud))
    nueva = HerramientasEP2(contexto, AlmacenEP2(almacen.ruta.parent), ConectorITSM(ruta))
    tercero = nueva.preparar_nota(nota)
    assert segundo.codigo == tercero.codigo == "NOTA_REUTILIZADA"
    assert primero.datos["id"] == segundo.datos["id"] == tercero.datos["id"]
    assert conteos(almacen) == (1, 1)


def test_mismo_id_distinto_contenido_es_conflicto_incluso_si_se_preparo_antes(entorno):
    servicio, almacen, _, _ = entorno
    nota = entrada()
    primera = servicio.preparar_nota(nota)
    distinta = entrada(id_operacion=nota.id_operacion, texto="Otra nota.")
    segunda = servicio.preparar_nota(distinta)
    servicio.confirmar_nota(decidir(primera))
    assert servicio.confirmar_nota(decidir(segunda)).estado == "conflicto"
    assert servicio.preparar_nota(distinta).estado == "conflicto"
    assert conteos(almacen) == (1, 1)


def test_auditoria_y_nota_se_revierten_juntas_y_se_puede_reintentar(entorno):
    servicio, almacen, _, _ = entorno
    solicitud = servicio.preparar_nota(entrada())
    with sqlite3.connect(almacen.ruta) as c:
        c.execute("CREATE TRIGGER impedir_auditoria BEFORE INSERT ON auditoria "
                  "BEGIN SELECT RAISE(ABORT, 'fallo simulado'); END")
    assert servicio.confirmar_nota(decidir(solicitud)).estado == "error"
    assert conteos(almacen) == (0, 0)
    with sqlite3.connect(almacen.ruta) as c:
        c.execute("DROP TRIGGER impedir_auditoria")
    assert servicio.confirmar_nota(decidir(solicitud)).estado == "ok"
    assert conteos(almacen) == (1, 1)


def test_confirmaciones_concurrentes_no_duplican_nota_ni_auditoria(entorno):
    servicio, almacen, ruta, contexto = entorno
    nota = entrada()
    servicios = [HerramientasEP2(contexto, almacen, ConectorITSM(ruta)) for _ in range(4)]
    solicitudes = [s.preparar_nota(nota) for s in servicios]
    with ThreadPoolExecutor(max_workers=4) as ejecutor:
        resultados = list(ejecutor.map(lambda par: par[0].confirmar_nota(decidir(par[1])),
                                       zip(servicios, solicitudes)))
    assert all(r.estado == "ok" for r in resultados)
    assert len({r.datos["id"] for r in resultados}) == 1
    assert conteos(almacen) == (1, 1)


def test_cancelacion_durante_commit_no_afirma_que_no_se_escribio(entorno, monkeypatch):
    servicio, almacen, _, _ = entorno
    solicitud = servicio.preparar_nota(entrada())
    dentro = Event()
    liberar = Event()
    original = almacen._registrar_nota_confirmada

    def demorar(*args, **kwargs):
        dentro.set()
        assert liberar.wait(timeout=5)
        return original(*args, **kwargs)

    monkeypatch.setattr(almacen, "_registrar_nota_confirmada", demorar)
    with ThreadPoolExecutor(max_workers=2) as ejecutor:
        confirmar = ejecutor.submit(servicio.confirmar_nota, decidir(solicitud))
        assert dentro.wait(timeout=5)
        cancelar = ejecutor.submit(servicio.confirmar_nota, decidir(solicitud, "cancelar"))
        try:
            with pytest.raises(TimeoutError):
                cancelar.result(timeout=0.1)
        finally:
            liberar.set()
        assert confirmar.result(timeout=5).estado == "ok"
        assert cancelar.result(timeout=5).codigo == "NOTA_YA_REGISTRADA"
    assert conteos(almacen) == (1, 1)


def test_notas_enmascaran_pii_antes_de_vista_previa_y_persistencia(entorno):
    servicio, almacen, _, _ = entorno
    texto = "Contacto persona@example.com; RUT 12.345.678-5; IP 192.168.1.20."
    solicitud = servicio.preparar_nota(entrada(texto=texto))
    for sensible in ("persona@example.com", "12.345.678-5", "192.168.1.20"):
        assert sensible not in solicitud.datos["texto"]
    registro = servicio.confirmar_nota(decidir(solicitud))
    assert registro.datos["texto"] == solicitud.datos["texto"]
    assert b"persona@example.com" not in almacen.ruta.read_bytes()


@pytest.mark.parametrize("texto", ["password=valor_secreto", "La contraseña es abc123", "token: abc123", "gsk_claveficticia12345678"])
def test_credenciales_no_crean_solicitud_ni_registro(entorno, texto):
    servicio, almacen, _, _ = entorno
    assert servicio.preparar_nota(entrada(texto=texto)).codigo == "CONTENIDO_SENSIBLE"
    assert conteos(almacen) == (0, 0)


def test_nota_con_sql_literal_no_ejecuta_sql(entorno):
    servicio, almacen, _, _ = entorno
    texto = "Verificación: '); DROP TABLE notas; --"
    solicitud = servicio.preparar_nota(entrada(texto=texto))
    assert servicio.confirmar_nota(decidir(solicitud)).datos["texto"] == texto
    assert conteos(almacen) == (1, 1)


def test_ticket_inexistente_y_ticket_desaparecido_no_generan_nota(entorno, monkeypatch):
    servicio, almacen, _, _ = entorno
    assert servicio.preparar_nota(entrada(ticket_id="INC-2026-99999")).estado == "no_encontrado"
    solicitud = servicio.preparar_nota(entrada())
    monkeypatch.setattr(servicio._conector, "estado_de_ticket", lambda _: None)
    assert servicio.confirmar_nota(decidir(solicitud)).estado == "no_encontrado"
    assert conteos(almacen) == (0, 0)


def test_reinicio_invalida_confirmaciones_pendientes(entorno):
    servicio, almacen, ruta, contexto = entorno
    solicitud = servicio.preparar_nota(entrada())
    nuevo = HerramientasEP2(contexto, almacen, ConectorITSM(ruta))
    assert nuevo.confirmar_nota(decidir(solicitud)).estado == "denegado"
    assert conteos(almacen) == (0, 0)


def test_base_existente_ajena_no_se_modifica(tmp_path):
    ruta = tmp_path / "agent.db"
    with sqlite3.connect(ruta) as c:
        c.execute("CREATE TABLE importante (valor TEXT)")
        c.execute("INSERT INTO importante VALUES ('conservar')")
    original = ruta.read_bytes()
    with pytest.raises(ValueError, match="no pertenece"):
        AlmacenEP2(tmp_path)
    assert ruta.read_bytes() == original


def test_inicializaciones_concurrentes_no_pierden_el_esquema(tmp_path, monkeypatch):
    conexion_original = AlmacenEP2._conexion
    barrera = Barrier(3)

    @contextmanager
    def sincronizar(self, comprobar_marca=True):
        if not comprobar_marca:
            barrera.wait(timeout=5)
        with conexion_original(self, comprobar_marca) as c:
            yield c

    monkeypatch.setattr(AlmacenEP2, "_conexion", sincronizar)
    with ThreadPoolExecutor(max_workers=3) as ejecutor:
        almacenes = list(ejecutor.map(lambda _: AlmacenEP2(tmp_path / "ep2"), range(3)))
    assert len({a.ruta for a in almacenes}) == 1
    assert conteos(almacenes[0]) == (0, 0)


def test_error_itsm_se_devuelve_sin_exponer_excepcion_ni_escribir(entorno, monkeypatch):
    servicio, almacen, _, _ = entorno

    def fallar(_):
        raise sqlite3.OperationalError("detalle interno sensible")

    monkeypatch.setattr(servicio._conector, "estado_de_ticket", fallar)
    resultado = servicio.preparar_nota(entrada())
    assert resultado.estado == "error"
    assert "sensible" not in resultado.model_dump_json()
    assert conteos(almacen) == (0, 0)


def test_enlace_al_itsm_original_no_se_modifica(tmp_path, monkeypatch):
    original = tmp_path / "itsm.db"
    seed_db.crear_base(original)
    huella = original.read_bytes()
    monkeypatch.setattr(config, "RUTA_BD", original)
    directorio = tmp_path / "ep2"
    directorio.mkdir()
    os.link(original, directorio / "agent.db")
    with pytest.raises(ValueError, match="enlace"):
        AlmacenEP2(directorio)
    assert original.read_bytes() == huella


@pytest.mark.parametrize("datos", [
    {"usuario_id": "persona@example.com", "sesion_id": "s", "perfil": "agente"},
    {"usuario_id": "a", "sesion_id": "s", "perfil": "administrador"},
])
def test_contexto_rechaza_identificadores_sensibles_y_perfiles_desconocidos(datos):
    with pytest.raises(ValidationError):
        ContextoEjecucion(**datos)
