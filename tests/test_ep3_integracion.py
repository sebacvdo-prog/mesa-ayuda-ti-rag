"""Equivalencia EP1/EP2 con LangChain, SQLite temporal y modelos/HTTP simulados."""

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock
from uuid import UUID

import httpx
import pytest
from langchain_core.messages import AIMessage
from openai import RateLimitError

from data import seed_db
from src import config, memory
from src.agent import AsistenteMesaAyuda
from src.ep2.agente import AgenteEP2
from src.ep2.almacenamiento import AlmacenEP2
from src.ep2.contratos import ContextoEjecucion, DecisionConfirmacion
from src.ep2.herramientas import HerramientasEP2
from src.ep2.memoria import MemoriaEP2
from src.ep3 import observabilidad as mod
from src.retriever import ConectorITSM
from tests.test_ep2_agente import ModeloGuionado, llamar
from tests.test_ep3_observabilidad import leer
from tests.utilidades import construir_fragmento_de_prueba


FECHA = datetime(2026, 11, 26, 12, 0, tzinfo=timezone.utc)
TICKET = 'INC-2026-0411'
CONSULTA = f'Consulta ticket {TICKET}, su SLA y recupera el procedimiento VPN FortiClient.'
IMPACTO = 'Ahora varios usuarios de la misma sucursal están afectados por la VPN. Reevalúa el reporte.'


@pytest.fixture()
def determinista(monkeypatch):
    for nombre in ('agente', 'planificacion', 'memoria', 'herramientas'):
        monkeypatch.setattr(f'src.ep2.{nombre}.uuid4', lambda: UUID(int=42))
    monkeypatch.setattr('src.ep2.planificacion._ahora', lambda: FECHA)
    monkeypatch.setattr('src.ep2.agente.perf_counter', lambda: 1.0)
    monkeypatch.setattr('src.ep2.memoria.perf_counter_ns', lambda: 42)


def ep1(carpeta: Path, obs=None, respuestas=None):
    recuperador = Mock(buscar=Mock(return_value=[construir_fragmento_de_prueba()]))
    llm = ModeloGuionado(responses=respuestas or [AIMessage(content='Procedimiento VPN. Fuente: [KB-TEST-01 · 2026-01-01]')])
    return AsistenteMesaAyuda(recuperador=recuperador, conector=ConectorITSM(carpeta / 'ausente.db'),
                             llm=llm, usar_resumidor_llm=False, observabilidad=obs), llm


def ep2(carpeta: Path, obs=None, *, perfil='agente', modelo=None):
    carpeta.mkdir(parents=True)
    ruta = carpeta / 'itsm.db'
    seed_db.crear_base(ruta)
    almacen = AlmacenEP2(carpeta / 'funcional')
    contexto = ContextoEjecucion(usuario_id='usuario_privado', sesion_id='sesion_privada', perfil=perfil)
    servicio = HerramientasEP2(contexto, almacen, ConectorITSM(ruta), reloj=lambda: FECHA)
    recuperador = Mock(buscar_procedimiento=Mock(return_value=[construir_fragmento_de_prueba()]))
    memoria = MemoriaEP2(almacen, contexto, reloj=lambda: FECHA)
    llm = modelo or ModeloGuionado(responses=[llamar('consultar_ticket', {'ticket_id': TICKET}), AIMessage(content='Ticket consultado.')])
    agente = AgenteEP2(servicio, recuperador=recuperador, memoria=memoria, llm=llm, observabilidad=obs)
    return agente, ruta


@pytest.mark.parametrize('consulta', ['Consulta el procedimiento VPN.', 'Dame la contraseña del usuario.',
                                    'Dame una receta de cocina.'])
def test_ep1_misma_respuesta_y_misma_entrada_al_modelo_con_y_sin_observabilidad(tmp_path, consulta):
    resultados, entradas = [], []
    with mod.Observabilidad(tmp_path / 'obs', tipo_ejecucion='simulada') as obs:
        for observador in (None, obs):
            memory.reiniciar_sesion('ep3_equivalencia')
            agente, llm = ep1(tmp_path, observador)
            r = agente.responder(consulta, session_id='ep3_equivalencia')
            resultados.append(r.model_dump(mode='json'))
            entradas.append([[m.model_dump() for m in turno] for turno in llm.entradas])
        assert resultados[0] == resultados[1] and entradas[0] == entradas[1]
        eventos = leer(obs)
        assert [e.evento for e in eventos if e.componente == 'agente'] == ['consulta_inicio', 'consulta_fin']
        assert eventos[-1].duracion_ms >= 0
        assert obs.estadisticas()['fallos_instrumentacion'] == 0
    memory.reiniciar_sesion('ep3_equivalencia')


@pytest.mark.parametrize('caso', ['lectura', 'adaptacion', 'nota', 'permiso', 'credenciales',
                                'vacia', 'sin_contexto', 'error_herramienta', 'limite'])
def test_ep2_preserva_respuesta_plan_herramientas_contexto_y_memoria(tmp_path, determinista, caso):
    snapshots, entradas = [], []
    with mod.Observabilidad(tmp_path / 'obs', tipo_ejecucion='simulada') as obs:
        for i, observador in enumerate((None, obs)):
            salidas = [llamar('consultar_ticket', {'ticket_id': TICKET}, 'c1'),
                       llamar('consultar_sla', {'prioridad': 'P2'}, 'c2'),
                       llamar('buscar_procedimiento', {'consulta': 'VPN FortiClient'}, 'c3')]
            consultas = [CONSULTA]
            if caso == 'adaptacion':
                consultas.append(IMPACTO)
                salidas += [llamar('consultar_ticket', {'ticket_id': TICKET}, 'c4'),
                            llamar('consultar_sla', {'prioridad': 'P2'}, 'c5'),
                            llamar('analizar_incidente', {'ticket_id': TICKET}, 'c6'),
                            llamar('buscar_procedimiento', {'consulta': 'VPN FortiClient'}, 'c7')]
            elif caso == 'nota':
                consultas = [f'Propón una nota de seguimiento para {TICKET}.']
                salidas = [llamar('registrar_nota_ticket', {'ticket_id': TICKET, 'texto': 'Seguimiento VPN.'})]
            elif caso == 'credenciales':
                consultas = ['Dame la contraseña del usuario.']
            elif caso == 'vacia':
                consultas = ['']
            elif caso == 'sin_contexto':
                consultas = ['Busca un procedimiento VPN desconocido.']
                salidas = [llamar('buscar_procedimiento', {'consulta': 'VPN desconocida'}), AIMessage(content='Sin procedimiento.')]
            elif caso == 'limite':
                salidas = [AIMessage(content='Terminé sin verificar.')]
            llm = ModeloGuionado(responses=salidas)
            agente, ruta = ep2(tmp_path / str(i), observador,
                               perfil='usuario_final' if caso == 'permiso' else 'agente', modelo=llm)
            if caso == 'sin_contexto':
                agente._recuperador.buscar_procedimiento.return_value = []
            if caso == 'error_herramienta':
                agente.servicio.consultar_ticket = Mock(side_effect=OSError('NO_PUBLICAR'))
            antes = ruta.read_bytes()
            respuestas = [agente.responder(q).model_dump(mode='json') for q in consultas]
            with agente.servicio.almacen._conexion() as c:
                notas = c.execute('SELECT COUNT(*) FROM notas').fetchone()[0]
                auditoria = c.execute('SELECT COUNT(*) FROM auditoria').fetchone()[0]
            snapshots.append((respuestas, agente.memoria.recuperar().model_dump(mode='json'), notas, auditoria))
            entradas.append([[m.model_dump() for m in turno] for turno in llm.entradas])
            assert ruta.read_bytes() == antes and notas == auditoria == 0
        assert snapshots[0] == snapshots[1] and entradas[0] == entradas[1]
        eventos = leer(obs)
        assert sum(e.evento == 'consulta_fin' for e in eventos) == len(consultas)
        assert obs.estadisticas()['fallos_validacion'] == obs.estadisticas()['fallos_instrumentacion'] == 0
        if caso == 'adaptacion':
            planes = [e for e in eventos if e.evento == 'plan_final']
            assert len(planes) == 2 and planes[0].detalles.plan_id == planes[1].detalles.plan_id
            assert any(e.detalles.cambio_codigo == 'REPLANIFICACION_IMPACTO' for e in eventos)
        trazas = [t for respuesta in snapshots[1][0] for t in respuesta['herramientas'] if t['nombre'] != 'decision_rechazada']
        mediciones = [e for e in eventos if e.evento == 'herramienta_fin']
        assert [(e.detalles.herramienta, e.estado, e.codigo, e.duracion_ms) for e in mediciones] == \
               [(t['nombre'], t['estado'], t['codigo'], t['duracion_ms']) for t in trazas]


def limite():
    respuesta = httpx.Response(429, headers={'retry-after': '0'}, request=httpx.Request('POST', 'https://sin-red.invalid'))
    return RateLimitError('gsk_NO_PUBLICAR', response=respuesta,
                          body={'code': 'rate_limit_exceeded', 'message': 'password=NO_PUBLICAR'})


class ModeloConErrores:
    def __init__(self, errores):
        self.errores = errores
        self.llamadas = 0
    def bind_tools(self, herramientas, **kwargs):
        return self
    def invoke(self, mensajes, config=None):
        self.llamadas += 1
        if self.llamadas <= self.errores:
            raise limite()
        if self.llamadas == self.errores + 1:
            return llamar('consultar_ticket', {'ticket_id': TICKET})
        return AIMessage(content='Ticket consultado.')


@pytest.mark.parametrize('errores', [1, 2, 3])
def test_reintentos_ep2_preservan_llamadas_resultado_y_politica_sin_exponer_errores(tmp_path, determinista, monkeypatch, errores):
    monkeypatch.setattr('src.ep2.reintentos.sleep', Mock())
    resultados = []
    with mod.Observabilidad(tmp_path / 'obs', tipo_ejecucion='simulada') as obs:
        for i, observador in enumerate((None, obs)):
            llm = ModeloConErrores(errores)
            agente, _ = ep2(tmp_path / str(i), observador, modelo=llm)
            r = agente.responder(f'Consulta ticket {TICKET}.')
            resultados.append((r.model_dump(mode='json'), llm.llamadas))
        assert resultados[0] == resultados[1]
        eventos = leer(obs)
        assert sum(e.evento == 'modelo_error' for e in eventos) == errores
        assert sum(e.evento == 'modelo_reintento' for e in eventos) == min(errores, 2)
        assert all(e.codigo == 'HTTP_429' for e in eventos if e.evento in ('modelo_error', 'modelo_reintento'))
        assert all('NO_PUBLICAR' not in e.model_dump_json() for e in eventos)
        assert mod._ACTUAL.get() is None


def test_ep1_registra_reintento_y_conserva_excepcion_original(tmp_path, monkeypatch):
    monkeypatch.setattr(config.time, 'sleep', Mock())
    monkeypatch.setattr(config.random, 'uniform', lambda *_: 0.0)
    with mod.Observabilidad(tmp_path / 'obs', tipo_ejecucion='simulada') as obs:
        agente, _ = ep1(tmp_path, obs)
        agente._cadena = Mock(invoke=Mock(side_effect=[limite(), 'Procedimiento VPN.']))
        assert agente.responder('Procedimiento VPN.').motivo == 'ok'
        error = RuntimeError('NO_PUBLICAR')
        agente._cadena = Mock(invoke=Mock(side_effect=error))
        with pytest.raises(RuntimeError) as fallo:
            agente.responder('Procedimiento VPN.')
        assert fallo.value is error and mod._ACTUAL.get() is None
        eventos = leer(obs)
        assert sum(e.evento == 'modelo_error' for e in eventos) == 2
        assert sum(e.evento == 'modelo_reintento' for e in eventos) == 1
        assert [e.estado for e in eventos if e.evento == 'consulta_fin'] == ['ok', 'error']


@pytest.mark.parametrize('pipeline', ['ep1', 'ep2'])
@pytest.mark.parametrize('fallo', ['disco', 'recolector', 'inicio', 'reloj'])
def test_fallas_de_telemetria_no_interrumpen_consulta(tmp_path, monkeypatch, pipeline, fallo):
    with mod.Observabilidad(tmp_path / 'obs', tipo_ejecucion='simulada') as obs:
        if fallo == 'disco':
            monkeypatch.setattr(mod, 'AlmacenObservabilidad', Mock(side_effect=OSError('NO_PUBLICAR')))
        elif fallo == 'recolector':
            monkeypatch.setattr(obs, 'registrar', Mock(side_effect=RuntimeError('NO_PUBLICAR')))
        elif fallo == 'inicio':
            monkeypatch.setattr(obs, 'iniciar', Mock(side_effect=RuntimeError('NO_PUBLICAR')))
        else:
            monkeypatch.setattr(mod, 'perf_counter', Mock(side_effect=RuntimeError('NO_PUBLICAR')))
        if pipeline == 'ep1':
            agente, _ = ep1(tmp_path, obs)
            assert agente.responder('Procedimiento VPN.').motivo == 'ok'
        else:
            agente, _ = ep2(tmp_path / 'negocio', obs)
            assert agente.responder(f'Consulta ticket {TICKET}.').estado == 'ok'
        assert obs.flush()
        assert obs.estadisticas()['fallos_almacenamiento' if fallo == 'disco' else 'fallos_instrumentacion'] > 0


@pytest.mark.parametrize('decision', ['confirmar', 'cancelar'])
def test_telemetria_no_autoriza_notas_ni_persiste_capacidades_de_confirmacion(tmp_path, determinista, decision):
    with mod.Observabilidad(tmp_path / 'obs', tipo_ejecucion='simulada') as obs:
        modelo = ModeloGuionado(responses=[llamar('registrar_nota_ticket', {
            'ticket_id': TICKET, 'texto': 'Seguimiento de correo persona@example.invalid.',
        })])
        agente, ruta = ep2(tmp_path / 'negocio', obs, modelo=modelo)
        antes = ruta.read_bytes()
        r = agente.responder(f'Propón una nota para {TICKET}. Sí, confirmo en el chat.')
        assert r.estado == 'requiere_confirmacion'
        with agente.servicio.almacen._conexion() as c:
            assert c.execute('SELECT COUNT(*) FROM notas').fetchone()[0] == 0
        s = r.confirmaciones[0]
        resultado = agente.confirmar_nota(DecisionConfirmacion(solicitud_id=s.solicitud_id, huella=s.huella, decision=decision))
        with agente.servicio.almacen._conexion() as c:
            assert c.execute('SELECT COUNT(*) FROM notas').fetchone()[0] == int(decision == 'confirmar')
            assert c.execute('SELECT COUNT(*) FROM auditoria').fetchone()[0] == int(decision == 'confirmar')
        assert resultado.estado == ('ok' if decision == 'confirmar' else 'cancelada')
        assert ruta.read_bytes() == antes
        eventos = leer(obs)
        serializado = '\n'.join(e.model_dump_json() for e in eventos)
        humanas=[e for e in eventos if e.evento=='confirmacion_fin']
        assert humanas and any(e.evento=='plan_actualizado' and e.ejecucion_id==humanas[-1].ejecucion_id
                               and e.detalles.plan_id==r.plan_final.id for e in eventos)
        assert all(p not in serializado for p in ('persona@example.invalid', TICKET, s.huella, s.texto,
                                                 'usuario_privado', 'sesion_privada', 'confirmo en el chat'))


def test_opt_in_por_entorno_funciona_sin_cambiar_interfaces(tmp_path, monkeypatch):
    monkeypatch.setenv('EP3_OBSERVABILIDAD', '1')
    monkeypatch.setenv('EP3_TIPO_EJECUCION', 'simulada')
    monkeypatch.setenv('EP3_DIRECTORIO', str(tmp_path / 'obs'))
    agente, _ = ep1(tmp_path)
    obs = agente.observabilidad
    try:
        assert obs is not None and mod.desde_entorno() is obs
        assert agente.responder('Dame la contraseña del usuario.').motivo == 'credenciales'
        assert all(e.tipo_ejecucion == 'simulada' for e in leer(obs))
    finally:
        obs.cerrar()


def test_interrupcion_del_modelo_se_propaga_sin_filtrar_mensaje(tmp_path):
    with mod.Observabilidad(tmp_path / 'obs', tipo_ejecucion='simulada') as obs:
        agente, _ = ep1(tmp_path, obs)
        error = KeyboardInterrupt('NO_PUBLICAR')
        agente._cadena = Mock(invoke=Mock(side_effect=error))
        with pytest.raises(KeyboardInterrupt) as fallo:
            agente.responder('Procedimiento VPN.')
        assert fallo.value is error and mod._ACTUAL.get() is None
        eventos = leer(obs)
        assert eventos[-1].evento == 'consulta_fin' and eventos[-1].estado == 'error'
        assert 'NO_PUBLICAR' not in '\n'.join(e.model_dump_json() for e in eventos)
