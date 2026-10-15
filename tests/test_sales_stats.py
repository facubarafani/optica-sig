"""The sales summary on Inicio: periods in the shop's calendar, each compared
with the same stretch of the period before. The owner's (reports:read) adds
how each seller, branch and product type did; a seller's is their own."""
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.core.config import settings
from app.models.sales import Sale, SalePayment
from app.services import clock, provisioning
from tests.test_sales import customer_id, make_sale, shop  # noqa: F401 (fixtures)

# Wednesday 2026-08-12, 15:00 in Buenos Aires.
NOW = datetime(2026, 8, 12, 18, 0, tzinfo=timezone.utc)


def at(y, m, d, h=12):
    """A Buenos Aires wall-clock time as the UTC instant the database stores."""
    return datetime(y, m, d, h + 3, 0, tzinfo=timezone.utc)


@pytest.fixture
def frozen(monkeypatch):
    monkeypatch.setattr(clock, "_now", lambda: NOW)


@pytest.fixture
def sold(client, auth_headers, shop, customer_id, db, frozen):  # noqa: F811
    """Sells ARM-001 ($50.000) at the given local times, paid as asked, as the
    owner unless ``headers`` says who."""
    def _sold(when, *, payments=None, cust=False, headers=None, **extra):
        extra.setdefault("customer_id", customer_id if cust else None)
        body = make_sale(client, headers or auth_headers, shop,
                         payments=payments if payments is not None
                         else [{"amount": "50000", "method": "cash"}], **extra)
        assert body.status_code == 201, body.text
        sale = db.get(Sale, body.json()["id"])
        sale.sold_at = when
        for p in sale.payments:
            p.paid_at = when
        db.commit()
        return sale.id
    return _sold


def stats(client, headers, period):
    resp = client.get(f"/api/sales/stats?period={period}", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_today_against_the_same_hours_of_yesterday(client, auth_headers, sold):
    sold(at(2026, 8, 12, 10))
    sold(at(2026, 8, 12, 14))
    sold(at(2026, 8, 11, 11))          # yesterday, before 15:00: compared
    sold(at(2026, 8, 11, 20))          # yesterday evening: on the line only
    s = stats(client, auth_headers, "day")
    assert (s["revenue"], s["count"], s["average_ticket"]) == ("100000.00", 2, "50000.00")
    assert s["previous"]["revenue"] == "50000.00"
    assert s["change"]["revenue"] == "100.0"
    hours = {b["key"]: b for b in s["series"]}
    assert hours["10"]["revenue"] == "50000.00" and hours["10"]["count"] == 1
    assert hours["20"]["previous"] == "50000.00"
    # Later today has not happened yet.
    assert hours["16"]["revenue"] is None and hours["15"]["revenue"] == "0.00"


def test_a_late_night_sale_belongs_to_the_shops_day(client, auth_headers, sold):
    # 23:30 on the 11th in Buenos Aires is already the 12th in UTC.
    sold(datetime(2026, 8, 12, 2, 30, tzinfo=timezone.utc))
    assert stats(client, auth_headers, "day")["count"] == 0
    assert stats(client, auth_headers, "week")["count"] == 1


def test_week_month_and_year_buckets(client, auth_headers, sold):
    sold(at(2026, 8, 10))              # Monday of this week
    sold(at(2026, 8, 3))               # last week
    sold(at(2026, 3, 15))              # earlier this year
    week = stats(client, auth_headers, "week")
    assert week["start"] == "2026-08-10"
    assert [b["label"] for b in week["series"]][:3] == ["lun 10", "mar 11", "mié 12"]
    assert week["series"][0]["revenue"] == "50000.00"
    assert week["series"][0]["previous"] == "50000.00"
    assert week["series"][3]["revenue"] is None

    month = stats(client, auth_headers, "month")
    assert len(month["series"]) == 31 and month["count"] == 2

    year = stats(client, auth_headers, "year")
    assert year["count"] == 3
    assert [b["label"] for b in year["series"]][7] == "ago"
    assert year["series"][2]["revenue"] == "50000.00"
    assert year["series"][8]["revenue"] is None


def test_quotes_and_cancelled_sales_do_not_count(client, auth_headers, sold):
    sold(at(2026, 8, 12, 9), payments=[], status="quote")
    cancelled = sold(at(2026, 8, 12, 9))
    client.post(f"/api/sales/{cancelled}/cancel", headers=auth_headers)
    sold(at(2026, 8, 12, 9))
    s = stats(client, auth_headers, "day")
    assert s["count"] == 1 and s["collected"] == "50000.00"


def test_how_it_was_paid_and_what_sold_most(client, auth_headers, sold, shop, db):  # noqa: F811
    sold(at(2026, 8, 12, 9), cust=True, payments=[
        {"amount": "20000", "method": "debit_card"},
        {"amount": "10000", "method": "credit_card", "installments": 3,
         "surcharge_type": "percent", "surcharge_value": "10"}])
    lc = sold(at(2026, 8, 12, 10), payments=[], cust=True,
              items=[{"product_id": shop["products"]["LC-001"], "quantity": "2"}])
    s = stats(client, auth_headers, "day")
    assert s["revenue"] == "63000.00"              # 51.000 with the recargo + 12.000
    assert s["owed"] == "32000.00"                 # 20.000 + the lenses
    assert [(m["method"], m["amount"]) for m in s["methods"]] == [
        ("debit_card", "20000.00"), ("credit_card", "11000.00")]
    assert [(p["code"], p["quantity"], p["revenue"]) for p in s["top_products"]] == [
        ("ARM-001", "1.00", "50000.00"), ("LC-001", "2.00", "12000.00")]

    # A payment today on an older sale is collected today.
    sale = db.get(Sale, lc)
    sale.sold_at = at(2026, 7, 1)
    db.commit()
    client.post(f"/api/sales/{lc}/payments", headers=auth_headers,
                json={"amount": "12000", "method": "cash"})
    db.query(SalePayment).filter(SalePayment.sale_id == lc).update({"paid_at": at(2026, 8, 12, 11)})
    db.commit()
    s = stats(client, auth_headers, "day")
    assert s["count"] == 1 and s["collected"] == "43000.00"


def test_an_unknown_period_is_refused(client, auth_headers):
    assert client.get("/api/sales/stats?period=decade", headers=auth_headers).status_code == 422


def test_best_sellers_are_grouped_by_model(client, auth_headers, sold, product_type_id, db):
    """Two colours of one frame add up under the frame; the colours ride along."""
    def color(name, code):
        return client.post("/api/colors", json={"name": name, "code": code},
                           headers=auth_headers).json()["id"]
    neg, car = color("Negro", "NEG"), color("Carey", "CAR")
    style = client.post("/api/products", headers=auth_headers, json={
        "code": "ARM-9", "description": "Armazón redondo", "product_type_id": product_type_id,
        "pricing_mode": "manual", "sale_price": "30000", "color_ids": [neg, car]}).json()
    assert style.get("id"), style
    variants = client.get(f"/api/products?parent_id={style['id']}", headers=auth_headers).json()
    by_code = {v["code"]: v["id"] for v in variants}
    sold(at(2026, 8, 12, 9), payments=[], cust=True,
         items=[{"product_id": by_code["ARM-9-NEG"], "quantity": "2"},
                {"product_id": by_code["ARM-9-CAR"], "quantity": "1"}])
    sold(at(2026, 8, 12, 10))             # one ARM-001 at $50.000, a plain article
    top = stats(client, auth_headers, "day")["top_products"]
    assert [(t["code"], t["quantity"], t["revenue"]) for t in top] == [
        ("ARM-9", "3.00", "90000.00"), ("ARM-001", "1.00", "50000.00")]
    assert [(v["label"], v["quantity"]) for v in top[0]["variants"]] == [("Negro", "2.00"), ("Carey", "1.00")]
    assert top[1]["variants"] == []


# --- the two Inicios ----------------------------------------------------------

def _seller(client, auth_headers, email="vera@test.com", name="Vera Vende"):
    """Someone with the Vendedor role's permissions, logged in."""
    perms = client.get("/api/permissions", headers=auth_headers).json()
    role = client.post("/api/roles", headers=auth_headers, json={
        "name": f"Mostrador {email}",
        "permission_ids": [p["id"] for p in perms if p["code"] in provisioning.SALESPERSON_PERMS],
    }).json()
    user = client.post("/api/users", headers=auth_headers, json={
        "email": email, "full_name": name, "password": "vende12345", "role_ids": [role["id"]]})
    assert user.status_code == 201, user.text
    token = client.post("/api/auth/login", json={
        "email": email, "password": "vende12345"}).json()["access_token"]
    return user.json()["id"], {"Authorization": f"Bearer {token}"}


def test_the_owner_sees_the_business_and_a_seller_their_own(db):
    owner, seller = provisioning.ensure_default_roles(db, settings.default_company_id)
    assert "reports:read" in {p.code for p in owner.permissions}
    assert "reports:read" not in {p.code for p in seller.permissions}


def test_the_shops_figures_need_reports_read(client, auth_headers, frozen):
    _, vera = _seller(client, auth_headers)
    assert client.get("/api/sales/stats?period=day", headers=vera).status_code == 403
    assert client.get("/api/sales/stats/mine?period=day", headers=vera).status_code == 200
    assert client.get("/api/sales/stats?period=day", headers=auth_headers).status_code == 200


def test_a_seller_sees_their_sales_and_what_they_took_in(client, auth_headers, sold, db):
    _, vera = _seller(client, auth_headers)
    sold(at(2026, 8, 12, 10), headers=vera)
    owing = sold(at(2026, 8, 12, 11), payments=[], cust=True)     # the owner's, unpaid
    sold(at(2026, 8, 12, 12))
    # Vera takes that customer's money at the counter: hers to account for,
    # though not her sale.
    resp = client.post(f"/api/sales/{owing}/payments", headers=vera,
                       json={"amount": "50000", "method": "cash"})
    assert resp.status_code == 200, resp.text
    db.query(SalePayment).filter(SalePayment.sale_id == owing).update({"paid_at": at(2026, 8, 12, 13)})
    db.commit()

    mine = client.get("/api/sales/stats/mine?period=day", headers=vera).json()
    assert (mine["revenue"], mine["count"], mine["owed"]) == ("50000.00", 1, "0.00")
    assert mine["collected"] == "100000.00"
    assert [(t["code"], t["quantity"]) for t in mine["top_products"]] == [("ARM-001", "1.00")]
    assert mine["sellers"] == [] and mine["branches"] == [] and mine["product_types"] == []

    shop_ = stats(client, auth_headers, "day")
    assert (shop_["revenue"], shop_["count"], shop_["collected"]) == ("150000.00", 3, "150000.00")


def test_each_seller_adds_up_to_the_shop(client, auth_headers, sold):
    _, vera = _seller(client, auth_headers)
    _seller(client, auth_headers, email="nico@test.com", name="Nico Nuevo")
    sold(at(2026, 8, 12, 10), headers=vera)
    sold(at(2026, 8, 12, 11), headers=vera)
    sold(at(2026, 8, 11, 10), headers=vera)          # yesterday, inside the stretch compared
    sold(at(2026, 8, 11, 20), headers=vera)          # yesterday evening: not compared
    sold(at(2026, 8, 12, 9))                         # the owner's

    s = stats(client, auth_headers, "day")
    by = {r["name"]: r for r in s["sellers"]}
    assert list(by) == ["Vera Vende", "Admin", "Nico Nuevo"]       # best first
    assert sum(Decimal(r["revenue"]) for r in s["sellers"]) == Decimal(s["revenue"])
    vera_row = by["Vera Vende"]
    assert (vera_row["revenue"], vera_row["count"], vera_row["average_ticket"]) == ("100000.00", 2, "50000.00")
    assert (vera_row["share"], vera_row["previous_revenue"], vera_row["change"]) == ("66.7", "50000.00", "100.0")
    assert (by["Admin"]["share"], by["Admin"]["change"]) == ("33.3", None)
    # Someone who sells at the counter and has not sold yet is news too.
    nico = by["Nico Nuevo"]
    assert (nico["revenue"], nico["count"], nico["share"], nico["change"]) == ("0.00", 0, "0.0", None)


def test_the_owner_is_listed_only_when_they_sold(client, auth_headers, sold):
    _, vera = _seller(client, auth_headers)
    sold(at(2026, 8, 12, 10), headers=vera)
    assert [r["name"] for r in stats(client, auth_headers, "day")["sellers"]] == ["Vera Vende"]


def test_what_a_seller_gave_away_cancelled_and_quoted(client, auth_headers, sold, shop):  # noqa: F811
    _, vera = _seller(client, auth_headers)
    arm = shop["products"]["ARM-001"]
    # 10% off the line: 5.000 of its 50.000 list price.
    sold(at(2026, 8, 12, 10), headers=vera, payments=[{"amount": "45000", "method": "cash"}],
         items=[{"product_id": arm, "quantity": "1", "discount_type": "percent", "discount_value": "10"}])
    # A price typed by hand, and 2.000 off the whole sale.
    sold(at(2026, 8, 12, 11), headers=vera, payments=[{"amount": "38000", "method": "cash"}],
         discount_type="amount", discount_value="2000",
         items=[{"product_id": arm, "quantity": "1", "unit_price": "40000"}])
    gone = sold(at(2026, 8, 12, 12), headers=vera)
    assert client.post(f"/api/sales/{gone}/cancel", headers=vera).status_code == 200
    # Two presupuestos: that customer came back and bought; the other had
    # nobody to come back.
    sold(at(2026, 8, 12, 12), headers=vera, status="quote", payments=[], cust=True)
    sold(at(2026, 8, 12, 13), headers=vera, status="quote", payments=[])
    sold(at(2026, 8, 12, 14), cust=True)

    s = stats(client, auth_headers, "day")
    vera_row = next(r for r in s["sellers"] if r["name"] == "Vera Vende")
    assert (vera_row["revenue"], vera_row["count"]) == ("83000.00", 2)
    assert (vera_row["discount_amount"], vera_row["discount_rate"]) == ("7000.00", "7.8")
    assert (vera_row["price_overrides"], vera_row["cancelled"]) == (1, 1)
    assert (vera_row["quotes"], vera_row["quotes_won"]) == (2, 1)
    # The shop's rate: 7.000 given on 140.000 of list price.
    assert s["discount_rate"] == "5.0"


def test_where_it_was_sold_and_what(client, auth_headers, sold):
    north = client.post("/api/branches", json={"name": "Norte", "code": "N"},
                        headers=auth_headers).json()["id"]
    lenses = client.post("/api/product-types", json={"name": "Contacto"}, headers=auth_headers).json()["id"]
    lc = client.post("/api/products", headers=auth_headers, json={
        "code": "LC-9", "description": "Mensual", "product_type_id": lenses,
        "pricing_mode": "manual", "sale_price": "6000"}).json()["id"]
    sold(at(2026, 8, 12, 10))                                        # Central: 50.000 of frames
    sold(at(2026, 8, 12, 11), branch_id=north, payments=[{"amount": "12000", "method": "cash"}],
         items=[{"product_id": lc, "quantity": "2"}])
    sold(at(2026, 8, 11, 11), branch_id=north)                       # Norte, yesterday

    s = stats(client, auth_headers, "day")
    assert [(b["name"], b["revenue"], b["count"], b["share"], b["change"]) for b in s["branches"]] == [
        ("Central", "50000.00", 1, "80.6", None), ("Norte", "12000.00", 1, "19.4", "-76.0")]
    assert [(t["name"], t["revenue"], t["quantity"], t["share"]) for t in s["product_types"]] == [
        ("Armazones", "50000.00", "1.00", "80.6"), ("Contacto", "12000.00", "2.00", "19.4")]


def test_presupuestos_still_worth_a_call(client, auth_headers, sold, customer_id):  # noqa: F811
    vera_id, vera = _seller(client, auth_headers)
    ana = client.post("/api/customers", headers=auth_headers, json={
        "first_name": "Ana", "last_name": "Gómez", "phone": "11 5555-1111"}).json()["id"]
    waiting = sold(at(2026, 8, 10), headers=vera, status="quote", payments=[], customer_id=ana)
    sold(at(2026, 8, 11), headers=vera, status="quote", payments=[], cust=True)
    sold(at(2026, 8, 12, 9), cust=True)                              # ...that customer bought
    sold(at(2026, 8, 12, 10), headers=vera, status="quote", payments=[])     # nobody to call
    sold(at(2026, 6, 1), headers=vera, status="quote", payments=[], customer_id=ana)  # too old
    owners = sold(at(2026, 8, 12, 11), status="quote", payments=[], customer_id=ana)

    rows = client.get(f"/api/sales/quotes/open?salesperson_id={vera_id}", headers=vera).json()
    assert [r["id"] for r in rows] == [waiting]
    assert (rows[0]["customer_name"], rows[0]["customer_phone"]) == ("Gómez, Ana", "11 5555-1111")
    assert rows[0]["items"] == ["Producto ARM-001"]
    everyone = client.get("/api/sales/quotes/open", headers=auth_headers).json()
    assert [r["id"] for r in everyone] == [owners, waiting]


def test_the_sales_list_narrows_to_one_seller(client, auth_headers, sold):
    vera_id, vera = _seller(client, auth_headers)
    hers = sold(at(2026, 8, 12, 10), headers=vera)
    sold(at(2026, 8, 12, 11))
    rows = client.get(f"/api/sales?salesperson_id={vera_id}", headers=auth_headers).json()
    assert [(r["id"], r["salesperson_id"], r["salesperson_name"]) for r in rows] == [
        (hers, vera_id, "Vera Vende")]


def test_a_list_row_names_its_customer_and_seller(client, auth_headers, sold):
    sold(at(2026, 8, 12, 10), cust=True)
    sold(at(2026, 8, 12, 11))
    rows = client.get("/api/sales?sold_from=2026-08-12&sold_to=2026-08-12", headers=auth_headers).json()
    assert [(r["customer_name"], r["salesperson_name"]) for r in rows] == [
        (None, "Admin"), ("Pérez, Juan", "Admin")]
