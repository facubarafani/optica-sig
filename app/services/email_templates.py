"""The two emails the system sends, in Spanish.

Plain strings rather than a template engine: there are two of them, they are
mostly static, and adding Jinja to render two documents would be a dependency
per template. Every message goes out as text *and* HTML — some shop owners
read mail on a phone client that renders neither well, and a plain-text part
is what keeps the link usable when the HTML fails.
"""
from __future__ import annotations

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
