---
titulo: "KB-M365-01 · Correo y ofimática: Outlook, Teams, OneDrive y licencias"
fecha_vigencia: 2026-05-05
nivel_acceso: publico_interno
---

# KB-M365-01 · Microsoft 365

Artículo de la base de conocimiento de la Mesa de Ayuda TI de Aconcagua Logística SpA.
Servicio asociado del catálogo: **CAT-M365 · Correo y ofimática**.

> El asistente conversacional entrega el procedimiento y la decisión de escalamiento.
> No ejecuta cambios en buzones, licencias ni sitios de OneDrive.

---

## 1. El correo no sincroniza en el equipo de escritorio

**Síntoma:** Outlook muestra "Trabajando sin conexión", "Intentando conectar" o el
último correo recibido tiene varias horas.

**Prioridad por defecto:** P3 · Media. Sube a P2 si afecta a toda una sucursal.

**Pasos de Nivel 1, en orden:**

1. Verificar el estado del servicio del proveedor antes de tocar el equipo. Si hay una
   incidencia declarada por Microsoft, el ticket se registra como "incidente de
   proveedor", se informa al usuario y no se aplican cambios locales.
2. Confirmar que el equipo tiene conectividad: abrir cualquier sitio corporativo.
   Si no hay red, el caso es de CAT-RED y no de correo.
3. Revisar el indicador de conexión en la barra de estado de Outlook. Si dice "Trabajando
   sin conexión", desactivar ese modo desde la pestaña Enviar y recibir.
4. Cerrar Outlook por completo y volver a abrirlo. Verificar que no quede el proceso
   residente en el administrador de tareas.
5. Comprobar que la cuenta no esté pidiendo autenticación: si aparece la ventana de
   inicio de sesión, el usuario debe completar el segundo factor.
6. Verificar el tamaño del buzón (sección 2). Un buzón al límite deja de recibir y el
   síntoma se confunde con falta de sincronización.
7. Si el problema persiste, revisar el archivo de datos sin conexión: en equipos con
   más de dos años de correo, un OST dañado impide sincronizar. La reconstrucción del
   OST la ejecuta **Nivel 2** porque implica reconfigurar el perfil.

**Escalamiento:** a Nivel 2 si el OST está dañado, si el usuario reporta correos que
desaparecieron, o si el problema afecta a más de tres usuarios de la misma sucursal
(posible incidente masivo, elevar a P1).

---

## 2. Buzón lleno

**Síntoma:** el usuario no puede enviar correo y recibe un aviso de cuota superada, o
los mensajes entrantes rebotan al remitente.

**Cuotas vigentes en Aconcagua Logística:**

| Perfil | Cuota de buzón | Aviso al usuario | Bloqueo de envío | Bloqueo de envío y recepción |
|---|---|---|---|---|
| Estándar (E1) | 50 GB | 45 GB | 49 GB | 50 GB |
| Avanzado (E3) | 100 GB | 90 GB | 98 GB | 100 GB |

**Pasos de Nivel 1:**

1. Consultar el porcentaje de ocupación del buzón en el panel de administración
   (lectura, no requiere privilegios de escritura).
2. Guiar al usuario para vaciar Elementos eliminados y la carpeta Correo no deseado.
3. Guiar la limpieza de adjuntos grandes con la herramienta de limpieza de buzón,
   ordenando por tamaño y trasladando lo relevante a OneDrive.
4. Verificar si hay carpetas compartidas o buzones delegados sincronizando en el mismo
   perfil: suman al archivo local y pueden ser la causa real.
5. Si el usuario necesita conservar todo, solicitar el archivado en línea a **Nivel 2**.

**El aumento de cuota y la activación del archivado en línea requieren privilegios de
administrador: los ejecuta Nivel 2.**

---

## 3. Teams

### 3.1 No inicia o queda en la pantalla de carga

1. Cerrar Teams desde el área de notificación (no basta con la X).
2. Verificar que el equipo tenga hora y fecha correctas: un desfase de reloj rompe la
   autenticación.
3. Cerrar sesión y volver a iniciar, completando el segundo factor.
4. Si sigue igual, borrar la caché local de Teams. Este paso borra los mensajes no
   enviados; se advierte al usuario antes.

### 3.2 No se escucha o no se ve en reuniones

1. Verificar en la configuración de dispositivos de Teams que el micrófono y el
   parlante seleccionados sean los correctos.
2. Revisar los permisos de micrófono y cámara del sistema operativo.
3. Probar la llamada de prueba integrada.
4. En sucursales con enlace de baja capacidad, indicar desactivar el video: la
   Política de Seguridad TI no restringe el video, pero el catálogo de servicios
   prioriza la voz sobre el video en enlaces saturados.

### 3.3 No aparece un colaborador en el directorio de Teams

Normalmente es una cuenta recién creada: la sincronización del directorio tarda hasta
2 horas. Si pasaron más de 4 horas, escalar a Nivel 2.

---

## 4. Licencias

**Asignación por cargo:**

| Cargo | Licencia | Incluye |
|---|---|---|
| Conductor y personal de ruta | E1 | Correo web, Teams, OneDrive 1 TB |
| Administrativo de sucursal | E1 | Correo web, Teams, OneDrive 1 TB |
| Jefaturas y analistas | E3 | Aplicaciones de escritorio, archivado en línea |
| Gerencia | E3 | Aplicaciones de escritorio, archivado en línea |

**Síntomas de falta de licencia:** las aplicaciones de escritorio muestran "Producto
sin licencia"; el usuario puede leer correo en el navegador pero no en Outlook de
escritorio; OneDrive deja de sincronizar.

**Pasos de Nivel 1:**

1. Verificar en el panel si la cuenta tiene licencia asignada y de qué tipo.
2. Si el cargo corresponde a E3 y tiene E1, se solicita el cambio con la aprobación de
   la jefatura; **la asignación la ejecuta Nivel 2**.
3. Si la licencia figura asignada pero la aplicación no la reconoce, pedir al usuario
   cerrar sesión en la aplicación de escritorio y volver a iniciarla.

**Nunca se libera una licencia de un usuario activo para asignarla a otro.**

---

## 5. OneDrive

### 5.1 No sincroniza

1. Revisar el ícono de OneDrive: una nube con una equis indica sesión cerrada; un
   triángulo indica conflicto de archivo.
2. Verificar el espacio libre en el disco local: la sincronización se detiene bajo
   10 GB libres.
3. Revisar rutas o nombres de archivo inválidos (caracteres prohibidos, rutas de más
   de 400 caracteres). Es la causa más común en carpetas de documentación de ruta.
4. Reiniciar el cliente de OneDrive.

### 5.2 Archivo eliminado por error

Los archivos permanecen 30 días en la papelera de reciclaje del usuario y otros 30 en
la papelera de segunda etapa. **La restauración desde la papelera de segunda etapa la
ejecuta Nivel 2.**

---

## 6. Criterios de escalamiento a Nivel 2

- Cualquier cambio de licencia, cuota o archivado en línea.
- Reconstrucción de perfil de Outlook o del archivo OST.
- Restauración de correos o archivos desde papeleras de segunda etapa.
- Sospecha de incidente masivo (más de tres usuarios de la misma sucursal con el mismo
  síntoma en menos de una hora): se eleva a P1 y se avisa al Nivel 2 de inmediato.
- Reglas de reenvío automático que el usuario no reconoce: se trata como incidente de
  seguridad y se escala con la marca `riesgo_identidad`.

**Fuente interna relacionada:** Catálogo de Servicios y SLA (CAT-M365), KB-ACC-01
(sección 4, autenticación) y Política de Seguridad TI (sección 3).
