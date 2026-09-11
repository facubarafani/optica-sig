"""Sending mail, with the provider behind a seam.

Three backends, chosen by ``EMAIL_BACKEND``:

- ``console`` — prints the message and sends nothing. The default, so a fresh
  checkout never needs credentials and never accidentally mails a real person.
- ``memory`` — appends to :data:`outbox` and sends nothing. What the tests
  assert against.
- ``smtp`` — any provider that speaks SMTP, which is all of them (Brevo,
  Resend, SendGrid, Mailgun, Gmail). Use port 587 with STARTTLS: port 25 is
  blocked outbound on most PaaS hosts, Render included.
- ``resend`` — Resend's HTTPS API. The configured provider.
- ``brevo`` — Brevo's HTTPS API.

The two HTTP backends exist because an ordinary HTTPS request still works where
SMTP ports are firewalled, which on a PaaS they often are.

Switching provider is a config change, not a code change. Adding one is a
function plus a line in ``_BACKENDS``.

Delivery never breaks the request that triggered it. A failed invitation must
not roll back the tenant that was just provisioned — the account is real
either way, and the fix is to resend, not to re-onboard.
"""
from __future__ import annotations

import logging
import smtplib
from dataclasses import dataclass
from email.message import EmailMessage

import httpx

from app.core.config import settings

logger = logging.getLogger("app.email")


class EmailError(Exception):
    """Raised when a backend could not hand the message over."""


@dataclass(frozen=True)
class Message:
    to: str
    subject: str
    text: str
    html: str


# --- backends -------------------------------------------------------------
# Everything the ``memory`` backend has "sent", oldest first. Tests read it;
# nothing in the application does.
outbox: list[Message] = []


def _send_console(msg: Message) -> None:
    """Print it instead of sending, so the link is copy-pasteable in dev.

    Deliberately ``print`` and not ``logger.info``. Nothing in this project
    configures logging, so the root logger sits at WARNING and an INFO record
    disappears — which made this backend silently do nothing at all, the one
    failure a development aid must never have.
    """
    print(
        f"\n--- EMAIL (backend=console, not actually sent) ---\n"
        f"To: {msg.to}\nSubject: {msg.subject}\n\n{msg.text}\n"
        f"--- end email ---",
        flush=True,
    )


def _send_memory(msg: Message) -> None:
    outbox.append(msg)


def _send_smtp(msg: Message) -> None:
    if not settings.smtp_host:
        raise EmailError("SMTP_HOST is not configured.")
    mail = EmailMessage()
    mail["From"] = settings.email_from
    mail["To"] = msg.to
    mail["Subject"] = msg.subject
    mail.set_content(msg.text)
    mail.add_alternative(msg.html, subtype="html")
    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as s:
            if settings.smtp_starttls:
                s.starttls()
            if settings.smtp_user:
                s.login(settings.smtp_user, settings.smtp_password)
            s.send_message(mail)
    except (smtplib.SMTPException, OSError) as exc:
        raise EmailError(f"SMTP delivery failed: {exc}") from exc


def _send_brevo(msg: Message) -> None:
    if not settings.brevo_api_key:
        raise EmailError("BREVO_API_KEY is not configured.")
    name, address = _split_from(settings.email_from)
    try:
        resp = httpx.post(
            "https://api.brevo.com/v3/smtp/email",
            headers={
                "api-key": settings.brevo_api_key,
                "content-type": "application/json",
            },
            json={
                "sender": {"name": name, "email": address},
                "to": [{"email": msg.to}],
                "subject": msg.subject,
                "textContent": msg.text,
                "htmlContent": msg.html,
            },
            timeout=15,
        )
    except httpx.HTTPError as exc:
        raise EmailError(f"Brevo request failed: {exc}") from exc
    if resp.status_code >= 300:
        raise EmailError(f"Brevo rejected the message ({resp.status_code}): {resp.text[:300]}")


def _send_resend(msg: Message) -> None:
    if not settings.resend_api_key:
        raise EmailError("RESEND_API_KEY is not configured.")
    try:
        resp = httpx.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {settings.resend_api_key}",
                "Content-Type": "application/json",
            },
            json={
                # Resend takes the whole "Name <address>" form directly, and
                # the address must be on a domain verified in the dashboard.
                "from": settings.email_from,
                "to": [msg.to],
                "subject": msg.subject,
                "text": msg.text,
                "html": msg.html,
            },
            timeout=15,
        )
    except httpx.HTTPError as exc:
        raise EmailError(f"Resend request failed: {exc}") from exc
    if resp.status_code >= 300:
        # 403 here almost always means the domain is not verified yet, which is
        # worth saying out loud: the body explains it and the log is where
        # anyone will look.
        raise EmailError(
            f"Resend rejected the message ({resp.status_code}): {resp.text[:300]}"
        )


_BACKENDS = {
    "console": _send_console,
    "memory": _send_memory,
    "smtp": _send_smtp,
    "resend": _send_resend,
    "brevo": _send_brevo,
}


def _split_from(value: str) -> tuple[str, str]:
    """``"SGI Óptica <no-reply@x.com>"`` -> ``("SGI Óptica", "no-reply@x.com")``."""
    value = value.strip()
    if value.endswith(">") and "<" in value:
        name, _, rest = value.partition("<")
        return name.strip().strip('"') or "SGI Óptica", rest[:-1].strip()
    return "SGI Óptica", value


def send(msg: Message) -> bool:
    """Deliver a message. Returns whether it went out; never raises.

    Callers are mid-transaction on something more important than the email —
    provisioning a tenant, resetting a password. A provider outage must not
    undo that work, so the failure is logged loudly and reported to the caller
    as ``False`` rather than thrown.
    """
    backend = _BACKENDS.get(settings.email_backend)
    if backend is None:
        logger.error(
            "Unknown EMAIL_BACKEND %r — message to %s not sent. Valid: %s",
            settings.email_backend, msg.to, ", ".join(_BACKENDS),
        )
        return False
    try:
        backend(msg)
        return True
    except EmailError as exc:
        logger.error("Could not send %r to %s: %s", msg.subject, msg.to, exc)
        return False
    except Exception:  # a backend bug must not take the request down with it
        logger.exception("Unexpected failure sending %r to %s", msg.subject, msg.to)
        return False
