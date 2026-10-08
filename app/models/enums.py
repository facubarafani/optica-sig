"""Controlled value lists (states/types) used across the domain.

Per the spec, any record with a "state" must use a controlled list rather than
free text. New values go here, never inline strings.
"""
from __future__ import annotations

import enum
import re
import unicodedata


class SupplierType(str, enum.Enum):
    MERCHANDISE = "merchandise"   # proveedor de mercadería
    LABORATORY = "laboratory"     # laboratorio
    WORKSHOP = "workshop"         # taller


class ChangeAction(str, enum.Enum):
    """What an operation did to one row (services.journal)."""

    CREATE = "create"   # the row did not exist before: undo deactivates it
    UPDATE = "update"   # columns changed: undo puts the old values back


class ColorAliasKind(str, enum.Enum):
    """What the tail of a product code turned out to mean.

    Decided once per spelling in the import's "Colores" step and remembered
    (services.importer.code_colors), so ``01/1009 C1`` and ``03/INDAH NERO``
    need an answer the first time only.
    """

    COLOR = "color"                       # uno o más colores del catálogo
    SUPPLIER_NUMBER = "supplier_number"   # número del proveedor: agrupa, sin color
    NOT_COLOR = "not_color"               # parte del modelo, no es un color


class PricingMode(str, enum.Enum):
    """How a product's selling price is determined."""

    MANUAL = "manual"             # precio propio, cargado a mano
    PRICE_LIST = "price_list"     # lista de precios + categoría


class Currency(str, enum.Enum):
    """Currencies a price list can be expressed in.

    Stored as a plain 3-letter code (``String(3)``) rather than a Postgres enum,
    matching ``companies.currency`` / ``company_settings.currency``. It is a
    label only: there is no exchange rate and nothing is converted — a list in
    USD holds US dollar prices.
    """

    ARS = "ARS"                   # pesos argentinos
    USD = "USD"                   # dólares


class RoundingMode(str, enum.Enum):
    """How a generated or adjusted price is rounded to the rounding step."""

    UP = "up"                     # hacia arriba (8.583 -> 8.600)
    NEAREST = "nearest"           # al más cercano
    DOWN = "down"                 # hacia abajo


class StockMovementType(str, enum.Enum):
    INBOUND = "inbound"           # ingreso
    OUTBOUND = "outbound"         # egreso
    ADJUSTMENT = "adjustment"     # ajuste
    TRANSFER = "transfer"         # transferencia entre sucursales


class TreatmentType(str, enum.Enum):
    MYOPIA = "myopia"             # miopía
    ASTIGMATISM = "astigmatism"   # astigmatismo
    HYPEROPIA = "hyperopia"       # hipermetropía
    PRESBYOPIA = "presbyopia"     # presbicia
    OTHER = "other"               # otro


class SaleStatus(str, enum.Enum):
    QUOTE = "quote"               # presupuesto
    CONFIRMED = "confirmed"       # confirmada
    PENDING = "pending"           # pendiente
    DELIVERED = "delivered"       # entregada
    CANCELLED = "cancelled"       # cancelada


class PaymentMethod(str, enum.Enum):
    """How the customer handed the money over."""

    CASH = "cash"                 # efectivo
    TRANSFER = "transfer"         # transferencia
    CARD = "card"                 # tarjeta


class DiscountType(str, enum.Enum):
    """How a discount value is read: a fixed sum, or a share of the base."""

    AMOUNT = "amount"             # importe fijo ($)
    PERCENT = "percent"           # porcentaje (%)


# --- Facturación electrónica (services.invoicing) ---------------------------
# The three lists below are stored as plain strings, like Currency: ARCA adds
# conditions and rates now and then, and a Postgres enum would turn each one
# into a migration. The names are ARCA's own (proper nouns, like DNI), so they
# map one to one onto arca-api's.


class IvaCondition(str, enum.Enum):
    """A taxpayer's condición frente al IVA.

    An issuer (the shop) is one of the first three; a buyer can be any of them.
    The buyer's decides the class a Responsable Inscripto issues: A or B.
    """

    RESPONSABLE_INSCRIPTO = "responsable_inscripto"
    MONOTRIBUTO = "monotributo"
    EXENTO = "exento"
    CONSUMIDOR_FINAL = "consumidor_final"
    NO_CATEGORIZADO = "no_categorizado"
    PROVEEDOR_EXTERIOR = "proveedor_exterior"
    CLIENTE_EXTERIOR = "cliente_exterior"
    IVA_LIBERADO_LEY_19640 = "iva_liberado_ley_19640"
    MONOTRIBUTO_SOCIAL = "monotributo_social"
    IVA_NO_ALCANZADO = "iva_no_alcanzado"
    MONOTRIBUTO_TRABAJADOR_INDEPENDIENTE_PROMOVIDO = (
        "monotributo_trabajador_independiente_promovido"
    )


ISSUER_IVA_CONDITIONS = (
    IvaCondition.RESPONSABLE_INSCRIPTO, IvaCondition.MONOTRIBUTO, IvaCondition.EXENTO,
)


class IvaRate(str, enum.Enum):
    """The alícuota a product type is sold at. Only class A and B carry it."""

    RATE_0 = "0"
    RATE_2_5 = "2.5"
    RATE_5 = "5"
    RATE_10_5 = "10.5"
    RATE_21 = "21"                # the general rate, and the default
    RATE_27 = "27"
    EXEMPT = "exempt"             # exento
    UNTAXED = "untaxed"           # no gravado


class DocumentType(str, enum.Enum):
    """How a customer is identified on a comprobante.

    The values are what shops already typed into the free-text field (``DNI``,
    ``CUIT``), so existing rows read as members without a data migration.
    """

    DNI = "DNI"
    CUIT = "CUIT"
    CUIL = "CUIL"
    CDI = "CDI"
    PASSPORT = "PASAPORTE"
    FOREIGN_ID = "CI_EXTRANJERA"  # cédula de identidad extranjera

    @classmethod
    def parse(cls, text: str | None) -> "DocumentType | None":
        """``"dni"``, ``"D.N.I."``, ``"Pasaporte"`` -> the member; None if unknown."""
        if not text:
            return None
        plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
        key = re.sub(r"[^A-Z]", "", plain.upper())
        return _DOCUMENT_ALIASES.get(key)


_DOCUMENT_ALIASES = {
    "DNI": DocumentType.DNI, "CUIT": DocumentType.CUIT, "CUIL": DocumentType.CUIL,
    "CDI": DocumentType.CDI, "PASAPORTE": DocumentType.PASSPORT,
    "PAS": DocumentType.PASSPORT, "PASSPORT": DocumentType.PASSPORT,
    "CIEXTRANJERA": DocumentType.FOREIGN_ID, "CI": DocumentType.FOREIGN_ID,
}


class InvoiceType(str, enum.Enum):
    """A comprobante: its kind and its class (A, B or C)."""

    INVOICE_A = "invoice_a"       # factura A
    INVOICE_B = "invoice_b"       # factura B
    INVOICE_C = "invoice_c"       # factura C
    CREDIT_NOTE_A = "credit_note_a"   # nota de crédito A
    CREDIT_NOTE_B = "credit_note_b"   # nota de crédito B
    CREDIT_NOTE_C = "credit_note_c"   # nota de crédito C


class InvoiceStatus(str, enum.Enum):
    """Where a comprobante stands with ARCA.

    ``PENDING`` covers everything not settled yet, including "we don't know":
    a request that timed out may have been authorized, so it is only ever
    resent under the same key. ``REJECTED`` means nothing was issued and no
    number was used, which is the only state a new attempt may follow.
    """

    PENDING = "pending"           # en trámite
    AUTHORIZED = "authorized"     # autorizado, con CAE
    REJECTED = "rejected"         # rechazado: no se emitió


# --- Reserved for transactional modules not built yet (shown in the ER
#     diagram). Defined here so states are controlled from day one. ---


class ExternalWorkType(str, enum.Enum):
    LABORATORY = "laboratory"
    WORKSHOP = "workshop"


class ExternalWorkStatus(str, enum.Enum):
    PENDING = "pending"           # pendiente
    SENT = "sent"                 # enviado
    IN_PROCESS = "in_process"     # en proceso
    RECEIVED = "received"         # recibido
    READY = "ready"               # listo para entregar
    DELIVERED = "delivered"       # entregado
    PAID = "paid"                 # pagado


class PlatformAction(str, enum.Enum):
    """What a platform (provider) user did, for the platform audit trail.

    Stored as a plain ``String(40)`` rather than a Postgres enum — like
    :class:`Currency` — because the list grows every time the admin console
    learns a new action, and a growing Postgres enum means a migration per
    value for no gain. The controlled list still lives here, so no caller
    invents a free-text action.
    """

    TENANT_CREATE = "tenant.create"
    TENANT_UPDATE = "tenant.update"
    TENANT_SUSPEND = "tenant.suspend"
    TENANT_REACTIVATE = "tenant.reactivate"
    TENANT_USER_CREATE = "tenant.user_create"
    TENANT_PASSWORD_RESET = "tenant.password_reset"
    TENANT_IMPERSONATE = "tenant.impersonate"
    TENANT_INVITE_SENT = "tenant.invite_sent"
    TENANT_INVOICING_LINK = "tenant.invoicing_link"
    TENANT_INVOICING_UPDATE = "tenant.invoicing_update"
    TENANT_INVOICING_NOTE = "tenant.invoicing_note"


class TokenPurpose(str, enum.Enum):
    """What a one-time link a user received is allowed to do.

    Stored as ``String(20)`` (see :class:`Currency` for the precedent): the
    list is short but grows with each new email flow, and a Postgres enum
    would mean a migration per value.
    """

    INVITATION = "invitation"          # set your first password
    PASSWORD_RESET = "password_reset"  # forgot it, set a new one
