"""Send one real email through the configured backend.

    python -m scripts.send_test_email vos@gmail.com

For checking that a provider actually works — credentials, domain
verification, deliverability — before wiring it into production and finding out
from a customer who never got their invitation.

Sends the real invitation template, so what arrives is what an óptica owner
will see: same subject, same layout, same From address.
"""
from __future__ import annotations

import sys

from app.core.config import settings
from app.services import email as email_service
from app.services import email_templates


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    to = argv[1].strip()

    print(f"Backend .......... {settings.email_backend}")
    print(f"From ............. {settings.email_from}")
    print(f"To ............... {to}")
    print(f"Base URL ......... {settings.public_base_url}")
    if settings.email_backend == "resend":
        key = settings.resend_api_key
        print(f"RESEND_API_KEY ... {'sí (' + key[:7] + '…)' if key else 'FALTA'}")
    elif settings.email_backend == "smtp":
        print(f"SMTP ............. {settings.smtp_host}:{settings.smtp_port}")
    print()

    if settings.email_backend in ("console", "memory"):
        print(
            f"⚠️  EMAIL_BACKEND={settings.email_backend} no manda nada de verdad.\n"
            "   Para probar el proveedor:  EMAIL_BACKEND=resend RESEND_API_KEY=re_... \\\n"
            f"                              python -m scripts.send_test_email {to}\n"
        )

    msg = email_templates.invitation(
        full_name="Prueba",
        company_name="Óptica de Prueba",
        link=f"{settings.public_base_url.rstrip('/')}/app#/password/TOKEN-DE-PRUEBA",
        hours=settings.invitation_ttl_hours,
    )
    sent = email_service.send(
        email_service.Message(to=to, subject=msg.subject, text=msg.text, html=msg.html)
    )

    if sent:
        print("✅ Entregado al proveedor. Revisá la bandeja (y el spam).")
        return 0
    print(
        "❌ No se pudo enviar. El motivo quedó arriba o en el log.\n"
        "   Lo más común con Resend: el dominio todavía no está verificado (403),\n"
        "   o EMAIL_FROM usa un dominio distinto al verificado."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
