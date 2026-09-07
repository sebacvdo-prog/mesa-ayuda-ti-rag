"""Interfaz de consola del asistente de la mesa de ayuda.

Modo conversación con selector de perfil. Mantiene el contexto entre turnos, así
que se puede diagnosticar como en una atención real: reportar el síntoma,
responder las repreguntas y llegar a la decisión de escalamiento.

Uso:
    python -m src.cli
    python -m src.cli --perfil usuario_final
    python -m src.cli --pregunta "¿Cuál es el SLA de un ticket P2?"
"""

from __future__ import annotations

import argparse
import sys

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from src import config
from src.agent import AsistenteMesaAyuda, RespuestaAsistente, crear_asistente

ANCHO: int = 78

AYUDA_COMANDOS: str = """
Comandos disponibles:
  /ayuda              Muestra esta ayuda
  /perfil agente      Cambia al perfil de agente de la mesa (ve todo el corpus)
  /perfil usuario     Cambia al perfil de usuario final (solo publico_interno)
  /fuentes            Muestra los fragmentos recuperados en la última respuesta
  /reiniciar          Borra la memoria de la conversación
  /salir              Termina la sesión
"""


def imprimir_encabezado(perfil: str) -> None:
    """Imprime la cabecera de la sesión.

    Args:
        perfil: Perfil activo.
    """
    print("=" * ANCHO)
    print("ASISTENTE DE LA MESA DE AYUDA TI · Aconcagua Logística SpA")
    print("=" * ANCHO)
    print(f"Perfil activo: {perfil}")
    print(f"Modelo de chat: {config.MODELO_CHAT} (temperatura {config.TEMPERATURA})")
    print(f"Recuperación: top_k={config.TOP_K}, umbral={config.UMBRAL_SIMILITUD}")
    print("El asistente no ejecuta acciones ni entrega credenciales.")
    print(AYUDA_COMANDOS)


def imprimir_respuesta(respuesta: RespuestaAsistente) -> None:
    """Muestra la respuesta y su trazabilidad resumida.

    Args:
        respuesta: Resultado devuelto por el asistente.
    """
    print("\n" + "-" * ANCHO)
    print(respuesta.texto)
    print("-" * ANCHO)

    detalles = [
        f"consulta: {respuesta.clasificacion}",
        f"perfil: {respuesta.perfil}",
        f"fragmentos: {len(respuesta.fragmentos)}",
        f"escalamiento: {'sí' if respuesta.escalamiento else 'no'}",
    ]
    if respuesta.motivo != "ok":
        detalles.append(f"motivo: {respuesta.motivo}")
    if respuesta.enmascarados:
        enmascarados = ", ".join(
            f"{tipo}:{cantidad}" for tipo, cantidad in sorted(respuesta.enmascarados.items())
        )
        detalles.append(f"enmascarado ({enmascarados})")
    print("[" + " · ".join(detalles) + "]")


def imprimir_fuentes(respuesta: RespuestaAsistente | None) -> None:
    """Muestra los fragmentos recuperados con su puntaje y vigencia.

    Args:
        respuesta: Última respuesta, o ``None`` si todavía no hubo consultas.
    """
    if respuesta is None:
        print("Todavía no hay una consulta en esta sesión.")
        return
    if not respuesta.fragmentos:
        print("La última respuesta no usó fragmentos del corpus.")
        return

    print("\nFragmentos recuperados:")
    for indice, fragmento in enumerate(respuesta.fragmentos, start=1):
        metadatos = fragmento.documento.metadata
        print(f"  {indice}. {fragmento.titulo}")
        print(
            f"     archivo: {fragmento.nombre_documento} · "
            f"fuente: {metadatos.get('fuente')} · "
            f"vigencia: {metadatos.get('fecha_vigencia')} · "
            f"similitud: {fragmento.puntaje:.3f}"
        )
        extracto = " ".join(fragmento.documento.page_content.split())[:180]
        print(f"     «{extracto}...»")


def consultar(
    asistente: AsistenteMesaAyuda, pregunta: str, perfil: str
) -> RespuestaAsistente | None:
    """Ejecuta una consulta capturando los errores esperables.

    Args:
        asistente: Asistente ya construido.
        pregunta: Consulta del usuario.
        perfil: Perfil activo.

    Returns:
        La respuesta, o ``None`` si la consulta no se pudo completar.
    """
    try:
        return asistente.responder(pregunta, perfil=perfil)
    except config.ErrorDeCuota as error:
        print(f"\n{error}")
    except FileNotFoundError as error:
        print(f"\n{error}")
    except RuntimeError as error:
        print(f"\nNo se pudo responder: {error}")
    return None


def bucle_conversacion(asistente: AsistenteMesaAyuda, perfil: str) -> None:
    """Bucle principal de la conversación.

    Args:
        asistente: Asistente ya construido.
        perfil: Perfil inicial.
    """
    imprimir_encabezado(perfil)
    ultima: RespuestaAsistente | None = None

    while True:
        try:
            entrada = input("\nConsulta> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nSesión terminada.")
            return

        if not entrada:
            continue

        comando = entrada.lower()
        if comando in ("/salir", "/exit", "/quit"):
            print("Sesión terminada.")
            return
        if comando == "/ayuda":
            print(AYUDA_COMANDOS)
            continue
        if comando == "/reiniciar":
            asistente.reiniciar()
            ultima = None
            print("Memoria de la conversación borrada.")
            continue
        if comando == "/fuentes":
            imprimir_fuentes(ultima)
            continue
        if comando.startswith("/perfil"):
            partes = comando.split()
            if len(partes) < 2:
                print(f"Perfil activo: {perfil}")
                continue
            nuevo = "usuario_final" if partes[1].startswith("usuario") else "agente"
            perfil = nuevo
            print(f"Perfil cambiado a: {perfil}")
            continue

        respuesta = consultar(asistente, entrada, perfil)
        if respuesta is not None:
            ultima = respuesta
            imprimir_respuesta(respuesta)


def main() -> None:
    """Punto de entrada de consola."""
    parser = argparse.ArgumentParser(
        description="Asistente RAG de la mesa de ayuda TI de Aconcagua Logística."
    )
    parser.add_argument(
        "--perfil",
        choices=list(config.PERFILES_VALIDOS),
        default="agente",
        help="Perfil con el que se consulta (por defecto: agente).",
    )
    parser.add_argument(
        "--pregunta",
        help="Ejecuta una única consulta y termina, sin entrar al modo conversación.",
    )
    argumentos = parser.parse_args()

    problemas = config.validar_configuracion()
    if problemas:
        print("Falta configuración para poder responder:")
        for problema in problemas:
            print(f"  - {problema}")
        print("\nCopiá .env.example como .env y completá las claves.")
        raise SystemExit(1)

    if not config.archivo_existe(config.DIR_INDICE_FAISS / "index.faiss"):
        print(
            "No existe el índice FAISS. Construilo primero:\n"
            "  python data/seed_db.py\n"
            "  python -m src.ingest"
        )
        raise SystemExit(1)

    asistente = crear_asistente()

    if argumentos.pregunta:
        respuesta = consultar(asistente, argumentos.pregunta, argumentos.perfil)
        if respuesta is None:
            raise SystemExit(2)
        imprimir_respuesta(respuesta)
        imprimir_fuentes(respuesta)
        return

    bucle_conversacion(asistente, argumentos.perfil)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nSesión interrumpida.")
        sys.exit(130)
