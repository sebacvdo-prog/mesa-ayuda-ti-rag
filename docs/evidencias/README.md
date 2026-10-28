# Evidencias de pruebas y validación

Este índice distingue pruebas automatizadas, recuperación local, llamadas reales
y registros históricos. Su actualización documental no constituye una ejecución
nueva. Los reportes originales y los logs se conservan sin modificar.

## Cierre técnico EP2 — Etapa 4

La evidencia vigente es el [cierre técnico del 22 de octubre de 2026](ep2_etapa4_cierre_tecnico.md):
**15/15 verificaciones en una misma ejecución**, tres procesos CLI, diez HTTP 200
y 18.137 tokens informados por Groq. El reporte identifica fuentes mediante
SHA-256 y conserva los límites y las quince comprobaciones.

| Evidencia | Tipo | Qué acredita y qué no acredita |
|---|---|---|
| [Cierre técnico](ep2_etapa4_cierre_tecnico.md) | Integral con Groq, FAISS y SQLite EP2 temporal | Consulta, adaptación, recuperación y propuesta pospuesta; cero notas/auditorías de negocio e ITSM intacto. No mide fidelidad semántica global. |
| [584 pruebas del cierre](ep2_etapa4_cierre_tecnico.md#revalidación-local-para-el-commit-de-cierre) | Automatizadas, con red bloqueada | Regresiones con modelos/HTTP simulados y bases temporales. No son 584 llamadas reales ni una medición de cobertura total. |
| [Integración de Etapa 2](ep2_integracion_real.md) | Groq real, 15 de octubre de 2026 | Cuatro casos aprobados y seis herramientas ejercitadas. La nota quedó como propuesta, sin confirmación. |
| [Memoria de Etapa 3](ep2_memoria_real.md) | Groq real entre procesos, 15 de octubre de 2026 | Once comprobaciones de continuidad y reapertura real de CLI. El aislamiento entre contextos se respalda con pruebas automatizadas. |
| [Calibración local](calibracion_embeddings_locales.md) | Recuperación Hugging Face/FAISS, sin Groq ni juez | Fuente@4: 11/19; al excluir cada pregunta de su calibración: 10/19. Es coincidencia documental, no calidad de respuestas. |
| [Plan real histórico](ep2_plan_real.md) | Intentos parciales del 15 de octubre de 2026 | Antecedentes de errores, límites y estados de aquel código. No reemplazan ni se suman al cierre posterior 15/15. |

En los ensayos reales de EP2 no se confirmaron notas. La escritura confirmada,
cancelación, caducidad, idempotencia y rollback tienen respaldo automatizado en
bases temporales. Cero escrituras de negocio no significa cero actualizaciones
internas: la memoria y el plan sí se persistieron. El HTTP 400 histórico no se
reprodujo en el cierre; su causa histórica no quedó demostrada.

## Procedencia de las métricas históricas EP1

La afirmación **0,880 de fidelidad en diez casos no está verificada**. No se
localizó un resultado versionado que respalde esa cifra ni ese tamaño de muestra.
Se retira como resultado acreditado, conservando su procedencia documental:

| Registro | Fecha y referencia Git | Alcance de la constatación |
|---|---|---|
| Introducción en este índice de 0,880 y diez casos | `4d366c5`, 7 de septiembre de 2026, 01:56:16 −03:00 | Cambio documental; no identifica una corrida compatible. |
| Incorporación al README principal | `7e040d2`, 15 de septiembre de 2026, 15:09:52 −03:00 | Cambio documental de la tabla; no aporta nuevos resultados. |
| Corrida respaldada | `2026-09-07T01:38:33`, sin zona horaria en el JSON; incorporada en `4d366c5` | Cinco casos KB-01–KB-05, fidelidad 0,360, duración 176,6 s. |

Fuentes originales: [JSON de la corrida](../../eval/resultados/evaluacion-20260907-013833.json),
[resumen Markdown](../../eval/resultados/evaluacion-20260907-013833.md) y
[copia documental](evaluacion_resultados.md).

| Métrica | Valor histórico registrado |
|---|---:|
| Fidelidad | 0,360 |
| Relevancia de la respuesta | 0,940 |
| Precisión del contexto | 0,990 |
| Acierto de fuente | 5/5 |

La configuración registrada es `openai/gpt-oss-120b` para chat y juez,
temperaturas 0,1 y 0,0; `models/gemini-embedding-001`, 768 dimensiones;
fragmentos 900/150, `top_k=4`, umbral 0,72, perfil `agente` y versiones 1.0.0
del dataset y prompts. La fidelidad se obtiene de los cinco valores
0,0; 0,2; 0,4; 0,2; 1,0. Las cuatro corridas anteriores repiten KB-01 y dos
registran errores de formato del juez: no forman diez casos independientes.

El comando exacto de esa ejecución no quedó registrado. El README documentaba
`python -m eval.evaluate` y este índice `python -m eval.evaluate --pausa 6`.
`--limite 5` es una opción admitida y compatible con la muestra observada,
pero no prueba la invocación original. No se atribuye una causa a la cifra 0,880.
**Estos resultados EP1 no representan el rendimiento actual de EP2.**

## Otros registros históricos EP1

| Archivo | Contenido preservado |
|---|---|
| [seed_db_log.txt](seed_db_log.txt) | Inicialización: 6 categorías, 4 SLA, 12 usuarios, 20 activos y 40 tickets ficticios. |
| [ingest_log.txt](ingest_log.txt) | Nueve documentos, fragmentación 900/150 y 98 vectores con Google de 768 dimensiones; el log indica 98 embeddings reutilizados de caché. |
| [test_pytest_log.txt](test_pytest_log.txt) | 88 pruebas aprobadas y una advertencia de caché; corresponde al estado histórico EP1, no al cierre EP2. |

## Comandos y condiciones de reproducción

Usar la [instalación ordenada del README](../../README.md#instalación-y-ejecución-ep2).
`seed_db.py` recrea las tablas: no ejecutarlo para consultar evidencias existentes.
La ingesta también genera archivos; no es un paso de lectura del repositorio.

Pruebas automatizadas con dobles, sin llamadas a proveedores:

```powershell
python -m pytest -q
python -m pip check
```

Evaluadores reales EP2, sujetos a autorización y cuota separadas:

```powershell
python -m eval.check_ep2_agent --offline-embeddings
python -m eval.check_ep2_memory
python -m eval.check_ep2_plan
```

`--offline-embeddings` impide descargas de Hugging Face; requiere el modelo
descargado. **No convierte la ejecución en offline: Groq usa red y consume cuota.**
Los verificadores de memoria y plan también fijan esas variables de Hugging Face,
manteniendo sus llamadas reales a Groq. No bloquean la red global ni las llamadas
a Google si se selecciona ese proveedor. Generan reportes en `.cache/` y utilizan
SQLite EP2 temporal; no confirman notas ni reconstruyen FAISS.

| Comando o interfaz | Tiempo y controles predeterminados |
|---|---|
| `src.ep2.cli` | 90 s cooperativos por consulta, timeout LLM de 30 s y ocho iteraciones. |
| `eval.check_ep2_agent` | Usa los límites del agente EP2: 90 s/30 s/ocho iteraciones por consulta, salvo configuración del entorno. |
| `eval.check_ep2_memory` | Usa esos límites por consulta y un timeout de 180 s por proceso hijo. |
| `eval.check_ep2_plan` | 300 s por fase, 360 s por proceso, timeout HTTP 30 s; 14 solicitudes y 80.000 tokens globales, 2.000 de salida por respuesta, intervalo 35 s y pausa 60 s; ocho iteraciones salvo configuración EP2. |

Estos controles están en [configuracion.py](../../src/ep2/configuracion.py),
[check_ep2_memory.py](../../eval/check_ep2_memory.py) y
[check_ep2_plan.py](../../eval/check_ep2_plan.py). El evaluador integral no cambia
el `.env` ni los 90 s predeterminados de la CLI normal. Sus tiempos incluyen
esperas y no deben presentarse como latencia de un servicio productivo.

Ejemplo admitido para una evaluación EP1 nueva, con **`LLM_API_KEY`**:

```powershell
python -m eval.evaluate --limite 5 --perfil agente --pausa 6
```

Consume cuota del proveedor configurado y escribe archivos nuevos en
`eval/resultados/`. No reproduce necesariamente las métricas antiguas ni sirve
para evaluar EP2. No ejecutar como parte de una revisión documental.

La [matriz IE1–IE10](../trazabilidad_ep2.md) relaciona estos registros con código,
pruebas y pendientes académicos, sin asignar calificaciones.
