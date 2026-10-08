"""The emails the system sends, in Spanish.

Plain strings rather than a template engine: there are two of them, they are
mostly static, and adding Jinja to render two documents would be a dependency
per template. Every message goes out as text *and* HTML — some shop owners
read mail on a phone client that renders neither well, and a plain-text part
is what keeps the link usable when the HTML fails.
"""
from __future__ import annotations

from html import escape

from app.services.email import Message

_STYLES = (
    "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,"
    "Arial,sans-serif;font-size:15px;line-height:1.5;color:#1f2937"
)
_BUTTON = (
    "display:inline-block;background:#2563eb;color:#ffffff;text-decoration:none;"
    "padding:12px 22px;border-radius:8px;font-weight:600"
)


def _wrap(body: str) -> str:
    return (
        f'<div style="{_STYLES};max-width:520px;margin:0 auto;padding:24px">'
        f"{body}"
        '<hr style="border:0;border-top:1px solid #e3e8ef;margin:26px 0">'
        '<p style="font-size:12px;color:#6b7280;margin:0">'
        "SGI Óptica · Sistema de gestión para ópticas"
        "</p></div>"
    )


def invitation(*, full_name: str, company_name: str, link: str, hours: int) -> Message:
    days = max(1, hours // 24)
    text = (
        f"Hola {full_name},\n\n"
        f"Se creó tu cuenta en SGI Óptica para {company_name}.\n\n"
        f"Definí tu contraseña acá:\n{link}\n\n"
        f"El enlace vence en {days} día(s) y se puede usar una sola vez.\n\n"
        "Si no esperabas este correo, ignoralo.\n"
    )
    html = _wrap(
        f"<p>Hola <b>{full_name}</b>,</p>"
        f"<p>Se creó tu cuenta en <b>SGI Óptica</b> para <b>{company_name}</b>.</p>"
        f'<p style="margin:24px 0"><a href="{link}" style="{_BUTTON}">Definir mi contraseña</a></p>'
        f'<p style="font-size:13px;color:#6b7280">El enlace vence en {days} día(s) '
        "y se puede usar una sola vez. Si no esperabas este correo, ignoralo.</p>"
        f'<p style="font-size:12px;color:#6b7280;word-break:break-all">'
        f"Si el botón no funciona, copiá esta dirección:<br>{link}</p>"
    )
    return Message(
        to="", subject=f"Tu acceso a SGI Óptica — {company_name}", text=text, html=html
    )


def password_reset(*, full_name: str, company_name: str, link: str, hours: int) -> Message:
    text = (
        f"Hola {full_name},\n\n"
        f"Pediste restablecer tu contraseña de SGI Óptica ({company_name}).\n\n"
        f"Definí una nueva acá:\n{link}\n\n"
        f"El enlace vence en {hours} hora(s) y se puede usar una sola vez.\n\n"
        "Si no lo pediste, ignorá este correo: tu contraseña actual sigue funcionando.\n"
    )
    html = _wrap(
        f"<p>Hola <b>{full_name}</b>,</p>"
        f"<p>Pediste restablecer tu contraseña de <b>SGI Óptica</b> ({company_name}).</p>"
        f'<p style="margin:24px 0"><a href="{link}" style="{_BUTTON}">Definir una nueva contraseña</a></p>'
        f'<p style="font-size:13px;color:#6b7280">El enlace vence en {hours} hora(s) '
        "y se puede usar una sola vez. Si no lo pediste, ignorá este correo: "
        "tu contraseña actual sigue funcionando.</p>"
        f'<p style="font-size:12px;color:#6b7280;word-break:break-all">'
        f"Si el botón no funciona, copiá esta dirección:<br>{link}</p>"
    )
    return Message(
        to="", subject="Restablecer tu contraseña — SGI Óptica", text=text, html=html
    )


# --- facturación electrónica ------------------------------------------------
# The guide in Empresa is asynchronous: the shop sends it, we accept the
# delegation at ARCA, we activate. These three say so, so nobody has to keep
# checking a screen.


def invoicing_request(
    *, company_name: str, cuit: str, condition: str, point_of_sale: int, link: str
) -> Message:
    """To us: a shop finished its steps at ARCA and waits for activation."""
    text = (
        f"{company_name} terminó la guía de facturación electrónica.\n\n"
        f"CUIT {cuit}, {condition}, punto de venta {point_of_sale}.\n\n"
        "Antes de activarla, en ARCA con nuestra Clave Fiscal: aceptá la delegación "
        "(Aceptación de Designación) y autorizá nuestro computador fiscal para su CUIT "
        "(Administrador de Relaciones, Facturación Electrónica).\n\n"
        f"Después, activala desde la consola del proveedor:\n{link}\n"
    )
    html = _wrap(
        f"<p><b>{escape(company_name)}</b> terminó la guía de facturación electrónica.</p>"
        f"<p>CUIT <b>{escape(cuit)}</b>, {escape(condition)}, punto de venta "
        f"<b>{point_of_sale}</b>.</p>"
        "<p>Antes de activarla, en ARCA con nuestra Clave Fiscal: aceptá la delegación "
        "(<i>Aceptación de Designación</i>) y autorizá nuestro computador fiscal para su "
        "CUIT (<i>Administrador de Relaciones</i>, Facturación Electrónica).</p>"
        f'<p style="margin:24px 0"><a href="{link}" style="{_BUTTON}">Abrir la consola</a></p>'
    )
    return Message(to="", subject=f"Facturación por activar: {company_name}",
                   text=text, html=html)


def invoicing_active(*, full_name: str, company_name: str, link: str) -> Message:
    """To the shop: it can invoice now."""
    text = (
        f"Hola {full_name},\n\n"
        f"Ya está activa la facturación electrónica de {company_name}.\n\n"
        "Desde ahora cada venta tiene el botón Facturar, y al anular una venta "
        "facturada sale sola su nota de crédito.\n\n"
        f"Podés verificar la conexión con ARCA desde Empresa, Facturación electrónica:\n{link}\n"
    )
    html = _wrap(
        f"<p>Hola <b>{escape(full_name)}</b>,</p>"
        f"<p>Ya está activa la facturación electrónica de <b>{escape(company_name)}</b>.</p>"
        "<p>Desde ahora cada venta tiene el botón <b>Facturar</b>, y al anular una venta "
        "facturada sale sola su nota de crédito.</p>"
        f'<p style="margin:24px 0"><a href="{link}" style="{_BUTTON}">Ir a Facturación electrónica</a></p>'
    )
    return Message(to="", subject=f"Tu facturación electrónica está activa: {company_name}",
                   text=text, html=html)


def invoicing_note(*, full_name: str, company_name: str, note: str, link: str) -> Message:
    """To the shop: something in its request needs another look."""
    text = (
        f"Hola {full_name},\n\n"
        f"Revisamos la facturación electrónica de {company_name} y te dejamos este mensaje:\n\n"
        f"{note}\n\n"
        f"Lo ves, y corregís lo que haga falta, en Empresa, Facturación electrónica:\n{link}\n"
    )
    html = _wrap(
        f"<p>Hola <b>{escape(full_name)}</b>,</p>"
        f"<p>Revisamos la facturación electrónica de <b>{escape(company_name)}</b> "
        "y te dejamos este mensaje:</p>"
        f'<p style="background:#fffbeb;border:1px solid #fde68a;border-radius:8px;'
        f'padding:12px 14px">{escape(note)}</p>'
        f'<p style="margin:24px 0"><a href="{link}" style="{_BUTTON}">Ver la guía</a></p>'
    )
    return Message(to="", subject=f"Sobre tu facturación electrónica: {company_name}",
                   text=text, html=html)
