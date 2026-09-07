---
titulo: "KB-RED-02 · Conectividad y VPN corporativa"
fecha_vigencia: 2026-02-10
nivel_acceso: publico_interno
---

# KB-RED-02 · Conectividad y VPN

Artículo de la base de conocimiento de la Mesa de Ayuda TI de Aconcagua Logística SpA.
Servicio asociado del catálogo: **CAT-RED · Conectividad y VPN**.
Cliente VPN corporativo: FortiClient (perfil `Aconcagua-SSLVPN`).

> El asistente conversacional entrega el procedimiento. No modifica configuraciones de
> red, no genera certificados y no reinicia el concentrador VPN.

---

## 1. Verificación previa de red (obligatoria antes de tocar la VPN)

Más de la mitad de los tickets de "no me funciona la VPN" son en realidad problemas del
enlace del usuario. Antes de cualquier paso sobre el cliente VPN, Nivel 1 confirma:

1. **¿Hay Internet sin VPN?** El usuario abre un sitio público. Si no carga, el caso es
   del proveedor de Internet del usuario y no de la VPN.
2. **¿Qué red usa?** Fibra domiciliaria, hotspot del teléfono o red de cliente. Las
   redes de clientes y algunos hoteles bloquean el puerto de la VPN corporativa
   (TCP 10443); en ese caso la alternativa es el hotspot del teléfono.
3. **¿Cambió algo?** Actualización del sistema operativo, antivirus nuevo, cambio de
   router.
4. **¿A cuántos afecta?** Si son varios usuarios de la misma sucursal, es un incidente
   de enlace y se eleva a P1.
5. **Registrar la dirección IP privada que el equipo tiene asignada** (rango
   192.168.x.x o 10.x.x.x) y el nombre del host, para dejar constancia en el ticket.

---

## 2. Conexión remota paso a paso

1. Abrir FortiClient y seleccionar el perfil `Aconcagua-SSLVPN`.
2. Confirmar que el servidor sea `vpn.aconcagualog.cl` y el puerto `10443`.
3. Ingresar el usuario corporativo **sin** el dominio `@aconcagualog.cl`.
4. Ingresar la contraseña del directorio (la misma del correo). El asistente no la
   entrega ni la restablece.
5. Aprobar el segundo factor en la aplicación autenticadora dentro de 60 segundos.
6. Verificar que el ícono quede en verde y que el túnel muestre bytes enviados y
   recibidos.
7. Probar el acceso a un recurso interno (el ERP de transporte) para confirmar que el
   túnel enruta correctamente.

**Horario:** la VPN está disponible 24/7. Las ventanas de mantención del concentrador
son el primer domingo de cada mes entre 02:00 y 05:00.

---

## 3. Errores frecuentes de autenticación

| Código / mensaje | Significado | Acción de Nivel 1 |
|---|---|---|
| `E-45` Credenciales incorrectas | Usuario o contraseña inválidos | Verificar que el usuario no incluya el dominio; guiar el autoservicio de contraseña (KB-ACC-01, sección 4) |
| `E-45` repetido 3 veces | Riesgo de bloqueo de cuenta | Detener los intentos; ver KB-ACC-01, sección 3 |
| `E-13` Permiso denegado | La cuenta existe pero no pertenece al grupo `VPN-Usuarios` | Escalar a Nivel 2: la asignación de grupo requiere privilegios de administrador |
| Segundo factor no llega | Aplicación autenticadora sin conexión o método desactualizado | Verificar datos móviles del teléfono; si el método está desactualizado, escalar a Nivel 2 |
| `E-98` Sesión duplicada | Ya hay una sesión activa del mismo usuario | Cerrar la sesión anterior desde el otro equipo; si no es posible, Nivel 2 la cierra en el concentrador |

**Regla:** tras **tres** intentos fallidos consecutivos, el agente detiene los intentos
para no gatillar el bloqueo por 10 intentos del directorio.

---

## 4. Errores de certificado

| Mensaje | Causa | Acción |
|---|---|---|
| "El certificado del servidor no es de confianza" | El equipo no tiene instalada la CA corporativa | Escalar a Nivel 2 para instalar la CA. La instalación requiere privilegios de administrador |
| "El certificado ha expirado" | Certificado del concentrador vencido, o reloj del equipo desfasado | Verificar primero fecha y hora del equipo; si están correctas, escalar a Nivel 2 como P2 |
| "El nombre del certificado no coincide" | El usuario apuntó a una dirección IP en vez del nombre `vpn.aconcagualog.cl` | Corregir el servidor en el perfil |

> **Nota de vigencia (revisión de febrero de 2026).** El procedimiento anterior a esta
> revisión permitía continuar la conexión aceptando la advertencia de certificado
> cuando el usuario estaba en ruta y necesitaba operar con urgencia. **Esa excepción
> quedó eliminada.** Ninguna advertencia de certificado se acepta: se escala a Nivel 2.
> Si una fuente externa más reciente refuerza o endurece este criterio, prevalece la
> fuente más reciente.

---

## 5. La VPN conecta pero no se accede a los recursos internos

1. Confirmar que el túnel esté en verde y con tráfico.
2. Verificar que el usuario esté usando el nombre interno del recurso y no una IP
   antigua anotada en su cuaderno.
3. Revisar si el equipo tiene otra VPN activa (personal o de un cliente): dos túneles
   simultáneos rompen el enrutamiento. Desconectar la otra VPN.
4. Comprobar que la red local del usuario no use el mismo rango que la red corporativa.
   Si el router domiciliario entrega 192.168.10.x, hay conflicto con la red de casa
   matriz: pedir al usuario cambiar el rango de su router o usar el hotspot del
   teléfono.
5. Si nada de lo anterior aplica, escalar a Nivel 2 con la IP privada del equipo, el
   nombre del host y la hora exacta del intento.

---

## 6. Criterios de escalamiento a Nivel 2

- Cualquier error de certificado.
- Falta de pertenencia al grupo `VPN-Usuarios` (`E-13`).
- Cierre de sesiones en el concentrador.
- Caída que afecte a más de una sucursal o al centro de distribución: se eleva a
  **P1 · Crítica** y se activa el protocolo de incidente mayor del catálogo.
- Cualquier sospecha de que las credenciales del usuario fueron usadas desde una
  ubicación no habitual: se escala con la marca `riesgo_identidad`.

**Fuente interna relacionada:** Catálogo de Servicios y SLA (CAT-RED), KB-ACC-01,
Política de Seguridad TI (sección 4, acceso desde equipos fuera de la red corporativa).
