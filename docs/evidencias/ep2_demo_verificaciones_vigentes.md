# EP2: reducir llamadas de la demostración sin reutilizar evidencia obsoleta

Fecha: 30 de octubre de 2026. Investigación y pruebas locales sin Groq.

## Hallazgo y límite de reutilización

Una tercera consulta como «Prepara una nota sobre varios usuarios afectados por
VPN, sin registrarla todavía» vuelve a activar `multiples_usuarios()`.
`Planificador._replantear_impacto()` reabre ticket, SLA, análisis y procedimiento;
la nota depende de esas verificaciones. El cierre determinista conserva la nota
pendiente: hacen falta cuatro decisiones del modelo para las lecturas y otra
para seleccionar la preparación. El 429 durante esas decisiones sigue siendo
un error; no existe una escritura ni un cierre exitoso que lo sustituya.

La memoria persistida no permite demostrar por sí sola que las verificaciones
previas continúen vigentes:

- `memoria._hechos()` guarda campos permitidos, procedencia y fecha de observación.
  Para RAG conserva documento, título, fecha y puntuación; omite los fragmentos.
- No conserva versiones verificables del ticket y SLA, huellas del contenido RAG
  ni los argumentos completos de recuperación que permitan repetir su selección.
- Los 30 días de retención predeterminados son un límite de conservación, no una
  garantía de frescura. `contexto.proyectar_contexto()` marca los hechos anteriores
  como `historica_requiere_reconsulta`.
- Un plan completado del mismo usuario, sesión y perfil acredita ejecución pasada;
  no acredita que las fuentes o los permisos actuales sean idénticos.

Las regresiones modifican una fuente temporal **después** de persistir un plan
completo: la prioridad en SQLite o el contenido del documento en el docstore FAISS
cargado, manteniendo título y fecha. La tercera consulta recupera los datos
actuales. La fecha reciente del plan y los metadatos históricos no bastarían para
detectar ambos cambios. La modificación de prioridad pertenece exclusivamente al
fixture de prueba; el agente no cambia prioridades.

Por ello no se habilitó una caché basada solo en antigüedad o estado `completado`,
ni se cambió código de producción en esta revisión. Para reutilizar resultados
entre turnos haría falta un contrato adicional: comprobar versiones actuales de
fuentes y permisos, identidad de consulta/filtros, integridad de los resultados
necesarios e invalidación de dependencias. La memoria actual no lo proporciona.

## Alternativa segura para la demostración

Combinar el aviso de impacto y la preparación de nota en la segunda consulta.
Se conservan las cuatro verificaciones frescas, la selección de herramientas por
el LLM, FAISS, memoria, permisos y la confirmación humana. El guion pasa de
`3 + 4 + 5 = 12` a `3 + 5 = 8` llamadas al modelo, sin una petición adicional para
redactar el cierre. Es un recuento de decisiones en la regresión guionada; no es
una medición de tokens ni una garantía de ausencia de 429 en Groq.

Para una demostración manual desde PowerShell, en la raíz del repositorio:

```powershell
.\.venv\Scripts\python.exe -m src.ep2.cli --usuario agente_demo --sesion demo_ep2_compacta
```

Este comando es para uso manual con el proveedor configurado; **no se ejecutó**
durante esta validación. Usar un identificador de sesión nuevo para reproducir el
guion desde el inicio; mantener ese mismo identificador en ambas consultas.

Primera consulta:

> Consulta el ticket INC-2026-0411, revisa su SLA y busca el procedimiento KB-RED-02 para diagnosticar la falla de VPN. No modifiques el ticket.

Segunda consulta:

> Ahora varios usuarios de la misma sucursal están afectados por la VPN. Reevalúa el reporte y prepara una nota de seguimiento para ese ticket, sin registrarla todavía.

Comprobar en las trazas las cuatro verificaciones completadas y después
`registrar_nota_ticket:CONFIRMACION_REQUERIDA`. Revisar la vista previa y escribir
`POSPONER`: no registra la nota. El paso de nota queda esperando confirmación,
no completado. No enviar luego la tercera consulta que repite el mismo reporte.
Un nuevo cambio de impacto sí debe volver a revalidarse. Si aparece 429, detener
el guion y mostrar el error; esta alternativa no modifica cuotas ni reintenta a
ciegas. Si se necesitan tres consultas separadas, se mantienen las revalidaciones
y debe respetarse el límite vigente del proveedor.

## Regresiones reproducibles sin red

`tests/test_ep2_cierre.py` añade cuatro casos con modelo simulado, SQLite temporal
y FAISS real con vectores explícitos:

- Dos consultas combinadas: ocho decisiones, mismo plan y prioridad P2;
  dependencias completas, `tool_choice="auto"`, vista previa y confirmación
  obligatoria. Cero notas y cero auditorías de escritura; ITSM intacto.
- Dos cambios entre turnos: ticket o contenido RAG actualizado, nueva instancia
  sobre memoria persistida, sin reutilizar observaciones obsoletas.
- Tres consultas separadas y 429 simulado antes de preparar: error visible,
  ningún paso de nota completado y ninguna escritura.

Ejecutar las regresiones desde PowerShell con bloqueo explícito de conexiones:

```powershell
@'
import sys, pytest
intentos = []
def sin_red(evento, args):
    if evento in ("socket.connect", "socket.getaddrinfo", "socket.sendto"):
        intentos.append(evento)
        raise RuntimeError("RED_BLOQUEADA")
sys.addaudithook(sin_red)
codigo = pytest.main(["-q", "tests/test_ep2_cierre.py", "-k",
    "demo_replanificar or memoria_reciente or 429_antes_de_preparar"])
print("NETWORK_ATTEMPTS_BLOCKED:", len(intentos))
raise SystemExit(codigo if not intentos else 1)
'@ | .\.venv\Scripts\python.exe -
```

Resultado de las regresiones: **4 aprobadas**, 28 no seleccionadas; cero intentos
de conexión.

Suite completa: **674 aprobadas en 70,72 segundos**, cero fallos, errores u
omisiones, salida 0 y cero intentos de conexión. Informe JUnit verificado:
`.cache/ep2_demo_verificaciones_vigentes_pytest.xml`, excluido de Git.
Los 37 archivos protegidos comprobados por huella (código de producción,
configuración, credenciales, datos e índices locales y figuras existentes)
permanecen idénticos durante esta revisión. Los cambios anteriores se conservan;
no se realizaron commits ni push.
