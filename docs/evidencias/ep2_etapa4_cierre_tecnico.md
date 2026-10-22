# EP2 — Cierre técnico de Etapa 4: evidencia sanitizada

**Resultado: 15/15 verificaciones reales aprobadas en una misma ejecución.**
Fecha: **22 de octubre de 2026**. Etapa 5 y entrega académica final permanecen fuera de alcance.

## Cómo interpretar esta evidencia

| Tipo de validación | Resultado | Qué acredita |
|---|---|---|
| Pruebas automatizadas | 584 aprobadas, con red bloqueada y cero intentos de red | Regresiones locales con modelos/HTTP simulados y SQLite temporal; no equivalen a llamadas reales a Groq. |
| Ensayos aislados reales | Cuatro controles de una sola decisión, detallados abajo | Compatibilidad de variantes de contexto, sin ejecutar herramientas ni escrituras; no son una integral. |
| Evaluación integral real | 15/15 en una ejecución; 10 solicitudes HTTP 200 | Ciclo real de CLI, Groq y FAISS en tres procesos, memoria/plan compartidos y confirmación pospuesta. |

El ITSM del proyecto contiene datos simulados y se consulta sin modificarlo. La
SQLite EP2 de esta evaluación fue temporal; no se incluye ninguna base de datos.
La entrada de interfaz se guionó con `POSPONER`, sin invocar la API de confirmación.

## Procedencia y ejecución real

- Inicio UTC: `2026-10-22T04:13:41.635545+00:00`.
- Inicio America/Santiago: `2026-10-22T01:13:41.635545-03:00`.
- Comando autorizado: `python -m eval.check_ep2_plan`, con el intérprete del entorno virtual del repositorio.
- Modelo: `openai/gpt-oss-20b`; agente real con proyección por decisión y un solo `AgentExecutor`.
- Fuente local: `.cache/ep2_plan_controlado.json`, último intento. El archivo original permanece ignorado; se conservan sus intentos previos.
- Los resultados siguientes pertenecen exclusivamente a ese intento completo; no se suman éxitos parciales de otras ejecuciones.
- SHA-256 del reporte local al extraer: `3e9ab7a9062befcc256c09929092239181e25bac28b8c689f2b9fa5eee43a2fc`.
- SHA-256 del intento seleccionado (JSON canónico: claves ordenadas, UTF-8, separadores compactos): `5c1c6dd1a1e7b9b49f01545096c45b4ec8b2849f9cdfc7cfd1ce28563333f2c2`.

## Fases y consumo informado por Groq

| Fase | Estado | Solicitudes | Entrada | Salida | Total tokens | Duración de fase (s) |
|---|---|---:|---:|---:|---:|---:|
| inicial | ok | 4 | 4672 | 1040 | 5712 | 125.906 |
| impacto | requiere_confirmacion | 5 | 7754 | 2017 | 9771 | 160.063 |
| reanudar | ok | 1 | 1865 | 789 | 2654 | 19.578 |
| **Total** | **Aprobado** | **10** | **14291** | **3846** | **18137** | — |

Las diez solicitudes devolvieron HTTP 200; no hubo HTTP 400, HTTP 429 ni motivo de
detención. Todas informaron uso: **cero solicitudes con estimación**. El total
operativo fue 18.137 y coincidió con el informado. Las reservas previas no se suman
como consumo real ni acreditan facturación o saldo de cuenta.
Los tiempos de fase incluyen inicio de proceso y esperas; las dos pausas entre
fases no están incluidas en esas duraciones.

## Las quince verificaciones del mismo intento

| Verificación del evaluador | Interpretación | Resultado |
|---|---|---|
| `tres_procesos_distintos` | Tres procesos CLI distintos | Aprobada |
| `consulta_ticket_sla_faiss` | Ticket, SLA y procedimiento consultados realmente | Aprobada |
| `caso_inicial_ok` | Caso inicial correcto y pasos completados | Aprobada |
| `mismo_plan_tras_reportar` | Mismo plan después del nuevo reporte de impacto | Aprobada |
| `revision_avanza` | Revisión del plan incrementada | Aprobada |
| `impacto_reportado_no_verificado` | Impacto reportado separado de hechos verificados | Aprobada |
| `registrada_y_propuesta_p2` | Prioridad registrada y propuesta P2 diferenciadas | Aprobada |
| `reevaluacion_real` | Reconsulta real de ticket, SLA y análisis de incidente | Aprobada |
| `nota_pendiente_sin_autorizar` | Una propuesta pendiente de confirmación humana | Aprobada |
| `reapertura_recupera_plan` | Plan recuperado correctamente al reabrir | Aprobada |
| `reapertura_conserva_pendiente` | Paso de nota conservado bloqueado/pendiente | Aprobada |
| `sin_nueva_propuesta_al_reanudar` | Reanudación sin nuevas herramientas ni propuestas | Aprobada |
| `sin_escrituras_de_negocio` | Cero notas y auditorías de escritura en las tres fases | Aprobada |
| `itsm_intacto` | ITSM original sin modificaciones | Aprobada |
| `memoria_guardada` | Memoria actualizada en las tres fases | Aprobada |

## Secuencia y garantías observadas

- Inicial: `consultar_ticket` → `consultar_sla` → `buscar_procedimiento` → respuesta sin herramientas.
- Impacto: `consultar_ticket` → `consultar_sla` → `analizar_incidente` → `buscar_procedimiento` → `registrar_nota_ticket` (solo propuesta).
- Reanudar: respuesta en modo `solo_estado`, sin herramientas ni nueva propuesta.
- Dos mensajes por decisión; las huellas de fuentes corresponden al nuevo compositor y a su integración real.
- Las selecciones ejecutadas pertenecen a la oferta habilitada y respetan prioridad y dependencias. Cero decisiones rechazadas.
- Las tres fases actualizaron la memoria; se conservó el mismo plan y avanzaron sus revisiones. El impacto siguió reportado/no verificado.
- Una propuesta pendiente en impacto y ninguna nueva confirmación al reanudar. Cero notas y cero auditorías de escritura en las tres fases.
- Se mantuvo el ITSM original intacto. La comprobación posterior también preservó código, almacenamiento original y reportes históricos.

## Límites aplicados

| Control | Valor |
|---|---|
| Solicitudes globales máximas | 14 |
| Presupuesto operativo global | 80000 tokens |
| Salida máxima por respuesta | 2000 tokens |
| Iteraciones por fase | 8 |
| Tiempo por fase / proceso | 300 s / 360 s |
| Timeout HTTP | 30 s |
| Intervalo entre llamadas / pausa entre fases | 35 s / 60 s |
| Reintentos SDK, transporte y evaluación completa | 0 |

La detención ante errores HTTP y agotamiento de límites sigue activa. La ejecución
aprobada no alcanzó esos límites y no se repitió para obtener el resultado.

## Ensayos aislados previos, separados del cierre integral

| Contexto y selección | HTTP | Llamada válida | Tokens informados |
|---|---:|---|---:|
| Completo + required | 400 | No validada | No informados |
| Completo + selección explícita | 400 | No validada | No informados |
| Mínimo + selección explícita | 200 | Sí | 404 |
| Mínimo + plan + selección explícita | 200 | Sí | 708 |

Los rechazos de contexto completo se clasificaron como `HERRAMIENTA_NO_OFRECIDA`.
Los controles exitosos acreditaron una llamada válida, sin ejecutarla. No se
presentan como un reemplazo de las quince verificaciones integrales.

## IE3, IE5 y alcance del cierre

- **IE3:** continuidad y recuperación real entre procesos con hechos fechados/procedencia y estado persistente; el aislamiento entre usuarios, sesiones y perfiles se acredita mediante las pruebas automatizadas, no mediante esta sesión real única.
- **IE5:** identidad/revisiones, prioridades, dependencias y adaptación del mismo plan según resultados reales; propuesta pendiente y recuperación sin autorizaciones restauradas.
- **HTTP 400:** no se reprodujo después de incorporar la proyección por paso en esta ejecución. Su causa histórica no quedó demostrada. Un resultado exitoso no garantiza todas las entradas ni disponibilidad futura del proveedor.
- **Cierre:** aceptación técnica de Etapa 4 cumplida con 15/15 en un intento completo. La entrega final de Etapa 5 no forma parte de esta evidencia.

## Huellas de las fuentes ejecutadas

Estas huellas identifican los bytes locales evaluados y fueron contrastadas antes
de formalizar el cierre. No son hashes de credenciales ni de datos de negocio.

| Fuente | SHA-256 |
|---|---|
| `src/ep2/agente.py` | `3598b580fc28dc108405d49235b61e2ee55b31b35c8ee0fc79b9a78a5d68d0b3` |
| `src/ep2/contexto.py` | `f6e77cc2d2af1e55db4bfbc137b4ba02c8715e0b13e3b6e66520a61a95cf1d10` |
| `src/ep2/planificacion.py` | `fe860f0cf0e374a891b735a8fa8fb60f298c6f399658cbd6302c7f5a61926796` |
| `src/ep2/memoria.py` | `dce4cff775eca7f4bd35ad5f4ab047d2bd0413d0fd06fa9e4f15547b16eb4897` |
| `src/ep2/contratos.py` | `943ecdaf3107539102936d29b9b05bce635fa6b6476b5a3b673b8b45deeb5f64` |
| `src/ep2/cli.py` | `3510136ac3d9c72b3f0a2217091dda5d20247885be3bfc4387b54d7004f6132e` |
| `src/ep2/herramientas.py` | `f4a4305397ef29cb37cc2cd8fb29a395c03270c4149cbbb0dc1e50b517535709` |
| `eval/check_ep2_plan.py` | `d89246b35fae35bb38edef832e1f3136cb460a893fb31b0982a4df09f47b7b27` |

## Sanitización y conservación de históricos

Este archivo deriva métricas y estados mediante una lista explícita de campos.
No copia prompts, argumentos, respuestas libres, razonamientos, cuerpos/cabeceras
HTTP, claves, identificadores de usuario/sesión/ticket/plan, tokens de confirmación
ni textos de notas o documentos. No se versionan cachés, archivos privados ni SQLite.
Los intentos parciales anteriores se conservan en [el registro histórico](ep2_plan_real.md).
El diseño y las limitaciones están en [la documentación de Etapa 4](../ep2_etapa4.md).

## Revalidación local para el commit de cierre

El 22 de octubre de 2026 se repitió la suite completa con sockets, DNS y envíos
bloqueados desde el arranque, también en subprocesos: **584 pruebas aprobadas en
31,13 s y cero intentos de red**. `pip check` no encontró dependencias rotas y
`git diff --check` pasó. No se ejecutaron nuevas llamadas reales durante esta
formalización ni se modificó la lógica evaluada del agente o del planificador.
