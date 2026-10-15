# Evidencia — Integración real del agente EP2 con Groq

Fecha: **15 de octubre de 2026**. Modelo: **`openai/gpt-oss-20b`**, usando la misma
clave y endpoint Groq existentes, sin imprimir credenciales. Llamadas reales con
`create_tool_calling_agent` y `AgentExecutor`, herramientas locales, ITSM en modo
solo lectura y FAISS existente. No se sustituyó el modelo por un doble en estas
corridas. Las pruebas automatizadas se identifican por separado al final.

## Reproducción

```powershell
.\.venv\Scripts\python.exe -m eval.check_ep2_agent --offline-embeddings
```

El modo offline afecta a Hugging Face y requiere el modelo descargado; Groq
requiere red y consume cuota. El verificador usa una base EP2 temporal bajo
`.cache/`, nunca invoca la API humana de confirmación y comprueba que haya cero
notas y que el hash del ITSM permanezca igual. Guarda todos los intentos locales
en `.cache/ep2_integracion_real.json`, excluido de Git.

Versiones comprobadas: Python 3.12.6; LangChain 0.3.30; Core 0.3.86;
`langchain-openai` 0.3.35; `langchain-huggingface` 0.1.2. Sin actualización de
dependencias durante la Etapa 2.

## Última corrida completa

Finalización UTC: **2026-10-15 04:30:54**. Código de salida del verificador: **0**.

| Caso | Selección real del modelo, en orden | Resultado observado | Verificaciones |
|---|---|---|---|
| consultas | `consultar_ticket` → `consultar_sla` → `consultar_activo` | INC-2026-0411 escalado/P2; primera respuesta 30 min y resolución 8 h; activo ACT-0003, HP ProBook 450. | Aprobadas. |
| analisis | `analizar_incidente` | Triage `seguimiento_nivel_2` por estado escalado y nivel 2; fuentes ticket y SLA. | Aprobadas. |
| rag | `buscar_procedimiento` | Recuperó `politica_seguridad_ti.md` y `kb_conectividad_vpn.md`; respuesta sobre VPN/FortiClient con esas fuentes. | Aprobadas. |
| nota | `registrar_nota_ticket` | Vista previa «Se solicita seguimiento del caso.»; estado `requiere_confirmacion`; no se guardó. | Aprobadas. |

**4/4 casos aprobados**, seis herramientas distintas ejecutadas. Cada caso
comprueba estado esperado, herramientas necesarias, cero escrituras y hash ITSM
intacto. Además, la búsqueda exige fuentes del corpus y la nota exige una
solicitud de confirmación. No se fuerza la selección con `tool_choice` ni se
ejecutan herramientas manualmente para hacer pasar los casos.

Duraciones de herramienta en esta corrida: ticket 3.568 ms; SLA 1.132 ms;
activo 1.802 ms; análisis 1.906 ms; búsqueda 8034.994 ms, incluida la primera
carga del modelo local; propuesta 2.693 ms. No son latencias totales del agente:
excluyen las llamadas a Groq.

La lectura real utilizó Hugging Face `all-MiniLM-L6-v2`, 384 dimensiones,
umbral `0.471764`. No se recalibró ni se reconstruyó el índice. La alternativa
Google y su umbral `0.72` permanecen configurables; no se llamó a su API.

## Historial e incidentes de verificación

Se conservan **12 resultados de caso aprobados en tres corridas completas**:

1. 04:25:29–04:25:51 UTC: los cuatro casos pasaron; después falló la limpieza del
   directorio temporal con `WinError 32`. El context manager de SQLite no cerraba
   la conexión del contador. Se corrigió con `contextlib.closing`; no fue un
   fallo de Groq ni se registró una nota.
2. 04:29:01–04:29:15 UTC: cuatro casos aprobados y salida 0 tras corregir el cierre.
   En análisis, el modelo consultó primero el ticket y luego el triage: variación
   permitida de su selección autónoma.
3. 04:30:43–04:30:54 UTC: cuatro casos aprobados y salida 0 con el código final.
   Se ajustó el verificador para fijar offline antes de importar Hugging Face,
   y el cronómetro a `perf_counter` para medir operaciones breves en Windows.

SHA-256 del JSON local al documentar estos 12 resultados:
`306f9303df9d01e19a7e1abd3ddbff2c30f005d06a7c5509eff1779bbaf900b8`.
Una nueva ejecución agrega intentos y cambia esta huella.

En la primera suite completa, la prueba preexistente de inicialización concurrente
alcanzó el timeout de su barrera de cinco segundos (`BrokenBarrierError`) mientras
se ejecutaba también la integración. La causa exacta no quedó demostrada. Pasó
aislada y en las dos suites completas siguientes sin cambiar esa prueba ni el
almacenamiento de Etapa 1; el fallo transitorio se deja registrado.

## Pruebas automatizadas y alcance de la evidencia

Último `python -m pytest -q`: **214 passed in 13.47s** — 181 anteriores + 33
nuevas. Los tests de agente usan un modelo guionado, el ejecutor LangChain real
y SQLite temporal. Validan selección/observación, las seis herramientas,
permisos, rechazo de argumentos de autorización, lotes inválidos, confirmación
humana, errores sin excepciones sensibles, límites, aislamiento entre consultas,
filtros documentales y limpieza del verificador en Windows.

`python -m pip check`: **No broken requirements found**.

Las confirmaciones y escrituras efectivas se probaron exclusivamente en bases
temporales automatizadas. La integración con Groq verificó la propuesta y la
pausa; no afirma haber realizado una escritura autorizada por una persona.
La evaluación acredita integración en estos casos, no fidelidad semántica
universal, autenticación empresarial, memoria entre sesiones ni planificación
adaptativa. Las métricas de recuperación previas conservan sus límites:
[calibración existente](calibracion_embeddings_locales.md).
