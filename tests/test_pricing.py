def _setup_list_with_items(client, headers):
    cat_a = client.post(
        "/api/price-categories", json={"name": "A"}, headers=headers
    ).json()["id"]
    cat_b = client.post(
        "/api/price-categories", json={"name": "B"}, headers=headers
    ).json()["id"]
    plist = client.post(
        "/api/price-lists", json={"name": "General", "is_default": True}, headers=headers
    ).json()["id"]
    client.post(
        f"/api/price-lists/{plist}/items",
        json={"price_category_id": cat_a, "price": "1000.00"},
        headers=headers,
    )
    client.post(
        f"/api/price-lists/{plist}/items",
        json={"price_category_id": cat_b, "price": "500.00"},
        headers=headers,
    )
    return plist


def test_price_list_items(client, auth_headers):
    plist = _setup_list_with_items(client, auth_headers)
    items = client.get(f"/api/price-lists/{plist}/items", headers=auth_headers).json()
    assert len(items) == 2
    assert {i["price"] for i in items} == {"1000.00", "500.00"}


def test_bulk_percentage_update(client, auth_headers):
    plist = _setup_list_with_items(client, auth_headers)
    resp = client.post(
        f"/api/price-lists/{plist}/bulk-update",
        json={"percentage": "10"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["updated_items"] == 2

    items = client.get(f"/api/price-lists/{plist}/items", headers=auth_headers).json()
    prices = {i["price"] for i in items}
    assert prices == {"1100.00", "550.00"}  # +10%


def test_price_category_unique_per_company(client, auth_headers):
    client.post("/api/price-categories", json={"name": "A"}, headers=auth_headers)
    dup = client.post("/api/price-categories", json={"name": "A"}, headers=auth_headers)
    # unique (company_id, name) constraint => 409 Conflict
    assert dup.status_code == 409
