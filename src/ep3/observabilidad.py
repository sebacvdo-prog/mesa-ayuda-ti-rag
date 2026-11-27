"""Telemetría local opcional: contexto por consulta, HMAC y cola acotada.

El agente nunca espera una transacción SQLite. Los fallos solo afectan contadores
de telemetría. La correlación se desactiva si no se configura una clave HMAC
estable, que permanece separada de los eventos y permite continuidad entre procesos.
"""

from __future__ import annotations

import atexit
from contextvars import ContextVar
from dataclasses import dataclass,field
from datetime import datetime, timezone
from functools import wraps
import hashlib
import hmac
import json
import os
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Condition, Event, Lock, Thread
from time import perf_counter
from typing import Callable
from uuid import uuid4

from src.ep3.almacenamiento import AlmacenObservabilidad, DIRECTORIO_EP3
from src.ep3.contratos import codigo_seguro
from src.ep3.contratos_v2 import DetallesV2 as Detalles, EventoV2 as Evento, TrazaV2 as Traza
from src.ep3.recursos import muestra
from src.ep3.identidad import leer_clave


class Observabilidad:
    """Recolector explícito. cerrar/flush solo se usan fuera del ciclo del agente."""

    def __init__(self, directorio: Path = DIRECTORIO_EP3, *, tipo_ejecucion='real',
                 clave_sesion: bytes | None = None, capacidad: int = 1024, retencion_dias: int = 30):
        if tipo_ejecucion not in ('real', 'simulada', 'historica'):
            raise ValueError('Tipo de ejecución inválido.')
        if clave_sesion is not None and (type(clave_sesion) is not bytes or len(clave_sesion) < 32):
            raise ValueError('La clave HMAC debe contener al menos 32 bytes.')
        if type(capacidad) is not int or capacidad < 1:
            raise ValueError('La capacidad debe ser positiva.')
        self.directorio = Path(directorio)
        self.tipo_ejecucion = tipo_ejecucion
        self._clave = clave_sesion
        self.retencion_dias = retencion_dias
        self.clave_id = hashlib.sha256(clave_sesion).hexdigest()[:16] if clave_sesion else None
        self._id = uuid4()
        self._cola = Queue(maxsize=capacidad)
        self._condicion = Condition()
        self._detener = Event()
        self._cerrado = False
        self._contadores = dict.fromkeys(('emitidos', 'persistidos', 'descartados', 'pendientes',
                                         'fallos_validacion', 'fallos_almacenamiento',
                                         'fallos_instrumentacion'), 0)
        self._hilo = Thread(target=self._escribir, name='ep3-telemetria', daemon=True)
        self._hilo.start()

    def estadisticas(self) -> dict[str, int]:
        with self._condicion:
            return dict(self._contadores)

    def fallo_instrumentacion(self) -> None:
        with self._condicion:
            self._contadores['fallos_instrumentacion'] += 1

    def iniciar(self, pipeline: str, identidad: tuple[str, ...]) -> _Contexto:
        identidad_bytes = json.dumps((pipeline, *identidad), ensure_ascii=False).encode('utf-8')
        referencia = hmac.new(self._clave, identidad_bytes, hashlib.sha256).hexdigest() if self._clave else None
        return _Contexto(self, Traza(ejecucion_id=uuid4(), sesion_ref=referencia,
                                    tipo_ejecucion=self.tipo_ejecucion, pipeline=pipeline,
                                    correlacion='estable' if self._clave else 'desactivada',
                                    clave_id=self.clave_id, categoria=_CATEGORIA.get(),
                                    inicio_utc=datetime.now(timezone.utc)))

    def registrar(self, datos: dict) -> None:
        with self._condicion:
            self._contadores['emitidos'] += 1
        try:
            evento = Evento.model_validate(datos)
        except Exception:
            with self._condicion:
                self._contadores['fallos_validacion'] += 1
                self._contadores['descartados'] += 1
            return
        with self._condicion:
            if self._cerrado:
                self._contadores['descartados'] += 1
                return
            try:
                self._cola.put_nowait(evento)
                self._contadores['pendientes'] += 1
            except Full:
                self._contadores['descartados'] += 1

    def _escribir(self) -> None:
        almacen = None
        try:
            while not self._detener.is_set() or not self._cola.empty():
                try:
                    eventos = [self._cola.get(timeout=0.05)]
                except Empty:
                    continue
                while len(eventos) < 64:
                    try:
                        eventos.append(self._cola.get_nowait())
                    except Empty:
                        break
                try:
                    if almacen is None:
                        almacen = (AlmacenObservabilidad(self.directorio) if self.retencion_dias == 30 else
                                   AlmacenObservabilidad(self.directorio, retencion_dias=self.retencion_dias))
                    contadores = self.estadisticas()
                    contadores['persistidos'] += len(eventos)
                    contadores['pendientes'] -= len(eventos)
                    almacen.guardar(eventos, self._id, contadores)
                except Exception:
                    with self._condicion:
                        self._contadores['fallos_almacenamiento'] += 1
                        self._contadores['descartados'] += len(eventos)
                else:
                    with self._condicion:
                        self._contadores['persistidos'] += len(eventos)
                finally:
                    with self._condicion:
                        self._contadores['pendientes'] -= len(eventos)
                        self._condicion.notify_all()
                    for _ in eventos:
                        self._cola.task_done()
        finally:
            if almacen is not None:
                try:
                    # Guarda también pérdidas por cola llena ocurridas tras el último lote.
                    almacen.guardar([], self._id, self.estadisticas())
                except Exception:
                    with self._condicion:
                        self._contadores['fallos_almacenamiento'] += 1
                finally:
                    try:
                        almacen.cerrar()
                    except Exception:
                        with self._condicion:
                            self._contadores['fallos_almacenamiento'] += 1

    def flush(self, timeout: float = 2.0) -> bool:
        with self._condicion:
            return self._condicion.wait_for(lambda: self._contadores['pendientes'] == 0, timeout=timeout)

    def cerrar(self, timeout: float = 2.0) -> bool:
        with self._condicion:
            self._cerrado = True
        self._detener.set()
        self._hilo.join(timeout)
        return not self._hilo.is_alive()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.cerrar()


@dataclass
class _Contexto:
    recolector: Observabilidad
    traza: Traza
    secuencia: int = 0
    solicitudes_vistas: set = field(default_factory=set)

    def emitir(self, evento: str, componente: str, estado: str, codigo: str,
               *, duracion_ms: float | None = None, detalles: Detalles | None = None) -> None:
        try:
            self.secuencia += 1
            self.recolector.registrar({**self.traza.model_dump(), 'evento_id': uuid4(),
                'secuencia': self.secuencia, 'fecha_utc': datetime.now(timezone.utc),
                'evento': evento, 'componente': componente, 'estado': estado,
                'codigo': codigo_seguro(codigo), 'duracion_ms': duracion_ms,
                'detalles': (detalles or Detalles()).model_dump()})
        except Exception:
            self.recolector.fallo_instrumentacion()


_ACTUAL: ContextVar[_Contexto | None] = ContextVar('ep3_traza_actual', default=None)
_CATEGORIA = ContextVar('ep3_categoria', default='interactiva')
_INSTANCIAS: dict[tuple[str, str], Observabilidad] = {}
_CERROJO = Lock()
_FALLOS_CONFIGURACION = 0


def desde_entorno() -> Observabilidad | None:
    """Opt-in. No abre archivos, crea hilos ni lee claves cuando está desactivada."""
    global _FALLOS_CONFIGURACION
    if os.getenv('EP3_OBSERVABILIDAD', '0') != '1':
        return None
    try:
        directorio = os.getenv('EP3_DIRECTORIO', str(DIRECTORIO_EP3))
        tipo = os.getenv('EP3_TIPO_EJECUCION', 'real')
        clave = (directorio, tipo)
        with _CERROJO:
            if clave not in _INSTANCIAS or _INSTANCIAS[clave]._cerrado:
                ruta_clave = os.getenv('EP3_HMAC_KEY_FILE')
                secreto = leer_clave(Path(ruta_clave)) if ruta_clave else None
                _INSTANCIAS[clave] = Observabilidad(Path(directorio), tipo_ejecucion=tipo,
                    clave_sesion=secreto, retencion_dias=int(os.getenv('EP3_RETENCION_DIAS', '30')))
                atexit.register(_INSTANCIAS[clave].cerrar)
            return _INSTANCIAS[clave]
    except Exception:
        _FALLOS_CONFIGURACION += 1
        return None


def fallos_configuracion() -> int:
    return _FALLOS_CONFIGURACION


def observar_consulta(pipeline: str, operacion: str = 'consulta'):
    def decorar(funcion):
        @wraps(funcion)
        def responder(self, consulta, *args, **kwargs):
            recolector = self.observabilidad
            if recolector is None:
                return funcion(self, consulta, *args, **kwargs)
            try:
                inicio = perf_counter()
                if pipeline == 'ep2':
                    c = self.servicio.contexto
                    identidad = (c.usuario_id, c.sesion_id, c.perfil)
                else:
                    perfil = args[0] if args else kwargs.get('perfil', 'agente')
                    sesion = args[1] if len(args) > 1 else kwargs.get('session_id', 'default')
                    identidad = (sesion, perfil)
                contexto = recolector.iniciar(pipeline, identidad)
                if operacion != 'consulta':
                    contexto.traza = contexto.traza.model_copy(update={'operacion': operacion})
                recursos_inicio = _recursos_seguros(recolector)
            except Exception:
                recolector.fallo_instrumentacion()
                return funcion(self, consulta, *args, **kwargs)
            token = _ACTUAL.set(contexto)
            contexto.emitir('consulta_inicio' if operacion == 'consulta' else 'confirmacion_inicio',
                            'agente', 'info', 'CONSULTA_INICIO')
            try:
                respuesta = funcion(self, consulta, *args, **kwargs)
            except BaseException:
                try:
                    contexto.emitir('consulta_fin' if operacion == 'consulta' else 'confirmacion_fin', 'agente', 'error', 'ERROR_CONSULTA',
                                    duracion_ms=(perf_counter() - inicio) * 1000)
                except Exception:
                    recolector.fallo_instrumentacion()
                raise
            else:
                try:
                    if pipeline == 'ep2':
                        estado = respuesta.estado
                        codigo = {'ok': 'OK', 'requiere_confirmacion': 'CONFIRMACION_REQUERIDA',
                                  'denegado': 'DENEGADO', 'sin_contexto': 'SIN_CONTEXTO',
                                  'limite': 'LIMITE_EJECUCION', 'error': 'ERROR_EJECUCION'}.get(estado, respuesta.codigo if hasattr(respuesta, 'codigo') else 'OTRO')
                        if operacion == 'confirmacion':
                            codigo = respuesta.codigo
                    else:
                        motivo = respuesta.motivo
                        estado = {'ok': 'ok', 'credenciales': 'denegado',
                                  'fuera_de_alcance': 'denegado', 'sin_contexto': 'sin_contexto'}.get(motivo, 'info')
                        codigo = {'ok': 'OK', 'credenciales': 'CREDENCIALES',
                                  'fuera_de_alcance': 'FUERA_DE_ALCANCE', 'sin_contexto': 'SIN_CONTEXTO'}.get(motivo, 'OTRO')
                    recursos_fin = _recursos_seguros(recolector)
                    detalle = Detalles(cpu_ms=max(0.0, (recursos_fin[0] - recursos_inicio[0]) * 1000)
                                       if recursos_fin[0] is not None and recursos_inicio[0] is not None else None,
                        ram_inicio_bytes=recursos_inicio[1], ram_fin_bytes=recursos_fin[1], metodo_ram=recursos_fin[2])
                    contexto.emitir('consulta_fin' if operacion == 'consulta' else 'confirmacion_fin', 'agente', estado, codigo,
                                    duracion_ms=(perf_counter() - inicio) * 1000, detalles=detalle)
                except Exception:
                    recolector.fallo_instrumentacion()
                return respuesta
            finally:
                _ACTUAL.reset(token)
        return responder
    return decorar


def _recursos_seguros(recolector):
    try:
        return muestra()
    except Exception:
        recolector.fallo_instrumentacion()
        return None, None, 'no_disponible'


def registrar_herramienta(traza) -> None:
    contexto = _ACTUAL.get()
    if contexto is not None:
        try:
            contexto.emitir('herramienta_fin', 'herramienta', traza.estado, traza.codigo,
                            duracion_ms=traza.duracion_ms, detalles=Detalles(herramienta=traza.nombre))
        except Exception:
            contexto.recolector.fallo_instrumentacion()


def registrar_plan(tipo: str, plan) -> None:
    contexto = _ACTUAL.get()
    if tipo == 'confirmacion_humana':
        tipo = 'plan_actualizado'
    if contexto is None or tipo not in ('plan_inicial', 'plan_actualizado', 'plan_final', 'observacion'):
        return
    try:
        if tipo == 'observacion':
            detalles = Detalles()
            codigo = plan.codigo
        else:
            detalles = Detalles(plan_id=plan.id, revision=plan.revision, pasos_total=len(plan.pasos),
                pasos_completados=sum(p.estado == 'completado' for p in plan.pasos),
                pasos_bloqueados=sum(p.estado == 'bloqueado' for p in plan.pasos),
                cambios_total=len(plan.cambios),
                cambio_codigo=codigo_seguro(plan.cambios[-1].codigo) if plan.cambios else None)
            codigo = tipo.upper()
        contexto.emitir(tipo, 'planificacion', 'info', codigo, detalles=detalles)
    except Exception:
        contexto.recolector.fallo_instrumentacion()


def _estado_http(error) -> int | None:
    try:
        valor = getattr(error, 'status_code', None)
    except Exception:
        return None
    return valor if type(valor) is int and 100 <= valor <= 599 else None


def observar_intento(funcion: Callable, *args, intento_ep3: int = 1, **kwargs):
    from src.ep3.instrumentacion import medir_intento
    return medir_intento(funcion, *args, intento_ep3=intento_ep3, **kwargs)


def _observar_intento_v1(funcion: Callable, *args, intento_ep3: int = 1, **kwargs):
    contexto = _ACTUAL.get()
    if contexto is None:
        return funcion(*args, **kwargs)
    try:
        inicio = perf_counter()
    except Exception:
        contexto.recolector.fallo_instrumentacion()
        return funcion(*args, **kwargs)
    try:
        return funcion(*args, **kwargs)
    except BaseException as error:
        try:
            status = _estado_http(error)
            contexto.emitir('modelo_error', 'modelo', 'error', f'HTTP_{status}' if status else 'ERROR_MODELO',
                duracion_ms=(perf_counter() - inicio) * 1000,
                detalles=Detalles(intento=intento_ep3, http_status=status))
        except Exception:
            contexto.recolector.fallo_instrumentacion()
        raise


def registrar_reintento(error, intento: int, espera: float) -> None:
    contexto = _ACTUAL.get()
    if contexto is not None:
        try:
            status = _estado_http(error)
            from src.ep3.instrumentacion import detalle_llamada
            contexto.emitir('modelo_reintento', 'modelo', 'reintentando', f'HTTP_{status}' if status else 'ERROR_MODELO',
                detalles=detalle_llamada(intento=intento, espera_prevista_ms=espera * 1000, http_status=status))
        except Exception:
            contexto.recolector.fallo_instrumentacion()
