from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from app.models.enums import ISSUER_IVA_CONDITIONS, InvoiceStatus, InvoiceType, IvaCondition
from app.schemas.common import ORMBase


class InvoiceRead(ORMBase):
    """A comprobante as the shop sees it. The body sent and the key stay inside."""

    id: int
    sale_id: int
    type: InvoiceType
    status: InvoiceStatus
    credited_invoice_id: int | None = None
    point_of_sale: int
    number: int | None = None
    formatted_number: str | None = None
    issue_date: date | None = None
    cae: str | None = None
    cae_due_date: date | None = None
    total: Decimal
    error: str | None = None
    authorized_at: datetime | None = None
    created_at: datetime


def valid_cuit(digits: str) -> bool:
    """A CUIT's last digit checks the other ten (mod 11), which catches most typos."""
    if not re.fullmatch(r"\d{11}", digits):
        return False
    total = sum(int(d) * w for d, w in zip(digits, (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)))
    check = 11 - total % 11
    check = 0 if check == 11 else check
    return check != 10 and check == int(digits[10])


def cuit_digits(value: str | None) -> str | None:
    """``"20-12345678-9"`` -> ``"20123456789"``; refused unless it checks out."""
    if value is None or not value.strip():
        return None
    digits = re.sub(r"\D", "", value)
    if not valid_cuit(digits):
        raise ValueError("El CUIT no es válido: revisá los 11 dígitos.")
    return digits


class InvoicingStatus(BaseModel):
    """Whether this shop invoices, and as what. Drives the Facturar button."""

    enabled: bool
    # Whether this server could invoice for it at all, so the console can
    # point a shop that does not invoice yet at the guide in Empresa.
    available: bool = False
    iva_condition: IvaCondition | None = None
    classes: list[str] = Field(default_factory=list)
    legal_name: str | None = None
    cuit: str | None = None
    point_of_sale: int | None = None


# --- provider side (/api/admin) ---------------------------------------------
def _issuer_condition(value: IvaCondition | None) -> IvaCondition | None:
    if value is not None and value not in ISSUER_IVA_CONDITIONS:
        raise ValueError("Un emisor es Responsable Inscripto, Monotributista o Exento.")
    return value


class FiscalData(BaseModel):
    """What a printed comprobante has to show about the shop (RG 1415).

    arca-api refuses the PDF until the first three are set, but not the
    invoice itself, so they can follow the link.
    """

    commercial_address: str | None = Field(None, max_length=250)
    gross_income_tax: str | None = Field(None, max_length=60)
    activity_start_date: date | None = None
    trade_name: str | None = Field(None, max_length=200)


class TenantInvoicingLink(FiscalData):
    """Turn invoicing on for a shop.

    With ``issuer_id``, link an issuer that already exists in arca-api (its
    CUIT, razón social and IVA condition are read from there). Without it,
    register the company's CUIT as a new delegated issuer, which needs
    ``iva_condition`` and takes the CUIT and razón social from the company
    unless given.
    """

    issuer_id: str | None = Field(None, max_length=40)
    cuit: str | None = None
    legal_name: str | None = Field(None, max_length=200)
    iva_condition: IvaCondition | None = None
    point_of_sale: int = Field(ge=1, le=99998)

    _condition = field_validator("iva_condition")(_issuer_condition)
    _cuit = field_validator("cuit")(cuit_digits)


class TenantInvoicingUpdate(FiscalData):
    point_of_sale: int | None = Field(None, ge=1, le=99998)
    is_active: bool | None = None


# --- the shop's guide (Empresa -> Facturación electrónica) -------------------
class InvoicingRequestWrite(FiscalData):
    """Step 3 of the guide. Anything may be missing while it is a draft;
    ``submit`` is the shop saying it finished its steps at ARCA."""

    cuit: str | None = None
    legal_name: str | None = Field(None, max_length=200)
    iva_condition: IvaCondition | None = None
    point_of_sale: int | None = Field(None, ge=1, le=99998)
    submit: bool = False

    _condition = field_validator("iva_condition")(_issuer_condition)
    _cuit = field_validator("cuit")(cuit_digits)


class InvoicingRequestRead(ORMBase):
    cuit: str | None = None
    legal_name: str | None = None
    iva_condition: IvaCondition | None = None
    point_of_sale: int | None = None
    commercial_address: str | None = None
    gross_income_tax: str | None = None
    activity_start_date: date | None = None
    trade_name: str | None = None
    submitted_at: datetime | None = None
    provider_note: str | None = None


class InvoicingIssuerSummary(BaseModel):
    cuit: str
    legal_name: str
    iva_condition: IvaCondition
    classes: list[str]
    point_of_sale: int
    since: datetime


class InvoicingSetupRead(BaseModel):
    """Where the shop stands: ``not_started``, ``draft``, ``submitted`` (we
    have it), ``active`` or ``paused``."""

    available: bool
    state: str
    platform_cuit: str | None = None
    platform_name: str | None = None
    request: InvoicingRequestRead | None = None
    issuer: InvoicingIssuerSummary | None = None


class InvoicingCheck(BaseModel):
    """The Verificar button: what ARCA says about invoicing for this CUIT."""

    ok: bool
    message: str
    points_of_sale: list[int] = Field(default_factory=list)
    checked_at: datetime


class TenantInvoicingNote(BaseModel):
    """Our answer to a request, shown in the shop's guide. Empty clears it."""

    note: str | None = Field(None, max_length=500)


class TenantInvoicingRead(BaseModel):
    """The link as SGI stores it, plus what arca-api says about the issuer."""

    linked: bool
    configured: bool
    issuer_id: str | None = None
    cuit: str | None = None
    legal_name: str | None = None
    iva_condition: IvaCondition | None = None
    point_of_sale: int | None = None
    is_active: bool | None = None
    # arca-api's view, when it could be reached: fiscal data, missingForPdf,
    # the credential's state. Passed through as arca-api words it.
    issuer: dict | None = None
    error: str | None = None
    # What the shop declared in its guide, and ARCA's padrón for that CUIT,
    # so the condition (which can never change) is checked before activating.
    request: InvoicingRequestRead | None = None
    taxpayer: dict | None = None
    taxpayer_error: str | None = None
