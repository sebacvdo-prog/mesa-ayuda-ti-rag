"""Frontera de privacidad y contrato versionado, sin datos de usuarios reales."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from src.ep3.contratos import Contadores, Detalles, Evento


def evento(**cambios):
    datos = dict(ejecucion_id=uuid4(), sesion_ref='a' * 64, tipo_ejecucion='simulada',
                 pipeline='ep2', inicio_utc=datetime.now(timezone.utc), evento_id=uuid4(),
                 secuencia=1, fecha_utc=datetime.now(timezone.utc), evento='consulta_fin',
                 componente='agente', duracion_ms=1.5, estado='ok', codigo='OK')
    return {**datos, **cambios}


@pytest.mark.parametrize('campo', ['consulta', 'respuesta', 'api_key', 'password', 'usuario_id',
                                  'sesion_id', 'texto', 'huella', 'solicitud_id', 'argumentos'])
def test_rechaza_campos_libres_o_de_autorizacion(campo):
    with pytest.raises(ValidationError):
        Evento.model_validate(evento(**{campo: 'NO_PUBLICAR'}))
    with pytest.raises(ValidationError):
        Detalles.model_validate({campo: 'NO_PUBLICAR'})


@pytest.mark.parametrize('cambios', [
    {'version_esquema': 2}, {'tipo_ejecucion': 'desconocida'}, {'pipeline': 'NO_PUBLICAR'},
    {'sesion_ref': 'persona@example.invalid'}, {'ejecucion_id': 'NO_PUBLICAR'},
    {'codigo': 'GSK_NO_PUBLICAR'}, {'componente': 'NO_PUBLICAR'}, {'evento': 'NO_PUBLICAR'},
    {'duracion_ms': float('nan')}, {'duracion_ms': float('inf')}, {'duracion_ms': -1.0},
    {'secuencia': 0}, {'estado': 'NO_PUBLICAR'}, {'fecha_utc': datetime(2026, 1, 1)},
    {'inicio_utc': datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=1)))},
    {'detalles': {'herramienta': 'confirmar_nota'}}, {'detalles': {'http_status': 999}},
    {'detalles': {'revision': True}}, {'detalles': {'cambio_codigo': 'NO_PUBLICAR'}},
])
def test_rechaza_valores_incompatibles_y_texto_arbitrario(cambios):
    with pytest.raises(ValidationError):
        Evento.model_validate(evento(**cambios))


@pytest.mark.parametrize('tipo', ['real', 'simulada', 'historica'])
def test_origen_explicito_y_roundtrip_json(tipo):
    e = Evento.model_validate(evento(tipo_ejecucion=tipo))
    assert Evento.model_validate_json(e.model_dump_json()) == e
    assert e.version_esquema == 1


def test_salud_solo_admite_contadores_numericos_permitidos():
    datos = dict.fromkeys(Contadores.model_fields, 0)
    assert Contadores.model_validate(datos).emitidos == 0
    with pytest.raises(ValidationError):
        Contadores.model_validate({**datos, 'api_key': 'NO_PUBLICAR'})
    with pytest.raises(ValidationError):
        Contadores.model_validate({**datos, 'fallos_almacenamiento': 'NO_PUBLICAR'})
