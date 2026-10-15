"""Calibración reproducible y umbral local, sin descargar modelos ni usar APIs."""

from __future__ import annotations

import runpy
from types import SimpleNamespace

import pytest
from langchain_core.documents import Document

from eval import calibrate_retrieval as calibracion
from src import config, retriever


def candidato(documento: str, puntaje: float, fecha: str = "2026-01-01"):
    return retriever.FragmentoRecuperado(
        documento=Document(page_content="contenido", metadata={
            "documento": documento, "fecha_vigencia": fecha,
            "fuente": "interna", "nivel_acceso": "publico_interno",
        }), puntaje=puntaje,
    )


def caso(identificador: str, fuente: str, candidatos: list):
    return {"id": identificador, "fuente_esperada": fuente, "categoria": "prueba",
            "clasificacion": "mixta", "candidatos": candidatos}


@pytest.mark.parametrize(("proveedor", "umbral"), [("google", 0.72), ("huggingface", 0.48)])
def test_umbral_default_por_proveedor_y_override_explicito(monkeypatch, proveedor, umbral):
    monkeypatch.setattr(config, "PROVEEDOR_EMBEDDINGS", proveedor)
    monkeypatch.setattr(config, "UMBRAL_SIMILITUD_HF", 0.48)
    assert config.UMBRAL_SIMILITUD == 0.72
    assert config.umbral_similitud() == umbral
    assert retriever.RecuperadorVectorial(almacen=object()).umbral == umbral
    assert retriever.RecuperadorVectorial(almacen=object(), umbral=0).umbral == 0
    fragmentos = [candidato("kb.md", 0.50)]
    assert bool(retriever.aplicar_umbral(fragmentos)) == (proveedor == "huggingface")
    assert retriever.aplicar_umbral(fragmentos, umbral=0) == fragmentos


@pytest.mark.parametrize("valor", ["abc", "nan", "inf", "-inf", "-0.01", "1.01", ""])
def test_umbral_invalido_se_reporta_solo_con_huggingface(monkeypatch, valor):
    import dotenv

    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args: None)
    monkeypatch.setenv("HF_SIMILARITY_THRESHOLD", valor)
    monkeypatch.setenv("EMBEDDING_PROVIDER", "huggingface")
    monkeypatch.setenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
    monkeypatch.setenv("EMBEDDING_DIM", "384")
    local = runpy.run_path(config.__file__)
    assert any("HF_SIMILARITY_THRESHOLD" in p for p in local["validar_configuracion"](False))
    assert local["validar_configuracion"](False, False) == []
    monkeypatch.setenv("EMBEDDING_PROVIDER", "google")
    monkeypatch.setenv("GOOGLE_API_KEY", "clave-falsa")
    google = runpy.run_path(config.__file__)
    assert google["validar_configuracion"](False) == []
    assert google["umbral_similitud"]() == 0.72


@pytest.mark.parametrize("valor", ["0", "0.471764", "1"])
def test_umbral_valido_desde_entorno(monkeypatch, valor):
    import dotenv

    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args: None)
    monkeypatch.setenv("EMBEDDING_PROVIDER", "huggingface")
    monkeypatch.setenv("HF_SIMILARITY_THRESHOLD", valor)
    local = runpy.run_path(config.__file__)
    assert local["umbral_similitud"]() == float(valor)


def test_umbral_no_invalida_embeddings_cache_ni_huella(monkeypatch):
    from src import ingest

    original = config.configuracion_embeddings()
    huella = ingest.calcular_huella([])
    monkeypatch.setattr(config, "UMBRAL_SIMILITUD_HF", 0.6)
    assert config.configuracion_embeddings() == original
    assert ingest.calcular_huella([]) == huella


@pytest.mark.parametrize(("proveedor", "esperados"), [("huggingface", ["alto.md"]), ("google", [])])
def test_busqueda_aplica_umbral_local_y_mantiene_el_de_google(monkeypatch, proveedor, esperados):
    monkeypatch.setattr(config, "PROVEEDOR_EMBEDDINGS", proveedor)
    monkeypatch.setattr(config, "UMBRAL_SIMILITUD_HF", 0.471764)
    pares = [(f.documento, f.puntaje) for f in
             [candidato("alto.md", 0.471765), candidato("bajo.md", 0.471763)]]
    almacen = SimpleNamespace(similarity_search_with_relevance_scores=lambda *args, **kwargs: pares)
    recuperador = retriever.RecuperadorVectorial(almacen=almacen)
    assert [f.nombre_documento for f in recuperador.buscar("consulta")] == esperados


def test_calibracion_rechaza_sin_fuente_antes_de_maximizar_aciertos():
    casos = [
        caso("P1", "kb.md", [candidato("kb.md", 0.8)]),
        caso("P2", "kb.md", [candidato("kb.md", 0.4)]),
        caso("N", "ninguna", [candidato("kb.md", 0.5)]),
    ]
    resultado = calibracion.seleccionar_umbral(casos)["seleccion"]
    assert resultado["intervalo_inferior"] == 0.5
    assert resultado["intervalo_superior"] == 0.8
    assert resultado["umbral"] == pytest.approx(0.65)
    assert resultado["contextos_sin_fuente"] == 0
    assert resultado["aciertos_fuente_top4"] == 1
    assert calibracion.evaluar_umbral(casos, 0.4)["contextos_sin_fuente"] == 1


def test_desempate_prefiere_precision_documental_y_punto_medio():
    casos = [
        caso("P", "correcto.md", [candidato("correcto.md", 0.8), candidato("otro.md", 0.6)]),
        caso("N", "ninguna", [candidato("otro.md", 0.3)]),
    ]
    seleccionado = calibracion.seleccionar_umbral(casos)["seleccion"]
    assert seleccionado["umbral"] == pytest.approx(0.7)
    assert seleccionado["precision_fuente_proxy"] == 1
    assert seleccionado["umbral"] not in {0.3, 0.6, 0.8}


def test_evaluacion_reproduce_vigencia_y_top_k_y_no_cuenta_negativas_como_sin_fuente():
    candidatos = [candidato("antiguo.md", 0.80)] + [
        candidato("reciente.md", 0.78, "2026-10-01") for _ in range(config.TOP_K)
    ]
    casos = [caso("NEG-01", "reciente.md", candidatos)]
    resultado = calibracion.evaluar_umbral(casos, 0.7)
    assert resultado["casos_sin_fuente"] == 0
    assert resultado["fragmentos_devueltos"] == config.TOP_K
    assert resultado["fragmentos_fuente"] == config.TOP_K
    assert resultado["aciertos_fuente_top4"] == 1


@pytest.mark.parametrize("casos", [
    [caso("P", "kb.md", [candidato("kb.md", 0.8)])],
    [caso("N", "ninguna", [candidato("kb.md", 0.3)])],
])
def test_calibracion_exige_casos_con_y_sin_fuente(casos):
    with pytest.raises(ValueError, match="necesita"):
        calibracion.seleccionar_umbral(casos)


def test_verificacion_con_faiss_real_distingue_score_y_coseno():
    import faiss
    import numpy as np
    from langchain_community.vectorstores import FAISS

    index = faiss.IndexFlatL2(2)
    index.add(np.array([[0.6, 0.8]], dtype=np.float32))
    almacen = SimpleNamespace(
        index=index, embeddings=SimpleNamespace(embed_query=lambda _: [1.0, 0.0]),
        _select_relevance_score_fn=lambda: FAISS._euclidean_relevance_score_fn,
    )
    medicion = calibracion.verificar_puntuacion(almacen, "consulta")
    assert medicion["distancia_faiss"] == pytest.approx(0.8)
    assert medicion["coseno"] == pytest.approx(0.6)
    assert medicion["score_langchain"] == pytest.approx(1 - 0.8 / 2**0.5)
    assert medicion["score_langchain"] != pytest.approx(medicion["coseno"])


def test_validacion_por_pregunta_excluye_su_propia_etiqueta(monkeypatch):
    casos = [caso("P1", "a.md", [candidato("a.md", 0.8)]),
             caso("P2", "b.md", [candidato("b.md", 0.7)]),
             caso("N", "ninguna", [candidato("a.md", 0.3)])]
    entrenamientos = []

    def seleccionar(entrenamiento):
        entrenamientos.append({c["id"] for c in entrenamiento})
        return {"seleccion": {"umbral": 0.5}}

    monkeypatch.setattr(calibracion, "seleccionar_umbral", seleccionar)
    validacion = calibracion.validar_dejando_una_fuente_fuera(casos)
    assert entrenamientos == [{"P2", "N"}, {"P1", "N"}]
    assert validacion["aciertos_fuente"] == 2
    assert validacion["casos"] == 2


def test_diagnostico_distingue_limite_de_umbral_y_enrutamiento():
    externo = candidato("externo.md", 0.8)
    externo.documento.metadata["fuente"] = "externa"
    bloqueado = caso("RUTA", "externo.md", [candidato("interno.md", 0.7)])
    bloqueado["clasificacion"] = "interna"
    casos = [caso("BAJO", "kb.md", [candidato("kb.md", 0.4)]),
             caso("N", "ninguna", [candidato("otro.md", 0.5)]),
             caso("EXT", "externo.md", [externo]), bloqueado]
    limites = calibracion.diagnosticar_limites(casos)
    assert limites["mayor_score_sin_fuente"] == 0.5
    assert [c["id"] for c in limites["fuentes_bajo_frontera"]] == ["BAJO"]
    assert limites["sin_candidatos_de_fuente"] == ["RUTA"]
    assert limites["bloqueadas_por_ruta"] == ["RUTA"]
