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


def test_oversized_strings_are_rejected_not_truncated(client, auth_headers,
                                                      product_type_id):
    """The columns are String(40)/(500)/(8); the schema has to say so.

    Without a max_length the value reaches Postgres and raises DataError, which
    main.py does not map — an unhandled 500 instead of a 422 naming the field.
    SQLite truncates silently, so this test only guards the contract, not the
    behaviour of the database underneath it.
    """
    for field, value in [
        ("code", "X" * 41),
        ("description", "d" * 501),
        ("price_category_code", "TOOLONGCODE"),
    ]:
        payload = {"code": "LEN-1", "product_type_id": product_type_id, field: value}
        resp = client.post("/api/products", json=payload, headers=auth_headers)
        assert resp.status_code == 422, f"{field}: {resp.text}"
        assert resp.json()["detail"][0]["loc"][-1] == field

    # An empty code is not a code either.
    resp = client.post(
        "/api/products",
        json={"code": "", "product_type_id": product_type_id},
        headers=auth_headers,
    )
    assert resp.status_code == 422, resp.text


# --- initial stock ----------------------------------------------------------

def _levels(client, headers, product_id):
    return {
        lv["branch_id"]: lv["quantity"]
        for lv in client.get(
            f"/api/stock/levels?product_id={product_id}", headers=headers
        ).json()
    }


def test_a_new_product_can_arrive_with_its_stock(
    client, auth_headers, product_type_id, branch_id
):
    resp = client.post(
        "/api/products",
        json={"code": "ARM-S1", "product_type_id": product_type_id,
              "initial_stock": [{"branch_id": branch_id, "quantity": "4"}]},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    assert _levels(client, auth_headers, resp.json()["id"]) == {branch_id: "4.00"}
    moves = client.get(
        f"/api/stock/movements?product_id={resp.json()['id']}", headers=auth_headers
    ).json()
    assert [(m["movement_type"], m["note"]) for m in moves] \
        == [("inbound", "Stock inicial")]


def test_initial_stock_lands_on_each_colour_not_the_style(
    client, auth_headers, product_type_id, branch_id
):
    negro, havana = (
        client.post("/api/colors", json={"name": n}, headers=auth_headers).json()["id"]
        for n in ("Negro", "Havana")
    )
    resp = client.post(
        "/api/products",
        json={"code": "ARM-S2", "product_type_id": product_type_id,
              "color_ids": [negro, havana],
              "initial_stock": [
                  {"branch_id": branch_id, "quantity": "2", "color_id": negro},
                  {"branch_id": branch_id, "quantity": "1", "color_id": havana},
              ]},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    style = resp.json()
    variants = {
        v["code"]: v["id"] for v in client.get(
            f"/api/products?parent_id={style['id']}", headers=auth_headers
        ).json()
    }
    assert _levels(client, auth_headers, variants["ARM-S2-NEG"]) == {branch_id: "2.00"}
    assert _levels(client, auth_headers, variants["ARM-S2-HAV"]) == {branch_id: "1.00"}
    assert _levels(client, auth_headers, style["id"]) == {}


def test_stock_without_its_colour_leaves_nothing_behind(
    client, auth_headers, product_type_id, branch_id
):
    negro, havana = (
        client.post("/api/colors", json={"name": n}, headers=auth_headers).json()["id"]
        for n in ("Negro", "Havana")
    )
    resp = client.post(
        "/api/products",
        json={"code": "ARM-S3", "product_type_id": product_type_id,
              "color_ids": [negro, havana],
              "initial_stock": [{"branch_id": branch_id, "quantity": "2"}]},
        headers=auth_headers,
    )
    assert resp.status_code == 400, resp.text
    assert client.get("/api/products?q=ARM-S3", headers=auth_headers).json() == []


def test_initial_stock_refuses_a_branch_of_another_shop(
    client, auth_headers, product_type_id
):
    resp = client.post(
        "/api/products",
        json={"code": "ARM-S4", "product_type_id": product_type_id,
              "initial_stock": [{"branch_id": 999, "quantity": "1"}]},
        headers=auth_headers,
    )
    assert resp.status_code == 400, resp.text


def test_initial_stock_needs_stock_write(client, auth_headers, product_type_id, branch_id):
    perms = {p["code"]: p["id"] for p in client.get(
        "/api/permissions", headers=auth_headers).json()}
    role = client.post(
        "/api/roles",
        json={"name": "Catálogo", "permission_ids":
              [perms["products:read"], perms["products:write"]]},
        headers=auth_headers,
    ).json()
    client.post(
        "/api/users",
        json={"email": "cat@test.com", "full_name": "Cat",
              "password": "catalogo1234", "role_ids": [role["id"]]},
        headers=auth_headers,
    )
    token = client.post("/api/auth/login", json={
        "email": "cat@test.com", "password": "catalogo1234"}).json()["access_token"]
    resp = client.post(
        "/api/products",
        json={"code": "ARM-S5", "product_type_id": product_type_id,
              "initial_stock": [{"branch_id": branch_id, "quantity": "1"}]},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403, resp.text
