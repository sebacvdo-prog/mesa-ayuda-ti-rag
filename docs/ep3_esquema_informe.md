# EP3 — Esquema de informe, máximo cinco páginas

Estructura para que los estudiantes elaboren su informe. No incluye conclusiones
personales, reflexiones ni justificaciones que les corresponda redactar. Revisar
la pauta oficial antes de diagramar; no se presume una rúbrica no proporcionada.
El máximo incluye referencias y declaración de IA salvo indicación distinta de la pauta.

| Página | Contenido a elaborar | Evidencia y visual sugerido |
|---|---|---|
| 1 | Problema, alcance de EP3, conservación EP1/EP2 y arquitectura. | Diagrama simplificado de ep3_arquitectura_metricas.md; estado Git y entorno registrados. |
| 2 | Instrumentación, contrato v1/v2, privacidad, HMAC, confirmación y límites de seguridad. | Tabla de cinco métricas con fuente/unidad/denominador; prueba de HMAC y migración. |
| 3 | Método de evaluación y resultados controlados. Separar objetivo documental, hechos e invariantes. | evaluaciones.csv; tabla con muestras/método/origen. Aclarar LLM y vectores simulados. |
| 4 | Dashboard, trazas y rendimiento. | Captura auténtica del origen seleccionado; benchmark.csv y gráfico pareado, n visible. |
| 5 | Hallazgos, límites, pendientes y análisis redactado por estudiantes; referencias y declaración de IA. | Matriz de hallazgos con trace_id/evento_id; comandos pendientes y rutas relativas de evidencia. |

## Preguntas que debe responder el equipo

- ¿Qué evidencia permite afirmar que EP1/EP2 conservaron su comportamiento y qué
  queda fuera del alcance de los tests controlados?
- ¿Por qué una similitud FAISS, un acierto documental y una exactitud de hechos
  responden preguntas diferentes?
- ¿Qué parte del benchmark se cronometró y cómo influyen calentamiento, orden,
  procesos en segundo plano y ausencia de latencia de red?
- ¿Qué se pierde cuando falla el escritor y por qué la auditoría funcional no usa
  el mismo mecanismo de entrega con pérdidas?
- ¿Qué resultados permiten o impiden concluir algo sobre Groq o usuarios reales?
- ¿Cómo se relacionan los hallazgos con cambios futuros, costos, riesgos y verificación?

## Capturas auténticas del dashboard

1. Ejecutar la evaluación offline en una carpeta nueva y abrir el dashboard con
   esa base. Verificar el aviso **SIMULACIÓN OFFLINE** antes de capturar.
2. Capturar resumen con P50/P95 y número de muestras; no ocultar el origen.
3. Elegir una traza de reintento: capturar error, espera y resultado definitivo.
4. Filtrar nota/POSPONER y mostrar estado pendiente sin exponer contenido privado.
5. Capturar calidad con método y muestras. Separar cualquier ejecución real futura.
6. Guardar la captura original, fecha, ruta de la base, filtros y comando que la
   produjo. No editar valores, usar imágenes de diseño ni fabricar capturas.

Esta implementación verifica Streamlit con AppTest; **no incluye capturas GUI**.
Las capturas y la selección del material para las cinco páginas corresponden al
equipo. Los CSV/JSON permiten construir gráficos propios sin inventar datos.
