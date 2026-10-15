"""Payment reminders by WhatsApp: the message in three tones, and its record.

A customer owes on a sale and the day they promised is near or gone: the shop
writes to them. ``draft`` words that message for the sale in each tone and
says where it goes, the phone on the customer's file (``services.whatsapp``
turns it into a WhatsApp number). ``record`` keeps the one the seller sent,
so the lists can say who was already written to, and when.

The shop sends, not the server. The console opens WhatsApp (a wa.me link) with
the message written, and the seller presses Enviar from the shop's own number:
the one the customer knows and can answer. No WhatsApp Business account, no
template to get approved, nothing paid per message. The price is that the
record says the message was opened, which is as much as can be known.

The tones, each worded for before the date ("vence el viernes 16/10") and for
after it or with no date at all ("venció el sábado 10/10", "sigue pendiente"):

* Amable: voseo and warm. Suggested until the date has passed.
* Formal: de usted. Suggested for the first week after it.
* Firme: voseo and direct, asks to regularise. Suggested after that.

The seller can edit any of them before sending; the defaults are the same for
every shop. Plain strings, like ``email_templates``. Nothing the customer reads
may carry an em dash or a gendered word: a name does not say how someone wants
to be addressed, so the formal one greets by name, never "Estimado".
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.customer import Customer
from app.models.enums import ReminderTone
from app.models.sales import PaymentReminder, Sale
from app.schemas.sales import PaymentReminderRead, ReminderDraft, ReminderMessage, ReminderSend
from app.services import clock, whatsapp
from app.services.sales import NON_DEBT_STATUSES

# Days after the promised date at which Firme becomes the suggestion.
FIRM_AFTER_DAYS = 7

WEEKDAYS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


class ReminderError(Exception):
    """The sale cannot be reminded about. Says why, in Spanish."""


# --- wording ---------------------------------------------------------------

@dataclass(frozen=True)
class Facts:
    """What a message says, already worded: the templates only join it up."""

    first_name: str        # "Juan"; empty when the file has none
    full_name: str         # "Juan Pérez"
    shop: str              # "Óptica Visión"
    balance: str           # "$45.000"
    bought: str            # "del 12/09", "de hoy", "de ayer"
    due: str               # "vence el viernes 16/10", "venció ayer", "sigue pendiente"
    upcoming: bool         # the date is today or later
    greeting: str          # "Buen día", "Buenas tardes", "Buenas noches"


def messages(f: Facts) -> dict[ReminderTone, str]:
    """The three default messages for these facts."""
    hello = f"¡Hola, {f.first_name}!" if f.first_name else "¡Hola!"
    plain_hello = f"Hola, {f.first_name}." if f.first_name else "Hola."
    formal_hello = f"{f.greeting}, {f.full_name}." if f.full_name else f"{f.greeting}."
    debt = f"el saldo de {f.balance} de tu compra {f.bought}"
    formal_debt = f"el saldo de {f.balance} de su compra {f.bought}"
    if f.upcoming:
        return {
            ReminderTone.FRIENDLY: (
                f"{hello} Te escribimos de {f.shop} para recordarte que {debt} {f.due}. "
                "Si necesitás algo, escribinos por acá. ¡Gracias!"
            ),
            ReminderTone.FORMAL: (
                f"{formal_hello} Le escribimos de {f.shop} para recordarle que "
                f"{formal_debt} {f.due}. Ante cualquier consulta, quedamos a su "
                "disposición. Saludos cordiales."
            ),
            ReminderTone.FIRM: (
                f"{plain_hello} Te recordamos que {debt} en {f.shop} {f.due}. "
                "Es importante que lo abones en la fecha acordada. Gracias."
            ),
        }
    return {
        ReminderTone.FRIENDLY: (
            f"{hello} Te escribimos de {f.shop}: {debt} {f.due}. Cuando puedas, "
            "avisanos cómo te queda más cómodo abonarlo. Si ya lo hiciste, "
            "¡disculpá la molestia y gracias!"
        ),
        ReminderTone.FORMAL: (
            f"{formal_hello} Le escribimos de {f.shop} para informarle que "
            f"{formal_debt} {f.due}. Le agradeceremos regularizarlo a la brevedad. "
            "Si ya realizó el pago, le pedimos que desestime este mensaje. "
            "Saludos cordiales."
        ),
        ReminderTone.FIRM: (
            f"{plain_hello} {debt[0].upper()}{debt[1:]} en {f.shop} {f.due}. "
            "Te pedimos que lo regularices a la brevedad. Si ya lo abonaste, "
            "desestimá este mensaje."
        ),
    }


def suggest(days_left: int | None) -> ReminderTone:
    """The tone that fits how late it is. ``days_left`` < 0 is overdue."""
    if days_left is None or days_left >= 0:
        return ReminderTone.FRIENDLY
    if -days_left <= FIRM_AFTER_DAYS:
        return ReminderTone.FORMAL
    return ReminderTone.FIRM


def _day(d: date, today: date) -> str:
    """16/10, with the year only when it is not this one."""
    return f"{d:%d/%m}" if d.year == today.year else f"{d:%d/%m/%Y}"


def due_phrase(due: date | None, today: date) -> str:
    """What happens on the promised day, said from today."""
    if due is None:
        return "sigue pendiente"
    days = (due - today).days
    # The weekday helps within a week ("el viernes"); further off it is noise.
    when = f"el {WEEKDAYS[due.weekday()]} {_day(due, today)}" if abs(days) < 7 else f"el {_day(due, today)}"
    if days == 0:
        return "vence hoy"
    if days == 1:
        return "vence mañana"
    if days == -1:
        return "venció ayer"
    return f"vence {when}" if days > 0 else f"venció {when}"


def bought_phrase(sold: date, today: date) -> str:
    days = (today - sold).days
    if days == 0:
        return "de hoy"
    if days == 1:
        return "de ayer"
    return f"del {_day(sold, today)}"


def money_text(value: Decimal, currency: str | None) -> str:
    """$45.000, or $45.000,50: how an amount is written in Argentina."""
    whole, cents = f"{Decimal(value):,.2f}".split(".")
    text = whole.replace(",", ".") + ("" if cents == "00" else f",{cents}")
    return ("US$" if currency == "USD" else "$") + text


def greeting(hour: int) -> str:
    if 5 <= hour < 12:
        return "Buen día"
    if 12 <= hour < 20:
        return "Buenas tardes"
    return "Buenas noches"


def _name(text: str | None) -> str:
    """A name as people write it: "JUAN PEREZ" or "juan" become "Juan Perez"
    and "Juan"; anything with its own capitals is left alone."""
    text = " ".join((text or "").split())
    return text.title() if text.isupper() or text.islower() else text


# --- the sale --------------------------------------------------------------

def _customer(db: Session, sale: Sale, company_id: int) -> Customer:
    """The customer a reminder goes to, or why there is no reminder to send."""
    if sale.status in NON_DEBT_STATUSES or Decimal(sale.balance) <= 0:
        raise ReminderError("La venta no tiene saldo pendiente.")
    customer = None
    if sale.customer_id is not None:
        customer = db.execute(
            select(Customer).where(
                Customer.id == sale.customer_id, Customer.company_id == company_id
            )
        ).scalar_one_or_none()
    if customer is None:
        raise ReminderError("La venta no tiene cliente.")
    return customer


def draft(db: Session, sale: Sale, *, company_id: int) -> ReminderDraft:
    """The three messages for this sale, and where they would go.

    A phone that cannot be read is not an error here: the console shows why
    and lets the seller fix it on the customer's file, then asks again.
    """
    customer = _customer(db, sale, company_id)
    company = db.get(Company, company_id)
    tz = clock.company_zone(db, company_id)
    now = clock._now().astimezone(tz)
    today = now.date()
    due = sale.promised_payment_date
    sold_at = sale.sold_at if sale.sold_at.tzinfo else sale.sold_at.replace(tzinfo=timezone.utc)

    first, last = _name(customer.first_name), _name(customer.last_name)
    facts = Facts(
        first_name=first,
        full_name=" ".join(p for p in (first, last) if p),
        shop=company.name if company else "la óptica",
        balance=money_text(sale.balance, company.currency if company else None),
        bought=bought_phrase(sold_at.astimezone(tz).date(), today),
        due=due_phrase(due, today),
        upcoming=due is not None and due >= today,
        greeting=greeting(now.hour),
    )
    try:
        number, problem = whatsapp.normalize(customer.phone), None
    except whatsapp.WhatsAppError as exc:
        number, problem = None, str(exc)
    return ReminderDraft(
        sale_id=sale.id,
        sale_number=sale.number,
        balance=sale.balance,
        promised_payment_date=due,
        customer_id=customer.id,
        customer_name=facts.full_name,
        phone=customer.phone,
        whatsapp_number=number,
        whatsapp_display=whatsapp.display(number) if number else None,
        phone_problem=problem,
        suggested_tone=suggest(None if due is None else (due - today).days),
        messages=[ReminderMessage(tone=tone, text=text) for tone, text in messages(facts).items()],
        reminders=[PaymentReminderRead.model_validate(r) for r in sale.payment_reminders],
    )


def record(
    db: Session, sale: Sale, data: ReminderSend, *, company_id: int, user_id: int | None
) -> PaymentReminder:
    """Keep the message the seller is sending.

    The number is read from the customer's file again here, never taken from
    the request: a reminder goes to the phone the shop registered.
    """
    customer = _customer(db, sale, company_id)
    try:
        number = whatsapp.normalize(customer.phone)
    except whatsapp.WhatsAppError as exc:
        raise ReminderError(str(exc)) from exc
    reminder = PaymentReminder(
        company_id=company_id,
        sale_id=sale.id,
        tone=data.tone.value,
        phone=number,
        message=data.message,
        sent_by_user_id=user_id,
    )
    db.add(reminder)
    db.commit()
    db.refresh(reminder)
    return reminder
