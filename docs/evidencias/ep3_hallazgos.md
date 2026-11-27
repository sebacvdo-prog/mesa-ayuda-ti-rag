# Análisis EP3 de registros observados

Fuente: `observabilidad.db`. Los resultados se separan por origen.

| Hallazgo observado | Evidencia concreta | Impacto | Hipótesis (no demostrada) | Propuesta | Riesgo / costo | Verificación |
|---|---|---|---|---|---|---|
| simulada: 60 consultas, 60 tiempos, P95 51.559290161821984 ms | analisis.json/origenes_separados/simulada/kpi | Describe solo esta muestra | El volumen y el modelo condicionan los tiempos | Repetir con condiciones documentadas | Bajo; nuevas corridas | Comparar mismos escenarios y tamaños de muestra |
| simulada: errores de modelo observados | trace `0269004c-b604-4e00-b950-cc909394271e`, evento `0c59cdb8-6655-47df-9faa-fb6439594339`, `HTTP_429` | Puede interrumpir o recuperar una consulta | Inyección controlada si el origen es simulado | Conservar clasificación, correlacionar con llamada_fin | Bajo; sin cambiar reintentos | Revisar resultado definitivo de cada llamada_id |
| Tokens de entrada disponibles en 0/115 respuestas | Eventos modelo_fin y detalles.origen_tokens | No se puede afirmar consumo faltante ni costo | El doble de modelo puede no informar uso | Mantener NULL y ejecutar prueba real autorizada | Consumo externo; pendiente | Inspeccionar usage del proveedor sin guardar mensajes |

## Alcance del benchmark

Los pares comparan responder() en caliente con bases temporales equivalentes, orden balanceado y semilla fija. El vaciado de la cola está fuera de la ventana medida.
El benchmark local sin espera de red puede amplificar el porcentaje de sobrecarga. Los deltas pueden ser negativos por variación del proceso; no se recortan ni se ocultan.
No se aplicaron optimizaciones especulativas a prompts, herramientas o planificación. Se mantiene la cola acotada y escritura por lotes. Una optimización adicional requiere medir antes y después.

## Límites para la interpretación

- No se midió Groq, exactitud generativa real, carga multiusuario ni precisión semántica de embeddings reales.
- Las comprobaciones de calidad comparan hechos, documentos e invariantes contra referencias controladas; no usan similitud FAISS como exactitud.
- Esta matriz proporciona evidencia e hipótesis técnicas; los estudiantes deben elaborar sus propias conclusiones y justificar sus decisiones.

## Candidato observado en esta simulación

Entre las etapas inclusivas de modelo, herramienta, memoria y RAG, `memoria_fin` tiene la mayor media: 6.1659 ms en 124 eventos. Ejemplo: trace `df34c4fa-2ce9-4a0d-bd1a-0e04b65b117c`, evento `d5721f38-5312-4d1d-b94f-bb084fa33018`. No demuestra causalidad ni un cuello de botella de Groq; requiere perfilado antes de cambiar lógica funcional.

## Optimización medida de observabilidad

Se cachearon clases y funciones nativas del muestreador, sin cachear las muestras. En 200 muestras por versión se observaron medias de 0.065289 ms antes y 0.004252 ms después. Evidencia: recursos_antes.json y recursos_despues.json, con hashes de fuente. Riesgo/costo bajo, sin dependencias ni cambios al agente. Verificación: working set positivo, CPU monotónica, cache de API de tamaño 1 y regresión completa. Dos procesos secuenciales sin intervalo de confianza: no extrapolar a latencia total o proveedor real.
