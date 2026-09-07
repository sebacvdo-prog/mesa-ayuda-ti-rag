"""Pruebas de los prompts y del contrato de salida.

Verifican lo que el informe promete: que P1 fija la respuesta literal de
escalamiento y prohíbe credenciales, que P2 trae dos ejemplos con el formato
completo, que P3 tiene los cinco pasos del triage, y que el bloque de fuente está
presente tanto en el prompt como en la respuesta final.
"""

from __future__ import annotations

import json

import pytest

from src import config, prompts
from src.agent import asegurar_bloque_fuente, indica_escalamiento
from tests.utilidades import construir_fragmento_de_prueba


# ---------------------------------------------------------------------------
# P1 · Sistema
# ---------------------------------------------------------------------------


def test_p1_fija_la_respuesta_literal_de_escalamiento() -> None:
    """La frase exacta de "sin procedimiento" está en el prompt de sistema."""
    assert config.RESPUESTA_SIN_PROCEDIMIENTO in prompts.P1_SISTEMA_V1
    assert prompts.RESPUESTA_SIN_PROCEDIMIENTO == config.RESPUESTA_SIN_PROCEDIMIENTO


def test_p1_prohibe_credenciales_y_privilegios_de_administrador() -> None:
    """Las dos prohibiciones centrales están escritas de forma explícita."""
    texto = prompts.P1_SISTEMA_V1.lower()

    assert "nunca entregas" in texto
    assert "contraseñas" in texto
    assert "clave" in texto and "recuperación" in texto
    assert "privilegios de administrador" in texto
    assert "no ejecutas acciones" in texto


def test_p1_exige_el_bloque_de_fuente() -> None:
    """El contrato de salida incluye la línea de fuente con su formato."""
    assert "Fuente: [título del artículo · fecha de vigencia]" in prompts.P1_SISTEMA_V1
    assert "nunca se omite" in prompts.P1_SISTEMA_V1


def test_p1_define_la_precedencia_por_vigencia() -> None:
    """Ante fuentes contradictorias, el prompt ordena preferir la más reciente."""
    assert "fecha de vigencia más reciente" in prompts.P1_SISTEMA_V1


# ---------------------------------------------------------------------------
# P2 · Few-shot
# ---------------------------------------------------------------------------


def test_p2_trae_exactamente_dos_ejemplos() -> None:
    """El few-shot está compuesto por dos ejemplos completos."""
    assert prompts.P2_RESPUESTA_V1.count("=== EJEMPLO") == 2
    assert "=== FIN DE LOS EJEMPLOS ===" in prompts.P2_RESPUESTA_V1


def test_p2_fija_el_formato_de_salida() -> None:
    """Los cuatro componentes del formato aparecen en el prompt."""
    texto = prompts.P2_RESPUESTA_V1

    assert "Diagnóstico probable:" in texto
    assert "Pasos:" in texto
    assert "Prioridad y tiempo comprometido:" in texto
    assert "Escalamiento:" in texto


def test_ambos_ejemplos_terminan_con_bloque_de_fuente() -> None:
    """Los ejemplos enseñan la cita, que es lo que el modelo tiende a omitir."""
    assert prompts.P2_RESPUESTA_V1.count("Fuente: [") >= 2


def test_el_segundo_ejemplo_rechaza_la_entrega_de_credenciales() -> None:
    """El few-shot muestra cómo se responde a un pedido de contraseña."""
    ejemplo = prompts.P2_RESPUESTA_V1.split("=== EJEMPLO 2 ===")[1]

    assert "No entregar ninguna contraseña" in ejemplo
    assert "Nivel 2" in ejemplo


def test_p2_declara_todas_las_variables_de_plantilla() -> None:
    """Las cuatro variables que inyecta el agente están en la plantilla."""
    for variable in ("{perfil}", "{contexto}", "{datos_itsm}", "{pregunta}"):
        assert variable in prompts.P2_RESPUESTA_V1


# ---------------------------------------------------------------------------
# P3 · Triage
# ---------------------------------------------------------------------------


def test_p3_tiene_los_cinco_pasos_del_triage() -> None:
    """El chain-of-thought recorre los cinco pasos, en orden."""
    texto = prompts.P3_TRIAGE_V1

    for numero in range(1, 6):
        assert f"Paso {numero} ·" in texto

    assert texto.index("Paso 1 ·") < texto.index("Paso 5 ·")


def test_p3_describe_el_contenido_de_cada_paso() -> None:
    """Cada paso corresponde al procedimiento real de la mesa."""
    texto = prompts.P3_TRIAGE_V1.lower()

    assert "identificar síntoma y categoría" in texto
    assert "incidentes similares" in texto
    assert "descartar causas verificadas" in texto
    assert "prioridad y sla" in texto
    assert "resolver en nivel 1 o escalar" in texto


def test_p3_declara_el_razonamiento_como_interno() -> None:
    """La cadena de razonamiento no debe mostrarse al agente."""
    assert "razonamiento interno" in prompts.P3_TRIAGE_V1
    assert "No los muestres al usuario" in prompts.P3_TRIAGE_V1


# ---------------------------------------------------------------------------
# Composición del prompt
# ---------------------------------------------------------------------------


def test_mensaje_de_sistema_combina_p1_y_p3() -> None:
    """El mensaje de sistema es P1 seguido del triage P3."""
    mensaje = prompts.construir_mensaje_sistema()

    assert prompts.P1_SISTEMA_V1 in mensaje
    assert prompts.P3_TRIAGE_V1 in mensaje


def test_prompt_de_chat_expone_las_variables_esperadas() -> None:
    """El ChatPromptTemplate declara las variables que pasa el agente."""
    plantilla = prompts.construir_prompt_chat()
    variables = set(plantilla.input_variables)

    assert {"perfil", "contexto", "datos_itsm", "pregunta"} <= variables


def test_prompt_de_chat_incluye_el_bloque_de_fuente_al_formatearse() -> None:
    """Al renderizar el prompt, la exigencia de citar la fuente viaja al modelo."""
    plantilla = prompts.construir_prompt_chat()
    mensajes = plantilla.format_messages(
        perfil="agente",
        contexto="[SIN CONTEXTO RECUPERADO]",
        datos_itsm="(sin datos estructurados)",
        pregunta="¿Cuál es el SLA de un P2?",
        historial=[],
    )
    renderizado = "\n".join(str(m.content) for m in mensajes)

    assert "Fuente:" in renderizado
    assert config.RESPUESTA_SIN_PROCEDIMIENTO in renderizado
    assert "¿Cuál es el SLA de un P2?" in renderizado


def test_registro_de_versiones_de_prompts() -> None:
    """El registro documenta los cuatro prompts y su técnica."""
    resumen = prompts.resumen_prompts()

    assert set(resumen) == {"P1_sistema", "P2_respuesta", "P3_triage", "juez"}
    assert resumen["P2_respuesta"]["tecnica"] == "few-shot con 2 ejemplos"
    assert resumen["P3_triage"]["tecnica"] == "chain-of-thought de 5 pasos"
    assert all(datos["caracteres"] > 0 for datos in resumen.values())


# ---------------------------------------------------------------------------
# Prompt del juez
# ---------------------------------------------------------------------------


def test_prompt_del_juez_define_las_tres_metricas_y_pide_json() -> None:
    """El juez recibe rúbrica y un ejemplo de JSON válido."""
    prompt = prompts.formatear_prompt_juez(
        pregunta="¿Cuál es el SLA de un P2?",
        referencia="30 minutos de primera respuesta.",
        contexto="Fragmento del catálogo de servicios.",
        respuesta="Primera respuesta: 30 minutos.",
    )

    assert "fidelidad" in prompt
    assert "relevancia" in prompt
    assert "precision_contexto" in prompt
    assert "¿Cuál es el SLA de un P2?" in prompt
    assert "{" not in prompt.split("JSON:")[-1], "no deben quedar llaves sin resolver"

    ejemplo = prompt[prompt.index('{"fidelidad"'): prompt.index("}", prompt.index('{"fidelidad"')) + 1]
    assert json.loads(ejemplo)["fidelidad"] == 0.0


# ---------------------------------------------------------------------------
# Contrato de salida en la respuesta final
# ---------------------------------------------------------------------------


def test_asegurar_bloque_fuente_agrega_la_cita_si_el_modelo_la_omite() -> None:
    """Si el modelo omite la fuente, se reconstruye desde los metadatos reales."""
    fragmentos = [
        construir_fragmento_de_prueba(
            documento="kb_accesos_y_cuentas.md",
            titulo="KB-ACC-01 · Cuentas y accesos",
            fecha="2026-04-20",
        )
    ]
    texto = asegurar_bloque_fuente("Diagnóstico probable: cuenta bloqueada.", fragmentos)

    assert texto.endswith("Fuente: [KB-ACC-01 · Cuentas y accesos · 2026-04-20]")


def test_asegurar_bloque_fuente_no_duplica_la_cita() -> None:
    """Si el modelo ya citó, no se agrega una segunda línea."""
    fragmentos = [construir_fragmento_de_prueba()]
    original = "Pasos: 1. Verificar.\n\nFuente: [KB-ACC-01 · 2026-04-20]"

    assert asegurar_bloque_fuente(original, fragmentos) == original


def test_la_respuesta_literal_de_escalamiento_va_sola() -> None:
    """La respuesta de "sin procedimiento" no lleva bloque de fuente."""
    resultado = asegurar_bloque_fuente(config.RESPUESTA_SIN_PROCEDIMIENTO, [])

    assert resultado == config.RESPUESTA_SIN_PROCEDIMIENTO
    assert "Fuente:" not in resultado


@pytest.mark.parametrize(
    ("texto", "esperado"),
    [
        ("Corresponde escalar a Nivel 2 por privilegios.", True),
        ("Se resuelve en Nivel 1 con el reinicio del cliente.", False),
        ("Escalamiento: no aplica, se cierra en primer contacto.", False),
    ],
)
def test_deteccion_de_escalamiento(texto: str, esperado: bool) -> None:
    """La marca de escalamiento se deduce del texto de la respuesta."""
    assert indica_escalamiento(texto) is esperado
