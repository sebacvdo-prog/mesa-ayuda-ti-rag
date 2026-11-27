# EP2: preparación de nota después de completar la reevaluación de impacto

Fecha: 30 de octubre de 2026. Regresiones sin Groq, con modelo guionado, FAISS
real con vectores explícitos y SQLite temporal.

## Causa reproducida

`_previstas()` reconocía «propón», «registra», «escribe» y otras formas, pero no
«prepara», «preparar» ni «redacta». Por tanto, una petición como «Prepara una nota
sobre varios usuarios afectados por VPN, sin registrarla todavía» dejaba
`permite_nota=False` y no creaba el paso `registrar_nota_ticket`.

El texto sobre varios afectados sí activaba la revalidación de impacto. Al
terminar ticket, SLA, análisis y procedimiento, el plan existente estaba completo
y el cierre determinista devolvía `ok`. No saltaba un paso pendiente: el paso de
preparación nunca había sido incluido por la detección de intención.

## Corrección delimitada

`_solicita_preparar_nota()` reconoce las formas explícitas de preparar, proponer
y redactar una nota. Distingue «prepara una nota sin registrarla» de negaciones
como «no prepares una nota» o «no quiero preparar una nota». No interpreta ninguna
de estas peticiones como confirmación de una escritura.

El planificador conserva las transiciones existentes: incorpora la preparación
con dependencias de las verificaciones previas. Al revalidar impacto, la nota
espera ticket, SLA, análisis y procedimiento. Después de completarlos, el LLM
recibe habilitada `registrar_nota_ticket` y debe seleccionarla antes de terminar.

El cierre determinista no se modificó: mientras la preparación está pendiente,
el plan no está completo y no puede cerrarse como éxito. La herramienta de nota
solo genera una vista previa y una `SolicitudConfirmacion`; devuelve
`requiere_confirmacion` y detiene el ciclo. El paso queda bloqueado con
`CONFIRMACION_REQUERIDA`, que representa espera de autorización humana.

La escritura continúa exclusivamente en la API humana `confirmar_nota()`. La
CLI muestra la nota y solicita `CONFIRMAR`; `POSPONER` no invoca esa API. No se
alteraron herramientas, permisos, prioridad registrada, memoria, RAG, cuotas o
credenciales.

## Regresiones

- Trece casos de intención: preparar, preparar con pronombre, redactar, proponer,
  negación explícita o coordinada con «ni», y preparación permitida con
  prohibición de registrar.
- Cuatro recorridos completos: consulta inicial terminada, reevaluación adaptativa
  terminada y petición de preparar una nota. Se cubren dos formulaciones, la
  misma instancia y una nueva instancia sobre la memoria SQLite persistida.
- Se verifica el mismo ID de plan, prioridad P2 intacta, nota pendiente hasta
  completar las cuatro verificaciones y quinta llamada destinada a preparar.
- Vista previa y solicitud de confirmación presentes; sin cierre `RESPUESTA_FINAL`
  que omita la nota, sin una llamada adicional para generar la respuesta final.
- `POSPONER` en la interfaz humana: cero notas, cero auditoría de escrituras e ITSM
  intacto. El texto de la nota pendiente no queda en la memoria persistente.
- El perfil `usuario_final` sigue denegado antes de llamar al modelo.

Desde PowerShell, en la raíz del repositorio:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_ep2_cierre.py
```

Informe completo local: `.cache/ep2_preparacion_nota_final_pytest.xml`, excluido de Git.

Resultado final: **670 pruebas aprobadas**, incluidas **18 regresiones nuevas**;
sin fallos, errores ni omisiones. Red bloqueada y cero intentos de conexión.
`git diff --check` aprobado. El cierre local, RAG, controles de escritura y datos
existentes permanecen intactos; cambios locales sin commit ni push.
