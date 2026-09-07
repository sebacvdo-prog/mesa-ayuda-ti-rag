# Prompts del Sistema — Justificación y Diseño

## Visión general

El sistema usa tres prompts complementarios, cada uno con una técnica distinta:

| Prompt | Técnica | Problema que resuelve |
|---|---|---|
| **P1 (sistema)** | Rol + restricciones duras + contrato de salida | Que el modelo no invente ni entregue credenciales |
| **P2 (respuesta)** | Few-shot con 2 ejemplos | Que la salida tenga siempre el mismo formato |
| **P3 (triage)** | Chain-of-thought de 5 pasos | Que el triage siga el orden del procedimiento |

Los prompts están versionados como constantes en `src/prompts.py` con sufijo `_V1`. Cuando un prompt cambie, se agrega una constante nueva y se actualiza `PROMPTS_VIGENTES`, de modo que una evaluación vieja siga siendo reproducible.

---

## P1 · Prompt de sistema

**Técnica:** asignación de rol más restricciones duras enumeradas y contrato de salida explícito.

### Por qué así

En un dominio de mesa de ayuda el riesgo no es que el modelo responda poco, es que responda de más:
- Que complete un procedimiento con conocimiento general.
- Que dicte una contraseña o una credencial temporal.
- Que indique un paso administrativo que el agente de Nivel 1 no debe ejecutar.

Las reglas se numeran (8 en total) para poder auditarlas una por una en las pruebas. La respuesta de "sin procedimiento" se fija literal para que la evaluación pueda compararla por igualdad. El bloque de fuente se declara obligatorio porque una respuesta sin cita no es aplicable según la Política de Seguridad TI (sección 7).

### Reglas clave

1. Solo responde desde el CONTEXTO.
2. Si no hay procedimiento: respuesta literal exacta de escalamiento.
3. Nunca entrega credenciales de ningún tipo.
4. Nunca entrega pasos con privilegios de administrador.
5. No ejecuta acciones.
6. Prevalece la fuente más reciente cuando hay contradicción.
7. Filtra por perfil.
8. Cierra siempre con `Fuente: [título · fecha]`.

---

## P2 · Prompt de respuesta (few-shot)

**Técnica:** few-shot con dos ejemplos completos que fijan el formato de salida.

### Por qué dos ejemplos

Describir el formato en prosa no basta; con dos ejemplos el modelo copia la estructura de forma estable:

- **Ejemplo 1** (terminal móvil en ruta): caso resoluble en Nivel 1 con escalamiento condicional. Muestra el flujo completo: diagnóstico probable → pasos numerados → prioridad y tiempo → criterio de escalamiento → fuente.
- **Ejemplo 2** (solicitud de contraseña): caso que debe rechazarse por política. Muestra cómo se responde a un pedido de credenciales sin entregar ningún valor, que es el ataque más probable contra este sistema.

### Formato de salida

Cada respuesta tiene 5 bloques obligatorios:
1. **Diagnóstico probable**
2. **Pasos** (numerados)
3. **Prioridad y tiempo comprometido** (según SLA)
4. **Escalamiento** (sí/no, con criterio)
5. **Fuente** (`[título · fecha]`)

### Variables del template

- `{perfil}`: `agente` o `usuario_final`
- `{contexto}`: fragmentos recuperados del corpus
- `{datos_itsm}`: resultados de las consultas SQL
- `{pregunta}`: consulta del usuario (ya enmascarada)

---

## P3 · Prompt de triage (chain-of-thought)

**Técnica:** chain-of-thought estructurado con cinco pasos fijos, declarado como razonamiento interno.

### Los 5 pasos

1. **Identificar síntoma y categoría.** ¿Qué falla, desde cuándo, a cuántas personas afecta? Asignar categoría del catálogo.
2. **Buscar incidentes similares.** Revisar el ITSM y el contexto en busca de casos equivalentes ya resueltos.
3. **Descartar causas verificadas.** No proponer un paso avanzado si una verificación previa sigue pendiente.
4. **Determinar prioridad y SLA.** Cruzar impacto y urgencia según la matriz del catálogo.
5. **Resolver en N1 o escalar.** Se resuelve solo si todos los pasos están documentados y ninguno requiere privilegios.

### Por qué razonamiento interno

El triage de la mesa tiene un orden que importa. Sin él, el modelo salta a la solución más citada del corpus y se saltea las verificaciones previas — que es exactamente el error que comete un agente nuevo (reinstalar el cliente VPN cuando el usuario no tiene Internet).

Se pide razonamiento interno y no visible porque:
- El agente necesita la indicación accionable, no la deliberación.
- Exponer el borrador invita a que el modelo lo contradiga en la respuesta final.

---

## Prompt del juez (evaluación)

**Técnica:** rúbrica explícita por métrica más salida forzada a JSON.

Un juez sin rúbrica puntúa alto casi todo. Definir qué es 1,0 y qué es 0,0 en cada métrica (fidelidad, relevancia, precisión del contexto), y aclarar cómo tratar la respuesta de escalamiento, es lo que hace comparables las corridas.

Las llaves del JSON de ejemplo van duplicadas (`{{`, `}}`) porque el template se formatea con `str.format`.
