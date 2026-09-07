---
titulo: "EXT-MS-01 · Resumen de la documentación de soporte de Microsoft 365"
fecha_vigencia: 2026-04-30
nivel_acceso: publico_interno
fuente_url: https://learn.microsoft.com/es-es/microsoft-365/troubleshoot/
tipo_fuente: documentacion_proveedor
---

# EXT-MS-01 · Microsoft 365 · Resumen de documentación del proveedor

**Origen:** documentación pública de soporte de Microsoft 365
(https://learn.microsoft.com/es-es/microsoft-365/troubleshoot/) y el panel de estado del
servicio. **Resumen elaborado por la Subgerencia de TI de Aconcagua Logística**; no es
una transcripción del texto original.

**Cómo usar este documento:** sirve para entender la causa técnica que describe el
proveedor. El procedimiento que aplica el agente es siempre el del artículo interno
KB-M365-01; ante discrepancia, manda la norma interna, salvo que este documento sea más
reciente y endurezca un criterio de seguridad.

---

## 1. Errores de sincronización de correo

El proveedor agrupa las fallas de sincronización de Outlook en cuatro familias:

1. **Problema de conectividad o de red.** El cliente no alcanza los servicios en la
   nube. Se manifiesta como "Desconectado" o "Intentando conectar". El proveedor
   recomienda descartar primero la red y los servidores proxy antes de tocar el perfil.
2. **Problema de autenticación.** El token de acceso venció o el segundo factor quedó
   pendiente. Aparecen ventanas de inicio de sesión repetidas. El proveedor indica
   cerrar sesión en las aplicaciones de Office y volver a autenticarse.
3. **Archivo de datos local dañado.** El archivo de caché sin conexión (OST) se corrompe
   por cierres abruptos o discos con errores. La recomendación del proveedor es
   reconstruir el archivo permitiendo que el cliente lo descargue de nuevo; el correo no
   se pierde porque el original está en el servidor.
4. **Buzón que superó su cuota.** Al alcanzar el límite de almacenamiento, el buzón deja
   de recibir y de enviar. El síntoma se confunde con una falla de sincronización.

El proveedor insiste en un punto que la mesa suele saltarse: **revisar primero el estado
del servicio**. Si hay una incidencia declarada en el panel de estado, ningún cambio en
el equipo del usuario la resuelve.

### Códigos que el usuario suele reportar

| Código o texto | Significado según el proveedor |
|---|---|
| `0x8004010F` | No se encuentra el archivo de datos de Outlook o el perfil está dañado |
| `0x800CCC0E` | Fallo de conexión con el servidor; típicamente red o puerto bloqueado |
| "Necesitamos actualizar la contraseña de la cuenta" | Credencial almacenada obsoleta tras un cambio de contraseña |
| "Su buzón está lleno" | Cuota superada |

---

## 2. Licenciamiento

- Una licencia se asigna **a un usuario**, no a un equipo. El mismo usuario puede
  activar las aplicaciones de escritorio en hasta cinco equipos.
- Los planes de tipo **E1** están pensados para trabajo en navegador: incluyen correo
  web, Teams y almacenamiento en la nube, pero **no** las aplicaciones de escritorio.
- Los planes de tipo **E3** agregan las aplicaciones de escritorio, mayor cuota de buzón
  y archivado en línea.
- Al quitar una licencia, los datos del usuario permanecen accesibles durante un período
  de gracia de **30 días**; después el proveedor los elimina.
- El mensaje "Producto sin licencia" se resuelve confirmando que la cuenta tenga la
  licencia correcta y forzando un nuevo inicio de sesión en la aplicación.

---

## 3. OneDrive y Teams

- La sincronización de OneDrive falla con **rutas de más de 400 caracteres** o con
  caracteres no admitidos en los nombres de archivo. El proveedor entrega la lista de
  caracteres prohibidos y sugiere renombrar antes que mover.
- Los archivos eliminados pasan por dos papeleras (usuario y colección de sitios), con
  **30 días** de retención en cada una.
- Teams mantiene una caché local; el proveedor documenta su limpieza como paso estándar
  para fallas de inicio, advirtiendo que se pierden los borradores no enviados.
- Los problemas de audio y video se atribuyen mayoritariamente a la selección de
  dispositivo y a los permisos del sistema operativo, no al servicio.

---

## 4. Lo que esta documentación **no** cubre

- Las cuotas internas, los perfiles de licencia por cargo y los tiempos comprometidos de
  Aconcagua Logística: eso está en KB-M365-01 y en el catálogo de servicios.
- Quién está autorizado a ejecutar cada paso. La documentación del proveedor describe
  acciones administrativas sin distinguir niveles; en Aconcagua Logística esa separación
  la define la Política de Seguridad TI y solo Nivel 2 ejecuta cambios administrativos.
