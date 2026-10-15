"""Calibra el umbral local con FAISS real, sin llamar al LLM ni al juez.

Uso: python -m eval.calibrate_retrieval --offline
Los informes se guardan en .cache/ (excluido de Git). No se modifica el .env.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
from fractions import Fraction
from pathlib import Path
from typing import Any

from src import config, retriever


def evaluar_umbral(casos: list[dict[str, Any]], umbral: float) -> dict[str, Any]:
    """Reproduce umbral, reordenamiento y top_k usando candidatos ya filtrados.

    La coincidencia con fuente_esperada es un proxy documental: no etiqueta la
    relevancia de cada fragmento ni evalúa la respuesta de un agente.
    NEG-01 y NEG-03 sí tienen fuente; solo 'ninguna' exige contexto vacío.
    """
    detalle = []
    fragmentos_fuente = fragmentos_devueltos = 0
    for caso in casos:
        resultado = retriever.reordenar_por_vigencia(
            retriever.aplicar_umbral(caso["candidatos"], umbral)
        )[:config.TOP_K]
        tiene_fuente = caso["fuente_esperada"] not in ("", "ninguna")
        acierto = any(f.nombre_documento == caso["fuente_esperada"] for f in resultado)
        fragmentos_fuente += sum(
            f.nombre_documento == caso["fuente_esperada"] for f in resultado
        )
        fragmentos_devueltos += len(resultado)
        detalle.append({
            "id": caso["id"], "categoria": caso["categoria"],
            "fuente_esperada": caso["fuente_esperada"],
            "clasificacion": caso["clasificacion"],
            "tiene_fuente": tiene_fuente, "acierto_fuente": acierto,
            "resultados": [{"documento": f.nombre_documento,
                            "chunk": f.documento.metadata.get("chunk"),
                            "puntaje": f.puntaje} for f in resultado],
        })
    con_fuente = [d for d in detalle if d["tiene_fuente"]]
    sin_fuente = [d for d in detalle if not d["tiene_fuente"]]
    return {
        "umbral": umbral,
        "casos_con_fuente": len(con_fuente),
        "aciertos_fuente_top4": sum(d["acierto_fuente"] for d in con_fuente),
        "consultas_con_contexto": sum(bool(d["resultados"]) for d in detalle),
        "casos_sin_fuente": len(sin_fuente),
        "contextos_sin_fuente": sum(bool(d["resultados"]) for d in sin_fuente),
        "fragmentos_fuente": fragmentos_fuente,
        "fragmentos_devueltos": fragmentos_devueltos,
        "precision_fuente_proxy": fragmentos_fuente / fragmentos_devueltos
        if fragmentos_devueltos else 0.0,
        "detalle": detalle,
    }


def resumir(medicion: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in medicion.items() if k != "detalle"}


def seleccionar_umbral(casos: list[dict[str, Any]]) -> dict[str, Any]:
    """Busca todos los intervalos donde la selección de fragmentos es constante.

    Exige rechazar los casos sin fuente. Maximiza aciertos de fuente, después
    precisión documental proxy y finalmente amplitud del intervalo estable.
    Su punto medio evita situar el umbral sobre un score del dataset. No usa una
    cuadrícula de cortes elegidos a mano ni redondea scores antes de comparar.
    """
    if not any(c["fuente_esperada"] in ("", "ninguna") for c in casos):
        raise ValueError("La calibración necesita al menos un caso sin fuente.")
    if not any(c["fuente_esperada"] not in ("", "ninguna") for c in casos):
        raise ValueError("La calibración necesita casos con fuente esperada.")
    limites = sorted({0.0, 1.0} | {
        f.puntaje for c in casos for f in c["candidatos"] if 0 < f.puntaje < 1
    })
    curva = []
    intervalos = [(0.0, 0.0), *zip(limites, limites[1:]), (1.0, 1.0)]
    for inferior, superior in intervalos:
        medio = (inferior + superior) / 2
        curva.append({**resumir(evaluar_umbral(casos, medio)),
                      "intervalo_inferior": inferior, "intervalo_superior": superior})
    seguros = [m for m in curva if m["contextos_sin_fuente"] == 0]
    if not seguros:
        raise ValueError("Ningún umbral entre 0 y 1 rechaza los casos sin fuente.")
    mejor = max(seguros, key=lambda m: (
        m["aciertos_fuente_top4"],
        Fraction(m["fragmentos_fuente"], m["fragmentos_devueltos"] or 1),
        m["intervalo_superior"] - m["intervalo_inferior"], m["umbral"],
    ))
    return {"seleccion": mejor, "curva": curva}


def validar_dejando_una_fuente_fuera(casos: list[dict[str, Any]]) -> dict[str, Any]:
    """Recalibra sin cada pregunta con fuente y evalúa esa pregunta excluida.

    El caso sin fuente permanece en calibración: su rechazo no queda validado
    de manera independiente. Las preguntas siguen compartiendo el mismo corpus.
    """
    pliegues = []
    for caso in casos:
        if caso["fuente_esperada"] in ("", "ninguna"):
            continue
        entrenamiento = [c for c in casos if c["id"] != caso["id"]]
        seleccionado = seleccionar_umbral(entrenamiento)["seleccion"]["umbral"]
        medicion = evaluar_umbral([caso], seleccionado)
        pliegues.append({"id": caso["id"], "umbral": seleccionado,
                        "acierto_fuente": bool(medicion["aciertos_fuente_top4"])})
    return {"casos": len(pliegues),
            "aciertos_fuente": sum(p["acierto_fuente"] for p in pliegues),
            "detalle": pliegues}


def diagnosticar_limites(casos: list[dict[str, Any]]) -> dict[str, Any]:
    """Identifica fuentes que un único umbral no puede separar del caso sin fuente."""
    frontera = max((f.puntaje for c in casos if c["fuente_esperada"] in ("", "ninguna")
                    for f in c["candidatos"]), default=None)
    debajo = []
    sin_candidatos = []
    bloqueadas = []
    fuentes = {f.nombre_documento: f.documento.metadata.get("fuente")
               for c in casos for f in c["candidatos"]}
    for c in casos:
        if c["fuente_esperada"] in ("", "ninguna"):
            continue
        scores = [f.puntaje for f in c["candidatos"]
                  if f.nombre_documento == c["fuente_esperada"]]
        if not scores:
            sin_candidatos.append(c["id"])
        elif frontera is not None and max(scores) <= frontera:
            debajo.append({"id": c["id"], "mejor_score_fuente": max(scores)})
        fuente_esperada = fuentes.get(c["fuente_esperada"])
        if (fuente_esperada and c["clasificacion"] != "mixta"
                and c["clasificacion"] != fuente_esperada):
            bloqueadas.append(c["id"])
    return {"mayor_score_sin_fuente": frontera, "fuentes_bajo_frontera": debajo,
            "sin_candidatos_de_fuente": sin_candidatos, "bloqueadas_por_ruta": bloqueadas}


def recolectar_candidatos(
    preguntas: list[dict[str, Any]], recuperador: retriever.RecuperadorVectorial,
    perfil: str,
) -> list[dict[str, Any]]:
    casos = []
    for pregunta in preguntas:
        clasificacion = retriever.clasificar_consulta(pregunta["pregunta"])
        fuente = retriever.filtro_de_fuente(clasificacion)
        crudos = recuperador._buscar_crudo(
            pregunta["pregunta"], config.TOP_K * 5, {"fuente": fuente} if fuente else None
        )
        casos.append({**pregunta, "clasificacion": clasificacion,
                      "candidatos": retriever.filtrar_por_metadatos(crudos, fuente, perfil)})
    return casos


def verificar_puntuacion(almacen: Any, consulta: str) -> dict[str, Any]:
    """Contrasta FAISS, suma de cuadrados, coseno y score de LangChain."""
    import faiss
    import numpy as np

    if almacen.index.metric_type != faiss.METRIC_L2:
        raise ValueError("Esta calibración requiere un índice FAISS L2.")
    vector = np.asarray(almacen.embeddings.embed_query(consulta), dtype=np.float32)
    distancias, indices = almacen.index.search(vector.reshape(1, -1), 1)
    documento = almacen.index.reconstruct(int(indices[0][0]))
    distancia = float(distancias[0][0])
    suma_cuadrados = float(np.sum((vector - documento) ** 2))
    score = float(almacen._select_relevance_score_fn()(distancia))
    formula = 1 - distancia / math.sqrt(2)
    if not math.isclose(distancia, suma_cuadrados, abs_tol=1e-5):
        raise ValueError("FAISS no coincide con la distancia L2 al cuadrado.")
    if not math.isclose(score, formula, abs_tol=1e-6):
        raise ValueError("Cambió la conversión de relevancia; revisar la calibración.")
    normas = [float(np.linalg.norm(v)) for v in (vector, documento)]
    if not all(math.isclose(n, 1, abs_tol=1e-5) for n in normas):
        raise ValueError("Los vectores locales deben estar normalizados.")
    return {"indice": type(almacen.index).__name__, "distancia_faiss": distancia,
            "suma_cuadrados": suma_cuadrados, "score_langchain": score,
            "formula": "1 - distancia_L2_cuadrada / sqrt(2)",
            "coseno": float(np.dot(vector, documento)), "normas": normas}


def escribir_informe(informe: dict[str, Any], salida: Path) -> None:
    salida.parent.mkdir(parents=True, exist_ok=True)
    salida.with_suffix(".json").write_text(
        json.dumps(informe, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    seleccion = informe["seleccion"]
    puntuacion = informe["verificacion_puntuacion"]
    filas = [
        "# Calibración de recuperación con Hugging Face", "",
        f"Modelo: `{informe['embeddings']['modelo']}`. Dataset SHA256: `{informe['dataset_sha256']}`.",
        f"Índice SHA256: `{informe['indice_sha256']}`. Perfil: `{informe['perfil']}`.",
        f"Versiones: `{informe['versiones']}`.", "",
        "FAISS IndexFlatL2 devuelve distancia euclídea al cuadrado. El conector instalado",
        "aplica `score = 1 - distancia_L2_cuadrada / sqrt(2)`. No es coseno ni probabilidad.",
        f"Verificación numérica: distancia² `{puntuacion['distancia_faiss']:.9f}`, "
        f"suma de cuadrados `{puntuacion['suma_cuadrados']:.9f}`, "
        f"score `{puntuacion['score_langchain']:.9f}` y coseno `{puntuacion['coseno']:.9f}`.",
        "Referencia: [métricas oficiales de FAISS](https://github.com/facebookresearch/faiss/wiki/MetricType-and-distances).", "",
        "Criterio: rechazar los casos sin fuente; maximizar acierto de fuente@4;",
        "desempatar por precisión documental proxy y amplitud del intervalo estable.",
        "Se evaluaron todos los intervalos definidos por los scores sin redondear.",
        f"Umbral seleccionado: `{seleccion['umbral']:.9f}`, punto medio del intervalo",
        f"`({seleccion['intervalo_inferior']:.9f}, {seleccion['intervalo_superior']:.9f}]`.", "",
        f"Umbral activo: `{informe['resultado_configurado']['umbral']}`. "
        "Se comprobó que las consultas reales de `RecuperadorVectorial.buscar()`",
        "coinciden con la reproducción de la evaluación para todas las preguntas.", "",
        "| Umbral | Aciertos de fuente@4 | Consultas con contexto | Contextos sin fuente | Precisión documental proxy |",
        "|---:|---:|---:|---:|---:|",
    ]
    for m in informe["comparacion"]:
        filas.append(f"| {m['umbral']:.6f} | {m['aciertos_fuente_top4']}/{m['casos_con_fuente']} "
                     f"| {m['consultas_con_contexto']}/{informe['consultas']} "
                     f"| {m['contextos_sin_fuente']}/{m['casos_sin_fuente']} "
                     f"| {m['precision_fuente_proxy']:.1%} |")
    validacion = informe["validacion_por_pregunta"]
    diagnostico = informe["diagnostico"]
    filas.extend([
        "", f"Validación excluyendo cada pregunta con fuente de su propia calibración: "
        f"{validacion['aciertos_fuente']}/{validacion['casos']} aciertos de fuente@4.", "",
        "## Límites", "",
        f"El dataset contiene {informe['consultas']} consultas, "
        f"{seleccion['casos_con_fuente']} con fuente y {seleccion['casos_sin_fuente']} sin fuente.",
        "`NEG-01` y `NEG-03` tienen fuentes de seguridad y accesos: no son casos sin fuente.",
        "La selección usa este dataset; sus resultados no son una prueba independiente.",
        "La validación por pregunta conserva el único caso sin fuente en entrenamiento.",
        "Una coincidencia de archivo no garantiza que el fragmento responda la pregunta,",
        "y un archivo diferente puede contener contexto complementario útil.",
        "No se evaluaron respuestas generadas ni se llamó a Groq o al LLM juez.", "",
        f"El mayor score del caso sin fuente es `{diagnostico['mayor_score_sin_fuente']:.9f}`.",
        "Las fuentes esperadas de "
        + ", ".join(d["id"] for d in diagnostico["fuentes_bajo_frontera"])
        + " tienen scores inferiores o iguales a esa frontera.",
        "Ningún umbral único puede recuperar esas fuentes y a la vez rechazar el caso sin fuente.",
        "Casos cuya fuente esperada queda bloqueada por el enrutador: "
        + (", ".join(diagnostico["bloqueadas_por_ruta"]) or "ninguno") + ".",
        "El umbral no corrige el modelo ni el enrutador; siguen pendientes esos límites",
        "y la evaluación con más casos sin fuente y fragmentos etiquetados.", "",
        "## Resultados del umbral seleccionado", "",
        "| Caso | Ruta | Fuente esperada | Resultado |",
        "|---|---|---|---|",
    ])
    for d in informe["resultado_seleccionado"]["detalle"]:
        nombres = ", ".join(dict.fromkeys(r["documento"] for r in d["resultados"])) or "sin contexto"
        filas.append(f"| {d['id']} | {d['clasificacion']} | {d['fuente_esperada']} | {nombres} |")
    salida.with_suffix(".md").write_text("\n".join(filas) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--dataset", type=Path, default=config.RUTA_DATASET)
    parser.add_argument("--salida", type=Path, default=config.DIR_CACHE / "calibracion-huggingface")
    argumentos = parser.parse_args()
    if config.PROVEEDOR_EMBEDDINGS != "huggingface":
        parser.error("La calibración se limita a Hugging Face; Google conserva su umbral.")
    if argumentos.offline:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
    contenido = argumentos.dataset.read_bytes()
    dataset = json.loads(contenido)
    perfil = dataset.get("perfil_por_defecto", "agente")
    recuperador = retriever.RecuperadorVectorial()
    comprobacion = verificar_puntuacion(recuperador.almacen, dataset["preguntas"][0]["pregunta"])
    casos = recolectar_candidatos(dataset["preguntas"], recuperador, perfil)
    calibracion = seleccionar_umbral(casos)
    umbral = calibracion["seleccion"]["umbral"]
    configurado = evaluar_umbral(casos, config.umbral_similitud())
    for caso, esperado in zip(casos, configurado["detalle"]):
        reales = recuperador.buscar(caso["pregunta"], perfil=perfil)
        identidades = [(f.nombre_documento, f.documento.metadata.get("chunk")) for f in reales]
        previstas = [(f["documento"], f["chunk"]) for f in esperado["resultados"]]
        if identidades != previstas:
            raise RuntimeError(f"La búsqueda real difiere de la evaluación en {caso['id']}.")
    comparacion = [resumir(evaluar_umbral(casos, t)) for t in
                  sorted({config.UMBRAL_SIMILITUD, 0.60, 0.55, 0.50, 0.45, 0.40, umbral}, reverse=True)]
    informe = {
        "embeddings": config.configuracion_embeddings(), "perfil": perfil,
        "dataset_sha256": hashlib.sha256(contenido).hexdigest(),
        "indice_sha256": hashlib.sha256((config.DIR_INDICE_FAISS / "index.faiss").read_bytes()).hexdigest(),
        "versiones": {n: importlib.metadata.version(n) for n in
                      ("faiss-cpu", "langchain-core", "langchain-community", "langchain-huggingface", "sentence-transformers")},
        "consultas": len(casos), "verificacion_puntuacion": comprobacion,
        **calibracion, "comparacion": comparacion,
        "resultado_seleccionado": evaluar_umbral(casos, umbral),
        "resultado_configurado": configurado,
        "validacion_por_pregunta": validar_dejando_una_fuente_fuera(casos),
        "diagnostico": diagnosticar_limites(casos),
    }
    escribir_informe(informe, argumentos.salida)
    print(json.dumps(calibracion["seleccion"], ensure_ascii=False))
    validacion = informe["validacion_por_pregunta"]
    print("Validación por pregunta:", validacion["aciertos_fuente"], "/", validacion["casos"])
    print("Informe:", argumentos.salida.with_suffix(".md"))


if __name__ == "__main__":
    main()
