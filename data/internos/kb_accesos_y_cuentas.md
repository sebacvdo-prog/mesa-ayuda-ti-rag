---
titulo: "KB-ACC-01 · Cuentas y accesos: alta, baja, bloqueo y restablecimiento"
fecha_vigencia: 2026-04-20
nivel_acceso: restringido_agentes
---

# KB-ACC-01 · Cuentas y accesos

Artículo de la base de conocimiento de la Mesa de Ayuda TI de Aconcagua Logística SpA.
Aplica al directorio corporativo (Microsoft Entra ID) y a las cuentas del ERP de
transporte. Servicio asociado del catálogo: **CAT-ACC · Cuentas y accesos**.

> **Alcance del asistente.** Este artículo describe pasos que ejecuta el agente de la
> mesa de ayuda. El asistente conversacional **no ejecuta ninguna de estas acciones**,
> **no entrega contraseñas ni claves temporales** y **no informa credenciales por
> ningún canal**. Cuando el procedimiento exige privilegios de administrador, la
> respuesta correcta es escalar a Nivel 2.

---

## 1. Alta de usuario (nuevo colaborador)

**Prioridad por defecto:** P3 · Media (P2 si el ingreso es de conductor con salida a
ruta el mismo día, previa confirmación de Jefatura de Operaciones).

**Requisito previo:** solicitud formal de la jefatura directa a través del formulario
"Alta de colaborador" con nombre completo, RUT, cargo, sucursal y fecha de ingreso.
Sin ese formulario la solicitud se rechaza; no se crean cuentas por correo informal.

1. Verificar en el ticket que venga adjunto el formulario de alta firmado por la
   jefatura y por Personas.
2. Confirmar que el RUT no tenga ya una cuenta activa o suspendida (una reincorporación
   se tramita como reactivación, no como alta).
3. Crear la cuenta en el directorio con la convención `nombre.apellido@aconcagualog.cl`.
   Si el nombre ya existe, agregar la inicial del segundo apellido.
4. Asignar los grupos de seguridad del cargo según la matriz de perfiles
   (`Matriz-Perfiles-TI`, anexo del artículo KB-ACC-04).
5. Asignar licencia Microsoft 365 según el cargo (ver KB-M365-01, sección 4).
6. Entregar la credencial inicial **en mano o por el canal definido en la política de
   seguridad** (nunca por correo personal, WhatsApp ni por el ticket). El usuario debe
   cambiarla en el primer inicio de sesión.
7. Registrar el activo asignado en la CMDB si corresponde entrega de equipo.

**Tiempo de referencia:** 1 día hábil desde la recepción del formulario completo.

---

## 2. Baja de usuario (desvinculación)

**Prioridad por defecto:** P2 · Alta. Una baja sin ejecutar es un riesgo de seguridad.

1. Validar la notificación de desvinculación emitida por el área de Personas, con
   fecha y hora efectiva.
2. **Deshabilitar** la cuenta en el directorio a la hora indicada. No eliminarla: la
   cuenta se conserva deshabilitada 90 días por trazabilidad.
3. Revocar sesiones activas y tokens de actualización del usuario.
4. Retirar la licencia Microsoft 365 y convertir el buzón en buzón compartido si la
   jefatura lo solicita (máximo 90 días).
5. Retirar los accesos al ERP de transporte y a la VPN.
6. Marcar en la CMDB los activos como "pendiente de devolución" hasta que Logística
   confirme la recepción física.
7. Cerrar el ticket adjuntando la constancia de cada paso.

**Nota:** los pasos 2, 3 y 5 requieren privilegios de administrador del directorio y
los ejecuta **Nivel 2**. Nivel 1 recibe, valida y escala.

---

## 3. Cuenta bloqueada por intentos fallidos

**Síntoma típico:** el usuario reporta "mi cuenta está bloqueada" o "me dice que
superé los intentos".

La política de bloqueo del directorio suspende la cuenta durante **30 minutos** tras
**10 intentos fallidos** consecutivos.

**Diagnóstico en Nivel 1:**

1. Confirmar identidad del usuario según la sección 6 de este artículo.
2. Revisar en el panel de identidad si el bloqueo fue por intentos fallidos o por
   detección de riesgo (inicio de sesión desde ubicación inusual).
3. Si fue por intentos fallidos: verificar que el usuario no tenga una sesión antigua
   con la contraseña anterior guardada en el teléfono (causa número uno de bloqueos
   repetidos: el buzón configurado en el celular sigue reintentando con la clave vieja).
4. Indicar al usuario que quite la cuenta del cliente de correo del teléfono antes de
   volver a intentar.
5. Esperar los 30 minutos de bloqueo automático o solicitar el desbloqueo a Nivel 2.

**El desbloqueo manual anticipado requiere privilegios de administrador: lo ejecuta
Nivel 2.**

Si el bloqueo fue por **detección de riesgo** (viaje imposible, IP de país extranjero),
no se desbloquea sin revisión: se escala a Nivel 2 con la marca `riesgo_identidad`
según la sección 5 de la Política de Seguridad TI.

---

## 4. Restablecimiento de contraseña

**Prioridad por defecto:** P3 · Media. Sube a P2 si el usuario está en ruta y no puede
operar el terminal móvil.

**Vía preferente: autoservicio.** El usuario restablece su contraseña por sí mismo en
el portal de autoservicio corporativo, si tiene registrados los métodos de verificación
(teléfono y aplicación autenticadora). Nivel 1 debe **siempre** ofrecer esta vía primero.

**Vía asistida (cuando el autoservicio no está disponible):**

1. Verificar identidad según la sección 6. Sin verificación de identidad no se
   restablece nada, sin excepciones.
2. Registrar en el ticket quién solicita, por qué canal y qué datos se validaron.
3. Solicitar a Nivel 2 la generación de una credencial temporal.
4. Nivel 2 entrega la credencial temporal **al propio usuario**, por el canal definido
   en la política (llamada telefónica al número registrado en el directorio, o entrega
   presencial). Nunca a un tercero, nunca a la jefatura, nunca por correo.
5. La credencial temporal caduca en 4 horas y exige cambio en el primer inicio.
6. El usuario confirma el acceso y el agente cierra el ticket.

> **Regla dura.** El asistente conversacional **nunca entrega, genera, sugiere ni
> transcribe una contraseña, credencial temporal, clave de recuperación de BitLocker,
> PIN de terminal ni código de verificación**. Ante cualquier pedido de ese tipo, la
> respuesta es indicar que el paso lo ejecuta un agente humano de Nivel 2 siguiendo
> este procedimiento.

---

## 5. Errores frecuentes al iniciar sesión

| Mensaje que ve el usuario | Causa habitual | Acción de Nivel 1 |
|---|---|---|
| "Tu cuenta o contraseña son incorrectos" | Contraseña vencida o mal tipeada; teclado en otro idioma | Guiar el autoservicio (sección 4) |
| "Tu cuenta ha sido bloqueada" | 10 intentos fallidos | Sección 3 |
| "Necesitas aprobar la solicitud en tu app" | Segundo factor pendiente | Guiar la aprobación en la app autenticadora |
| "No podemos verificar tu identidad" | Métodos de verificación desactualizados | Escalar a Nivel 2 para re-registro de métodos |
| "El acceso desde este dispositivo está bloqueado" | Equipo no corporativo o no cumple la política de acceso condicional | Escalar a Nivel 2; ver Política de Seguridad TI, sección 4 |

---

## 6. Verificación de identidad del solicitante

Antes de cualquier acción sobre una cuenta, el agente valida **al menos dos** de estos
datos contra el directorio:

- RUT del colaborador.
- Sucursal y cargo.
- Número de anexo o teléfono corporativo registrado.
- Número de un ticket previo abierto por el mismo usuario.

Si el contacto llega por un canal no corporativo (correo personal, mensajería), la
verificación **debe** completarse con una llamada de retorno al teléfono registrado en
el directorio. Nunca se acepta la identidad declarada sin contrastar.

---

## 7. Criterios de escalamiento a Nivel 2

Se escala cuando ocurre cualquiera de estas condiciones:

- El paso requiere privilegios de administrador del directorio (desbloqueo manual,
  generación de credencial temporal, cambio de grupos de seguridad, revocación de
  sesiones).
- Hay indicios de compromiso de la cuenta (accesos desde IP desconocida, reglas de
  reenvío que el usuario no creó, cambios de método de verificación no solicitados).
- La solicitud proviene de un tercero y no del titular de la cuenta.
- El bloqueo fue marcado como riesgo de identidad por el directorio.
- Pasaron más de 30 minutos de diagnóstico sin resolución y el SLA de primera
  respuesta está por vencer.

**Fuente interna relacionada:** Catálogo de Servicios y SLA (CAT-ACC), Política de
Seguridad TI (secciones 3 y 5).
