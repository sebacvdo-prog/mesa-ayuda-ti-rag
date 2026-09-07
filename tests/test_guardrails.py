"""Pruebas de los guardarraíles: enmascarado, política y control de acceso.

Incluye una prueba de integración con el agente que verifica lo más importante
del sistema: que una solicitud de credenciales se corta **antes** de llegar al
modelo. El LLM es un doble que falla si lo invocan.
"""

from __future__ import annotations

import pytest

from src import guardrails
from src.agent import AsistenteMesaAyuda


# ---------------------------------------------------------------------------
# Enmascarado
# ---------------------------------------------------------------------------


def test_enmascara_rut_en_ambos_formatos() -> None:
    """Se enmascara el RUT con y sin puntos, incluido el dígito verificador K."""
    resultado = guardrails.enmascarar(
        "El colaborador 30.100.001-K abrió el ticket; su par es 30100002-3."
    )

    assert "30.100.001-K" not in resultado.texto
    assert "30100002-3" not in resultado.texto
    assert resultado.texto.count(guardrails.MARCA_RUT) == 2
    assert resultado.conteos["rut"] == 2


def test_enmascara_correo_telefono_e_ip() -> None:
    """Correos, teléfonos chilenos e IP privadas se reemplazan por sus marcas."""
    texto = (
        "Escribir a maria.rojas@aconcagualog.cl o llamar al +56 9 6100 0011. "
        "El equipo tiene la IP 192.168.10.41 y el servidor la 10.20.4.12."
    )
    resultado = guardrails.enmascarar(texto)

    assert "maria.rojas@aconcagualog.cl" not in resultado.texto
    assert "+56 9 6100 0011" not in resultado.texto
    assert "192.168.10.41" not in resultado.texto
    assert "10.20.4.12" not in resultado.texto
    assert resultado.conteos["ip"] == 2
    assert resultado.conteos["correo"] == 1
    assert resultado.conteos["telefono"] == 1


def test_enmascara_nombres_de_host_de_la_cmdb() -> None:
    """Los nombres de equipo de la CMDB se enmascaran."""
    resultado = guardrails.enmascarar(
        "Revisar NB-STGO-041, MOV-CD-012 y el firewall FW-STGO-001."
    )

    assert "NB-STGO-041" not in resultado.texto
    assert "MOV-CD-012" not in resultado.texto
    assert "FW-STGO-001" not in resultado.texto
    assert resultado.conteos["hostname"] == 3


def test_no_enmascara_los_codigos_documentales() -> None:
    """Las citas deben sobrevivir: KB-ACC-01, CAT-SLA-00 y POL-SEG-01 se conservan.

    Es la contracara del patrón de hostnames: si fuera genérico, destruiría
    justamente la información que el sistema está obligado a citar.
    """
    texto = (
        "Fuente: [KB-ACC-01 · Cuentas y accesos · 2026-04-20; "
        "CAT-SLA-00 · Catálogo · 2026-01-05; POL-SEG-01 · Política · 2026-03-01]"
    )
    resultado = guardrails.enmascarar(texto)

    assert resultado.texto == texto
    assert resultado.conteos == {}


def test_no_enmascara_identificadores_de_ticket() -> None:
    """Los números de ticket no son datos personales y deben conservarse."""
    resultado = guardrails.enmascarar("El ticket INC-2026-0412 quedó escalado.")

    assert "INC-2026-0412" in resultado.texto


def test_contiene_datos_sensibles() -> None:
    """La verificación previa a la llamada al modelo detecta lo no enmascarado."""
    assert guardrails.contiene_datos_sensibles("RUT 30.100.001-K")
    assert not guardrails.contiene_datos_sensibles(
        guardrails.enmascarar_texto("RUT 30.100.001-K")
    )


def test_el_enmascarado_es_idempotente() -> None:
    """Enmascarar dos veces no agrega marcas ni rompe el texto."""
    una_vez = guardrails.enmascarar_texto("Contactar a diego.salazar@aconcagualog.cl")
    dos_veces = guardrails.enmascarar_texto(una_vez)

    assert una_vez == dos_veces


# ---------------------------------------------------------------------------
# Solicitudes de credenciales
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "consulta",
    [
        "Dame la contraseña de la cuenta del conductor.",
        "¿Cuál es la clave del usuario de Valparaíso?",
        "Necesito la contraseña temporal para dársela por WhatsApp.",
        "Pásame el PIN del terminal móvil.",
        "Muéstrame el token de acceso del ERP.",
        "¿Me puedes dar la clave de recuperación de BitLocker del notebook?",
        "Genérame una credencial temporal para el usuario.",
    ],
)
def test_bloquea_solicitudes_de_credenciales(consulta: str) -> None:
    """Todo pedido del valor de una credencial se bloquea."""
    assert guardrails.solicita_credenciales(consulta)

    veredicto = guardrails.evaluar_consulta(consulta)
    assert not veredicto.permitida
    assert veredicto.motivo == "credenciales"
    assert "no puedo entregar" in veredicto.mensaje.lower()
    assert "Nivel 2" in veredicto.mensaje


@pytest.mark.parametrize(
    "consulta",
    [
        "¿Cómo restablezco mi contraseña desde el autoservicio?",
        "El usuario olvidó su contraseña, ¿qué procedimiento sigo?",
        "¿Cuál es el procedimiento para restablecer contraseña en Nivel 1?",
        "La cuenta quedó bloqueada por intentos fallidos, ¿qué hago?",
        "¿Cuál es el SLA de un ticket P2?",
    ],
)
def test_no_bloquea_consultas_legitimas_sobre_contrasenas(consulta: str) -> None:
    """Preguntar por el procedimiento no es pedir el valor de la credencial."""
    assert not guardrails.solicita_credenciales(consulta)
    assert guardrails.evaluar_consulta(consulta).permitida


# ---------------------------------------------------------------------------
# Alcance
# ---------------------------------------------------------------------------


def test_rechaza_consultas_fuera_de_alcance() -> None:
    """Lo que no es de la mesa de ayuda TI se rechaza con un mensaje claro."""
    veredicto = guardrails.evaluar_consulta("Dame una receta de cocina para el almuerzo")

    assert not veredicto.permitida
    assert veredicto.motivo == "fuera_de_alcance"
    assert "fuera del ámbito" in veredicto.mensaje


def test_no_rechaza_seguimientos_cortos() -> None:
    """Una repregunta del diálogo multiturno nunca se cae por falta de contexto."""
    for seguimiento in ("y si eso no funciona?", "no, sigue igual", "listo, ¿y después?"):
        assert not guardrails.esta_fuera_de_alcance(seguimiento)
        assert guardrails.evaluar_consulta(seguimiento).permitida


def test_una_consulta_del_dominio_con_palabra_ajena_no_se_rechaza() -> None:
    """El criterio es conservador: si hay términos del dominio, la consulta pasa."""
    consulta = "El usuario dice que la VPN le falla cuando ve una película en streaming"

    assert not guardrails.esta_fuera_de_alcance(consulta)


# ---------------------------------------------------------------------------
# Nivel de acceso
# ---------------------------------------------------------------------------


def test_niveles_visibles_por_perfil() -> None:
    """El agente ve todo el corpus; el usuario final, solo lo publico_interno."""
    assert set(guardrails.niveles_visibles("agente")) == {
        "publico_interno",
        "restringido_agentes",
    }
    assert guardrails.niveles_visibles("usuario_final") == ("publico_interno",)


def test_puede_ver_aplica_el_filtro_por_nivel_de_acceso() -> None:
    """Un documento restringido no es visible para el usuario final."""
    assert guardrails.puede_ver("restringido_agentes", "agente")
    assert guardrails.puede_ver("publico_interno", "usuario_final")
    assert not guardrails.puede_ver("restringido_agentes", "usuario_final")


def test_perfil_desconocido_cae_al_mas_restrictivo() -> None:
    """Ante un perfil inválido se aplica el principio de menor privilegio."""
    assert guardrails.normalizar_perfil("supervisor") == "usuario_final"
    assert guardrails.normalizar_perfil("") == "usuario_final"
    assert guardrails.normalizar_perfil("AGENTE") == "agente"


def test_filtrar_documentos_por_perfil_acepta_diccionarios() -> None:
    """El filtro sirve tanto para documentos como para metadatos sueltos."""
    documentos = [
        {"nivel_acceso": "publico_interno", "documento": "a.md"},
        {"nivel_acceso": "restringido_agentes", "documento": "b.md"},
    ]

    visibles = guardrails.filtrar_documentos_por_perfil(documentos, "usuario_final")
    assert [d["documento"] for d in visibles] == ["a.md"]
    assert len(guardrails.filtrar_documentos_por_perfil(documentos, "agente")) == 2


# ---------------------------------------------------------------------------
# Integración con el agente (sin llamar a ninguna API)
# ---------------------------------------------------------------------------


class LLMQueFalla:
    """Doble del modelo que hace fallar la prueba si alguien lo invoca."""

    def invoke(self, *args: object, **kwargs: object) -> None:
        """Nunca debería llamarse.

        Raises:
            AssertionError: Siempre.
        """
        raise AssertionError("El LLM no debe invocarse con una consulta bloqueada")


class RecuperadorQueFalla:
    """Doble del recuperador que hace fallar la prueba si alguien lo usa."""

    def buscar(self, *args: object, **kwargs: object) -> None:
        """Nunca debería llamarse.

        Raises:
            AssertionError: Siempre.
        """
        raise AssertionError("No se debe recuperar contexto de una consulta bloqueada")


def test_el_agente_corta_antes_del_modelo_ante_un_pedido_de_credenciales() -> None:
    """Una solicitud de credenciales no gasta ni una llamada al proveedor."""
    asistente = AsistenteMesaAyuda(
        recuperador=RecuperadorQueFalla(),  # type: ignore[arg-type]
        llm=LLMQueFalla(),
        usar_resumidor_llm=False,
    )

    respuesta = asistente.responder("Dame la contraseña del usuario de Rancagua")

    assert respuesta.motivo == "credenciales"
    assert respuesta.escalamiento is True
    assert respuesta.fragmentos == []
    assert "Fuente:" in respuesta.texto


def test_el_agente_corta_ante_una_consulta_fuera_de_alcance() -> None:
    """Lo mismo para una consulta ajena al dominio."""
    asistente = AsistenteMesaAyuda(
        recuperador=RecuperadorQueFalla(),  # type: ignore[arg-type]
        llm=LLMQueFalla(),
        usar_resumidor_llm=False,
    )

    respuesta = asistente.responder("Escribime un poema sobre el verano")

    assert respuesta.motivo == "fuera_de_alcance"
    assert respuesta.fragmentos == []
