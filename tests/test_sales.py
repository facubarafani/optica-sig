"""Ventas: pricing, discounts, stock discharge, payments and pending accounts."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.models.enums import DiscountType
from app.services import sales as sales_service


# --- the discount helper ---------------------------------------------------

@pytest.mark.parametrize("base, kind, value, expected", [
    ("1000", DiscountType.PERCENT, "20", "200.00"),
    ("1000", DiscountType.AMOUNT, "150", "150.00"),
    ("1000", DiscountType.PERCENT, "0", "0.00"),
    ("1000", None, "20", "0.00"),
    ("1000", DiscountType.AMOUNT, None, "0.00"),
    # Never turns a line into a refund.
    ("1000", DiscountType.AMOUNT, "5000", "1000.00"),
    ("1000", DiscountType.PERCENT, "150", "1000.00"),
    # Half-up at the cent, the way a till rounds.
    ("100.05", DiscountType.PERCENT, "50", "50.03"),
])
def test_discount_amount(base, kind, value, expected):
    got = sales_service.discount_amount(
        Decimal(base), kind, Decimal(value) if value is not None else None
    )
    assert got == Decimal(expected)


# --- fixtures --------------------------------------------------------------

@pytest.fixture
def customer_id(client, auth_headers):
    return client.post(
        "/api/customers",
        json={"first_name": "Juan", "last_name": "Pérez",
              "document_number": "30111222"},
        headers=auth_headers,
    ).json()["id"]


@pytest.fixture
def shop(client, auth_headers, product_type_id, branch_id):
    """Two priced products with stock, and an account to receive money."""
    plist = client.post(
        "/api/price-lists", json={"name": "General", "currency": "ARS"},
        headers=auth_headers,
    ).json()
    for code, price in [("AA", "6000"), ("AB", "50000")]:
        client.post(
            f"/api/price-lists/{plist['id']}/categories",
            json={"code": code, "price": price}, headers=auth_headers,
        )
    # Products carry a category code only, so the company default list is what
    # resolves it (same wiring as the real console).
    client.put("/api/company/settings",
               json={"default_price_list_id": plist["id"]}, headers=auth_headers)
    ids = {}
    for code, category in [("ARM-001", "AB"), ("LC-001", "AA")]:
        ids[code] = client.post(
            "/api/products",
            json={"code": code, "description": f"Producto {code}",
                  "product_type_id": product_type_id,
                  "pricing_mode": "price_list", "price_category_code": category},
            headers=auth_headers,
        ).json()["id"]
        client.post(
            "/api/stock/movements",
            json={"product_id": ids[code], "branch_id": branch_id,
                  "movement_type": "inbound", "quantity": "10"},
            headers=auth_headers,
        )
    account = client.post(
        "/api/payment-accounts",
        json={"name": "Santander", "method": "transfer"}, headers=auth_headers,
    ).json()["id"]
    return {"products": ids, "branch_id": branch_id, "account_id": account,
            "price_list_id": plist["id"]}


def make_sale(client, headers, shop, **overrides):
    body = {
        "branch_id": shop["branch_id"],
        "items": [{"product_id": shop["products"]["ARM-001"], "quantity": "1"}],
    }
    body.update(overrides)
    return client.post("/api/sales", json=body, headers=headers)


# --- pricing and totals ----------------------------------------------------

def test_price_comes_from_the_pricing_service(client, auth_headers, shop):
    resp = make_sale(client, auth_headers, shop, payments=[
        {"amount": "50000", "method": "cash"}])
    assert resp.status_code == 201, resp.text
    sale = resp.json()
    assert sale["items"][0]["unit_price"] == "50000.00"
    assert sale["items"][0]["price_overridden"] is False
    assert sale["total"] == "50000.00"
    assert sale["balance"] == "0.00"
    assert sale["number"].startswith("V-")


def test_manual_price_overrides_the_resolved_one(client, auth_headers, shop):
    resp = make_sale(client, auth_headers, shop, items=[
        {"product_id": shop["products"]["ARM-001"], "quantity": "1",
         "unit_price": "42000"}], customer_id=None,
        payments=[{"amount": "42000", "method": "cash"}])
    item = resp.json()["items"][0]
    assert item["unit_price"] == "42000.00"
    assert item["price_overridden"] is True


def test_line_and_sale_discounts_stack(client, auth_headers, shop, customer_id):
    resp = make_sale(
        client, auth_headers, shop,
        customer_id=customer_id,
        items=[
            # 50.000 less 20% = 40.000
            {"product_id": shop["products"]["ARM-001"], "quantity": "1",
             "discount_type": "percent", "discount_value": "20"},
            # 2 × 6.000 = 12.000, no line discount
            {"product_id": shop["products"]["LC-001"], "quantity": "2"},
        ],
        discount_type="amount", discount_value="2000",
    )
    assert resp.status_code == 201, resp.text
    sale = resp.json()
    assert [i["line_total"] for i in sale["items"]] == ["40000.00", "12000.00"]
    assert sale["subtotal"] == "52000.00"
    assert sale["discount_amount"] == "2000.00"
    assert sale["total"] == "50000.00"


def test_preview_matches_what_gets_saved(client, auth_headers, shop, customer_id):
    body = {
        "customer_id": customer_id, "branch_id": shop["branch_id"],
        "items": [{"product_id": shop["products"]["ARM-001"], "quantity": "2",
                   "discount_type": "percent", "discount_value": "10"}],
        "discount_type": "amount", "discount_value": "5000",
        "payments": [{"amount": "10000", "method": "cash"}],
    }
    preview = client.post("/api/sales/preview", json=body, headers=auth_headers)
    assert preview.status_code == 200, preview.text
    pv = preview.json()

    saved = client.post("/api/sales", json=body, headers=auth_headers).json()
    assert (pv["subtotal"], pv["total"], pv["balance"]) == (
        saved["subtotal"], saved["total"], saved["balance"])
    assert pv["currency"] == "ARS"


def test_preview_writes_nothing(client, auth_headers, shop):
    body = {"branch_id": shop["branch_id"],
            "items": [{"product_id": shop["products"]["ARM-001"], "quantity": "1"}]}
    client.post("/api/sales/preview", json=body, headers=auth_headers)
    assert client.get("/api/sales", headers=auth_headers).json() == []
    levels = client.get(
        f"/api/stock/levels?product_id={shop['products']['ARM-001']}",
        headers=auth_headers,
    ).json()
    assert levels[0]["quantity"] == "10.00"


def test_unpriceable_product_is_refused_with_a_reason(
    client, auth_headers, shop, product_type_id
):
    orphan = client.post(
        "/api/products",
        json={"code": "SIN-PRECIO", "product_type_id": product_type_id,
              "pricing_mode": "price_list"},
        headers=auth_headers,
    ).json()["id"]
    resp = make_sale(client, auth_headers, shop,
                     items=[{"product_id": orphan, "quantity": "1"}])
    assert resp.status_code == 400
    assert "SIN-PRECIO" in resp.json()["detail"]


# --- stock -----------------------------------------------------------------

def test_sale_discharges_stock_through_the_stock_service(
    client, auth_headers, shop
):
    make_sale(client, auth_headers, shop, items=[
        {"product_id": shop["products"]["ARM-001"], "quantity": "3"}],
        payments=[{"amount": "150000", "method": "cash"}])

    levels = client.get(
        f"/api/stock/levels?product_id={shop['products']['ARM-001']}",
        headers=auth_headers,
    ).json()
    assert levels[0]["quantity"] == "7.00"

    # ...and it shows in the ledger, tagged with the sale number.
    moves = client.get(
        "/api/stock/movements?movement_type=outbound", headers=auth_headers
    ).json()
    assert len(moves) == 1
    assert moves[0]["quantity"] == "-3.00"
    assert moves[0]["reference"].startswith("V-")


def test_selling_more_than_there_is_gets_refused_and_writes_nothing(
    client, auth_headers, shop
):
    resp = make_sale(client, auth_headers, shop, items=[
        {"product_id": shop["products"]["ARM-001"], "quantity": "99"}],
        payments=[{"amount": "1", "method": "cash"}])
    assert resp.status_code == 400, resp.text

    # No sale, no number burned, no stock moved.
    assert client.get("/api/sales", headers=auth_headers).json() == []
    levels = client.get(
        f"/api/stock/levels?product_id={shop['products']['ARM-001']}",
        headers=auth_headers,
    ).json()
    assert levels[0]["quantity"] == "10.00"


def test_a_quote_holds_no_stock(client, auth_headers, shop):
    resp = make_sale(client, auth_headers, shop, status="quote")
    assert resp.status_code == 201, resp.text
    levels = client.get(
        f"/api/stock/levels?product_id={shop['products']['ARM-001']}",
        headers=auth_headers,
    ).json()
    assert levels[0]["quantity"] == "10.00"


def test_cancelling_puts_the_stock_back(client, auth_headers, shop, customer_id):
    sale = make_sale(client, auth_headers, shop,
                     customer_id=customer_id).json()
    cancelled = client.post(f"/api/sales/{sale['id']}/cancel", headers=auth_headers)
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"

    levels = client.get(
        f"/api/stock/levels?product_id={shop['products']['ARM-001']}",
        headers=auth_headers,
    ).json()
    assert levels[0]["quantity"] == "10.00"
    # Cancelling twice is refused rather than double-crediting stock.
    assert client.post(
        f"/api/sales/{sale['id']}/cancel", headers=auth_headers
    ).status_code == 400


# --- payments and balance --------------------------------------------------

def test_partial_payment_leaves_a_balance(client, auth_headers, shop, customer_id):
    sale = make_sale(client, auth_headers, shop, customer_id=customer_id,
                     payments=[{"amount": "20000", "method": "cash"}]).json()
    assert sale["paid_amount"] == "20000.00"
    assert sale["balance"] == "30000.00"


def test_several_payments_add_up_and_clear_the_reminder(
    client, auth_headers, shop, customer_id
):
    sale = make_sale(
        client, auth_headers, shop, customer_id=customer_id,
        payments=[{"amount": "20000", "method": "cash"}],
        promised_payment_date=str(date.today() + timedelta(days=7)),
        reminder_note="Pasa el viernes",
    ).json()
    assert sale["promised_payment_date"] is not None

    after = client.post(
        f"/api/sales/{sale['id']}/payments",
        json={"amount": "10000", "method": "transfer",
              "account_id": shop["account_id"], "reference": "TRF-9"},
        headers=auth_headers,
    ).json()
    assert after["paid_amount"] == "30000.00"
    assert after["balance"] == "20000.00"
    assert after["promised_payment_date"] is not None

    settled = client.post(
        f"/api/sales/{sale['id']}/payments",
        json={"amount": "20000", "method": "card"}, headers=auth_headers,
    ).json()
    assert settled["balance"] == "0.00"
    # Nothing left to chase, so the promise is dropped.
    assert settled["promised_payment_date"] is None
    assert len(settled["payments"]) == 3
    assert {p["method"] for p in settled["payments"]} == {"cash", "transfer", "card"}


def test_overpayment_is_refused(client, auth_headers, shop, customer_id):
    sale = make_sale(client, auth_headers, shop, customer_id=customer_id,
                     payments=[{"amount": "20000", "method": "cash"}]).json()
    too_much = client.post(
        f"/api/sales/{sale['id']}/payments",
        json={"amount": "999999", "method": "cash"}, headers=auth_headers,
    )
    assert too_much.status_code == 400
    assert "supera el saldo" in too_much.json()["detail"]


def test_paying_more_than_the_total_up_front_is_refused(
    client, auth_headers, shop, customer_id
):
    resp = make_sale(client, auth_headers, shop, customer_id=customer_id,
                     payments=[{"amount": "80000", "method": "cash"}])
    assert resp.status_code == 400
    assert "supera el total" in resp.json()["detail"]


def test_a_debt_needs_a_customer(client, auth_headers, shop):
    resp = make_sale(client, auth_headers, shop, payments=[
        {"amount": "10000", "method": "cash"}])
    assert resp.status_code == 400
    assert "cliente" in resp.json()["detail"]


def test_cancelled_sales_take_no_more_payments(
    client, auth_headers, shop, customer_id
):
    sale = make_sale(client, auth_headers, shop, customer_id=customer_id).json()
    client.post(f"/api/sales/{sale['id']}/cancel", headers=auth_headers)
    resp = client.post(
        f"/api/sales/{sale['id']}/payments",
        json={"amount": "100", "method": "cash"}, headers=auth_headers,
    )
    assert resp.status_code == 400


# --- numbering -------------------------------------------------------------

def test_numbers_are_sequential_and_unique(client, auth_headers, shop):
    numbers = [
        make_sale(client, auth_headers, shop,
                  payments=[{"amount": "50000", "method": "cash"}]).json()["number"]
        for _ in range(3)
    ]
    assert numbers == ["V-000001", "V-000002", "V-000003"]


# --- searching and the pending screen --------------------------------------

def test_search_by_number_customer_and_reminder_note(
    client, auth_headers, shop, customer_id
):
    sale = make_sale(
        client, auth_headers, shop, customer_id=customer_id,
        payments=[{"amount": "10000", "method": "cash"}],
        reminder_note="Señó el armazón",
    ).json()

    def found(query):
        return [s["number"] for s in
                client.get(f"/api/sales{query}", headers=auth_headers).json()]

    assert found(f"?q={sale['number']}") == [sale["number"]]
    assert found("?q=perez") == [sale["number"]]      # accent-insensitive
    assert found("?q=Pérez") == [sale["number"]]
    assert found("?q=30111222") == [sale["number"]]   # by document
    assert found("?q=armazon") == [sale["number"]]    # by reminder note
    assert found("?q=nada-de-esto") == []


def test_pending_filters(client, auth_headers, shop, customer_id):
    yesterday = date.today() - timedelta(days=1)
    overdue = make_sale(
        client, auth_headers, shop, customer_id=customer_id,
        payments=[{"amount": "10000", "method": "cash"}],
        promised_payment_date=str(yesterday),
    ).json()
    future = make_sale(
        client, auth_headers, shop, customer_id=customer_id,
        payments=[{"amount": "10000", "method": "cash"}],
        promised_payment_date=str(date.today() + timedelta(days=5)),
    ).json()
    settled = make_sale(client, auth_headers, shop, customer_id=customer_id,
                        payments=[{"amount": "50000", "method": "cash"}]).json()

    def numbers(query):
        return sorted(s["number"] for s in
                      client.get(f"/api/sales{query}", headers=auth_headers).json())

    assert numbers("?pending_only=true") == sorted(
        [overdue["number"], future["number"]])
    assert settled["number"] not in numbers("?pending_only=true")
    assert numbers("?overdue_only=true") == [overdue["number"]]
    assert numbers(f"?due_to={yesterday}") == [overdue["number"]]

    summary = client.get("/api/sales/pending/summary", headers=auth_headers).json()
    assert summary["count"] == 2
    assert summary["total_pending"] == "80000.00"
    assert summary["overdue_count"] == 1
    assert summary["overdue_amount"] == "40000.00"


def test_cancelled_sales_never_count_as_pending(
    client, auth_headers, shop, customer_id
):
    sale = make_sale(client, auth_headers, shop, customer_id=customer_id,
                     payments=[{"amount": "10000", "method": "cash"}]).json()
    assert client.get(
        "/api/sales?pending_only=true", headers=auth_headers
    ).json() != []

    client.post(f"/api/sales/{sale['id']}/cancel", headers=auth_headers)
    assert client.get(
        "/api/sales?pending_only=true", headers=auth_headers
    ).json() == []
    summary = client.get("/api/sales/pending/summary", headers=auth_headers).json()
    assert summary["count"] == 0


# --- reminders -------------------------------------------------------------

def test_reminder_can_be_set_after_the_fact(
    client, auth_headers, shop, customer_id
):
    sale = make_sale(client, auth_headers, shop, customer_id=customer_id,
                     payments=[{"amount": "10000", "method": "cash"}]).json()
    assert sale["promised_payment_date"] is None

    promised = str(date.today() + timedelta(days=3))
    updated = client.put(
        f"/api/sales/{sale['id']}",
        json={"promised_payment_date": promised, "reminder_note": "Llamar antes"},
        headers=auth_headers,
    ).json()
    assert updated["promised_payment_date"] == promised
    assert updated["reminder_note"] == "Llamar antes"


# --- payment accounts ------------------------------------------------------

def test_payment_account_crud(client, auth_headers):
    created = client.post(
        "/api/payment-accounts",
        json={"name": "MercadoPago", "method": "transfer"}, headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    aid = created.json()["id"]
    assert client.post(
        "/api/payment-accounts", json={"name": "MercadoPago"}, headers=auth_headers
    ).status_code == 409
    assert client.delete(
        f"/api/payment-accounts/{aid}", headers=auth_headers
    ).status_code == 204
    assert client.get("/api/payment-accounts", headers=auth_headers).json() == []
