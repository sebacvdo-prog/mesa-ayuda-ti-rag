# EP2 — Etapa 1: contratos, permisos y notas confirmadas

Estado verificado el 15 de octubre de 2026. Esta etapa es independiente del
asistente EP1: no incorpora todavía el agente de producción, memoria
conversacional persistente, planificación adaptativa ni cambios en las interfaces.

## Alcance y archivos

| Archivo | Responsabilidad |
|---|---|
| `src/ep2/contratos.py` | Entradas y resultados Pydantic; contexto de confianza y confirmaciones. |
| `src/ep2/almacenamiento.py` | Base SQLite EP2, transacciones, idempotencia y auditoría. |
| `src/ep2/herramientas.py` | Permisos, consultas, vista previa, cancelación y registro confirmado. |
| `eval/check_groq_tools.py` | Prueba manual real de compatibilidad, con herramienta sintética sin escritura. |
| `tests/test_ep2_etapa1.py` | Pruebas reproducibles con bases temporales, sin APIs. |

Los archivos originales, `.env`, el ITSM y el índice FAISS se conservaron:
se compararon los hashes de los 60 archivos presentes en la instantánea inicial
y no cambió ninguno. Tampoco se cambiaron dependencias ni se repitió la calibración.
Hugging Face conserva `HF_SIMILARITY_THRESHOLD=0.471764`; Google conserva `0.72`.

## Contratos y permisos

`ContextoEjecucion` contiene `usuario_id`, `sesion_id` y `perfil`. Lo establece la
aplicación de confianza. Se requieren identificadores internos opacos; el contrato
rechaza correos como identificador y perfiles distintos de los definidos.
Esto no implementa un sistema de autenticación: la interfaz futura debe obtener
el contexto de una identidad validada y no del mensaje del usuario ni del LLM.

| Operación | Entrada | Perfil agente | Perfil usuario_final |
|---|---|---|---|
| `consultar_ticket` | `ConsultaTicket` | Permitida; devuelve campos técnicos mínimos. | Denegada. |
| `consultar_sla` | `ConsultaSLA` | Permitida. | Permitida; no contiene datos personales. |
| `consultar_notas` | `ConsultaTicket` | Solo notas del mismo usuario y sesión. | Denegada. |
| `preparar_nota` | `RegistrarNota` | Solicita confirmación; no registra una nota. | Denegada. |
| `confirmar_nota` | `DecisionConfirmacion` | Exclusivamente desde la interfaz humana. | Denegada. |

`RegistrarNota` exige ticket, texto e identificador UUID de operación. Rechaza
campos adicionales, incluidos `confirmado`, `perfil`, `usuario_id` y `sesion_id`.
La aplicación debe generar y conservar `id_operacion` durante los reintentos.
Los resultados comparten estado, código, mensaje, datos y procedencia.

## Confirmación explícita

```mermaid
sequenceDiagram
    actor Usuario
    participant UI as Interfaz de confianza
    participant H as Herramientas EP2
    participant I as ITSM solo lectura
    participant E as SQLite EP2
    UI->>H: preparar_nota(contexto fijado, propuesta)
    H->>I: verificar existencia del ticket
    H-->>UI: vista previa enmascarada, solicitud, huella y caducidad
    UI-->>Usuario: mostrar contenido y solicitar confirmar/cancelar
    Usuario->>UI: decisión explícita
    UI->>H: confirmar_nota(solicitud, huella, decisión)
    H->>H: validar permiso, solicitud, contenido y vigencia
    alt cancelar
        H-->>UI: cancelada, sin registrar nota
    else confirmar
        H->>I: verificar nuevamente el ticket
        H->>E: BEGIN IMMEDIATE; nota + auditoría; COMMIT
        E-->>H: identificador persistido o operación previa
        H-->>UI: resultado confirmado
    end
```

La solicitud queda vinculada al usuario, sesión y contenido enmascarado. La
interfaz debe mostrar ese contenido, no el texto original, y enviar su huella.
La vigencia predeterminada es de cinco minutos y es configurable al construir
el servicio. Reiniciar el servicio invalida solicitudes pendientes y obliga a
solicitar una confirmación nueva.

**No registrar `confirmar_nota` como herramienta de LangChain.** El LLM podrá
proponer notas mediante `preparar_nota`, pero la decisión deberá proceder de un
evento humano validado por la interfaz. Un `confirmado=true` generado por el
modelo no autoriza ninguna escritura. Esta etapa proporciona esa frontera de API;
la interfaz de confirmación se conectará en una etapa posterior.

Una cancelación posterior al registro devuelve `NOTA_YA_REGISTRADA`; no afirma
haber deshecho una escritura. Confirmación y cancelación se serializan dentro de
cada instancia del servicio para evitar respuestas contradictorias durante el commit.

## Persistencia e idempotencia

La ruta predeterminada es `storage/ep2/agent.db`, excluida de Git por la regla
existente `storage/`. Se creó con tablas `notas` y `auditoria`, ambas vacías en el
entorno local. Las escrituras de validación se realizaron solo en bases temporales.

El almacenamiento conserva:

- Identificador de nota, ticket, usuario y sesión.
- Identificadores de operación y solicitud, huella del contenido y fechas UTC.
- Texto enmascarado y origen `confirmacion_explicita_usuario`.
- Evento de auditoría con referencia a la nota; no duplica su texto.

La clave de idempotencia es `(usuario_id, sesion_id, id_operacion)`. Un reintento
con igual contenido devuelve la nota anterior sin insertar otra nota ni otro
evento. Reutilizar la clave con distinto contenido devuelve conflicto. Una
operación ya confirmada puede recuperarse después de reconstruir el servicio.
Esto es persistencia de operaciones; la continuidad conversacional pertenece a
la Etapa 3.

`BEGIN IMMEDIATE` y la restricción UNIQUE controlan confirmaciones concurrentes.
Nota y auditoría se escriben en la misma transacción: si falla cualquiera,
se revierten ambas y se puede reintentar. Las consultas utilizan parámetros SQL.

La base incluye `application_id` EP21 y versión de esquema 1. Se rechazan bases
existentes sin esas marcas y enlaces al ITSM original; no se borran ni migran
bases ajenas. El conector original continúa abriendo el ITSM con `mode=ro`.

Se enmascaran los datos personales reconocidos por los guardarraíles existentes
antes de crear la vista previa. Se rechazan patrones comunes de credenciales.
Estos detectores son heurísticos: no garantizan reconocer todos los nombres o
secretos posibles. El entorno de demostración debe seguir usando datos ficticios.

## Ejemplo desde una interfaz humana de consola

Ejemplo de uso de la API, no integrado aún en la CLI/Streamlit existentes:

```python
from uuid import uuid4
from src.ep2.almacenamiento import AlmacenEP2
from src.ep2.contratos import ContextoEjecucion, RegistrarNota, DecisionConfirmacion
from src.ep2.herramientas import HerramientasEP2

# En la aplicación final, este contexto procederá de la identidad de confianza.
contexto = ContextoEjecucion(
    usuario_id="agente_demo", sesion_id="sesion_demo", perfil="agente"
)
servicio = HerramientasEP2(contexto, AlmacenEP2())
propuesta = RegistrarNota(
    ticket_id="INC-2026-0411", id_operacion=uuid4(),
    texto="Se consultó el caso y se solicita seguimiento."
)
pendiente = servicio.preparar_nota(propuesta)
if pendiente.estado == "requiere_confirmacion":
    print(pendiente.mensaje)
    print(pendiente.datos["texto"])
    respuesta = input("Escribe CONFIRMAR para registrar; otra respuesta cancela: ")
    resultado = servicio.confirmar_nota(DecisionConfirmacion(
        solicitud_id=pendiente.datos["solicitud_id"],
        huella=pendiente.datos["huella"],
        decision="confirmar" if respuesta.strip().upper() == "CONFIRMAR" else "cancelar"
    ))
    print(resultado.model_dump_json(indent=2))
else:
    print(pendiente.model_dump_json(indent=2))
```

## Compatibilidad real con Groq

Se probó `create_tool_calling_agent` + `AgentExecutor` con una función sintética
que devuelve una marca verificable. No consulta el ITSM, no registra notas y no
cambia `.env`. Se utilizó el mismo conector `ChatOpenAI` y endpoint Groq existentes.

| Modelo | Resultado real |
|---|---|
| Configurado: `llama-3.3-70b-versatile` | HTTP 404: el modelo no existe o la cuenta no tiene acceso. La llamada simple sin herramientas también falla. |
| Alternativa temporal: `qwen/qwen3.8-27b` | HTTP 429; no se pudo confirmar la integración por límite de uso. |
| Alternativa temporal: `openai/gpt-oss-20b` | Integración aprobada: seleccionó y ejecutó la herramienta, y devolvió su estado y marca reales. |

La lista de modelos accesibles no incluía el modelo configurado. El fallo 404
no acredita una incompatibilidad de LangChain Agents. La alternativa comprobada
para considerar en Etapa 2 es `openai/gpt-oss-20b`; **no se sustituyó el modelo
configurado ni se modificaron dependencias**. Su adopción queda pendiente de revisión.
La prueba acredita un caso mínimo, no todos los futuros flujos o herramientas.

Reproducir manualmente; estos comandos llaman a la API y consumen su cuota:

```powershell
.\.venv\Scripts\python.exe -m eval.check_groq_tools
.\.venv\Scripts\python.exe -m eval.check_groq_tools --model openai/gpt-oss-20b
```

Referencia técnica: Groq. (s. f.). *Local tool calling*. GroqDocs.
https://console.groq.com/docs/tool-use/local-tool-calling

## Validación y correspondencia con la pauta

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m pip check
```

Resultado: **181 pruebas aprobadas**, incluidas las 145 existentes y 36 nuevas de
Etapa 1. `pip check`: **No broken requirements found**.

Las pruebas ejercitan SQLite real temporal: permisos, suplantación de argumentos,
confirmación/cancelación/caducidad, huella alterada, aislamiento de usuarios y
sesiones, reintentos, conflictos, concurrencia, rollback de auditoría, SQL
literal en notas, enmascarado, rechazo de secretos, bases ajenas y enlaces al ITSM.

| Indicador | Aporte de esta etapa | Pendiente |
|---|---|---|
| IE1 | Servicios de consulta/escritura con contratos y autorización. | Selección autónoma por el agente en Etapa 2. |
| IE2 | Compatibilidad mínima real del framework con una alternativa Groq, sin cambios de dependencias. | Revisar modelo y conectar el agente a estas herramientas. |
| IE3 | Separación por usuario/sesión y procedencia de operaciones persistidas. | Memoria conversacional de corto/largo plazo en Etapa 3. |
| IE4 | RAG existente preservado, con su configuración y evidencia. | Integrarlo como herramienta y verificar continuidad contextual. |
| IE5 | No se implementa todavía. | Planificación adaptativa y sus pruebas en Etapa 4. |
| IE6 | Documentación técnica y flujo de confirmación. | Informe final Word/PDF de máximo cinco páginas. |
| IE7 | Condiciones de permisos, errores y confirmación verificadas por pruebas. | Demostración de decisiones del agente funcional. |
| IE8 | Código nuevo, documentación y pruebas reproducibles. | README y entrega del repositorio de la solución completa. |
| IE9–IE10 | Resultados de compatibilidad y pruebas para respaldar la defensa. | Argumentación y presentación elaboradas por los estudiantes. |

No se realizaron commits ni push. El desarrollo se detiene al finalizar la
Etapa 1. La siguiente etapa necesita autorización; las justificaciones finales,
conclusiones y reflexiones académicas deben redactarlas los estudiantes, con
la declaración de uso de IA exigida por la pauta.
