"""Persistencia, correlación, aislamiento y fallas controladas del recolector."""

from contextlib import closing
import json
import sqlite3
from threading import Event, Thread
from unittest.mock import Mock

import pytest

from src.ep3 import observabilidad as mod
from src.ep3.almacenamiento import AlmacenObservabilidad
from src.ep3.contratos_v2 import leer_evento


def leer(obs):
    assert obs.flush()
    with closing(sqlite3.connect((obs.directorio / 'observabilidad.db').as_uri() + '?mode=ro', uri=True)) as c:
        return [leer_evento(f[0]) for f in c.execute('SELECT contenido_json FROM eventos ORDER BY rowid')]


def emitir(obs, identidad=('persona_privada', 'sesion_privada', 'agente')):
    ctx = obs.iniciar('ep2', identidad)
    ctx.emitir('consulta_inicio', 'agente', 'info', 'CONSULTA_INICIO')
    ctx.emitir('consulta_fin', 'agente', 'ok', 'OK', duracion_ms=1.0)
    return ctx


def test_sesiones_hmac_y_ejecuciones_independientes(tmp_path):
    with mod.Observabilidad(tmp_path, tipo_ejecucion='simulada', clave_sesion=b'a' * 32) as obs:
        a, b = emitir(obs), emitir(obs)
        c = emitir(obs, ('otra_persona', 'sesion_privada', 'agente'))
        eventos = leer(obs)
        assert a.traza.sesion_ref == b.traza.sesion_ref != c.traza.sesion_ref
        assert a.traza.ejecucion_id != b.traza.ejecucion_id
        assert [e.secuencia for e in eventos if e.ejecucion_id == a.traza.ejecucion_id] == [1, 2]
        assert obs.estadisticas()['persistidos'] == 6
    datos = (tmp_path / 'observabilidad.db').read_bytes()
    assert all(p not in datos for p in (b'persona_privada', b'sesion_privada', b'otra_persona'))


def test_clave_explicita_permite_correlacion_sin_guardar_identidades(tmp_path):
    with mod.Observabilidad(tmp_path / 'a', clave_sesion=b'a' * 32) as a, \
         mod.Observabilidad(tmp_path / 'b', clave_sesion=b'a' * 32) as b, \
         mod.Observabilidad(tmp_path / 'c', clave_sesion=b'b' * 32) as c:
        ra = emitir(a).traza.sesion_ref
        assert emitir(b).traza.sesion_ref == ra != emitir(c).traza.sesion_ref


def test_validacion_y_cierre_contabilizan_perdidas_sin_datos_crudos(tmp_path):
    obs = mod.Observabilidad(tmp_path)
    emitir(obs)
    obs.registrar({'consulta': 'NO_PUBLICAR'})
    assert obs.cerrar()
    emitir(obs)
    salud = obs.estadisticas()
    assert salud['fallos_validacion'] == 1 and salud['descartados'] == 3
    assert salud['persistidos'] == 2 and salud['pendientes'] == 0
    with closing(sqlite3.connect(tmp_path / 'observabilidad.db')) as c:
        guardado = json.loads(c.execute('SELECT contadores_json FROM salud_telemetria').fetchone()[0])
        assert guardado['fallos_validacion'] == 1
    assert b'NO_PUBLICAR' not in (tmp_path / 'observabilidad.db').read_bytes()


def test_error_de_disco_no_propaga_y_conserva_contadores_en_ram(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, 'AlmacenObservabilidad', Mock(side_effect=OSError('NO_PUBLICAR')))
    with mod.Observabilidad(tmp_path) as obs:
        emitir(obs)
        assert obs.flush()
        assert obs.estadisticas()['fallos_almacenamiento'] >= 1
        assert obs.estadisticas()['descartados'] == 2
        assert not (tmp_path / 'observabilidad.db').exists()


def test_cola_acotada_no_espera_al_disco_y_hace_visibles_las_perdidas(tmp_path, monkeypatch):
    inicio, liberar = Event(), Event()
    original = mod.AlmacenObservabilidad
    def lento(directorio):
        inicio.set()
        assert liberar.wait(5)
        return original(directorio)
    monkeypatch.setattr(mod, 'AlmacenObservabilidad', lento)
    obs = mod.Observabilidad(tmp_path, capacidad=1)
    try:
        ctx = obs.iniciar('ep2', ('a', 's', 'agente'))
        ctx.emitir('consulta_inicio', 'agente', 'info', 'CONSULTA_INICIO')
        assert inicio.wait(5)
        ctx.emitir('consulta_fin', 'agente', 'ok', 'OK')
        ctx.emitir('consulta_fin', 'agente', 'ok', 'OK')
        assert obs.estadisticas()['descartados'] == 1
        assert obs.flush(timeout=0.01) is False
    finally:
        liberar.set()
        assert obs.cerrar()
    with closing(sqlite3.connect(tmp_path / 'observabilidad.db')) as c:
        assert c.execute('SELECT COUNT(*) FROM eventos').fetchone()[0] == 2
        salud = json.loads(c.execute('SELECT contadores_json FROM salud_telemetria').fetchone()[0])
        assert salud['descartados'] == 1 and salud['pendientes'] == 0


def test_contextos_concurrentes_no_mezclan_sesiones(tmp_path):
    with mod.Observabilidad(tmp_path, clave_sesion=b'c' * 32) as obs:
        hilos = [Thread(target=emitir, args=(obs, (str(i), 's', 'agente'))) for i in range(8)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join()
        eventos = leer(obs)
        assert len(eventos) == 16
        assert len({e.ejecucion_id for e in eventos}) == len({e.sesion_ref for e in eventos}) == 8


@pytest.mark.parametrize('version', [0, 2])
def test_base_ajena_o_version_incompatible_no_se_adopta_ni_modifica(tmp_path, version):
    ruta = tmp_path / 'observabilidad.db'
    with closing(sqlite3.connect(ruta)) as c, c:
        c.execute('CREATE TABLE ajena (id INTEGER)')
        if version:
            from src.ep3.almacenamiento import APPLICATION_ID
            c.execute(f'PRAGMA application_id={APPLICATION_ID}')
            c.execute(f'PRAGMA user_version={version}')
    antes = ruta.read_bytes()
    with pytest.raises(ValueError):
        AlmacenObservabilidad(tmp_path)
    assert ruta.read_bytes() == antes


def test_rechaza_enlace_duro_a_base_funcional(tmp_path, monkeypatch):
    from src.ep3 import almacenamiento
    monkeypatch.setattr(almacenamiento, 'RAIZ', tmp_path)
    funcional = tmp_path / 'storage/ep2/agent.db'
    funcional.parent.mkdir(parents=True)
    funcional.write_bytes(b'NO_MODIFICAR')
    carpeta = tmp_path / 'telemetria'
    carpeta.mkdir()
    (carpeta / 'observabilidad.db').hardlink_to(funcional)
    with pytest.raises(ValueError):
        AlmacenObservabilidad(carpeta)
    assert funcional.read_bytes() == b'NO_MODIFICAR'


def test_desactivada_no_crea_archivos_y_configuracion_invalida_no_interrumpe(tmp_path, monkeypatch):
    monkeypatch.setenv('EP3_DIRECTORIO', str(tmp_path / 'no_crear'))
    monkeypatch.setenv('EP3_OBSERVABILIDAD', '0')
    assert mod.desde_entorno() is None
    monkeypatch.setenv('EP3_OBSERVABILIDAD', '1')
    monkeypatch.setenv('EP3_TIPO_EJECUCION', 'NO_PUBLICAR')
    antes = mod.fallos_configuracion()
    assert mod.desde_entorno() is None and mod.fallos_configuracion() == antes + 1
    assert not (tmp_path / 'no_crear').exists()
