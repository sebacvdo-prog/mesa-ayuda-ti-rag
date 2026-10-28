# Arquitectura del asistente — EP1 y EP2

La descripción inicial conserva la arquitectura y los parámetros históricos de
EP1. La [arquitectura EP2](#arquitectura-ep2) al final incorpora el planificador,
la proyección por decisión, la memoria persistente y la confirmación humana.
Para instalación y configuración vigente, consultar el [README](../README.md).

## Visión general

El asistente es un sistema RAG (Retrieval-Augmented Generation) que combina recuperación vectorial sobre documentos no estructurados con consultas SQL sobre datos estructurados del ITSM. Está diseñado para operar como herramienta de apoyo al agente humano de Nivel 1, nunca como reemplazo: no ejecuta acciones, no entrega credenciales y siempre cita la fuente de sus indicaciones.

## Diagrama de capas

```mermaid
flowchart TB
    subgraph Capa de Presentación
        CLI["CLI\nsrc/cli.py"]
        APP["Streamlit\nsrc/app.py"]
    end

    subgraph Capa de Orquestación
        AGENT["Agente\nsrc/agent.py"]
        MEMORY["Memoria\nsrc/memory.py\nventana 6 turnos + resumen"]
    end

    subgraph Capa de Seguridad
        GUARD["Guardarraíles\nsrc/guardrails.py"]
        direction LR
        G1["Alcance"]
        G2["Credenciales"]
        G3["Nivel de acceso"]
        G4["Enmascarado PII"]
    end

    subgraph Capa de Recuperación
        ROUTER["Enrutador\ninterna / externa / mixta"]
        RETRIEVER["Retriever vectorial\nsrc/retriever.py"]
        RERANK["Re-ranking\npor vigencia"]
        SQLCONN["Conector SQL\nparametrizado"]
    end

    subgraph Capa de Datos
        FAISS[("FAISS\nstorage/faiss_index/")]
        SQLITE[("SQLite\ndata/itsm.db")]
        CORPUS["Corpus .md\ndata/internos/ + data/externos/"]
    end

    subgraph Capa de Modelos Externos
        GROQ["Groq API\nllama-3.3-70b-versatile"]
        GEMINI["Google AI\ngemini-embedding-001"]
    end

    subgraph Capa de Ingesta
        INGEST["Pipeline\nsrc/ingest.py"]
    end

    CLI --> AGENT
    APP --> AGENT
    AGENT --> GUARD
    AGENT --> MEMORY
    GUARD --> G1
    GUARD --> G2
    GUARD --> G3
    GUARD --> G4
    AGENT --> ROUTER
    ROUTER --> RETRIEVER
    ROUTER --> SQLCONN
    RETRIEVER --> RERANK
    RETRIEVER --> FAISS
    SQLCONN --> SQLITE
    AGENT --> GROQ
    INGEST --> CORPUS
    INGEST --> GEMINI
    INGEST --> FAISS
```

## Descripción de capas

### Capa de Presentación

Dos interfaces que consumen la misma API del agente:

- **CLI** (`src/cli.py`): modo conversación con selector de perfil, comandos `/fuentes`, `/reiniciar`, `/perfil`. Útil para la evaluación rápida y para operar sin navegador.
- **Streamlit** (`src/app.py`): historial visual, panel lateral con parámetros del pipeline, y un expander por respuesta que muestra los fragmentos recuperados con su puntaje y fecha de vigencia.

### Capa de Orquestación

- **Agente** (`src/agent.py`): cadena `prompt | llm | parser` envuelta en `RunnableWithMessageHistory`. Orquesta los 7 pasos del pipeline: guardarraíles → enrutamiento → recuperación → SQL → enmascarado → modelo → verificación de salida.
- **Memoria** (`src/memory.py`): ventana deslizante de los últimos 6 intercambios más resumen de sesión. Lo que sale de la ventana se pliega con un resumidor (LLM o heurístico), para que el contexto del síntoma sobreviva a la conversación.

### Capa de Seguridad

Cuatro controles aplicados en orden:

1. **Alcance**: rechaza consultas fuera del ámbito de TI (recetas, fútbol, criptomonedas).
2. **Credenciales**: bloquea toda solicitud del valor de una contraseña, PIN, token o código de verificación. No confunde con consultas legítimas sobre el procedimiento de restablecimiento.
3. **Nivel de acceso**: el perfil `usuario_final` solo ve documentos marcados `publico_interno`; el perfil `agente` ve todo.
4. **Enmascarado**: RUT, correos, teléfonos, IP y hostnames se reemplazan por marcas **antes** de la llamada al modelo, no después.

### Capa de Recuperación

- **Enrutador**: clasifica la consulta en `interna`, `externa` o `mixta` por heurística de palabras clave, y filtra el índice por el metadato `fuente`.
- **Retriever vectorial**: `similarity_search_with_relevance_scores` con `top_k=4` y umbral 0,72. Se piden `top_k * 5` candidatos para compensar el filtrado posterior.
- **Re-ranking por vigencia**: entre fragmentos con puntaje equivalente (diferencia < 0,05), prevalece el documento con `fecha_vigencia` más reciente. Esto permite que un aviso del CSIRT supere a un procedimiento interno desactualizado.
- **Conector SQL**: consultas parametrizadas con marcadores `?` a las tablas `tickets`, `sla`, `activos_cmdb` y `usuarios`. Detecta en la consulta identificadores de ticket, prioridades y RUT. Nunca interpola texto del usuario en el SQL.

### Capa de Datos

- **FAISS**: índice vectorial de 768 dimensiones, persistido en `storage/faiss_index/`. Solo contiene los documentos del corpus, nunca tickets ni datos de la CMDB.
- **SQLite** (`data/itsm.db`): 5 tablas que simulan el ITSM y la CMDB. 12 usuarios, 40 tickets, 20 activos, 6 categorías de servicio y 4 niveles de SLA.
- **Corpus**: 6 documentos internos (KB, catálogo de servicios, política de seguridad) y 3 externos (Microsoft, Fortinet, CSIRT). Cada uno con frontmatter YAML.

### Capa de Modelos Externos

- **Groq** (`llama-3.3-70b-versatile`): modelo de chat a temperatura 0,1 con máximo 700 tokens. Se accede vía endpoint compatible con OpenAI. Cuota gratuita: 100.000 tokens/día.
- **Google AI** (`gemini-embedding-001`): embeddings de 768 dimensiones con caché en disco (SQLite). La caché evita recalcular vectores al reingestar. Cuota gratuita: 1.000 peticiones/día.

### Capa de Ingesta

- **Pipeline** (`src/ingest.py`): carga → normalización → fragmentación (`RecursiveCharacterTextSplitter`, 900 caracteres, 150 de solape) → metadatos → embeddings → FAISS. Idempotente por manifiesto con hash del corpus y los parámetros.

## Flujo de una consulta

```mermaid
sequenceDiagram
    actor Usuario
    participant Agente as agent.py
    participant Guard as guardrails.py
    participant Retriever as retriever.py
    participant SQL as ConectorITSM
    participant LLM as Groq

    Usuario->>Agente: consulta
    Agente->>Guard: evaluar_consulta()
    alt bloqueada
        Guard-->>Agente: mensaje de rechazo
        Agente-->>Usuario: respuesta de bloqueo
    else permitida
        Agente->>Retriever: buscar(consulta, perfil)
        Retriever-->>Agente: fragmentos filtrados y reordenados
        Agente->>SQL: consultar_datos_estructurados()
        SQL-->>Agente: datos del ITSM
        Agente->>Agente: enmascarar(consulta + contexto + datos)
        alt sin contexto ni datos
            Agente-->>Usuario: respuesta de escalamiento determinista
        else con contexto
            Agente->>LLM: invoke(prompt con historial)
            LLM-->>Agente: respuesta
            Agente->>Agente: asegurar bloque de fuente
            Agente-->>Usuario: respuesta con cita y escalamiento
        end
    end
```

## Decisiones de diseño relevantes

1. **Tickets no vectorizados.** Son datos estructurados con identificadores exactos: buscarlos por similitud semántica sería más lento y menos preciso que SQL.
2. **Enmascarado antes de la llamada.** Se enmascara la entrada, no la salida. Enmascarar la respuesta deja los datos igualmente enviados al proveedor.
3. **Respuesta determinista sin contexto.** Si no hay fragmentos ni datos del ITSM, la respuesta es literal y no se gasta una llamada al modelo.
4. **Caché de embeddings.** Un SQLite local guarda los vectores ya calculados, keyed por SHA-256 del modelo, el tipo y el texto. Cambiar de modelo invalida la caché automáticamente.
5. **Backoff exponencial.** Los reintentos ante HTTP 429 siguen `espera_base^n + jitter`, con un techo de 60 segundos. Solo se reintenta error de cuota; cualquier otro error se propaga de inmediato.

## Arquitectura EP2

Este diagrama describe las llamadas y fronteras implementadas en el cierre de
Etapa 4. No representa una ejecución nueva ni una conexión con un ITSM productivo.
CLI y Streamlit EP1 permanecen independientes de la CLI EP2.

```mermaid
flowchart TD
    U["Persona"] --> CLI["CLI EP2: contexto y guardarraíles"]
    CLI --> M["MemoriaEP2: recuperar contexto"]
    M <--> DB[("SQLite EP2: agent.db<br/>memoria, plan, notas y auditoría")]
    M --> P["Planificador adaptativo<br/>prioridades, dependencias y estados"]
    P --> E["LangChain AgentExecutor<br/>un ciclo por consulta"]
    E --> O["Oferta habilitada por el servidor"]
    P --> O
    O --> C["Proyección de contexto por decisión<br/>solo lectura"]
    M --> C
    C --> L["Groq: selección de una herramienta<br/>o respuesta permitida por el plan"]
    L --> V["Validación local de selección<br/>argumentos, permisos y plan"]
    V --> R["Herramientas de consulta y triage"]
    R --> I[("ITSM SQLite: itsm.db<br/>mode=ro, SQL parametrizado")]
    R --> F["RecuperadorVectorial: filtros y umbral"]
    F --> FA[("FAISS: corpus documental")]
    R --> OB["Observación: estado, código y procedencia"]
    OB --> P
    OB --> E
    V --> N["registrar_nota_ticket<br/>solo propuesta y vista previa"]
    N -->|"verificar ticket en lectura"| I
    N -->|"return_direct: pausa"| S["Respuesta y persistencia de memoria/plan"]
    E --> S
    S --> M
    S --> H["Campo humano independiente del LLM"]
    H -->|"POSPONER: conservar pendiente"| CLI
    H -->|"CONFIRMAR o cancelar"| API["API humana confirmar_nota<br/>permiso, huella y vigencia"]
    API -->|"revalidar ticket en lectura"| I
    API -->|"solo confirmación válida: nota y auditoría atómicas"| DB
    API -->|"recibo mínimo, actualización posterior"| M
```

Las flechas representan dependencias de datos y llamadas. El `AgentExecutor`
invoca el adaptador en cada decisión; la oferta y la proyección no son otros
agentes ni ejecutan herramientas. Antes de la siguiente decisión, los resultados
actualizan el plan. Los pasos bloqueados, completados o sin dependencias satisfechas
no se ofrecen como acciones pendientes. En modo `solo_estado` o plan completado
se permite responder sin herramientas; un plan bloqueado o sin permisos detiene
el ciclo desde el servidor.

### Correspondencia con los módulos

| Componente | Implementación verificable |
|---|---|
| CLI y contexto | [cli.py](../src/ep2/cli.py): `main()`, `mostrar_trazabilidad()` y `resolver_confirmaciones()`; identidad local sin autenticación empresarial. |
| Ejecutor y oferta | [agente.py](../src/ep2/agente.py): `AgenteEP2._responder()`, `_ModeloPlanificado.bind_tools()`, `_oferta_herramientas()` y `_validar_decision()`. |
| Planificador | [planificacion.py](../src/ep2/planificacion.py): `Planificador`, `disponibles()`, `preparar()`, `observar()` y `_replantear_impacto()`; grafo validado mediante [contratos.py](../src/ep2/contratos.py). |
| Proyección | [contexto.py](../src/ep2/contexto.py): `proyectar_contexto()` construye reglas y datos pertinentes; distingue hechos históricos, observaciones actuales y solicitudes no verificadas. |
| Memoria persistente | [memoria.py](../src/ep2/memoria.py): `recuperar()` y `registrar_turno()`; clave usuario/sesión/perfil y snapshot acotado que incluye el plan. |
| Consultas y triage | [herramientas.py](../src/ep2/herramientas.py): `consultar_ticket`, `consultar_sla`, `consultar_activo`, `buscar_procedimiento` y `analizar_incidente`. Este último aplica reglas sobre ITSM/SLA; no comprueba infraestructura. |
| RAG e ITSM | [retriever.py](../src/retriever.py): `RecuperadorVectorial` y `ConectorITSM`. FAISS contiene documentos; los tickets se consultan por SQL. |
| Propuesta y escritura | `registrar_nota_ticket` llama a `HerramientasEP2.preparar_nota()`. `confirmar_nota()` está fuera del registro del LLM; [almacenamiento.py](../src/ep2/almacenamiento.py) confirma nota y auditoría juntas. |

La proyección no modifica memoria ni autoriza operaciones. El estado canónico
permanece en SQLite dentro de los límites de retención; no se restaura el
scratchpad ni una autorización de escritura. Una nueva vista previa y una
decisión humana válida son necesarias después de reiniciar. `POSPONER` no invoca
la API de confirmación: la propuesta ya persistida continúa pendiente.

La confirmación registra únicamente en SQLite EP2, no modifica el ITSM ni su
prioridad. Nota y auditoría forman una transacción; actualizar después su recibo
en memoria es otra operación. Los datos y perfiles del proyecto son simulados.

Las [584 pruebas automatizadas y el cierre real 15/15](evidencias/ep2_etapa4_cierre_tecnico.md)
son evidencias distintas. La integral real verificó propuesta pospuesta y cero
escrituras de negocio; las confirmaciones efectivas se comprobaron con pruebas
automatizadas en bases temporales. No se acreditan escalabilidad bajo carga ni
fidelidad semántica universal.

Ver [bocetos de los flujos EP2](bocetos/ep2.md),
[detalle de Etapa 4](ep2_etapa4.md) y [trazabilidad IE1–IE10](trazabilidad_ep2.md).
