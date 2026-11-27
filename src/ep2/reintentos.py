"""Reintentos acotados de inferencia EP2; nunca ejecutan herramientas."""

from __future__ import annotations

import logging
import math
import re
from email.utils import parsedate_to_datetime
from time import monotonic, sleep, time
from src.ep3.observabilidad import observar_intento, registrar_reintento
from src.ep3.instrumentacion import observar_llamada, dormir_observado


MAX_REINTENTOS = 2
MAX_ESPERA_SEGUNDOS = 10.0
_LOG = logging.getLogger(__name__)


def _detalle(error) -> dict:
    cuerpo = getattr(error, "body", None)
    if not isinstance(cuerpo, dict):
        return {}
    detalle = cuerpo.get("error", cuerpo)
    return detalle if isinstance(detalle, dict) else {}


def _segundos(valor, divisor=1.0) -> float | None:
    try:
        segundos = float(valor) / divisor
    except (TypeError, ValueError, OverflowError):
        return None
    return segundos if math.isfinite(segundos) and segundos >= 0 else None


def _espera_indicada(error) -> float | None:
    # Leer solo indicaciones de espera. Nunca registrar cuerpos ni cabeceras.
    respuesta = getattr(error, "response", None)
    cabeceras = getattr(respuesta, "headers", {})
    for nombre, divisor in (("retry-after", 1.0), ("retry-after-ms", 1000.0)):
        valor = cabeceras.get(nombre)
        segundos = _segundos(valor, divisor)
        if segundos is not None:
            return segundos
        if nombre == "retry-after" and isinstance(valor, str) and len(valor) <= 128:
            try:
                fecha = parsedate_to_datetime(valor)
                if fecha.tzinfo is not None:
                    return max(0.0, fecha.timestamp() - time())
            except (TypeError, ValueError, OverflowError, OSError):
                pass
    # Groq también indica "Please try again in 2.91s" en rate_limit_exceeded.
    # Extraer solo la duración acotada en RAM; no exponer el mensaje del proveedor.
    mensaje = _detalle(error).get("message")
    if isinstance(mensaje, str):
        pista = re.search(r"\bPlease try again in ((?:\d{1,9}(?:\.\d{1,6})?(?:ms|s|m|h)){1,4})(?=[.\s]|$)",
                          mensaje[:4096], flags=re.IGNORECASE)
        if pista:
            unidades = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0}
            return sum(float(n) * unidades[u] for n, u in re.findall(
                r"(\d+(?:\.\d+)?)(ms|s|m|h)", pista[1].lower()))
    return None


@observar_llamada()
def invocar_modelo(modelo, mensajes, *, config=None, max_reintentos=MAX_REINTENTOS,
                   deadline: float | None = None):
    """Repetir solo invoke, con la misma entrada; propagar el último error real.

    El SDK de producción mantiene max_retries=0. Si la espera indicada supera
    el tope local o el presupuesto del turno, no adelantar la petición: detener.
    """
    for intento in range(MAX_REINTENTOS + 1):
        try:
            return observar_intento(modelo.invoke, mensajes, config=config, intento_ep3=intento + 1)
        except Exception as error:
            detalle = _detalle(error)
            codigo = detalle.get("code") or getattr(error, "code", None) or detalle.get("type")
            if (getattr(error, "status_code", None) != 429
                or codigo not in (None, "rate_limit_exceeded", "rate_limit_error") or intento >= max_reintentos
                or intento >= MAX_REINTENTOS):
                raise
            espera = _espera_indicada(error)
            if espera is None:
                espera = float(2 ** intento)  # Sin pista válida: 1 s, después 2 s.
            if espera > MAX_ESPERA_SEGUNDOS or deadline is not None and monotonic() + espera >= deadline:
                raise
            _LOG.warning("EP2 HTTP 429: reintento del modelo %d/%d en %.3f s.",
                         intento + 1, min(max_reintentos, MAX_REINTENTOS), espera)
            registrar_reintento(error, intento + 1, espera)
            dormir_observado(sleep, espera)
            if deadline is not None and monotonic() >= deadline:
                raise
