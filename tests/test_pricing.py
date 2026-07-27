"""The category ladder: generating it, filling it, adjusting it, editing it."""
from decimal import Decimal

import pytest

from app.models.audit import ChangeHistory
from app.models.enums import RoundingMode
from app.services import pricing


def _list(client, headers, name="General", **extra):
    resp = client.post(
        "/api/price-lists", json={"name": name, **extra}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _categories(client, headers, list_id, **params):
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    resp = client.get(
        f"/api/price-lists/{list_id}/categories" + (f"?{qs}" if qs else ""),
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# --- the AA..ZZ sequence --------------------------------------------------

@pytest.mark.parametrize(
    "position, expected",
    [(0, "AA"), (1, "AB"), (25, "AZ"), (26, "BA"), (27, "BB"), (675, "ZZ")],
)
def test_category_code_sequence(position, expected):
    assert pricing.category_code(position) == expected


def test_category_code_runs_out_at_zz():
    with pytest.raises(pricing.PricingError):
        pricing.category_code(676)


# --- rounding -------------------------------------------------------------

@pytest.mark.parametrize(
    "value, step, mode, expected",
    [
        # The example from the feedback: $8.583 rounds up to $8.600.
        ("8583", "100", RoundingMode.UP, "8600.00"),
        ("8583", "100", RoundingMode.NEAREST, "8600.00"),
        ("8583", "100", RoundingMode.DOWN, "8500.00"),
        ("8500", "100", RoundingMode.UP, "8500.00"),   # already a multiple
        ("8583", "1000", RoundingMode.UP, "9000.00"),
        ("8583.4", "0", RoundingMode.UP, "8583.40"),   # 0 = no rounding
    ],
)
def test_round_price(value, step, mode, expected):
    got = pricing.round_price(Decimal(value), step=Decimal(step), mode=mode)
    assert got == Decimal(expected)


# --- generating the ladder ------------------------------------------------

def test_generate_categories_names_them_aa_onwards(client, auth_headers):
    lid = _list(client, auth_headers)
    resp = client.post(
        f"/api/price-lists/{lid}/generate-categories",
        json={"count": 4}, headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert [c["code"] for c in resp.json()] == ["AA", "AB", "AC", "AD"]


def test_generate_categories_past_az_rolls_into_ba(client, auth_headers):
    lid = _list(client, auth_headers)
    client.post(f"/api/price-lists/{lid}/generate-categories",
                json={"count": 28}, headers=auth_headers)
    codes = [c["code"] for c in _categories(client, auth_headers, lid)]
    assert codes[25:28] == ["AZ", "BA", "BB"]


def test_growing_the_ladder_keeps_the_existing_prices(client, auth_headers):
    lid = _list(client, auth_headers)
    client.post(f"/api/price-lists/{lid}/generate-categories",
                json={"count": 2}, headers=auth_headers)
    cats = _categories(client, auth_headers, lid)
    client.put(f"/api/price-lists/{lid}/categories/{cats[0]['id']}",
               json={"price": "1234.00"}, headers=auth_headers)

    client.post(f"/api/price-lists/{lid}/generate-categories",
                json={"count": 4}, headers=auth_headers)
    after = _categories(client, auth_headers, lid)
    assert [c["code"] for c in after] == ["AA", "AB", "AC", "AD"]
    assert after[0]["price"] == "1234.00"


def test_shrinking_deactivates_rather_than_deletes(client, auth_headers):
    lid = _list(client, auth_headers)
    client.post(f"/api/price-lists/{lid}/generate-categories",
                json={"count": 4}, headers=auth_headers)
    cats = _categories(client, auth_headers, lid)
    client.put(f"/api/price-lists/{lid}/categories/{cats[3]['id']}",
               json={"price": "999.00"}, headers=auth_headers)

    client.post(f"/api/price-lists/{lid}/generate-categories",
                json={"count": 2}, headers=auth_headers)
    assert [c["code"] for c in _categories(client, auth_headers, lid)] == ["AA", "AB"]

    # AD is still there, just inactive — and going back up restores its price.
    every = _categories(client, auth_headers, lid, include_inactive="true")
    assert len(every) == 4
    client.post(f"/api/price-lists/{lid}/generate-categories",
                json={"count": 4}, headers=auth_headers)
    restored = _categories(client, auth_headers, lid)
    assert restored[3]["code"] == "AD"
    assert restored[3]["price"] == "999.00"


# --- adding / editing / removing by hand ----------------------------------

def test_adding_a_category_picks_the_next_free_code(client, auth_headers):
    lid = _list(client, auth_headers)
    client.post(f"/api/price-lists/{lid}/generate-categories",
                json={"count": 2}, headers=auth_headers)
    resp = client.post(f"/api/price-lists/{lid}/categories",
                       json={"price": "500.00"}, headers=auth_headers)
    assert resp.status_code == 201, resp.text
    assert resp.json()["code"] == "AC"


def test_a_category_can_be_renamed_and_repriced_by_hand(client, auth_headers):
    lid = _list(client, auth_headers)
    client.post(f"/api/price-lists/{lid}/generate-categories",
                json={"count": 2}, headers=auth_headers)
    cat = _categories(client, auth_headers, lid)[0]
    resp = client.put(
        f"/api/price-lists/{lid}/categories/{cat['id']}",
        json={"code": "promo", "price": "777.77", "description": "Liquidación"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["code"] == "PROMO"          # codes are stored upper-cased
    assert body["price"] == "777.77"
    assert body["description"] == "Liquidación"


def test_duplicate_code_in_the_same_list_is_rejected(client, auth_headers):
    lid = _list(client, auth_headers)
    client.post(f"/api/price-lists/{lid}/generate-categories",
                json={"count": 1}, headers=auth_headers)
    dup = client.post(f"/api/price-lists/{lid}/categories",
                      json={"code": "AA"}, headers=auth_headers)
    assert dup.status_code == 400
    assert "AA" in dup.json()["detail"]


def test_the_same_code_may_exist_in_two_lists(client, auth_headers):
    a = _list(client, auth_headers, "Mostrador")
    b = _list(client, auth_headers, "Mayorista")
    for lid in (a, b):
        resp = client.post(f"/api/price-lists/{lid}/categories",
                           json={"code": "AA", "price": "100"}, headers=auth_headers)
        assert resp.status_code == 201, resp.text


def test_deleting_a_category_deactivates_it(client, auth_headers):
    lid = _list(client, auth_headers)
    client.post(f"/api/price-lists/{lid}/generate-categories",
                json={"count": 2}, headers=auth_headers)
    cat = _categories(client, auth_headers, lid)[1]
    assert client.delete(f"/api/price-lists/{lid}/categories/{cat['id']}",
                         headers=auth_headers).status_code == 204
    assert [c["code"] for c in _categories(client, auth_headers, lid)] == ["AA"]
    assert len(_categories(client, auth_headers, lid, include_inactive="true")) == 2


# --- generating the prices ------------------------------------------------

def test_generate_prices_spreads_the_range_over_the_ladder(client, auth_headers):
    lid = _list(client, auth_headers)
    client.post(f"/api/price-lists/{lid}/generate-categories",
                json={"count": 4}, headers=auth_headers)
    resp = client.post(
        f"/api/price-lists/{lid}/generate-prices",
        json={"min_price": "5000", "max_price": "20000", "rounding_step": "100"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    prices = [c["price"] for c in _categories(client, auth_headers, lid)]
    # min and max are the endpoints; the step is (20000-5000)/3 = 5000.
    assert prices == ["5000.00", "10000.00", "15000.00", "20000.00"]


def test_generated_prices_round_up_to_hundreds(client, auth_headers):
    lid = _list(client, auth_headers)
    client.post(f"/api/price-lists/{lid}/generate-categories",
                json={"count": 3}, headers=auth_headers)
    client.post(
        f"/api/price-lists/{lid}/generate-prices",
        json={"min_price": "8583", "max_price": "17166"},   # rounding defaults to 100 up
        headers=auth_headers,
    )
    prices = [c["price"] for c in _categories(client, auth_headers, lid)]
    assert prices == ["8600.00", "12900.00", "17200.00"]


def test_the_rounding_step_can_be_changed(client, auth_headers):
    lid = _list(client, auth_headers)
    client.post(f"/api/price-lists/{lid}/generate-categories",
                json={"count": 2}, headers=auth_headers)
    client.post(
        f"/api/price-lists/{lid}/generate-prices",
        json={"min_price": "8583", "max_price": "9100", "rounding_step": "1000"},
        headers=auth_headers,
    )
    prices = [c["price"] for c in _categories(client, auth_headers, lid)]
    assert prices == ["9000.00", "10000.00"]


def test_generate_prices_without_categories_explains_itself(client, auth_headers):
    lid = _list(client, auth_headers)
    resp = client.post(
        f"/api/price-lists/{lid}/generate-prices",
        json={"min_price": "1000", "max_price": "2000"}, headers=auth_headers,
    )
    assert resp.status_code == 400
    assert "categorías" in resp.json()["detail"]


def test_max_below_min_is_rejected(client, auth_headers):
    lid = _list(client, auth_headers)
    resp = client.post(
        f"/api/price-lists/{lid}/generate-prices",
        json={"min_price": "2000", "max_price": "1000"}, headers=auth_headers,
    )
    assert resp.status_code == 422


def test_generated_prices_are_audited(client, auth_headers, db):
    lid = _list(client, auth_headers)
    client.post(f"/api/price-lists/{lid}/generate-categories",
                json={"count": 2}, headers=auth_headers)
    client.post(
        f"/api/price-lists/{lid}/generate-prices",
        json={"min_price": "1000", "max_price": "2000"}, headers=auth_headers,
    )
    rows = (
        db.query(ChangeHistory)
        .filter(ChangeHistory.entity_type == "price_category",
                ChangeHistory.field_name == "price")
        .all()
    )
    assert len(rows) == 2


# --- percentage adjustment ------------------------------------------------

def test_bulk_percentage_update(client, auth_headers):
    lid = _list(client, auth_headers)
    client.post(f"/api/price-lists/{lid}/generate-categories",
                json={"count": 2}, headers=auth_headers)
    client.post(f"/api/price-lists/{lid}/generate-prices",
                json={"min_price": "1000", "max_price": "2000"}, headers=auth_headers)

    resp = client.post(f"/api/price-lists/{lid}/bulk-update",
                       json={"percentage": "10", "rounding_step": "0"},
                       headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["updated_items"] == 2
    prices = [c["price"] for c in _categories(client, auth_headers, lid)]
    assert prices == ["1100.00", "2200.00"]


def test_a_percentage_drop_works_too(client, auth_headers):
    lid = _list(client, auth_headers)
    client.post(f"/api/price-lists/{lid}/generate-categories",
                json={"count": 1}, headers=auth_headers)
    client.post(f"/api/price-lists/{lid}/generate-prices",
                json={"min_price": "1000", "max_price": "1000"}, headers=auth_headers)
    client.post(f"/api/price-lists/{lid}/bulk-update",
                json={"percentage": "-20", "rounding_step": "0"}, headers=auth_headers)
    assert _categories(client, auth_headers, lid)[0]["price"] == "800.00"


def test_bulk_update_rounds_when_asked(client, auth_headers):
    lid = _list(client, auth_headers)
    client.post(f"/api/price-lists/{lid}/generate-categories",
                json={"count": 1}, headers=auth_headers)
    client.post(f"/api/price-lists/{lid}/generate-prices",
                json={"min_price": "8583", "max_price": "8583", "rounding_step": "0"},
                headers=auth_headers)
    client.post(f"/api/price-lists/{lid}/bulk-update",
                json={"percentage": "0", "rounding_step": "100"}, headers=auth_headers)
    assert _categories(client, auth_headers, lid)[0]["price"] == "8600.00"


# --- currency -------------------------------------------------------------

def test_a_list_defaults_to_pesos_and_accepts_dollars(client, auth_headers):
    default = client.post("/api/price-lists", json={"name": "Mostrador"},
                          headers=auth_headers).json()
    assert default["currency"] == "ARS"
    usd = client.post("/api/price-lists",
                      json={"name": "Importados", "currency": "USD"},
                      headers=auth_headers).json()
    assert usd["currency"] == "USD"


def test_an_unknown_currency_is_rejected(client, auth_headers):
    resp = client.post("/api/price-lists", json={"name": "Raro", "currency": "EUR"},
                       headers=auth_headers)
    assert resp.status_code == 422


# --- the grid summary -----------------------------------------------------

def test_summary_reports_the_shape_of_each_ladder(client, auth_headers):
    lid = _list(client, auth_headers, "Mostrador")
    client.post(f"/api/price-lists/{lid}/generate-categories",
                json={"count": 3}, headers=auth_headers)
    client.post(f"/api/price-lists/{lid}/generate-prices",
                json={"min_price": "1000", "max_price": "3000"}, headers=auth_headers)

    rows = client.get("/api/price-lists/summary", headers=auth_headers).json()
    row = next(r for r in rows if r["id"] == lid)
    assert row["category_count"] == 3
    assert row["min_price"] == "1000.00"
    assert row["max_price"] == "3000.00"
