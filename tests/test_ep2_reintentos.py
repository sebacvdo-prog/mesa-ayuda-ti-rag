"""Política de espera EP2 con errores HTTP reales simulados y reloj virtual."""

from datetime import datetime, timezone
from email.utils import format_datetime
from unittest.mock import Mock

import httpx
import pytest
from openai import RateLimitError

from src.ep2 import reintentos


def limite(*, headers=None, mensaje="Cuota temporal simulada.", codigo="rate_limit_exceeded", tipo=None):
    body = {"message": mensaje, "code": codigo}
    if tipo is not None:
        body["type"] = tipo
    response = httpx.Response(429, headers=headers, request=httpx.Request("POST", "https://sin-red.invalid/v1"))
    return RateLimitError("MENSAJE_PRIVADO_NO_PUBLICAR", response=response, body=body)


@pytest.fixture()
def reloj(monkeypatch):
    tiempo = [100.0]
    def avanzar(segundos):
        tiempo[0] += segundos
    dormir = Mock(side_effect=avanzar)
    monkeypatch.setattr(reintentos, "sleep", dormir)
    monkeypatch.setattr(reintentos, "monotonic", lambda: tiempo[0])
    monkeypatch.setattr(reintentos, "time", lambda: 1_700_000_000.0)
    return dormir


@pytest.mark.parametrize("headers,mensaje,espera", [
    ({"Retry-After": "2.91"}, "Please try again in 5s.", 2.91),
    ({"retry-after-ms": "2910"}, "Sin pista textual.", 2.91),
    ({"retry-after": format_datetime(datetime.fromtimestamp(1_700_000_003, timezone.utc), usegmt=True)}, "", 3.0),
    ({}, "Please try again in 2.91s. DETALLE_PRIVADO", 2.91),
    ({}, "Please try again in 2910ms.", 2.91),
    ({"retry-after": "no es una fecha"}, "Sin pista válida.", 1.0),
    ({"retry-after": "NaN"}, "", 1.0),
    ({"retry-after": "inf"}, "", 1.0),
    ({"retry-after": "-2"}, "", 1.0),
])
def test_respeta_pistas_validas_y_no_propaga_datos_privados(reloj, caplog, headers, mensaje, espera):
    error = limite(headers=headers, mensaje=mensaje)
    modelo = Mock(invoke=Mock(side_effect=[error, "respuesta verificada"]))
    mensajes, config = object(), {"metadata": {"caso": "prueba"}}
    assert reintentos.invocar_modelo(modelo, mensajes, config=config, deadline=110) == "respuesta verificada"
    assert [c.args[0] for c in reloj.call_args_list] == pytest.approx([espera])
    assert modelo.invoke.call_count == 2
    assert all(c.args[0] is mensajes and c.kwargs["config"] is config for c in modelo.invoke.call_args_list)
    assert "HTTP 429" in caplog.text and "1/2" in caplog.text
    assert "PRIVADO" not in caplog.text and "retry-after" not in caplog.text


def test_sin_pista_aplica_uno_y_dos_segundos_y_despues_completa(reloj):
    modelo = Mock(invoke=Mock(side_effect=[limite(), limite(), "ok"]))
    assert reintentos.invocar_modelo(modelo, []) == "ok"
    assert [c.args[0] for c in reloj.call_args_list] == [1.0, 2.0]
    assert modelo.invoke.call_count == 3


@pytest.mark.parametrize("maximo", [2, 10])
def test_nunca_supera_dos_reintentos_y_propaga_ultimo_429(reloj, maximo):
    errores = [limite() for _ in range(3)]
    modelo = Mock(invoke=Mock(side_effect=errores))
    with pytest.raises(RateLimitError) as fallo:
        reintentos.invocar_modelo(modelo, [], max_reintentos=maximo)
    assert fallo.value is errores[-1]
    assert modelo.invoke.call_count == 3 and reloj.call_count == 2


@pytest.mark.parametrize("headers,mensaje", [
    ({"retry-after": "10.01"}, "Please try again in 2s."),
    ({"retry-after": "440"}, ""),
    ({}, "Please try again in 1m2.91s."),
])
def test_espera_larga_no_se_recorta_para_adelantar_la_peticion(reloj, headers, mensaje):
    error = limite(headers=headers, mensaje=mensaje)
    modelo = Mock(invoke=Mock(side_effect=error))
    with pytest.raises(RateLimitError) as fallo:
        reintentos.invocar_modelo(modelo, [])
    assert fallo.value is error and modelo.invoke.call_count == 1
    reloj.assert_not_called()


@pytest.mark.parametrize("deadline", [99.0, 100.0, 102.0, 102.91])
def test_espera_no_cabe_en_presupuesto_conserva_429(reloj, deadline):
    error = limite(headers={"retry-after": "2.91"})
    modelo = Mock(invoke=Mock(side_effect=error))
    with pytest.raises(RateLimitError) as fallo:
        reintentos.invocar_modelo(modelo, [], deadline=deadline)
    assert fallo.value is error and modelo.invoke.call_count == 1
    reloj.assert_not_called()


def test_despertar_despues_del_deadline_no_hace_otra_peticion(reloj, monkeypatch):
    tiempos = iter([100.0, 112.0])
    monkeypatch.setattr(reintentos, "monotonic", lambda: next(tiempos))
    error = limite(headers={"retry-after": "2.91"})
    modelo = Mock(invoke=Mock(side_effect=error))
    with pytest.raises(RateLimitError) as fallo:
        reintentos.invocar_modelo(modelo, [], deadline=110)
    assert fallo.value is error and modelo.invoke.call_count == 1
    reloj.assert_called_once_with(2.91)


@pytest.mark.parametrize("codigo", ["insufficient_quota", "billing_hard_limit_reached", "otro_error"])
def test_429_con_codigo_no_temporal_no_se_reintenta(reloj, codigo):
    modelo = Mock(invoke=Mock(side_effect=limite(codigo=codigo)))
    with pytest.raises(RateLimitError):
        reintentos.invocar_modelo(modelo, [])
    assert modelo.invoke.call_count == 1
    reloj.assert_not_called()


@pytest.mark.parametrize("estado", [400, 401, 403, 408, 500])
def test_otros_errores_http_no_se_reintentan(reloj, estado):
    error = httpx.HTTPStatusError("PRIVADO", request=httpx.Request("POST", "https://sin-red.invalid"),
        response=httpx.Response(estado))
    error.status_code = estado
    modelo = Mock(invoke=Mock(side_effect=error))
    with pytest.raises(httpx.HTTPStatusError) as fallo:
        reintentos.invocar_modelo(modelo, [])
    assert fallo.value is error and modelo.invoke.call_count == 1
    reloj.assert_not_called()


@pytest.mark.parametrize("error", [RuntimeError("PRIVADO"), KeyboardInterrupt()])
def test_error_sin_estado_o_interrupcion_no_se_reintenta(reloj, error):
    modelo = Mock(invoke=Mock(side_effect=error))
    with pytest.raises(type(error)):
        reintentos.invocar_modelo(modelo, [])
    assert modelo.invoke.call_count == 1
    reloj.assert_not_called()


def test_evaluacion_puede_desactivar_reintentos(reloj):
    modelo = Mock(invoke=Mock(side_effect=limite()))
    with pytest.raises(RateLimitError):
        reintentos.invocar_modelo(modelo, [], max_reintentos=0)
    assert modelo.invoke.call_count == 1
    reloj.assert_not_called()


@pytest.mark.parametrize("tipo,temporal", [("rate_limit_error", True), ("insufficient_quota", False)])
def test_sin_code_el_tipo_explicito_distingue_cuota_permanente(reloj, tipo, temporal):
    error = limite(codigo=None, tipo=tipo)
    modelo = Mock(invoke=Mock(side_effect=[error, "ok"]))
    if temporal:
        assert reintentos.invocar_modelo(modelo, []) == "ok"
        assert modelo.invoke.call_count == 2
        reloj.assert_called_once_with(1.0)
    else:
        with pytest.raises(RateLimitError) as fallo:
            reintentos.invocar_modelo(modelo, [])
        assert fallo.value is error and modelo.invoke.call_count == 1
        reloj.assert_not_called()
