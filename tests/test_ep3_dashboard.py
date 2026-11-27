"""Streamlit AppTest: lectura real sin servidor, red ni agente."""
import os
from pathlib import Path
from unittest.mock import Mock
import pytest
from src.ep3.almacenamiento import AlmacenObservabilidad
from src.ep3.lectura import cargar,DatosNoDisponibles
from src.ep3.analisis import resumen,percentil
from src.ep3.observabilidad import Observabilidad
from tests.test_ep3_observabilidad import emitir

APP=Path(__file__).resolve().parents[1]/'src/dashboard_ep3.py'

@pytest.mark.parametrize('tipo',['ausente','vacia','datos','v1'])
def test_dashboard_lee_sin_mutar_ni_instanciar_agente(tmp_path,monkeypatch,tipo):
    import streamlit as st
    from streamlit.testing.v1 import AppTest
    ruta=tmp_path/'observabilidad.db'
    if tipo=='vacia': AlmacenObservabilidad(tmp_path).cerrar()
    if tipo=='datos':
        with Observabilidad(tmp_path,tipo_ejecucion='simulada') as obs: emitir(obs);assert obs.flush()
    if tipo=='v1':
        import sqlite3
        from contextlib import closing
        from src.ep3.almacenamiento import APPLICATION_ID
        from src.ep3.contratos import Evento
        from tests.test_ep3_contratos import evento
        e=Evento.model_validate(evento())
        with closing(sqlite3.connect(ruta)) as c,c:
            c.execute(f'PRAGMA application_id={APPLICATION_ID}');c.execute('PRAGMA user_version=1')
            c.execute('CREATE TABLE eventos(contenido_json TEXT)')
            c.execute('CREATE TABLE salud_telemetria(recolector_id TEXT,contadores_json TEXT)')
            c.execute('INSERT INTO eventos VALUES (?)',(e.model_dump_json(),))
    antes=ruta.read_bytes() if ruta.exists() else None
    monkeypatch.setenv('EP3_DASHBOARD_DB',str(ruta))
    monkeypatch.setattr('src.ep2.agente.AgenteEP2.__init__',Mock(side_effect=AssertionError('No crear agente')))
    app=AppTest.from_file(str(APP),default_timeout=20).run()
    assert not app.exception
    assert (ruta.read_bytes() if ruta.exists() else None)==antes
    if tipo in ('datos','v1'):
        assert any(m.label=='Consultas finalizadas' and m.value=='1' for m in app.metric)
        if tipo=='v1':
            app.sidebar.selectbox[1].select('no_disponible_v1').run()
            assert not app.exception
    else: assert app.info

def test_metricas_vacias_no_inventan_latencias():
    r=resumen([])
    assert r['consultas']==0 and r['p95_ms'] is None and r['promedio_ms'] is None
    assert percentil([1,3],.5)==2

def test_error_permisos_no_expone_excepcion(tmp_path,monkeypatch):
    ruta=tmp_path/'observabilidad.db';ruta.write_bytes(b'')
    import sqlite3
    monkeypatch.setattr(sqlite3,'connect',Mock(side_effect=PermissionError('NO_PUBLICAR')))
    with pytest.raises(DatosNoDisponibles) as e: cargar(ruta)
    assert 'NO_PUBLICAR' not in str(e.value)

def test_dashboard_escenarios_completos_y_filtros(tmp_path,monkeypatch):
    from eval.evaluate_ep3 import ejecutar
    from streamlit.testing.v1 import AppTest
    r=ejecutar(tmp_path/'datos',pares=2);assert r['aprobado']
    ruta=tmp_path/'datos/observabilidad.db';antes=ruta.read_bytes()
    monkeypatch.setenv('EP3_DASHBOARD_DB',str(ruta))
    monkeypatch.setattr('src.ep2.agente.AgenteEP2.__init__',Mock(side_effect=AssertionError('No crear agente')))
    app=AppTest.from_file(str(APP),default_timeout=20).run();assert not app.exception
    app.sidebar.selectbox[1].select('rag_kb').run();assert not app.exception
    assert any(m.label=='Consultas finalizadas' and m.value=='3' for m in app.metric)
    calidad=[d.value for d in app.dataframe if {'caso','metrica'}<=set(d.value.columns)]
    assert calidad and all(set(d.caso)=={'rag_kb'} for d in calidad)
    app.sidebar.selectbox[1].select('sin_procedimiento').run();assert not app.exception
    assert ruta.read_bytes()==antes
