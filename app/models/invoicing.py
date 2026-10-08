"""Facturación electrónica: the shop's link to arca-api and what it issued.

ARCA is reached through arca-api, a separate service (``services/arca.py`` is
the only code that talks to it). Two tables here:

* ``arca_issuers`` says which arca-api issuer a company invoices as. Only the
  provider writes it (``/api/admin``), so a shop can never point itself at
  another shop's CUIT.
* ``invoices`` holds every comprobante a sale gets: its factura and, if the
  sale is cancelled, the nota de crédito that reverses it.

A comprobante's number is ARCA's, never ``services.numbering``'s, and nothing
here is ever deleted or edited by hand: a fiscal record is corrected by
issuing another one.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import CompanyMixin, IDMixin, SoftDeleteMixin, TimestampMixin

if TYPE_CHECKING:
    from app.models.sales import Sale

MONEY = Numeric(12, 2)


class ArcaIssuer(IDMixin, CompanyMixin, TimestampMixin, SoftDeleteMixin, Base):
    """The arca-api issuer a company invoices as: one CUIT per company.

    ``cuit``, ``legal_name`` and ``iva_condition`` are copied from arca-api
    when the link is made. arca-api cannot change an issuer's IVA condition,
    and the class of every comprobante follows from it, so it is read here
    rather than asked of arca-api on every sale. ``is_active=False`` switches
    invoicing off for the shop without forgetting the link.
    """

    __tablename__ = "arca_issuers"
    __table_args__ = (
        UniqueConstraint("company_id", name="uq_arca_issuer_company"),
        # One arca-api issuer, one shop: two tenants sharing one would invoice
        # under each other's CUIT.
        UniqueConstraint("issuer_id", name="uq_arca_issuer_issuer"),
    )

    issuer_id: Mapped[str] = mapped_column(String(40), nullable=False)
    cuit: Mapped[str] = mapped_column(String(11), nullable=False)
    legal_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # IvaCondition value, one of ISSUER_IVA_CONDITIONS.
    iva_condition: Mapped[str] = mapped_column(String(40), nullable=False)
    # The company's punto de venta. A branch with its own overrides it.
    point_of_sale: Mapped[int] = mapped_column(Integer, nullable=False)


class Invoice(IDMixin, CompanyMixin, TimestampMixin, Base):
    """One comprobante of a sale, as SGI asked for it and as ARCA answered.

    ``request_body`` is the exact JSON sent and ``idempotency_key`` the key it
    went under. Both are written before the first request leaves, and a retry
    resends them byte for byte: arca-api refuses a key reused with another
    body, and a request that timed out may already have a CAE, so a pending
    comprobante is never rebuilt, only resent. A new key is only ever minted
    for a new row, which ``services.invoicing`` allows once the previous
    attempt is ``REJECTED``.
    """

    __tablename__ = "invoices"
    __table_args__ = (
        UniqueConstraint("company_id", "idempotency_key", name="uq_invoice_key"),
    )

    sale_id: Mapped[int] = mapped_column(
        ForeignKey("sales.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # InvoiceType / InvoiceStatus values.
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    # The factura a nota de crédito reverses.
    credited_invoice_id: Mapped[int | None] = mapped_column(
        ForeignKey("invoices.id", ondelete="RESTRICT")
    )

    # --- what was asked, kept verbatim for retries --------------------------
    arca_issuer_id: Mapped[str] = mapped_column(String(40), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    request_body: Mapped[str] = mapped_column(Text, nullable=False)
    point_of_sale: Mapped[int] = mapped_column(Integer, nullable=False)
    # What SGI invoiced, which is the sale's total for a factura.
    total: Mapped[Decimal] = mapped_column(MONEY, nullable=False)

    # --- what ARCA answered -------------------------------------------------
    arca_invoice_id: Mapped[str | None] = mapped_column(String(40))
    number: Mapped[int | None] = mapped_column(Integer)
    formatted_number: Mapped[str | None] = mapped_column(String(20))
    issue_date: Mapped[date | None] = mapped_column(Date)
    cae: Mapped[str | None] = mapped_column(String(20))
    cae_due_date: Mapped[date | None] = mapped_column(Date)
    # Why it is not authorized yet, or why it was rejected. Shown as is.
    error: Mapped[str | None] = mapped_column(String(1000))
    authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # When arca-api was last asked, so a screen polling it cannot hammer it.
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    requested_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )

    sale: Mapped["Sale"] = relationship(back_populates="invoices")


class InvoicingRequest(IDMixin, CompanyMixin, TimestampMixin, Base):
    """What a shop declared in its Facturación electrónica guide (Empresa).

    The shop fills it in while it does its steps at ARCA (a punto de venta for
    web services, the delegation to our CUIT) and sends it; we read it in
    /admin, accept the delegation at ARCA, and activate it, which registers
    the issuer (``ArcaIssuer``). It is a request, never a link: nothing here
    lets a shop invoice, so whose CUIT a shop invoices as stays our decision.

    Every field is optional until it is sent, so the guide can be left half
    done and picked up later.
    """

    __tablename__ = "invoicing_requests"
    __table_args__ = (UniqueConstraint("company_id", name="uq_invoicing_request_company"),)

    cuit: Mapped[str | None] = mapped_column(String(11))
    legal_name: Mapped[str | None] = mapped_column(String(200))
    # IvaCondition value, one of ISSUER_IVA_CONDITIONS.
    iva_condition: Mapped[str | None] = mapped_column(String(40))
    point_of_sale: Mapped[int | None] = mapped_column(Integer)
    commercial_address: Mapped[str | None] = mapped_column(String(250))
    gross_income_tax: Mapped[str | None] = mapped_column(String(60))
    activity_start_date: Mapped[date | None] = mapped_column(Date)
    trade_name: Mapped[str | None] = mapped_column(String(200))
    # When the shop said it finished its steps at ARCA. Null while a draft.
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # Our answer while it waits ("todavía no vemos la delegación"), shown in
    # the shop's guide. Sending again clears it.
    provider_note: Mapped[str | None] = mapped_column(String(500))
