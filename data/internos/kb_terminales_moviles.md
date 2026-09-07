---
titulo: "KB-MOV-03 · Terminales móviles en ruta: enrolamiento, fallas y pérdida"
fecha_vigencia: 2026-06-15
nivel_acceso: restringido_agentes
---

# KB-MOV-03 · Terminales móviles en ruta

Artículo de la base de conocimiento de la Mesa de Ayuda TI de Aconcagua Logística SpA.
Servicio asociado del catálogo: **CAT-MOV · Terminales móviles en ruta**.
Parque: terminales Android robustecidos, gestionados con Microsoft Intune, usados por
conductores y peonetas para la captura de entregas y firmas.

> El asistente conversacional entrega el procedimiento y la decisión de escalamiento.
> **No ejecuta borrados remotos, no libera equipos y no entrega PIN ni claves de
> desbloqueo.**

---

## 1. Contexto operativo

Un terminal caído en ruta detiene la captura de entregas de esa hoja de ruta completa.
Por eso los incidentes de terminales con el vehículo en ruta se clasifican como
**P2 · Alta** por defecto, y como **P1 · Crítica** cuando afectan a tres o más
vehículos de la misma flota simultáneamente.

Horario crítico: 06:00 a 12:00, ventana de salida del centro de distribución.

---

## 2. Enrolamiento de un terminal nuevo en Intune

**Prerrequisitos:** el equipo debe estar registrado en la CMDB con su número de serie y
asignado a una sucursal; el conductor debe tener cuenta activa y licencia asignada.

1. Encender el equipo y conectarlo a la red Wi-Fi del centro de distribución.
2. Iniciar sesión con la cuenta corporativa del colaborador.
3. Aceptar el registro del dispositivo en la organización cuando el asistente de
   configuración lo solicite.
4. Esperar la aplicación del perfil de cumplimiento: cifrado obligatorio, PIN de 6
   dígitos, bloqueo a los 2 minutos de inactividad.
5. Verificar que la aplicación de ruta se instale automáticamente desde el portal de
   empresa. Si no aparece en 15 minutos, forzar la sincronización desde el portal.
6. Registrar en la CMDB la asignación equipo–colaborador y la fecha.

**Si el equipo aparece como "ya registrado por otro usuario"**, quedó enrolado a nombre
del colaborador anterior. **El retiro del registro previo lo ejecuta Nivel 2.**

---

## 3. Fallas frecuentes en ruta

| Síntoma | Causa habitual | Acción de Nivel 1 |
|---|---|---|
| La aplicación de ruta no abre | Perfil de cumplimiento no aplicado o sesión vencida | Pedir reinicio del equipo y nuevo inicio de sesión |
| No captura firmas | Pantalla sucia o protector dañado; sin espacio de almacenamiento | Verificar espacio libre; si es hardware, reemplazo por equipo de respaldo |
| Sin datos móviles | Zona sin cobertura o SIM desactivada por consumo | Confirmar cobertura; si la SIM está suspendida, escalar a Nivel 2 |
| "Tu dispositivo no cumple las políticas" | PIN eliminado, cifrado desactivado o versión de sistema desactualizada | Guiar la corrección del PIN; si es la versión de sistema, escalar |
| Batería que no dura la jornada | Batería degradada (más de 24 meses de uso) | Registrar en la CMDB y solicitar recambio a Nivel 2 |

**Equipo de respaldo:** cada sucursal mantiene dos terminales de contingencia. El
cambio lo autoriza el jefe de sucursal y se registra en la CMDB en el mismo día.

---

## 4. Pérdida o robo del dispositivo

**Prioridad: P1 · Crítica, sin excepción.** El terminal tiene datos de clientes y una
sesión corporativa activa.

**Pasos inmediatos de Nivel 1 (primeros 15 minutos):**

1. Registrar hora, lugar aproximado y circunstancia (extravío o robo con violencia).
2. Solicitar al conductor que **no** intente recuperar el equipo por su cuenta.
3. Identificar el equipo en la CMDB por número de serie y confirmar a qué colaborador
   está asignado.
4. **Escalar de inmediato a Nivel 2** para el bloqueo remoto del dispositivo y la
   revocación de las sesiones de la cuenta del colaborador.
5. Informar al jefe de sucursal y a Seguridad Operacional.
6. En caso de robo, indicar que la constancia policial la realiza el colaborador con
   apoyo de su jefatura; el número de parte se adjunta al ticket.

### 4.1 Borrado remoto (wipe)

> **Acción exclusiva de Nivel 2.** El borrado remoto es irreversible: elimina la
> configuración y los datos del terminal. Nivel 1 **nunca** lo ejecuta ni lo sugiere
> como paso propio, y el asistente conversacional **no lo ejecuta bajo ninguna
> circunstancia**: solo indica que corresponde escalar.

Criterio de decisión que aplica Nivel 2:

- **Bloqueo remoto** cuando hay expectativa razonable de recuperar el equipo en las
  próximas 24 horas (extravío dentro de instalaciones o en el vehículo).
- **Borrado remoto completo** cuando hay robo, cuando pasaron 24 horas sin recuperación
  o cuando existe sospecha de manipulación del equipo.
- **Retiro selectivo de datos corporativos** cuando el equipo es de propiedad del
  colaborador (casos excepcionales autorizados por Gerencia).

Toda ejecución de borrado queda registrada con quién la autorizó, la hora y el ticket.

---

## 5. Devolución y baja del terminal

1. Verificar el estado físico y registrarlo en el ticket.
2. Solicitar a Nivel 2 el retiro del registro de Intune.
3. Restablecer el equipo a valores de fábrica antes de reasignarlo.
4. Actualizar la CMDB: cambiar el estado a "en bodega" y limpiar la asignación.
5. Si el equipo cumplió su vida útil (36 meses), marcarlo como "dado de baja" y derivar
   a la gestión de residuos electrónicos.

---

## 6. Criterios de escalamiento a Nivel 2

- Pérdida o robo del dispositivo (siempre, y como P1).
- Cualquier acción de bloqueo, borrado remoto o retiro de registro en Intune.
- Terminal enrolado a nombre de otro colaborador.
- Falla de hardware que requiera reemplazo o gestión de garantía.
- SIM suspendida o cambio de plan de datos.
- Tres o más terminales de la misma flota con el mismo síntoma en menos de una hora.

**Fuente interna relacionada:** Catálogo de Servicios y SLA (CAT-MOV), Política de
Seguridad TI (secciones 2 y 5).
