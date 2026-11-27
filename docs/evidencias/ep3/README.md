# EP3 — Evidencia preparada para GitHub

Preparación: **27 de noviembre de 2026**. Los archivos de esta carpeta son
extractos publicables de ejecuciones identificadas, no resultados de una nueva
llamada al proveedor. Las bases operativas y los registros crudos quedan locales.

| Clase | Evidencia | Alcance |
|---|---|---|
| Pruebas automatizadas | [Regresión de preparación](automatizadas/regresion_20261127.json) y [JUnit portable](automatizadas/pytest_20261127.xml) | Suite completa EP1/EP2/EP3 con red/DNS y subprocesos bloqueados; SQLite funcional protegida. Incluye Streamlit AppTest, equivalencia con/sin instrumentación y fallas de telemetría. |
| Offline simulada | [Evaluación](simulada/evaluacion_20261126.json) y [métricas por caso](simulada/metricas_20261126.csv) | 26 escenarios; LLM y vectores simulados, FAISS y SQLite locales reales. Referencias estructuradas, restricciones y paráfrasis controladas. |
| Rendimiento | [30 pares originales](rendimiento/benchmark_20261126.csv) | Orden balanceado, calentamiento y semilla 20261126. Duración de `responder()`; preparación y flush fuera de tiempo. No estima latencia ni costo de Groq. |
| Seguridad y privacidad | [Auditoría](seguridad/auditoria_20261127.json) y [procedencia de archivos](seguridad/procedencia_20261127.json) | Rutas relativas, categorías y conteos; sin secretos, huellas de secretos, identidades, sesiones ni datos operativos. |
| Groq real EP3 | [Estado pendiente](real_groq/README.md) | No hay una corrida real EP3 acreditada. La evidencia real EP2 permanece separada. |
| Capturas del dashboard | [Estado e instrucciones](capturas/README.md) | No se aportaron capturas EP3. AppTest no equivale a una captura ni a aceptación visual manual. |

## Procedencia y transformación

La evaluación y el benchmark reutilizan la corrida local
`.cache/ep3/20261126T184710Z/evaluacion_final/`. El JSON conserva la fecha,
versión, Python, dependencias, métricas, tamaños de muestra, casos, controles,
contadores y SHA-256 de código/corpus. Su lista permitida elimina identificadores
de ejecución/evaluación, referencias de sesión y campos que no son necesarios
para revisar resultados. Los separadores de rutas relativas se normalizan a `/`.
El CSV de métricas elimina las columnas `evaluacion_id` y `ejecucion_id`; el CSV
de benchmark se conserva byte a byte. No se publican eventos crudos ni SQLite.

El JUnit portable conserva clase, nombre de función, duración y resultado por
prueba; los parámetros se sustituyen por ordinales `caso_NNNN`. Omite hostname,
directorios, salida capturada y variables del entorno. El resumen JSON
registra la huella del reporte original y del código comprobado. Los originales
permanecen en `.cache/`, fuera de Git. La regresión del día 27 es una nueva
comprobación; no se mezcla con las duraciones del benchmark del día 26.

Los resultados 1,0 de las referencias controladas no representan precisión de un
LLM real. Los tokens ausentes siguen siendo desconocidos; no equivalen a consumo
cero. El [desarrollo técnico](../ep3_desarrollo_tecnico.md), la
[Etapa 1](../ep3_etapa1.md) y los [hallazgos](../ep3_hallazgos.md) conservan sus
propios alcances y fechas. Algunas referencias de esos documentos son artefactos
locales ignorados; los extractos necesarios para GitHub están en esta carpeta.

Para reproducir desde PowerShell, consultar el [README](../../../README.md#observabilidad-ep3--ejecución-para-evaluación-académica)
y la [guía vigente](../../ep3_guia_completa.md#evaluación-y-dashboard-sin-servicios-externos).
Cada corrida usa una carpeta nueva y produce sus propias mediciones.
