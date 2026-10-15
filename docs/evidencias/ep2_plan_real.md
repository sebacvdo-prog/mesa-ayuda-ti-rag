# Evidencia real — Etapa 4: plan adaptativo

Fecha de ejecución: **15 de octubre de 2026**. Base estable:
`8affe89f2b996dad326a8eba9dd531552c2dd431`, rama `master`, árbol inicialmente limpio.
Esta evidencia corresponde a desarrollo y comprobación técnica de Etapa 4;
no sustituye la demostración final ni el informe académico de Etapa 5.

**Estado: implementación con 308 pruebas automáticas aprobadas; validación real
integral pendiente. No hay ninguna corrida completa 15/15.** Se detuvieron las
llamadas al alcanzar la cuota diaria de Groq; no se consideran aprobados los
intentos parciales ni se combinan fases de distintas versiones para afirmar éxito.

## Método reproducible

```powershell
python -m pytest -q
python -m pip check
python -m eval.check_ep2_plan
```

El verificador inicia tres procesos distintos de `src.ep2.cli`: consulta inicial,
reporte de nuevo impacto y reapertura. Utiliza el agente y las seis herramientas
reales, Groq `openai/gpt-oss-20b`, el ITSM en solo lectura y FAISS existente con
Hugging Face. Solo adapta la entrada humana guionada y la ubicación SQLite EP2
a un directorio temporal; no sustituye respuestas del modelo ni del recuperador.
En el campo de confirmación responde `POSPONER`, nunca `CONFIRMAR`.

Versiones comprobadas: LangChain 0.3.30, langchain-core 0.3.86 y
langchain-openai 0.3.35. No se instalaron ni actualizaron dependencias.
Hugging Face conserva 384 dimensiones y umbral 0.471764; Google conserva su
alternativa y 0.72. No se recalibró ni reconstruyó el índice.

Para reducir los HTTP 429 observados, la prueba manual espacia las llamadas LLM
35 s y los procesos 60 s, con presupuesto de 300 s por fase. Usa el limitador
nativo ya instalado. Estos valores **no cambian** los predeterminados del agente:
8 iteraciones, 90 s por ciclo y 30 s por petición. La demostración con cuota
limitada no acredita que el recorrido completo quepa siempre en 90 s.

La evidencia completa local se guarda en `.cache/ep2_plan_real.json`, excluida
de Git. Contiene consultas, trazas CLI, observaciones, planes antes/después,
PID, versiones, verificaciones y hashes del código al terminar las corridas más recientes.
No guarda claves ni tokens de autorización. Cada prueba usa SQLite temporal;
no modifica las notas del almacenamiento habitual de EP2.

## Ticket y criterio de impacto

Se verificó INC-2026-0411: CAT-RED, «Advertencia de certificado al conectar la
VPN», escalado a Nivel 2, prioridad registrada **P2**. SLA P2: primera respuesta
30 minutos y resolución 8 horas; su descripción contempla grupos de usuarios
sin servicio. Procedencia: `itsm:ticket:INC-2026-0411`, `itsm:sla:P2`.

«Ahora hay varios usuarios afectados» es un reporte del usuario, conservado
como `usuario:reporte_no_verificado`. No prueba una caída real. El controlador
revalida fuentes y propone P2 únicamente tras consultar el SLA; el número de
afectados, por sí solo, no acredita P1. La prioridad registrada permanece P2.
El triage propone seguimiento Nivel 2; no ejecuta escalamiento en otro sistema.

## Intentos y hallazgos

Se conservan los fallos; no se presentan ejecuciones parciales como éxito.
Los horarios siguientes son UTC, obtenidos del registro al finalizar cada intento.

| Intento | Hora UTC | Inicial / impacto / reapertura | Verificaciones | Hallazgo |
|---|---|---|---|---|
| 1 | 14:43:50 | ok / error / error | 11/15 | HTTP 429 después de la consulta inicial. |
| 2 | 14:48:56 | error / error / error | 9/15 | Consulta específica sin procedimiento admisible y HTTP 429. |
| 3 | 14:54:50 | ok / error / ok | 12/15 | Reevaluación interrumpida por HTTP 429; plan recuperado. |
| 4 | 15:12:01 | ok / límite / ok | 14/15 | Rechazos de notas prematuras y presupuesto agotado con ritmo de 45 s. |
| 5 | 15:24:57 | ok / límite / ok | 14/15 | Decisiones inválidas consumieron las ocho iteraciones; ninguna escritura. |
| 6 | 15:33:50 | ok / límite / ok | 13/15 | Reiteración de nota prematura; no completó triage. |
| 7 | 15:40:09 | ok / error / ok | 12/15 | HTTP 400 en la primera llamada de impacto con esquemas restringidos. |
| 8 | 15:45:46 | ok / error / ok | 12/15 | HTTP 400 persistió indicando el nombre de la herramienta única. |
| 9 | 15:52:59 | ok / error / ok | 12/15 | La instrucción final no resolvió el rechazo nativo con selección forzada. |
| 10 | 16:02:00 | ok / error / ok | 12/15 | Registro completo con función forzada: HTTP 400; se descartó esa combinación. |
| 11 | 16:07:53 | ok / error / error | 11/15 | Última versión probada con Groq: ticket/SLA/FAISS iniciales; impacto y respuesta de reapertura interrumpidos por cuota diaria HTTP 429. |

El intento 1 también permitió detectar una respuesta con instrucciones de
certificados no respaldadas por el procedimiento aplicable. Se reforzó el prompt
EP2 con la política existente: advertencias de certificado requieren Nivel 2;
no inventar renovación/instalación ni aceptar advertencias. Recuperar el archivo
correcto en FAISS **no acredita**, por sí solo, fidelidad de toda la respuesta.
No se afirma una evaluación exhaustiva de calidad semántica.

Los intentos 4–5 mostraron dos problemas de integración corregidos: el
formateador original de LangChain 0.3 omite la observación de `_Exception`, y la
lista ofrecida al modelo incluía pasos de menor prioridad que luego se rechazaban.
El adaptador transmite solo la última corrección segura del servidor; la lista
actual contiene únicamente pasos ejecutables de mayor prioridad. Ambos cambios
se verifican automáticamente, conservando el mismo `AgentExecutor` y presupuesto.

El intento 6 siguió agotando iteraciones con una elección prematura de nota.
Se ensayó restringir los **esquemas** ofrecidos por `bind_tools` al conjunto
ejecutable y utilizar `tool_choice` por nombre / `required`. Los intentos siguientes
mostraron rechazos HTTP 400; esas variantes se descartaron. Las pruebas de la
implementación actual comprueban el registro fijo, las directivas dinámicas y
la elección entre dos herramientas habilitadas de igual prioridad. Sin acciones
disponibles se permite responder sin herramientas. No hay llamadas directas
que sustituyan la selección del modelo ni otro ciclo de ejecución.

Los intentos 7–8 recibieron HTTP 400. Un diagnóstico controlado posterior,
restaurando el plan real anterior en SQLite temporal, capturó únicamente
`tool_use_failed` / `invalid_request_error` y la categoría «herramienta no
permitida»; no imprimió ni persistió `failed_generation`. Se añadió una
instrucción final del servidor con el conjunto habilitado y el ticket actual.
El mensaje sanitizado confirmó: intento de llamar `analizar_incidente` no
incluido en `request.tools`. Los intentos 9–10 tampoco completaron la selección
forzada. La implementación final conserva los seis esquemas y la selección
nativa automática de Etapa 2, comunica los pasos habilitados al final del prompt
y aplica las restricciones en el servidor. No se desactiva la validación del
proveedor ni se introduce otro ejecutor. Los rechazos pueden volver al modelo
como observaciones controladas, dentro del mismo presupuesto.

## Plan antes y después — última corrida real, intento 11

Plan `be377d56-7bd5-4915-b4e6-3af0fc8ba4ab`. Procesos: 21628 (inicial), 24024
(impacto), 13820 (reapertura). Revisión 8 antes del reporte, 12 al adaptar el
plan, 16 tras la interrupción y 19 después de recuperar/persistir en el tercer
proceso. Los PID y snapshots proceden de la ejecución real.

| Paso | Antes: revisión 8 | Después del reporte: revisión 12 | Final de impacto: revisión 16 |
|---|---|---|---|
| p1 `consultar_ticket` | Completado, prioridad de paso 2 | Pendiente, prioridad 1 | Completado con consulta real nueva |
| p2 `consultar_sla` | Completado, prioridad 2; depende p1 | Pendiente, prioridad 1; depende p1 | Bloqueado por interrupción del proveedor |
| p3 `buscar_procedimiento` | Completado, prioridad 2; depende p1,p2 | Pendiente, prioridad 2; depende p1,p2 | Bloqueado por interrupción |
| p5 `analizar_incidente` | No existía | Nuevo, prioridad 1; depende p1,p2 | Bloqueado; no ejecutado realmente |
| p4 `registrar_nota_ticket` | No existía | Nuevo, prioridad 3; depende p1,p2,p3,p5 | Bloqueado; sin vista previa ni autorización |

Fechas UTC y procedencia verificables:

- 16:02:33: ticket inicial, `itsm:ticket:INC-2026-0411`.
- 16:03:07: SLA inicial, `itsm:sla:P2`.
- 16:03:50: FAISS, `corpus:politica_seguridad_ti.md` y
  `corpus:kb_conectividad_vpn.md`.
- 16:05:32: reporte nuevo, `usuario:reporte_no_verificado`; no confirma impacto.
- 16:05:34: selección prematura de análisis rechazada como
  `PLAN_DEPENDENCIA_PENDIENTE`; **no ejecutó el triage**.
- 16:06:08: el modelo rectificó y reconsultó realmente el ticket, P2 y Nivel 2.
- La siguiente llamada y la respuesta de reapertura recibieron HTTP 429.

La prioridad registrada permaneció **P2**. En esta última corrida la propuesta
quedó vacía, porque no se alcanzó el nuevo SLA: no se inventó una prioridad.
Los tres snapshots se guardaron; el tercero recuperó el mismo identificador y
los pendientes antes de llamar al LLM. La CLI mostró ese plan, pero no obtuvo
una respuesta de continuación del proveedor. Hubo **0 notas, 0 auditorías de
escritura y 0 solicitudes de confirmación** en las tres fases.

## Evidencia adicional parcial — versión intermedia, intento 4

Este intento **no valida la versión final** y no se presenta como demostración
completa. Conserva evidencia real de reevaluación: plan
`8c922191-5a81-48c8-953e-cfba0507bbd0`, revisión 8 → 12 → 24 → 26,
procesos 10824 → 18648 → 23428. Ticket/SLA/FAISS se completaron inicialmente;
tras el reporte se ejecutaron ticket, SLA y análisis reales. La prioridad
registrada fue P2 y la propuesta fue P2, sujeta a verificar el reporte y respaldada
por el SLA consultado a las 15:07:04 UTC. El análisis de las 15:08:34 recomendó
seguimiento Nivel 2. El presupuesto se agotó antes del procedimiento revalidado
y la nota; ambos quedaron bloqueados. Otro proceso recuperó ese plan y respondió
desde memoria sin herramientas ni escrituras. Resultado **14/15**, no aprobado.

## Bloqueo externo y comprobación pendiente

Un diagnóstico posterior capturó `rate_limit_exceeded` por **tokens por día
(TPD)**: límite 200.000, usados 198.544, petición de 2.474 tokens rechazada,
`retry-after: 440` segundos. La organización se omitió. Las cabeceras también
indican 8.000 tokens/minuto; el rechazo diagnosticado correspondía a la cuota
**diaria**, no a una incompatibilidad de dependencias. No se muestran claves
ni generación interna del modelo. El diagnóstico restauró el plan real previo
en SQLite temporal y no cuenta como una corrida integral.

Ese tiempo de reintento corresponde a una petición, no garantiza cuota suficiente
para todas las llamadas del caso. Se detuvieron las solicitudes; no se cambió
de modelo, cuenta o plan de pago y no se implementaron reintentos ilimitados.
Queda pendiente ejecutar de nuevo `python -m eval.check_ep2_plan` cuando exista
presupuesto suficiente, obtener 15/15 y revisar el contenido de la nota propuesta.
No se cierra la validación real de Etapa 4 ni se inicia Etapa 5.

## Validación automática y controles

- **308 pruebas aprobadas en 17.63 s**: las 257 existentes y 51 casos nuevos
  de planificación. Incluyen recuperación sin hechos tras error del proveedor
  y atribución al sistema de un timeout previo a ejecutar una herramienta.
- `python -m pip check`: **No broken requirements found.**
- `git diff --check`: sin errores de espacios; Git informa la conversión LF/CRLF
  habitual del entorno Windows, sin normalizar archivos por este motivo.
- Hashes verificados sin cambios para `.env`, ITSM original, ambos archivos FAISS
  y base EP2 habitual. `.env`, bases, índices y `.cache` siguen excluidos de Git.
- Durante la implementación, sin commits ni push; el respaldo local fue
  autorizado posteriormente. Sin cambios en dependencias ni implementación de Etapa 5.

Tras detener las llamadas se añadieron dos correcciones comprobadas sin API:
reanudar una propuesta bloqueada por fallo del proveedor conservando sus
dependencias, e invalidar la vista previa anterior desde la solicitud de una
nueva nota aunque el LLM falle. Estos cambios están en `agente.py` y
`planificacion.py`; las huellas de la corrida 11 corresponden al estado anterior
a ellos. No se afirma que estas dos correcciones se hayan probado con Groq real.

Una ejecución de cierre produjo `BrokenBarrierError` en la prueba existente
`test_inicializaciones_concurrentes_no_pierden_el_esquema` al esperar su barrera
de 5 s: 307 aprobadas / 1 fallida. La prueba aislada pasó en 0.28 s y la
repetición completa dio 308/308. No se modificaron esa prueba ni el módulo de
almacenamiento de Etapa 1. Se registra como fallo temporal no reproducido en
esas repeticiones, sin ocultarlo ni afirmar que se haya corregido su causa.

IE5 se respalda con planes tipados, dependencias y prioridades exigidas en el
servidor, transiciones por resultados reales y recuperación persistente. IE7 se
respalda parcialmente con el contraste del mismo plan ante el reporte, la decisión
condicional P2 de la versión intermedia y los rechazos verificables. Falta la
demostración real integral de la versión final hasta nota pendiente y respuesta
tras reiniciar. Las pruebas automáticas sí verifican propuesta, confirmación
humana nueva, cancelación, aislamiento y prevención de escrituras sin autorización.

Documento preparado con ayuda de IA. Las conclusiones, justificaciones técnicas
académicas y reflexiones personales deben ser redactadas por los estudiantes.

## Revisión para respaldo local — 15 de octubre de 2026

Se revisaron los 12 archivos de Etapa 4 y las exclusiones de secretos, SQLite,
FAISS y cachés. No se realizaron llamadas a Groq ni cambios de funcionalidades.
La suite local reprodujo el timeout de barrera de la prueba de concurrencia
existente (307 aprobadas / 1 fallida); la prueba aislada volvió a pasar en
0.28 s y la repetición completa aprobó **308 pruebas en 20.68 s**. No se modificó
código ni pruebas para obtener ese resultado.

Se conserva el estado de validación real: **11/15 verificaciones, integral
pendiente por cuota diaria de Groq**. El respaldo autorizado es exclusivamente
local, con mensaje `feat(ep2): implementar planificación adaptativa etapa 4`;
no se autoriza push ni iniciar Etapa 5.
