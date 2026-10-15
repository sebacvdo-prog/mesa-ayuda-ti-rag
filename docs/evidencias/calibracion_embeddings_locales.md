# Calibración de recuperación con Hugging Face

Modelo: `sentence-transformers/all-MiniLM-L6-v2`. Dataset SHA256: `443fccb8de34fbe33b9869a0d6437e5de53916bd1b4a8a5b4879f25a759ec930`.
Índice SHA256: `e768c7bbeaf0fddd3267fef9b1c1de99d89dccb528482a60262b948adeacaf3f`. Perfil: `agente`.
Versiones: `{'faiss-cpu': '1.15.1', 'langchain-core': '0.3.86', 'langchain-community': '0.3.31', 'langchain-huggingface': '0.1.2', 'sentence-transformers': '6.1.0'}`.

FAISS IndexFlatL2 devuelve distancia euclídea al cuadrado. El conector instalado
aplica `score = 1 - distancia_L2_cuadrada / sqrt(2)`. No es coseno ni probabilidad.
Verificación numérica: distancia² `0.632492900`, suma de cuadrados `0.632492900`, score `0.552759981` y coseno `0.683753431`.
Referencia: [métricas oficiales de FAISS](https://github.com/facebookresearch/faiss/wiki/MetricType-and-distances).

Criterio: rechazar los casos sin fuente; maximizar acierto de fuente@4;
desempatar por precisión documental proxy y amplitud del intervalo estable.
Se evaluaron todos los intervalos definidos por los scores sin redondear.
Umbral seleccionado: `0.471763939`, punto medio del intervalo
`(0.470855892, 0.472671986]`.

Umbral activo: `0.471764`. Se comprobó que las consultas reales de `RecuperadorVectorial.buscar()`
coinciden con la reproducción de la evaluación para todas las preguntas.

| Umbral | Aciertos de fuente@4 | Consultas con contexto | Contextos sin fuente | Precisión documental proxy |
|---:|---:|---:|---:|---:|
| 0.720000 | 1/19 | 1/20 | 0/1 | 100.0% |
| 0.600000 | 4/19 | 4/20 | 0/1 | 80.0% |
| 0.550000 | 7/19 | 7/20 | 0/1 | 83.3% |
| 0.500000 | 9/19 | 10/20 | 0/1 | 70.0% |
| 0.471764 | 11/19 | 13/20 | 0/1 | 68.0% |
| 0.450000 | 11/19 | 15/20 | 1/1 | 54.5% |
| 0.400000 | 13/19 | 17/20 | 1/1 | 45.8% |

Validación excluyendo cada pregunta con fuente de su propia calibración: 10/19 aciertos de fuente@4.

## Límites

El dataset contiene 20 consultas, 19 con fuente y 1 sin fuente.
`NEG-01` y `NEG-03` tienen fuentes de seguridad y accesos: no son casos sin fuente.
La selección usa este dataset; sus resultados no son una prueba independiente.
La validación por pregunta conserva el único caso sin fuente en entrenamiento.
Una coincidencia de archivo no garantiza que el fragmento responda la pregunta,
y un archivo diferente puede contener contexto complementario útil.
No se evaluaron respuestas generadas ni se llamó a Groq o al LLM juez.

El mayor score del caso sin fuente es `0.456351817`.
Las fuentes esperadas de SLA-01, SLA-03, SLA-04, POL-01, POL-03, EXT-01, NEG-01 tienen scores inferiores o iguales a esa frontera.
Ningún umbral único puede recuperar esas fuentes y a la vez rechazar el caso sin fuente.
Casos cuya fuente esperada queda bloqueada por el enrutador: EXT-04.
El umbral no corrige el modelo ni el enrutador; siguen pendientes esos límites
y la evaluación con más casos sin fuente y fragmentos etiquetados.

## Resultados del umbral seleccionado

| Caso | Ruta | Fuente esperada | Resultado |
|---|---|---|---|
| KB-01 | interna | kb_accesos_y_cuentas.md | kb_terminales_moviles.md, kb_accesos_y_cuentas.md, politica_seguridad_ti.md |
| KB-02 | mixta | kb_microsoft365.md | kb_microsoft365.md |
| KB-03 | mixta | kb_conectividad_vpn.md | fortinet_vpn.md, kb_conectividad_vpn.md |
| KB-04 | mixta | kb_conectividad_vpn.md | fortinet_vpn.md, kb_conectividad_vpn.md |
| KB-05 | mixta | kb_terminales_moviles.md | kb_terminales_moviles.md |
| KB-06 | interna | kb_microsoft365.md | kb_microsoft365.md |
| SLA-01 | interna | catalogo_servicios_sla.md | sin contexto |
| SLA-02 | interna | catalogo_servicios_sla.md | catalogo_servicios_sla.md |
| SLA-03 | interna | catalogo_servicios_sla.md | kb_microsoft365.md |
| SLA-04 | interna | catalogo_servicios_sla.md | sin contexto |
| POL-01 | interna | politica_seguridad_ti.md | sin contexto |
| POL-02 | mixta | politica_seguridad_ti.md | politica_seguridad_ti.md, kb_conectividad_vpn.md |
| POL-03 | interna | politica_seguridad_ti.md | sin contexto |
| EXT-01 | externa | microsoft_365_soporte.md | sin contexto |
| EXT-02 | externa | fortinet_vpn.md | fortinet_vpn.md |
| EXT-03 | mixta | csirt_avisos_seguridad.md | csirt_avisos_seguridad.md |
| EXT-04 | interna | csirt_avisos_seguridad.md | kb_conectividad_vpn.md |
| NEG-01 | mixta | politica_seguridad_ti.md | sin contexto |
| NEG-02 | mixta | ninguna | sin contexto |
| NEG-03 | interna | kb_accesos_y_cuentas.md | kb_accesos_y_cuentas.md |
