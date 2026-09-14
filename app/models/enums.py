"""Controlled value lists (states/types) used across the domain.

Per the spec, any record with a "state" must use a controlled list rather than
free text. New values go here, never inline strings.
"""
from __future__ import annotations

import enum


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


class TokenPurpose(str, enum.Enum):
    """What a one-time link a user received is allowed to do.

    Stored as ``String(20)`` (see :class:`Currency` for the precedent): the
    list is short but grows with each new email flow, and a Postgres enum
    would mean a migration per value.
    """

    INVITATION = "invitation"          # set your first password
    PASSWORD_RESET = "password_reset"  # forgot it, set a new one
