# EP3 — Guía de estudio para la defensa

Esta guía plantea temas y referencias. Las respuestas, reflexiones y defensa de
decisiones deben elaborarlas los estudiantes a partir de evidencias verificadas.

| Tema | Preguntas para preparar | Dónde contrastar |
|---|---|---|
| Observabilidad | ¿Qué aportan eventos, métricas y correlación? ¿Qué no prueba un log? | src/ep3/observabilidad.py, contratos_v2.py. |
| Modelo y decisiones | ¿Cuándo hay decisión sin solicitud? ¿Cómo se identifica un intento, una llamada lógica y un reintento? | instrumentacion.py y evento decision/modelo_inicio/llamada_fin. |
| LangChain | ¿Qué mide un callback? ¿Cómo se evita duplicar solicitudes heredadas del resumidor? | MedidorLLM y prueba de resumen EP1. |
| RAG | ¿Qué diferencia hay entre identidad KB, similitud y acierto documental? | retriever.py, rag_fin y referencias de escenarios_ep3.py. |
| Memoria | ¿Qué conserva SQLite y por qué observar no debe reconsultar ni modificar datos? | ep2/memoria.py; decorators memoria_fin. |
| Confirmación | ¿Por qué proponer/POSPONER no autoriza una nota? ¿Cómo se verifican expiración e idempotencia? | ep2/herramientas.py y escenarios seguridad. |
| Privacidad | ¿Por qué HMAC con clave estable? ¿Qué se muestra si falta? ¿Qué se registra al rotarla? | identidad.py, clave_id, correlacion y evidencia de dos procesos. |
| Rendimiento | ¿Cómo se define P95? ¿Qué incluye cada duración? ¿Por qué no se suman etapas inclusivas? | analisis.py y diccionario de métricas. |
| Recursos | ¿Qué mide working set/RSS frente a heap Python? ¿Por qué CPU es del proceso? | recursos.py y microbenchmark documentado. |
| Calidad | ¿Qué significan las muestras de cada métrica? ¿Qué sesgo introduce un modelo guionado? | evaluate_ep3.py, evaluaciones.csv y límites del reporte. |
| QA | ¿Por qué una prueba de equivalencia no demuestra sobrecarga cero ni calidad universal? | test_ep3_integracion.py y benchmark.csv. |
| Fallas | ¿Qué ocurre con cola llena, disco inaccesible o final abrupto? ¿Qué contadores faltan en disco? | tests de telemetría y salud_telemetria. |
| Seguridad local | ¿Por qué el dashboard es mode=ro? ¿Qué diferencia hay entre perfil declarado y autenticación? | lectura.py y límites de la guía. |

## Ejercicio de lectura de evidencia

Elegir un trace_id del JSON exportado y localizar sus eventos por secuencia.
Identificar qué datos son hechos observados, cuáles son referencias controladas,
cuáles representan fallas simuladas y qué hipótesis requeriría otra ejecución.
Relacionar una fila de la matriz de hallazgos con el registro concreto que la
respalda. Preparar una demostración local que funcione sin claves de proveedor.

## Registro del uso de asistentes de IA

Durante el desarrollo técnico se utilizó **Codex (asistente de IA)** para inspección
del repositorio, implementación de instrumentación/dashboard/evaluadores, creación
y ejecución de pruebas, análisis técnico y preparación de esta documentación.
El código y los resultados se validaron con los comandos y artefactos registrados.
No se ejecutaron solicitudes a Groq ni se generaron capturas de pantalla ficticias.

Para la declaración académica, completar según la pauta:

- Integrantes y responsables de revisión: **[completar por el equipo]**.
- Herramienta y fecha de uso: Codex, 26 de noviembre de 2026.
- Archivos/asistencia utilizada: inventario en evidencia de desarrollo técnico.
- Verificaciones realizadas personalmente: **[completar con acciones reales]**.
- Análisis, conclusiones y justificaciones propias: **[elaborar por estudiantes]**.

No atribuir al equipo una revisión manual, captura o ejecución real que no haya
efectuado. La asistencia técnica no reemplaza el estudio ni la responsabilidad
de comprobar las afirmaciones incluidas en el informe.
