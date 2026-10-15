"""The semáforo of what customers owe: red once a promised date has passed,
yellow when it falls due this week or nobody agreed one, green when it is
further off. A customer shows their worst debt."""
from datetime import date, datetime, timezone

import pytest

from app.models.enums import DebtLight
from app.services import clock
from app.services.sales import debt_light
from tests.test_sales import make_sale, shop  # noqa: F401 (fixtures)

# Wednesday 2026-08-12, 15:00 in Buenos Aires.
NOW = datetime(2026, 8, 12, 18, 0, tzinfo=timezone.utc)
TODAY = date(2026, 8, 12)


@pytest.fixture
def frozen(monkeypatch):
    monkeypatch.setattr(clock, "_now", lambda: NOW)


def test_the_light_of_one_debt():
    assert debt_light(date(2026, 8, 11), TODAY) is DebtLight.RED
    assert debt_light(TODAY, TODAY) is DebtLight.YELLOW
    assert debt_light(date(2026, 8, 19), TODAY) is DebtLight.YELLOW     # a week ahead
    assert debt_light(date(2026, 8, 20), TODAY) is DebtLight.GREEN
    assert debt_light(None, TODAY) is DebtLight.YELLOW                   # no date agreed


@pytest.fixture
def debtors(client, auth_headers, shop, frozen):  # noqa: F811
    """Five customers, each owing differently. ARM-001 sells at $50.000."""
    def customer(first, last):
        return client.post("/api/customers", json={"first_name": first, "last_name": last},
                           headers=auth_headers).json()["id"]

    def owes(cid, promised=None, paid="10000", **extra):
        resp = make_sale(client, auth_headers, shop, customer_id=cid, promised_payment_date=promised,
                         payments=[{"amount": paid, "method": "cash"}] if paid else [], **extra)
        assert resp.status_code == 201, resp.text
        return resp.json()["id"]

    ids = {name: customer(name, "Test") for name in ("Ana", "Beto", "Carla", "Dora", "Eva")}
    owes(ids["Ana"], "2026-09-01")                       # green on its own...
    owes(ids["Ana"], "2026-08-05")                       # ...but this one is a week late
    owes(ids["Beto"])                                    # no date agreed
    owes(ids["Beto"], "2026-08-15")                      # due in three days
    owes(ids["Carla"], "2026-08-22")                     # ten days off
    owes(ids["Dora"], paid="50000")                      # paid in full
    owes(ids["Eva"], paid=None, status="quote")          # a presupuesto owes nothing
    gone = owes(ids["Eva"], "2026-08-01")
    client.post(f"/api/sales/{gone}/cancel", headers=auth_headers)   # neither does an anulada
    return ids


def test_a_customer_shows_their_worst_debt(client, auth_headers, debtors):
    rows = {c["first_name"]: c for c in client.get("/api/customers", headers=auth_headers).json()}
    assert rows["Ana"]["debt"] == {"light": "red", "due": "2026-08-05", "owed": "80000.00", "count": 2}
    # Yellow either way; the dated debt says more than the one with no date.
    assert rows["Beto"]["debt"] == {"light": "yellow", "due": "2026-08-15", "owed": "80000.00", "count": 2}
    assert rows["Carla"]["debt"] == {"light": "green", "due": "2026-08-22", "owed": "40000.00", "count": 1}
    assert rows["Dora"]["debt"] is None and rows["Eva"]["debt"] is None


def test_con_deuda_keeps_the_customers_who_owe(client, auth_headers, debtors):
    rows = client.get("/api/customers?owing_only=true", headers=auth_headers).json()
    assert sorted(c["first_name"] for c in rows) == ["Ana", "Beto", "Carla"]


def test_what_a_customer_owes_is_for_whoever_sees_sales(client, auth_headers, debtors):
    perms = client.get("/api/permissions", headers=auth_headers).json()
    role = client.post("/api/roles", headers=auth_headers, json={
        "name": "Recepción", "permission_ids": [p["id"] for p in perms if p["code"] == "customers:read"]}).json()
    client.post("/api/users", headers=auth_headers, json={
        "email": "recepcion@test.com", "full_name": "Recepción", "password": "recepcion1234",
        "role_ids": [role["id"]]})
    token = client.post("/api/auth/login", json={
        "email": "recepcion@test.com", "password": "recepcion1234"}).json()["access_token"]
    front = {"Authorization": f"Bearer {token}"}
    rows = client.get("/api/customers?owing_only=true", headers=front).json()
    assert len(rows) == 5 and all(c["debt"] is None for c in rows)


def test_each_debt_on_the_sales_list_carries_its_light(client, auth_headers, debtors):
    rows = client.get("/api/sales?pending_only=true", headers=auth_headers).json()
    assert sorted((r["promised_payment_date"], r["debt_light"]) for r in rows
                  if r["promised_payment_date"]) == [
        ("2026-08-05", "red"), ("2026-08-15", "yellow"), ("2026-08-22", "green"), ("2026-09-01", "green")]
    paid = client.get("/api/sales", headers=auth_headers).json()
    assert all(r["debt_light"] is None for r in paid if r["balance"] == "0.00" or r["status"] != "confirmed")

    reds = client.get("/api/sales?light=red", headers=auth_headers).json()
    assert [r["promised_payment_date"] for r in reds] == ["2026-08-05"]
    yellows = client.get("/api/sales?light=yellow", headers=auth_headers).json()
    assert sorted(str(r["promised_payment_date"]) for r in yellows) == ["2026-08-15", "None"]


def test_the_pending_summary_adds_up_by_light(client, auth_headers, debtors):
    s = client.get("/api/sales/pending/summary", headers=auth_headers).json()
    assert s["lights"] == {
        "red": {"amount": "40000.00", "count": 1},
        "yellow": {"amount": "80000.00", "count": 2},
        "green": {"amount": "80000.00", "count": 2},
    }
    assert sum(float(b["amount"]) for b in s["lights"].values()) == float(s["total_pending"])
