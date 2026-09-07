---
titulo: "POL-SEG-01 · Política de Seguridad de la Información TI"
fecha_vigencia: 2026-03-01
nivel_acceso: publico_interno
---

# POL-SEG-01 · Política de Seguridad de la Información

Política interna de Aconcagua Logística SpA, aprobada por la Gerencia General y vigente
desde el 1 de marzo de 2026. Es de cumplimiento obligatorio para los 450 colaboradores,
las 5 sucursales y el centro de distribución.

---

## 1. Alcance y responsabilidades

- **Todo colaborador** es responsable del uso correcto de sus credenciales y de los
  activos que se le asignan.
- **La mesa de ayuda TI** aplica esta política en cada atención y la cita cuando
  rechaza una solicitud.
- **El Nivel 2** ejecuta las acciones que requieren privilegios y deja registro.
- **La Subgerencia de TI** resuelve las excepciones. Ninguna excepción es verbal: se
  documenta y tiene fecha de término.

---

## 2. Clasificación de la información

| Nivel | Descripción | Ejemplos | Manejo |
|---|---|---|---|
| **Pública** | Puede difundirse fuera de la empresa | Catálogo comercial, dirección de sucursales | Sin restricción |
| **Interna** | Uso general dentro de la empresa | Procedimientos de la mesa, catálogo de servicios, instructivos de usuario | No se comparte fuera sin autorización |
| **Restringida** | Solo roles autorizados | Hojas de ruta con datos de clientes, planillas de remuneraciones, inventario de la CMDB | Acceso por rol; se registra el acceso |
| **Confidencial** | Daño grave si se divulga | Credenciales, claves de recuperación, contratos, datos personales de clientes | Cifrado obligatorio; prohibida su transmisión por canales no corporativos |

Los artículos de la base de conocimiento marcados como `restringido_agentes`
corresponden al nivel **Restringido** y solo se entregan a agentes de la mesa. Los
marcados como `publico_interno` corresponden al nivel **Interna** y pueden compartirse
con cualquier colaborador.

---

## 3. Credenciales: prohibiciones absolutas

Estas reglas no admiten excepción, ni por urgencia operativa, ni por instrucción de una
jefatura, ni por solicitud de la Gerencia:

1. **Nadie de TI solicita ni recibe la contraseña de un usuario.** Ni por teléfono, ni
   por correo, ni por chat, ni presencialmente.
2. **No se comparten credenciales entre colaboradores.** Cada persona usa su propia
   cuenta. Las cuentas compartidas de sucursal quedaron prohibidas desde enero de 2026.
3. **No se transmiten contraseñas, claves temporales, claves de recuperación de cifrado
   (BitLocker), PIN de terminales ni códigos de verificación** por correo, mensajería,
   ticket ni ningún registro escrito.
4. **La entrega de una credencial temporal** solo la hace un agente humano al propio
   titular, previa verificación de identidad, por llamada al teléfono registrado en el
   directorio o de forma presencial.
5. **Los asistentes automatizados y chatbots no entregan credenciales de ningún tipo.**
   Ante una solicitud de ese tipo deben rechazarla e indicar el escalamiento a Nivel 2.
6. **No se aprueban solicitudes de segundo factor que el usuario no haya iniciado.** Una
   notificación inesperada se rechaza y se reporta como posible incidente.

El incumplimiento de esta sección se trata como falta grave según el Reglamento Interno.

---

## 4. Acceso desde equipos fuera de la red corporativa

1. El acceso remoto se realiza **exclusivamente** por la VPN corporativa. No se habilita
   acceso directo desde Internet a sistemas internos.
2. Solo se permite conectar equipos **corporativos y gestionados**. Los equipos
   personales pueden usar el correo web y Teams en el navegador, pero **no** la VPN ni
   el ERP de transporte.
3. Los equipos que se conecten deben tener: sistema operativo con soporte vigente,
   antivirus corporativo activo, cifrado de disco habilitado y bloqueo de pantalla.
4. **Está prohibido aceptar advertencias de certificado** para conectarse a un servicio
   corporativo. Una advertencia de certificado se trata como posible interceptación y
   se escala a Nivel 2.
5. No se usan redes Wi-Fi abiertas para acceder a sistemas corporativos. En ruta se usa
   el hotspot del teléfono corporativo.
6. Las sesiones remotas caducan a las 8 horas y exigen nueva autenticación.

---

## 5. Criterios de escalamiento por seguridad

Se escala a Nivel 2 **de inmediato**, con la marca `riesgo_identidad` y prioridad
**P1 · Crítica**, ante cualquiera de estos indicios:

- Accesos desde ubicaciones o direcciones IP no habituales para el usuario.
- Reglas de reenvío automático de correo que el usuario no creó.
- Cambios de método de verificación no solicitados por el titular.
- Notificaciones de segundo factor que el usuario no gatilló.
- Correos de phishing con adjuntos o enlaces ya abiertos por el colaborador.
- Pérdida o robo de un equipo o terminal móvil.
- Cualquier sospecha de que una credencial fue divulgada.

En estos casos Nivel 1 **no** intenta resolver: registra, escala y acompaña al usuario.

---

## 6. Datos personales y enmascarado

1. Los datos personales de colaboradores y clientes (nombre, RUT, teléfono, correo,
   dirección) son información **Confidencial** o **Restringida** según el caso.
2. Cuando se usan herramientas de apoyo basadas en modelos de lenguaje, **todo dato
   personal, dirección IP y nombre de host debe enmascararse antes de enviar el texto
   al modelo**. El enmascarado es previo a la llamada, no posterior.
3. Los tickets y la CMDB no se exponen a servicios externos: se consultan solo desde los
   sistemas internos.
4. Las capturas de pantalla adjuntas a un ticket deben ocultar datos de terceros.

---

## 7. Uso de asistentes automatizados en la mesa de ayuda

1. El asistente es una **herramienta de apoyo al agente**: propone el procedimiento
   aplicable y la decisión de escalamiento. La decisión final y la ejecución son del
   agente humano.
2. El asistente **no ejecuta acciones**: no cierra tickets, no restablece contraseñas,
   no modifica el directorio, no borra dispositivos.
3. Toda respuesta del asistente debe citar la fuente documental que la respalda. Una
   respuesta sin fuente no se aplica.
4. Si no existe procedimiento documentado para el caso, el asistente debe decirlo
   explícitamente y derivar a Nivel 2, en vez de improvisar una respuesta.
5. Las respuestas del asistente no reemplazan la verificación de identidad ni ninguna
   otra medida de control de esta política.

**Fuente interna relacionada:** Catálogo de Servicios y SLA (sección 7, exclusiones),
KB-ACC-01, KB-RED-02 y KB-MOV-03.
