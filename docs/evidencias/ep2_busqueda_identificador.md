# EP2: causa y verificación de KB-RED-02

Fecha: 30 de octubre de 2026. Diagnóstico local, sin solicitudes a Groq.

## Evidencia del argumento y causa demostrada

La última fila de la caché SQLite de embeddings (fila 130 al inspeccionarla) tiene
la clave SHA-256 correspondiente a la configuración activa y a la consulta exacta
`KB-RED-02`. Se comprobó en modo de solo lectura, sin imprimir vectores, claves
de API ni consultas ajenas. Esto acredita que se vectorizó ese código, en lugar
de la solicitud completa. La caché no conserva el argumento `fuente`; ese dato
histórico no se puede reconstruir.

El servicio pasaba `consulta` directamente a la búsqueda semántica y convertía
`fuente="automatica"` en la clasificación heurística. No había resolución exacta
de identificadores KB, aunque el título persistido del documento empieza por
`KB-RED-02`. Un código no tiene la misma representación semántica que una
descripción del problema.

Reproducción con el índice local vigente y el mismo modelo de embeddings:

| Consulta | Documento | Mejor puntaje semántico |
|---|---|---:|
| KB-RED-02 | politica_seguridad_ti.md | 0.198727190 |
| KB-RED-02 | kb_conectividad_vpn.md | 0.055327237 |
| KB-RED-02 | fortinet_vpn.md | -0.061243653 |
| KB-RED-02 VPN | kb_conectividad_vpn.md | 0.471641 |
| Solicitud completa facilitada por el usuario | kb_conectividad_vpn.md | 0.544752 |

El umbral vigente es `0.471764`. Para el código solo, todas las opciones de fuente
quedan vacías en la ruta semántica. No hay indicio de que un permiso sea el
descarte determinante en esta reproducción: los candidatos válidos permitidos
también quedan por debajo del umbral. No se cambió el corte para admitirlos.

El diagnóstico del control automático registra: 20 vecinos antes de fuente,
16 después de fuente FAISS, 3 scores válidos, 3 después de permisos y 0 después
del umbral. La condición final era una lista vacía en
`HerramientasEP2.buscar_procedimiento()`, que devuelve `SIN_PROCEDIMIENTO`.
Los scores negativos son candidatos inválidos ya descartados por la corrección
anterior; no explican que la KB con score positivo quede bajo el corte.

## Corrección delimitada a EP2

La entrada RAG de EP2 ahora distingue dos tipos de consulta:

- Si contiene un código KB válido, busca una coincidencia exacta al inicio del
  título en el docstore del índice FAISS existente. Aplica fuente y permisos,
  comprueba que el código no sea ambiguo y devuelve hasta `top_k` fragmentos,
  ordenados por vigencia y posición. No calcula embeddings ni inventa un score:
  la respuesta marca `coincidencia="identificador"` y `puntaje=null`.
- Sin código KB, conserva la búsqueda semántica y el umbral actuales.

La identidad documental se comprueba directamente por metadatos; el umbral de
similitud sigue reservado a las búsquedas semánticas. Un código inexistente,
ambiguo, no autorizado o incompatible con la fuente explícita no devuelve otros
documentos como sustitutos. EP1 conserva su método de búsqueda semántica.

La consulta `KB-RED-02` obtiene 11 fragmentos exactos de la KB, todos permitidos
para el perfil agente y la fuente interna, y devuelve 4. El resultado es
`PROCEDIMIENTO_RECUPERADO`, con procedencia `corpus:kb_conectividad_vpn.md`.
No se reconstruyó el índice ni se modificaron modelo, credenciales, cuotas,
memoria, permisos, planificación o la confirmación humana de notas.

## Diferencia entre prueba local y CLI

Las reproducciones anteriores enviaban la solicitud completa o frases sobre VPN.
Eso no ejercitaba la consulta formada únicamente por el código, evidenciada en
la caché. Además, los tests con scores prefijados no representaban la distancia
real de ese identificador. La CLI y el servicio no aplicaban un algoritmo RAG
distinto: faltaba comprobar los argumentos que había elegido el modelo.

Una nueva prueba ejecuta el bucle real de la CLI con el modelo guionado para
llamar `buscar_procedimiento(consulta="KB-RED-02")`, FAISS real, SQLite temporal,
las seis herramientas y `tool_choice="auto"`. Ticket, SLA y procedimiento quedan
completados, sin notas ni auditoría de escrituras. Se prueba tanto con diagnóstico
como sin él, y se comprueba que el diagnóstico no se persista en memoria.

## Diagnóstico seguro

La opción `--diagnostico-rag` de la CLI muestra datos de la llamada efectiva:
consulta solo cuando es un código KB, hash y longitud cuando es texto libre,
fuente solicitada, ruta y filtro efectivos, niveles visibles, umbral, límites,
conteos por etapa y motivo del resultado. La ruta semántica muestra además hasta
20 nombres documentales conocidos, distancias y scores antes de filtros.

No muestra texto de fragmentos, títulos libres, identificadores de usuario o
sesión, credenciales, payloads ni excepciones. Omite los nombres de documentos
que el perfil no puede consultar. El diagnóstico no autoriza acciones ni añade
llamadas al modelo o a embeddings: la ruta semántica reutiliza un único embedding
para las dos búsquedas locales de diagnóstico.

## Verificación desde PowerShell sin Groq

Desde la raíz del repositorio:

```powershell
.\.venv\Scripts\python.exe -m eval.check_ep2_retrieval --consulta "KB-RED-02" --fuente automatica
```

El comando bloquea la red, utiliza el modelo Hugging Face ya disponible y el
índice local, no construye un LLM y no escribe en la caché de embeddings ni en
el ITSM. Primero muestra el control semántico (`motivo="UMBRAL"`, cero resultados)
y después la resolución exacta (`motivo="RECUPERADO"`, cuatro fragmentos).
Debe terminar con `resultado="PROCEDIMIENTO_RECUPERADO"`, `intentos_red=0` y código
de salida 0. Con `--fuente externa`, la KB interna debe seguir siendo rechazada.

Para ejecutar las regresiones sin APIs:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_ep2_recuperacion.py
```

En una siguiente prueba real realizada por el usuario, la CLI habitual acepta:

```powershell
.\.venv\Scripts\python.exe -m src.ep2.cli --usuario agente_demo --sesion sesion_demo --diagnostico-rag
```

Esta última interfaz sí utiliza Groq al enviar una consulta; no se ejecutó una
consulta real durante este trabajo. Sus líneas `Diagnóstico RAG:` permiten
comprobar la fuente y el argumento exacto del código en esa ejecución.

## Resultado de las verificaciones

- Suite completa: **621 pruebas aprobadas**, incluidas **16 regresiones nuevas**;
  sin fallos, errores ni omisiones. Red bloqueada, cero intentos de conexión.
- Comando de diagnóstico ejecutado con el índice y el modelo locales: código de
  salida 0, control semántico `UMBRAL`, herramienta EP2 `PROCEDIMIENTO_RECUPERADO`,
  cuatro fragmentos y cero intentos de red.
- `git diff --check` aprobado. Cambios locales, sin commit ni push.
