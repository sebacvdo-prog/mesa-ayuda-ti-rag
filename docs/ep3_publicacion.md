# Preparación de publicación EP3 — 27 de noviembre de 2026

El conjunto queda preparado para revisión y publicación conjunta de los
prerrequisitos EP2 pendientes y EP3. **No se ha ejecutado commit ni push.** El
índice habitual permanece vacío. La validación no acredita una ejecución real
EP3 con Groq ni capturas del dashboard.

## Rama, remoto y procedencia

- Rama local y rama predeterminada remota: `master`.
- Remoto `origin`: `https://github.com/sebacvdo-prog/mesa-ayuda-ti-rag.git`.
- HEAD local, referencia local `origin/master` y `master` consultado en GitHub:
  `8d248c3b9aa90960db13a5de6f9709e91e60637b`, al realizar esta revisión.
- Ningún conflicto de índice, marcador de conflicto ni archivo inicial ausente.
- Se respaldaron los 142 archivos visibles iniciales y el estado Git en
  `.cache/ep3/publicacion-20261127T145010Z/`, fuera de publicación.

La [procedencia](evidencias/ep3/seguridad/procedencia_20261127.json) compara el
estado inicial con la captura previa a EP3 del 26 de noviembre. Había **30 rutas
pendientes de EP2**, incluidas mejoras de recuperación, planificación,
preparación de notas, reintentos 429, pruebas, documentación y cuatro diagramas.
EP3 añadió 40 archivos y modificó diez preexistentes. Cinco rutas comparten ambos
orígenes: `eval/check_ep2_retrieval.py`, `src/ep2/agente.py`, `src/ep2/cli.py`,
`src/ep2/reintentos.py` y `src/retriever.py`.

Publicar únicamente los nuevos archivos EP3 omitiría prerrequisitos funcionales.
Se propone un commit coherente que incluya ambos grupos y explique esa inclusión
en su mensaje. Separarlos requeriría revisar también los cambios dentro de los
cinco archivos compartidos. No se restauró, descartó ni reescribió trabajo previo.

## Archivos previstos

La lista exhaustiva es [ep3_publicacion.paths](ep3_publicacion.paths), con una
ruta relativa por línea. Incluye los archivos nuevos y modificados, sin agregar
el resto del árbol sin cambios:

| Grupo | Contenido |
|---|---|
| Implementación EP3 | `src/ep3/*.py`, `src/dashboard_ep3.py` e integración opcional en EP1/EP2. |
| Evaluación y QA | Aislamiento, regresión, escenarios, evaluación, análisis y gestión EP3 en `eval/`; pruebas EP3 en `tests/`. |
| Prerrequisitos EP2 | Las 30 rutas identificadas en procedencia, incluidas pruebas y diagramas previos. |
| Contratos y documentación | Esquemas v1/v2, guías, arquitectura/métricas, defensa, informe, README e índice de evidencias. |
| Evidencia portable | `docs/evidencias/ep3/`: regresión/JUnit, evaluación/CSV simulados, benchmark, seguridad, procedencia y estados pendientes. |
| Privacidad de publicación | `.gitignore` reforzado y tres logs EP1 con rutas locales sustituidas por marcadores. |

Esta preparación cambió únicamente `.gitignore`, README, el índice de evidencias
y las rutas de tres logs históricos; agregó documentación y extractos
publicables. No modificó código, pruebas, prompts, modelo, cuotas, credenciales,
herramientas, permisos ni confirmación humana. Los originales de los logs están
en el respaldo local; sus cifras históricas no cambiaron.

## Exclusiones y seguridad

| Exclusión | Motivo |
|---|---|
| `.env`, `.env.*` salvo `.env.example` | Credenciales/configuración privada; la plantilla contiene marcadores. |
| `*.key`, `*.pem`, `*.p12`, `*.pfx`, `*.jks` | Claves HMAC y material de autenticación. |
| `data/itsm.db`, `*.db`, `*.sqlite`, `*.sqlite3` y sus auxiliares | Bases operativas, memoria, cachés o telemetría; solo se publican código y extractos permitidos. |
| `storage/`, `.cache/` | FAISS, HMAC, bases, backups, snapshots y evidencia cruda local. |
| `.venv/`, `venv/`, `env/`, cachés Python/pruebas y archivos temporales | Entorno local, artefactos regenerables y posibles rutas personales. |
| Logs `*.log`, backups `*.bak`, temporales | Pueden incluir contexto sensible; los tres `.txt` históricos rastreados se revisaron y sanitizaron explícitamente. |

La [auditoría](evidencias/ep3/seguridad/auditoria_20261127.json) distingue archivos
rastreados, nuevos y objetos históricos. No se detectaron secretos coincidentes
con las credenciales locales ni con los patrones de proveedores revisados. No
había bases operativas, `.env` privado ni claves rastreadas. Se verificaron también
los PNG visualmente y sus metadatos, y los SVG como texto.

El corpus y `data/seed_db.py` son fixtures académicos declarados ficticios en el
código: no se publican registros extraídos de las bases operativas. Los resultados
EP1 ya versionados contienen preguntas/respuestas del dataset sintético, no
transcripciones EP3. Los contratos EP3 no aceptan contenido libre del usuario,
argumentos de herramientas ni excepciones del proveedor.

Las rutas personales de los tres logs ya estaban en el historial publicado.
Sanitizar la versión siguiente no las elimina de commits anteriores; se respeta
la prohibición de reescribir el historial. La búsqueda de secretos cubre el árbol
publicable y los 209 blobs alcanzables desde referencias locales, sin garantizar
objetos remotos no descargados ni una detección universal de cualquier secreto.

## Validación y límites

- **820 aprobadas, 0 fallidas, 0 errores y 0 omitidas**; código de salida 0.
- Duración del arnés: **74,465 s**. Pytest: 73,36 s y ocho avisos
  `LangChainPendingDeprecationWarning` de APIs existentes.
- Cero intentos de red/DNS externa, subprocesos y escrituras funcionales
  bloqueadas; ocho conexiones IPC locales de `socketpair` estándar para AppTest.
- Artefactos protegidos y código sin cambios durante la regresión.
- Dashboard verificado con AppTest sin instanciar agente, con filtros y lectura
  v1/v2, ausencia/vacío de datos y conservación de las bases.
- `pip check`: `No broken requirements found.` No se instalaron dependencias.
- `git diff --check` y revisión del conjunto completo mediante un índice Git
  temporal separado; no se altera el índice habitual ni se crea un commit.

Ver [resumen de regresión](evidencias/ep3/automatizadas/regresion_20261127.json)
y [JUnit portable](evidencias/ep3/automatizadas/pytest_20261127.xml). El
[benchmark del día 26](evidencias/ep3/rendimiento/benchmark_20261126.csv) conserva
sus 30 pares originales; no se recalcularon ni inventaron mediciones para publicar.

Pendientes académicos: ejecución real Groq EP3, capturas reales sanitizadas y
aceptación visual manual. Los resultados offline no acreditan calidad generativa,
costos ni rendimiento del proveedor. Los requisitos usan rangos, sin lock completo;
el inventario de versiones comprobadas acompaña a la regresión. Los avisos de
deprecación de LangChain se conservan como deuda, sin cambiar dependencias durante
esta preparación.

## Comandos propuestos — No ejecutados

Desde la raíz, volver a revisar si el trabajo o el remoto cambian. La siguiente
secuencia crea una rama de entrega; `master` permanece como destino de integración.
El manifiesto limita `git add` al conjunto revisado; no usar `git add .` ni `-f`.

```powershell
git status --short --branch
git remote -v
git ls-remote --symref origin HEAD refs/heads/master
git switch -c codex/ep3-observabilidad
git add --pathspec-from-file=docs/ep3_publicacion.paths
git diff --cached --check
git diff --cached --stat
git diff --cached
git commit -m "feat(ep3): add observability dashboard and offline evaluation" -m "Include pending EP2 prerequisites, sanitized academic evidence and offline regression."
git push -u origin codex/ep3-observabilidad
```

Ejecutar commit y push solamente después de la decisión del responsable de la
entrega. No hay force push, merge, despliegue ni modificación de historial en esta
preparación. Una copia temporal del índice y los hashes del conjunto revisado
quedan en `.cache/ep3/publicacion-20261127T145010Z/` para inspección local.
