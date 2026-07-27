def test_create_and_get_product(client, auth_headers, product_type_id):
    resp = client.post(
        "/api/products",
        json={
            "code": "ARM-1", "product_type_id": product_type_id,
            "current_cost": "1000.00", "min_stock": "2",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    pid = resp.json()["id"]
    got = client.get(f"/api/products/{pid}", headers=auth_headers).json()
    assert got["code"] == "ARM-1"
    assert got["current_cost"] == "1000.00"
    assert "name" not in got


def test_product_carries_a_model(client, auth_headers, product_type_id):
    model = client.post(
        "/api/product-models",
        json={"name": "Clipper", "product_type_id": product_type_id},
        headers=auth_headers,
    ).json()
    resp = client.post(
        "/api/products",
        json={"code": "ARM-2", "product_type_id": product_type_id,
              "model_id": model["id"]},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["model_id"] == model["id"]

    listed = client.get(
        f"/api/products?model_id={model['id']}", headers=auth_headers
    ).json()
    assert [p["code"] for p in listed] == ["ARM-2"]


def test_cost_change_is_audited_and_historized(client, auth_headers, product_id):
    resp = client.post(
        f"/api/products/{product_id}/cost",
        json={"new_cost": "250.50", "note": "supplier increase"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["current_cost"] == "250.50"

    history = client.get(
        f"/api/products/{product_id}/cost-history", headers=auth_headers
    ).json()
    assert len(history) == 1
    assert history[0]["new_cost"] == "250.50"
    assert history[0]["old_cost"] == "100.00"
    assert history[0]["note"] == "supplier increase"


def test_update_product_cannot_change_cost_directly(client, auth_headers, product_id):
    # current_cost is not part of ProductUpdate; sending it is ignored.
    resp = client.put(
        f"/api/products/{product_id}",
        json={"description": "Renamed", "current_cost": "9999"},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["description"] == "Renamed"
    assert resp.json()["current_cost"] == "100.00"  # unchanged


def test_list_products_filter_by_type(client, auth_headers, product_type_id):
    client.post(
        "/api/products",
        json={"code": "X-1", "product_type_id": product_type_id},
        headers=auth_headers,
    )
    listed = client.get(
        f"/api/products?product_type_id={product_type_id}", headers=auth_headers
    ).json()
    assert len(listed) >= 1
    assert all(p["product_type_id"] == product_type_id for p in listed)
