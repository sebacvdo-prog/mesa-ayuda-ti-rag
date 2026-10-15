# Decisiones del Pipeline de Ingesta y Recuperación

## Fragmentación (chunking)

### Tamaño del fragmento: 900 caracteres

Se eligió 900 caracteres como compromiso entre dos extremos:

- **Demasiado chico** (< 400): los procedimientos numerados quedan partidos por la mitad. El paso 3 de un procedimiento de 8 pasos aparece sin contexto y sin el criterio de escalamiento que viene al final.
- **Demasiado grande** (> 1.500): el fragmento recuperado contiene ruido de secciones vecinas, y el modelo usa ese ruido para responder. Además, 1.500 caracteres de contexto × 4 fragmentos = 6.000 caracteres, que sumados al few-shot ya se acercan al límite útil de atención del modelo.

Con 900 caracteres, un procedimiento típico de la KB (título + 5 a 8 pasos + nota de escalamiento) cabe en 1 o 2 fragmentos, y los 4 fragmentos de contexto suman ~3.600 caracteres: suficiente para responder con sustento sin saturar la ventana.

### Solape: 150 caracteres (~17 %)

El solape previene el corte justo en una oración de decisión ("si persiste, escalar a Nivel 2"). Con 150 caracteres, esa oración se replica en el fragmento siguiente y el retriever puede recuperar cualquiera de los dos sin perder la indicación.

### Separadores

En orden de preferencia:

1. `\n## ` — encabezado de sección Markdown (H2)
2. `\n### ` — encabezado H3
3. `\n\n` — párrafo
4. `\n` — línea
5. `. ` — oración
6. ` ` — palabra
7. `""` — carácter

Cortar por encabezado primero garantiza que un fragmento rara vez parta un procedimiento numerado por la mitad. Los encabezados H2 y H3 son los que separan los procedimientos en la KB.

## Embeddings

### Modelo: `gemini-embedding-001`

- 768 dimensiones (se solicita `output_dimensionality=768` también en cada llamada de embeddings, porque el conector 2.x no conserva ese parámetro del constructor).
- Cuota gratuita: 1.000 peticiones/día.
- Caché en disco: los vectores se guardan en un SQLite local (`.cache/embeddings.sqlite`) indexados por SHA-256 de `configuración|tipo|texto`. La configuración incluye proveedor, modelo, dimensión y normalización.

### Alternativa local para EP2

La alternativa de Google y `langchain-google-genai` se conservan. Para evitar la
dependencia de permisos y cuota de Google durante EP2, `EMBEDDING_PROVIDER=huggingface`
ejecuta `sentence-transformers/all-MiniLM-L6-v2` en CPU, con 384 dimensiones y
vectores normalizados. Cada índice identifica su configuración y la reconstrucción
conserva el índice anterior como respaldo.

## Recuperación

### `top_k = 4`

Cuatro fragmentos cubren hasta 2 procedimientos distintos (un procedimiento ocupa 1-2 fragmentos). Con 6 fragmentos ya se observa que el modelo copia texto de un procedimiento ajeno; con 2, pierde el contexto de escalamiento.

### Umbral original de Google: 0,72

Se estableció empíricamente con el dataset de evaluación:

- Con 0,60 entraban fragmentos del catálogo de servicios en preguntas de VPN (ruido).
- Con 0,80 se descartaban fragmentos pertinentes en preguntas formuladas con lenguaje coloquial ("la VPN no me anda" vs. el vocabulario técnico de la KB).
- 0,72 descarta el ruido sin penalizar la variabilidad léxica esperable de un agente de Nivel 1.

### Umbral configurable de Hugging Face

`HF_SIMILARITY_THRESHOLD=0.471764` afecta exclusivamente a Hugging Face. Se obtuvo
evaluando los intervalos definidos por las puntuaciones reales, con el enrutador,
los permisos, el reordenamiento y `top_k=4` del proyecto. FAISS devuelve distancia
L2 al cuadrado; el conector instalado aplica `1 - distancia² / sqrt(2)`.
Se conserva esa escala y el comportamiento de Google.

El criterio exige rechazar el caso sin fuente (`NEG-02`), maximiza el acierto de
fuente y desempata por precisión documental proxy. El umbral es el punto medio
del intervalo estable elegido. En el dataset actual mejora de 1/19 a 11/19
aciertos de fuente, con 0/1 contextos para casos sin fuente. La validación que
excluye cada pregunta con fuente de su propia calibración obtiene 10/19.

Esto todavía no demuestra recuperación confiable en todos los casos: siete
fuentes esperadas puntúan por debajo del caso sin fuente y `EXT-04` queda
bloqueado por el filtro del enrutador. Un umbral único no puede corregir esos
límites. Ver [método, comparaciones y resultados por pregunta](evidencias/calibracion_embeddings_locales.md).
Reproducir con `python -m eval.calibrate_retrieval --offline`; no usa Groq ni juez.

### Búsqueda ampliada

Se piden `top_k * 5 = 20` candidatos al índice FAISS, porque el filtrado por fuente y nivel de acceso puede descartar muchos. Sin ese margen, una consulta de perfil `usuario_final` (que no ve documentos `restringido_agentes`) podría quedarse sin contexto.

### Re-ranking por vigencia

Cuando dos fragmentos tienen puntajes de similitud que difieren en menos de 0,05 (el `MARGEN_REORDENAMIENTO`), se consideran equivalentes en pertinencia. Entre ellos, prevalece el documento con `fecha_vigencia` más reciente.

Esto resuelve el caso concreto del aviso del CSIRT sobre fatiga de segundo factor (julio 2026) vs. el procedimiento interno de cuentas y accesos (abril 2026): ambos hablan de aprobación de MFA, pero el aviso describe un ataque que cambia el procedimiento.

### Enrutador de consultas

Clasifica la consulta en `interna`, `externa` o `mixta` por heurística de palabras clave. Es deliberadamente simple y conservador:

- `mixta` es el valor por defecto y nunca deja fuera documentos.
- Una clasificación equivocada solo cambia el filtro de fuente; el umbral de similitud sigue protegiendo la calidad.
- Un clasificador basado en el propio LLM gastaría cuota en cada consulta sin mejorar la calidad de forma medible.

## Conector SQL

Los tickets y la CMDB no se vectorizan: se consultan por SQL parametrizado con marcadores `?`. Tres razones:

1. Son datos estructurados con identificadores exactos (`INC-2026-0412`, `P2`, `ACT-0001`). Buscar por similitud semántica sería más lento y menos preciso.
2. Cambian con frecuencia. Revectorizar 40 tickets cada vez que se cierra uno no tiene sentido.
3. Contienen datos personales (RUT, teléfono, IP). Enviarlos al proveedor de embeddings para vectorizarlos expondría esos datos.

El conector detecta en la consulta del usuario: identificadores de ticket (`INC-xxxx`, `REQ-xxxx`), prioridades (`P1` a `P4`) y RUT. Si los encuentra, ejecuta la consulta SQL correspondiente y añade el resultado al bloque `DATOS DEL ITSM` del prompt.
