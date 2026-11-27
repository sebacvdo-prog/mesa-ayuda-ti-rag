# EP2: recuperación FAISS y salida segura sin procedimiento

Fecha: 30 de octubre de 2026. Validación local, sin llamadas a Groq ni descarga
de modelos. Se conserva `tool_choice="auto"` y no se modifican los umbrales,
el modelo, las credenciales, los filtros de fuente o los permisos documentales.

## Causas comprobadas y límite de la investigación

El índice local es `IndexFlatL2`, con 98 vectores de 384 dimensiones y embeddings
Hugging Face normalizados. FAISS devuelve distancias al cuadrado; el conector
instalado convierte con `1 - distancia² / sqrt(2)`. Esta es la escala sobre la
que se calibró el umbral `0.471764`, no coseno ni una probabilidad.

Para candidatos lejanos, esa conversión puede producir valores negativos. La
API de relevancia de LangChain emite entonces la advertencia y reproduce los
documentos en ella, pero no los elimina por sí misma. Además, un valor inferior
a -1 no cabía en `FragmentoRecuperado` y podía invalidar el lote completo,
incluidos candidatos válidos. Esto es distinto del resultado `SIN_PROCEDIMIENTO`.

La búsqueda ahora obtiene las distancias FAISS, aplica la misma conversión y
descarta individualmente los scores no finitos o fuera de [0, 1]. Los scores
válidos conservan exactamente su valor; no se recortan, reescalan ni sustituyen
por coseno. Después se siguen aplicando fuente, permisos, umbral, vigencia y
`top_k`. El contrato de `FragmentoRecuperado` también exige scores finitos en
[0, 1]. El cambio evita la advertencia sin silenciarla globalmente.

Las trazas de decisiones no conservan los argumentos de consulta y fuente. No
se pudieron reconstruir los de la llamada que falló. La solicitud original
facilitada por el usuario sí recupera procedimientos con las cuatro opciones de
fuente, tanto antes como después del cambio. Por ello **no se atribuye una causa
definitiva al `SIN_PROCEDIMIENTO` de esa prueba real**.

## Reproducción sobre el índice local

Se usa el mismo modelo local, sin caché de escritura ni reconstrucción del índice.
La etiqueta «original» corresponde a la solicitud de ticket, SLA y diagnóstico
VPN facilitada por el usuario; no acredita los argumentos elegidos por Groq.

| Consulta local | Fuente | Mejor score previo al corte | Fragmentos aceptados |
|---|---|---:|---:|
| Original | automatica / ruta interna | 0.518811 | 3 |
| Original | interna | 0.518811 | 3 |
| Original | externa | 0.504399 | 1 |
| Original | mixta | 0.518811 | 4 |
| VPN FortiClient | automatica / ruta externa | 0.199071 | 0 |
| VPN FortiClient | interna | 0.412172 | 0 |
| VPN FortiClient | externa | 0.199071 | 0 |
| VPN FortiClient | mixta | 0.412172 | 0 |

Encontrar vecinos como `kb_conectividad_vpn.md` o `fortinet_vpn.md` no basta para
aceptarlos: deben cumplir el corte y los filtros. La consulta corta también
queda vacía con fuente mixta. En esa reproducción, la advertencia y el resultado
vacío coinciden, pero quitar la advertencia no cambia el resultado del umbral.
No se redujo el corte ni se amplió la fuente para forzar una recuperación.

Las 20 preguntas del dataset mantienen exactamente los mismos fragmentos y
puntajes aceptados que antes del cambio, con el umbral vigente. El caso local
sin procedimiento queda vacío con las cuatro fuentes. Las 12 búsquedas de la
matriz local y las 20 del dataset terminaron sin advertencias de relevancia y con
cero intentos de conexión.

## EP2 cuando no hay evidencia admisible

En un plan estructurado, `SIN_PROCEDIMIENTO` bloquea el paso y cualquier nota
dependiente; puede añadir el triage permitido. Tras ese triage, la oferta vacía
producía `PLAN_BLOQUEADO` antes de alcanzar la respuesta segura RAG.

Ahora ese caso devuelve `sin_contexto` y la respuesta fija que indica falta de
procedimiento y derivación a Nivel 2. No se invoca al modelo para inventar pasos,
no se completa el paso bloqueado y no se propone ni registra una nota. Se
conservan las fuentes de las lecturas válidas. Otros errores o denegaciones,
incluido un fallo del triage, mantienen su salida de error.

## Pruebas

Se agregaron 17 casos con FAISS real y vectores explícitos, SQLite temporal y
modelo guionado: scores inválidos junto con evidencia válida, las cuatro fuentes,
permisos, umbral insuficiente, salida segura y ausencia de escrituras, con y sin
nota pendiente, y preservación de errores del triage. No se descargan modelos ni
se llaman APIs durante la suite.

Suite completa: **605 pruebas aprobadas**, sin fallos, errores ni omisiones;
`NETWORK_ATTEMPTS_BLOCKED: 0`. `git diff --check` también aprobado.

Los informes locales sanitizados quedan fuera de Git:
`.cache/ep2_rag_diagnostico_local.json` y `.cache/ep2_rag_pytest.xml`.

Referencia de la métrica: [documentación oficial de FAISS](https://github.com/facebookresearch/faiss/wiki/MetricType-and-distances).
