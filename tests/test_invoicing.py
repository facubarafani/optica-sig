"""Facturación electrónica against the fake arca-api.

What matters most here, in order: a retry can never invoice twice (the key
and the body are written down before anything leaves, and only a definite
"nothing was stored" frees a new attempt); the comprobante adds up to the
sale to the cent, bonificaciones included; and a shop can only ever invoice
under the CUIT the provider linked it to.
"""
from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.enums import DocumentType, IvaCondition, PlatformAction
from app.models.invoicing import ArcaIssuer, Invoice
from app.models.platform import PlatformAuditLog
from app.services import arca, invoicing

COMPANY = settings.default_company_id


# --- pure rules -----------------------------------------------------------------

@pytest.mark.parametrize("total, weights", [
    (100, [3333, 3333, 3334]),
    (2, [1, 1, 1]),
    (3, [1, 1, 1]),
    (1, [500, 500]),
    (999, [1000]),
    (1000, [250, 750]),
    (0, [100, 200]),
    (5, [0, 10, 0]),
])
def test_spread_is_exact_and_never_exceeds_a_line(total, weights):
    shares = invoicing.spread(total, weights)
    assert sum(shares) == total
    assert all(0 <= s <= w for s, w in zip(shares, weights))


def test_spread_is_proportional():
    assert invoicing.spread(100, [1000, 3000]) == [25, 75]
    assert invoicing.spread(10, [100, 100, 100]) == [4, 3, 3]


@pytest.mark.parametrize("issuer, buyer, klass", [
    ("responsable_inscripto", "consumidor_final", "B"),
    ("responsable_inscripto", "responsable_inscripto", "A"),
    ("responsable_inscripto", "monotributo", "A"),
    ("responsable_inscripto", "monotributo_social", "A"),
    ("responsable_inscripto", "exento", "B"),
    ("responsable_inscripto", "cliente_exterior", "B"),
    ("monotributo", "responsable_inscripto", "C"),
    ("monotributo", "consumidor_final", "C"),
    ("exento", "monotributo", "C"),
])
def test_the_class_follows_from_both_conditions(issuer, buyer, klass):
    assert invoicing.invoice_class(issuer, buyer) == klass


@pytest.mark.parametrize("text, expected", [
    ("DNI", DocumentType.DNI), ("d.n.i.", DocumentType.DNI), (" cuit ", DocumentType.CUIT),
    ("Pasaporte", DocumentType.PASSPORT), ("CUIL", DocumentType.CUIL),
    ("Libreta cívica", None), ("", None), (None, None),
])
def test_document_types_are_read_however_they_were_typed(text, expected):
    assert DocumentType.parse(text) is expected


# --- fixtures -------------------------------------------------------------------

@pytest.fixture
def link(db):
    """Link a company to a fresh issuer in the fake arca-api."""
    made = iter(range(1, 100))

    def _link(condition="MONOTRIBUTO", *, point_of_sale=2, company_id=COMPANY,
              complete=True):
        issuer = arca.fake.add_issuer(cuit=f"20{next(made):08d}9", iva_condition=condition,
                                      complete=complete)
        db.add(ArcaIssuer(
            company_id=company_id, issuer_id=issuer["id"], cuit=issuer["cuit"],
            legal_name=issuer["legalName"], iva_condition=condition.lower(),
            point_of_sale=point_of_sale,
        ))
        db.commit()
        return issuer
    return _link


@pytest.fixture
def no_throttle(monkeypatch):
    """Let a follow-up GET ask arca-api right away."""
    monkeypatch.setattr(invoicing, "REFRESH_EVERY", timedelta(0))


@pytest.fixture
def catalog(client, auth_headers, branch_id):
    def product_type(name, iva_rate=None):
        body = {"name": name, **({"iva_rate": iva_rate} if iva_rate else {})}
        resp = client.post("/api/product-types", json=body, headers=auth_headers)
        assert resp.status_code == 201, resp.text
        return resp.json()["id"]

    frames, lenses = product_type("Armazones"), product_type("Cristales", "10.5")
    ids = {}
    for code, type_id in [("ARM-1", frames), ("ARM-2", frames), ("CRI-1", lenses)]:
        resp = client.post(
            "/api/products",
            json={"code": code, "description": f"Producto {code}", "product_type_id": type_id},
            headers=auth_headers,
        )
        assert resp.status_code == 201, resp.text
        ids[code] = resp.json()["id"]
    return {"products": ids, "branch_id": branch_id}


def line(catalog, code, price, quantity="1", **discount):
    return {"product_id": catalog["products"][code], "unit_price": price,
            "quantity": quantity, **discount}


def sell(client, headers, catalog, items, *, customer_id=None, pay=True, **extra):
    body = {"branch_id": catalog["branch_id"], "items": items,
            "customer_id": customer_id, **extra}
    if pay:
        preview = client.post("/api/sales/preview", json=body, headers=headers)
        assert preview.status_code == 200, preview.text
        total = preview.json()["total"]
        body["payments"] = [{"amount": total, "method": "cash"}] if Decimal(total) else []
    resp = client.post("/api/sales", json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def customer(client, headers, **fields):
    body = {"first_name": "Ana", "last_name": "Gómez", **fields}
    resp = client.post("/api/customers", json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def facturar(client, headers, sale_id):
    return client.post(f"/api/sales/{sale_id}/invoice", headers=headers)


def sent(db, invoice_id) -> dict:
    db.expire_all()
    return json.loads(db.get(Invoice, invoice_id).request_body)


# --- what the comprobante says ------------------------------------------------------

def test_a_monotributista_issues_a_factura_c(client, auth_headers, catalog, link, db):
    link("MONOTRIBUTO")
    sale = sell(client, auth_headers, catalog, [line(catalog, "ARM-1", "185000")])
    resp = facturar(client, auth_headers, sale["id"])
    assert resp.status_code == 200, resp.text
    inv = resp.json()
    assert (inv["type"], inv["status"]) == ("invoice_c", "authorized")
    assert inv["formatted_number"] == "00002-00000001"
    assert inv["cae"] and inv["cae_due_date"]
    assert Decimal(inv["total"]) == Decimal(sale["total"])

    body = sent(db, inv["id"])
    assert body["type"] == "FACTURA_C"
    assert body["pointOfSale"] == 2
    assert body["receiver"] == {"docType": "SIN_IDENTIFICAR", "ivaCondition": "CONSUMIDOR_FINAL"}
    assert body["saleCondition"] == "Contado"
    assert "pricesIncludeIva" not in body
    assert body["items"] == [{"description": "ARM-1 - Producto ARM-1", "quantity": 1,
                              "unitPrice": 185000}]


def test_a_responsable_inscripto_issues_b_to_a_consumidor_final(
    client, auth_headers, catalog, link, db
):
    link("RESPONSABLE_INSCRIPTO")
    buyer = customer(client, auth_headers, document_type="DNI",
                     document_number="30.111.222", address="Calle 1")
    sale = sell(client, auth_headers, catalog,
                [line(catalog, "ARM-1", "1000"), line(catalog, "CRI-1", "500")],
                customer_id=buyer)
    inv = facturar(client, auth_headers, sale["id"]).json()
    assert inv["type"] == "invoice_b"
    body = sent(db, inv["id"])
    assert body["pricesIncludeIva"] is True
    assert body["receiver"] == {"ivaCondition": "CONSUMIDOR_FINAL", "name": "Ana Gómez",
                                "docType": "DNI", "docNumber": "30111222",
                                "address": "Calle 1"}
    # The alícuota is the product type's; unset is the general 21%.
    assert [i["ivaRate"] for i in body["items"]] == [21, 10.5]


def test_a_responsable_inscripto_issues_a_to_an_ri_with_cuit(
    client, auth_headers, catalog, link, db
):
    link("RESPONSABLE_INSCRIPTO")
    buyer = customer(client, auth_headers, document_type="CUIT",
                     document_number="30-71234567-1", iva_condition="responsable_inscripto")
    sale = sell(client, auth_headers, catalog, [line(catalog, "ARM-1", "1210")],
                customer_id=buyer)
    inv = facturar(client, auth_headers, sale["id"]).json()
    assert (inv["type"], inv["status"]) == ("invoice_a", "authorized")
    assert sent(db, inv["id"])["receiver"]["docType"] == "CUIT"


def test_a_factura_a_without_cuit_is_refused_before_anything_is_written(
    client, auth_headers, catalog, link, db
):
    link("RESPONSABLE_INSCRIPTO")
    buyer = customer(client, auth_headers, document_type="DNI", document_number="30111222",
                     iva_condition="monotributo")
    sale = sell(client, auth_headers, catalog, [line(catalog, "ARM-1", "1000")],
                customer_id=buyer)
    resp = facturar(client, auth_headers, sale["id"])
    assert resp.status_code == 400
    assert "necesita su CUIT" in resp.json()["detail"]
    assert db.execute(select(Invoice)).first() is None
    assert arca.fake.invoices == {}


def test_a_document_type_arca_does_not_take_is_refused(client, auth_headers, catalog, link):
    link("MONOTRIBUTO")
    buyer = customer(client, auth_headers, document_type="Libreta", document_number="123")
    sale = sell(client, auth_headers, catalog, [line(catalog, "ARM-1", "1000")],
                customer_id=buyer)
    resp = facturar(client, auth_headers, sale["id"])
    assert resp.status_code == 400
    assert "Libreta" in resp.json()["detail"]


def test_a_debt_is_invoiced_as_cuenta_corriente(client, auth_headers, catalog, link, db):
    link("MONOTRIBUTO")
    buyer = customer(client, auth_headers)
    sale = sell(client, auth_headers, catalog, [line(catalog, "ARM-1", "1000")],
                customer_id=buyer, pay=False)
    inv = facturar(client, auth_headers, sale["id"]).json()
    assert sent(db, inv["id"])["saleCondition"] == "Cuenta corriente"


def test_bonificaciones_add_up_to_the_sale_to_the_cent(client, auth_headers, catalog, link, db):
    """Three units of 33,34 with a line discount, plus 10% off the whole sale:
    every cent of both discounts lands on a line, and arca-api's own total
    (quantity x price, half up, minus the bonificación) equals the sale's."""
    link("RESPONSABLE_INSCRIPTO")
    sale = sell(
        client, auth_headers, catalog,
        [line(catalog, "ARM-1", "33.34", "3", discount_type="amount", discount_value="0.02"),
         line(catalog, "ARM-2", "999.99"),
         line(catalog, "CRI-1", "1500.50", "2")],
        discount_type="percent", discount_value="10",
    )
    inv = facturar(client, auth_headers, sale["id"]).json()
    assert inv["status"] == "authorized", inv
    items = sent(db, inv["id"])["items"]
    bonif = sum(Decimal(str(i.get("discount", 0))) for i in items)
    assert bonif == Decimal("0.02") + Decimal(sale["discount_amount"])
    fake_total = Decimal(str(arca.fake.invoices[db.get(Invoice, inv["id"]).arca_invoice_id]
                             ["totals"]["total"]))
    assert fake_total == Decimal(sale["total"]) == Decimal(inv["total"])


def test_quotes_cancelled_and_free_sales_are_not_invoiced(client, auth_headers, catalog, link):
    link("MONOTRIBUTO")
    quote = sell(client, auth_headers, catalog, [line(catalog, "ARM-1", "100")],
                 pay=False, status="quote")
    assert "presupuesto" in facturar(client, auth_headers, quote["id"]).json()["detail"]
    free = sell(client, auth_headers, catalog, [line(catalog, "ARM-1", "0")])
    assert "$0" in facturar(client, auth_headers, free["id"]).json()["detail"]
    sale = sell(client, auth_headers, catalog, [line(catalog, "ARM-1", "100")])
    client.post(f"/api/sales/{sale['id']}/cancel", headers=auth_headers)
    assert "anulada" in facturar(client, auth_headers, sale["id"]).json()["detail"]


def test_a_branch_point_of_sale_overrides_the_shops(client, auth_headers, catalog, link, db):
    link("MONOTRIBUTO", point_of_sale=2)
    resp = client.put(f"/api/branches/{catalog['branch_id']}", json={"point_of_sale": 5},
                      headers=auth_headers)
    assert resp.status_code == 200, resp.text
    sale = sell(client, auth_headers, catalog, [line(catalog, "ARM-1", "100")])
    inv = facturar(client, auth_headers, sale["id"]).json()
    assert inv["point_of_sale"] == 5
    assert inv["formatted_number"] == "00005-00000001"


def test_without_a_link_invoicing_is_off(client, auth_headers, catalog):
    assert client.get("/api/invoicing/status", headers=auth_headers).json()["enabled"] is False
    sale = sell(client, auth_headers, catalog, [line(catalog, "ARM-1", "100")])
    resp = facturar(client, auth_headers, sale["id"])
    assert resp.status_code == 400
    assert "no está activada" in resp.json()["detail"]


def test_status_tells_the_console_which_classes(client, auth_headers, link):
    link("RESPONSABLE_INSCRIPTO")
    got = client.get("/api/invoicing/status", headers=auth_headers).json()
    assert got["enabled"] is True
    assert got["classes"] == ["A", "B"]
    assert got["iva_condition"] == "responsable_inscripto"


# --- never twice -----------------------------------------------------------------

def test_asking_twice_returns_the_same_factura(client, auth_headers, catalog, link):
    link()
    sale = sell(client, auth_headers, catalog, [line(catalog, "ARM-1", "100")])
    first = facturar(client, auth_headers, sale["id"]).json()
    second = facturar(client, auth_headers, sale["id"]).json()
    assert first["id"] == second["id"]
    assert len(arca.fake.invoices) == 1


def test_a_timeout_after_arca_authorized_is_resolved_without_a_second_factura(
    client, auth_headers, catalog, link, db, no_throttle
):
    """The worst case: ARCA authorized it, and the answer never came back."""
    link()
    sale = sell(client, auth_headers, catalog, [line(catalog, "ARM-1", "100")])
    arca.fake.script = ["timeout"]
    inv = facturar(client, auth_headers, sale["id"]).json()
    assert inv["status"] == "pending"
    assert "Sin respuesta" in inv["error"]
    key = db.get(Invoice, inv["id"]).idempotency_key

    followed = client.get(f"/api/invoices/{inv['id']}", headers=auth_headers).json()
    assert followed["status"] == "authorized"
    assert followed["formatted_number"] == "00002-00000001"
    assert len(arca.fake.invoices) == 1
    assert [k for (_, k) in arca.fake.keys] == [key]


def test_unreachable_stays_pending_and_retries_under_the_same_key(
    client, auth_headers, catalog, link, db
):
    link()
    sale = sell(client, auth_headers, catalog, [line(catalog, "ARM-1", "100")])
    arca.fake.script = ["unreachable"]
    inv = facturar(client, auth_headers, sale["id"]).json()
    assert inv["status"] == "pending"
    before = db.get(Invoice, inv["id"])
    key, body = before.idempotency_key, before.request_body

    retried = client.post(f"/api/invoices/{inv['id']}/retry", headers=auth_headers).json()
    assert retried["status"] == "authorized"
    db.expire_all()
    after = db.get(Invoice, inv["id"])
    assert (after.idempotency_key, after.request_body) == (key, body)


def test_a_pending_answer_settles_when_asked_again(
    client, auth_headers, catalog, link, db, no_throttle
):
    link()
    sale = sell(client, auth_headers, catalog, [line(catalog, "ARM-1", "100")])
    arca.fake.script = ["pending"]
    inv = facturar(client, auth_headers, sale["id"]).json()
    assert inv["status"] == "pending"
    arca_id = db.get(Invoice, inv["id"]).arca_invoice_id
    assert arca_id is not None

    arca.fake.settle(arca_id)
    assert client.get(f"/api/invoices/{inv['id']}", headers=auth_headers).json()["status"] \
        == "authorized"


def test_a_5xx_naming_the_invoice_stays_pending(client, auth_headers, catalog, link, db, no_throttle):
    link()
    sale = sell(client, auth_headers, catalog, [line(catalog, "ARM-1", "100")])
    arca.fake.script = ["down"]
    inv = facturar(client, auth_headers, sale["id"]).json()
    assert inv["status"] == "pending"
    arca_id = db.get(Invoice, inv["id"]).arca_invoice_id
    assert arca_id is not None
    arca.fake.settle(arca_id)
    assert client.get(f"/api/invoices/{inv['id']}", headers=auth_headers).json()["status"] \
        == "authorized"


def test_a_rejection_frees_a_new_attempt_under_a_new_key(client, auth_headers, catalog, link, db):
    link()
    sale = sell(client, auth_headers, catalog, [line(catalog, "ARM-1", "100")])
    arca.fake.script = ["reject"]
    rejected = facturar(client, auth_headers, sale["id"]).json()
    assert rejected["status"] == "rejected"
    assert "ARCA lo rechazó" in rejected["error"]

    again = facturar(client, auth_headers, sale["id"]).json()
    assert again["id"] != rejected["id"]
    assert again["status"] == "authorized"
    # A rejection uses no number.
    assert again["formatted_number"] == "00002-00000001"
    keys = {db.get(Invoice, i).idempotency_key for i in (rejected["id"], again["id"])}
    assert len(keys) == 2


def test_refused_before_storing_is_rejected(client, auth_headers, catalog, link):
    """A 4xx with no invoiceId means arca-api stored nothing."""
    link()
    sale = sell(client, auth_headers, catalog, [line(catalog, "ARM-1", "100")])
    arca.fake.script = ["not_ready"]
    inv = facturar(client, auth_headers, sale["id"]).json()
    assert inv["status"] == "rejected"
    assert inv["error"].startswith("No se emitió")
    assert facturar(client, auth_headers, sale["id"]).json()["status"] == "authorized"


def test_a_total_arca_authorized_differently_is_kept_and_visible(
    client, auth_headers, catalog, link, monkeypatch
):
    """An arca-api older than ``discount`` drops it and authorizes the full
    price. The record keeps what ARCA authorized, so the sale shows it."""
    link()
    create = arca.fake._create_invoice

    def drop_discounts(issuer, body, key, text):
        for item in body["items"]:
            item.pop("discount", None)
        return create(issuer, body, key, text)

    monkeypatch.setattr(arca.fake, "_create_invoice", drop_discounts)
    sale = sell(client, auth_headers, catalog, [line(catalog, "ARM-1", "100")],
                discount_type="amount", discount_value="10")
    inv = facturar(client, auth_headers, sale["id"]).json()
    assert inv["status"] == "authorized"
    assert Decimal(inv["total"]) == Decimal("100.00") != Decimal(sale["total"])


# --- cancelling ------------------------------------------------------------------

def test_cancelling_an_invoiced_sale_issues_its_credit_note(
    client, auth_headers, catalog, link, db
):
    link()
    sale = sell(client, auth_headers, catalog, [line(catalog, "ARM-1", "100")])
    factura = facturar(client, auth_headers, sale["id"]).json()
    resp = client.post(f"/api/sales/{sale['id']}/cancel", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    cancelled = resp.json()
    assert cancelled["status"] == "cancelled"
    note = cancelled["invoices"][-1]
    assert (note["type"], note["status"]) == ("credit_note_c", "authorized")
    assert note["credited_invoice_id"] == factura["id"]
    assert Decimal(note["total"]) == Decimal(factura["total"])

    body = sent(db, note["id"])
    assert body["type"] == "NOTA_CREDITO_C"
    assert body["associated"] == [{"invoiceId": db.get(Invoice, factura["id"]).arca_invoice_id}]
    assert body["items"] == sent(db, factura["id"])["items"]


def test_a_pending_factura_blocks_cancelling(client, auth_headers, catalog, link):
    link()
    sale = sell(client, auth_headers, catalog, [line(catalog, "ARM-1", "100")])
    arca.fake.script = ["pending"]
    facturar(client, auth_headers, sale["id"])
    resp = client.post(f"/api/sales/{sale['id']}/cancel", headers=auth_headers)
    assert resp.status_code == 400
    assert "en trámite" in resp.json()["detail"]


def test_a_rejected_credit_note_is_asked_for_again(client, auth_headers, catalog, link):
    link()
    sale = sell(client, auth_headers, catalog, [line(catalog, "ARM-1", "100")])
    facturar(client, auth_headers, sale["id"])
    arca.fake.script = ["reject"]
    cancelled = client.post(f"/api/sales/{sale['id']}/cancel", headers=auth_headers).json()
    assert cancelled["status"] == "cancelled"
    assert cancelled["invoices"][-1]["status"] == "rejected"

    note = client.post(f"/api/sales/{sale['id']}/credit-note", headers=auth_headers).json()
    assert (note["type"], note["status"]) == ("credit_note_c", "authorized")


def test_a_sale_without_factura_cancels_as_before(client, auth_headers, catalog, link):
    link()
    sale = sell(client, auth_headers, catalog, [line(catalog, "ARM-1", "100")])
    cancelled = client.post(f"/api/sales/{sale['id']}/cancel", headers=auth_headers).json()
    assert cancelled["status"] == "cancelled"
    assert cancelled["invoices"] == []


def test_put_cannot_cancel_around_anular(client, auth_headers, catalog):
    sale = sell(client, auth_headers, catalog, [line(catalog, "ARM-1", "100")])
    resp = client.put(f"/api/sales/{sale['id']}", json={"status": "cancelled"},
                      headers=auth_headers)
    assert resp.status_code == 400


# --- the PDF -----------------------------------------------------------------------

def test_the_pdf_comes_from_arca_api(client, auth_headers, catalog, link):
    link()
    sale = sell(client, auth_headers, catalog, [line(catalog, "ARM-1", "100")])
    inv = facturar(client, auth_headers, sale["id"]).json()
    resp = client.get(f"/api/invoices/{inv['id']}/pdf", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content.startswith(b"%PDF")
    assert "factura-c-00002-00000001.pdf" in resp.headers["content-disposition"]


def test_no_pdf_without_cae_or_without_the_fiscal_data(client, auth_headers, catalog, link):
    link(complete=False)
    sale = sell(client, auth_headers, catalog, [line(catalog, "ARM-1", "100")])
    arca.fake.script = ["pending"]
    pending = facturar(client, auth_headers, sale["id"]).json()
    resp = client.get(f"/api/invoices/{pending['id']}/pdf", headers=auth_headers)
    assert resp.status_code == 409
    assert "autorizado" in resp.json()["detail"]

    other = sell(client, auth_headers, catalog, [line(catalog, "ARM-1", "100")])
    inv = facturar(client, auth_headers, other["id"]).json()
    resp = client.get(f"/api/invoices/{inv['id']}/pdf", headers=auth_headers)
    assert resp.status_code == 409
    assert "domicilio comercial" in resp.json()["detail"]


# --- whose CUIT ----------------------------------------------------------------------

def _second_shop(client, platform_headers):
    resp = client.post("/api/admin/tenants", json={
        "name": "Otra Óptica", "tax_id": "30-71111111-1", "admin_email": "otra@test.com",
        "admin_password": "otra123456",
    }, headers=platform_headers)
    assert resp.status_code == 201, resp.text
    login = client.post("/api/auth/login",
                        json={"email": "otra@test.com", "password": "otra123456"})
    return resp.json()["company"]["id"], {"Authorization": f"Bearer {login.json()['access_token']}"}


def test_a_comprobante_is_only_seen_by_its_shop(
    client, auth_headers, platform_headers, catalog, link
):
    link()
    sale = sell(client, auth_headers, catalog, [line(catalog, "ARM-1", "100")])
    inv = facturar(client, auth_headers, sale["id"]).json()
    _, other = _second_shop(client, platform_headers)
    assert client.get(f"/api/invoices/{inv['id']}", headers=other).status_code == 404
    assert client.get(f"/api/invoices/{inv['id']}/pdf", headers=other).status_code == 404
    assert client.get("/api/invoices", headers=other).json() == []
    assert facturar(client, other, sale["id"]).status_code == 404


def test_the_provider_registers_a_shop_as_a_delegated_issuer(
    client, platform_headers, auth_headers, db
):
    resp = client.post(f"/api/admin/tenants/{COMPANY}/invoicing", json={
        "cuit": "20111111112", "legal_name": "Óptica Test", "iva_condition": "monotributo",
        "point_of_sale": 2, "commercial_address": "Av. Test 1", "gross_income_tax": "Exento",
        "activity_start_date": "2019-03-01",
    }, headers=platform_headers)
    assert resp.status_code == 200, resp.text
    got = resp.json()
    assert got["linked"] and got["iva_condition"] == "monotributo"
    assert got["issuer"]["missingForPdf"] == []
    registered = next(iter(arca.fake.issuers.values()))
    assert registered["credentialMode"] == "delegated"
    assert registered["ivaCondition"] == "MONOTRIBUTO"
    assert client.get("/api/invoicing/status", headers=auth_headers).json()["enabled"] is True
    actions = db.execute(select(PlatformAuditLog.action)).scalars().all()
    assert PlatformAction.TENANT_INVOICING_LINK.value in actions


def test_a_cuit_already_in_arca_api_is_linked_rather_than_refused(client, platform_headers):
    existing = arca.fake.add_issuer(cuit="20111111112", iva_condition="RESPONSABLE_INSCRIPTO")
    resp = client.post(f"/api/admin/tenants/{COMPANY}/invoicing", json={
        "cuit": "20111111112", "iva_condition": "responsable_inscripto", "point_of_sale": 3,
    }, headers=platform_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["issuer_id"] == existing["id"]


def test_a_cuit_already_registered_as_something_else_is_not_linked(client, platform_headers):
    """arca-api cannot change an issuer's condition, so linking one registered
    as RI to a shop declared Monotributista would invoice it as the wrong thing."""
    arca.fake.add_issuer(cuit="20111111112", iva_condition="RESPONSABLE_INSCRIPTO")
    resp = client.post(f"/api/admin/tenants/{COMPANY}/invoicing", json={
        "cuit": "20111111112", "iva_condition": "monotributo", "point_of_sale": 3,
    }, headers=platform_headers)
    assert resp.status_code == 400
    assert "registrado como responsable inscripto" in resp.json()["detail"]


def test_one_issuer_never_serves_two_shops(client, platform_headers, link):
    issuer = link()
    other_id, _ = _second_shop(client, platform_headers)
    resp = client.post(f"/api/admin/tenants/{other_id}/invoicing", json={
        "issuer_id": issuer["id"], "point_of_sale": 1,
    }, headers=platform_headers)
    assert resp.status_code == 400
    assert "ya está vinculado" in resp.json()["detail"]


def test_a_shop_cannot_link_itself(client, auth_headers):
    resp = client.post(f"/api/admin/tenants/{COMPANY}/invoicing",
                       json={"issuer_id": "iss_x", "point_of_sale": 1}, headers=auth_headers)
    assert resp.status_code == 401


def test_the_provider_pauses_invoicing_and_sets_fiscal_data(
    client, platform_headers, auth_headers, catalog, link, db
):
    issuer = link(complete=False)
    resp = client.patch(f"/api/admin/tenants/{COMPANY}/invoicing", json={
        "point_of_sale": 4, "commercial_address": "Av. Nueva 2", "gross_income_tax": "901-1",
        "activity_start_date": "2020-01-01", "is_active": False,
    }, headers=platform_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["point_of_sale"] == 4
    assert arca.fake.issuers[issuer["id"]]["commercialAddress"] == "Av. Nueva 2"
    assert client.get("/api/invoicing/status", headers=auth_headers).json()["enabled"] is False
    sale = sell(client, auth_headers, catalog, [line(catalog, "ARM-1", "100")])
    assert facturar(client, auth_headers, sale["id"]).status_code == 400
    actions = db.execute(select(PlatformAuditLog.action)).scalars().all()
    assert PlatformAction.TENANT_INVOICING_UPDATE.value in actions


def test_a_shop_that_already_invoiced_keeps_its_issuer(
    client, platform_headers, auth_headers, catalog, link
):
    link()
    sale = sell(client, auth_headers, catalog, [line(catalog, "ARM-1", "100")])
    facturar(client, auth_headers, sale["id"])
    other = arca.fake.add_issuer(cuit="20999999999")
    resp = client.post(f"/api/admin/tenants/{COMPANY}/invoicing", json={
        "issuer_id": other["id"], "point_of_sale": 1,
    }, headers=platform_headers)
    assert resp.status_code == 400
    assert "ya emitió" in resp.json()["detail"]


def test_health_is_arca_apis_own(client, platform_headers, link):
    link()
    resp = client.get(f"/api/admin/tenants/{COMPANY}/invoicing/health", headers=platform_headers)
    assert resp.status_code == 200
    assert resp.json()["invoicing"]["ok"] is True


# --- master data feeding it ---------------------------------------------------------

def test_customer_document_types_are_stored_controlled(client, auth_headers):
    cid = customer(client, auth_headers, document_type="d.n.i.", document_number="1",
                   iva_condition="monotributo")
    got = client.get(f"/api/customers/{cid}", headers=auth_headers).json()
    assert got["document_type"] == "DNI"
    assert got["iva_condition"] == IvaCondition.MONOTRIBUTO.value
    bad = client.post("/api/customers", json={"first_name": "a", "last_name": "b",
                                              "iva_condition": "rico"}, headers=auth_headers)
    assert bad.status_code == 422
