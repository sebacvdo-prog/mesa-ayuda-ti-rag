"""Selección de embeddings, aislamiento de caché y persistencia segura de FAISS.

Los proveedores se sustituyen por dobles; FAISS y SQLite se ejercitan de verdad
en directorios temporales. No se descargan modelos ni se llaman APIs.
"""

from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from langchain_core.embeddings import Embeddings

from src import config, ingest, retriever


class EmbeddingsFalsos(Embeddings):
    def __init__(self, dimension: int = 3) -> None:
        self.dimension = dimension
        self.llamadas: list[dict] = []

    def embed_documents(self, texts: list[str], **kwargs) -> list[list[float]]:
        self.llamadas.append(kwargs)
        return [[1.0] + [0.0] * (self.dimension - 1) for _ in texts]

    def embed_query(self, text: str, **kwargs) -> list[float]:
        self.llamadas.append(kwargs)
        return [1.0] + [0.0] * (self.dimension - 1)


@pytest.fixture(autouse=True)
def configuracion_aislada(monkeypatch):
    monkeypatch.setattr(config, "PROVEEDOR_EMBEDDINGS", "google")
    monkeypatch.setattr(config, "MODELO_EMBEDDINGS", "models/gemini-embedding-001")
    monkeypatch.setattr(config, "DIMENSION_EMBEDDINGS", 768)
    monkeypatch.setattr(config, "GOOGLE_API_KEY", "clave-falsa")
    monkeypatch.setattr(config, "LLM_API_KEY", "clave-falsa")
    monkeypatch.setattr(config, "configurar_langsmith", lambda: False)


def seleccionar_local(monkeypatch):
    monkeypatch.setattr(config, "PROVEEDOR_EMBEDDINGS", "huggingface")
    monkeypatch.setattr(config, "MODELO_EMBEDDINGS", "sentence-transformers/all-MiniLM-L6-v2")
    monkeypatch.setattr(config, "DIMENSION_EMBEDDINGS", 384)


def test_google_exige_su_clave_solo_si_se_necesitan_embeddings(monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_API_KEY", "")
    assert any("GOOGLE_API_KEY" in p for p in config.validar_configuracion())
    assert config.validar_configuracion(requiere_embeddings=False) == []


def test_local_no_exige_google_y_conserva_validacion_de_groq(monkeypatch):
    seleccionar_local(monkeypatch)
    monkeypatch.setattr(config, "GOOGLE_API_KEY", "")
    monkeypatch.setattr(config, "LLM_API_KEY", "")
    assert config.validar_configuracion(requiere_llm=False) == []
    assert len(config.validar_configuracion()) == 1
    assert "LLM_API_KEY" in config.validar_configuracion()[0]


@pytest.mark.parametrize(("campo", "valor", "mensaje"), [
    ("PROVEEDOR_EMBEDDINGS", "desconocido", "EMBEDDING_PROVIDER"),
    ("MODELO_EMBEDDINGS", "", "EMBEDDING_MODEL"),
    ("DIMENSION_EMBEDDINGS", 0, "EMBEDDING_DIM"),
    ("DIMENSION_EMBEDDINGS", -1, "EMBEDDING_DIM"),
])
def test_configuracion_invalida_falla_antes_de_crear_proveedor(monkeypatch, campo, valor, mensaje):
    monkeypatch.setattr(config, campo, valor)
    with pytest.raises(RuntimeError, match=mensaje):
        config.crear_embeddings(usar_cache=False)
    assert config.validar_configuracion(requiere_embeddings=False) == []


def test_minilm_rechaza_768_dimensiones(monkeypatch):
    seleccionar_local(monkeypatch)
    monkeypatch.setattr(config, "DIMENSION_EMBEDDINGS", 768)
    with pytest.raises(RuntimeError, match="384"):
        config.crear_embeddings(usar_cache=False)


@pytest.mark.parametrize(("proveedor", "modelo", "dimension"), [
    (None, "models/gemini-embedding-001", 768),
    ("google", "models/gemini-embedding-001", 768),
    (" HuggingFace ", "sentence-transformers/all-MiniLM-L6-v2", 384),
])
def test_valores_por_defecto_dependen_del_proveedor(monkeypatch, proveedor, modelo, dimension):
    import dotenv

    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args: None)
    for nombre in ("EMBEDDING_PROVIDER", "EMBEDDING_MODEL", "EMBEDDING_DIM"):
        monkeypatch.delenv(nombre, raising=False)
    if proveedor is not None:
        monkeypatch.setenv("EMBEDDING_PROVIDER", proveedor)
    valores = runpy.run_path(config.__file__)
    assert valores["MODELO_EMBEDDINGS"] == modelo
    assert valores["DIMENSION_EMBEDDINGS"] == dimension


def test_dimension_no_numerica_se_reporta_sin_romper_import(monkeypatch):
    import dotenv

    monkeypatch.setattr(dotenv, "load_dotenv", lambda *args: None)
    monkeypatch.setenv("EMBEDDING_DIM", "abc")
    valores = runpy.run_path(config.__file__)
    assert any("EMBEDDING_DIM" in p for p in valores["validar_configuracion"](False, True))


@pytest.mark.parametrize("constructor_antiguo", [False, True])
def test_google_conserva_modelo_y_envia_dimension_en_cada_llamada(monkeypatch, constructor_antiguo):
    base = EmbeddingsFalsos(768)
    fabrica = Mock(side_effect=[TypeError("constructor antiguo"), base]
                   if constructor_antiguo else None, return_value=base)
    monkeypatch.setitem(sys.modules, "langchain_google_genai",
                        SimpleNamespace(GoogleGenerativeAIEmbeddings=fabrica))
    embeddings = config.crear_embeddings(usar_cache=False)
    assert len(embeddings.embed_query("consulta")) == 768
    assert len(embeddings.embed_documents(["documento"])[0]) == 768
    assert base.llamadas == [{"output_dimensionality": 768}] * 2
    assert fabrica.call_args.kwargs["model"] == "models/gemini-embedding-001"
    assert fabrica.call_args.kwargs["google_api_key"] == "clave-falsa"


def test_local_usa_cpu_y_normalizacion_sin_importar_google(monkeypatch):
    seleccionar_local(monkeypatch)
    monkeypatch.setattr(config, "GOOGLE_API_KEY", "")
    fabrica = Mock(return_value=EmbeddingsFalsos(384))
    monkeypatch.setitem(sys.modules, "langchain_huggingface",
                        SimpleNamespace(HuggingFaceEmbeddings=fabrica))
    monkeypatch.setitem(sys.modules, "langchain_google_genai", None)
    embeddings = config.crear_embeddings(usar_cache=False)
    assert len(embeddings.embed_query("consulta")) == 384
    assert len(embeddings.embed_documents(["documento"])[0]) == 384
    fabrica.assert_called_once_with(
        model_name="sentence-transformers/all-MiniLM-L6-v2",
        model_kwargs={"device": "cpu"}, encode_kwargs={"normalize_embeddings": True},
    )


@pytest.mark.parametrize("metodo", ["embed_query", "embed_documents"])
def test_dimension_real_incorrecta_no_se_guarda_en_cache(tmp_path, metodo):
    modelo = config._EmbeddingsDimensionados(EmbeddingsFalsos(3), 384)
    cache = config.EmbeddingsConCache(modelo, "prueba", tmp_path / "cache.sqlite")
    argumento = "consulta" if metodo == "embed_query" else ["documento"]
    with pytest.raises(RuntimeError, match="3 dimensiones"):
        getattr(cache, metodo)(argumento)
    tipo = "consulta" if metodo == "embed_query" else "documento"
    assert cache._leer([cache._clave(argumento if isinstance(argumento, str) else argumento[0], tipo)]) == {}


@pytest.mark.parametrize(("campo", "valor"), [
    ("PROVEEDOR_EMBEDDINGS", "huggingface"),
    ("MODELO_EMBEDDINGS", "otro-modelo"),
    ("DIMENSION_EMBEDDINGS", 384),
])
def test_cache_y_huella_separan_configuraciones(monkeypatch, tmp_path, campo, valor):
    base = EmbeddingsFalsos(3)
    identidad = json.dumps(config.configuracion_embeddings(), sort_keys=True)
    cache = config.EmbeddingsConCache(base, identidad, tmp_path / "cache.sqlite")
    cache.embed_documents(["mismo texto"])
    cache.embed_documents(["mismo texto"])
    cache.embed_query("mismo texto")
    assert cache.aciertos == 1
    assert len(base.llamadas) == 2  # consulta y documento tienen claves distintas
    huella = ingest.calcular_huella([])
    monkeypatch.setattr(config, campo, valor)
    nueva_identidad = json.dumps(config.configuracion_embeddings(), sort_keys=True)
    nueva = config.EmbeddingsConCache(base, nueva_identidad, tmp_path / "cache.sqlite")
    nueva.embed_documents(["mismo texto"])
    assert nueva.aciertos == 0
    assert len(base.llamadas) == 3
    assert ingest.calcular_huella([]) != huella


def test_fabrica_no_reutiliza_cache_anterior_ni_de_otro_proveedor(monkeypatch, tmp_path):
    base = EmbeddingsFalsos(768)
    ruta_cache = tmp_path / "cache.sqlite"
    clase_cache = config.EmbeddingsConCache
    anterior = clase_cache(base, f"{config.MODELO_EMBEDDINGS}@768", ruta_cache)
    anterior.embed_documents(["mismo texto"])
    monkeypatch.setattr(config, "EmbeddingsConCache",
                        lambda modelo, identidad: clase_cache(modelo, identidad, ruta_cache))
    monkeypatch.setitem(sys.modules, "langchain_google_genai",
                        SimpleNamespace(GoogleGenerativeAIEmbeddings=Mock(return_value=base)))
    monkeypatch.setitem(sys.modules, "langchain_huggingface",
                        SimpleNamespace(HuggingFaceEmbeddings=Mock(return_value=base)))
    google = config.crear_embeddings()
    google.embed_documents(["mismo texto"])
    google.embed_documents(["mismo texto"])
    assert google.fallos == 1
    assert google.aciertos == 1
    # Igual modelo y dimensión: cambiar solo proveedor también invalida la caché.
    monkeypatch.setattr(config, "PROVEEDOR_EMBEDDINGS", "huggingface")
    local = config.crear_embeddings()
    local.embed_documents(["mismo texto"])
    assert local.fallos == 1
    assert local.aciertos == 0
    assert len(base.llamadas) == 3


@pytest.fixture()
def indice_temporal(monkeypatch, tmp_path):
    from langchain_community.vectorstores import FAISS

    monkeypatch.setattr(config, "DIMENSION_EMBEDDINGS", 3)
    embeddings = EmbeddingsFalsos()
    monkeypatch.setattr(config, "crear_embeddings", lambda: embeddings)
    almacen = FAISS.from_texts(["procedimiento VPN"], embeddings)
    ruta = tmp_path / "faiss_index"
    ingest.guardar_indice(almacen, ruta)
    return ruta, almacen


def test_faiss_se_guarda_y_recupera_con_configuracion_compatible(indice_temporal):
    ruta, _ = indice_temporal
    cargado = retriever.RecuperadorVectorial.cargar_indice(ruta)
    assert cargado.index.d == 3
    assert cargado.similarity_search("VPN", k=1)[0].page_content == "procedimiento VPN"


@pytest.mark.parametrize("cambio", ["proveedor", "modelo", "dimension", "normalizar", "sin_metadatos", "incompleto", "json_invalido"])
def test_carga_rechaza_indices_incompatibles_antes_de_crear_embeddings(monkeypatch, indice_temporal, cambio):
    ruta, _ = indice_temporal
    metadatos = ruta / "configuracion_embeddings.json"
    if cambio == "sin_metadatos":
        metadatos.unlink()
    elif cambio == "incompleto":
        (ruta / "index.pkl").unlink()
    elif cambio == "json_invalido":
        metadatos.write_text("{", encoding="utf-8")
    else:
        datos = json.loads(metadatos.read_text(encoding="utf-8"))
        datos[cambio] = "incompatible"
        metadatos.write_text(json.dumps(datos), encoding="utf-8")
    monkeypatch.setattr(config, "crear_embeddings", lambda: pytest.fail("No debe cargar el proveedor"))
    with pytest.raises(RuntimeError, match="python -m src.ingest"):
        retriever.RecuperadorVectorial.cargar_indice(ruta)


def test_carga_comprueba_dimension_real_del_indice(monkeypatch, indice_temporal):
    ruta, _ = indice_temporal
    monkeypatch.setattr(config, "DIMENSION_EMBEDDINGS", 384)
    (ruta / "configuracion_embeddings.json").write_text(
        json.dumps(config.configuracion_embeddings()), encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="dimensión real"):
        retriever.RecuperadorVectorial.cargar_indice(ruta)


def test_reconstruccion_conserva_archivos_anteriores(indice_temporal):
    ruta, almacen = indice_temporal
    anteriores = {p.name: p.read_bytes() for p in ruta.iterdir()}
    ingest.guardar_indice(almacen, ruta)
    respaldos = list(ruta.parent.glob("faiss_index-respaldo-*"))
    assert len(respaldos) == 1
    assert {p.name: p.read_bytes() for p in respaldos[0].iterdir()} == anteriores
    assert config.indice_embeddings_compatible(ruta)


@pytest.mark.parametrize("etapa", ["escritura", "sustitucion"])
def test_fallo_al_guardar_preserva_indice_anterior(monkeypatch, indice_temporal, etapa):
    ruta, almacen = indice_temporal
    anteriores = {p.name: p.read_bytes() for p in ruta.iterdir()}
    if etapa == "escritura":
        monkeypatch.setattr(almacen, "save_local", Mock(side_effect=OSError("fallo simulado")))
    else:
        renombrar = Path.rename

        def fallar_sustitucion(origen, destino):
            if "-nuevo-" in origen.name:
                raise OSError("fallo simulado")
            return renombrar(origen, destino)

        monkeypatch.setattr(Path, "rename", fallar_sustitucion)
    with pytest.raises(OSError, match="fallo simulado"):
        ingest.guardar_indice(almacen, ruta)
    assert {p.name: p.read_bytes() for p in ruta.iterdir()} == anteriores


def test_ingesta_reutiliza_solo_un_indice_compatible(monkeypatch, indice_temporal, tmp_path):
    ruta, _ = indice_temporal
    monkeypatch.setattr(config, "DIR_INDICE_FAISS", ruta)
    monkeypatch.setattr(config, "RUTA_MANIFIESTO_INGESTA", tmp_path / "manifiesto.json")
    resumen = {"huella": ingest.calcular_huella(ingest.cargar_corpus())}
    ingest.escribir_manifiesto(resumen)
    monkeypatch.setattr(config, "crear_embeddings", lambda: pytest.fail("No debe recalcular"))
    assert ingest.ingestar() == resumen


def test_ingesta_reconstruye_indice_antiguo_aunque_huella_coincida(monkeypatch, indice_temporal, tmp_path):
    ruta, _ = indice_temporal
    monkeypatch.setattr(config, "DIR_INDICE_FAISS", ruta)
    monkeypatch.setattr(config, "RUTA_MANIFIESTO_INGESTA", tmp_path / "manifiesto.json")
    resumen = {"huella": ingest.calcular_huella(ingest.cargar_corpus())}
    ingest.escribir_manifiesto(resumen)
    (ruta / "configuracion_embeddings.json").unlink()
    anterior = (ruta / "index.faiss").read_bytes()
    nuevo = ingest.ingestar()
    assert nuevo["fragmentos"] == 98
    assert config.indice_embeddings_compatible(ruta)
    respaldos = list(ruta.parent.glob("faiss_index-respaldo-*"))
    assert len(respaldos) == 1
    assert (respaldos[0] / "index.faiss").read_bytes() == anterior
