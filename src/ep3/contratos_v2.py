"""Extensión v2: v1 conserva sus modelos y documentos sin modificaciones."""
from typing import Literal
from uuid import UUID
import json
from pydantic import Field,model_validator
from src.ep3.contratos import Traza, Evento, Detalles, Contrato

VERSION_BD = 2
Categoria = Literal['interactiva', 'ticket_sla', 'rag_kb', 'impacto', 'nota', 'posponer',
                    'sin_procedimiento', 'reintento', 'seguridad', 'benchmark']

def correlacion_valida(self):
    if self.correlacion=='estable' and (self.sesion_ref is None or self.clave_id is None):
        raise ValueError('La correlación estable necesita referencia y clave identificada.')
    if self.correlacion=='desactivada' and (self.sesion_ref is not None or self.clave_id is not None):
        raise ValueError('La correlación desactivada no admite asociaciones de sesión.')
    return self

class DetallesV2(Detalles):
    llamada_id: UUID | None = None
    solicitud_id_tecnica: UUID | None = None
    frontera: Literal['llm', 'cadena'] | None = None
    clase_error: Literal['limite_temporal', 'autenticacion', 'timeout', 'proveedor', 'validacion', 'interrupcion', 'ejecucion'] | None = None
    tokens_entrada: int | None = Field(default=None, ge=0)
    tokens_salida: int | None = Field(default=None, ge=0)
    origen_tokens: Literal['proveedor', 'no_disponible'] | None = None
    espera_real_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    cpu_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    ram_inicio_bytes: int | None = Field(default=None, ge=0)
    ram_fin_bytes: int | None = Field(default=None, ge=0)
    metodo_ram: Literal['working_set', 'rss_proc', 'no_disponible'] | None = None
    rag_metodo: Literal['identificador', 'semantica'] | None = None
    rag_devueltos: int | None = Field(default=None, ge=0)
    puntaje_maximo: float | None = Field(default=None, ge=0, le=1, allow_inf_nan=False)
    etapa: Literal['recuperar', 'guardar', 'historial'] | None = None
    decision_indice: int | None = Field(default=None, ge=1)
    herramientas_ofrecidas: int | None = Field(default=None, ge=0, le=6)

class TrazaV2(Traza):
    version_esquema: Literal[2] = 2
    sesion_ref: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')
    correlacion: Literal['estable', 'desactivada']
    clave_id: str | None = Field(default=None, pattern=r'^[0-9a-f]{16}$')
    categoria: Categoria = 'interactiva'
    operacion: Literal['consulta', 'confirmacion', 'posponer'] = 'consulta'
    _correlacion_valida=model_validator(mode='after')(correlacion_valida)

class EventoV2(Evento):
    version_esquema: Literal[2] = 2
    sesion_ref: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')
    correlacion: Literal['estable', 'desactivada']
    clave_id: str | None = Field(default=None, pattern=r'^[0-9a-f]{16}$')
    categoria: Categoria = 'interactiva'
    operacion: Literal['consulta', 'confirmacion', 'posponer'] = 'consulta'
    evento: Literal['consulta_inicio', 'consulta_fin', 'herramienta_fin', 'modelo_error',
                    'modelo_reintento', 'modelo_inicio', 'modelo_fin', 'llamada_fin', 'espera_fin',
                    'plan_inicial', 'plan_actualizado', 'plan_final', 'observacion',
                    'rag_fin', 'memoria_fin', 'decision', 'confirmacion_inicio', 'confirmacion_fin', 'posponer']
    componente: Literal['agente', 'herramienta', 'modelo', 'planificacion', 'rag', 'memoria', 'interfaz_humana']
    detalles: DetallesV2 = Field(default_factory=DetallesV2)
    _correlacion_valida=model_validator(mode='after')(correlacion_valida)

def leer_evento(texto: str) -> Evento | EventoV2:
    datos = json.loads(texto)
    modelo = {1: Evento, 2: EventoV2}.get(datos.get('version_esquema'))
    if modelo is None:
        raise ValueError('Versión de evento no soportada.')
    return modelo.model_validate_json(texto)

class Evaluacion(Contrato):
    version_esquema: Literal[2] = 2
    evaluacion_id: UUID
    ejecucion_id: UUID | None = None
    tipo_ejecucion: Literal['real', 'simulada', 'historica']
    caso: Literal['ticket_sla', 'rag_kb', 'impacto', 'nota', 'posponer', 'sin_procedimiento', 'reintento', 'seguridad']
    variante: int = Field(ge=1, le=100)
    metrica: Literal['exactitud_hechos', 'acierto_documental', 'cumplimiento_restricciones', 'consistencia']
    metodo: Literal['referencia_estructurada', 'referencia_documental', 'invariante', 'acuerdo_entre_variantes']
    valor: float = Field(ge=0, le=1, allow_inf_nan=False)
    muestras: int = Field(ge=1)
