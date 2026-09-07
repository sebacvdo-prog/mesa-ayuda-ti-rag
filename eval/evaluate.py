"""Evaluación del asistente con un LLM juez.

Recorre ``data/evaluacion/dataset.json``, ejecuta el sistema sobre cada pregunta
y puntúa tres métricas en escala 0–1 con un modelo juez a ``temperature=0``:

* **fidelidad**: si todo lo afirmado está respaldado por el contexto recuperado.
* **relevancia**: si responde lo preguntado con el formato exigido.
* **precision_contexto**: si los fragmentos recuperados eran los pertinentes.

Además se calcula una métrica objetiva que no depende del juez,
**acierto_de_fuente**: si el documento esperado por el dataset aparece entre los
fragmentos recuperados. Sirve de contraste cuando el juez es generoso.

Los resultados se escriben en ``eval/resultados/`` como ``.json`` (detalle por
pregunta) y ``.md`` (tabla resumen y promedios).

Uso:
    python -m eval.evaluate
    python -m eval.evaluate --limite 5
    python -m eval.evaluate --perfil usuario_final
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from datetime import datetime
from pathlib import Path
from typing import Any

from src import config, prompts
from src.agent import RespuestaAsistente, crear_asistente

METRICAS: tuple[str, ...] = ("fidelidad", "relevancia", "precision_contexto")

_PATRON_JSON = re.compile(r"\{.*\}", re.DOTALL)


def _leer_archivo(ruta: Path) -> str:
    """Lee un archivo de texto manejando rutas largas en Windows."""
    ruta_str = str(ruta.resolve())
    if os.name == "nt" and len(ruta_str) >= 240 and not ruta_str.startswith("\\\\?\\"):
        ruta_str = f"\\\\?\\{ruta_str}"
    with open(ruta_str, encoding="utf-8") as archivo:
        return archivo.read()


def _escribir_archivo(ruta: Path, texto: str) -> None:
    """Escribe un archivo de texto manejando rutas largas en Windows."""
    ruta_str = str(ruta.resolve())
    if os.name == "nt" and len(ruta_str) >= 240 and not ruta_str.startswith("\\\\?\\"):
        ruta_str = f"\\\\?\\{ruta_str}"
    with open(ruta_str, "w", encoding="utf-8") as archivo:
        archivo.write(texto)


# ---------------------------------------------------------------------------
# Dataset
# ---------------------------------------------------------------------------


def cargar_dataset(ruta: Path = config.RUTA_DATASET) -> dict[str, Any]:
    """Carga el dataset de evaluación.

    Args:
        ruta: Ruta del archivo JSON.

    Returns:
        Diccionario del dataset.

    Raises:
        FileNotFoundError: Si el archivo no existe.
    """
    if not ruta.exists():
        raise FileNotFoundError(f"No se encuentra el dataset de evaluación: {ruta}")
    return json.loads(_leer_archivo(ruta))


# ---------------------------------------------------------------------------
# Juez
# ---------------------------------------------------------------------------


def extraer_json(texto: str) -> dict[str, Any]:
    """Extrae el primer objeto JSON de la salida del juez.

    Los modelos suelen envolver el JSON en texto o en un bloque de código pese a
    la instrucción; en vez de fallar, se busca el objeto dentro de la respuesta.

    Args:
        texto: Salida cruda del modelo juez.

    Returns:
        Diccionario con las métricas.

    Raises:
        ValueError: Si no hay JSON interpretable en la respuesta.
    """
    coincidencia = _PATRON_JSON.search(texto)
    if not coincidencia:
        raise ValueError(f"El juez no devolvió JSON: {texto[:200]}")
    return json.loads(coincidencia.group(0))


def puntuar_con_juez(
    juez: Any, pregunta: str, referencia: str, contexto: str, respuesta: str
) -> dict[str, Any]:
    """Pide al modelo juez las tres métricas de una respuesta.

    Args:
        juez: Modelo de chat configurado a temperatura 0.
        pregunta: Pregunta del dataset.
        referencia: Respuesta de referencia.
        contexto: Contexto que usó el sistema.
        respuesta: Respuesta que produjo el sistema.

    Returns:
        Diccionario con las métricas y la justificación. Si el juez falla al
        devolver JSON, se registra el error y las métricas quedan en ``None``
        para no contaminar los promedios con ceros inventados.
    """
    prompt = prompts.formatear_prompt_juez(pregunta, referencia, contexto, respuesta)
    salida = config.reintentar_con_backoff(juez.invoke, prompt)
    texto = str(getattr(salida, "content", salida))

    try:
        datos = extraer_json(texto)
    except (ValueError, json.JSONDecodeError) as error:
        return {
            "fidelidad": None,
            "relevancia": None,
            "precision_contexto": None,
            "justificacion": f"No se pudo interpretar la salida del juez: {error}",
            "error_juez": True,
        }

    resultado: dict[str, Any] = {"error_juez": False}
    for metrica in METRICAS:
        valor = datos.get(metrica)
        try:
            resultado[metrica] = max(0.0, min(1.0, float(valor)))
        except (TypeError, ValueError):
            resultado[metrica] = None
    resultado["justificacion"] = str(datos.get("justificacion", ""))[:400]
    return resultado


# ---------------------------------------------------------------------------
# Métricas objetivas
# ---------------------------------------------------------------------------


def acierto_de_fuente(respuesta: RespuestaAsistente, fuente_esperada: str) -> bool | None:
    """Indica si el documento esperado está entre los fragmentos recuperados.

    Args:
        respuesta: Respuesta del asistente.
        fuente_esperada: Nombre de archivo esperado, o ``ninguna``.

    Returns:
        ``True`` o ``False``, o ``None`` cuando el dataset no espera fuente
        (preguntas cuya respuesta correcta es que no hay procedimiento).
    """
    if fuente_esperada in ("", "ninguna"):
        return None
    documentos = {fragmento.nombre_documento for fragmento in respuesta.fragmentos}
    return fuente_esperada in documentos


def promedio(valores: list[float]) -> float | None:
    """Promedia una lista, tolerando que esté vacía.

    Args:
        valores: Valores numéricos.

    Returns:
        El promedio, o ``None`` si no hay valores.
    """
    return round(sum(valores) / len(valores), 3) if valores else None


# ---------------------------------------------------------------------------
# Corrida
# ---------------------------------------------------------------------------


def evaluar(
    limite: int | None = None,
    perfil: str | None = None,
    pausa: float = 1.0,
) -> dict[str, Any]:
    """Ejecuta la evaluación completa.

    Args:
        limite: Evalúa solo las primeras N preguntas (útil para no gastar cuota).
        perfil: Perfil con el que se consulta. Por defecto, el del dataset.
        pausa: Segundos de espera entre preguntas, para no saturar la cuota.

    Returns:
        Diccionario con la corrida completa: metadatos, detalle y resumen.
    """
    dataset = cargar_dataset()
    preguntas = dataset["preguntas"][:limite] if limite else dataset["preguntas"]
    perfil = perfil or dataset.get("perfil_por_defecto", "agente")

    asistente = crear_asistente()
    juez = config.crear_llm(temperatura=config.TEMPERATURA_JUEZ, max_tokens=400)

    inicio = datetime.now()
    detalle: list[dict[str, Any]] = []

    print("=" * 78)
    print("EVALUACIÓN DEL ASISTENTE RAG · Mesa de Ayuda TI")
    print("=" * 78)
    print(f"Dataset: {dataset.get('nombre')} v{dataset.get('version')}")
    print(f"Preguntas: {len(preguntas)} · Perfil: {perfil}")
    print(f"Modelo evaluado: {config.MODELO_CHAT} (temperatura {config.TEMPERATURA})")
    print(f"Modelo juez: {config.MODELO_CHAT} (temperatura {config.TEMPERATURA_JUEZ})")
    print("-" * 78)

    for indice, caso in enumerate(preguntas, start=1):
        identificador = caso["id"]
        print(f"[{indice:>2}/{len(preguntas)}] {identificador} · {caso['categoria']}")

        # Cada pregunta usa su propia sesión: la evaluación mide respuestas
        # individuales, no el comportamiento multiturno.
        respuesta = asistente.responder(
            caso["pregunta"], perfil=perfil, session_id=f"eval-{identificador}"
        )

        puntajes = puntuar_con_juez(
            juez,
            caso["pregunta"],
            caso["respuesta_referencia"],
            respuesta.contexto,
            respuesta.texto,
        )

        registro = {
            "id": identificador,
            "categoria": caso["categoria"],
            "pregunta": caso["pregunta"],
            "respuesta_referencia": caso["respuesta_referencia"],
            "respuesta_sistema": respuesta.texto,
            "fuente_esperada": caso["fuente_esperada"],
            "fuentes_recuperadas": [f.nombre_documento for f in respuesta.fragmentos],
            "puntajes_similitud": [round(f.puntaje, 4) for f in respuesta.fragmentos],
            "clasificacion": respuesta.clasificacion,
            "motivo": respuesta.motivo,
            "escalamiento": respuesta.escalamiento,
            "acierto_fuente": acierto_de_fuente(respuesta, caso["fuente_esperada"]),
            **puntajes,
        }
        detalle.append(registro)

        resumen_linea = " · ".join(
            f"{metrica[:4]}={registro[metrica] if registro[metrica] is not None else 's/d'}"
            for metrica in METRICAS
        )
        print(f"          {resumen_linea} · fuente_ok={registro['acierto_fuente']}")

        if pausa and indice < len(preguntas):
            time.sleep(pausa)

    resumen = construir_resumen(detalle)
    corrida: dict[str, Any] = {
        "fecha": inicio.isoformat(timespec="seconds"),
        "duracion_segundos": round((datetime.now() - inicio).total_seconds(), 1),
        "dataset": {"nombre": dataset.get("nombre"), "version": dataset.get("version")},
        "perfil": perfil,
        "configuracion": {
            "modelo_chat": config.MODELO_CHAT,
            "modelo_embeddings": config.MODELO_EMBEDDINGS,
            "dimension_embeddings": config.DIMENSION_EMBEDDINGS,
            "chunk_size": config.TAMANO_CHUNK,
            "chunk_overlap": config.SOLAPE_CHUNK,
            "top_k": config.TOP_K,
            "umbral_similitud": config.UMBRAL_SIMILITUD,
            "temperatura": config.TEMPERATURA,
            "temperatura_juez": config.TEMPERATURA_JUEZ,
            "version_prompts": prompts.VERSION_PROMPTS,
        },
        "resumen": resumen,
        "detalle": detalle,
    }
    return corrida


def construir_resumen(detalle: list[dict[str, Any]]) -> dict[str, Any]:
    """Calcula promedios globales y por categoría.

    Args:
        detalle: Registros de cada pregunta evaluada.

    Returns:
        Diccionario con los promedios globales, por categoría y los conteos.
    """
    globales = {
        metrica: promedio([r[metrica] for r in detalle if r[metrica] is not None])
        for metrica in METRICAS
    }

    por_categoria: dict[str, dict[str, Any]] = {}
    for registro in detalle:
        categoria = registro["categoria"]
        grupo = por_categoria.setdefault(categoria, {"casos": 0})
        grupo["casos"] += 1
    for categoria, grupo in por_categoria.items():
        casos = [r for r in detalle if r["categoria"] == categoria]
        for metrica in METRICAS:
            grupo[metrica] = promedio(
                [r[metrica] for r in casos if r[metrica] is not None]
            )

    aciertos = [r["acierto_fuente"] for r in detalle if r["acierto_fuente"] is not None]
    return {
        "casos": len(detalle),
        "promedios": globales,
        "por_categoria": por_categoria,
        "acierto_de_fuente": {
            "evaluados": len(aciertos),
            "aciertos": sum(1 for a in aciertos if a),
            "tasa": round(sum(1 for a in aciertos if a) / len(aciertos), 3)
            if aciertos
            else None,
        },
        "escalamientos": sum(1 for r in detalle if r["escalamiento"]),
        "errores_del_juez": sum(1 for r in detalle if r.get("error_juez")),
    }


# ---------------------------------------------------------------------------
# Salidas
# ---------------------------------------------------------------------------


def _formatear(valor: Any) -> str:
    """Formatea un valor de métrica para la tabla Markdown.

    Args:
        valor: Número o ``None``.

    Returns:
        Texto con tres decimales, o ``s/d``.
    """
    return f"{valor:.3f}" if isinstance(valor, (int, float)) else "s/d"


def escribir_resultados(corrida: dict[str, Any], directorio: Path | None = None) -> tuple[Path, Path]:
    """Escribe el detalle en ``.json`` y el resumen en ``.md``.

    Args:
        corrida: Resultado de :func:`evaluar`.
        directorio: Carpeta de salida. Por defecto ``eval/resultados``.

    Returns:
        Tupla con las rutas del archivo JSON y del Markdown.
    """
    directorio = directorio or config.DIR_RESULTADOS_EVAL
    directorio.mkdir(parents=True, exist_ok=True)
    marca = datetime.fromisoformat(corrida["fecha"]).strftime("%Y%m%d-%H%M%S")

    ruta_json = directorio / f"evaluacion-{marca}.json"
    _escribir_archivo(
        ruta_json, json.dumps(corrida, ensure_ascii=False, indent=2)
    )

    resumen = corrida["resumen"]
    lineas: list[str] = [
        "# Resultados de evaluación · Asistente RAG Mesa de Ayuda TI",
        "",
        f"- **Fecha de la corrida:** {corrida['fecha']}",
        f"- **Duración:** {corrida['duracion_segundos']} s",
        f"- **Dataset:** {corrida['dataset']['nombre']} v{corrida['dataset']['version']}",
        f"- **Perfil:** {corrida['perfil']}",
        f"- **Casos evaluados:** {resumen['casos']}",
        "",
        "## Configuración de la corrida",
        "",
        "| Parámetro | Valor |",
        "|---|---|",
    ]
    for clave, valor in corrida["configuracion"].items():
        lineas.append(f"| {clave} | `{valor}` |")

    lineas += [
        "",
        "## Promedios globales",
        "",
        "| Métrica | Promedio |",
        "|---|---|",
        f"| Fidelidad | {_formatear(resumen['promedios']['fidelidad'])} |",
        f"| Relevancia de la respuesta | {_formatear(resumen['promedios']['relevancia'])} |",
        f"| Precisión del contexto | {_formatear(resumen['promedios']['precision_contexto'])} |",
        "",
        f"- **Acierto de fuente** (métrica objetiva, sin juez): "
        f"{resumen['acierto_de_fuente']['aciertos']}/"
        f"{resumen['acierto_de_fuente']['evaluados']} "
        f"({_formatear(resumen['acierto_de_fuente']['tasa'])})",
        f"- **Respuestas con escalamiento a Nivel 2:** {resumen['escalamientos']}",
        f"- **Fallos de formato del juez:** {resumen['errores_del_juez']}",
        "",
        "## Promedios por categoría",
        "",
        "| Categoría | Casos | Fidelidad | Relevancia | Precisión de contexto |",
        "|---|---|---|---|---|",
    ]
    for categoria, grupo in sorted(corrida["resumen"]["por_categoria"].items()):
        lineas.append(
            f"| {categoria} | {grupo['casos']} | {_formatear(grupo['fidelidad'])} | "
            f"{_formatear(grupo['relevancia'])} | "
            f"{_formatear(grupo['precision_contexto'])} |"
        )

    lineas += [
        "",
        "## Detalle por pregunta",
        "",
        "| ID | Categoría | Fid. | Rel. | Prec. | Fuente esperada | ¿Recuperada? | Escala |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for registro in corrida["detalle"]:
        acierto = registro["acierto_fuente"]
        marca_acierto = "n/a" if acierto is None else ("sí" if acierto else "no")
        lineas.append(
            f"| {registro['id']} | {registro['categoria']} | "
            f"{_formatear(registro['fidelidad'])} | {_formatear(registro['relevancia'])} | "
            f"{_formatear(registro['precision_contexto'])} | "
            f"`{registro['fuente_esperada']}` | {marca_acierto} | "
            f"{'sí' if registro['escalamiento'] else 'no'} |"
        )

    lineas += [
        "",
        "## Justificaciones del juez",
        "",
    ]
    for registro in corrida["detalle"]:
        lineas.append(f"- **{registro['id']}**: {registro.get('justificacion', '')}")

    lineas += [
        "",
        "---",
        "",
        f"Detalle completo (respuestas íntegras incluidas): `{ruta_json.name}`.",
        "",
    ]

    ruta_md = directorio / f"evaluacion-{marca}.md"
    _escribir_archivo(ruta_md, "\n".join(lineas))
    return ruta_json, ruta_md


def imprimir_resumen(corrida: dict[str, Any]) -> None:
    """Imprime el resumen de la corrida en consola.

    Args:
        corrida: Resultado de :func:`evaluar`.
    """
    resumen = corrida["resumen"]
    print("-" * 78)
    print("RESUMEN")
    print("-" * 78)
    for metrica in METRICAS:
        print(f"  {metrica:<22} {_formatear(resumen['promedios'][metrica])}")
    print(
        f"  {'acierto_de_fuente':<22} "
        f"{resumen['acierto_de_fuente']['aciertos']}/"
        f"{resumen['acierto_de_fuente']['evaluados']}"
    )
    print(f"  {'escalamientos':<22} {resumen['escalamientos']}")
    print(f"  {'errores del juez':<22} {resumen['errores_del_juez']}")


def main() -> None:
    """Punto de entrada de consola."""
    parser = argparse.ArgumentParser(
        description="Evalúa el asistente RAG con un LLM juez a temperatura 0."
    )
    parser.add_argument(
        "--limite", type=int, default=None,
        help="Evalúa solo las primeras N preguntas (cuida la cuota diaria).",
    )
    parser.add_argument(
        "--perfil", choices=list(config.PERFILES_VALIDOS), default=None,
        help="Perfil con el que se consulta (por defecto, el del dataset).",
    )
    parser.add_argument(
        "--pausa", type=float, default=1.0,
        help="Segundos de espera entre preguntas (por defecto 1.0).",
    )
    argumentos = parser.parse_args()

    problemas = config.validar_configuracion()
    if problemas:
        print("Falta configuración para evaluar:")
        for problema in problemas:
            print(f"  - {problema}")
        raise SystemExit(1)

    if not config.archivo_existe(config.DIR_INDICE_FAISS / "index.faiss"):
        print("No existe el índice FAISS. Ejecutá primero: python -m src.ingest")
        raise SystemExit(1)

    try:
        corrida = evaluar(
            limite=argumentos.limite, perfil=argumentos.perfil, pausa=argumentos.pausa
        )
    except config.ErrorDeCuota as error:
        print(f"\n{error}")
        print(
            "\nSugerencia: volvé a correr con --limite 5 cuando se reponga la cuota, "
            "o usá otra clave."
        )
        raise SystemExit(2) from error

    imprimir_resumen(corrida)
    ruta_json, ruta_md = escribir_resultados(corrida)
    print(f"\nResultados escritos en:\n  {ruta_json}\n  {ruta_md}")


if __name__ == "__main__":
    main()
