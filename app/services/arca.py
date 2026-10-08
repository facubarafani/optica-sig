"""Talking to arca-api, with the transport behind a seam.

arca-api is our own gateway to ARCA's web services (repo
``facubarafani/arca-api``): certificates, WSAA tickets, numbering and the
printable comprobante all live there. This module is the only code in SGI that
calls it. Two backends, chosen by ``ARCA_API_BACKEND``:

- ``http``: the real service at ``ARCA_API_URL``, authenticated with
  ``ARCA_API_KEY``. Invoicing is off until both are set.
- ``fake``: :data:`fake`, an in-process stand-in that keeps the promises SGI
  relies on (see :class:`FakeArca`). What the tests run against.

Calls never raise on an HTTP status. They return a :class:`Reply`, and
``services.invoicing`` decides what a 4xx or a 5xx means for a comprobante,
because the answer depends on whether arca-api had stored it yet. The one thing
singled out is getting no answer at all (``Reply.unreachable``): after a
timeout the comprobante may exist, so it may only be asked about again under
the same key.
"""
from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import httpx

from app.core.config import settings

logger = logging.getLogger("app.arca")


@dataclass
class Reply:
    """What arca-api answered. ``status`` is 0 when nothing came back."""

    status: int
    body: dict[str, Any] | None = None
    content: bytes = b""
    unreachable: str | None = None

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


def configured() -> bool:
    """Whether this server can reach an arca-api at all."""
    if settings.arca_api_backend == "fake":
        return True
    return bool(settings.arca_api_url and settings.arca_api_key)


# --- calls ------------------------------------------------------------------
def create_invoice(issuer_id: str, body: str, key: str) -> Reply:
    """``body`` is the JSON text itself, so a retry sends the same bytes."""
    return _backend().request(
        "POST", f"/v1/issuers/{issuer_id}/invoices", text=body,
        headers={"Idempotency-Key": key},
    )


def get_invoice(issuer_id: str, invoice_id: str) -> Reply:
    return _backend().request("GET", f"/v1/issuers/{issuer_id}/invoices/{invoice_id}")


def invoice_pdf(issuer_id: str, invoice_id: str) -> Reply:
    return _backend().request("GET", f"/v1/issuers/{issuer_id}/invoices/{invoice_id}/pdf")


def create_issuer(body: dict) -> Reply:
    return _backend().request("POST", "/v1/issuers", text=_dumps(body))


def get_issuer(issuer_id: str) -> Reply:
    return _backend().request("GET", f"/v1/issuers/{issuer_id}")


def list_issuers() -> Reply:
    """This project's issuers, as ``{"data": [...]}``."""
    return _backend().request("GET", "/v1/issuers")


def update_issuer(issuer_id: str, body: dict) -> Reply:
    return _backend().request("PATCH", f"/v1/issuers/{issuer_id}", text=_dumps(body))


def issuer_health(issuer_id: str) -> Reply:
    return _backend().request("GET", f"/v1/issuers/{issuer_id}/health")


def lookup_taxpayer(cuit: str) -> Reply:
    """ARCA's padrón for a CUIT (constancia de inscripción). arca-api caches
    it for a day."""
    return _backend().request("GET", f"/v1/taxpayers/{cuit}")


def _dumps(body: dict) -> str:
    return json.dumps(body, ensure_ascii=False, separators=(",", ":"))


# --- http -------------------------------------------------------------------
class _Http:
    def request(
        self, method: str, path: str, *, text: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> Reply:
        if not configured():
            return Reply(0, unreachable="la facturación no está configurada en este servidor")
        sent = {"Authorization": f"Bearer {settings.arca_api_key}", **(headers or {})}
        if text is not None:
            sent["Content-Type"] = "application/json"
        try:
            resp = httpx.request(
                method,
                settings.arca_api_url.rstrip("/") + path,
                content=text.encode("utf-8") if text is not None else None,
                headers=sent,
                timeout=httpx.Timeout(settings.arca_api_timeout_seconds, connect=5.0),
            )
        except httpx.TimeoutException:
            return Reply(0, unreachable="el servicio de facturación tardó demasiado en responder")
        except httpx.HTTPError as exc:
            logger.warning("arca-api %s %s failed: %s", method, path, exc)
            return Reply(0, unreachable="no se pudo conectar con el servicio de facturación")
        body = None
        if "json" in resp.headers.get("content-type", ""):
            try:
                body = resp.json()
            except ValueError:
                body = None
        return Reply(resp.status_code, body, content=resp.content)


# --- fake -------------------------------------------------------------------
CLASS_A_RECEIVERS = {"RESPONSABLE_INSCRIPTO", "MONOTRIBUTO", "MONOTRIBUTO_SOCIAL",
                     "MONOTRIBUTO_TRABAJADOR_INDEPENDIENTE_PROMOVIDO"}
CLASSES_BY_ISSUER = {"RESPONSABLE_INSCRIPTO": "AB", "MONOTRIBUTO": "C", "EXENTO": "C"}
RATE_TENTHS = {0: 0, 2.5: 25, 5: 50, 10.5: 105, 21: 210, 27: 270}
FISCAL_FIELDS = ("commercialAddress", "grossIncomeTax", "activityStartDate")


def _cents(value: float | int) -> int:
    return int((Decimal(str(value)) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _round_div(n: int, d: int) -> int:
    """n / d rounded half up, for non-negative integers (arca-api's roundDiv)."""
    return (n * 2 + d) // (2 * d)


@dataclass
class FakeArca:
    """arca-api in memory, holding the promises SGI's rules lean on.

    * One invoice per (issuer, Idempotency-Key). The same key with the same
      body returns it again; with another body it is ``409
      IDEMPOTENCY_KEY_REUSED``, carrying the stored ``invoiceId``.
    * The checks ``prepareInvoice`` makes before storing anything (class per
      issuer, receiver per class, CUIT for A, IVA rates for A/B only, a
      bonificación no larger than its line) answer ``422 INVALID_INVOICE``
      without an ``invoiceId``: nothing stored, no number used.
    * Totals as ``totals.ts`` computes them, in cents: quantity times price,
      half up, minus the line's ``discount``.
    * Numbers per (issuer, punto de venta, type), only for authorized ones.

    ``script`` makes the next ``create_invoice`` calls misbehave, one entry
    each: ``"pending"`` (stored, 202), ``"reject"`` (stored as REJECTED, 422),
    ``"timeout"`` (stored and authorized, but the answer never arrives),
    ``"unreachable"`` (never arrives, nothing stored), ``"down"`` (stored,
    then a 502 naming it), ``"not_ready"`` (409 before storing anything).
    """

    issuers: dict[str, dict] = field(default_factory=dict)
    invoices: dict[str, dict] = field(default_factory=dict)
    keys: dict[tuple[str, str], tuple[str, str]] = field(default_factory=dict)
    sequences: dict[tuple[str, int, str], int] = field(default_factory=dict)
    calls: list[tuple[str, str]] = field(default_factory=list)
    script: list[str] = field(default_factory=list)
    taxpayers: dict[str, dict] = field(default_factory=dict)
    # What the health check answers instead of "all fine", when a test sets it.
    health: dict | None = None
    _next: int = 0

    def reset(self) -> None:
        self.__init__()

    # -- test helpers ------------------------------------------------------
    def add_issuer(self, *, cuit: str = "20111111112", iva_condition: str = "MONOTRIBUTO",
                   legal_name: str = "OPTICA DE PRUEBA", complete: bool = True) -> dict:
        body = {"cuit": cuit, "legalName": legal_name, "ivaCondition": iva_condition,
                "credentialMode": "delegated"}
        if complete:
            body.update(commercialAddress="Av. Siempre Viva 742", grossIncomeTax="Exento",
                        activityStartDate="2019-03-01")
        return self._create_issuer(body).body

    def add_taxpayer(self, cuit: str, *, name: str, suggested: str | None) -> dict:
        """A constancia in the padrón, the way arca-api maps it."""
        self.taxpayers[cuit] = {
            "cuit": cuit, "environment": "homologacion", "name": name, "keyStatus": "ACTIVO",
            "fiscalAddress": {"address": "Calle 1", "locality": "Mar del Plata",
                              "postalCode": "7600", "province": "BUENOS AIRES"},
            "ivaCondition": {"suggested": suggested, "reason": "fake"},
            "constancia": {"available": True, "errors": []},
        }
        return self.taxpayers[cuit]

    def settle(self, invoice_id: str, status: str = "AUTHORIZED") -> dict:
        """What arca-api's background loop does to a pending invoice."""
        inv = self.invoices[invoice_id]
        if status == "AUTHORIZED":
            self._authorize(inv)
        else:
            inv.update(status="REJECTED", nextAttemptAt=None, lastError=None,
                       arca={"observations": [], "errors": [
                           {"code": 10016, "msg": "El numero o fecha del comprobante no se corresponde"}]})
        return inv

    # -- transport ---------------------------------------------------------
    def request(self, method: str, path: str, *, text: str | None = None,
                headers: dict[str, str] | None = None) -> Reply:
        self.calls.append((method, path))
        parts = path.strip("/").split("/")[1:]       # drop "v1"
        body = json.loads(text) if text else None
        if parts == ["issuers"] and method == "POST":
            return self._create_issuer(body)
        if parts == ["issuers"]:
            return Reply(200, {"data": [self._present_issuer(i) for i in self.issuers.values()]})
        if parts[0] == "taxpayers":
            found = self.taxpayers.get(parts[1])
            return Reply(200, dict(found)) if found else _problem(
                404, "NOT_FOUND", "ARCA has no taxpayer with that CUIT")
        issuer = self.issuers.get(parts[1]) if len(parts) > 1 else None
        if issuer is None:
            return _problem(404, "NOT_FOUND", "Issuer not found")
        if len(parts) == 2:
            if method == "PATCH":
                issuer.update({k: v for k, v in body.items() if v is not None})
            return Reply(200, self._present_issuer(issuer))
        if parts[2] == "health" and self.health is not None:
            return Reply(200, self.health)
        if parts[2] == "health":
            return Reply(200, {"ready": True, "credentialStatus": "ACTIVE",
                               "arca": {"ok": True, "app": "OK", "db": "OK", "auth": "OK", "error": None},
                               "authentication": {"ok": True, "expiresAt": None, "error": None},
                               "invoicing": {"ok": True, "pointsOfSale": [], "error": None}})
        if parts[2] == "invoices" and len(parts) == 3:
            return self._create_invoice(issuer, body, (headers or {}).get("Idempotency-Key", ""), text or "")
        inv = self.invoices.get(parts[3])
        if inv is None or inv["issuerId"] != issuer["id"]:
            return _problem(404, "NOT_FOUND", "Invoice not found")
        if len(parts) == 4:
            return Reply(200, dict(inv))
        if inv["status"] != "AUTHORIZED":
            return _problem(409, "INVOICE_NOT_AUTHORIZED", "This invoice has no CAE yet.")
        missing = [f for f in FISCAL_FIELDS if not issuer.get(f)]
        if missing:
            return _problem(409, "ISSUER_INCOMPLETE", "The issuer's fiscal data is incomplete.",
                            missing=missing)
        return Reply(200, None, content=b"%PDF-1.4 fake " + inv["id"].encode())

    # -- issuers -----------------------------------------------------------
    def _create_issuer(self, body: dict) -> Reply:
        if any(i["cuit"] == body["cuit"] for i in self.issuers.values()):
            return _problem(409, "ISSUER_EXISTS", "This CUIT is already registered.")
        self._next += 1
        issuer = {"id": f"iss_{self._next:04d}", "environment": "homologacion", **body}
        self.issuers[issuer["id"]] = issuer
        return Reply(201, self._present_issuer(issuer))

    def _present_issuer(self, issuer: dict) -> dict:
        return {
            "id": issuer["id"], "environment": issuer["environment"], "cuit": issuer["cuit"],
            "legalName": issuer["legalName"], "ivaCondition": issuer["ivaCondition"],
            "commercialAddress": issuer.get("commercialAddress"),
            "grossIncomeTax": issuer.get("grossIncomeTax"),
            "activityStartDate": issuer.get("activityStartDate"),
            "tradeName": issuer.get("tradeName"), "logo": None,
            "missingForPdf": [f for f in FISCAL_FIELDS if not issuer.get(f)],
            "credential": {"mode": "delegated", "status": "ACTIVE", "alias": "arcaapi",
                           "certificateExpiresAt": None, "certificateRequestPending": False},
            "ready": True, "createdAt": "2026-10-07T12:00:00Z",
        }

    # -- invoices ----------------------------------------------------------
    def _create_invoice(self, issuer: dict, body: dict, key: str, text: str) -> Reply:
        if not key:
            return _problem(400, "IDEMPOTENCY_KEY_REQUIRED", "Send an Idempotency-Key header.")
        digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        known = self.keys.get((issuer["id"], key))
        if known is not None:
            invoice_id, known_digest = known
            if known_digest != digest:
                return _problem(409, "IDEMPOTENCY_KEY_REUSED",
                                "This Idempotency-Key was already used with a different request body.",
                                invoiceId=invoice_id)
            return self._answer(self.invoices[invoice_id])

        behaviour = self.script.pop(0) if self.script else "authorize"
        if behaviour == "unreachable":
            return Reply(0, unreachable="no se pudo conectar con el servicio de facturación")
        if behaviour == "not_ready":
            return _problem(409, "ISSUER_NOT_READY", "The issuer has no active certificate.")
        errors, total_cents = _validate(issuer, body)
        if errors:
            return _problem(422, "INVALID_INVOICE", "The invoice is invalid.", errors=errors)

        self._next += 1
        inv = {
            "id": f"inv_{self._next:04d}", "issuerId": issuer["id"], "status": "PENDING",
            "type": body["type"], "pointOfSale": body["pointOfSale"], "number": None,
            "formattedNumber": None, "issueDate": date(2026, 10, 7).isoformat(),
            "concept": body["concept"], "receiver": body["receiver"],
            "saleCondition": body["saleCondition"], "items": body["items"],
            "pricesIncludeIva": body.get("pricesIncludeIva"), "currency": "PES",
            "totals": {"total": total_cents / 100}, "cae": None, "caeDueDate": None,
            "qrUrl": None, "arca": {"observations": [], "errors": []},
            "lastError": None, "nextAttemptAt": None, "metadata": body.get("metadata", {}),
            "createdAt": "2026-10-07T12:00:00Z", "authorizedAt": None,
            "associated": body.get("associated", []),
        }
        self.invoices[inv["id"]] = inv
        self.keys[(issuer["id"], key)] = (inv["id"], digest)

        if behaviour == "pending":
            inv.update(lastError="ARCA didn't answer: socket hang up",
                       nextAttemptAt="2026-10-07T12:01:00Z")
            return self._answer(inv)
        if behaviour == "reject":
            self.settle(inv["id"], "REJECTED")
            return self._answer(inv)
        if behaviour == "down":
            inv.update(lastError="ARCA error", nextAttemptAt="2026-10-07T12:01:00Z")
            return _problem(502, "ARCA_ERROR", "ARCA refused a question about the sequence.",
                            invoiceId=inv["id"])
        self._authorize(inv)
        if behaviour == "timeout":
            return Reply(0, unreachable="el servicio de facturación tardó demasiado en responder")
        return self._answer(inv)

    def _authorize(self, inv: dict) -> None:
        seq = (inv["issuerId"], inv["pointOfSale"], inv["type"])
        number = self.sequences.get(seq, 0) + 1
        self.sequences[seq] = number
        inv.update(status="AUTHORIZED", number=number,
                   formattedNumber=f"{inv['pointOfSale']:05d}-{number:08d}",
                   cae=f"7628{number:010d}", caeDueDate=(date(2026, 10, 17)).isoformat(),
                   qrUrl="https://www.arca.gob.ar/fe/qr/?p=fake", lastError=None,
                   nextAttemptAt=None,
                   authorizedAt=datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc).isoformat())

    @staticmethod
    def _answer(inv: dict) -> Reply:
        code = {"AUTHORIZED": 201, "REJECTED": 422}.get(inv["status"], 202)
        return Reply(code, dict(inv))


def _validate(issuer: dict, body: dict) -> tuple[list[dict], int]:
    """The subset of arca-api's prepareInvoice that SGI's choices can trip."""
    errors: list[dict] = []
    klass = body["type"][-1]
    receiver = body["receiver"]
    if klass not in CLASSES_BY_ISSUER[issuer["ivaCondition"]]:
        errors.append({"path": "type", "message": f"Can't issue class {klass}."})
    a_receiver = receiver["ivaCondition"] in CLASS_A_RECEIVERS
    if (klass == "A" and not a_receiver) or (klass == "B" and a_receiver):
        errors.append({"path": "receiver.ivaCondition", "message": "Not a valid receiver for this class."})
    if klass == "A" and receiver["docType"] != "CUIT":
        errors.append({"path": "receiver.docType", "message": "Class A comprobantes need the receiver's CUIT."})
    if receiver["docType"] == "SIN_IDENTIFICAR" and "docNumber" in receiver:
        errors.append({"path": "receiver.docNumber", "message": "Leave it out for SIN_IDENTIFICAR."})
    if klass in "AB" and body.get("pricesIncludeIva") is None:
        errors.append({"path": "pricesIncludeIva", "message": "Required for classes A and B."})
    gross_by_rate: dict[Any, int] = {}
    for i, item in enumerate(body["items"]):
        line = _round_div(round(item["quantity"] * 1000) * _cents(item["unitPrice"]), 1000)
        discount = _cents(item.get("discount", 0))
        if discount > line:
            errors.append({"path": f"items.{i}.discount", "message": "Larger than the line."})
        if klass == "C" and "ivaRate" in item:
            errors.append({"path": f"items.{i}.ivaRate", "message": "Class C carries no IVA."})
        if klass in "AB" and "ivaRate" not in item:
            errors.append({"path": f"items.{i}.ivaRate", "message": "Required for class A and B."})
        rate = item.get("ivaRate")
        gross_by_rate[rate] = gross_by_rate.get(rate, 0) + line - discount
    total = 0
    for rate, cents in gross_by_rate.items():
        if klass == "C" or rate in ("EXEMPT", "UNTAXED") or body.get("pricesIncludeIva"):
            total += cents          # IVA included: base + IVA is the gross itself
        else:
            total += cents + _round_div(cents * RATE_TENTHS[rate], 1000)
    return errors, total


def _problem(status: int, code: str, detail: str, **extra: Any) -> Reply:
    return Reply(status, {"status": status, "code": code, "detail": detail, **extra})


fake = FakeArca()
_http = _Http()


def _backend():
    return fake if settings.arca_api_backend == "fake" else _http


__all__ = [
    "Reply", "FakeArca", "fake", "configured", "create_invoice", "get_invoice",
    "invoice_pdf", "create_issuer", "get_issuer", "list_issuers", "update_issuer",
    "issuer_health", "lookup_taxpayer",
]
