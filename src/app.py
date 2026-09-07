"""Interfaz web del asistente, en Streamlit.

Incluye historial de la conversación, panel lateral con el selector de perfil y
un expander por respuesta que muestra los fragmentos recuperados con su puntaje
de similitud y su fecha de vigencia: sin eso, el agente no puede auditar de dónde
salió la indicación que está a punto de aplicar.

Uso:
    streamlit run src/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import streamlit as st

# ``streamlit run src/app.py`` ejecuta el archivo como script: agrega ``src/`` al
# path pero no la raíz del proyecto, así que ``from src import ...`` fallaría.
RAIZ_PROYECTO = Path(__file__).resolve().parent.parent
if str(RAIZ_PROYECTO) not in sys.path:
    sys.path.insert(0, str(RAIZ_PROYECTO))

from src import config  # noqa: E402 - requiere el ajuste de sys.path previo
from src.agent import RespuestaAsistente, crear_asistente  # noqa: E402

TITULO: str = "Asistente Mesa de Ayuda TI · Aconcagua Logística"

EJEMPLOS: tuple[str, ...] = (
    "Un conductor no puede conectar la VPN y le aparece error de credenciales.",
    "¿Cuál es el tiempo de primera respuesta comprometido para un ticket P2?",
    "El buzón de una usuaria está lleno y no puede enviar correo.",
    "¿En qué estado está el ticket INC-2026-0412?",
    "Se perdió un terminal móvil en ruta, ¿qué hago?",
)


def inicializar_estado() -> None:
    """Crea las claves de ``st.session_state`` que usa la aplicación."""
    if "mensajes" not in st.session_state:
        st.session_state.mensajes = []
    if "perfil" not in st.session_state:
        st.session_state.perfil = "agente"
    if "session_id" not in st.session_state:
        st.session_state.session_id = "streamlit"


@st.cache_resource(show_spinner=False)
def obtener_asistente() -> Any:
    """Construye el asistente una sola vez por proceso.

    El índice FAISS y el modelo se cargan una vez y se reutilizan entre
    interacciones; sin esta caché, cada mensaje recargaría el índice.

    Returns:
        Instancia de ``AsistenteMesaAyuda``.
    """
    return crear_asistente()


def dibujar_barra_lateral() -> None:
    """Dibuja el panel lateral: perfil, parámetros y acciones."""
    with st.sidebar:
        st.header("Configuración")

        perfil = st.radio(
            "Perfil de quien consulta",
            options=list(config.PERFILES_VALIDOS),
            index=list(config.PERFILES_VALIDOS).index(st.session_state.perfil),
            format_func=lambda p: (
                "Agente de la mesa (ve todo el corpus)"
                if p == "agente"
                else "Usuario final (solo publico_interno)"
            ),
        )
        if perfil != st.session_state.perfil:
            st.session_state.perfil = perfil
            st.toast(f"Perfil cambiado a {perfil}")

        st.divider()
        st.subheader("Parámetros del pipeline")
        st.markdown(
            f"""
            - Modelo de chat: `{config.MODELO_CHAT}`
            - Temperatura: `{config.TEMPERATURA}` · máx. tokens: `{config.MAX_TOKENS}`
            - Embeddings: `{config.MODELO_EMBEDDINGS}` ({config.DIMENSION_EMBEDDINGS} dim)
            - Fragmentación: `{config.TAMANO_CHUNK}` / `{config.SOLAPE_CHUNK}`
            - Recuperación: `top_k={config.TOP_K}` · umbral `{config.UMBRAL_SIMILITUD}`
            - Memoria: últimos `{config.VENTANA_TURNOS}` intercambios + resumen
            """
        )

        st.divider()
        st.subheader("Reglas activas")
        st.markdown(
            """
            - No entrega credenciales de ningún tipo.
            - No ejecuta acciones sobre el ITSM ni el directorio.
            - Enmascara RUT, correo, teléfono, IP y host antes de llamar al modelo.
            - Cita siempre la fuente y su fecha de vigencia.
            """
        )

        st.divider()
        if st.button("Reiniciar conversación", use_container_width=True):
            obtener_asistente().reiniciar(st.session_state.session_id)
            st.session_state.mensajes = []
            st.rerun()


def dibujar_fragmentos(respuesta: RespuestaAsistente) -> None:
    """Muestra el expander con los fragmentos recuperados.

    Args:
        respuesta: Respuesta cuya trazabilidad se quiere mostrar.
    """
    etiqueta = (
        f"Fragmentos recuperados ({len(respuesta.fragmentos)}) · "
        f"consulta {respuesta.clasificacion}"
    )
    with st.expander(etiqueta):
        if not respuesta.fragmentos:
            st.info(
                "No se usaron fragmentos del corpus. "
                f"Motivo registrado: `{respuesta.motivo}`."
            )
        for indice, fragmento in enumerate(respuesta.fragmentos, start=1):
            metadatos = fragmento.documento.metadata
            st.markdown(f"**{indice}. {fragmento.titulo}**")
            columnas = st.columns(3)
            columnas[0].metric("Similitud", f"{fragmento.puntaje:.3f}")
            columnas[1].metric("Vigencia", str(metadatos.get("fecha_vigencia", "s/f")))
            columnas[2].metric("Fuente", str(metadatos.get("fuente", "?")))
            st.caption(
                f"Archivo: `{fragmento.nombre_documento}` · "
                f"Nivel de acceso: `{metadatos.get('nivel_acceso', 'publico_interno')}` · "
                f"Fragmento `{metadatos.get('id_fragmento', '?')}`"
            )
            st.text(fragmento.documento.page_content)
            st.divider()

        if respuesta.datos_itsm:
            st.markdown("**Datos consultados por SQL en el ITSM**")
            st.code(respuesta.datos_itsm, language="text")

        if respuesta.enmascarados:
            st.markdown("**Datos enmascarados antes de llamar al modelo**")
            st.json(respuesta.enmascarados)


def verificar_requisitos() -> bool:
    """Comprueba claves e índice, y muestra el error correspondiente.

    Returns:
        ``True`` si se puede operar.
    """
    problemas = config.validar_configuracion()
    if problemas:
        st.error("Falta configuración para poder responder:")
        for problema in problemas:
            st.markdown(f"- {problema}")
        st.info("Copiá `.env.example` como `.env` y completá las claves.")
        return False

    if not config.archivo_existe(config.DIR_INDICE_FAISS / "index.faiss"):
        st.error("No existe el índice FAISS.")
        st.code("python data/seed_db.py\npython -m src.ingest", language="bash")
        return False
    return True


def main() -> None:
    """Punto de entrada de la aplicación Streamlit."""
    st.set_page_config(page_title=TITULO, page_icon="🛠️", layout="wide")
    inicializar_estado()

    st.title(TITULO)
    st.caption(
        "Asistente RAG de apoyo al agente de Nivel 1. No ejecuta acciones: "
        "entrega el procedimiento aplicable, el tiempo comprometido y la decisión "
        "de escalamiento, citando siempre la fuente."
    )

    dibujar_barra_lateral()

    if not verificar_requisitos():
        return

    if not st.session_state.mensajes:
        st.markdown("**Consultas de ejemplo**")
        columnas = st.columns(len(EJEMPLOS))
        for columna, ejemplo in zip(columnas, EJEMPLOS):
            if columna.button(ejemplo, use_container_width=True):
                st.session_state.pendiente = ejemplo
                st.rerun()

    for mensaje in st.session_state.mensajes:
        with st.chat_message(mensaje["rol"]):
            st.markdown(mensaje["texto"])
            if mensaje.get("respuesta") is not None:
                dibujar_fragmentos(mensaje["respuesta"])

    entrada = st.chat_input("Escribí la consulta de la mesa de ayuda...")
    pendiente = st.session_state.get("pendiente")
    if pendiente:
        del st.session_state["pendiente"]
    consulta = entrada or pendiente

    if not consulta:
        return

    st.session_state.mensajes.append({"rol": "user", "texto": consulta})
    with st.chat_message("user"):
        st.markdown(consulta)

    with st.chat_message("assistant"):
        with st.spinner("Consultando el corpus y el ITSM..."):
            try:
                respuesta = obtener_asistente().responder(
                    consulta,
                    perfil=st.session_state.perfil,
                    session_id=st.session_state.session_id,
                )
            except config.ErrorDeCuota as error:
                st.warning(str(error))
                return
            except (RuntimeError, FileNotFoundError) as error:
                st.error(str(error))
                return

        st.markdown(respuesta.texto)
        dibujar_fragmentos(respuesta)

    st.session_state.mensajes.append(
        {"rol": "assistant", "texto": respuesta.texto, "respuesta": respuesta}
    )


if __name__ == "__main__":
    # Streamlit ejecuta el archivo como script, de modo que esta guarda se cumple
    # tanto con ``streamlit run src/app.py`` como con ``python src/app.py``.
    main()
