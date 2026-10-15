"""Contratos de la frontera de herramientas y de la interfaz de confirmación."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Contrato(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class ContextoEjecucion(Contrato):
    """Lo establece la aplicación de confianza, nunca los argumentos del LLM.

    Usar identificadores internos opacos, no correos, RUT ni credenciales.
    El perfil es una autorización de la aplicación, no una autenticación.
    """

    usuario_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    sesion_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    perfil: Literal["agente", "usuario_final"]


class ConsultaTicket(Contrato):
    ticket_id: str = Field(pattern=r"^(INC|REQ)-\d{4}-\d{3,5}$")

    @field_validator("ticket_id", mode="before")
    @classmethod
    def normalizar_ticket(cls, valor: Any) -> Any:
        return valor.strip().upper() if isinstance(valor, str) else valor


class ConsultaSLA(Contrato):
    prioridad: Literal["P1", "P2", "P3", "P4"]

    @field_validator("prioridad", mode="before")
    @classmethod
    def normalizar_prioridad(cls, valor: Any) -> Any:
        return valor.strip().upper() if isinstance(valor, str) else valor


class RegistrarNota(ConsultaTicket):
    """Propuesta de escritura. No acepta perfil, usuario ni un flag confirmado."""

    id_operacion: UUID
    texto: str = Field(min_length=1, max_length=2000)


class ProponerNota(ConsultaTicket):
    """Entrada del LLM: la aplicación asigna el id de operación."""

    texto: str = Field(min_length=1, max_length=2000)


class ConsultaProcedimiento(Contrato):
    consulta: str = Field(min_length=1, max_length=1000)
    fuente: Literal["automatica", "interna", "externa", "mixta"] = "automatica"


class DecisionConfirmacion(Contrato):
    """Entrada exclusiva de la interfaz humana; no registrar como herramienta."""

    solicitud_id: UUID
    huella: str = Field(pattern=r"^[0-9a-f]{64}$")
    decision: Literal["confirmar", "cancelar"]


class SolicitudConfirmacion(Contrato):
    solicitud_id: UUID
    id_operacion: UUID
    ticket_id: str
    texto: str
    huella: str
    expira_en: datetime
    mensaje: str


class ResultadoHerramienta(Contrato):
    estado: Literal[
        "ok", "requiere_confirmacion", "cancelada", "denegado",
        "no_encontrado", "conflicto", "expirada", "error",
    ]
    codigo: str
    mensaje: str
    datos: dict[str, Any] = Field(default_factory=dict)
    procedencia: tuple[str, ...] = ()


class TrazaHerramienta(Contrato):
    nombre: str
    estado: str
    codigo: str
    duracion_ms: float = 0


NombreHerramienta = Literal["consultar_ticket", "consultar_sla", "consultar_activo",
                            "buscar_procedimiento", "analizar_incidente", "registrar_nota_ticket"]
EstadoPaso = Literal["pendiente", "en_ejecucion", "completado", "bloqueado", "cancelado"]


class PasoPlan(Contrato):
    id: str = Field(pattern=r"^p\d{1,3}$")
    herramienta: NombreHerramienta
    prioridad: int = Field(ge=1, le=5)
    dependencias: tuple[str, ...] = ()
    estado: EstadoPaso = "pendiente"
    motivo: str = Field(max_length=240)
    codigo: str = "PENDIENTE"
    actualizado_en: datetime
    intentos: int = Field(default=0, ge=0, le=2)


class ObservacionPlan(Contrato):
    fecha: datetime
    origen: Literal["herramienta", "usuario", "sistema", "interfaz_humana"]
    codigo: str = Field(max_length=80)
    resumen: str = Field(max_length=240)
    procedencia: tuple[str, ...] = Field(default=(), max_length=8)


class CambioPlan(Contrato):
    fecha: datetime
    revision: int
    codigo: str
    motivo: str = Field(max_length=240)
    paso_id: str | None = None


class PlanEjecucion(Contrato):
    id: UUID
    objetivo: str = Field(min_length=1, max_length=384)
    revision: int = Field(default=1, ge=1)
    creado_en: datetime
    actualizado_en: datetime
    ticket_id: str | None = None
    pasos: tuple[PasoPlan, ...] = Field(min_length=1, max_length=12)
    observaciones: tuple[ObservacionPlan, ...] = Field(default=(), max_length=20)
    cambios: tuple[CambioPlan, ...] = Field(default=(), max_length=30)
    impacto_reportado: Literal["no_informado", "multiples_usuarios"] = "no_informado"
    impacto_verificado: Literal[False] = False
    prioridad_registrada: Literal["P1", "P2", "P3", "P4"] | None = None
    prioridad_propuesta: Literal["P1", "P2", "P3", "P4"] | None = None
    criterio_prioridad: str = Field(default="Sin propuesta; consultar evidencia.", max_length=240)

    @model_validator(mode="after")
    def validar_grafo(self) -> PlanEjecucion:
        pasos = {p.id: p for p in self.pasos}
        if len(pasos) != len(self.pasos):
            raise ValueError("Los identificadores de pasos deben ser únicos.")
        visitados, activos = set(), set()
        def visitar(id_paso):
            if id_paso in activos:
                raise ValueError("El plan contiene dependencias cíclicas.")
            if id_paso in visitados:
                return
            activos.add(id_paso)
            for dependencia in pasos[id_paso].dependencias:
                if dependencia not in pasos:
                    raise ValueError("La dependencia no existe.")
                visitar(dependencia)
            activos.remove(id_paso)
            visitados.add(id_paso)
        for p in self.pasos:
            visitar(p.id)
            if p.estado in ("en_ejecucion", "completado") and any(
                pasos[d].estado != "completado" for d in p.dependencias
            ):
                raise ValueError("Un paso activo/completado requiere dependencias completadas.")
        return self


class RespuestaAgenteEP2(Contrato):
    estado: Literal["ok", "requiere_confirmacion", "denegado", "sin_contexto", "limite", "error"]
    texto: str
    herramientas: tuple[TrazaHerramienta, ...] = ()
    fuentes: tuple[str, ...] = ()
    confirmaciones: tuple[SolicitudConfirmacion, ...] = ()
    escrituras_realizadas: Literal[0] = 0
    memoria_estado: Literal["sin_cambios", "actualizada", "no_disponible"] = "sin_cambios"
    aviso_memoria: str = ""
    plan_inicial: PlanEjecucion | None = None
    plan_final: PlanEjecucion | None = None
