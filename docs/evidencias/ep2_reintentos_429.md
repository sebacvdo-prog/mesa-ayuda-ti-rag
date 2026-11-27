# EP2: reintento acotado ante HTTP 429 temporal

Fecha: 30 de octubre de 2026. Validación con HTTP simulado; sin llamadas a Groq.

La evidencia facilitada por el usuario indica un límite temporal de 8.000 TPM:
5.119 utilizados más 3.269 solicitados exceden ese límite. El proveedor indicó
esperar 2,91 segundos antes de volver a intentar. El agente ya había completado
las cuatro verificaciones; falló la inferencia para seleccionar la preparación
de nota. La fábrica tiene `max_retries=0`: hasta este cambio el 429 interrumpía
el turno inmediatamente. No se reprodujo este error con una conexión real.

## Política implementada

`src/ep2/reintentos.py` repite únicamente `modelo.invoke()`, con idénticos
mensajes, configuración y herramientas enlazadas. No reinicia `AgentExecutor`,
no vuelve a proyectar memoria ni ejecuta herramientas dentro del bucle.
El planificador recibe la respuesta exitosa una sola vez y conserva sus
validaciones posteriores de selección, argumentos, dependencias y permisos.

- Máximo **dos reintentos adicionales por inferencia fallida**: tres intentos
  totales. `ConfiguracionAgente.max_reintentos_llm` vale 2 por defecto y admite
  únicamente valores de 0 a 2. No cambia las iteraciones del plan.
- Se reintenta HTTP 429 de límite temporal o sin código/tipo de error específico;
  errores con códigos o tipos de cuota permanente u otros códigos no se reintentan.
  Tampoco se reintentan HTTP 400, autenticación, otros estados, fallos de
  transporte o interrupciones.
- Se prioriza `Retry-After` en segundos o fecha HTTP, después `retry-after-ms`;
  si faltan pistas válidas, se reconoce la duración de «Please try again in
  2.91s» del cuerpo. El texto del error solo se examina de forma acotada en RAM.
  [Groq documenta `Retry-After` en segundos](https://console.groq.com/docs/rate-limits).
- Sin indicación válida: espera de 1 s para el primer reintento y 2 s para el
  segundo. Máximo **10 s por espera y 20 s de espera acumulada por inferencia**.
  Una espera válida superior al tope no se recorta: se propaga el 429.
- Se comprueba el presupuesto restante del turno antes de esperar y al despertar.
  Si la espera no cabe o el plazo ya venció al despertar, se conserva el 429.
  Los timeouts HTTP existentes continúan vigentes.
- Los avisos solo contienen `HTTP 429`, número de reintento y segundos. No se
  registran cuerpos, cabeceras, credenciales ni argumentos. Al agotar reintentos,
  el último error conserva `HTTP_429`, respuesta de error y plan interrumpido
  persistido; las verificaciones anteriores siguen completadas.

El SDK conserva `max_retries=0` para evitar dos capas de reintentos. El evaluador
`eval/check_ep2_plan.py` desactiva explícitamente esta nueva política: mantiene
sus límites auditados y su detención global al primer 429. La CLI normal usa
la política habilitada por defecto; no necesita nuevos argumentos ni variables.

`registrar_nota_ticket` continúa preparando solo una vista previa y una solicitud
de confirmación humana. Recuperarse del 429 nunca llama a `confirmar_nota()`;
no hay escritura automática. RAG, memoria, prioridad registrada, modelo,
credenciales, proveedor, cuotas y las seis herramientas se conservan.

## Pruebas

Las regresiones usan reloj virtual y `httpx.MockTransport` con el cliente
`ChatOpenAI` real. Simulan el caso exacto tras las cuatro verificaciones: uno o
dos 429 de 2,91 s seguidos de éxito, y tres 429 consecutivos. Comparan las
peticiones repetidas, el plan completo y los resultados antes de cada intento.
Comprueban que cada lectura solo se ejecutó una vez, que el éxito solicita
confirmación y que el agotamiento bloquea la nota sin completarla. SQLite y
FAISS son locales de prueba; no se modifican los datos de la demostración.

También se prueban pistas ausentes, inválidas, fechas HTTP, milisegundos, esperas
excesivas, presupuesto agotado, interrupciones y errores no reintentables.
Las esperas son simuladas; no se duerme durante las pruebas de reintento.

Desde PowerShell, en la raíz del repositorio:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_ep2_reintentos.py tests/test_ep2_cierre.py tests/test_ep2_agente.py tests/test_check_ep2_plan.py
```

Las pruebas usan modelos falsos o transporte HTTP simulado. En esta validación
se añade además un audit hook que bloquea conexiones de sockets y comprueba
cero intentos de conexión.

Resultado final: **712 pruebas aprobadas en 39,04 s**, incluidas **38 nuevas**,
cero fallos, errores u omisiones. Salida 0; cero intentos de conexión. Informe
JUnit verificado: `.cache/ep2_reintentos_429_final_pytest.xml`, excluido de Git.
`git diff --check` aprobado. Credenciales, configuración de EP1, datos e índices
locales permanecen intactos; no se realizó commit ni push.

Persisten límites externos: el siguiente intento puede volver a recibir 429.
No se garantiza una grabación sin errores de cuota; se limita la recuperación y
se conserva el fallo visible cuando no es posible continuar.
