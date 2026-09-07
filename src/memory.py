"""Memoria conversacional: ventana de 6 intercambios más resumen de sesión.

El diagnóstico en una mesa de ayuda es multiturno. El agente pregunta, el usuario
responde, y tres turnos después "no, sigue igual" solo significa algo si el
sistema recuerda cuál era el síntoma. Por eso el historial no se trunca a secas:
lo que sale de la ventana se pliega en un **resumen de sesión** que viaja al
principio del historial.

Diseño:

* Se conservan literales los últimos ``VENTANA_TURNOS`` intercambios
  (usuario + asistente), es decir 12 mensajes.
* Lo que se desplaza se resume. El resumidor es inyectable: en producción usa el
  propio LLM; en las pruebas se usa el resumidor heurístico, que no llama a
  ninguna API.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable, Sequence

from langchain_core.chat_history import BaseChatMessageHistory
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from src import config

Resumidor = Callable[[Sequence[BaseMessage], str], str]
"""Firma de un resumidor: recibe los mensajes que salen y el resumen previo."""

PREFIJO_RESUMEN: str = "Resumen de la sesión hasta ahora: "


# ---------------------------------------------------------------------------
# Resumidores
# ---------------------------------------------------------------------------


def resumidor_heuristico(
    mensajes: Sequence[BaseMessage], resumen_previo: str = ""
) -> str:
    """Resume sin llamar a ningún modelo, encadenando los temas tratados.

    Es el resumidor por defecto: barato, determinista y suficiente para sostener
    el hilo del síntoma. Se usa también en las pruebas, que corren sin APIs.

    Args:
        mensajes: Mensajes que salen de la ventana.
        resumen_previo: Resumen acumulado hasta ahora.

    Returns:
        Resumen actualizado.
    """
    temas: list[str] = []
    for mensaje in mensajes:
        if not isinstance(mensaje, HumanMessage):
            continue
        texto = " ".join(str(mensaje.content).split())
        if texto:
            temas.append(texto[:160])

    if not temas:
        return resumen_previo

    nuevo = "; ".join(temas)
    if resumen_previo:
        return f"{resumen_previo}; {nuevo}"
    return nuevo


def crear_resumidor_llm(llm: Any) -> Resumidor:
    """Construye un resumidor que delega en el modelo de chat.

    Args:
        llm: Modelo de chat de LangChain.

    Returns:
        Función resumidora con la firma :data:`Resumidor`. Si la llamada al
        modelo falla, cae al resumidor heurístico: perder el resumen nunca debe
        cortar la conversación.
    """

    def _resumir(mensajes: Sequence[BaseMessage], resumen_previo: str = "") -> str:
        conversacion = "\n".join(
            f"{'Usuario' if isinstance(m, HumanMessage) else 'Asistente'}: "
            f"{str(m.content)[:600]}"
            for m in mensajes
        )
        instruccion = (
            "Resumí en un máximo de 4 líneas el estado del diagnóstico de esta "
            "conversación de mesa de ayuda: síntoma reportado, verificaciones ya "
            "hechas y su resultado, y decisión pendiente. No agregues información "
            "que no esté en la conversación.\n\n"
            f"Resumen previo: {resumen_previo or 'ninguno'}\n\n"
            f"Conversación:\n{conversacion}"
        )
        try:
            respuesta = config.reintentar_con_backoff(llm.invoke, instruccion)
            texto = getattr(respuesta, "content", str(respuesta))
            return " ".join(str(texto).split())
        except Exception:  # noqa: BLE001 - el resumen es accesorio, no crítico
            return resumidor_heuristico(mensajes, resumen_previo)

    return _resumir


# ---------------------------------------------------------------------------
# Historial
# ---------------------------------------------------------------------------


class HistorialConVentanaYResumen(BaseChatMessageHistory):
    """Historial con ventana deslizante de N intercambios y resumen del resto.

    Attributes:
        session_id: Identificador de la sesión.
        ventana_turnos: Cantidad de intercambios que se conservan literales.
        resumen: Resumen acumulado de lo que salió de la ventana.
    """

    def __init__(
        self,
        session_id: str = "default",
        ventana_turnos: int = config.VENTANA_TURNOS,
        resumidor: Resumidor | None = None,
    ) -> None:
        """Inicializa el historial.

        Args:
            session_id: Identificador de la sesión.
            ventana_turnos: Intercambios literales a conservar.
            resumidor: Función que pliega los mensajes desplazados. Por defecto,
                :func:`resumidor_heuristico`.
        """
        self.session_id = session_id
        self.ventana_turnos = ventana_turnos
        self.resumidor: Resumidor = resumidor or resumidor_heuristico
        self.resumen: str = ""
        self._mensajes: list[BaseMessage] = []

    # -- Interfaz de BaseChatMessageHistory ---------------------------------

    @property
    def messages(self) -> list[BaseMessage]:
        """Mensajes que se inyectan en el prompt.

        Returns:
            El resumen de sesión (si existe) como mensaje de sistema, seguido de
            los mensajes dentro de la ventana.
        """
        if self.resumen:
            cabecera = SystemMessage(content=f"{PREFIJO_RESUMEN}{self.resumen}")
            return [cabecera, *self._mensajes]
        return list(self._mensajes)

    def add_messages(self, messages: Iterable[BaseMessage]) -> None:
        """Agrega mensajes al historial y aplica la ventana.

        Args:
            messages: Mensajes a incorporar.
        """
        self._mensajes.extend(messages)
        self._plegar_excedente()

    def clear(self) -> None:
        """Vacía el historial y el resumen."""
        self._mensajes = []
        self.resumen = ""

    # -- Detalles internos ---------------------------------------------------

    @property
    def limite_mensajes(self) -> int:
        """Cantidad máxima de mensajes literales (2 por intercambio)."""
        return self.ventana_turnos * 2

    def _plegar_excedente(self) -> None:
        """Mueve al resumen los mensajes que se salen de la ventana."""
        excedente = len(self._mensajes) - self.limite_mensajes
        if excedente <= 0:
            return
        # Se pliega de a pares para no cortar un intercambio por la mitad.
        if excedente % 2:
            excedente += 1
        salientes = self._mensajes[:excedente]
        self._mensajes = self._mensajes[excedente:]
        self.resumen = self.resumidor(salientes, self.resumen)

    @property
    def cantidad_intercambios(self) -> int:
        """Intercambios completos actualmente en la ventana."""
        return len(self._mensajes) // 2

    def transcripcion(self) -> str:
        """Devuelve la conversación en texto plano, para depurar o exportar.

        Returns:
            Transcripción legible del historial vigente.
        """
        lineas: list[str] = []
        if self.resumen:
            lineas.append(f"[{PREFIJO_RESUMEN}{self.resumen}]")
        for mensaje in self._mensajes:
            if isinstance(mensaje, HumanMessage):
                lineas.append(f"Usuario: {mensaje.content}")
            elif isinstance(mensaje, AIMessage):
                lineas.append(f"Asistente: {mensaje.content}")
            else:
                lineas.append(f"Sistema: {mensaje.content}")
        return "\n".join(lineas)


# ---------------------------------------------------------------------------
# Registro de sesiones
# ---------------------------------------------------------------------------

_SESIONES: dict[str, HistorialConVentanaYResumen] = {}


def obtener_historial(
    session_id: str = "default", resumidor: Resumidor | None = None
) -> HistorialConVentanaYResumen:
    """Devuelve el historial de una sesión, creándolo si no existe.

    Es la función que consume ``RunnableWithMessageHistory``.

    Args:
        session_id: Identificador de la sesión.
        resumidor: Resumidor a usar al crear la sesión.

    Returns:
        Historial de la sesión.
    """
    if session_id not in _SESIONES:
        _SESIONES[session_id] = HistorialConVentanaYResumen(
            session_id=session_id, resumidor=resumidor
        )
    return _SESIONES[session_id]


def reiniciar_sesion(session_id: str = "default") -> None:
    """Elimina el historial de una sesión.

    Args:
        session_id: Identificador de la sesión a limpiar.
    """
    _SESIONES.pop(session_id, None)


def sesiones_activas() -> list[str]:
    """Lista los identificadores de sesión en memoria.

    Returns:
        Lista de ``session_id``.
    """
    return list(_SESIONES)
