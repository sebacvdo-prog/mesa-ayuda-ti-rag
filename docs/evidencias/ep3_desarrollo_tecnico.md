# EP3 — Evidencia del desarrollo técnico

Fecha: 26 de noviembre de 2026. La ejecución conserva el estado local anterior;
no hizo commit/push, publicación, instalación ni solicitudes a Groq.

## Estado por fase

| Fase | Estado | Alcance |
|---|---|---|
| A | COMPLETO | Captura previa, versiones y línea base fresca de 790 pruebas sin red externa. |
| B | COMPLETO | Contrato v2/v1, migración, HMAC estable, memoria/RAG, herramientas, solicitudes/tokens disponibles, CPU/RAM y controles humanos. |
| C | COMPLETO | Dashboard local de solo lectura, filtros, calidad por categoría y compatibilidad v1/v2. |
| D | PARCIAL | Evaluación y benchmark offline completos; Groq real pendiente de credenciales, cuota y decisión del operador. |
| E | COMPLETO | Negativas de privacidad, permisos, confirmación, expiración, idempotencia y fallas de telemetría. |
| F | COMPLETO en alcance offline | Análisis con registros concretos, hipótesis separadas y optimización medida del muestreador. |
| G | COMPLETO | Guías, esquema de informe, defensa, declaración de IA y procedimiento de capturas auténticas. |
| H | COMPLETO | Regresión completa, integridad, diff, migración y HMAC entre procesos. |

## Pruebas realmente ejecutadas

| Corrida | Aprobadas | Fallidas | Errores | Omitidas |
|---|---:|---:|---:|---:|
| Línea base de esta tarea | 790 | 0 | 0 | 0 |
| Aceptación v1/v2 | 820 | 0 | 0 | 0 |

Los conteos y tiempos exactos están en [el resumen JSON](ep3_desarrollo_tecnico_resultados.json),
y los JUnit/logs originales en la carpeta de evidencia. Se incorporaron 30 casos
respecto de la línea base fresca. Los ocho avisos de la API
RunnableWithMessageHistory no son fallas; no se migró LangChain.

Hubo cero intentos de red externa/DNS bloqueados, cero subprocesos de pruebas y
cero escrituras funcionales bloqueadas. Los socketpair locales contabilizados
por separado son IPC estándar de Windows para AppTest, restringidos al socket y
puerto creados por esa función. No autorizan conexiones arbitrarias a loopback.

Se comprobó Streamlit sobre bases ausentes, vacías, v1 y v2, filtros de calidad,
no construcción del agente e integridad del archivo. También se verificaron
datos corruptos, tokens NULL, callbacks de resumen sin duplicación, recursos y
fallas aisladas. No se generaron capturas GUI.

Una corrida completa intermedia encontró cuatro fallas por un audit hook de un
diagnóstico EP2 que permanecía activo después de terminar. Se acotó su vida sin
alterar su protección durante el diagnóstico, y se añadieron regresiones de
salida normal/error. También se ajustó el arnés al IPC de AppTest y se recogieron
los ciclos del seed temporal fuera del cronómetro para liberar handles Windows.
El seed funcional no cambió. Las corridas intermedias se conservan; sus resultados
no se mezclan con la aceptación final ni se ocultan.

## Calidad y rendimiento medidos

Se ejecutaron 26 escenarios referenciados. LLM y vectores son simulados; LangChain,
FAISS, corpus y SQLite son componentes locales efectivos. Las métricas comparan
hechos de herramientas, documento esperado, restricciones y consistencia entre
paráfrasis equivalentes. No usan similitud como exactitud ni evalúan calidad
generativa de Groq. Los valores y denominadores están en el resumen JSON y CSV.

El benchmark tiene 30 pares, semilla fija y orden balanceado (15 on/off y 15
off/on). Usa bases nuevas equivalentes y calentamiento. Solo cronometra
responder(); el seed, gc de preparación y flush quedan fuera de la ventana.
Se exportan todos los pares, incluso deltas negativos. No se compara duración de
suite como si fuese sobrecarga del agente, ni se extrapolan porcentajes a una API
real, carga productiva o SLA. La telemetría contiene las consultas de escenarios,
una consulta de calentamiento observada y los pares instrumentados; consultas no
equivale a número de escenarios. Ese calentamiento reutiliza categoría ticket_sla
y no forma parte de las referencias ni de las 30 muestras del benchmark.

Los tokens ausentes se conservan NULL/no disponibles. CPU y RAM son snapshots del
proceso completo; no atribución exclusiva ni pico por consulta. La
[matriz de hallazgos](ep3_hallazgos.md) cita trace_id/evento_id y separa hechos,
hipótesis, impacto, costo, riesgo y verificación. Los estudiantes deben elaborar
sus propias conclusiones a partir de esas evidencias.

## Preservación, migración y HMAC

- Las huellas de .env, ITSM, bases funcionales, índices, manifiesto y cachés coinciden
  antes/después. No falta ningún archivo preexistente y no se instalaron paquetes.
- Prompts, guardarraíles, contratos/esquemas v1, herramientas, planificador y
  configuración EP2 conservan sus hashes. Las fábricas de modelos conservan su AST.
- La copia controlada de la muestra anterior migró 31 eventos a BD v2 sin cambiar
  ninguno de sus JSON; conserva un respaldo BD v1. El origen sigue intacto.
- Dos procesos distintos produjeron la misma referencia HMAC con una clave dedicada.
  La clave no está en evidencias públicas. Sin clave se desactiva correlación;
  los metadatos desconocidos de v1 se muestran como desconocidos, sin inventarlos.
- La retención es una ventana de lectura configurable. No se borran evidencias
  automáticamente. La clave requiere ACL local y reinicio al cambiar configuración.

## Archivos y reproducción

El [resumen JSON](ep3_desarrollo_tecnico_resultados.json) incluye inventario completo
de archivos creados/modificados, versiones instaladas, métricas, controles y
huellas de evidencias. La captura previa preserva los cambios EP2/EP3 que ya
existían y el diff se calcula contra esa captura, sin mezclarlos con este trabajo.

Raíz de artefactos locales: `.cache/ep3/20261126T184710Z/`:

- `previo/`: estado y código anteriores a esta tarea.
- `baseline/`: línea base fresca y JUnit/log/JSON.
- `aceptacion_v1_v2/`: regresión de aceptación completa y JUnit/log/JSON.
- `evaluacion_final/`: SQLite, evaluacion.json, evaluaciones.csv y benchmark.csv.
- `analisis_final/`: análisis y matriz generados desde los registros finales.
- `exportacion_final/`: eventos JSON/CSV sanitizados.
- `migracion_controlada/`: copia migrada, respaldo y verificación.
- `hmac_proceso_1.json` / `hmac_proceso_2.json`: prueba entre procesos, sin clave.
- `recursos_antes.json` / `recursos_despues.json`: 200 muestras por versión.
- `cambios_sobre_previo.patch`: revisión de cambios, normalizando saltos de línea.

La [guía vigente](../ep3_guia_completa.md) contiene comandos PowerShell para
instalación, activación, evaluación, exportación, dashboard y desactivación.
El [esquema de informe](../ep3_esquema_informe.md) distribuye cinco páginas, y la
[guía de defensa](../ep3_defensa.md) registra la asistencia de IA y preguntas de estudio.

## Pendientes manuales y límites

Ejecutar con autorización la prueba Groq real y contrastar disponibilidad/cuota;
capturar el dashboard auténtico con origen y filtros visibles; revisar la pauta;
y redactar análisis, reflexiones y justificaciones propias. AppTest no sustituye
una captura GUI. No se demuestra autenticación empresarial, cumplimiento
normativo, carga multiusuario ni sobrecarga cero. Cerca de un límite de tiempo,
la instrumentación puede influir en la detención; no se aumentaron límites.
