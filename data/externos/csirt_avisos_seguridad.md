---
titulo: "EXT-CSIRT-03 · Avisos de seguridad vigentes (resumen)"
fecha_vigencia: 2026-07-28
nivel_acceso: publico_interno
fuente_url: https://www.csirt.gob.cl/alertas/
tipo_fuente: alerta_organismo_publico
---

# EXT-CSIRT-03 · Avisos de seguridad vigentes

**Origen:** alertas públicas del CSIRT de Gobierno de Chile
(https://www.csirt.gob.cl/alertas/). **Resumen elaborado por la Subgerencia de TI de
Aconcagua Logística**; no reproduce el texto original de las alertas.

**Regla de precedencia.** Cuando un aviso de este documento entra en tensión con un
procedimiento interno más antiguo, **prevalece el criterio más reciente y más
restrictivo**, y el caso se escala a Nivel 2 para confirmar. Los avisos no habilitan al
agente a ejecutar acciones nuevas: habilitan a **detenerse y escalar**.

---

## Aviso 1 · Campaña de fatiga de segundo factor (MFA fatigue)

- **Fecha del aviso:** 12 de junio de 2026.
- **Estado:** vigente.

**Qué está ocurriendo.** Atacantes que ya obtuvieron la contraseña de una víctima envían
decenas de solicitudes de aprobación de segundo factor seguidas, apostando a que la
persona apruebe una por cansancio o por confusión. En varias organizaciones chilenas la
aprobación llegó de madrugada.

**Indicadores.** Notificaciones de aprobación que el usuario no inició; varias
notificaciones seguidas; llamadas de alguien que dice ser de soporte pidiendo "aceptar
la notificación para terminar una configuración".

**Recomendaciones del aviso.** Rechazar toda solicitud no iniciada por el propio
usuario; reportarla de inmediato; forzar el cambio de la contraseña porque, si llegan
solicitudes, la contraseña ya está comprometida; preferir métodos con coincidencia de
número en lugar de la aprobación simple.

**Tensión con el procedimiento interno.** El artículo KB-ACC-01 trata las solicitudes de
segundo factor pendientes como un paso normal de la atención ("guiar la aprobación en la
app autenticadora"). **Con este aviso vigente, ese paso no aplica** cuando el usuario
declara que no inició la solicitud: en ese caso corresponde escalamiento inmediato a
Nivel 2 con la marca `riesgo_identidad`, según la sección 5 de la Política de Seguridad
TI, y no guiar ninguna aprobación.

---

## Aviso 2 · Interceptación en redes no confiables y advertencias de certificado

- **Fecha del aviso:** 3 de julio de 2026.
- **Estado:** vigente.

**Qué está ocurriendo.** Se detectaron equipos intermedios en redes Wi-Fi de acceso
público (hoteles, terminales de buses, cafeterías) que presentan certificados propios
para interceptar sesiones cifradas hacia portales corporativos, incluidos portales de
VPN.

**Indicadores.** Advertencias de certificado no confiable o de nombre no coincidente que
aparecen solo en una red determinada y no en otras; portales de acceso que exigen
instalar un certificado para "mejorar la navegación".

**Recomendaciones del aviso.** No aceptar nunca una advertencia de certificado para
continuar; no instalar certificados solicitados por una red; usar el hotspot del
teléfono corporativo cuando el portal presente advertencias; reportar el hecho al equipo
de seguridad con la fecha, hora y ubicación.

**Tensión con el procedimiento interno.** Las versiones de KB-RED-02 anteriores a
febrero de 2026 admitían una excepción para el personal en ruta: continuar aceptando la
advertencia si había urgencia operativa. **Esa excepción está eliminada y este aviso la
contradice de forma explícita.** Ante cualquier advertencia de certificado: no conectar,
registrar la red donde ocurrió y escalar a Nivel 2 como P2; si la red es pública, tratar
la credencial del usuario como potencialmente expuesta.

---

## Aviso 3 · Suplantación de mesas de ayuda internas

- **Fecha del aviso:** 21 de julio de 2026.
- **Estado:** vigente.

**Qué está ocurriendo.** Llamadas y mensajes en que el atacante se hace pasar por la mesa
de ayuda interna de la propia organización y pide la contraseña, el código de
verificación o que la víctima instale una herramienta de asistencia remota. En el sentido
inverso, también hay atacantes que llaman **a la mesa de ayuda** haciéndose pasar por un
colaborador para pedir el restablecimiento de una contraseña o el cambio del método de
verificación.

**Indicadores.** Presión por urgencia ("el gerente lo necesita ahora"); solicitud de
restablecimiento por un canal no corporativo; petición de cambiar el teléfono de
verificación junto con el restablecimiento; negativa del solicitante a la llamada de
retorno al número registrado.

**Recomendaciones del aviso.** Verificar identidad con al menos dos datos contrastables
contra el directorio; devolver la llamada al número registrado antes de actuar; no
combinar en una misma atención el restablecimiento de contraseña con el cambio de método
de verificación; registrar y reportar todo intento.

**Relación con el procedimiento interno.** Refuerza, sin contradecirla, la sección 6 de
KB-ACC-01 (verificación de identidad) y la sección 3 de la Política de Seguridad TI
(prohibición de entregar credenciales). Añade un criterio que la norma interna no tenía
escrito: **no ejecutar en la misma atención el restablecimiento de contraseña y el
cambio del método de verificación**; si ambos se piden juntos, escalar a Nivel 2.

---

## Cómo cita la mesa de ayuda estos avisos

Al aplicar cualquiera de estos criterios, el agente cita este documento con su fecha y
el número de aviso, e indica que la fuente es externa (CSIRT) y más reciente que el
procedimiento interno correspondiente.
