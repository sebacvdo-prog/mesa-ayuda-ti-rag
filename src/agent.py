"""Cadena principal del asistente: orquesta guardarraíles, RAG, SQL y memoria.

Orden de ejecución de una consulta, que es donde está la mayor parte del diseño:

1. **Guardarraíles de entrada.** Alcance y solicitudes de credenciales. Si la
   consulta se bloquea, no se gasta ni una llamada al modelo.
2. **Enrutamiento y recuperación.** Se clasifica la consulta, se buscan
   fragmentos con umbral 0,72 y se reordenan por vigencia.
3. **Consulta SQL.** Si la pregunta menciona un ticket, una prioridad o un RUT,
   se consulta la base del ITSM con sentencias parametrizadas.
4. **Enmascarado.** Recién acá, y **antes** de armar el mensaje que sale del
   proceso, se enmascaran consulta, contexto y datos del ITSM.
5. **Corte por contexto vacío.** Si no quedó contexto ni datos, se devuelve la
   respuesta literal de escalamiento sin llamar al modelo: la respuesta es
   determinista y no consume cuota.
6. **Llamada al modelo** con historial (ventana de 6 intercambios + resumen).
7. **Verificación de salida.** Se garantiza la línea de fuente y se registra si
   la respuesta indica escalamiento.
"""

from __future__ import annotations

from typing import Any, Sequence

from pydantic import BaseModel, ConfigDict, Field

from src import config, guardrails, memory, prompts
from src.retriever import (
    ConectorITSM,
    FragmentoRecuperado,
    RecuperadorVectorial,
    clasificar_consulta,
    consultar_datos_estructurados,
    formatear_contexto,
)

MARCA_FUENTE: str = "Fuente:"
"""Prefijo de la línea de cita obligatoria en toda respuesta."""

_TERMINOS_ESCALAMIENTO: tuple[str, ...] = (
    "escalar a nivel 2",
    "escalamiento a nivel 2",
    "escalar el caso",
    "derivar a nivel 2",
    "nivel 2",
)


class RespuestaAsistente(BaseModel):
    """Resultado completo de una consulta al asistente.

    Attributes:
        texto: Respuesta final para el agente de la mesa.
        fragmentos: Fragmentos usados como contexto, con su puntaje.
        clasificacion: ``interna``, ``externa`` o ``mixta``.
        perfil: Perfil con el que se resolvió la consulta.
        motivo: ``ok``, ``credenciales``, ``fuera_de_alcance`` o ``sin_contexto``.
        escalamiento: Si la respuesta indica escalar a Nivel 2.
        datos_itsm: Bloque de datos estructurados (ya enmascarado).
        enmascarados: Conteo de datos sensibles reemplazados antes de llamar al LLM.
        contexto: Contexto enmascarado que se envió al modelo.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    texto: str
    fragmentos: list[FragmentoRecuperado] = Field(default_factory=list)
    clasificacion: str = "mixta"
    perfil: str = "agente"
    motivo: str = "ok"
    escalamiento: bool = False
    datos_itsm: str = ""
    enmascarados: dict[str, int] = Field(default_factory=dict)
    contexto: str = ""


def indica_escalamiento(texto: str) -> bool:
    """Detecta si una respuesta indica escalamiento a Nivel 2.

    Args:
        texto: Respuesta del asistente.

    Returns:
        ``True`` si menciona el escalamiento.
    """
    minusculas = texto.lower()
    return any(termino in minusculas for termino in _TERMINOS_ESCALAMIENTO)


def asegurar_bloque_fuente(
    texto: str, fragmentos: Sequence[FragmentoRecuperado]
) -> str:
    """Garantiza que la respuesta termine con la línea de fuente.

    El prompt ya la exige, pero un modelo puede omitirla al truncar. Como la
    Política de Seguridad TI (sección 7) declara inaplicable una respuesta sin
    cita, acá se agrega de forma determinista a partir de los metadatos reales de
    los fragmentos usados: nunca se inventa una fuente.

    Args:
        texto: Respuesta del modelo.
        fragmentos: Fragmentos que se usaron como contexto.

    Returns:
        Respuesta con la línea de fuente asegurada.
    """
    texto = texto.strip()
    if MARCA_FUENTE.lower() in texto.lower():
        return texto
    if texto == config.RESPUESTA_SIN_PROCEDIMIENTO:
        return texto
    if not fragmentos:
        return texto

    citas: list[str] = []
    for fragmento in fragmentos:
        if fragmento.cita not in citas:
            citas.append(fragmento.cita)
    return f"{texto}\n\nFuente: [{'; '.join(citas)}]"


class AsistenteMesaAyuda:
    """Asistente conversacional RAG de la mesa de ayuda TI.

    Attributes:
        recuperador: Recuperador vectorial sobre el índice FAISS.
        conector: Conector SQL al ITSM y la CMDB.
        llm: Modelo de chat.
    """

    def __init__(
        self,
        recuperador: RecuperadorVectorial | None = None,
        conector: ConectorITSM | None = None,
        llm: Any | None = None,
        usar_resumidor_llm: bool = True,
    ) -> None:
        """Inicializa el asistente.

        Args:
            recuperador: Recuperador a usar. Si es ``None`` se crea uno que carga
                el índice de disco de forma perezosa.
            conector: Conector SQL. Si es ``None`` se usa el de la ruta por defecto.
            llm: Modelo de chat ya construido (útil para inyectar dobles en las
                pruebas). Si es ``None`` se construye con la configuración.
            usar_resumidor_llm: Si el resumen de sesión lo hace el propio modelo.
        """
        self.recuperador = recuperador or RecuperadorVectorial()
        self.conector = conector or ConectorITSM()
        self._llm = llm
        self._cadena: Any | None = None
        self._usar_resumidor_llm = usar_resumidor_llm

    # -- Construcción perezosa ----------------------------------------------

    @property
    def llm(self) -> Any:
        """Modelo de chat, construido la primera vez que se usa."""
        if self._llm is None:
            self._llm = config.crear_llm(
                temperatura=config.TEMPERATURA, max_tokens=config.MAX_TOKENS
            )
        return self._llm

    def _resumidor(self) -> memory.Resumidor:
        """Elige el resumidor de sesión.

        Returns:
            Resumidor basado en el LLM, o el heurístico si no corresponde usarlo.
        """
        if not self._usar_resumidor_llm:
            return memory.resumidor_heuristico
        return memory.crear_resumidor_llm(self.llm)

    @property
    def cadena(self) -> Any:
        """Cadena ``prompt | llm | parser`` envuelta con historial de mensajes."""
        if self._cadena is None:
            from langchain_core.output_parsers import StrOutputParser
            from langchain_core.runnables.history import RunnableWithMessageHistory

            base = prompts.construir_prompt_chat() | self.llm | StrOutputParser()
            resumidor = self._resumidor()

            self._cadena = RunnableWithMessageHistory(
                base,
                lambda session_id: memory.obtener_historial(session_id, resumidor),
                input_messages_key="pregunta",
                history_messages_key="historial",
            )
        return self._cadena

    # -- Consulta -------------------------------------------------------------

    def responder(
        self,
        consulta: str,
        perfil: str = "agente",
        session_id: str = "default",
    ) -> RespuestaAsistente:
        """Responde una consulta aplicando todo el pipeline.

        Args:
            consulta: Pregunta del agente o del colaborador.
            perfil: ``agente`` o ``usuario_final``.
            session_id: Identificador de la conversación, para la memoria.

        Returns:
            :class:`RespuestaAsistente` con el texto y toda la trazabilidad.

        Raises:
            config.ErrorDeCuota: Si el proveedor agota la cuota diaria.
        """
        perfil = guardrails.normalizar_perfil(perfil)

        # 1. Guardarraíles de entrada.
        veredicto = guardrails.evaluar_consulta(consulta)
        if not veredicto.permitida:
            return RespuestaAsistente(
                texto=veredicto.mensaje,
                perfil=perfil,
                motivo=veredicto.motivo,
                escalamiento=veredicto.motivo == "credenciales",
            )

        # 2. Enrutamiento y recuperación vectorial.
        clasificacion = clasificar_consulta(consulta)
        fragmentos = self.recuperador.buscar(
            consulta, perfil=perfil, clasificacion=clasificacion
        )

        # 3. Datos estructurados por SQL parametrizado.
        datos_itsm = consultar_datos_estructurados(consulta, self.conector)

        # 4. Enmascarado, antes de cualquier salida hacia el proveedor.
        contexto_crudo = formatear_contexto(fragmentos)
        contexto = guardrails.enmascarar_texto(contexto_crudo)
        datos_enmascarados = guardrails.enmascarar(datos_itsm)
        consulta_enmascarada = guardrails.enmascarar(consulta)
        conteos = dict(consulta_enmascarada.conteos)
        for clave, valor in datos_enmascarados.conteos.items():
            conteos[clave] = conteos.get(clave, 0) + valor

        # 5. Corte determinista cuando no hay de dónde responder.
        if not fragmentos and not datos_itsm:
            return RespuestaAsistente(
                texto=config.RESPUESTA_SIN_PROCEDIMIENTO,
                clasificacion=clasificacion,
                perfil=perfil,
                motivo="sin_contexto",
                escalamiento=True,
                enmascarados=conteos,
                contexto=contexto,
            )

        # 6. Llamada al modelo con memoria de sesión.
        salida = config.reintentar_con_backoff(
            self.cadena.invoke,
            {
                "pregunta": consulta_enmascarada.texto,
                "contexto": contexto,
                "datos_itsm": datos_enmascarados.texto or "(sin datos estructurados)",
                "perfil": perfil,
            },
            config={"configurable": {"session_id": session_id}},
        )
        texto = str(getattr(salida, "content", salida)).strip()

        # 7. Verificación de la salida.
        texto = asegurar_bloque_fuente(texto, fragmentos)

        return RespuestaAsistente(
            texto=texto,
            fragmentos=fragmentos,
            clasificacion=clasificacion,
            perfil=perfil,
            motivo="ok",
            escalamiento=indica_escalamiento(texto),
            datos_itsm=datos_enmascarados.texto,
            enmascarados=conteos,
            contexto=contexto,
        )

    def reiniciar(self, session_id: str = "default") -> None:
        """Borra la memoria de una sesión.

        Args:
            session_id: Sesión a reiniciar.
        """
        memory.reiniciar_sesion(session_id)


def crear_asistente(**kwargs: Any) -> AsistenteMesaAyuda:
    """Fábrica de conveniencia para la CLI, Streamlit y la evaluación.

    Args:
        **kwargs: Argumentos de :class:`AsistenteMesaAyuda`.

    Returns:
        Asistente listo para usar.
    """
    config.configurar_langsmith()
    return AsistenteMesaAyuda(**kwargs)
