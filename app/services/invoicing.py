"""Facturación electrónica: which comprobante a sale gets, and getting it.

A comprobante is a second step, never part of the sale. A sale is one
transaction (CLAUDE.md rule 10) and stays one: it commits first, and only on
the Facturar button does anyone ask ARCA for anything. An ARCA outage
therefore never blocks a sale, and no transaction is ever held open across a
network call.

What a comprobante says is decided here and nowhere else:

* **The class** follows from the shop's IVA condition and the buyer's. A
  Monotributista or Exento issues C. A Responsable Inscripto issues A to a
  buyer arca-api accepts for A (RI and the monotributos), with their CUIT, and
  B to everyone else. A customer with no condition is a consumidor final.
* **The lines** are the sale's own, at the price charged, each with its
  bonificación: the line's own discount plus its share of the sale's discount,
  spread by largest remainder. arca-api computes the total the same way
  (quantity times price, half up, minus the bonificación), so the comprobante
  adds up to ``sale.total`` to the cent.
* **Prices are final**, IVA included, as an Argentine shop quotes them. The
  alícuota of a line comes from its product type, 21% when unset.

Why a retry can never invoice twice (see ``models/invoicing.py``): the row,
its key and its exact body are committed before the first byte leaves, and a
pending comprobante is only ever resent under that key, never rebuilt. A
rejected one used no number, so the next attempt is a new row with a new key.
"""
from __future__ import annotations

import json
import logging
import re
import secrets
import unicodedata
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.branch import Branch
from app.models.customer import Customer
from app.models.enums import (
    DocumentType,
    InvoiceStatus,
    InvoiceType,
    IvaCondition,
    IvaRate,
    SaleStatus,
)
from app.models.invoicing import ArcaIssuer, Invoice, InvoicingRequest
from app.models.product import Product
from app.models.sales import Sale, SaleItem
from app.services import arca, platform

logger = logging.getLogger("app.invoicing")

CENTS = Decimal("0.01")
PENDING = InvoiceStatus.PENDING.value
AUTHORIZED = InvoiceStatus.AUTHORIZED.value
REJECTED = InvoiceStatus.REJECTED.value

INVOICE_TYPES = {"A": InvoiceType.INVOICE_A, "B": InvoiceType.INVOICE_B,
                 "C": InvoiceType.INVOICE_C}
CREDIT_NOTE_TYPES = {"A": InvoiceType.CREDIT_NOTE_A, "B": InvoiceType.CREDIT_NOTE_B,
                     "C": InvoiceType.CREDIT_NOTE_C}
FACTURAS = tuple(t.value for t in INVOICE_TYPES.values())
CREDIT_NOTES = tuple(t.value for t in CREDIT_NOTE_TYPES.values())
# arca-api's names for them.
ARCA_TYPE = {
    InvoiceType.INVOICE_A: "FACTURA_A", InvoiceType.INVOICE_B: "FACTURA_B",
    InvoiceType.INVOICE_C: "FACTURA_C", InvoiceType.CREDIT_NOTE_A: "NOTA_CREDITO_A",
    InvoiceType.CREDIT_NOTE_B: "NOTA_CREDITO_B", InvoiceType.CREDIT_NOTE_C: "NOTA_CREDITO_C",
}
LABELS = {
    InvoiceType.INVOICE_A: "Factura A", InvoiceType.INVOICE_B: "Factura B",
    InvoiceType.INVOICE_C: "Factura C", InvoiceType.CREDIT_NOTE_A: "Nota de crédito A",
    InvoiceType.CREDIT_NOTE_B: "Nota de crédito B", InvoiceType.CREDIT_NOTE_C: "Nota de crédito C",
}

# The buyers a Responsable Inscripto invoices with an A (arca-api's
# RECEIVER_CONDITIONS_BY_CLASS). Every other condition gets a B.
CLASS_A_BUYERS = frozenset({
    IvaCondition.RESPONSABLE_INSCRIPTO.value,
    IvaCondition.MONOTRIBUTO.value,
    IvaCondition.MONOTRIBUTO_SOCIAL.value,
    IvaCondition.MONOTRIBUTO_TRABAJADOR_INDEPENDIENTE_PROMOVIDO.value,
})
CONDITION_LABELS = {
    IvaCondition.RESPONSABLE_INSCRIPTO.value: "Responsable Inscripto",
    IvaCondition.MONOTRIBUTO.value: "Monotributista",
    IvaCondition.EXENTO.value: "Exento",
    IvaCondition.CONSUMIDOR_FINAL.value: "Consumidor final",
}
ARCA_RATES: dict[str, Any] = {
    IvaRate.RATE_0.value: 0, IvaRate.RATE_2_5.value: 2.5, IvaRate.RATE_5.value: 5,
    IvaRate.RATE_10_5.value: 10.5, IvaRate.RATE_21.value: 21, IvaRate.RATE_27.value: 27,
    IvaRate.EXEMPT.value: "EXEMPT", IvaRate.UNTAXED.value: "UNTAXED",
}
# From this total a consumidor final has to be identified (RG 5866/2026).
# arca-api refuses it too; checking first says so in Spanish.
IDENTIFY_FROM = Decimal("10000000")
# A screen polling a pending comprobante asks arca-api at most this often.
REFRESH_EVERY = timedelta(seconds=5)
MISSING_FOR_PDF = {
    "commercialAddress": "domicilio comercial",
    "grossIncomeTax": "Ingresos Brutos",
    "activityStartDate": "fecha de inicio de actividades",
}


class InvoicingError(Exception):
    """Raised when a comprobante cannot be requested, shown, or printed as asked."""


# --- reading ------------------------------------------------------------------
def issuer_for(db: Session, company_id: int) -> ArcaIssuer | None:
    """The company's active link to arca-api, if invoicing is on for it."""
    return db.execute(
        select(ArcaIssuer).where(
            ArcaIssuer.company_id == company_id, ArcaIssuer.is_active.is_(True)
        )
    ).scalar_one_or_none()


def status(db: Session, company_id: int) -> dict:
    """What the console needs to know before showing a Facturar button."""
    issuer = issuer_for(db, company_id)
    if issuer is None:
        return {"enabled": False, "available": available(), "iva_condition": None, "classes": []}
    return {
        "enabled": arca.configured(),
        "available": available(),
        "iva_condition": issuer.iva_condition,
        "classes": classes_for(issuer.iva_condition),
        "legal_name": issuer.legal_name,
        "cuit": issuer.cuit,
        "point_of_sale": issuer.point_of_sale,
    }


def classes_for(issuer_condition: str) -> list[str]:
    return ["A", "B"] if issuer_condition == IvaCondition.RESPONSABLE_INSCRIPTO.value else ["C"]


def get_invoice(db: Session, invoice_id: int, *, company_id: int) -> Invoice | None:
    return db.execute(
        select(Invoice).where(Invoice.id == invoice_id, Invoice.company_id == company_id)
    ).scalar_one_or_none()


def list_invoices(
    db: Session, *, company_id: int, status: InvoiceStatus | None = None,
    sale_id: int | None = None, limit: int = 100,
) -> list[Invoice]:
    stmt = select(Invoice).where(Invoice.company_id == company_id)
    if status is not None:
        stmt = stmt.where(Invoice.status == status.value)
    if sale_id is not None:
        stmt = stmt.where(Invoice.sale_id == sale_id)
    return list(db.execute(stmt.order_by(Invoice.id.desc()).limit(limit)).scalars())


def label(invoice: Invoice) -> str:
    """"Factura B 00002-00000184", the way the shop names it."""
    kind = LABELS[InvoiceType(invoice.type)]
    return f"{kind} {invoice.formatted_number}" if invoice.formatted_number else kind


# --- deciding what a comprobante says ------------------------------------------
def invoice_class(issuer_condition: str, buyer_condition: str) -> str:
    if issuer_condition != IvaCondition.RESPONSABLE_INSCRIPTO.value:
        return "C"
    return "A" if buyer_condition in CLASS_A_BUYERS else "B"


def normalize_document_type(text: str | None) -> DocumentType | None:
    return DocumentType.parse(text)


def spread(total: int, weights: list[int]) -> list[int]:
    """Split ``total`` cents over ``weights`` in proportion, exactly.

    Largest remainder: everyone gets the floor of their share, and the cents
    left over go to the largest fractions. No share exceeds its weight while
    the total does not exceed their sum, which a capped discount never does.
    """
    base = sum(weights)
    if total <= 0 or base <= 0:
        return [0] * len(weights)
    raw = [total * w for w in weights]
    shares = [r // base for r in raw]
    order = sorted(range(len(weights)), key=lambda i: (-(raw[i] % base), -weights[i], i))
    for i in order[: total - sum(shares)]:
        shares[i] += 1
    return shares


def _cents(value: Decimal | int | float) -> int:
    return int((Decimal(value) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _number(value: Decimal) -> int | float:
    """A JSON number with no trailing zeros: 185000, 33.34, 1.5."""
    value = Decimal(value)
    return int(value) if value == value.to_integral_value() else float(value)


def _describe(product: Product) -> str:
    text = f"{product.code} - {product.description}" if product.description else product.code
    return text[:250]


def _receiver(customer: Customer | None, klass: str, total: Decimal) -> dict:
    if customer is None:
        receiver = {"docType": "SIN_IDENTIFICAR", "ivaCondition": "CONSUMIDOR_FINAL"}
        return _identified_enough(receiver, total)
    condition = customer.iva_condition or IvaCondition.CONSUMIDOR_FINAL.value
    name = f"{customer.first_name} {customer.last_name}".strip()
    digits = re.sub(r"\D", "", customer.document_number or "")
    doc = normalize_document_type(customer.document_type) if digits else None
    if digits and customer.document_type and doc is None:
        raise InvoicingError(
            f"ARCA no acepta el tipo de documento de {name} ({customer.document_type}). "
            "Elegí DNI, CUIT, CUIL, CDI o pasaporte en su ficha."
        )
    if klass == "A" and doc is not DocumentType.CUIT:
        raise InvoicingError(
            f"{name} es {CONDITION_LABELS.get(condition, condition)}: la factura A "
            "necesita su CUIT. Cargalo en su ficha, con tipo de documento CUIT."
        )
    if doc in (DocumentType.CUIT, DocumentType.CUIL) and len(digits) != 11:
        raise InvoicingError(f"El {doc.value} de {name} tiene que tener 11 dígitos.")
    if len(digits) > 11:
        raise InvoicingError(f"El documento de {name} tiene más de 11 dígitos.")
    receiver: dict[str, Any] = {"ivaCondition": condition.upper(), "name": name[:250]}
    if doc is None:
        if condition != IvaCondition.CONSUMIDOR_FINAL.value:
            raise InvoicingError(
                f"{name} es {CONDITION_LABELS.get(condition, condition)} y tiene que "
                "estar identificado: cargá su CUIT en la ficha."
            )
        receiver["docType"] = "SIN_IDENTIFICAR"
        return _identified_enough(receiver, total)
    receiver["docType"] = doc.value
    receiver["docNumber"] = digits
    if customer.address:
        receiver["address"] = customer.address[:250]
    return receiver


def _identified_enough(receiver: dict, total: Decimal) -> dict:
    if Decimal(total) >= IDENTIFY_FROM:
        raise InvoicingError(
            "Desde $10.000.000 el comprador tiene que estar identificado "
            "(RG 5866/2026): elegí un cliente con DNI o CUIT."
        )
    return receiver


def _items(db: Session, sale: Sale, klass: str) -> list[dict]:
    lines: list[SaleItem] = sorted(sale.items, key=lambda line: line.id)
    shares = spread(_cents(sale.discount_amount), [_cents(line.line_total) for line in lines])
    items = []
    for line, share in zip(lines, shares):
        item: dict[str, Any] = {
            "description": _describe(line.product),
            "quantity": _number(line.quantity),
            "unitPrice": _number(line.unit_price),
        }
        discount = _cents(line.discount_amount) + share
        if discount:
            item["discount"] = _number(Decimal(discount) / 100)
        if klass != "C":
            rate = line.product.product_type.iva_rate or IvaRate.RATE_21.value
            item["ivaRate"] = ARCA_RATES[rate]
        items.append(item)
    return items


def _sale_condition(sale: Sale) -> str:
    """Condiciones de venta, which the comprobante has to print."""
    return "Cuenta corriente" if Decimal(sale.balance) > 0 else "Contado"


def _point_of_sale(db: Session, sale: Sale, issuer: ArcaIssuer) -> int:
    if sale.branch_id is not None:
        branch_pos = db.execute(
            select(Branch.point_of_sale).where(Branch.id == sale.branch_id)
        ).scalar_one_or_none()
        if branch_pos:
            return branch_pos
    return issuer.point_of_sale


def _new_key(sale: Sale, kind: str) -> str:
    # Random, and written down before it is used: a reset development
    # database reuses sale numbers, and arca-api must never take that for a
    # retry of an older comprobante.
    return f"sgi-{sale.company_id}-{sale.number}-{kind}-{secrets.token_hex(5)}"


def _dumps(body: dict) -> str:
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"))


# --- asking for one ----------------------------------------------------------
def _lock(db: Session, sale: Sale) -> SaleStatus:
    """Hold the sale's row until the next commit, and say where it stands now.

    Facturar and Anular both take it, so neither acts on what the other has
    just changed: two Facturar clicks get one factura, and a sale cancelled a
    moment ago is not invoiced afterwards. A no-op on SQLite.
    """
    return db.execute(
        select(Sale.status).where(Sale.id == sale.id).with_for_update()
    ).scalar_one()


def _current(db: Session, sale_id: int, types: tuple[str, ...]) -> Invoice | None:
    """The live attempt of a kind: the one that is not rejected, if any."""
    return db.execute(
        select(Invoice)
        .where(Invoice.sale_id == sale_id, Invoice.type.in_(types),
               Invoice.status != REJECTED)
        .order_by(Invoice.id.desc())
    ).scalars().first()


def request_invoice(
    db: Session, sale: Sale, *, company_id: int, user_id: int | None = None
) -> Invoice:
    """The Facturar button. Asking twice returns the factura already asked for."""
    issuer = issuer_for(db, company_id)
    if issuer is None:
        raise InvoicingError(
            "La facturación electrónica no está activada para esta óptica. "
            "Pedila a soporte."
        )
    if not arca.configured():
        raise InvoicingError("La facturación electrónica no está configurada en este servidor.")
    if sale.status is SaleStatus.QUOTE:
        raise InvoicingError("Un presupuesto no se factura. Confirmá la venta primero.")
    if sale.status is SaleStatus.CANCELLED:
        raise InvoicingError("Una venta anulada no se factura.")
    if Decimal(sale.total) <= 0:
        raise InvoicingError("Una venta de $0 no se factura.")

    if _lock(db, sale) is SaleStatus.CANCELLED:
        raise InvoicingError("Una venta anulada no se factura.")
    current = _current(db, sale.id, FACTURAS)
    if current is not None:
        db.commit()   # release the lock before anything leaves
        return refresh(db, current)

    customer = db.get(Customer, sale.customer_id) if sale.customer_id else None
    buyer = (customer.iva_condition if customer else None) or IvaCondition.CONSUMIDOR_FINAL.value
    klass = invoice_class(issuer.iva_condition, buyer)
    invoice_type = INVOICE_TYPES[klass]
    point_of_sale = _point_of_sale(db, sale, issuer)
    body: dict[str, Any] = {
        "type": ARCA_TYPE[invoice_type],
        "pointOfSale": point_of_sale,
        "concept": "PRODUCTS",
        "receiver": _receiver(customer, klass, sale.total),
        "saleCondition": _sale_condition(sale),
        "items": _items(db, sale, klass),
    }
    if klass != "C":
        body["pricesIncludeIva"] = True

    invoice = Invoice(
        company_id=company_id, sale_id=sale.id, type=invoice_type.value, status=PENDING,
        arca_issuer_id=issuer.issuer_id, idempotency_key=_new_key(sale, "factura"),
        request_body="", point_of_sale=point_of_sale, total=sale.total,
        requested_by_user_id=user_id,
    )
    db.add(invoice)
    db.flush()
    body["metadata"] = _metadata(sale, invoice)
    invoice.request_body = _dumps(body)
    # Committed before the request leaves: from here on, whatever happens,
    # this row knows which key to ask again under.
    db.commit()
    return _send(db, invoice)


def request_credit_note(
    db: Session, sale: Sale, *, company_id: int, user_id: int | None = None
) -> Invoice:
    """The nota de crédito that reverses a cancelled sale's factura.

    It repeats the factura's own lines and receiver, so it reverses exactly
    what was invoiced, and goes out under the factura's issuer even if
    invoicing has been switched off since: a fiscal record must stay
    reversible.
    """
    if sale.status is not SaleStatus.CANCELLED:
        raise InvoicingError("La nota de crédito se emite al anular la venta.")
    _lock(db, sale)
    factura = db.execute(
        select(Invoice)
        .where(Invoice.sale_id == sale.id, Invoice.type.in_(FACTURAS),
               Invoice.status == AUTHORIZED)
        .order_by(Invoice.id.desc())
    ).scalars().first()
    if factura is None:
        raise InvoicingError("La venta no tiene una factura autorizada que revertir.")
    current = db.execute(
        select(Invoice).where(Invoice.credited_invoice_id == factura.id,
                              Invoice.status != REJECTED)
    ).scalars().first()
    if current is not None:
        db.commit()
        return refresh(db, current)

    klass = InvoiceType(factura.type).value[-1].upper()
    note_type = CREDIT_NOTE_TYPES[klass]
    body = json.loads(factura.request_body)
    body["type"] = ARCA_TYPE[note_type]
    body["associated"] = [{"invoiceId": factura.arca_invoice_id}]
    note = Invoice(
        company_id=company_id, sale_id=sale.id, type=note_type.value, status=PENDING,
        credited_invoice_id=factura.id, arca_issuer_id=factura.arca_issuer_id,
        idempotency_key=_new_key(sale, "nc"), request_body="",
        point_of_sale=factura.point_of_sale, total=factura.total,
        requested_by_user_id=user_id,
    )
    db.add(note)
    db.flush()
    body["metadata"] = _metadata(sale, note)
    note.request_body = _dumps(body)
    db.commit()
    return _send(db, note)


def credit_note_if_invoiced(
    db: Session, sale: Sale, *, company_id: int, user_id: int | None = None
) -> Invoice | None:
    """After a cancellation: reverse the factura, if the sale had one.

    Never undoes the cancellation. Whatever ARCA answers is recorded on the
    nota de crédito itself, which the sale shows and can retry.
    """
    if not any(i.type in FACTURAS and i.status == AUTHORIZED for i in sale.invoices):
        return None
    try:
        return request_credit_note(db, sale, company_id=company_id, user_id=user_id)
    except InvoicingError:
        logger.exception("Could not request the credit note for sale %s", sale.id)
        return None


def assert_cancellable(db: Session, sale: Sale) -> None:
    """A sale whose factura is still with ARCA cannot be cancelled yet.

    arca-api cannot withdraw a comprobante it has not settled, so cancelling
    now could leave an authorized factura behind with nothing to reverse it.
    Read under the sale's lock, which the cancellation then holds until it
    commits, so a Facturar arriving meanwhile waits and finds it cancelled.
    """
    _lock(db, sale)
    pending = db.execute(
        select(Invoice.id).where(Invoice.sale_id == sale.id, Invoice.type.in_(FACTURAS),
                                 Invoice.status == PENDING)
    ).first()
    if pending is not None:
        raise InvoicingError(
            "La factura de esta venta todavía está en trámite con ARCA. "
            "Anulala cuando se autorice o se rechace."
        )


def _metadata(sale: Sale, invoice: Invoice) -> dict[str, str]:
    return {"sgi_company_id": str(sale.company_id), "sgi_sale_id": str(sale.id),
            "sgi_sale_number": sale.number, "sgi_invoice_id": str(invoice.id)}


# --- following one up ------------------------------------------------------------
def refresh(db: Session, invoice: Invoice, *, force: bool = False) -> Invoice:
    """Ask arca-api what became of a pending comprobante. Settled ones are final."""
    if invoice.status != PENDING:
        return invoice
    if not force and invoice.last_checked_at is not None:
        if _now() - _aware(invoice.last_checked_at) < REFRESH_EVERY:
            return invoice
    if invoice.arca_invoice_id is None:
        # No answer ever arrived, so arca-api's id is unknown. Asking again
        # under the same key is how to find out: it returns what it has.
        return _send(db, invoice)
    issuer_id, arca_id = invoice.arca_issuer_id, invoice.arca_invoice_id
    db.commit()   # no transaction stays open across the network call
    reply = arca.get_invoice(issuer_id, arca_id)
    _apply(invoice, reply, posted=False)
    db.commit()
    db.refresh(invoice)
    return invoice


def retry(db: Session, invoice: Invoice) -> Invoice:
    """Resend a pending comprobante under its own key.

    Also how to restart one arca-api stopped retrying (it gives up 24 hours
    after creating it). A rejected one is not retried: ask for a new one.
    """
    if invoice.status != PENDING:
        raise InvoicingError("Solo se reintenta un comprobante en trámite.")
    return _send(db, invoice)


def pdf(db: Session, invoice: Invoice) -> tuple[bytes, str]:
    """The printable comprobante, as arca-api renders it, and a file name."""
    if invoice.status != AUTHORIZED:
        raise InvoicingError("Solo un comprobante autorizado tiene PDF: el CAE es parte de él.")
    reply = arca.invoice_pdf(invoice.arca_issuer_id, invoice.arca_invoice_id)
    if reply.status == 200 and reply.content:
        name = f"{label(invoice)}.pdf".lower().replace(" ", "-")
        name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
        return reply.content, name
    body = reply.body or {}
    if body.get("code") == "ISSUER_INCOMPLETE":
        missing = ", ".join(MISSING_FOR_PDF.get(m, m) for m in body.get("missing", []))
        raise InvoicingError(
            f"Para imprimir el comprobante faltan datos fiscales de la óptica: {missing}. "
            "Pedí a soporte que los cargue."
        )
    raise InvoicingError(
        f"No se pudo obtener el PDF: {reply.unreachable or _problem_text(body, reply.status)}"
    )


def _send(db: Session, invoice: Invoice) -> Invoice:
    issuer_id, body, key = invoice.arca_issuer_id, invoice.request_body, invoice.idempotency_key
    db.commit()   # no transaction stays open across the network call
    reply = arca.create_invoice(issuer_id, body, key)
    _apply(invoice, reply, posted=True)
    db.commit()
    db.refresh(invoice)
    return invoice


def _apply(invoice: Invoice, reply: arca.Reply, *, posted: bool) -> None:
    """Fold arca-api's answer into the row.

    The rule that keeps a retry from invoicing twice: a comprobante only
    becomes REJECTED when arca-api says so, or when a POST was refused
    before arca-api stored anything (a 4xx with no ``invoiceId``). No answer,
    a 5xx, or a problem naming an invoice all leave it PENDING, to be asked
    about again under the same key.
    """
    invoice.last_checked_at = _now()
    if reply.unreachable is not None:
        invoice.error = _plain(
            f"Sin respuesta de ARCA ({reply.unreachable}). Queda en trámite: "
            "se puede reintentar sin riesgo de facturar dos veces."
        )
        return
    body = reply.body or {}
    if "status" in body and "id" in body and isinstance(body["status"], str):
        _apply_invoice(invoice, body)
        return
    if body.get("invoiceId"):
        invoice.arca_invoice_id = invoice.arca_invoice_id or body["invoiceId"]
        invoice.error = _problem_text(body, reply.status)
        return
    if posted and 400 <= reply.status < 500:
        invoice.status = REJECTED
        invoice.error = "No se emitió: " + _problem_text(body, reply.status)
        return
    invoice.error = _problem_text(body, reply.status)


def _apply_invoice(invoice: Invoice, body: dict) -> None:
    invoice.arca_invoice_id = body["id"]
    state = body["status"]
    if state == "AUTHORIZED":
        invoice.status = AUTHORIZED
        invoice.number = body.get("number")
        invoice.formatted_number = body.get("formattedNumber")
        invoice.issue_date = _date(body.get("issueDate"))
        invoice.cae = body.get("cae")
        invoice.cae_due_date = _date(body.get("caeDueDate"))
        invoice.authorized_at = _datetime(body.get("authorizedAt")) or _now()
        invoice.error = None
        total = (body.get("totals") or {}).get("total")
        if total is not None:
            authorized = Decimal(str(total)).quantize(CENTS, rounding=ROUND_HALF_UP)
            if authorized != Decimal(invoice.total):
                # The arithmetic above exists so this never happens; an
                # arca-api too old to know ``discount`` would cause it, since
                # it drops unknown fields and authorizes the full price. The
                # record keeps what ARCA authorized, which is the fiscal truth,
                # so the sale shows the difference and a nota de crédito can
                # correct it.
                logger.error("Invoice %s: ARCA authorized %s, SGI asked for %s",
                             invoice.id, authorized, invoice.total)
                invoice.total = authorized
    elif state == "REJECTED":
        invoice.status = REJECTED
        errors = (body.get("arca") or {}).get("errors") or []
        reasons = "; ".join(f"{e.get('msg')} ({e.get('code')})" for e in errors)
        invoice.error = _plain("ARCA lo rechazó: " + (reasons or body.get("lastError") or "sin motivo"))
    else:
        invoice.error = _plain(body.get("lastError") or "En trámite con ARCA.")


def _problem_text(body: dict, status_code: int) -> str:
    detail = body.get("detail") or f"error {status_code} del servicio de facturación"
    extra = "; ".join(
        f"{e.get('path')}: {e.get('message')}" for e in body.get("errors") or []
        if isinstance(e, dict)
    )
    return _plain(f"{detail} ({extra})" if extra else detail)


def _plain(text: str) -> str:
    """No em dashes reach the screen (CLAUDE.md), whoever wrote the message."""
    return text.replace(" — ", ", ").replace("—", "-")[:1000]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _aware(value: datetime) -> datetime:
    # SQLite hands timestamps back without their zone; they were stored UTC.
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value[:10]) if value else None


def _datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# --- the guide in Empresa ----------------------------------------------------
# How a shop gets here, the way invoicing providers do it: it creates a punto
# de venta for web services and delegates Facturación Electrónica to our CUIT
# at ARCA, then sends its data from the guide. We accept the delegation at
# ARCA and activate it from /admin (``platform.link_tenant_invoicing``). The
# guide only ever writes a request: the link stays ours to make.
SETUP_FIELDS = ("cuit", "legal_name", "iva_condition", "point_of_sale", "commercial_address",
                "gross_income_tax", "activity_start_date", "trade_name")
REQUIRED_TO_SUBMIT = {
    "cuit": "CUIT", "legal_name": "razón social", "iva_condition": "condición frente al IVA",
    "point_of_sale": "punto de venta", "commercial_address": "domicilio comercial",
    "gross_income_tax": "Ingresos Brutos", "activity_start_date": "inicio de actividades",
}


def available() -> bool:
    """Whether this server can take shops through the guide at all."""
    return arca.configured() and bool(settings.arca_platform_cuit)


def _link(db: Session, company_id: int) -> ArcaIssuer | None:
    """The link whether or not it is paused (``issuer_for`` is active only)."""
    return db.execute(
        select(ArcaIssuer).where(ArcaIssuer.company_id == company_id)
    ).scalar_one_or_none()


def _request(db: Session, company_id: int) -> InvoicingRequest | None:
    return db.execute(
        select(InvoicingRequest).where(InvoicingRequest.company_id == company_id)
    ).scalar_one_or_none()


def setup(db: Session, company_id: int) -> dict:
    """Where the shop stands in the guide, and what it declared."""
    link = _link(db, company_id)
    request = _request(db, company_id)
    if link is not None:
        state = "active" if link.is_active else "paused"
    elif request is not None:
        state = "submitted" if request.submitted_at else "draft"
    else:
        state = "not_started"
    return {
        "available": available(),
        "state": state,
        "platform_cuit": settings.arca_platform_cuit or None,
        "platform_name": settings.arca_platform_name or None,
        "request": request,
        "issuer": None if link is None else {
            "cuit": link.cuit, "legal_name": link.legal_name,
            "iva_condition": link.iva_condition, "classes": classes_for(link.iva_condition),
            "point_of_sale": link.point_of_sale, "since": link.created_at,
        },
    }


def save_request(db: Session, data, *, company_id: int, user_id: int | None) -> dict:
    """Keep what the shop typed; with ``submit``, tell us it is ready.

    ``data`` is an ``InvoicingRequestWrite``. A draft keeps whatever it has. A
    submission needs everything the issuer and its printed comprobante need,
    clears our earlier note (it is the shop's answer to it) and mails us.
    """
    if not available():
        raise InvoicingError("La facturación electrónica todavía no está disponible.")
    if _link(db, company_id) is not None:
        raise InvoicingError(
            "La facturación ya está activa. Para cambiar estos datos, escribinos."
        )
    request = _request(db, company_id) or InvoicingRequest(company_id=company_id)
    for field in SETUP_FIELDS:
        value = getattr(data, field)
        setattr(request, field, value.value if isinstance(value, IvaCondition) else value)
    if data.submit:
        missing = [label for field, label in REQUIRED_TO_SUBMIT.items()
                   if not getattr(request, field)]
        if missing:
            raise InvoicingError("Para enviar falta completar: " + ", ".join(missing) + ".")
        request.submitted_at = _now()
        request.submitted_by_user_id = user_id
        request.provider_note = None
    db.add(request)
    db.commit()
    if data.submit:
        platform.notify_invoicing_request(db, company_id)
    return setup(db, company_id)


def check(db: Session, company_id: int) -> dict:
    """The Verificar button: ask ARCA, through arca-api, whether it would
    let us invoice for this shop's CUIT right now, and say it plainly."""
    link = _link(db, company_id)
    if link is None:
        raise InvoicingError("La facturación electrónica todavía no está activa.")
    issuer_id, point_of_sale = link.issuer_id, link.point_of_sale
    db.commit()   # no transaction stays open across the network call
    reply = arca.issuer_health(issuer_id)
    if not reply.ok:
        raise InvoicingError(
            f"No se pudo verificar: {reply.unreachable or _problem_text(reply.body or {}, reply.status)}"
        )
    ok, message = _health_message(reply.body or {})
    points = [p for p in ((reply.body or {}).get("invoicing") or {}).get("pointsOfSale") or []
              if isinstance(p, dict)]
    numbers = [p.get("number") for p in points if not p.get("blocked")]
    if ok and points and point_of_sale not in numbers:
        ok = False
        message = (f"ARCA no muestra el punto de venta {point_of_sale} entre tus puntos de venta "
                   f"para web services ({', '.join(map(str, numbers)) or 'ninguno'}). "
                   "Revisá el número, o escribinos para cambiarlo.")
    return {"ok": ok, "message": message, "points_of_sale": numbers, "checked_at": _now()}


def _health_message(health: dict) -> tuple[bool, str]:
    if not (health.get("arca") or {}).get("ok"):
        return False, "ARCA no está respondiendo en este momento. Probá de nuevo en un rato."
    if not (health.get("authentication") or {}).get("ok"):
        return False, ("No pudimos identificarnos ante ARCA. Es de nuestro lado: "
                       "si sigue así en un rato, escribinos.")
    invoicing_part = health.get("invoicing") or {}
    if not invoicing_part.get("ok"):
        error = invoicing_part.get("error") or ""
        if "relaciones" in error.lower() or "600" in error or "601" in error:
            return False, ("ARCA todavía no muestra la delegación de Facturación Electrónica a "
                           "nuestro CUIT. Si ya la hiciste, puede tardar hasta 24 horas.")
        return False, _plain(f"ARCA todavía no nos deja facturar por tu CUIT: {error}")
    return True, "ARCA confirma que podemos facturar por tu CUIT. Ya podés facturar tus ventas."


__all__ = [
    "InvoicingError", "issuer_for", "status", "classes_for", "get_invoice",
    "list_invoices", "label", "invoice_class", "normalize_document_type", "spread",
    "request_invoice", "request_credit_note", "credit_note_if_invoiced",
    "assert_cancellable", "refresh", "retry", "pdf", "available", "setup",
    "save_request", "check",
]
