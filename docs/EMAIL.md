# Correo: invitaciones y restablecer contraseña

El sistema manda dos correos, ambos en español:

| Correo | Cuándo | Vence |
|---|---|---|
| **Invitación** | Se da de alta una óptica o un administrador sin contraseña | 7 días |
| **Restablecer contraseña** | Alguien usa "Olvidé mi contraseña" en `/app` | 1 hora |

Los dos llevan un enlace de **un solo uso** a `/app#/password/<token>`.

## Por qué el token va en el fragmento

`#/password/<token>` — todo lo que sigue al `#` **nunca se manda al servidor**.
El token no aparece en los logs de acceso, ni en los del proxy, ni en la
cabecera `Referer` si el usuario hace clic en un enlace desde esa página. La
consola lo lee en el navegador y lo manda por HTTPS al confirmar.

En la base sólo se guarda el **SHA-256** del token, nunca el token. Un backup
filtrado no sirve para entrar a ninguna cuenta.

## Elegir un backend

`EMAIL_BACKEND` decide quién entrega:

| Valor | Qué hace | Para qué |
|---|---|---|
| `console` | Lo imprime por pantalla | Desarrollo. **Es el default**: nadie recibe nada |
| `memory` | Lo guarda en una lista | Tests |
| `smtp` | SMTP común | Cualquier proveedor (Brevo, Resend, SendGrid, Mailgun, Gmail) |
| `resend` | API HTTPS de Resend | **El configurado.** Un POST sale aunque SMTP esté bloqueado |
| `brevo` | API HTTPS de Brevo | Alternativa, ya implementada |

> **`console` no manda nada.** En producción hay que cambiarlo, o las
> invitaciones se imprimen en los logs de Render y el dueño nunca recibe nada.

**Preferí una API HTTPS antes que SMTP en un PaaS.** Render bloquea el puerto 25
saliente, y SMTP a través de un firewall de plataforma falla de maneras poco
claras. Un POST HTTPS siempre sale y devuelve un error legible.

## El proveedor: Resend

3.000 correos por mes gratis, sin tarjeta. Manda desde un dominio verificado —
por eso hace falta que la delegación a Cloudflare esté lista antes.

1. Crear la cuenta en **resend.com** (con GitHub o email; no pide tarjeta).
2. **Domains → Add Domain** → `miopticadigital.com.ar`.
3. Resend muestra tres registros DNS. Cargarlos en Cloudflare tal cual:

   | Tipo | Nombre | Valor | Proxy |
   |---|---|---|---|
   | `TXT` | `send` | `v=spf1 include:amazonses.com ~all` | — |
   | `MX` | `send` | `feedback-smtp.<región>.amazonses.com` (prio 10) | — |
   | `TXT` | `resend._domainkey` | `p=MIGfMA0GCSq…` (largo) | — |

   > Resend usa Amazon SES por debajo: por eso los valores dicen `amazonses.com`.
   > Los registros van en el subdominio `send`, así el correo normal del dominio
   > nunca se ve afectado por lo que mande el sistema.

4. **API Keys → Create API Key** (permiso *Sending access* alcanza). Empieza con `re_`.
5. En Render:
   ```
   EMAIL_BACKEND=resend
   RESEND_API_KEY=re_...
   EMAIL_FROM=Mi Óptica Digital <no-reply@miopticadigital.com.ar>
   PUBLIC_BASE_URL=https://app.miopticadigital.com.ar
   ```
6. Verificar que los registros estén arriba:
   ```bash
   python -m scripts.check_dns
   ```
   y darle **Verify** en Resend.

### Probarlo antes de tocar producción

Con la API key en la mano, mandate un correo real desde la máquina local — sin
desplegar nada:

```bash
EMAIL_BACKEND=resend RESEND_API_KEY=re_... \
  python -m scripts.send_test_email vos@gmail.com
```

Manda la plantilla de invitación de verdad, así ves exactamente lo que va a
recibir el dueño de una óptica. Recién cuando eso llegue, cambiá las variables
en Render.

### El primer error que vas a ver

Un `403` de Resend con "domain is not verified" significa que los registros DNS
todavía no propagaron o que falta apretar *Verify*. Queda en los logs y el alta
de la óptica **no** se deshace: se reenvía la invitación desde `/admin` cuando
el dominio quede verificado.

### Si preferís SMTP

Resend también habla SMTP, y sirve igual:

```
EMAIL_BACKEND=smtp
SMTP_HOST=smtp.resend.com
SMTP_PORT=587
SMTP_USER=resend
SMTP_PASSWORD=re_...
```

La API HTTPS es preferible en Render: un POST siempre sale, aunque el host
bloquee los puertos de SMTP.

## El dominio: miopticadigital.com.ar (nic.ar)

Dos cosas distintas se apoyan en el dominio:

1. **Mandar correo** como `no-reply@miopticadigital.com.ar` (SPF/DKIM/DMARC).
2. **Servir la app** en `app.miopticadigital.com.ar` en vez de
   `sgi-optica.onrender.com` — importa más de lo que parece: un dueño de óptica
   que recibe un enlace a un dominio que no reconoce piensa que es phishing, y
   hace bien.

> **Después de cada cambio, corré:**
> ```bash
> python -m scripts.check_dns
> ```
> Te dice qué falta y qué sigue, sin adivinar mientras propaga.

### Primero: delegar el DNS a Cloudflare

nic.ar tiene su propio panel de DNS, pero conviene delegar los nameservers a
**Cloudflare** (plan gratis) y manejar todo desde ahí: el panel es mejor, los
cambios propagan en segundos y no hay sorpresas con qué tipos de registro
soporta.

1. Crear la cuenta en Cloudflare → *Add a site* → `miopticadigital.com.ar`.
2. Cloudflare da dos nameservers, tipo `xxx.ns.cloudflare.com`.
3. En **nic.ar** (entrás con Clave Fiscal de AFIP o con Mi Argentina):
   **Delegaciones → Nueva delegación** — cargás los dos nameservers de
   Cloudflare y le ponés un nombre, por ejemplo `cloudflare`.

   > nic.ar no te deja escribir los nameservers dentro del dominio: primero se
   > crea una *delegación* (un conjunto de NS con nombre, reutilizable) y
   > después se le asigna a uno o más dominios. Es el paso donde casi todos se
   > traban buscando el campo en la ficha del dominio.

4. **Mis dominios → `miopticadigital.com.ar` → Cambiar delegación** → elegís la
   que acabás de crear.
5. Esperar la propagación (suele ser menos de una hora, a veces hasta 24):
   ```bash
   python -m scripts.check_dns
   ```

> Si preferís no usar Cloudflare, el DNS propio de nic.ar también sirve: hay que
> cargar los mismos registros de abajo en su panel. Verificá que acepte TXT con
> valores largos — la clave DKIM es larga y ese es el punto donde suele fallar.

### Después: los registros para el correo

Resend da los valores exactos al agregar el dominio. La forma es esta:

| Tipo | Nombre | Valor (ejemplo — usar el del proveedor) | Para qué |
|---|---|---|---|
| `TXT` | `send` | `v=spf1 include:amazonses.com ~all` | **SPF**: quién puede mandar |
| `MX` | `send` | `feedback-smtp.<región>.amazonses.com` | Rebotes y quejas |
| `TXT` | `resend._domainkey` | `p=MIGfMA0…` | **DKIM**: firma cada correo |
| `TXT` | `_dmarc` | `v=DMARC1; p=none; rua=mailto:facu@miopticadigital.com.ar` | **DMARC**: qué hacer con lo que no valida |

`p=none` para arrancar: informa sin bloquear nada. Cuando lleve unas semanas
mandando bien, subir a `p=quarantine`.

> **Lo más cómodo es el DMARC Management de Cloudflare** (DNS → Settings →
> DMARC Management): crea el registro solo, con un `rua` que apunta a
> `dmarc-reports.cloudflare.net`, y te muestra los reportes parseados en un
> panel. Evita tener que recibir correo en el dominio sólo para leer XML —
> que es justamente lo que hace falta si el `rua` apunta a un Gmail.

Verificar:

```bash
python -m scripts.check_dns     # chequea los cuatro de una
```

### Y la app en app.miopticadigital.com.ar

1. Render → el servicio → **Settings → Custom Domains** → agregar
   `app.miopticadigital.com.ar`. Render pide un `CNAME`.
2. En Cloudflare: `CNAME` `app` → `sgi-optica.onrender.com`.
   **Poner el registro en "DNS only"** (la nube gris, no la naranja): con el
   proxy de Cloudflare activado, Render no puede emitir su certificado.
3. Render emite el certificado solo. Después:
   ```
   PUBLIC_BASE_URL=https://app.miopticadigital.com.ar
   ```
   Sin ese cambio los enlaces de invitación siguen apuntando a onrender.com.

### Orden recomendado

El correo no depende de la app y viceversa, así que:

1. Delegar a Cloudflare (bloquea todo lo demás).
2. Agregar el dominio en Resend y cargar los tres registros que da.
3. Cambiar `EMAIL_BACKEND` a `resend` y cargar `RESEND_API_KEY`.
4. Recién ahí el custom domain de Render y `PUBLIC_BASE_URL`.

Mientras 1–3 no estén, `EMAIL_BACKEND=console` deja el sistema andando: las
invitaciones se imprimen en los logs de Render y se pueden pasar a mano.

## Probar sin proveedor

Con `EMAIL_BACKEND=console` el correo entero sale por pantalla, enlace incluido:

```
--- EMAIL (backend=console, not actually sent) ---
To: ana@belgrano.com
Subject: Tu acceso a SGI Óptica — Óptica Belgrano
...
http://localhost:8000/app#/password/5eLpc-v9Hp...
--- end email ---
```

Copiás ese enlace al navegador y recorrés el flujo completo.

## Límites

- **`console` es el default**, a propósito: un checkout nuevo no manda correo a
  nadie por accidente. La contracara es que hay que acordarse de cambiarlo.
- **El rate limiting cuenta por proceso** (`app/core/ratelimit.py`). Con
  `WEB_CONCURRENCY=1` eso es toda la aplicación; con más workers el límite
  efectivo se multiplica y habría que moverlo a la base.
- **Los envíos son sincrónicos.** Un proveedor lento agrega su latencia al
  request. Con un puñado de ópticas no se nota; a más volumen, va a una cola.
- **No hay reintentos.** Si falla, se registra y se reenvía a mano desde
  `/admin`. El alta de la óptica nunca se deshace por un correo que no salió.
