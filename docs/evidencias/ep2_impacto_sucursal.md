# EP2: replanificación tras un reporte de impacto en la sucursal

Fecha: 30 de octubre de 2026. Reproducción con SQLite temporal, FAISS real con
vectores explícitos y modelo guionado. Sin llamadas a Groq.

## Causa concreta

`multiples_usuarios()` exigía prácticamente la secuencia «varios usuarios
afectados». No admitía los modificadores de ubicación en «varios usuarios de la
misma sucursal están afectados por la VPN», ni la construcción «la falla de VPN
afecta a varios usuarios de la misma sucursal».

Al devolver falso, `Planificador.__init__()` no llamaba a
`_replantear_impacto()`. Si la solicitud incluía «ahora», recuperaba el plan
completado y solo registraba `PLAN_RECUPERADO`; `disponibles()` quedaba vacío.
La oferta `plan_completado` permitía entonces una respuesta final sin nuevas
herramientas. Sin una palabra de continuidad, podía incluso crearse otro plan
flexible en vez de adaptar el recuperado.

El problema no era una pérdida del plan en SQLite: las transiciones de
replanificación ya reabrían las dependencias y añadían el análisis cuando el
detector reconocía el reporte. Las pruebas anteriores utilizaban principalmente
«ahora hay varios usuarios afectados», que sí coincidía con el patrón original.

## Corrección

El detector reconoce la relación entre cantidad plural, usuarios y afectación
dentro de una oración, con modificadores intermedios y formas explícitas como
«reportan la misma falla» o «afecta a varios usuarios». Mantiene una búsqueda
acotada y excluye negaciones, supuestos explícitos y cantidades inferiores a dos.
La cantidad solo distingue pluralidad; no es un umbral de prioridad o escalamiento.

El reporte activa las transiciones existentes del servidor:

1. Recuperar el mismo ID de plan y aumentar su revisión.
2. Registrar el impacto como reportado, todavía sin verificación independiente.
3. Reabrir ticket y SLA; añadir o reabrir `analizar_incidente`, con dependencia
   del ticket y SLA; revalidar los procedimientos previstos que dependían de ellos.
4. Mantener las prioridades de ejecución y las dependencias hasta obtener
   resultados reales. Un `AgentFinish` prematuro sigue rechazado con
   `PLAN_INCOMPLETO`, dentro del presupuesto del único ejecutor.
5. Persistir los estados efectivamente obtenidos. Las afirmaciones del LLM no
   crean pasos ni los completan.

El cierre de una reevaluación de impacto sin escritura se compone con las trazas,
la prioridad registrada y los estados del plan del servidor. No reproduce el
texto libre del LLM que podría inventar un p4 hipotético o umbrales de cinco
usuarios o porcentajes. Remite los criterios de escalamiento al SLA y a la
documentación recuperados; no define reglas nuevas.

La prioridad registrada solo se actualiza con lecturas de las fuentes existentes.
El reporte del usuario no la modifica y no escribe en el ITSM. La regla existente
de propuesta basada en el SLA no se alteró. Las propuestas de notas continúan
sujetas a solicitud actual, dependencias y confirmación humana.

## Regresiones

- Variantes de ubicación, verbo anterior, número de afectados y reporte de falla.
- Negaciones, hipótesis y frases en oraciones distintas que no acreditan impacto plural.
- Plan inicialmente completado con ticket, SLA y procedimiento KB-RED-02.
- Continuación en la misma instancia y recuperación con una nueva instancia de
  agente, almacenamiento y memoria sobre la misma SQLite temporal.
- Revalidación de ticket, SLA, análisis y procedimiento mediante las herramientas
  reales; p4 persistido y todos los pasos completados con un intento real por paso.
- Rechazo de una respuesta prematura y cierre seguro incluso cuando el modelo
  guionado insiste en el texto de los umbrales inventados.
- Misma prioridad registrada P2, bytes del ITSM intactos y cero notas o auditoría
  de escrituras; ninguna nota añadida sin solicitud.
- Conservación de `tool_choice="auto"`, seis herramientas, resolución exacta KB,
  permisos, memoria persistente y controles de confirmación.

Para ejecutar las pruebas de planificación desde PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_ep2_planificacion.py
```

El informe completo de esta revisión queda ignorado por Git en
`.cache/ep2_impacto_plan_pytest.xml`.

Resultado: **642 pruebas aprobadas**, incluidas **21 regresiones nuevas**, sin
fallos, errores ni omisiones. `NETWORK_ATTEMPTS_BLOCKED: 0` y `git diff --check`
aprobado. Se verificaron sin cambios 20 archivos protegidos, incluidos índice,
caché, almacenamiento existente y las correcciones previas de recuperación.
