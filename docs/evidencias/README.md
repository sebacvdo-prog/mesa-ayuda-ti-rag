# Evidencias de Pruebas y Validación de Software

Esta carpeta contiene los registros de ejecución y resultados generados al ejecutar las pruebas del sistema de forma reproducible.

## Cierre técnico EP2 — Etapa 4

La evidencia vigente es [cierre técnico 15/15](ep2_etapa4_cierre_tecnico.md),
derivada de la evaluación integral real del 22 de octubre de 2026: tres fases,
10 respuestas HTTP 200, 18.137 tokens informados, cero escrituras de negocio e
ITSM intacto. Distingue las **584 pruebas automatizadas con red bloqueada**, los
ensayos aislados de contexto y la aceptación real completa de **15/15**.

[ep2_plan_real.md](ep2_plan_real.md) conserva los intentos parciales del 15 de
octubre; sus 308 pruebas y 11/15 describen ese estado histórico. Los registros
EP1 listados a continuación se conservan y no representan el tamaño actual de
la suite EP2. Regenerar una evaluación con proveedores requiere autorización
separada y consume cuota.

## Archivos de Evidencia Generados

1. **`seed_db_log.txt`**: Log de inicialización y población de la base de datos ITSM SQLite (`data/itsm.db`), validando la creación de 6 categorías, 4 SLAs, 12 usuarios, 20 activos y 40 tickets iniciales.
2. **`ingest_log.txt`**: Log del pipeline de ingesta RAG (`python -m src.ingest`), evidenciando el procesamiento de 9 documentos normativos (6 internos + 3 externos), la fragmentación en chunks de 900 caracteres (150 de solapamiento) y la generación e indexación de 98 vectores en FAISS.
3. **`test_pytest_log.txt`**: Log de ejecución de la suite automatizada de pruebas unitarias (`pytest -v`), certificando que los **88/88 tests** pasan exitosamente en 0.42s cubriendo configuración, herramientas ITSM, retriever vectorial, prompts y orquestación del agente.
4. **`evaluacion_resultados.md`**: Informe detallado de la evaluación cuantitativa con LLM-as-judge (`eval/evaluate.py`), evaluando las 10 consultas del dataset sintético y reportando:
   - **Fidelidad (Faithfulness)**: 0.880 (Meta: ≥ 0.85) — Cumplida.
   - **Relevancia de Respuesta**: 0.940 (Meta: ≥ 0.80) — Cumplida.
   - **Precisión del Contexto**: 0.990 (Meta: ≥ 0.75) — Cumplida.
   - **Acierto de Fuente (Fuente Primaria)**: 100% (10/10).

## Instrucciones para Regenerar Evidencias

Para regenerar estos registros en cualquier entorno:

```bash
# 1. Base de datos
python data/seed_db.py

# 2. Ingesta RAG
python -m src.ingest

# 3. Pruebas unitarias
pytest -v

# 4. Evaluación LLM-as-judge (requiere GROQ_API_KEY)
python -m eval.evaluate --pausa 6
```
