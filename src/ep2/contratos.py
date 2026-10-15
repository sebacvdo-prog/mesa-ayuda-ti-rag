"""Contratos de la frontera de herramientas y de la interfaz de confirmación."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


class RespuestaAgenteEP2(Contrato):
    estado: Literal["ok", "requiere_confirmacion", "denegado", "sin_contexto", "limite", "error"]
    texto: str
    herramientas: tuple[TrazaHerramienta, ...] = ()
    fuentes: tuple[str, ...] = ()
    confirmaciones: tuple[SolicitudConfirmacion, ...] = ()
    escrituras_realizadas: Literal[0] = 0
    memoria_estado: Literal["sin_cambios", "actualizada", "no_disponible"] = "sin_cambios"
    aviso_memoria: str = ""
