# Resultados de evaluación · Asistente RAG Mesa de Ayuda TI

- **Fecha de la corrida:** 2026-09-07T01:38:33
- **Duración:** 176.6 s
- **Dataset:** Dataset de evaluación · Asistente RAG Mesa de Ayuda TI v1.0.0
- **Perfil:** agente
- **Casos evaluados:** 5

## Configuración de la corrida

| Parámetro | Valor |
|---|---|
| modelo_chat | `openai/gpt-oss-120b` |
| modelo_embeddings | `models/gemini-embedding-001` |
| dimension_embeddings | `768` |
| chunk_size | `900` |
| chunk_overlap | `150` |
| top_k | `4` |
| umbral_similitud | `0.72` |
| temperatura | `0.1` |
| temperatura_juez | `0.0` |
| version_prompts | `1.0.0` |

## Promedios globales

| Métrica | Promedio |
|---|---|
| Fidelidad | 0.360 |
| Relevancia de la respuesta | 0.940 |
| Precisión del contexto | 0.990 |

- **Acierto de fuente** (métrica objetiva, sin juez): 5/5 (1.000)
- **Respuestas con escalamiento a Nivel 2:** 0
- **Fallos de formato del juez:** 0

## Promedios por categoría

| Categoría | Casos | Fidelidad | Relevancia | Precisión de contexto |
|---|---|---|---|---|
| procedimiento_kb | 5 | 0.360 | 0.940 | 0.990 |

## Detalle por pregunta

| ID | Categoría | Fid. | Rel. | Prec. | Fuente esperada | ¿Recuperada? | Escala |
|---|---|---|---|---|---|---|---|
| KB-01 | procedimiento_kb | 0.000 | 1.000 | 1.000 | `kb_accesos_y_cuentas.md` | sí | no |
| KB-02 | procedimiento_kb | 0.200 | 0.900 | 0.950 | `kb_microsoft365.md` | sí | no |
| KB-03 | procedimiento_kb | 0.400 | 0.900 | 1.000 | `kb_conectividad_vpn.md` | sí | no |
| KB-04 | procedimiento_kb | 0.200 | 0.900 | 1.000 | `kb_conectividad_vpn.md` | sí | no |
| KB-05 | procedimiento_kb | 1.000 | 1.000 | 1.000 | `kb_terminales_moviles.md` | sí | no |

## Justificaciones del juez

- **KB-01**: Incluye datos de prioridad y tiempos no presentes en el contexto
- **KB-02**: Incluye datos de SLA no presentes en el contexto, aunque sigue el formato y usa fragmentos pertinentes
- **KB-03**: Incluye pasos correctos del contexto pero añade prioridad, tiempos y escalamiento no documentados
- **KB-04**: El diagnóstico y escalado son correctos, pero añade pasos y tiempos no respaldados por el contexto
- **KB-05**: Respuesta totalmente respaldada por los fragmentos y cubre diagnóstico, pasos, prioridad, escalamiento y fuente

---

Detalle completo (respuestas íntegras incluidas): `evaluacion-20260907-013833.json`.
