# EP2 ISY0101 — matriz de trazabilidad IE1–IE10

Revisión documental: 26 de octubre de 2026. Fuente de requisitos: pauta oficial
*Evaluación Parcial N°2. Encargo con Presentación: Desarrollo de un Agente
Funcional*, versión estudiante, `EP2_ISY0101_estudiante.pdf`, ocho páginas.
El original fue proporcionado fuera del repositorio y no se copia aquí.

Los indicadores se encuentran en las páginas 5–8. Cada uno pondera 10 %:
IE1–IE6 corresponden al encargo (60 %) e IE7–IE10 a la presentación (40 %).
Esta matriz no asigna notas, porcentajes de logro ni asegura cumplimiento total.
Relaciona requisitos con implementación y evidencias existentes; no constituye
una ejecución nueva, una conclusión académica ni una justificación del equipo.

## Catálogo de evidencias

| Referencia | Fuente | Naturaleza y alcance |
|---|---|---|
| E1 | [Integración real de herramientas](evidencias/ep2_integracion_real.md) | 15 de octubre de 2026: cuatro casos aprobados y seis herramientas ejercitadas con Groq, ITSM y FAISS locales. Nota propuesta, sin confirmación ni escritura de negocio. |
| E2 | [Continuidad real de memoria](evidencias/ep2_memoria_real.md) | 15 de octubre de 2026: once comprobaciones entre dos procesos y una reapertura real de CLI. El aislamiento por usuario/sesión/perfil tiene pruebas automatizadas. |
| E3 | [Cierre técnico de Etapa 4](evidencias/ep2_etapa4_cierre_tecnico.md) | 22 de octubre de 2026: 15/15 verificaciones en una ejecución, tres procesos, diez HTTP 200 y 18.137 tokens informados. Propuesta pospuesta, memoria actualizada y cero notas/auditorías de negocio; ITSM intacto. |
| E4 | [Suite documentada en el cierre](evidencias/ep2_etapa4_cierre_tecnico.md#revalidación-local-para-el-commit-de-cierre) | 584 pruebas automatizadas del conjunto del proyecto, con red bloqueada. Modelos/HTTP simulados y bases temporales; no son llamadas reales ni una medición de cobertura total. |
| E5 | [Calibración de embeddings locales](evidencias/calibracion_embeddings_locales.md) | Hugging Face/FAISS sin Groq ni LLM juez: 11/19 aciertos de fuente@4; 10/19 al excluir cada consulta de su calibración. No mide fidelidad de respuestas. |
| E6 | [Procedencia de la evaluación histórica EP1](evidencias/README.md#procedencia-de-las-métricas-históricas-ep1) | Corrida de cinco casos, fidelidad 0,360. La afirmación 0,880/diez casos no está verificada; no representa resultados actuales de EP2. |

La [evidencia histórica del plan](evidencias/ep2_plan_real.md) conserva intentos
parciales anteriores. No se suman fases de esos intentos para construir el 15/15.
Los reportes de ejecución bajo `.cache/` permanecen ignorados; las evidencias
versionadas E1–E3 identifican sus fuentes y huellas sin publicar bases ni secretos.

## Matriz por indicador

Los nombres de pruebas son referencias a funciones existentes, no afirmaciones de
que se hayan ejecutado durante esta actualización. Las evidencias reales utilizan
datos organizacionales ficticios y servicios locales; solo el proveedor Groq es
real. Ninguna prueba funcional sustituye el informe o el desempeño oral.

| Indicador de la pauta, resumido | Archivos y funciones | Pruebas y evidencias existentes | Límite o tarea pendiente |
|---|---|---|---|
| **IE1. Configurar herramientas que ejecuten funciones específicas con autonomía.** P. 5. | [agente.py](../src/ep2/agente.py): `AgenteEP2._crear_herramientas()`, `_validar_decision()` y `_ejecutar()`; [herramientas.py](../src/ep2/herramientas.py): cinco herramientas de consulta/triage y `preparar_nota()`. | [test_ep2_agente.py](../tests/test_ep2_agente.py): `test_registro_contiene_exactamente_seis_herramientas_sin_autorizacion`, `test_ciclo_selecciona_ticket_y_sla_segun_observaciones` y `test_confirmacion_no_es_herramienta_invocable_por_modelo`. E1, E3 y E4. | El LLM propone la nota; la API humana confirma. Las escrituras confirmadas se probaron automáticamente en SQLite temporal, no en las integrales con Groq. |
| **IE2. Integrar frameworks adecuados, con escalabilidad y compatibilidad técnica.** P. 6. | [agente.py](../src/ep2/agente.py): `create_tool_calling_agent`, `AgentExecutor`, `_ModeloPlanificado`; [configuracion.py](../src/ep2/configuracion.py): `crear_llm_ep2()`; [requirements.txt](../requirements.txt). | [test_ep2_agente.py](../tests/test_ep2_agente.py): `test_fabrica_ep2_usa_misma_clave_y_deja_modelo_ep1`. E1 registra versiones y compatibilidad real; E3 demuestra integración del flujo. | No hay medición de escalabilidad bajo carga ni instalación nueva verificada en esta revisión. La compatibilidad observada corresponde al entorno registrado; los rangos de dependencias no bloquean todo el entorno. |
| **IE3. Configurar memoria de contenido para continuidad en flujos prolongados.** P. 6. | [memoria.py](../src/ep2/memoria.py): `MemoriaEP2.recuperar()`, `registrar_turno()`, `_incorporar()` y `_guardar()`; [almacenamiento.py](../src/ep2/almacenamiento.py). | [test_ep2_memoria.py](../tests/test_ep2_memoria.py): `test_reabrir_agente_y_sqlite_recupera_ticket_sin_repetir_identificador`, `test_aislamiento_por_usuario_sesion_y_perfil` y `test_actualizaciones_concurrentes_se_fusionan_sin_perder_hechos`. E2–E4. | Ventana, hechos y retención son acotados; no hay memoria ilimitada ni autorización restaurada. Las ejecuciones reales documentadas cubren dos turnos o tres fases, no todos los flujos prolongados posibles. |
| **IE4. Configurar recuperación de contexto semántico que sostenga la continuidad.** P. 6. | [retriever.py](../src/retriever.py): `RecuperadorVectorial.buscar()`; [herramientas.py](../src/ep2/herramientas.py): `buscar_procedimiento()`; [contexto.py](../src/ep2/contexto.py): `proyectar_contexto()` y `_antecedente_tecnico()`. | [test_ep2_agente.py](../tests/test_ep2_agente.py): `test_rag_integra_filtros_existentes_y_enmascara_documentos`; [test_ep2_contexto.py](../tests/test_ep2_contexto.py): `test_replanificacion_conserva_tema_fuentes_nota_y_confirmacion`. E1, E3 y E5. | La calibración obtiene 11/19 y 10/19, con un solo caso sin fuente. Recuperar el archivo esperado no garantiza la relevancia de cada fragmento ni la fidelidad de cada respuesta. |
| **IE5. Diseñar planificación que secuencie actividades según prioridades.** P. 6. | [planificacion.py](../src/ep2/planificacion.py): `Planificador`, `disponibles()`, `preparar()`, `observar()` y `_replantear_impacto()`; [contratos.py](../src/ep2/contratos.py): `PlanEjecucion.validar_grafo()`. | [test_ep2_planificacion.py](../tests/test_ep2_planificacion.py): `test_replanifica_impacto_reabre_verificaciones_y_distingue_prioridades`, `test_dependencias_impiden_ejecutar_sla_antes_de_ticket` y `test_prioridad_impide_tarea_menos_urgente_aunque_este_disponible`. E3 y E4. | El servidor construye/adapta planes con reglas acotadas y Groq selecciona entre herramientas elegibles. Un reporte no verifica impacto ni cambia la prioridad del ITSM. |
| **IE6. Elaborar informe técnico con diagramas, flujos y respaldo documental.** P. 7. | [arquitectura EP2](arquitectura.md#arquitectura-ep2), [Etapas 1](ep2_etapa1.md), [2](ep2_etapa2.md), [3](ep2_etapa3.md), [4](ep2_etapa4.md) y [bocetos EP2](bocetos/ep2.md). | E1–E6 aportan hechos y límites para el informe; no existe una prueba de software que acredite este entregable. | Falta el informe Word/PDF de máximo cinco páginas. Los estudiantes deben elaborar sus justificaciones, conclusiones y reflexiones personales conforme a la p. 4. |
| **IE7. Demostrar con ejemplos decisiones adaptativas ante condiciones del entorno.** P. 7. | [cli.py](../src/ep2/cli.py): `mostrar_trazabilidad()`; [check_ep2_plan.py](../eval/check_ep2_plan.py): `paso_real()` y `verificaciones()`; [guion de demo](bocetos/ep2.md#guion-de-demo-sin-escrituras-de-negocio). | [test_check_ep2_plan.py](../tests/test_check_ep2_plan.py): `test_instrumentacion_cli_real_posponer_memoria_y_diez_peticiones_simuladas`; [test_ep2_planificacion.py](../tests/test_ep2_planificacion.py): `test_posponer_en_cli_conserva_pendiente_sin_confirmar`. E1 y E3. | Preparar ejemplos claros de consulta, cambio de impacto y recuperación, más la demo en vivo exigida. Los tests simulados y un video no sustituyen la demostración presencial. |
| **IE8. Elaborar diagrama de orquestación y README en GitHub con la arquitectura del agente.** P. 7. | [README](../README.md), [diagrama EP2](arquitectura.md#arquitectura-ep2) y [flujo resumido de Etapa 4](ep2_etapa4.md#arquitectura-y-ejecución). Los comandos corresponden a `src.ep2.cli` y `eval.check_ep2_*`. | Revisión estática de enlaces, módulos y argumentos; E1–E3 documentan ejecuciones históricas. No sustituye instalar desde cero. | Revisar estos cambios antes de publicar y comprobar posteriormente que el evaluador tenga acceso al repositorio y a la revisión entregada.  |
| **IE9. Justificar componentes y su alineación con los requisitos del flujo.** P. 7. | Fuentes para consultar: [pipeline.md](pipeline.md), [Etapa 2](ep2_etapa2.md), [Etapa 4](ep2_etapa4.md), módulos de agente, memoria, recuperación y almacenamiento. | E1–E6, sus configuraciones y límites sirven de respaldo factual. No hay prueba automatizada que sustituya la argumentación propia. | El equipo debe redactar y defender la justificación de sus componentes y completar referencias APA. Esta matriz no formula esa justificación. |
| **IE10. Usar lenguaje técnico y argumentar respuestas con evidencias o ejemplos.** P. 8. | [Índice de evidencias](evidencias/README.md), diagramas, bocetos y funciones referenciadas en esta matriz. | E1–E6 son fuentes para las respuestas. El desempeño oral no se acredita por código o por la cantidad de pruebas. | Ensayar la exposición y diez minutos de preguntas, con participación equitativa y diferenciando evidencia automatizada, proveedor real e información no demostrada. |

## Pendientes formales y de autoría

Según las páginas 3–4 de la pauta:

- Informe Word/PDF de máximo cinco páginas, con diagramas y referencias APA.
- Repositorio con código, README, bocetos y evidencia de pruebas; entrega del
  informe y enlace por AVA y correo del docente en las fechas del curso.
- Presentación con apoyo visual: diez minutos de exposición, diez de preguntas,
  demo en vivo y participación equitativa de ambos integrantes.
- Declaración de herramientas de IA utilizadas y cómo se aplicaron; revisión y
  validación del contenido por los estudiantes.
- Justificaciones técnicas, conclusiones y reflexiones individuales redactadas
  por los estudiantes sin IA. Cada integrante debe incluir su reflexión personal
  en la sección de conclusiones. Este archivo no las redacta ni las anticipa.

Los límites documentados de escalabilidad, recuperación y calidad semántica deben
acompañar cualquier afirmación sobre resultados. La identidad de la CLI es local,
sin autenticación empresarial. El HTTP 400 no se reprodujo en la integral de
cierre, pero su causa histórica no quedó demostrada. La aceptación técnica de
Etapa 4 no acredita por sí sola todos los entregables académicos de Etapa 5.
