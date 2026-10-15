"""Servicios de herramientas EP2; no contienen un agente ni realizan llamadas LLM."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Callable
from uuid import UUID, uuid4

from src import guardrails
from src.ep2.almacenamiento import AlmacenEP2, ConflictoIdempotencia
from src.ep2.contratos import (
    ConsultaProcedimiento, ConsultaSLA, ConsultaTicket, ContextoEjecucion, DecisionConfirmacion,
    RegistrarNota, ResultadoHerramienta, SolicitudConfirmacion,
)
from src.retriever import ConectorITSM, RecuperadorVectorial

_CREDENCIAL = re.compile(
    r"\b(?:password|contrase[ñn]a|api[_ -]?key|token|pin|secret)\s*(?:[:=]|\bes\b)\s*\S+"
    r"|\b(?:gsk_|sk-|AIza|lsv2_)[A-Za-z0-9_-]{8,}", re.IGNORECASE,
)


@dataclass(frozen=True)
class _Pendiente:
    contexto: ContextoEjecucion
    solicitud: SolicitudConfirmacion


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def contiene_credenciales(texto: str) -> bool:
    return bool(_CREDENCIAL.search(texto))


class HerramientasEP2:
    """El contexto se fija al construir el servicio desde una interfaz confiable.

    preparar_nota es la operación expuesta al agente EP2. confirmar_nota
    es una API exclusiva de la interfaz humana: NUNCA exponerla como herramienta
    ni permitir que el LLM construya ContextoEjecucion o DecisionConfirmacion.
    Las solicitudes pendientes viven en RAM en esta etapa y caducan al reiniciar.
    """

    def __init__(
        self, contexto: ContextoEjecucion, almacen: AlmacenEP2,
        conector: ConectorITSM | None = None, *, reloj: Callable[[], datetime] = _ahora,
        vigencia_confirmacion: timedelta = timedelta(minutes=5),
    ) -> None:
        if vigencia_confirmacion <= timedelta(0):
            raise ValueError("La vigencia de confirmación debe ser positiva.")
        self._contexto = ContextoEjecucion.model_validate(contexto)
        self._almacen = almacen
        self._conector = conector or ConectorITSM()
        self._reloj = reloj
        self._vigencia = vigencia_confirmacion
        self._pendientes: dict[UUID, _Pendiente] = {}
        self._cerrojo = RLock()

    @property
    def contexto(self) -> ContextoEjecucion:
        return self._contexto

    @property
    def almacen(self) -> AlmacenEP2:
        """Almacenamiento de la aplicación; nunca se expone como herramienta."""
        return self._almacen

    def descartar_confirmaciones(self) -> None:
        """Invalida vistas previas en RAM ante nuevo plan/condiciones/contenido.

        No borra notas ni auditoría. Solo la aplicación, nunca el LLM, invoca
        esta frontera antes de reemplazar una propuesta o replanificar.
        """
        with self._cerrojo:
            self._pendientes.clear()

    def _puede_operar_ticket(self) -> bool:
        return self._contexto.perfil == "agente"

    @staticmethod
    def _denegado() -> ResultadoHerramienta:
        return ResultadoHerramienta(
            estado="denegado", codigo="PERMISO_REQUERIDO",
            mensaje="Esta operación requiere el perfil agente de la aplicación.",
        )

    @staticmethod
    def _error_almacenamiento() -> ResultadoHerramienta:
        return ResultadoHerramienta(
            estado="error", codigo="ALMACENAMIENTO_NO_DISPONIBLE",
            mensaje="No se pudo completar la operación. No se registró una nota nueva.",
        )

    @staticmethod
    def _nota_registrada(nota: dict, reutilizada: bool) -> ResultadoHerramienta:
        return ResultadoHerramienta(
            estado="ok", codigo="NOTA_REUTILIZADA" if reutilizada else "NOTA_REGISTRADA",
            mensaje="Nota previamente confirmada recuperada." if reutilizada else "Nota confirmada y registrada en EP2.",
            datos=nota, procedencia=(f"ep2:nota:{nota['id']}",),
        )

    def consultar_ticket(self, entrada: ConsultaTicket) -> ResultadoHerramienta:
        entrada = ConsultaTicket.model_validate(entrada)
        if not self._puede_operar_ticket():
            return self._denegado()
        try:
            ticket = self._conector.estado_de_ticket(entrada.ticket_id)
        except sqlite3.Error:
            return self._error_almacenamiento()
        if ticket is None:
            return ResultadoHerramienta(estado="no_encontrado", codigo="TICKET_NO_ENCONTRADO",
                                        mensaje="El ticket no existe o el ITSM no está disponible.")
        # Se minimizan datos: no devolver nombres, RUT, contactos ni descripciones libres.
        datos = {k: ticket[k] for k in
                 ("id", "estado", "prioridad", "categoria", "nivel_atencion", "fecha_apertura")}
        return ResultadoHerramienta(estado="ok", codigo="TICKET_CONSULTADO",
                                    mensaje="Ticket consultado en modo solo lectura.", datos=datos,
                                    procedencia=(f"itsm:ticket:{entrada.ticket_id}",))

    def consultar_sla(self, entrada: ConsultaSLA) -> ResultadoHerramienta:
        entrada = ConsultaSLA.model_validate(entrada)
        try:
            sla = self._conector.sla_de_prioridad(entrada.prioridad)
        except sqlite3.Error:
            return self._error_almacenamiento()
        if sla is None:
            return ResultadoHerramienta(estado="no_encontrado", codigo="SLA_NO_ENCONTRADO",
                                        mensaje="No se encontró el SLA solicitado.")
        return ResultadoHerramienta(estado="ok", codigo="SLA_CONSULTADO",
                                    mensaje="SLA consultado en modo solo lectura.", datos=sla,
                                    procedencia=(f"itsm:sla:{entrada.prioridad}",))

    def consultar_activo(self, entrada: ConsultaTicket) -> ResultadoHerramienta:
        entrada = ConsultaTicket.model_validate(entrada)
        if not self._puede_operar_ticket():
            return self._denegado()
        try:
            ticket = self._conector.estado_de_ticket(entrada.ticket_id)
            filas = self._conector._consultar(
                "SELECT id, tipo, marca_modelo, sucursal, estado FROM activos_cmdb WHERE id = ?",
                (ticket["activo_id"],),
            ) if ticket and ticket.get("activo_id") else []
        except sqlite3.Error:
            return self._error_almacenamiento()
        if not filas:
            return ResultadoHerramienta(estado="no_encontrado", codigo="ACTIVO_NO_ENCONTRADO",
                                        mensaje="No hay activo disponible asociado a este ticket.")
        return ResultadoHerramienta(estado="ok", codigo="ACTIVO_CONSULTADO",
                                    mensaje="Activo consultado sin exponer IP, hostname ni titular.",
                                    datos=filas[0], procedencia=(f"itsm:activo:{filas[0]['id']}",))

    def buscar_procedimiento(
        self, entrada: ConsultaProcedimiento, recuperador: RecuperadorVectorial,
    ) -> ResultadoHerramienta:
        entrada = ConsultaProcedimiento.model_validate(entrada)
        clasificacion = None if entrada.fuente == "automatica" else entrada.fuente
        fragmentos = recuperador.buscar(
            entrada.consulta, perfil=self._contexto.perfil, clasificacion=clasificacion,
        )
        if not fragmentos:
            return ResultadoHerramienta(estado="no_encontrado", codigo="SIN_PROCEDIMIENTO",
                                        mensaje="No se recuperó un procedimiento con el umbral vigente.")
        datos = [{"documento": f.nombre_documento, "titulo": f.titulo,
                  "fecha": str(f.fecha_vigencia), "puntaje": f.puntaje,
                  "texto": guardrails.enmascarar_texto(f.documento.page_content)} for f in fragmentos]
        return ResultadoHerramienta(estado="ok", codigo="PROCEDIMIENTO_RECUPERADO",
                                    mensaje="Fragmentos recuperados con los permisos y umbral vigentes.",
                                    datos={"fragmentos": datos},
                                    procedencia=tuple(dict.fromkeys(f"corpus:{f.nombre_documento}" for f in fragmentos)))

    def analizar_incidente(self, entrada: ConsultaTicket) -> ResultadoHerramienta:
        """Triage acotado sobre hechos del ITSM; no diagnostica infraestructura.

        La regla distingue casos resueltos, seguimiento en Nivel 2 y necesidad
        de consultar un procedimiento. No inventa impacto ni modifica prioridad.
        """
        entrada = ConsultaTicket.model_validate(entrada)
        ticket = self.consultar_ticket(entrada)
        if ticket.estado != "ok":
            return ticket
        sla = self.consultar_sla(ConsultaSLA(prioridad=ticket.datos["prioridad"]))
        if sla.estado != "ok":
            return sla
        estado = ticket.datos["estado"]
        nivel = ticket.datos["nivel_atencion"]
        if estado == "resuelto":
            decision = "caso_resuelto"
        elif estado == "escalado" or nivel >= 2:
            decision = "seguimiento_nivel_2"
        else:
            decision = "consultar_procedimiento"
        return ResultadoHerramienta(
            estado="ok", codigo="INCIDENTE_ANALIZADO", mensaje="Triage basado en hechos del ITSM.",
            datos={"ticket_id": entrada.ticket_id, "prioridad_registrada": ticket.datos["prioridad"],
                   "estado_registrado": estado, "nivel_atencion": nivel, "decision": decision,
                   "criterio": f"Estado registrado {estado}; nivel de atención {nivel}.",
                   "sla": sla.datos, "diagnostico_confirmado": False,
                   "version_regla": "triage_ep2_v1"},
            procedencia=(*ticket.procedencia, *sla.procedencia),
        )

    def consultar_notas(self, entrada: ConsultaTicket) -> ResultadoHerramienta:
        entrada = ConsultaTicket.model_validate(entrada)
        if not self._puede_operar_ticket():
            return self._denegado()
        try:
            notas = self._almacen.listar_notas(self._contexto, entrada.ticket_id)
        except (sqlite3.Error, ValueError):
            return self._error_almacenamiento()
        return ResultadoHerramienta(estado="ok", codigo="NOTAS_CONSULTADAS",
                                    mensaje="Notas de este usuario y sesión.", datos={"notas": notas},
                                    procedencia=("ep2:notas_confirmadas",))

    def preparar_nota(self, entrada: RegistrarNota) -> ResultadoHerramienta:
        with self._cerrojo:
            return self._preparar_nota(entrada)

    def _preparar_nota(self, entrada: RegistrarNota) -> ResultadoHerramienta:
        entrada = RegistrarNota.model_validate(entrada)
        if not self._puede_operar_ticket():
            return self._denegado()
        if contiene_credenciales(entrada.texto):
            return ResultadoHerramienta(estado="denegado", codigo="CONTENIDO_SENSIBLE",
                                        mensaje="Quitá credenciales o secretos antes de proponer la nota.")
        try:
            ticket = self._conector.estado_de_ticket(entrada.ticket_id)
        except sqlite3.Error:
            return self._error_almacenamiento()
        if ticket is None:
            return ResultadoHerramienta(estado="no_encontrado", codigo="TICKET_NO_ENCONTRADO",
                                        mensaje="No se puede anotar un ticket inexistente o no disponible.")
        texto = guardrails.enmascarar_texto(entrada.texto)
        contenido = json.dumps({"usuario_id": self._contexto.usuario_id,
                                "sesion_id": self._contexto.sesion_id,
                                "ticket_id": entrada.ticket_id, "texto": texto}, sort_keys=True)
        huella = hashlib.sha256(contenido.encode("utf-8")).hexdigest()
        try:
            anterior = self._almacen.buscar_operacion(self._contexto, str(entrada.id_operacion))
        except (sqlite3.Error, ValueError):
            return self._error_almacenamiento()
        if anterior:
            if anterior["huella"] != huella:
                return ResultadoHerramienta(estado="conflicto", codigo="IDEMPOTENCIA_CONFLICTO",
                                            mensaje="El id de operación ya corresponde a otra nota.")
            return self._nota_registrada(anterior, True)
        ahora = self._reloj()
        # Evita acumular solicitudes vencidas; nunca se almacena el texto original.
        self._pendientes = {k: v for k, v in self._pendientes.items() if v.solicitud.expira_en > ahora}
        solicitud = SolicitudConfirmacion(
            solicitud_id=uuid4(), id_operacion=entrada.id_operacion,
            ticket_id=entrada.ticket_id, texto=texto, huella=huella,
            expira_en=ahora + self._vigencia,
            mensaje=f"¿Confirmas registrar esta nota en el simulador EP2 para {entrada.ticket_id}?",
        )
        self._pendientes[solicitud.solicitud_id] = _Pendiente(self._contexto, solicitud)
        return ResultadoHerramienta(estado="requiere_confirmacion", codigo="CONFIRMACION_REQUERIDA",
                                    mensaje=solicitud.mensaje, datos=solicitud.model_dump(mode="json"))

    def confirmar_nota(self, decision: DecisionConfirmacion) -> ResultadoHerramienta:
        """Solo la interfaz humana puede invocar esta API tras un sí/no explícito."""
        with self._cerrojo:
            return self._confirmar_nota(decision)

    def _confirmar_nota(self, decision: DecisionConfirmacion) -> ResultadoHerramienta:
        decision = DecisionConfirmacion.model_validate(decision)
        if not self._puede_operar_ticket():
            return self._denegado()
        pendiente = self._pendientes.get(decision.solicitud_id)
        if pendiente is None or pendiente.contexto != self._contexto:
            return ResultadoHerramienta(estado="denegado", codigo="CONFIRMACION_NO_VALIDA",
                                        mensaje="La confirmación no pertenece a esta solicitud, usuario y sesión.")
        solicitud = pendiente.solicitud
        if decision.huella != solicitud.huella:
            return ResultadoHerramienta(estado="denegado", codigo="CONTENIDO_NO_CONFIRMADO",
                                        mensaje="La confirmación no coincide con la vista previa solicitada.")
        try:
            anterior = self._almacen.buscar_operacion(self._contexto, str(solicitud.id_operacion))
        except (sqlite3.Error, ValueError):
            return self._error_almacenamiento()
        if anterior:
            if anterior["huella"] != solicitud.huella:
                return ResultadoHerramienta(estado="conflicto", codigo="IDEMPOTENCIA_CONFLICTO",
                                            mensaje="La operación ya corresponde a otra nota.")
            if decision.decision == "cancelar":
                return ResultadoHerramienta(estado="conflicto", codigo="NOTA_YA_REGISTRADA",
                                            mensaje="La nota ya fue registrada; cancelarla ahora no la revierte.")
            return self._nota_registrada(anterior, True)
        if decision.decision == "cancelar":
            del self._pendientes[decision.solicitud_id]
            return ResultadoHerramienta(estado="cancelada", codigo="NOTA_CANCELADA",
                                        mensaje="Se canceló la solicitud; no se registró la nota.")
        ahora = self._reloj()
        if solicitud.expira_en <= ahora:
            del self._pendientes[decision.solicitud_id]
            return ResultadoHerramienta(estado="expirada", codigo="CONFIRMACION_EXPIRADA",
                                        mensaje="La vista previa expiró. Solicitá una nueva confirmación.")
        try:
            ticket = self._conector.estado_de_ticket(solicitud.ticket_id)
        except sqlite3.Error:
            return self._error_almacenamiento()
        if ticket is None:
            return ResultadoHerramienta(estado="no_encontrado", codigo="TICKET_NO_ENCONTRADO",
                                        mensaje="El ticket dejó de estar disponible; no se registró la nota.")
        try:
            nota, reutilizada = self._almacen._registrar_nota_confirmada(
                self._contexto, id_operacion=str(solicitud.id_operacion),
                solicitud_id=str(solicitud.solicitud_id), ticket_id=solicitud.ticket_id,
                texto=solicitud.texto, huella=solicitud.huella, fecha=ahora.isoformat(),
            )
        except ConflictoIdempotencia:
            return ResultadoHerramienta(estado="conflicto", codigo="IDEMPOTENCIA_CONFLICTO",
                                        mensaje="La operación ya fue confirmada con otro contenido.")
        except (sqlite3.Error, ValueError):
            return self._error_almacenamiento()
        return self._nota_registrada(nota, reutilizada)
