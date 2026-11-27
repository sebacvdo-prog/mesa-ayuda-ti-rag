"""Observadores v2: no despachan herramientas ni interpretan autorizaciones."""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from time import perf_counter
from uuid import uuid4
import re
from langchain_core.callbacks import BaseCallbackHandler
from src.ep3 import observabilidad as obs
from src.ep3.contratos_v2 import DetallesV2 as Detalles

_LLAMADA = ContextVar('ep3_llamada', default=None)
_ETAPAS = ContextVar('ep3_etapas', default=frozenset())

def _fallo(c):
    c.recolector.fallo_instrumentacion()

def clase_error(error):
    status = obs._estado_http(error)
    # HTTP 429 también puede representar cuota permanente; no inferir duración.
    if status == 429: return 'proveedor'
    if status in (401, 403): return 'autenticacion'
    if status: return 'proveedor'
    if isinstance(error, (KeyboardInterrupt, SystemExit)): return 'interrupcion'
    if isinstance(error, TimeoutError) or type(error).__name__ in ('TimeoutException', 'APITimeoutError', 'ReadTimeout', 'ConnectTimeout'): return 'timeout'
    if isinstance(error, ValueError): return 'validacion'
    return 'ejecucion'

def tokens(respuesta):
    uso = getattr(respuesta, 'usage_metadata', None)
    if not isinstance(uso, dict):
        meta = getattr(respuesta, 'response_metadata', None)
        uso = meta.get('token_usage') if isinstance(meta, dict) else None
    uso = uso if isinstance(uso, dict) else {}
    def entero(*nombres):
        return next((uso[n] for n in nombres if type(uso.get(n)) is int and uso[n] >= 0), None)
    a, b = entero('input_tokens', 'prompt_tokens'), entero('output_tokens', 'completion_tokens')
    return dict(tokens_entrada=a, tokens_salida=b, origen_tokens='proveedor' if a is not None or b is not None else 'no_disponible')

def detalle_llamada(**kw):
    grupo = _LLAMADA.get()
    return Detalles(llamada_id=grupo[0] if grupo else None, frontera=grupo[1] if grupo else 'cadena', **kw)

def observar_llamada(frontera='llm', condicion=None):
    def decorar(f):
        @wraps(f)
        def ejecutar(*args, **kwargs):
            c = obs._ACTUAL.get()
            if c is None or condicion and not kwargs.get(condicion):
                return f(*args, **kwargs)
            try:
                identificador = uuid4()
                inicio, estado, codigo = perf_counter(), 'ok', 'OK'
                token = _LLAMADA.set((identificador, frontera))
            except Exception:
                _fallo(c)
                return f(*args,**kwargs)
            try:
                return f(*args, **kwargs)
            except BaseException as error:
                estado, codigo = 'error', f'HTTP_{obs._estado_http(error)}' if obs._estado_http(error) else 'ERROR_MODELO'
                raise
            finally:
                try:
                    c.emitir('llamada_fin', 'modelo', estado, codigo, duracion_ms=(perf_counter()-inicio)*1000,
                             detalles=detalle_llamada())
                except Exception: _fallo(c)
                _LLAMADA.reset(token)
        return ejecutar
    return decorar

def medir_intento(f, *args, intento_ep3=1, **kwargs):
    c = obs._ACTUAL.get()
    if c is None: return f(*args, **kwargs)
    try:
        inicio = perf_counter()
        grupo = _LLAMADA.get()
        es_llm = grupo is not None and grupo[1] == 'llm'
        solicitud = uuid4() if es_llm else None
        if es_llm:
            c.emitir('modelo_inicio', 'modelo', 'info', 'OK', detalles=detalle_llamada(
                solicitud_id_tecnica=solicitud, intento=intento_ep3))
    except Exception:
        _fallo(c)
        return f(*args, **kwargs)
    try:
        salida = f(*args, **kwargs)
    except BaseException as error:
        try:
            status = obs._estado_http(error)
            c.emitir('modelo_error', 'modelo', 'error', f'HTTP_{status}' if status else 'ERROR_MODELO',
                     duracion_ms=(perf_counter()-inicio)*1000,
                     detalles=detalle_llamada(solicitud_id_tecnica=solicitud, intento=intento_ep3,
                                             http_status=status, clase_error=clase_error(error)))
        except Exception: _fallo(c)
        raise
    else:
        if es_llm:
            try:
                c.emitir('modelo_fin', 'modelo', 'ok', 'OK', duracion_ms=(perf_counter()-inicio)*1000,
                         detalles=detalle_llamada(solicitud_id_tecnica=solicitud, intento=intento_ep3, **tokens(salida)))
            except Exception: _fallo(c)
        return salida

def dormir_observado(dormir, segundos):
    c = obs._ACTUAL.get()
    if c is None: return dormir(segundos)
    try: inicio = perf_counter()
    except Exception:
        _fallo(c)
        return dormir(segundos)
    estado = 'ok'
    try:
        return dormir(segundos)
    except BaseException:
        estado = 'error'
        raise
    finally:
        try:
            c.emitir('espera_fin', 'modelo', estado, 'OK' if estado == 'ok' else 'ERROR_MODELO',
                     detalles=detalle_llamada(espera_prevista_ms=segundos*1000,
                                             espera_real_ms=(perf_counter()-inicio)*1000))
        except Exception: _fallo(c)

def observar_etapa(componente, etapa=None):
    def decorar(f):
        @wraps(f)
        def ejecutar(self, *args, **kwargs):
            c = obs._ACTUAL.get()
            if c is None or componente in _ETAPAS.get(): return f(self, *args, **kwargs)
            try:
                inicio, estado, salida = perf_counter(), 'ok', None
                token = _ETAPAS.set(_ETAPAS.get() | {componente})
            except Exception:
                _fallo(c)
                return f(self,*args,**kwargs)
            try:
                salida = f(self, *args, **kwargs)
                return salida
            except BaseException:
                estado = 'error'
                raise
            finally:
                try:
                    if componente == 'rag':
                        consulta = args[0] if args else kwargs.get('consulta', '')
                        identidad = f.__name__ == 'buscar_procedimiento' and isinstance(consulta,str) and re.search(r'\bKB-[A-Z]{2,12}-\d{2,4}\b',consulta,re.I)
                        puntajes = [r.puntaje for r in salida or [] if getattr(r,'puntaje',None) is not None]
                        detalle = Detalles(rag_metodo='identificador' if identidad else 'semantica',
                                          rag_devueltos=len(salida) if salida is not None else None,
                                          puntaje_maximo=max(puntajes) if puntajes else None)
                    else: detalle = Detalles(etapa=etapa)
                    c.emitir(componente+'_fin', componente, estado, 'OK' if estado=='ok' else 'ERROR_EJECUCION',
                             duracion_ms=(perf_counter()-inicio)*1000, detalles=detalle)
                except Exception: _fallo(c)
                _ETAPAS.reset(token)
        return ejecutar
    return decorar

def registrar_decision(indice, ofrecidas):
    c = obs._ACTUAL.get()
    if c is not None:
        try:
            c.emitir('decision','planificacion','info','OK',
                     detalles=Detalles(decision_indice=indice,herramientas_ofrecidas=len(ofrecidas)))
        except Exception: _fallo(c)

@contextmanager
def categoria(valor):
    token = obs._CATEGORIA.set(valor)
    try: yield
    finally: obs._CATEGORIA.reset(token)

class MedidorLLM(BaseCallbackHandler):
    """Solo run_id, reloj y usage; nunca conserva prompts, mensajes ni excepciones."""
    def __init__(self):
        self.activos = {}
    def on_chat_model_start(self, serialized, messages, *, run_id, **kwargs):
        c = obs._ACTUAL.get()
        if c is None: return
        try:
            if run_id in c.solicitudes_vistas: return
            c.solicitudes_vistas.add(run_id)
            grupo = _LLAMADA.get()
            self.activos[run_id] = (c, perf_counter(), grupo[0] if grupo else run_id)
            c.emitir('modelo_inicio','modelo','info','OK',detalles=Detalles(
                frontera='llm',llamada_id=self.activos[run_id][2],solicitud_id_tecnica=run_id))
        except Exception: _fallo(c)
    def on_llm_end(self, response, *, run_id, **kwargs):
        dato = self.activos.pop(run_id, None)
        if dato is None: return
        c, inicio, grupo = dato
        try:
            mensaje = response.generations[0][0].message
            c.emitir('modelo_fin','modelo','ok','OK',duracion_ms=(perf_counter()-inicio)*1000,
                     detalles=Detalles(frontera='llm',llamada_id=grupo,solicitud_id_tecnica=run_id,**tokens(mensaje)))
        except Exception: _fallo(c)
    def on_llm_error(self, error, *, run_id, **kwargs):
        dato = self.activos.pop(run_id, None)
        if dato is None: return
        c, inicio, grupo = dato
        try:
            status = obs._estado_http(error)
            c.emitir('modelo_error','modelo','error',f'HTTP_{status}' if status else 'ERROR_MODELO',
                duracion_ms=(perf_counter()-inicio)*1000,detalles=Detalles(frontera='llm',llamada_id=grupo,
                solicitud_id_tecnica=run_id,http_status=status,clase_error=clase_error(error)))
        except Exception: _fallo(c)

def configurar_callbacks(config=None):
    config = config if config is not None else {}
    if obs._ACTUAL.get() is None: return config
    return {**config,'callbacks':[*config.get('callbacks',[]),MedidorLLM()]}

def kwargs_callbacks():
    return {'config': configurar_callbacks()} if obs._ACTUAL.get() is not None else {}

def registrar_posponer(agente):
    r = getattr(agente,'observabilidad',None)
    if r is None: return
    try:
        c = agente.servicio.contexto
        ctx = r.iniciar('ep2',(c.usuario_id,c.sesion_id,c.perfil))
        ctx.traza = ctx.traza.model_copy(update={'operacion':'posponer','categoria':'posponer'})
        ctx.emitir('posponer','interfaz_humana','requiere_confirmacion','CONFIRMACION_REQUERIDA')
    except Exception: r.fallo_instrumentacion()
