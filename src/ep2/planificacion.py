"""Planificador de control: no llama al LLM ni ejecuta herramientas."""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from src.ep2.contratos import (
    CambioPlan, ObservacionPlan, PasoPlan, PlanEjecucion, ResultadoHerramienta,
)
from src.ep2.memoria import texto_seguro


def _normalizar(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto.lower()) if unicodedata.category(c) != "Mn")


def _ahora() -> datetime:
    return datetime.now(timezone.utc)


def multiples_usuarios(texto: str) -> bool:
    t = _normalizar(texto)
    patron = r"(?:varios|multiples|muchos|\d+) usuarios (?:estan |estan siendo |han sido )?afectados"
    for m in re.finditer(patron, t):
        if re.search(r"\b(?:no|ningun|sin)\b.{0,15}$", t[:m.start()]):
            continue
        numero = re.match(r"\d+", m.group())
        if not numero or int(numero.group()) >= 2:
            return True
    return False


def _previstas(consulta: str) -> list[str]:
    t = _normalizar(consulta)
    herramientas = []
    if re.search(r"(?:consulta|revisa|verifica).{0,25}\bticket\b", t) or (
        re.search(r"\b(?:estado|prioridad)\b", t) and re.search(r"\b(?:inc|req)-\d", t)
    ):
        herramientas.append("consultar_ticket")
    if "sla" in t or re.search(r"tiempos?.{0,30}(?:respuesta|resolucion)", t):
        herramientas.append("consultar_sla")
    if "activo" in t:
        herramientas.append("consultar_activo")
    if re.search(r"\b(?:analiza|analisis|triage)\b", t):
        herramientas.append("analizar_incidente")
    if "procedimiento" in t:
        herramientas.append("buscar_procedimiento")
    nota = re.search(r"\b(?:propon|registrar|registra|anade|anadir|escribe)\b.{0,45}\bnota\b", t)
    if nota and not re.search(r"\b(?:no|sin)\s+$", t[:nota.start()]):
        herramientas.append("registrar_nota_ticket")
    return herramientas


class Planificador:
    """Un plan activo por contexto. Las transiciones las decide el servidor.

    Las plantillas declaran verificaciones previstas; Groq selecciona las
    herramientas dentro del mismo AgentExecutor. Ningún método ejecuta acciones.
    """

    def __init__(self, consulta: str, *, anterior: PlanEjecucion | None = None,
                 ticket_activo: str | None = None) -> None:
        ahora = _ahora()
        ids = re.findall(r"\b(?:INC|REQ)-\d{4}-\d{3,5}\b", consulta.upper())
        ticket = ids[0] if ids else ticket_activo or (anterior.ticket_id if anterior else None)
        previstas = _previstas(consulta)
        impacto = multiples_usuarios(consulta)
        self.solo_estado = "sin ejecutar" in _normalizar(consulta) and ("plan" in _normalizar(consulta))
        continuar = anterior is not None and ticket == anterior.ticket_id and (
            impacto or re.search(r"\b(?:retoma|retomemos|continua|reanuda|pendiente|ahora)\b", _normalizar(consulta))
        )
        self.es_flexible = len(previstas) <= 1 and not continuar and not impacto
        self.permite_nota = "registrar_nota_ticket" in previstas
        self.ejecutadas: set[str] = set()
        if continuar:
            self.plan = anterior
            for p in self.plan.pasos:
                if p.estado == "en_ejecucion":
                    self._paso(p.id, estado="pendiente", codigo="LECTURA_INTERRUMPIDA",
                               motivo="Lectura interrumpida; se puede reintentar sin escritura.")
                elif p.herramienta == "registrar_nota_ticket" and p.estado == "bloqueado":
                    self._cambio("AUTORIZACION_NO_RECUPERADA", "Se necesita nueva vista previa y confirmación humana.", p.id)
            for nombre in previstas:
                deps = tuple(p.id for p in self.plan.pasos if p.estado != "cancelado") if nombre == "registrar_nota_ticket" else ()
                self._agregar(nombre, dependencias=deps, prioridad=3 if nombre == "registrar_nota_ticket" else 2)
            if not impacto and not self.solo_estado:
                for p in self.plan.pasos:
                    if p.estado == "bloqueado" and p.herramienta != "registrar_nota_ticket" and p.intentos < 2 and p.codigo not in ("PERMISO_REQUERIDO", "ARGUMENTOS_INVALIDOS"):
                        self._paso(p.id, estado="pendiente", codigo="REINTENTO_EXPLICITO",
                                   motivo="Reanudación solicitada; máximo dos intentos por paso.")
                    elif self.permite_nota and p.herramienta == "registrar_nota_ticket" and p.estado == "bloqueado" and p.codigo in (
                        "EJECUCION_INTERRUMPIDA", "LIMITE_EJECUCION", "DEPENDENCIA_BLOQUEADA",
                        "CONFIRMACION_REQUERIDA", "CONFIRMACION_EXPIRADA",
                    ):
                        self._paso(p.id, estado="pendiente", codigo="NUEVA_VISTA_PREVIA",
                                   motivo="Solicitud explícita de nueva propuesta; dependencias y confirmación humana siguen obligatorias.")
            self._cambio("PLAN_RECUPERADO", "Plan recuperado de la memoria del mismo usuario, sesión y perfil.")
        else:
            pasos = self._construir(previstas or ["consultar_ticket"], ahora)
            objetivo = "Atender solicitud de nota; contenido omitido." if "registrar_nota_ticket" in previstas else texto_seguro(consulta)
            self.plan = PlanEjecucion(id=uuid4(), objetivo=objetivo, creado_en=ahora,
                                      actualizado_en=ahora, ticket_id=ticket, pasos=tuple(pasos))
            self._cambio("PLAN_CREADO", "Verificaciones previstas según la solicitud; pendientes de ejecución real.")
        if impacto:
            self._replantear_impacto()
        self.inicial = self.plan.model_copy(deep=True)

    @staticmethod
    def _construir(nombres: list[str], ahora: datetime) -> list[PasoPlan]:
        pasos = []
        for nombre in nombres:
            deps = []
            if nombre != "consultar_ticket":
                deps = [p.id for p in pasos if p.herramienta == "consultar_ticket"]
            if nombre in ("buscar_procedimiento", "analizar_incidente", "registrar_nota_ticket"):
                deps = [p.id for p in pasos if nombre == "registrar_nota_ticket" or p.herramienta in ("consultar_ticket", "consultar_sla")]
            pasos.append(PasoPlan(id=f"p{len(pasos)+1}", herramienta=nombre,
                                  prioridad=3 if nombre == "registrar_nota_ticket" else 2,
                                  dependencias=tuple(deps), motivo="Verificación solicitada.", actualizado_en=ahora))
        return pasos

    def _actualizar(self, **datos) -> None:
        # model_copy no valida actualizaciones: validar SIEMPRE el grafo completo.
        self.plan = PlanEjecucion.model_validate({**self.plan.model_dump(), **datos})

    def _cambio(self, codigo: str, motivo: str, paso_id: str | None = None) -> None:
        revision = self.plan.revision + 1
        evento = CambioPlan(fecha=_ahora(), revision=revision, codigo=codigo, motivo=motivo, paso_id=paso_id)
        self._actualizar(revision=revision, actualizado_en=evento.fecha,
                         cambios=(*self.plan.cambios, evento)[-30:])

    def _paso(self, identificador: str, **datos) -> None:
        pasos = tuple(p.model_copy(update={**datos, "actualizado_en": _ahora()}) if p.id == identificador else p
                      for p in self.plan.pasos)
        self._actualizar(pasos=pasos)
        p = next(p for p in self.plan.pasos if p.id == identificador)
        self._cambio(p.codigo, p.motivo, p.id)

    def _agregar(self, nombre: str, *, dependencias: tuple[str, ...] = (), prioridad: int = 2) -> PasoPlan:
        existente = next((p for p in self.plan.pasos if p.herramienta == nombre and p.estado != "cancelado"), None)
        if existente:
            return existente
        if len(self.plan.pasos) >= 12:
            raise ValueError("El plan alcanzó doce pasos.")
        numero = max(int(p.id[1:]) for p in self.plan.pasos) + 1
        p = PasoPlan(id=f"p{numero}", herramienta=nombre, prioridad=prioridad, dependencias=dependencias,
                     motivo="Paso añadido al adaptar el plan.", actualizado_en=_ahora())
        self._actualizar(pasos=(*self.plan.pasos, p))
        self._cambio("PASO_ANADIDO", p.motivo, p.id)
        return p

    def _replantear_impacto(self) -> None:
        objetivo = "Reevaluar impacto reportado: verificar ticket, SLA y procedimiento previsto."
        if self.permite_nota:
            objetivo += " Proponer seguimiento sujeto a confirmación humana."
        self._actualizar(objetivo=objetivo, impacto_reportado="multiples_usuarios", prioridad_propuesta=None,
                         criterio_prioridad="Reporte de varios afectados; verificar alcance y consultar SLA. No equivale a P1.")
        o = ObservacionPlan(fecha=_ahora(), origen="usuario", codigo="IMPACTO_REPORTADO",
                            resumen="El usuario reporta múltiples usuarios afectados; aún no está verificado.",
                            procedencia=("usuario:reporte_no_verificado",))
        self._actualizar(observaciones=(*self.plan.observaciones, o)[-20:])
        ticket = self._agregar("consultar_ticket", prioridad=1)
        sla = self._agregar("consultar_sla", dependencias=(ticket.id,), prioridad=1)
        analisis = self._agregar("analizar_incidente", dependencias=(ticket.id, sla.id), prioridad=1)
        # Reabrir primero todos los descendientes para mantener válido el grafo.
        afectados = {ticket.id, sla.id, analisis.id}
        for _ in self.plan.pasos:
            afectados |= {p.id for p in self.plan.pasos if any(d in afectados for d in p.dependencias)}
        pasos = []
        for p in self.plan.pasos:
            deps = p.dependencias
            if p.id == sla.id:
                deps = (ticket.id,)
            elif p.id == analisis.id:
                deps = (ticket.id, sla.id)
            elif p.herramienta == "registrar_nota_ticket":
                deps = tuple(dict.fromkeys((*deps, ticket.id, sla.id, analisis.id)))
            datos = {"dependencias": deps}
            if p.id in afectados or p.herramienta == "registrar_nota_ticket":
                datos.update(estado="pendiente", intentos=0, codigo="REVALIDAR_IMPACTO",
                             actualizado_en=_ahora(),
                             motivo="Revalidar por un nuevo reporte de impacto, sin modificar el ITSM.")
            if p.id in (ticket.id, sla.id, analisis.id):
                datos["prioridad"] = 1
            pasos.append(p.model_copy(update=datos))
        self._actualizar(pasos=tuple(pasos))
        self._cambio("REPLANIFICACION_IMPACTO", "Se priorizan ticket, SLA y análisis; la nota espera esas verificaciones.")

    def disponibles(self) -> list[PasoPlan]:
        completados = {p.id for p in self.plan.pasos if p.estado == "completado"}
        listos = sorted((p for p in self.plan.pasos if p.estado == "pendiente" and set(p.dependencias) <= completados
                         and (p.herramienta != "registrar_nota_ticket" or self.permite_nota)),
                        key=lambda p: (p.prioridad, int(p.id[1:])))
        return [p for p in listos if p.prioridad == listos[0].prioridad] if listos else []

    def nota_espera_dependencias(self) -> bool:
        paso = next((p for p in self.plan.pasos if p.herramienta == "registrar_nota_ticket" and p.estado != "cancelado"), None)
        if not paso:
            return any(p.estado != "completado" for p in self.plan.pasos if p.estado != "cancelado")
        completos = {p.id for p in self.plan.pasos if p.estado == "completado"}
        return not set(paso.dependencias) <= completos

    def rechazar_nota_prematura(self) -> None:
        self._cambio("NOTA_ESPERA_VERIFICACIONES", "Resolver dependencias antes de proponer la nota; no se ejecutó la herramienta.")

    def preparar(self, nombre: str, argumentos: dict[str, Any]) -> ResultadoHerramienta | None:
        def rechazar(codigo, mensaje):
            self._cambio(codigo, mensaje)
            return ResultadoHerramienta(estado="error", codigo=codigo, mensaje=mensaje)
        if self.solo_estado:
            return rechazar("PLAN_SOLO_ESTADO", "Se solicitó mostrar el plan sin ejecutar acciones.")
        if nombre == "registrar_nota_ticket" and not self.permite_nota:
            return rechazar("PLAN_NOTA_NO_SOLICITADA", "La solicitud actual no pide proponer una nota.")
        if self.plan.ticket_id and argumentos.get("ticket_id") not in (None, self.plan.ticket_id):
            return rechazar("PLAN_TICKET_DISTINTO", "La herramienta debe usar el ticket del plan activo.")
        paso = next((p for p in self.plan.pasos if p.herramienta == nombre and p.estado != "cancelado"), None)
        if paso is None:
            if self.es_flexible and not self.ejecutadas:
                self._actualizar(pasos=tuple(p.model_copy(update={"estado": "cancelado", "codigo": "SELECCION_AUTONOMA"})
                                            for p in self.plan.pasos))
            deps = tuple(p.id for p in self.plan.pasos if p.estado != "cancelado") if nombre == "registrar_nota_ticket" else ()
            paso = self._agregar(nombre, dependencias=deps)
        if paso.id in self.ejecutadas:
            return rechazar("PLAN_PASO_YA_EJECUTADO", "El paso ya se ejecutó en este turno; no repetir la acción.")
        if paso.estado == "completado":
            return rechazar("PLAN_PASO_COMPLETADO", "El paso ya está completado; retoma los pendientes o solicita una nueva consulta.")
        if paso.estado == "bloqueado" and nombre == "registrar_nota_ticket" and paso.codigo == "CONFIRMACION_REQUERIDA":
            self._paso(paso.id, estado="pendiente", codigo="NUEVA_VISTA_PREVIA", motivo="Se requiere una autorización humana nueva.")
        elif paso.estado != "pendiente":
            return rechazar("PLAN_PASO_BLOQUEADO", "Paso bloqueado; resolver la causa antes de reintentar.")
        disponibles = self.disponibles()
        completados = {p.id for p in self.plan.pasos if p.estado == "completado"}
        if not set(paso.dependencias) <= completados:
            return rechazar("PLAN_DEPENDENCIA_PENDIENTE", "Hay verificaciones previas pendientes; consulta los pasos disponibles del plan.")
        if disponibles and paso.prioridad > disponibles[0].prioridad:
            nombres = ", ".join(p.herramienta for p in disponibles)
            return rechazar("PLAN_PRIORIDAD_PENDIENTE", f"Hay pasos con mayor prioridad: {nombres}.")
        if nombre == "consultar_sla" and paso.dependencias and self.plan.prioridad_registrada and argumentos.get("prioridad") != self.plan.prioridad_registrada:
            return rechazar("PLAN_PRIORIDAD_NO_COINCIDE", "Consulta el SLA de la prioridad registrada, sin sustituirla por la propuesta.")
        self._paso(paso.id, estado="en_ejecucion", intentos=paso.intentos+1,
                   codigo="PASO_INICIADO", motivo="Dependencias y prioridad satisfechas; ejecutar la herramienta seleccionada.")
        self.ejecutadas.add(paso.id)
        return None

    def observar(self, nombre: str, resultado: ResultadoHerramienta) -> None:
        p = next((p for p in self.plan.pasos if p.herramienta == nombre and p.estado == "en_ejecucion"), None)
        resumen = f"{nombre}: {resultado.codigo}."
        nueva_prioridad = (resultado.datos.get("prioridad") if resultado.codigo == "TICKET_CONSULTADO" else
                           resultado.datos.get("prioridad_registrada") if resultado.codigo == "INCIDENTE_ANALIZADO" else None)
        if nueva_prioridad and self.plan.prioridad_registrada and nueva_prioridad != self.plan.prioridad_registrada:
            self._actualizar(prioridad_propuesta=None,
                criterio_prioridad="Cambió la prioridad registrada en la fuente; revisar la propuesta y el seguimiento.")
            if resultado.codigo == "INCIDENTE_ANALIZADO":
                # analizar_incidente consulta ticket y SLA reales internamente:
                # reflejar ese SLA actualizado sin ejecutar otra llamada duplicada.
                self._actualizar(pasos=tuple(s.model_copy(update={
                    "codigo": "SLA_VERIFICADO_EN_ANALISIS", "actualizado_en": _ahora(),
                    "motivo": "SLA actualizado obtenido en el resultado real del triage.",
                }) if s.herramienta == "consultar_sla" and s.estado == "completado" else s for s in self.plan.pasos))
            self._cambio("REPLANIFICACION_PRIORIDAD_REGISTRADA", "Una observación real cambió la prioridad registrada; se descarta la propuesta anterior.")
        if resultado.codigo == "TICKET_CONSULTADO":
            d = resultado.datos
            self._actualizar(ticket_id=d["id"], prioridad_registrada=d["prioridad"])
            resumen += f" Estado {d['estado']}; prioridad registrada {d['prioridad']}; nivel {d['nivel_atencion']}."
        if self.plan.impacto_reportado == "multiples_usuarios" and resultado.codigo == "SLA_CONSULTADO":
            d = resultado.datos
            if d.get("prioridad") == "P2" and "grupo de usuarios" in _normalizar(d.get("descripcion", "")):
                self._actualizar(prioridad_propuesta="P2", criterio_prioridad="P2 contempla grupos de usuarios sin servicio según SLA; propuesta sujeta a verificar el reporte.")
                self._cambio("PRIORIDAD_PROPUESTA", self.plan.criterio_prioridad)
        if resultado.codigo == "INCIDENTE_ANALIZADO":
            self._actualizar(ticket_id=resultado.datos["ticket_id"], prioridad_registrada=resultado.datos["prioridad_registrada"])
            resumen += f" Decisión: {resultado.datos['decision']}; no es un diagnóstico de infraestructura."
        if resultado.estado == "requiere_confirmacion":
            self._actualizar(ticket_id=resultado.datos["ticket_id"])
        origen = "sistema" if resultado.codigo.startswith("PLAN_") or resultado.codigo in ("ARGUMENTOS_INVALIDOS", "TIEMPO_AGOTADO") else "herramienta"
        o = ObservacionPlan(fecha=_ahora(), origen=origen, codigo=resultado.codigo,
                            resumen=resumen[:240], procedencia=resultado.procedencia[:8])
        self._actualizar(observaciones=(*self.plan.observaciones, o)[-20:])
        if p is None:
            return
        estado = "completado" if resultado.estado == "ok" else "bloqueado"
        self._paso(p.id, estado=estado, codigo=resultado.codigo,
                   motivo="Resultado real de la herramienta." if estado == "completado" else resultado.mensaje[:240])
        if resultado.estado != "ok" and resultado.estado != "requiere_confirmacion":
            self._bloquear_descendientes(p.id, "Verificación previa no disponible; no ejecutar acciones dependientes.")
            if resultado.codigo == "SIN_PROCEDIMIENTO":
                # El triage verifica ticket/SLA internamente. Recomendar Nivel 2
                # no requiere inventar un procedimiento ni escribir en el ITSM.
                self._agregar("analizar_incidente", prioridad=1)
                self._cambio("ESCALAMIENTO_PROPUESTO", "Sin procedimiento admisible: evaluar seguimiento Nivel 2, sin improvisar pasos.")
            else:
                self._cambio("REPLANIFICACION_ERROR", "Paso bloqueado por el resultado real; reintento explícito posterior, sin bucle automático.")

    def _bloquear_descendientes(self, id_paso: str, motivo: str) -> None:
        afectados = {id_paso}
        for _ in self.plan.pasos:
            afectados |= {p.id for p in self.plan.pasos if any(d in afectados for d in p.dependencias)}
        pasos = tuple(p.model_copy(update={"estado": "bloqueado", "codigo": "DEPENDENCIA_BLOQUEADA", "motivo": motivo, "actualizado_en": _ahora()})
                      if p.id in afectados and p.id != id_paso and p.estado == "pendiente" else p for p in self.plan.pasos)
        self._actualizar(pasos=pasos)

    def finalizar(self, estado: str) -> None:
        if estado == "limite":
            self._actualizar(pasos=tuple(p.model_copy(update={"estado": "bloqueado", "codigo": "LIMITE_EJECUCION",
                "motivo": "Presupuesto agotado; continuar en una solicitud posterior.", "actualizado_en": _ahora()}) if p.estado in ("pendiente", "en_ejecucion") else p for p in self.plan.pasos))
            self._cambio("LIMITE_EJECUCION", "Se detuvo el único ciclo de ejecución; no se ejecutan pasos fuera del presupuesto.")
        elif estado == "error":
            self._actualizar(pasos=tuple(p.model_copy(update={"estado": "bloqueado", "codigo": "EJECUCION_INTERRUMPIDA",
                "motivo": "Ejecución interrumpida; revisar y reanudar explícitamente.", "actualizado_en": _ahora()}) if p.estado in ("pendiente", "en_ejecucion") else p for p in self.plan.pasos))
            self._cambio("EJECUCION_INTERRUMPIDA", "Ejecución interrumpida; conservar el plan para revisión y reanudación explícita.")
        elif estado == "ok" and self.disponibles():
            self._cambio("PLAN_INCOMPLETO", "La respuesta del modelo no completa pasos que no fueron ejecutados.")

    def confirmar(self, resultado: ResultadoHerramienta) -> None:
        p = next((p for p in self.plan.pasos if p.herramienta == "registrar_nota_ticket" and p.codigo == "CONFIRMACION_REQUERIDA"), None)
        if p and resultado.codigo in ("NOTA_REGISTRADA", "NOTA_REUTILIZADA", "NOTA_CANCELADA", "CONFIRMACION_EXPIRADA"):
            estado = "completado" if resultado.estado == "ok" else "cancelado" if resultado.estado == "cancelada" else "bloqueado"
            self._paso(p.id, estado=estado, codigo=resultado.codigo, motivo=resultado.mensaje[:240])
            o = ObservacionPlan(fecha=_ahora(), origen="interfaz_humana", codigo=resultado.codigo,
                                resumen=resultado.mensaje[:240], procedencia=resultado.procedencia[:8])
            self._actualizar(observaciones=(*self.plan.observaciones, o)[-20:])

    def contexto(self) -> str:
        datos = self.plan.model_dump(mode="json", exclude={"creado_en", "actualizado_en", "objetivo", "cambios"})
        datos["pasos"] = [{k: s[k] for k in ("id", "herramienta", "prioridad", "dependencias", "estado", "codigo")} for s in datos["pasos"]]
        datos["observaciones"] = datos["observaciones"][-2:]
        return json.dumps({"plan": datos,
                           "solo_estado": self.solo_estado,
                           "disponibles": [] if self.solo_estado else [p.herramienta for p in self.disponibles()],
                           "regla": "Estados del servidor; cumple dependencias. Reporte de impacto no verificado. Ninguna autorización de escritura está en el plan."}, ensure_ascii=False, separators=(",", ":"))
