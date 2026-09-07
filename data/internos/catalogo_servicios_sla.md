---
titulo: "CAT-SLA-00 · Catálogo de servicios TI y acuerdos de nivel de servicio"
fecha_vigencia: 2026-01-05
nivel_acceso: publico_interno
---

# CAT-SLA-00 · Catálogo de servicios y SLA

Documento oficial de la Subgerencia de TI de Aconcagua Logística SpA. Define los
servicios que presta la mesa de ayuda interna, las prioridades y los tiempos
comprometidos. Vigente desde el 5 de enero de 2026.

---

## 1. Horario de atención

| Modalidad | Cobertura |
|---|---|
| Mesa de ayuda Nivel 1 | Lunes a viernes de 08:00 a 19:00; sábados de 09:00 a 14:00 |
| Nivel 2 (especialistas) | Lunes a viernes de 08:30 a 18:30 |
| Turno de emergencia P1 | 24 horas, todos los días del año, vía teléfono de guardia |
| Ventana de mantención | Primer domingo del mes, 02:00 a 05:00 |

Los tiempos de resolución de P3 y P4 se cuentan en **horas hábiles** dentro del horario
de la mesa. Los de P1 y P2 se cuentan en **horas corridas**.

---

## 2. Servicios del catálogo

| Código | Servicio | Descripción | Prioridad base |
|---|---|---|---|
| CAT-ACC | Cuentas y accesos | Alta, baja, bloqueo, restablecimiento de contraseña, permisos | P3 |
| CAT-M365 | Correo y ofimática | Outlook, Teams, OneDrive, licencias Microsoft 365 | P3 |
| CAT-RED | Conectividad y VPN | Enlaces de sucursal, Wi-Fi, VPN corporativa | P2 |
| CAT-MOV | Terminales móviles en ruta | Terminales Android de reparto, Intune, SIM de datos | P2 |
| CAT-ERP | ERP de transporte | Módulos de hojas de ruta, facturación y flota | P2 |
| CAT-IMP | Impresión y guías | Impresoras de sucursal e impresoras térmicas de guías | P3 |

---

## 3. Matriz de prioridades

La prioridad resulta de cruzar **impacto** (cuánta gente u operación se ve afectada) con
**urgencia** (cuánto puede esperar).

| | Urgencia alta | Urgencia media | Urgencia baja |
|---|---|---|---|
| **Impacto alto** (sucursal, CD o flota completa) | P1 | P1 | P2 |
| **Impacto medio** (área o grupo de usuarios) | P2 | P2 | P3 |
| **Impacto bajo** (un usuario) | P2 | P3 | P4 |

### Definición de cada prioridad

- **P1 · Crítica.** Servicio caído para una sucursal completa, el centro de distribución
  o la flota en ruta. También: pérdida o robo de un terminal móvil, y todo incidente de
  seguridad confirmado.
- **P2 · Alta.** Un grupo de usuarios sin servicio, o un usuario en ruta bloqueado para
  operar. También: bajas de personal pendientes de ejecutar.
- **P3 · Media.** Un usuario con el servicio degradado pero con alternativa de trabajo.
  Es la prioridad base de la mayoría de las solicitudes de cuentas y de correo.
- **P4 · Baja.** Consultas, solicitudes de información, mejoras y requerimientos
  programables sin impacto operativo.

---

## 4. Tiempos comprometidos

| Prioridad | Primera respuesta | Resolución objetivo | Cumplimiento mínimo mensual |
|---|---|---|---|
| P1 · Crítica | 15 minutos | 4 horas corridas | 95 % |
| P2 · Alta | 30 minutos | 8 horas corridas | 90 % |
| P3 · Media | 2 horas hábiles | 24 horas hábiles | 90 % |
| P4 · Baja | 4 horas hábiles | 40 horas hábiles | 85 % |

**Primera respuesta** es el contacto efectivo con el usuario informando que el caso fue
tomado, no el acuse automático de recepción del sistema.

**Reloj del SLA.** El cronómetro se detiene cuando el ticket queda "en espera del
usuario" (falta información que solo el solicitante puede aportar) y se reanuda con la
respuesta. Un escalamiento a Nivel 2 **no** detiene el cronómetro.

---

## 5. Escalamiento

### 5.1 Escalamiento funcional (a Nivel 2)

Procede cuando el caso requiere privilegios de administrador, conocimiento
especializado, o cuando Nivel 1 agotó el procedimiento documentado sin resolver.
Nivel 1 entrega el caso con: síntoma, pasos ya realizados, resultado de cada uno,
prioridad propuesta y datos del activo involucrado.

### 5.2 Escalamiento jerárquico (por tiempo)

| Prioridad | Aviso al coordinador de mesa | Aviso a Subgerencia de TI |
|---|---|---|
| P1 | A los 30 minutos sin solución | A las 2 horas |
| P2 | A las 4 horas | A las 8 horas |
| P3 | Al 80 % del SLA de resolución | No aplica |
| P4 | No aplica | No aplica |

### 5.3 Reclasificación de prioridad

La prioridad se puede subir en cualquier momento si el impacto crece. Bajarla requiere
acuerdo explícito del usuario, registrado en el ticket.

---

## 6. Volumen y capacidad de referencia

- Volumen promedio: 900 tickets al mes.
- Distribución histórica: 38 % CAT-ACC, 27 % CAT-M365, 16 % CAT-RED, 11 % CAT-MOV,
  5 % CAT-ERP, 3 % CAT-IMP.
- Dotación: 4 agentes de Nivel 1, 2 especialistas de Nivel 2.
- Resolución en primer contacto (objetivo): 65 %.

---

## 7. Exclusiones del servicio

La mesa de ayuda **no** atiende:

- Equipos y cuentas personales de los colaboradores.
- Software no autorizado por TI.
- Soporte a sistemas de clientes o de proveedores externos.
- Entrega de credenciales, claves de recuperación o códigos de verificación por
  cualquier canal; ver Política de Seguridad TI, sección 3.

**Fuente interna relacionada:** Política de Seguridad TI, artículos KB-ACC-01,
KB-M365-01, KB-RED-02 y KB-MOV-03.
