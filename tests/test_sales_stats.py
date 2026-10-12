"""The sales summary on Inicio: periods in the shop's calendar, each compared
with the same stretch of the period before."""
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.models.sales import Sale, SalePayment
from app.services import clock
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
    """Sells ARM-001 ($50.000) at the given local times, paid as asked."""
    def _sold(when, *, payments=None, cust=False, **extra):
        body = make_sale(client, auth_headers, shop,
                         payments=payments if payments is not None
                         else [{"amount": "50000", "method": "cash"}],
                         customer_id=customer_id if cust else None, **extra)
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
