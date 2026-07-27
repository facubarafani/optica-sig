"""Selling price: manual, by list+category, and the company-default fallback."""
import pytest

from app.models.audit import ChangeHistory


@pytest.fixture
def category_id(client, auth_headers):
    resp = client.post("/api/price-categories", json={"name": "Cat A"}, headers=auth_headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _price_list(client, headers, name, category_id, price, **extra):
    lst = client.post("/api/price-lists", json={"name": name, **extra}, headers=headers)
    assert lst.status_code == 201, lst.text
    lid = lst.json()["id"]
    item = client.post(
        f"/api/price-lists/{lid}/items",
        json={"price_category_id": category_id, "price": price},
        headers=headers,
    )
    assert item.status_code == 201, item.text
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


def test_price_from_the_products_own_list(client, auth_headers, product_type_id, category_id):
    lid = _price_list(client, auth_headers, "Armazones por receta", category_id, "50000.00")
    p = _make_product(client, auth_headers, product_type_id, code="L-1",
                      price_list_id=lid, price_category_id=category_id)
    assert p["resolved_sale_price"] == "50000.00"
    assert p["price_source"] == "price_list"


def test_falls_back_to_the_company_default_list(
    client, auth_headers, product_type_id, category_id
):
    lid = _price_list(client, auth_headers, "General", category_id, "30000.00")
    client.put("/api/company/settings", json={"default_price_list_id": lid}, headers=auth_headers)

    # No list on the product → the company default applies.
    p = _make_product(client, auth_headers, product_type_id, code="D-1",
                      price_category_id=category_id)
    assert p["resolved_sale_price"] == "30000.00"
    assert p["price_source"] == "price_list"


def test_products_own_list_wins_over_the_company_default(
    client, auth_headers, product_type_id, category_id
):
    default_id = _price_list(client, auth_headers, "General", category_id, "30000.00")
    own_id = _price_list(client, auth_headers, "Especial", category_id, "99000.00")
    client.put("/api/company/settings", json={"default_price_list_id": default_id},
               headers=auth_headers)

    p = _make_product(client, auth_headers, product_type_id, code="W-1",
                      price_list_id=own_id, price_category_id=category_id)
    assert p["resolved_sale_price"] == "99000.00"


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


def test_category_without_a_price_in_the_list(
    client, auth_headers, product_type_id, category_id
):
    other = client.post("/api/price-categories", json={"name": "Cat B"},
                        headers=auth_headers).json()["id"]
    lid = _price_list(client, auth_headers, "General", category_id, "30000.00")
    p = _make_product(client, auth_headers, product_type_id, code="N-1",
                      price_list_id=lid, price_category_id=other)
    assert p["resolved_sale_price"] is None
    assert "no tiene precio para esa categoría" in p["price_reason"]


def test_list_scoped_to_another_product_type_is_rejected(
    client, auth_headers, product_type_id, category_id
):
    other_type = client.post("/api/product-types", json={"name": "Líquidos"},
                             headers=auth_headers).json()["id"]
    lid = _price_list(client, auth_headers, "Sólo líquidos", category_id, "1000.00",
                      product_type_id=other_type)
    resp = client.post(
        "/api/products",
        json={"code": "X-1", "product_type_id": product_type_id,
              "price_list_id": lid, "price_category_id": category_id},
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


def test_price_endpoint_explains_the_source(
    client, auth_headers, product_type_id, category_id
):
    lid = _price_list(client, auth_headers, "General", category_id, "30000.00")
    p = _make_product(client, auth_headers, product_type_id, code="E-1",
                      price_list_id=lid, price_category_id=category_id)
    resp = client.get(f"/api/products/{p['id']}/price", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["price"] == "30000.00"
    assert body["source"] == "price_list"
    assert body["price_list_id"] == lid
