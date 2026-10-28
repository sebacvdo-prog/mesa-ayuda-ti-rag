# Bocetos de las interfaces EP1 y EP2

Los esquemas de CLI y Streamlit que siguen son bocetos históricos de EP1;
sus valores ilustrativos no son métricas ni capturas nuevas de ejecución.
Los [bocetos EP2](ep2.md) muestran consulta, replanificación, continuidad y
confirmación humana en la CLI independiente, con referencias al código y a la
evidencia existente. La [arquitectura EP2](../arquitectura.md#arquitectura-ep2)
describe sus componentes.

## CLI (`src/cli.py`)

```
==============================================================================
ASISTENTE DE LA MESA DE AYUDA TI · Aconcagua Logística SpA
==============================================================================
Perfil activo: agente
Modelo de chat: llama-3.3-70b-versatile (temperatura 0.1)
Recuperación: top_k=4, umbral=0.72
El asistente no ejecuta acciones ni entrega credenciales.

Comandos disponibles:
  /ayuda              Muestra esta ayuda
  /perfil agente      Cambia al perfil de agente
  /perfil usuario     Cambia al perfil de usuario final
  /fuentes            Muestra los fragmentos recuperados
  /reiniciar          Borra la memoria de la conversación
  /salir              Termina la sesión

Consulta> Un conductor no puede abrir la app de ruta en el terminal

------------------------------------------------------------------------------
Diagnóstico probable: sesión corporativa vencida en el terminal...

Pasos:
1. Pedir al conductor que detenga el vehículo...
2. Reiniciar el terminal por completo...
3. Iniciar sesión de nuevo...
...

Prioridad y tiempo comprometido: P2 Alta...

Escalamiento: si tras el reinicio...

Fuente: [KB-MOV-03 · Terminales móviles · 2026-06-15]
------------------------------------------------------------------------------
[consulta: interna · perfil: agente · fragmentos: 3 · escalamiento: no]
```

### Decisiones de diseño de la CLI

- Encabezado con perfil y parámetros del pipeline para que el evaluador vea de un vistazo la configuración.
- Barra de estado debajo de cada respuesta con clasificación, perfil, cantidad de fragmentos y escalamiento.
- Comandos con `/` para cambiar perfil, ver fuentes y reiniciar sin salir.
- El comando `/fuentes` muestra archivo, puntaje de similitud y vigencia de cada fragmento, para auditar la respuesta.

## Streamlit (`src/app.py`)

```
┌──────────────────────────────────────────────────────────────────────┐
│  Asistente Mesa de Ayuda TI · Aconcagua Logística                  │
│                                                                     │
│  ┌─── Panel lateral ──────────┐  ┌─── Área de chat ───────────────┐ │
│  │                            │  │                                │ │
│  │  Configuración             │  │  🧑 Un conductor no puede     │ │
│  │                            │  │     conectar la VPN...         │ │
│  │  Perfil:                   │  │                                │ │
│  │  ○ Agente (ve todo)        │  │  🤖 Diagnóstico probable:     │ │
│  │  ● Usuario final           │  │     ...                       │ │
│  │                            │  │                                │ │
│  │  ─────────────────         │  │  ▼ Fragmentos recuperados (3)  │ │
│  │  Parámetros del pipeline   │  │  ┌──────────────────────────┐  │ │
│  │  · Modelo: llama-3.3...    │  │  │ 1. Conectividad y VPN    │  │ │
│  │  · Temperatura: 0.1        │  │  │    Similitud: 0.891      │  │ │
│  │  · Embeddings: gemini...   │  │  │    Vigencia: 2026-05-10  │  │ │
│  │  · top_k: 4                │  │  │    Fuente: interna       │  │ │
│  │  · Umbral: 0.72            │  │  │    «El cliente VPN...»   │  │ │
│  │  · Memoria: 6 turnos       │  │  └──────────────────────────┘  │ │
│  │                            │  │                                │ │
│  │  ─────────────────         │  │  ┌─ Datos SQL del ITSM ─────┐  │ │
│  │  Reglas activas            │  │  │ (consulta parametrizada)  │  │ │
│  │  · No entrega credenciales │  │  └──────────────────────────┘  │ │
│  │  · No ejecuta acciones     │  │                                │ │
│  │  · Enmascara PII           │  │  ┌─ Datos enmascarados ─────┐  │ │
│  │  · Cita la fuente          │  │  │ {"rut": 1, "ip": 2}      │  │ │
│  │                            │  │  └──────────────────────────┘  │ │
│  │  ─────────────────         │  │                                │ │
│  │  [Reiniciar conversación]  │  │  Escribe tu consulta aquí...  │ │
│  │                            │  │                                │ │
│  └────────────────────────────┘  └────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────┘
```

### Decisiones de diseño de Streamlit

- **Panel lateral fijo** con perfil, parámetros y reglas: el agente siempre ve con qué configuración está operando.
- **Expander de fragmentos** debajo de cada respuesta: muestra puntaje de similitud, fecha de vigencia, fuente, nivel de acceso y un extracto del contenido. Sin esto, el agente no puede auditar de dónde salió la indicación.
- **Datos SQL y enmascarado** también en el expander: transparencia total sobre qué datos se consultaron y qué se enmascaró.
- **Botón de reinicio** en el panel lateral: borra la memoria de sesión sin recargar la aplicación.
- **Caché del asistente** con `@st.cache_resource`: el índice FAISS y el modelo se cargan una vez por proceso.
- **Ejemplos sugeridos**: 5 consultas de ejemplo para orientar al evaluador.
