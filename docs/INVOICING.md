# Facturación electrónica (ARCA, vía arca-api)

Una venta se factura con el botón **Facturar** de su ficha (o desde el aviso
que aparece al cobrarla). SGI no habla con ARCA directamente: le pide el
comprobante a **arca-api**, nuestro gateway propio
([facubarafani/arca-api](https://github.com/facubarafani/arca-api)), que tiene
los certificados, los tickets de WSAA, la numeración y el PDF.

```
consola ─► SGI (services/invoicing.py) ─► services/arca.py ─HTTP─► arca-api ─SOAP─► ARCA
```

`services/arca.py` es el único código que llama a arca-api; las reglas (qué
clase, qué líneas, qué hacer con cada respuesta) están en
`services/invoicing.py`.

## Configuración

| Variable | Qué es |
|---|---|
| `ARCA_API_URL` | Dónde está arca-api, por ejemplo `https://api.<dominio>` |
| `ARCA_API_KEY` | La clave `ak_...` del proyecto de SGI en arca-api (`npm run admin -- project:create "SGI Óptica"`) |
| `ARCA_API_BACKEND` | `http` (default) o `fake`. Los tests fuerzan `fake` |
| `ARCA_API_TIMEOUT_SECONDS` | Cuánto espera SGI una respuesta (30). Pasado eso, el comprobante queda en trámite |
| `ARCA_PLATFORM_CUIT` | Nuestro CUIT, en el que las ópticas delegan Facturación Electrónica. Sin él no aparece la guía |
| `ARCA_PLATFORM_NAME` | Cómo muestra ARCA ese CUIT (opcional, para que la óptica confirme que eligió bien) |

Sin `ARCA_API_URL` y `ARCA_API_KEY` la facturación está apagada: un checkout
nuevo nunca le habla a ARCA por accidente.

**Un arca-api por ambiente.** Cada deployment de arca-api sirve uno solo
(homologación o producción, con su propia base). El SGI local apunta a
homologación; el de producción, a producción. Nunca al revés.

## Desarrollo local contra homologación

Los comprobantes de homologación no tienen efecto fiscal.

1. En `arca-api`: `docker compose up -d --wait` y `npm start` (queda en
   `http://127.0.0.1:3000`). Su `.env` tiene que decir
   `ARCA_ENVIRONMENT=homologacion` y la credencial de homologación tiene que
   estar importada (ver su README).
2. Un proyecto para SGI: `npm run admin -- project:create "SGI Óptica (dev)"`.
3. En el `.env` de SGI: `ARCA_API_URL=http://127.0.0.1:3000` y la clave.
4. En `/admin`, ficha de la óptica, **Activar facturación** con el CUIT que
   está autorizado en WSASS y punto de venta `1` (homologación no tiene puntos
   de venta propios: acepta cualquiera).

## Dar de alta una óptica (producción, modo delegado)

Como hacen los proveedores de facturación: la óptica factura con **nuestro**
certificado, en su nombre, y lo autoriza ella misma desde ARCA. SGI la guía.

**La óptica**, desde su consola: **Empresa → Facturación electrónica**. La
guía le pide dos pasos en ARCA con su Clave Fiscal (nivel 3), con los nombres
exactos de cada pantalla:

1. Crear un punto de venta **para web services**, con el *Sistema* que
   corresponde a su condición frente al IVA (la guía muestra cuál). Nunca uno
   de Comprobantes en Línea.
2. Delegar **Facturación Electrónica** en nuestro CUIT (`ARCA_PLATFORM_CUIT`,
   que la guía muestra con un botón para copiarlo): *Administrador de
   Relaciones de Clave Fiscal → Nueva Relación → ARCA → WebServices →
   Facturación Electrónica*, representante: nuestro CUIT.

Cada paso muestra, debajo, la pantalla de ARCA que le corresponde, recortada
de sus instructivos oficiales ([alta de punto de venta](https://arca.gob.ar/guias/paso-a-paso/Guia-Como-emito-factura-electronica-y-punto-de-venta.pdf),
[delegar un servicio](https://www.afip.gob.ar/guias/paso-a-paso/Como-delego-servicios-para-que-utilicen-en-mi-nombre-como-se-acepta-delegacion.pdf),
[delegar un web service](https://www.afip.gob.ar/ws/WSAA/ADMINREL.DelegarWS.pdf)). Donde el ejemplo
de ARCA no es nuestro caso, la captura lo dice; en el formulario del punto de
venta, ARCA elige *Factura en Línea* y la guía lo tacha encima. Si ARCA cambia
sus pantallas, se recortan de nuevo de la versión nueva del instructivo
(`app/web/guia/`).

Después completa sus datos (CUIT, razón social, condición, punto de venta,
domicilio comercial, Ingresos Brutos, inicio de actividades) y toca **Ya
delegué, enviar**. Puede guardar a medias y seguir otro día. La guía nunca
activa nada: sólo deja el pedido (`invoicing_requests`) y nos manda un email.

**Nosotros**, en `/admin`: la óptica aparece **Por activar** en la lista. Su
ficha muestra lo que envió al lado del **padrón de ARCA** para ese CUIT, y
avisa si la condición declarada no coincide con la que sugiere ARCA (la
condición no se puede cambiar después). Antes de activar, con nuestra Clave
Fiscal:

1. *Aceptación de Designación*: aceptar la delegación (figura pendiente).
2. *Administrador de Relaciones*: con su CUIT como representado, *Nueva
   Relación → WebServices → Facturación Electrónica*, y como representante
   nuestro computador fiscal.

Después **Activar** (el formulario viene con sus datos) registra el CUIT en
arca-api como emisor delegado, o vincula el que ya exista si la condición
coincide. Si falta algo, **Dejar un mensaje**: la óptica lo ve en su guía y le
llega por email. Al activar le llega otro email, y en su tarjeta puede
**Verificar con ARCA**, que dice en castellano qué falta (la delegación, el
punto de venta) o que ya puede facturar. La autorización puede tardar hasta
24 h en propagarse.

Sin `ARCA_PLATFORM_CUIT` la guía no aparece. `ARCA_PLATFORM_NAME` es opcional:
el nombre con el que ARCA muestra nuestro CUIT, para que la óptica sepa que
eligió bien.

Solo el proveedor vincula una óptica con un emisor: el vínculo decide a
nombre de qué CUIT salen sus ventas. Un emisor sirve a una sola óptica, y una
óptica que ya emitió comprobantes no cambia de emisor. **Pausar** la
facturación esconde el botón sin olvidar el vínculo.

Cada sucursal puede tener su propio punto de venta (Sucursales → editar);
sin él, usa el de la óptica.

## Cómo se arma un comprobante

- **Clase.** Monotributista o Exento: **C**. Responsable Inscripto: **A**
  para un comprador Responsable Inscripto o monotributista (con su CUIT, que
  la ficha del cliente tiene que tener), **B** para todos los demás. Un
  cliente sin condición frente al IVA es consumidor final; una venta sin
  cliente, un consumidor final sin identificar (hasta $10.000.000,
  RG 5866/2026).
- **Líneas.** Las de la venta, al precio cobrado, con su **bonificación**: el
  descuento de la línea más su parte del descuento de la venta, repartido por
  mayor resto. El total del comprobante es el de la venta, al centavo.
- **IVA.** Los precios son finales (IVA incluido). La alícuota de cada línea
  sale de su tipo de producto (Catálogo → Tipos de producto); vacía es el
  21%. Solo la usan A y B, y la tiene que confirmar el contador de la óptica.
- **Condición de venta.** "Contado" si la venta está paga, "Cuenta
  corriente" si queda saldo.

## Por qué un reintento nunca factura dos veces

La fila del comprobante, su `Idempotency-Key` y el cuerpo exacto se guardan
**antes** de mandar nada. Pase lo que pase después (respuesta, timeout,
caída), SGI sabe con qué clave volver a preguntar, y un comprobante en
trámite solo se reenvía tal cual: nunca se rearma.

| arca-api responde | Estado en SGI |
|---|---|
| 201 | **Autorizado**, con número y CAE |
| 202, timeout, sin conexión, 5xx | **En trámite**: se vuelve a preguntar con la misma clave |
| 422 con el comprobante | **Rechazado** por ARCA |
| 4xx sin `invoiceId` | **Rechazado**: arca-api no guardó nada |

Solo después de un rechazo se puede pedir otro comprobante, con otra clave:
un rechazo no usa número. La ficha de la venta vuelve a preguntar sola cada
cinco segundos mientras algo esté en trámite, y **Reintentar** reenvía con la
misma clave (también reactiva uno que arca-api dejó de reintentar a las 24 h).

## Anular una venta facturada

Anular devuelve el stock como siempre y después emite la **nota de crédito**
contra la factura, con sus mismas líneas. Si ARCA la rechaza, la venta queda
anulada igual y la ficha ofrece **Emitir nota de crédito**. Una venta cuya
factura todavía está en trámite no se puede anular hasta que se resuelva:
arca-api no puede retirar un comprobante que no terminó.

## Límites conocidos

- **arca-api tiene que conocer `discount`** (la bonificación por línea). Un
  arca-api anterior descarta el campo sin avisar y autoriza el precio sin
  descuento. SGI guarda lo que ARCA autorizó y la ficha avisa si no coincide
  con la venta, pero el remedio es desplegar arca-api primero.
- Solo concepto "productos": un servicio facturado necesita período y
  vencimiento, que todavía no se piden.
- Solo pesos, sin percepciones ni otros tributos, sin notas de débito ni
  Factura de Crédito MiPyME.
- Que un contador lea un comprobante impreso de cada clase antes del primer
  comprobante real (ver NEXT_STEPS de arca-api).
