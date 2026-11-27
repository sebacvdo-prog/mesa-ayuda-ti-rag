# EP3 — Evidencia de línea base e instrumentación inicial

Fecha: 26 de noviembre de 2026. Validación local simulada; sin solicitudes a Groq.

## Estado previo y preservación

La referencia Git es `8d248c3b9aa90960db13a5de6f9709e91e60637b` sobre `master`. El directorio ya tenía
cambios EP2 y archivos sin seguimiento. La captura previa registra las huellas de
102 archivos visibles a Git y 12 artefactos protegidos. Se guardó una copia
del código/documentación previos, excluyendo `.env`, bases e índices de ejecución,
datos y resultados históricos de evaluación. No se hizo commit, push ni instalación.

La implementación modificó estos archivos preexistentes respecto de esa captura:

- `README.md`
- `src/agent.py`
- `src/config.py`
- `src/ep2/agente.py`
- `src/ep2/reintentos.py`
- `src/memory.py`

No desapareció ningún archivo preexistente. Los demás archivos preexistentes
conservaron su hash, incluidos prompts, proyección de contexto, herramientas,
planificador, configuración de modelos y requisitos. Las adiciones de EP3 están
identificadas en la [guía técnica](../ep3_observabilidad.md).

## Archivos nuevos EP3

- `docs/ep3_evento_v1.schema.json`
- `docs/ep3_observabilidad.md`
- `docs/ep3_traza_v1.schema.json`
- `docs/evidencias/ep3_etapa1.md`
- `docs/evidencias/ep3_etapa1_resultados.json`
- `eval/aislamiento_ep3.py`
- `eval/check_ep3_observabilidad.py`
- `eval/check_ep3_regression.py`
- `src/ep3/__init__.py`
- `src/ep3/almacenamiento.py`
- `src/ep3/contratos.py`
- `src/ep3/observabilidad.py`
- `tests/test_ep3_contratos.py`
- `tests/test_ep3_evaluacion.py`
- `tests/test_ep3_integracion.py`
- `tests/test_ep3_observabilidad.py`

## Entorno medido

Python: `3.12.6 (tags/v3.12.6:a4a2d2b, Sep  6 2024, 20:11:23) [MSC v.1940 64 bit (AMD64)]`.

| Dependencia | Versión instalada |
|---|---|
| `faiss-cpu` | `1.15.1` |
| `langchain` | `0.3.30` |
| `langchain-community` | `0.3.31` |
| `langchain-core` | `0.3.86` |
| `langchain-google-genai` | `2.1.12` |
| `langchain-huggingface` | `0.1.2` |
| `langchain-openai` | `0.3.35` |
| `langsmith` | `0.14.8` |
| `openai` | `2.54.0` |
| `pydantic` | `2.14.1` |
| `pytest` | `8.4.2` |
| `sentence-transformers` | `6.1.0` |
| `streamlit` | `1.66.0` |

La captura privada contiene el inventario completo. Las versiones permanecieron
iguales al terminar; no se instalaron dependencias ni se editaron credenciales.

## Pruebas y controles

| Corrida verificada | Aprobadas | Fallidas | Errores | Omitidas | Duración del arnés |
|---|---:|---:|---:|---:|---:|
| Línea base EP1/EP2 | 712 | 0 | 0 | 0 | 40.707 s |
| Regresión final con EP3 | 790 | 0 | 0 | 0 | 47.412 s |

Se incorporaron 78 casos nuevos. En ambas corridas verificadas hubo cero
intentos de red, cero subprocesos y cero escrituras bloqueadas durante las pruebas. Las huellas de
`.env`, ITSM, SQLite EP2, índices, manifiesto y cachés originales permanecieron
iguales. El código tampoco cambió durante la regresión final.

Las pruebas comparan respuestas completas, entradas al modelo, planes y memoria
con la instrumentación activada/desactivada bajo relojes e identificadores
controlados. Cubren permisos, propuesta y confirmación/cancelación de notas,
falta de contexto, errores, límites y replanificación; también fallas de disco,
recolector, inicio y reloj, cola llena, datos prohibidos y correlación concurrente.

La suite emitió seis advertencias de `RunnableWithMessageHistory` por la API
LangChain utilizada; no fueron fallas. Su migración queda fuera de esta etapa.

El primer intento del arnés registró 711 aprobadas y una fallida porque bloqueaba
una lectura SQLite legítima `mode=ro`. Se corrigió el arnés, sin modificar esa
prueba ni la lógica EP2, y se repitió la línea base antes de instrumentar EP1/EP2.
El intento inicial y las corridas intermedias se conservan en la carpeta local;
no se mezclan sus resultados con las dos corridas verificadas de la tabla.

Las duraciones de suite incluyen trabajo del arnés y no constituyen una medición
de latencia productiva ni una comparación de sobrecarga del agente.

## Muestra persistida para inspección

Se ejecutó `eval.check_ep3_observabilidad` con LLM y vectores simulados, LangChain,
FAISS y SQLite locales. Dos consultas reutilizan el plan y ejercitan su adaptación;
un 429 simulado provoca un reintento de inferencia. Las bases de negocio usadas
por la muestra fueron temporales y no se registraron notas.

| Dato calculado desde eventos persistidos | Valor |
|---|---:|
| Consultas | 2 |
| Ejecuciones de herramientas | 7 |
| Eventos de planificación | 18 |
| Errores del modelo simulado | 1 |
| Reintentos del modelo simulado | 1 |
| Eventos totales | 31 |
| Eventos descartados | 0 |

Todos están etiquetados `simulada`. Las latencias exactas medidas están en el JSON
de la muestra; representan ejecución local con un doble del modelo y no el tiempo
de Groq. No se calcularon precisión, fidelidad, tokens, costo ni uso de recursos.

## Evidencias y reproducción

El [resumen JSON sanitizado](ep3_etapa1_resultados.json) contiene conteos, controles,
versiones, verificaciones y huellas de las evidencias. El contrato está publicado en
[Evento v1](../ep3_evento_v1.schema.json) y [Traza v1](../ep3_traza_v1.schema.json).

Los artefactos completos están excluidos de Git, bajo
`.cache/ep3/20261126T120214Z/`:

- `pre_ep3/estado.json` y `pre_ep3/codigo_previo.zip`: referencia anterior a EP3.
- `baseline_verificada/`: JSON, JUnit y log de las 712 pruebas iniciales.
- `regresion_final/`: JSON, JUnit y log de las 790 pruebas finales.
- `muestra/observabilidad.db` y `muestra/resultado.json`: eventos y resumen simulados.
- `cambios_ep3_sobre_previo.patch`: cambios sobre el estado local previo, sin mezclar
  modificaciones EP2 anteriores. El diff normaliza saltos de línea para revisión.

Para repetir en carpetas nuevas, desde la raíz y usando el entorno existente:

```powershell
python -m eval.check_ep3_regression --salida .cache/ep3/otra_regresion
python -m eval.check_ep3_observabilidad --salida .cache/ep3/otra_muestra
```

## Límites y siguiente etapa

La instrumentación está desactivada por defecto. No se midieron proveedor real,
carga ni sobrecarga estadística. Las fallas de almacenamiento dejan contadores en
RAM; una terminación abrupta puede perder eventos pendientes. La clave HMAC es
efímera salvo inyección explícita de una clave estable. Antes del dashboard faltan
lectura/agregación, retención, control de acceso y gestión de clave entre procesos.
La confirmación humana y su auditoría funcional permanecen separadas de EP3.
