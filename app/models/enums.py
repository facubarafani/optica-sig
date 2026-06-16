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


# --- Reserved for transactional modules (out of scope this session, shown in
#     the ER diagram). Defined here so states are controlled from day one. ---

class SaleStatus(str, enum.Enum):
    QUOTE = "quote"               # presupuesto
    CONFIRMED = "confirmed"       # confirmada
    PENDING = "pending"           # pendiente
    DELIVERED = "delivered"       # entregada
    CANCELLED = "cancelled"       # cancelada


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
