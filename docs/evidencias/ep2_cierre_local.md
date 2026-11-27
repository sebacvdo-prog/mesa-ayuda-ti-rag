# EP2: cierre de planes verificados sin otra llamada a Groq

Fecha: 30 de octubre de 2026. Pruebas locales con proveedor y HTTP simulados.

## Causa

Después de ejecutar la última herramienta de lectura, `AgentExecutor` vuelve a
consultar al agente para obtener un `AgentFinish`. `_ModeloPlanificado` enviaba
otra petición a Groq, aunque el servidor ya tuviera todos los pasos completados.
Esa petición podía recibir HTTP 429 y convertir la respuesta del turno en error
después de cuatro herramientas correctas. En la reevaluación de impacto, el texto
final ya se componía determinísticamente, pero después de la petición adicional.

El 429 sigue siendo un error del proveedor: la corrección elimina una solicitud
innecesaria, sin cambiar cuota, credenciales, proveedor, modelo o reintentos.

## Condiciones del cierre

`AgenteEP2._cerrar_plan_verificado()` solo permite cerrar si:

- El plan es estructurado, no es una lectura de estado y tiene pasos activos.
- Todos los pasos no cancelados están completados según el plan del servidor.
- Existen resultados reales del turno y todos son `ok`, con procedencia.

El adaptador consulta esa condición antes de proyectar el contexto, enlazar
esquemas o invocar al modelo. El marcador `AIMessage` que recibe el parser es
local: no representa una respuesta de Groq. La traza final usa
`RESPUESTA_FINAL`, `estado_oferta="plan_completado"`, `tool_choice="none"` y
`modelo_respondio=false`; no se inventan solicitudes ni consumo de tokens.

Si la última herramienta consume la última iteración, el mismo cierre se evalúa
tras la salida del ejecutor. Solo se acepta el plan ya completado y verificado;
un límite con pasos pendientes sigue devolviendo `limite`. No se ejecutan pasos
adicionales fuera del presupuesto.

La respuesta presenta valores comprobados del ticket, SLA, activo o triage, las
notas consultadas, los fragmentos RAG como evidencia literal y el estado real del
plan, con sus fuentes. No sintetiza umbrales ni cambia la prioridad registrada.
La memoria conserva el resultado y el plan a través de su ruta habitual.

## Controles conservados

El LLM sigue eligiendo cada herramienta habilitada y sus argumentos, con una
sola selección por decisión. La oferta, los permisos, las prioridades de
ejecución y las dependencias no se modificaron.

No se cierra como éxito ante errores, denegaciones, falta de contexto, pasos
bloqueados o confirmaciones pendientes. La propuesta de nota sigue deteniendo el
ciclo con `requiere_confirmacion`; solo la interfaz humana puede escribirla.
Un 429 durante la selección de herramientas sigue devolviendo error.

El modo flexible permite al modelo elegir lecturas independientes adicionales,
por lo que conserva su decisión final. `solo_estado` también conserva su ruta.
Los ensayos históricos del evaluador no activan el cierre de producción y
mantienen sus parámetros diagnósticos originales.

## Ahorro y pruebas

Para un plan de cuatro herramientas correctas: **5 solicitudes pasan a 4**,
un 20 % menos de solicitudes en ese caso. Para tres herramientas, pasan de 4 a 3.
Se evitan todo el prompt final y la generación final del proveedor; las
decisiones intermedias siguen usando la proyección acotada y solo los esquemas
permitidos. No se cuantifica ahorro real de tokens o facturación sin otra prueba
real, que no se realizó.

La prueba integral de CLI y transporte simulado pasa de 10 a 9 solicitudes y
mantiene sus 15 verificaciones. Su usage ficticio pasa de 120 a 108 tokens; esos
números son datos del doble HTTP, no consumo real de Groq. El cierre local es una
decisión de la traza, pero no una solicitud HTTP ni una respuesta del modelo.

Las regresiones incluyen un transporte HTTP que devolvería 429 a partir de la
quinta petición, replanificación con cuatro herramientas, límite exacto de
iteraciones, planes incompletos, errores de herramientas y de proveedor,
confirmación humana, modo flexible y reinicio del estado del cierre entre turnos.
Las pruebas de contexto y de instrumentación distinguen ahora proyecciones
enviadas al proveedor de vistas locales; no se debilitaron los controles previos.

Desde PowerShell, en la raíz del repositorio:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_ep2_cierre.py
```

El informe completo de esta revisión se genera en
`.cache/ep2_cierre_local_pytest.xml`, excluido de Git.

Resultado: **652 pruebas aprobadas**, incluidas **10 regresiones nuevas**, sin
fallos, errores ni omisiones. Red bloqueada: `NETWORK_ATTEMPTS_BLOCKED: 0`.
`git diff --check` también aprobado; no se realizaron llamadas reales a Groq.
