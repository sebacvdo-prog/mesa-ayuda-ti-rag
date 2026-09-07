---
titulo: "EXT-FTNT-02 · Códigos de error del cliente VPN FortiClient (resumen)"
fecha_vigencia: 2026-05-22
nivel_acceso: publico_interno
fuente_url: https://docs.fortinet.com/product/forticlient/
tipo_fuente: documentacion_proveedor
---

# EXT-FTNT-02 · FortiClient · Resumen de códigos de error

**Origen:** documentación pública de FortiClient y notas de la base de conocimiento del
fabricante (https://docs.fortinet.com/product/forticlient/). **Resumen elaborado por la
Subgerencia de TI de Aconcagua Logística**; no reproduce el texto original.

**Equivalencias internas.** El artículo KB-RED-02 usa etiquetas propias (`E-45`, `E-13`,
`E-98`) para los casos más frecuentes en Aconcagua Logística. Este documento explica el
código que muestra el cliente y a qué etiqueta interna corresponde.

---

## 1. Tabla de códigos habituales

| Código del cliente | Qué significa | Etiqueta interna | Dónde está la causa |
|---|---|---|---|
| `-5` | No se pudo establecer la conexión; el servidor no responde | — | Red del usuario, DNS, o puerto 10443 bloqueado por la red donde está conectado |
| `-7200` | Credenciales incorrectas o configuración del túnel equivocada | `E-45` | Usuario, contraseña o nombre del portal mal ingresados |
| `-14` | El usuario no tiene permiso sobre el portal solicitado | `E-13` | Pertenencia a grupos en el servidor; se corrige del lado del concentrador |
| `-455` | Sesión ya establecida para el mismo usuario | `E-98` | Otra sesión abierta en otro equipo |
| `-12` | Error de negociación del túnel | — | Versión del cliente incompatible con el servidor |
| `-20199` | El servidor cerró la conexión durante la autenticación | — | Segundo factor no completado dentro del tiempo, o política del servidor |

**Punto que el fabricante repite:** el código `-5` casi nunca es un problema del cliente
VPN. Indica que el cliente no llegó al servidor, así que se diagnostica como problema de
red antes de reinstalar nada.

---

## 2. Errores de certificado

El cliente valida el certificado del portal contra las autoridades certificadoras del
equipo. Los tres mensajes documentados son:

1. **Certificado no confiable.** La autoridad certificadora que firmó el certificado del
   portal no está en el almacén del equipo. Ocurre con certificados internos en equipos
   recién instalados.
2. **Certificado expirado.** El certificado del portal venció, o el reloj del equipo está
   desfasado. El fabricante recomienda verificar la hora del sistema antes de concluir
   que el certificado venció.
3. **Nombre no coincidente.** El nombre con el que se conecta no corresponde al del
   certificado; típico al conectarse por dirección IP en vez de por nombre.

El cliente ofrece una opción para continuar de todos modos. El fabricante la documenta,
pero advierte que **anula la validación del servidor** y recomienda no usarla en
producción. En Aconcagua Logística esa opción está **prohibida** por la Política de
Seguridad TI, sección 4.

---

## 3. Comportamientos que el fabricante documenta y conviene conocer

- **Túnel dividido (split tunnel).** Si el perfil está configurado con túnel dividido,
  solo el tráfico hacia las redes corporativas pasa por la VPN. Un usuario que "conecta
  pero no navega distinto" no tiene una falla: está viendo el comportamiento esperado.
- **Conflicto de rangos.** Si la red local del usuario usa el mismo rango privado que la
  red corporativa, el enrutamiento se rompe. El fabricante señala que no hay solución del
  lado del cliente: hay que cambiar el rango de la red local.
- **Dos clientes VPN simultáneos.** Dos túneles activos compiten por las rutas; el
  fabricante recomienda mantener uno solo activo.
- **Actualizaciones.** El fabricante publica correcciones de seguridad periódicas para el
  cliente; mantener versiones antiguas es un riesgo conocido.

---

## 4. Lo que esta documentación **no** define

- Quién ejecuta cada corrección. Las acciones sobre el concentrador (grupos, sesiones,
  certificados) son de Nivel 2 en Aconcagua Logística.
- Los tiempos de respuesta comprometidos: eso lo fija el catálogo de servicios interno
  (CAT-RED).
- La prohibición de aceptar advertencias de certificado, que es una norma interna más
  estricta que la recomendación del fabricante.
