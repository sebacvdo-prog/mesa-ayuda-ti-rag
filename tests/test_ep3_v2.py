"""Compatibilidad, instrumentación y privacidad de v2."""
from contextlib import closing
from pathlib import Path
from datetime import datetime,timezone
from uuid import uuid4
from unittest.mock import Mock
import json
import sqlite3
import pytest
from pydantic import ValidationError
from src.ep3.contratos_v2 import EventoV2,DetallesV2,leer_evento
from src.ep3.almacenamiento import AlmacenObservabilidad,APPLICATION_ID
from src.ep3.identidad import crear_clave,leer_clave
from src.ep3.observabilidad import Observabilidad
from src.ep3.lectura import cargar,DatosNoDisponibles
from tests.test_ep3_contratos import evento
from tests.test_ep3_integracion import ep1,ep2,TICKET
from tests.test_ep3_observabilidad import emitir,leer

def test_v1_se_lee_y_migra_con_respaldo_y_sin_reescribir_eventos(tmp_path):
    from src.ep3.contratos import Evento
    e=Evento.model_validate(evento());texto=e.model_dump_json()
    ruta=tmp_path/'observabilidad.db'
    with closing(sqlite3.connect(ruta)) as c,c:
        c.execute(f'PRAGMA application_id={APPLICATION_ID}');c.execute('PRAGMA user_version=1')
        c.execute('CREATE TABLE trazas(ejecucion_id TEXT PRIMARY KEY, version_esquema INTEGER, sesion_ref TEXT NOT NULL,tipo_ejecucion TEXT,pipeline TEXT,inicio_utc TEXT)')
        c.execute('CREATE TABLE eventos(evento_id TEXT PRIMARY KEY,ejecucion_id TEXT,secuencia INTEGER,fecha_utc TEXT,evento TEXT,componente TEXT,duracion_ms REAL,estado TEXT,codigo TEXT,contenido_json TEXT)')
        c.execute('CREATE TABLE salud_telemetria(recolector_id TEXT PRIMARY KEY,actualizado_utc TEXT,contadores_json TEXT)')
        c.execute('INSERT INTO trazas VALUES (?,?,?,?,?,?)',(str(e.ejecucion_id),1,e.sesion_ref,e.tipo_ejecucion,e.pipeline,e.inicio_utc.isoformat()))
        c.execute('INSERT INTO eventos VALUES (?,?,?,?,?,?,?,?,?,?)',(str(e.evento_id),str(e.ejecucion_id),1,e.fecha_utc.isoformat(),e.evento,e.componente,1.0,e.estado,e.codigo,texto))
    assert cargar(ruta).version==1
    with Observabilidad(tmp_path,tipo_ejecucion='simulada') as obs: emitir(obs);assert obs.flush()
    respaldos=list(tmp_path.glob('*.bak'));assert len(respaldos)==1
    with closing(sqlite3.connect(respaldos[0])) as c:
        assert c.execute('PRAGMA user_version').fetchone()[0]==1
        assert c.execute('SELECT contenido_json FROM eventos').fetchone()[0]==texto
    datos=cargar(ruta)
    assert datos.version==2 and len(datos.eventos)==3
    assert next(e for e in datos.eventos if e['version_esquema']==1)['evento_id']==str(e.evento_id)

def test_sin_clave_se_desactiva_correlacion_y_clave_persistente_no_se_sobrescribe(tmp_path):
    ruta=tmp_path/'identidad.key';crear_clave(ruta);clave=leer_clave(ruta)
    with pytest.raises(FileExistsError): crear_clave(ruta)
    assert clave==leer_clave(ruta)
    with Observabilidad(tmp_path/'a',clave_sesion=clave) as a, Observabilidad(tmp_path/'b',clave_sesion=leer_clave(ruta)) as b, Observabilidad(tmp_path/'c') as c:
        assert a.iniciar('ep2',('a','s','agente')).traza.sesion_ref==b.iniciar('ep2',('a','s','agente')).traza.sesion_ref
        assert c.iniciar('ep2',('a','s','agente')).traza.sesion_ref is None
        assert c.iniciar('ep2',('a','s','agente')).traza.correlacion=='desactivada'

@pytest.mark.parametrize('campo',['prompt','respuesta','nota','documento','api_key','exception','usuario_id','huella'])
def test_v2_no_admite_contenido_privado(campo):
    with pytest.raises(ValidationError): DetallesV2.model_validate({campo:'NO_PUBLICAR'})

def test_modelo_memoria_recursos_solicitudes_distintas_de_decisiones(tmp_path):
    with Observabilidad(tmp_path/'obs',tipo_ejecucion='simulada') as obs:
        agente,_=ep2(tmp_path/'negocio',obs)
        r=agente.responder(f'Consulta ticket {TICKET}.')
        eventos=leer(obs)
        solicitudes=[e for e in eventos if e.evento=='modelo_inicio']
        assert r.estado=='ok' and len(solicitudes)==2
        assert len({e.detalles.solicitud_id_tecnica for e in solicitudes})==2
        finales=[e for e in eventos if e.evento=='modelo_fin']
        assert all(e.detalles.tokens_entrada is None and e.detalles.tokens_salida is None for e in finales)
        assert any(e.evento=='memoria_fin' for e in eventos)
        assert eventos[-1].detalles.cpu_ms is not None

def test_ep1_callback_registra_tokens_solo_si_modelo_los_informa(tmp_path):
    from langchain_core.messages import AIMessage
    respuesta=AIMessage(content='NO_PUBLICAR',usage_metadata={'input_tokens':7,'output_tokens':2,'total_tokens':9})
    with Observabilidad(tmp_path/'obs',tipo_ejecucion='simulada') as obs:
        agente,_=ep1(tmp_path,obs,respuestas=[respuesta]);agente.responder('Procedimiento VPN.')
        eventos=leer(obs);modelo=[e for e in eventos if e.evento=='modelo_fin']
        assert len(modelo)==1 and modelo[0].detalles.tokens_entrada==7 and modelo[0].detalles.tokens_salida==2
        assert 'NO_PUBLICAR' not in '\n'.join(e.model_dump_json() for e in eventos)

def test_lector_no_modifica_archivo_y_omite_eventos_corruptos(tmp_path):
    with Observabilidad(tmp_path) as obs: emitir(obs);assert obs.flush()
    ruta=tmp_path/'observabilidad.db'
    with closing(sqlite3.connect(ruta)) as c,c:
        c.execute("UPDATE eventos SET contenido_json=? WHERE secuencia=1",('{"consulta":"NO_PUBLICAR"}',))
    antes=ruta.read_bytes();datos=cargar(ruta)
    assert datos.invalidos==1 and 'NO_PUBLICAR' not in str(datos.eventos) and ruta.read_bytes()==antes

def test_retencion_es_politica_no_borrado(tmp_path):
    with Observabilidad(tmp_path,retencion_dias=1) as obs: emitir(obs);assert obs.flush()
    datos=cargar(tmp_path/'observabilidad.db')
    assert datos.retencion_dias==1 and len(datos.eventos)==2

def test_reloj_de_instrumentacion_falla_sin_cambiar_respuesta(tmp_path,monkeypatch):
    from src.ep3 import instrumentacion
    with Observabilidad(tmp_path/'obs') as obs:
        agente,_=ep2(tmp_path/'negocio',obs)
        monkeypatch.setattr(instrumentacion,'perf_counter',Mock(side_effect=OSError('NO_PUBLICAR')))
        assert agente.responder(f'Consulta ticket {TICKET}.').estado=='ok'
        assert obs.estadisticas()['fallos_instrumentacion']>0

def test_resumidor_ep1_no_duplica_solicitudes_por_callbacks_heredados(tmp_path):
    from src import memory
    memory.reiniciar_sesion('ep3_resumen_v2')
    with Observabilidad(tmp_path/'obs',tipo_ejecucion='simulada') as obs:
        agente,llm=ep1(tmp_path,obs);agente._usar_resumidor_llm=True
        for _ in range(8): agente.responder('Procedimiento VPN.',session_id='ep3_resumen_v2')
        eventos=leer(obs)
        solicitudes=[e for e in eventos if e.evento=='modelo_inicio']
        assert len(solicitudes)==len(llm.entradas)
        assert len({e.detalles.solicitud_id_tecnica for e in solicitudes})==len(solicitudes)
    memory.reiniciar_sesion('ep3_resumen_v2')

def test_correlacion_no_puede_afirmarse_sin_clave(tmp_path):
    from src.ep3.contratos_v2 import TrazaV2
    datos=dict(ejecucion_id=uuid4(),tipo_ejecucion='simulada',pipeline='ep2',inicio_utc=datetime.now(timezone.utc),correlacion='estable')
    with pytest.raises(ValidationError): TrazaV2.model_validate(datos)

def test_muestreo_recursos_cachea_api_sin_cachear_la_medicion():
    from src.ep3.recursos import muestra,_api_windows
    import os
    a=muestra();b=muestra()
    assert b[0]>=a[0]
    if os.name=='nt':
        assert a[2]==b[2]=='working_set' and a[1]>0 and b[1]>0
        assert _api_windows.cache_info().currsize==1

@pytest.mark.parametrize('fallar',[False,True])
def test_hook_diagnostico_ep2_no_contamina_procesos_posteriores(tmp_path,monkeypatch,fallar):
    from eval import check_ep2_retrieval as d
    hooks=[]
    monkeypatch.setattr(d.sys,'addaudithook',hooks.append)
    monkeypatch.setattr(d.config,'PROVEEDOR_EMBEDDINGS','huggingface')
    recuperador=Mock()
    recuperador.buscar_procedimiento.return_value=[]
    if fallar: recuperador.buscar.side_effect=lambda *a,**k: hooks[0]('socket.connect',())
    monkeypatch.setattr(d,'RecuperadorVectorial',Mock(return_value=recuperador))
    assert d.main(['--consulta','KB-RED-02'])==1
    assert len(hooks)==1
    hooks[0]('socket.connect',())  # Fuera del diagnóstico ya no bloquea.

def test_429_no_se_etiqueta_como_temporal_sin_evidencia():
    from src.ep3.instrumentacion import clase_error
    assert clase_error(Mock(status_code=429,body={'code':'insufficient_quota'}))=='proveedor'

def test_metadato_http_anomalo_no_interrumpe_observacion():
    from src.ep3.observabilidad import _estado_http
    class Error(RuntimeError):
        @property
        def status_code(self): raise ValueError('NO_PUBLICAR')
    assert _estado_http(Error()) is None
