# EP3 — Línea base e instrumentación inicial

> Antecedente de Etapa 1 (v1). Para la versión vigente v2, dashboard, HMAC estable,
> retención y evaluaciones, consultar [la guía completa](ep3_guia_completa.md).
> La descripción de clave efímera y los pendientes de este documento son históricos.

Esta etapa agrega observabilidad opcional a EP1 y EP2. No modifica prompts,
selección de modelos, registro de herramientas, reglas del planificador, permisos,
confirmaciones ni política de reintentos. No agrega dependencias.

## Componentes

| Módulo | Responsabilidad |
|---|---|
| `src/ep3/contratos.py` | Traza, evento y contadores con versión 1; campos y valores permitidos. |
| `src/ep3/observabilidad.py` | Contexto por consulta, HMAC, cola acotada y escritura en segundo plano. |
| `src/ep3/almacenamiento.py` | SQLite independiente con marca EP31 y versión de esquema. |
| `eval/check_ep3_regression.py` | Pruebas sin red, JUnit, log, versiones, huellas y verificaciones de integridad. |
| `eval/aislamiento_ep3.py` | Bloquea red, subprocesos y escrituras a artefactos originales durante evaluaciones. |
| `eval/check_ep3_observabilidad.py` | Muestra reproducible con LangChain, FAISS y SQLite locales y LLM simulado. |

La base predeterminada es `storage/ep3/observabilidad.db`, cubierta por el
`.gitignore` existente. Tiene tablas `trazas`, `eventos` y `salud_telemetria`.
Se rechazan bases ajenas, versiones incompatibles y enlaces a bases funcionales.
No se migra ni adopta una base desconocida. El dashboard futuro deberá abrirla en
modo de solo lectura sin construir agentes ni abrir la memoria funcional.

## Activación

Por defecto `EP3_OBSERVABILIDAD=0`: no se crea recolector, hilo ni base de datos.
Para una ejecución operativa, en una terminal con el entorno del proyecto activo:

```powershell
$env:EP3_OBSERVABILIDAD = '1'
$env:EP3_TIPO_EJECUCION = 'real'
python -m src.ep2.cli --usuario agente_demo --sesion sesion_demo --perfil agente
```

Ese comando abre la CLI normal: puede llamar a Groq y persiste memoria EP2.
No forma parte de las validaciones offline realizadas para esta etapa. Las
variables solo afectan ese proceso y no requieren editar `.env`.
`EP3_DIRECTORIO` permite seleccionar otro directorio exclusivo de telemetría.
Una configuración EP3 inválida desactiva la telemetría y suma un fallo de
configuración consultable mediante `fallos_configuracion()`.

También se puede inyectar un recolector en cualquiera de los dos agentes:

```python
from pathlib import Path
from src.ep3 import Observabilidad

with Observabilidad(Path('.cache/ep3/ensayo'), tipo_ejecucion='simulada') as obs:
    # Construir el agente con sus dependencias simuladas habituales.
    # AgenteEP2(servicio, llm=llm_simulado, observabilidad=obs)
    # AsistenteMesaAyuda(llm=llm_simulado, observabilidad=obs)
    pass
```

El recolector configurado por entorno se comparte dentro del proceso y se cierra
al salir. El recolector explícito debe cerrarse con `cerrar()` o `with`.
`flush(timeout=2)` espera los eventos aceptados; `cerrar(timeout=2)` indica si el
escritor terminó. Estas operaciones no se ejecutan dentro de `responder()`.

## Contrato de traza y evento v1

Los modelos Pydantic usan `extra='forbid'`, tipos estrictos y objetos inmutables.
Los JSON Schema se entregan en `ep3_traza_v1.schema.json` y
`ep3_evento_v1.schema.json`. Cambiar el contrato persistido requiere versionarlo.

| Campo | Significado |
|---|---|
| `version_esquema` | Literal `1`. |
| `ejecucion_id` | UUID nuevo por invocación de `responder()`. No es el identificador del plan. |
| `sesion_ref` | HMAC-SHA256 de la identidad del contexto y el pipeline. No contiene los identificadores originales. |
| `tipo_ejecucion` | `real`, `simulada` o `historica`; el origen se declara explícitamente. |
| `pipeline` | `ep1` o `ep2`. |
| `inicio_utc` | Inicio de la traza, con zona UTC. |
| `evento_id`, `secuencia`, `fecha_utc` | Identidad, orden por consulta y fecha UTC del evento. |
| `evento`, `componente` | Valores de listas cerradas. |
| `duracion_ms` | Duración monotónica observada, o `null` si el evento no representa una duración. |
| `estado`, `codigo` | Estado técnico y código permitido; los códigos desconocidos se sustituyen por `OTRO`. |
| `detalles` | Solo herramienta, intento, espera prevista, HTTP y resumen numérico/identidad UUID del plan. |

`real` identifica una invocación operativa; no acredita por sí sola una llamada al
proveedor. Una consulta bloqueada o un cierre local pueden no llamar al modelo.
`historica` está reservado para clasificar evidencia histórica: esta etapa no
importa reportes antiguos ni les atribuye latencias nuevas.

## Métricas implementadas

| Evento | Medición y frontera |
|---|---|
| `consulta_inicio`, `consulta_fin` | Latencia total, estado y código de la consulta; incluye guardarraíles, espera del cerrojo EP2 y memoria. Excluye espera humana y vaciado de telemetría. |
| `herramienta_fin` | Nombre, estado, código y duración de `TrazaHerramienta` EP2. Conserva la medición existente, que incluye controles y actualización del plan. |
| `modelo_error` | Intento fallido, duración observada y HTTP si está disponible. Nunca registra la excepción ni el contenido del proveedor. |
| `modelo_reintento` | Reintento programado por la política existente y `espera_prevista_ms`; no afirma cuánto duró realmente la espera. |
| `plan_inicial`, `observacion`, `plan_actualizado`, `plan_final` | Revisiones, código del cambio, identidad del plan y cantidad de pasos totales/completados/bloqueados. |

En EP1 la frontera observada de errores/reintentos es la invocación de la cadena,
y también se observan los reintentos del resumidor LLM. En EP2 se observa la
inferencia dentro del bucle de reintentos existente. No se cuentan decisiones
locales como llamadas HTTP ni se ejecutan nuevamente herramientas para medirlas.
La API humana de confirmación continúa separada; sus escrituras efectivas siguen
auditándose transaccionalmente en EP2, sin volcar capacidades de autorización a EP3.

## Fallas de la propia telemetría

`estadisticas()` devuelve únicamente contadores numéricos:

- `emitidos`: intentos de registrar eventos.
- `persistidos`: eventos cuya transacción terminó correctamente.
- `descartados`: eventos rechazados, perdidos por cola llena/cierre o por error de almacenamiento.
- `pendientes`: aceptados que aún no terminaron de procesarse.
- `fallos_validacion`, `fallos_almacenamiento`, `fallos_instrumentacion`.

El escritor guarda un snapshot de estos contadores. Si la base no está disponible,
la información sigue en RAM; no se finge que fue persistida. Una interrupción
abrupta del proceso puede perder eventos pendientes. La cola admite 1024 eventos
por defecto y el productor usa `put_nowait`; el escritor procesa lotes de hasta
64. Los errores se contabilizan sin imprimir excepciones crudas.

## Privacidad

Solo se persisten campos técnicos permitidos. Se excluyen consultas, respuestas,
fragmentos documentales, argumentos de herramientas, ticket, nombres, correos,
RUT, IP, claves API, contraseñas, huellas y solicitudes de confirmación. La base
de telemetría no replica la memoria funcional ni registra razonamiento del LLM.
El esquema de contadores también rechaza campos adicionales.

La clave HMAC predeterminada es aleatoria y vive solo en RAM durante la vida del
recolector. Por ello la referencia de sesión cambia entre procesos. La inyección
de `clave_sesion` con al menos 32 bytes permite una referencia estable, sin guardar
la clave en la base. La gestión persistente de esa clave queda pendiente para la
etapa de dashboard. La seudonimización no reemplaza el control de acceso al archivo.

## Reproducción sin red

Desde la raíz y con el entorno existente, usar carpetas nuevas para cada corrida:

```powershell
python -m eval.check_ep3_regression --salida .cache/ep3/mi_regresion
python -m eval.check_ep3_observabilidad --salida .cache/ep3/mi_muestra
```

El primer comando bloquea conexiones/DNS/UDP y subprocesos mediante auditoría de
Python; desactiva tracing y proveedores de embeddings remotos en ese proceso.
Permite lecturas explícitas SQLite `mode=ro`, protege `.env`, datos SQLite,
`storage/` y cachés originales, y verifica sus huellas antes/después. Además
comprueba que el código no cambió durante la suite. No ejecuta evaluadores Groq.
El resultado solo se aprueba con cero pruebas fallidas/errores, cero intentos
bloqueados y artefactos intactos. Las omitidas se informan explícitamente.

La muestra usa dos consultas, replanificación adaptativa y un HTTP 429 simulado.
Ejecuta los componentes locales existentes sobre datos temporales y entrega una
SQLite exclusiva con eventos y un resumen calculado desde esos eventos. Sus
latencias son tiempos de simulación local y no representan el rendimiento de Groq.

Los resultados de esta implementación y la procedencia de la línea base están en
[la evidencia de Etapa 1](evidencias/ep3_etapa1.md).

## Pendientes para el dashboard

- Interfaz Streamlit de solo lectura, filtros y agregaciones p50/p95 con tamaño de muestra.
- Política de retención, control de acceso y gestión de clave HMAC entre procesos.
- Desglose de RAG/memoria, tokens informados, recursos del proceso y evaluación de calidad.
- Importación explícita y separada de resultados históricos.
- Benchmark controlado de sobrecarga. Las comparaciones funcionales no prueban
  sobrecarga nula; el trabajo adicional puede afectar casos próximos al límite de tiempo.
- El aviso de deprecación de `RunnableWithMessageHistory` es previo en la API
  utilizada; esta etapa conserva LangChain 0.3 y no migra la arquitectura funcional.
