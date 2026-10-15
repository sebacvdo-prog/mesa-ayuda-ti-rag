# Evidencia — Continuidad real de memoria EP2 con Groq

Fecha: **15 de octubre de 2026**, horas expresadas en UTC. Modelo:
**`openai/gpt-oss-20b`**, con la misma clave y endpoint Groq existentes.
No se imprimieron credenciales ni se usaron dobles del modelo en las pruebas reales.

## Agente entre dos procesos independientes

Comando reproducible; consume cuota de Groq:

```powershell
.\.venv\Scripts\python.exe -m eval.check_ep2_memory
```

Se ejecutaron dos procesos Python secuenciales sobre la misma base EP2 temporal.
El primero terminó antes de iniciar el segundo; no compartieron objetos Python,
historial en RAM ni scratchpad. Usuario `memoria_integracion`, sesión
`continuidad_01`, perfil `agente`.

| Paso | PID real | Solicitud | Selección de Groq | Resultado |
|---|---:|---|---|---|
| Iniciar | 26440 | Consultar estado y prioridad de INC-2026-0411. | `consultar_ticket` → `analizar_incidente` | Escalado, P2, seguimiento Nivel 2; ticket activo y un intercambio persistidos. |
| Continuar | 30832 | «Retomemos el mismo ticket de esta sesión. Consulta su SLA según su prioridad y dime el identificador del ticket.» | `consultar_sla` | Identificó INC-2026-0411, consultó P2 y devolvió 30 minutos / 8 horas; dos intercambios persistidos. |

La segunda solicitud **no contenía el identificador del ticket**. Antes de llamar
al LLM, el segundo proceso recuperó el ticket y el intercambio inicial de SQLite.
El SLA correcto quedó registrado como hecho `sla:P2`, con fuente `itsm:sla:P2`;
la referencia del ticket conservó `itsm:ticket:INC-2026-0411`.

Finalización de la última corrida: **2026-10-15 05:17:16 UTC**. Verificador: salida **0**,
**11/11 comprobaciones aprobadas**: dos turnos reales exitosos, procesos distintos,
ticket inicial consultado, segunda solicitud sin identificador, recuperación antes
del LLM, selección autónoma de SLA, valores correctos, identificador en respuesta,
persistencia del segundo turno, cero notas/auditoría e ITSM intacto por SHA-256.
No se forzó `tool_choice` ni se ejecutó la herramienta por fuera del agente.

Versiones registradas: LangChain 0.3.30, Core 0.3.86 y
`langchain-openai` 0.3.35. Los resultados completos están en el artefacto local
`.cache/ep2_memoria_real.json`, excluido de Git. SHA-256 al registrar esta corrida:
`12a8d442dfe9d934ca9913ea0838e5dcb8f3578aaac76ebae2172740478d1406`.
El verificador elimina únicamente su directorio temporal comprobado bajo `.cache`;
conserva los intentos en el JSON. No cambia el ITSM ni la base EP2 de uso normal.

El artefacto conserva dos corridas aprobadas, a las 05:02:46 y 05:17:16 UTC.
En la primera, Groq seleccionó solo `consultar_ticket` en el turno inicial; en
la segunda añadió el triage. Ambas recuperaron el contexto y consultaron el SLA
correcto después de terminar el proceso inicial. La última verifica el código
final, incluida la corrección del orden de observaciones descrita más abajo.

## Cierre y reapertura reales de la CLI

Además se invocó la CLI en dos procesos separados, ambos con:

```powershell
.\.venv\Scripts\python.exe -m src.ep2.cli --usuario agente_demo_ep3 --sesion continuidad_ep3 --perfil agente
```

En la primera apertura se consultó INC-2026-0411 y se terminó con `/salir`.
En la segunda, con los mismos identificadores, se pidió retomar «el mismo ticket»
y consultar su SLA, sin repetir el identificador. Groq volvió a seleccionar
`consultar_sla`, identificó INC-2026-0411 y respondió 30 minutos / 8 horas.

Observaciones UTC persistidas en la base EP2 local:

- **05:04:39:** `consultar_ticket`, estado escalado, prioridad P2.
- **05:05:46:** `consultar_sla`, P2, primera respuesta 30 min, resolución 8 h.

Verificación posterior: ticket activo INC-2026-0411, dos intercambios, dos hechos
con fecha/procedencia, dos eventos y tarea en estado `ok`, sin pendientes.
Snapshot de la sesión: **1767 bytes UTF-8**. La base EP2 local mantiene
**cero notas y cero eventos de auditoría de negocio**; solo se añadieron las
tablas de memoria y esta sesión ficticia.

Logs locales excluidos de Git:

- `.cache/ep2_cli_memoria_1.txt`, SHA-256
  `bac67bcfeb39be98d107475f4190c282d64f65276267bf227c73716f16d4b6cc`.
- `.cache/ep2_cli_memoria_2.txt`, SHA-256
  `304f342d58db33b614f54c7300c5d10d85868f0d1304e5b0b07a5a5a9c864021`.

## Pruebas automatizadas y límites de la evidencia

Suite final: **257 passed in 29.44s** — las 214 pruebas anteriores y **43 nuevas**
de memoria. Usan LangChain real con modelos guionados y SQLite temporal; no
llaman a Groq. Cubren continuidad, reapertura de CLI, aislamiento de usuario,
sesión y perfil, hechos actualizados, contradicciones, observaciones tardías,
deduplicación, concurrencia, límites, caducidad, privacidad, confirmaciones y
recuperación ante errores. También verifican que ampliar el esquema preserve
las notas y la auditoría anteriores.

Una repetición intermedia detectó un empate de fechas UTC que permitía activar
un ticket observado antes al terminar tarde su respuesta. Se añadió un desempate
interno con `perf_counter_ns` para hechos y ticket activo. La prueba ahora fija
la misma fecha para ambas observaciones y verifica tanto el rechazo de la antigua
como la aceptación de una nueva. La suite completa y la integración real se
repitieron después de corregirlo; los resultados finales son los indicados arriba.

`python -m pip check`: **No broken requirements found**.
`git diff --check`: sin errores. Sin instalación ni actualización de dependencias.

Esta evidencia acredita continuidad en un caso de ticket/SLA con datos ficticios.
No acredita fidelidad universal, autenticación empresarial ni planificación
adaptativa. La prioridad usada en el seguimiento fue la observada previamente:
si cambia en el ITSM se necesita reconsultar el ticket, no asumir que la memoria
está actualizada. La memoria muestra fechas y procedencia y no sustituye la fuente.

No se hicieron escrituras de notas con Groq. Las confirmaciones, cancelaciones y
fallos de memoria posteriores a una escritura se comprobaron con bases temporales
automatizadas. No se recalibró FAISS ni se llamó nuevamente a Google.

**IE3:** los intercambios y hechos sobrevivieron al proceso, el agente resolvió
una referencia de seguimiento desde SQLite y conservó el contexto de tarea. Los
controles de aislamiento y autorización se comprobaron por pruebas específicas.
Memoria y límites: [documentación de Etapa 3](../ep2_etapa3.md).
