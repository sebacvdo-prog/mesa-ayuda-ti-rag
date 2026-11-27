"""Lista cerrada de campos técnicos. Nunca admite mensajes ni argumentos libres."""

from __future__ import annotations

from datetime import datetime
import re
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator


VERSION_ESQUEMA = 1
TipoEjecucion = Literal['real', 'simulada', 'historica']
Pipeline = Literal['ep1', 'ep2']
Estado = Literal['ok', 'error', 'denegado', 'sin_contexto', 'limite',
                 'requiere_confirmacion', 'cancelada', 'no_encontrado',
                 'conflicto', 'expirada', 'info', 'reintentando']
Herramienta = Literal['consultar_ticket', 'consultar_sla', 'consultar_activo',
                      'buscar_procedimiento', 'analizar_incidente', 'registrar_nota_ticket']
CODIGOS = frozenset('''
OK OTRO DENEGADO ERROR_CONSULTA ERROR_MODELO CREDENCIALES FUERA_DE_ALCANCE SIN_CONTEXTO
CONSULTA_INICIO PLAN_INICIAL PLAN_ACTUALIZADO PLAN_FINAL OBSERVACION
ACTIVO_CONSULTADO ACTIVO_NO_ENCONTRADO ALMACENAMIENTO_NO_DISPONIBLE
ARGUMENTOS_INVALIDOS AUTORIZACION_NO_RECUPERADA CONFIRMACION_EXPIRADA
CONFIRMACION_NO_VALIDA CONFIRMACION_REQUERIDA CONTENIDO_NO_CONFIRMADO
CONTENIDO_SENSIBLE DEPENDENCIA_BLOQUEADA EJECUCION_INTERRUMPIDA ERROR_EJECUCION
ERROR_HERRAMIENTA ESCALAMIENTO_PROPUESTO FORMATO_INVALIDO IDEMPOTENCIA_CONFLICTO
IMPACTO_REPORTADO INCIDENTE_ANALIZADO LECTURA_INTERRUMPIDA LIMITE_EJECUCION
NOTA_CANCELADA NOTA_ESPERA_VERIFICACIONES NOTA_REGISTRADA NOTA_REUTILIZADA
NOTA_YA_REGISTRADA NOTAS_CONSULTADAS NUEVA_VISTA_PREVIA PASO_ANADIDO PASO_INICIADO
PERMISO_REQUERIDO PLAN_BLOQUEADO PLAN_CREADO PLAN_DEPENDENCIA_PENDIENTE
PLAN_INCOMPLETO PLAN_NO_PREVISTO PLAN_NOTA_NO_SOLICITADA PLAN_PASO_BLOQUEADO
PLAN_PASO_COMPLETADO PLAN_PASO_YA_EJECUTADO PLAN_PRIORIDAD_NO_COINCIDE
PLAN_PRIORIDAD_PENDIENTE PLAN_RECUPERADO PLAN_SOLO_ESTADO PLAN_TICKET_DISTINTO
PRIORIDAD_PROPUESTA PROCEDIMIENTO_RECUPERADO REINTENTO_EXPLICITO
REPLANIFICACION_ERROR REPLANIFICACION_IMPACTO REPLANIFICACION_PRIORIDAD_REGISTRADA
RESPUESTA_FINAL REVALIDAR_IMPACTO SELECCION_AUTONOMA SELECCION_NO_PERMITIDA
SIN_PROCEDIMIENTO SLA_CONSULTADO SLA_NO_ENCONTRADO SLA_VERIFICADO_EN_ANALISIS
TICKET_CONSULTADO TICKET_NO_ENCONTRADO TIEMPO_AGOTADO
'''.split())
ESQUEMA_CODIGO = {'anyOf': [{'type': 'string', 'enum': sorted(CODIGOS)},
                          {'type': 'string', 'pattern': r'^HTTP_[1-5][0-9]{2}$'}]}


def codigo_seguro(valor: object) -> str:
    if type(valor) is str and (valor in CODIGOS or re.fullmatch(r'HTTP_[1-5][0-9]{2}', valor)):
        return valor
    return 'OTRO'


class Contrato(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True, strict=True)


class Contadores(Contrato):
    emitidos: int = Field(ge=0)
    persistidos: int = Field(ge=0)
    descartados: int = Field(ge=0)
    pendientes: int = Field(ge=0)
    fallos_validacion: int = Field(ge=0)
    fallos_almacenamiento: int = Field(ge=0)
    fallos_instrumentacion: int = Field(ge=0)


class Traza(Contrato):
    version_esquema: Literal[1] = VERSION_ESQUEMA
    ejecucion_id: UUID
    sesion_ref: str = Field(pattern=r'^[0-9a-f]{64}$')
    tipo_ejecucion: TipoEjecucion
    pipeline: Pipeline
    inicio_utc: AwareDatetime

    @field_validator('inicio_utc')
    @classmethod
    def exigir_utc(cls, valor: datetime) -> datetime:
        if valor.utcoffset().total_seconds() != 0:
            raise ValueError('La fecha debe estar expresada en UTC.')
        return valor


class Detalles(Contrato):
    herramienta: Herramienta | None = None
    intento: int | None = Field(default=None, ge=1)
    espera_prevista_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    http_status: int | None = Field(default=None, ge=100, le=599)
    plan_id: UUID | None = None
    revision: int | None = Field(default=None, ge=1)
    pasos_total: int | None = Field(default=None, ge=0, le=12)
    pasos_completados: int | None = Field(default=None, ge=0, le=12)
    pasos_bloqueados: int | None = Field(default=None, ge=0, le=12)
    cambios_total: int | None = Field(default=None, ge=0, le=30)
    cambio_codigo: str | None = Field(default=None, json_schema_extra={
        'anyOf': [*ESQUEMA_CODIGO['anyOf'], {'type': 'null'}],
    })

    @field_validator('cambio_codigo')
    @classmethod
    def validar_codigo(cls, valor: str | None) -> str | None:
        if valor is not None and codigo_seguro(valor) != valor:
            raise ValueError('Código fuera de la lista permitida.')
        return valor


class Evento(Traza):
    evento_id: UUID
    secuencia: int = Field(ge=1)
    fecha_utc: AwareDatetime
    evento: Literal['consulta_inicio', 'consulta_fin', 'herramienta_fin',
                    'modelo_error', 'modelo_reintento', 'plan_inicial',
                    'plan_actualizado', 'plan_final', 'observacion']
    componente: Literal['agente', 'herramienta', 'modelo', 'planificacion']
    duracion_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    estado: Estado
    codigo: str = Field(json_schema_extra=ESQUEMA_CODIGO)
    detalles: Detalles = Field(default_factory=Detalles)

    _utc = field_validator('fecha_utc')(Traza.exigir_utc.__func__)

    @field_validator('codigo')
    @classmethod
    def validar_codigo(cls, valor: str) -> str:
        if codigo_seguro(valor) != valor:
            raise ValueError('Código fuera de la lista permitida.')
        return valor
