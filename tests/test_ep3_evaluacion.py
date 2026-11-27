"""La evidencia debe distinguir simulación y hacer cumplir el aislamiento."""

import pytest

from eval.aislamiento_ep3 import Aislamiento
from eval.check_ep3_observabilidad import ejecutar


@pytest.mark.parametrize('evento', ['socket.connect', 'socket.getaddrinfo', 'socket.sendto',
                                   'socket.sendmsg', 'subprocess.Popen'])
def test_bloqueo_se_aplica_incluso_si_una_biblioteca_reemplaza_socket(tmp_path, evento):
    guardia = Aislamiento(tmp_path)
    guardia.activo = True
    # Invocar directamente el auditor comprueba la política sin intentar red
    # ni disparar el contador del arnés externo que ejecuta esta misma prueba.
    with pytest.raises(OSError):
        guardia.auditar(evento, ())
    assert sum(guardia.controles.values()) == 1


def test_guardia_permite_solo_lectura_sqlite_original_y_bases_temporales(tmp_path):
    guardia = Aislamiento(tmp_path)
    guardia.activo = True
    uri = (tmp_path / 'data/itsm.db').as_uri()
    guardia.auditar('sqlite3.connect', (uri + '?mode=ro',))
    guardia.auditar('sqlite3.connect', (str(tmp_path / 'pruebas.db'),))
    with pytest.raises(OSError):
        guardia.auditar('sqlite3.connect', (uri + '?mode=rw',))
    with pytest.raises(OSError):
        guardia.auditar('open', (str(tmp_path / '.env'), 'w', 0))
    with pytest.raises(OSError):
        guardia.auditar('os.rename', (str(tmp_path / '.env'), str(tmp_path / 'otra')))
    assert guardia.controles['escrituras_funcionales_bloqueadas'] == 3


def test_muestra_reproducible_usa_componentes_reales_y_modelo_simulado(tmp_path):
    r = ejecutar(tmp_path / 'muestra')
    assert r['aprobado'] and r['tipo_ejecucion'] == 'simulada'
    assert r['consultas'] == 2 and r['herramientas'] == 7
    assert r['errores_modelo'] == r['reintentos_modelo'] == 1
    assert r['eventos_planificacion'] > 0 and all(t >= 0 for t in r['latencias_consulta_ms'])
    assert (tmp_path / 'muestra/observabilidad.db').is_file()
