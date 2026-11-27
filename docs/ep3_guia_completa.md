# EP3 — Guía técnica vigente

La solución es local, opcional y conserva el comportamiento funcional de EP1/EP2.
No incorpora autenticación empresarial, no demuestra cumplimiento normativo y no
activa servicios externos. La CLI sigue usando perfiles declarados para la simulación.

## Instalación y entorno

Usar el entorno existente; no recrearlo ni sobrescribir `.env`. La evidencia
registra Python y versiones realmente utilizadas. No se añadieron dependencias:
Streamlit, pandas, LangChain, Pydantic y FAISS ya forman parte del entorno.
CPU/RAM se consultan con biblioteca estándar y API del proceso en Windows/Linux.

Para una instalación **nueva**, revisar primero `requirements.txt` y preparar
manualmente un entorno Python compatible (se verificó Python 3.12). La instalación
requiere acceso de red y no se ejecutó durante este trabajo:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Los rangos del archivo de requisitos no son un lock completo. Para reproducir la
ejecución concreta, revisar el inventario de dependencias en las evidencias.

## Evaluación y dashboard sin servicios externos

Desde la raíz del repositorio:

```powershell
$pyEP3 = '.\.venv\Scripts\python.exe'
$runEP3 = Get-Date -Format 'yyyyMMdd-HHmmss'
$salidaEP3 = ".cache/ep3/evaluacion-$runEP3"
& $pyEP3 -B -m eval.check_ep3_regression --salida ".cache/ep3/pruebas-$runEP3"
& $pyEP3 -B -m eval.evaluate_ep3 --salida $salidaEP3 --pares 30
& $pyEP3 -B -m eval.analyze_ep3 --base "$salidaEP3/observabilidad.db" --evaluacion "$salidaEP3/evaluacion.json" --salida "$salidaEP3/analisis"
& $pyEP3 -B -m eval.gestion_ep3 exportar --ruta "$salidaEP3/observabilidad.db" --salida "$salidaEP3/exportacion"
$env:EP3_DASHBOARD_DB = "$salidaEP3/observabilidad.db"
& $pyEP3 -m streamlit run src/dashboard_ep3.py --server.address=127.0.0.1 --server.port=8503 --browser.gatherUsageStats=false
```

Abrir `http://127.0.0.1:8503` localmente. Detener Streamlit con Ctrl+C. El dashboard
no inicia el agente, no ejecuta herramientas, no llama a Groq y no migra bases.
Las carpetas de salida deben ser nuevas: la protección contra sobrescritura es intencional.

La evaluación crea datos funcionales temporales y una telemetría exclusiva. Usa
corpus y FAISS locales, vectores explícitamente simulados y un LLM guionado. No
descarga modelos, no mide embeddings semánticos reales ni calidad generativa de Groq.
Los escenarios cubren ticket/SLA, KB-RED-02, impacto, propuesta, POSPONER,
procedimiento ausente, 429/recuperación/agotamiento y seguridad. Las referencias
están en `eval/escenarios_ep3.py`. Se exportan indicadores, no consultas ni respuestas.

## HMAC estable y activación operativa

Una clave HMAC **dedicada** se prepara explícitamente; nunca reutilizar una API key.
El comando no muestra el secreto y falla si el archivo ya existe:

```powershell
& $pyEP3 -B -m eval.gestion_ep3 clave --ruta storage/ep3/claves/sesion.key
$env:EP3_HMAC_KEY_FILE = (Resolve-Path 'storage/ep3/claves/sesion.key').Path
$env:EP3_OBSERVABILIDAD = '1'
$env:EP3_TIPO_EJECUCION = 'real'
$env:EP3_RETENCION_DIAS = '30'
```

`EP3_DIRECTORIO` cambia el directorio exclusivo de telemetría; por defecto es
`storage/ep3`. La clave es un archivo binario de 32 bytes excluido de Git por
extensión y directorio. Proteger su ACL y no adjuntarla a informes, entregas o ZIP.
El identificador de clave es una huella corta; no permite reconstruirla. Usar la
misma clave conserva la referencia de sesión entre procesos. Rotarla cambia esas
referencias y requiere documentar el cambio de clave_id.
Reiniciar el proceso recolector al cambiar clave o política; las instancias ya
construidas conservan su configuración durante su vida.

Si no se configura clave, los eventos se registran con `sesion_ref=null` y
`correlacion=desactivada`. Si se configura una clave inválida o inaccesible, la
activación por entorno se desactiva y suma un fallo de configuración. Nunca se
genera una clave aleatoria nueva por proceso para aparentar continuidad.

## PENDIENTE DE EJECUCIÓN REAL — Groq

Requiere credenciales válidas, cuota y decisión del operador. No se ejecutó en
esta implementación. No se modifican modelo, límites ni claves existentes:

Si los embeddings configurados usan un proveedor remoto, esa ejecución también
requiere su autorización y cuota; un modelo Hugging Face debe estar previamente
disponible en la caché local para operar sin descargarlo.

```powershell
$env:LANGCHAIN_TRACING_V2 = 'false'
$env:LANGSMITH_TRACING = 'false'
# Mantener EP3_OBSERVABILIDAD=1, tipo real y HMAC configurado como arriba.
& $pyEP3 -m src.ep2.cli --usuario agente_ep3 --sesion validacion_real_ep3 --perfil agente
```

Usar entradas sintéticas controladas de ticket/SLA y KB-RED-02. Una nota debe
quedar pendiente salvo decisión humana deliberada. No grabar transcripciones ni
pegar respuestas o documentos en logs. Después de cerrar la CLI, inspeccionar
los eventos técnicos del origen `real` desde el dashboard. Los tokens faltantes
permanecen NULL; no se deduce costo ni cuota desde una estimación.

## Desactivación

```powershell
$env:EP3_OBSERVABILIDAD = '0'
```

Los cambios afectan al siguiente proceso/agente construido. No editar `.env` ni
borrar bases para desactivar. El dashboard puede seguir leyendo datos existentes.

## Privacidad, retención y migración

- Contratos cerrados: no se almacenan prompts, respuestas, notas, documentos,
  argumentos, ticket, identificadores originales de usuario/sesión, excepciones,
  cabeceras ni capacidades de confirmación.
- La telemetría usa SQLite EP31, separada de ITSM, memoria y cachés. La confirmación
  y auditoría de notas siguen siendo operaciones funcionales transaccionales.
- La base v1 se respalda consistentemente antes del DDL; se conservan sus JSON sin
  reescribirlos. Se agregan columnas, índices y evaluaciones dentro de transacción.
  Se rechazan bases ajenas, esquemas futuros y enlaces a bases funcionales.
- Retención predeterminada: ventana de consulta de 30 días, configurable entre 1
  y 3650. El dashboard permite incluir datos anteriores. **No hay DELETE automático**:
  ni el escritor ni el dashboard borran evidencia. El operador debe archivar y
  decidir la conservación según la pauta y su política local.
- Una falla de disco o cola llena afecta a la telemetría y sus contadores; no
  autoriza acciones ni cambia la respuesta. Un cierre abrupto puede perder pendientes.

## Interpretación y límites

Los orígenes real/simulado/histórico se seleccionan por separado. La exactitud de
hechos y el acierto documental contrastan referencias controladas. La consistencia
se calcula entre paráfrasis equivalentes; no entre distintas fallas inyectadas.
Una similitud FAISS no es una probabilidad ni la precisión de una respuesta.

El benchmark usa pares con/sin observabilidad, bases nuevas equivalentes,
calentamiento, orden balanceado y semilla fija. Solo cronometra `responder()`;
creación de datos, recolección de ciclos del seed y flush están fuera del tiempo.
Sin espera de red, el porcentaje de sobrecarga local puede ser mayor que en una
API real. Se conservan deltas negativos y tamaño de muestra. No representa carga
concurrente, un SLA productivo ni una garantía de sobrecarga cero.

Las pruebas Streamlit AppTest no crean un servidor web. Windows necesita un
`socketpair` de IPC loopback: el auditor permite solo el socket y puerto creados
por la implementación estándar, y contabiliza `ipc_socketpair_local` por separado.
Las demás conexiones, DNS y subprocesos continúan bloqueados.

Consultar [arquitectura/métricas](ep3_arquitectura_metricas.md),
[evidencias](evidencias/ep3_desarrollo_tecnico.md),
[informe de cinco páginas](ep3_esquema_informe.md) y [defensa](ep3_defensa.md).
