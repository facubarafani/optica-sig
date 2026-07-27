"""Selling price: manual, by list+code, and the company-default fallback."""
import pytest

from app.models.audit import ChangeHistory


def _price_list(client, headers, name, code, price, **extra):
    """A list with a single category ``code`` priced at ``price``."""
    lst = client.post("/api/price-lists", json={"name": name, **extra}, headers=headers)
    assert lst.status_code == 201, lst.text
    lid = lst.json()["id"]
    cat = client.post(
        f"/api/price-lists/{lid}/categories",
        json={"code": code, "price": price},
        headers=headers,
    )
    assert cat.status_code == 201, cat.text
    return lid


def _make_product(client, headers, product_type_id, **fields):
    resp = client.post(
        "/api/products",
        json={"code": fields.pop("code", "P-X"), "product_type_id": product_type_id, **fields},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_manual_price(client, auth_headers, product_type_id):
    p = _make_product(client, auth_headers, product_type_id,
                      code="M-1", pricing_mode="manual", sale_price="85000.00")
    assert p["resolved_sale_price"] == "85000.00"
    assert p["price_source"] == "manual"


def test_price_from_the_products_own_list(client, auth_headers, product_type_id):
    lid = _price_list(client, auth_headers, "Armazones por receta", "AA", "50000.00")
    p = _make_product(client, auth_headers, product_type_id, code="L-1",
                      price_list_id=lid, price_category_code="AA")
    assert p["resolved_sale_price"] == "50000.00"
    assert p["price_source"] == "price_list"


def test_falls_back_to_the_company_default_list(client, auth_headers, product_type_id):
    lid = _price_list(client, auth_headers, "General", "AA", "30000.00")
    client.put("/api/company/settings", json={"default_price_list_id": lid}, headers=auth_headers)

    # No list on the product → the company default applies.
    p = _make_product(client, auth_headers, product_type_id, code="D-1",
                      price_category_code="AA")
    assert p["resolved_sale_price"] == "30000.00"
    assert p["price_source"] == "price_list"


def test_products_own_list_wins_over_the_company_default(
    client, auth_headers, product_type_id
):
    default_id = _price_list(client, auth_headers, "General", "AA", "30000.00")
    own_id = _price_list(client, auth_headers, "Especial", "AA", "99000.00")
    client.put("/api/company/settings", json={"default_price_list_id": default_id},
               headers=auth_headers)

    p = _make_product(client, auth_headers, product_type_id, code="W-1",
                      price_list_id=own_id, price_category_code="AA")
    assert p["resolved_sale_price"] == "99000.00"


def test_one_code_is_priced_by_whichever_list_applies(
    client, auth_headers, product_type_id
):
    """The point of tagging by code: two lists, two prices, one product."""
    counter = _price_list(client, auth_headers, "Mostrador", "AB", "12400.00")
    wholesale = _price_list(client, auth_headers, "Mayorista", "AB", "9900.00")

    p = _make_product(client, auth_headers, product_type_id, code="C-1",
                      price_list_id=counter, price_category_code="AB")
    assert p["resolved_sale_price"] == "12400.00"

    moved = client.put(f"/api/products/{p['id']}",
                       json={"price_list_id": wholesale}, headers=auth_headers)
    assert moved.json()["resolved_sale_price"] == "9900.00"


def test_the_code_is_matched_case_insensitively(client, auth_headers, product_type_id):
    lid = _price_list(client, auth_headers, "General", "AB", "4200.00")
    p = _make_product(client, auth_headers, product_type_id, code="I-1",
                      price_list_id=lid, price_category_code="ab")
    assert p["price_category_code"] == "AB"
    assert p["resolved_sale_price"] == "4200.00"


def test_the_price_carries_the_lists_currency(client, auth_headers, product_type_id):
    lid = _price_list(client, auth_headers, "Importados", "AA", "180.00", currency="USD")
    p = _make_product(client, auth_headers, product_type_id, code="U-2",
                      price_list_id=lid, price_category_code="AA")
    assert p["resolved_sale_price"] == "180.00"
    assert p["price_currency"] == "USD"


@pytest.mark.parametrize(
    "fields, expected_reason_fragment",
    [
        ({}, "lista por defecto"),                       # no list anywhere
        ({"pricing_mode": "manual"}, "sin cargar"),      # manual with no price
    ],
)
def test_unresolved_prices_explain_themselves(
    client, auth_headers, product_type_id, fields, expected_reason_fragment
):
    p = _make_product(client, auth_headers, product_type_id, code="U-1", **fields)
    assert p["resolved_sale_price"] is None
    assert p["price_source"] == "unresolved"
    assert expected_reason_fragment in p["price_reason"]


def test_a_code_the_list_does_not_have(client, auth_headers, product_type_id):
    lid = _price_list(client, auth_headers, "General", "AA", "30000.00")
    p = _make_product(client, auth_headers, product_type_id, code="N-1",
                      price_list_id=lid, price_category_code="AB")
    assert p["resolved_sale_price"] is None
    assert 'no tiene la categoría "AB"' in p["price_reason"]


def test_a_deactivated_category_stops_pricing(client, auth_headers, product_type_id):
    lid = _price_list(client, auth_headers, "General", "AA", "30000.00")
    cat = client.get(f"/api/price-lists/{lid}/categories", headers=auth_headers).json()[0]
    client.delete(f"/api/price-lists/{lid}/categories/{cat['id']}", headers=auth_headers)

    p = _make_product(client, auth_headers, product_type_id, code="X-3",
                      price_list_id=lid, price_category_code="AA")
    assert p["resolved_sale_price"] is None


def test_list_scoped_to_another_product_type_is_rejected(
    client, auth_headers, product_type_id
):
    other_type = client.post("/api/product-types", json={"name": "Líquidos"},
                             headers=auth_headers).json()["id"]
    lid = _price_list(client, auth_headers, "Sólo líquidos", "AA", "1000.00",
                      product_type_id=other_type)
    resp = client.post(
        "/api/products",
        json={"code": "X-1", "product_type_id": product_type_id,
              "price_list_id": lid, "price_category_code": "AA"},
        headers=auth_headers,
    )
    assert resp.status_code == 400, resp.text
    assert "otro tipo de producto" in resp.json()["detail"]


def test_negative_manual_price_is_rejected(client, auth_headers, product_type_id):
    resp = client.post(
        "/api/products",
        json={"code": "X-2", "product_type_id": product_type_id,
              "pricing_mode": "manual", "sale_price": "-1"},
        headers=auth_headers,
    )
    assert resp.status_code == 400


def test_pricing_changes_are_audited(client, auth_headers, db, product_id):
    resp = client.put(
        f"/api/products/{product_id}",
        json={"pricing_mode": "manual", "sale_price": "12345.00"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["resolved_sale_price"] == "12345.00"

    rows = (
        db.query(ChangeHistory)
        .filter(ChangeHistory.entity_type == "product",
                ChangeHistory.entity_id == product_id)
        .all()
    )
    changed = {r.field_name: (r.old_value, r.new_value) for r in rows}
    assert "pricing_mode" in changed
    assert changed["pricing_mode"][1] == "manual"
    assert changed["sale_price"] == (None, "12345.00")


def test_changing_the_category_code_is_audited(client, auth_headers, db, product_id):
    client.put(f"/api/products/{product_id}",
               json={"price_category_code": "AC"}, headers=auth_headers)
    rows = (
        db.query(ChangeHistory)
        .filter(ChangeHistory.entity_type == "product",
                ChangeHistory.entity_id == product_id,
                ChangeHistory.field_name == "price_category_code")
        .all()
    )
    assert len(rows) == 1
    assert rows[0].new_value == "AC"


def test_unchanged_pricing_fields_are_not_audited(client, auth_headers, db, product_id):
    client.put(f"/api/products/{product_id}",
               json={"pricing_mode": "price_list"}, headers=auth_headers)
    rows = (
        db.query(ChangeHistory)
        .filter(ChangeHistory.entity_type == "product",
                ChangeHistory.entity_id == product_id)
        .all()
    )
    assert rows == []


def test_price_endpoint_explains_the_source(client, auth_headers, product_type_id):
    lid = _price_list(client, auth_headers, "General", "AA", "30000.00")
    p = _make_product(client, auth_headers, product_type_id, code="E-1",
                      price_list_id=lid, price_category_code="AA")
    resp = client.get(f"/api/products/{p['id']}/price", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["price"] == "30000.00"
    assert body["source"] == "price_list"
    assert body["price_list_id"] == lid
    assert body["currency"] == "ARS"


def test_category_codes_endpoint_lists_every_code_in_use(client, auth_headers):
    _price_list(client, auth_headers, "Mostrador", "AA", "100")
    _price_list(client, auth_headers, "Mayorista", "AA", "80")
    _price_list(client, auth_headers, "Especial", "AB", "500")

    rows = client.get("/api/price-category-codes", headers=auth_headers).json()
    by_code = {r["code"]: r["list_count"] for r in rows}
    assert by_code == {"AA": 2, "AB": 1}
