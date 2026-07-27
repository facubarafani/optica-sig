"""Product models ("Modelo": clipper, aviador, redondo...)."""


def test_crud_roundtrip(client, auth_headers, product_type_id):
    created = client.post(
        "/api/product-models",
        json={"name": "Clipper", "product_type_id": product_type_id},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    mid = created.json()["id"]

    updated = client.put(
        f"/api/product-models/{mid}", json={"name": "Clip-on"}, headers=auth_headers
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Clip-on"

    assert client.delete(
        f"/api/product-models/{mid}", headers=auth_headers
    ).status_code == 204
    # soft delete: gone from the default listing, still there with include_inactive
    assert client.get("/api/product-models", headers=auth_headers).json() == []
    inactive = client.get(
        "/api/product-models?include_inactive=true", headers=auth_headers
    ).json()
    assert [m["is_active"] for m in inactive] == [False]


def test_filter_by_type_also_returns_untyped_models(
    client, auth_headers, product_type_id
):
    other_type = client.post(
        "/api/product-types", json={"name": "Líquidos"}, headers=auth_headers
    ).json()["id"]

    for payload in (
        {"name": "Clipper", "product_type_id": product_type_id},
        {"name": "Aviador", "product_type_id": product_type_id},
        {"name": "Gotero", "product_type_id": other_type},
        {"name": "Redondo"},  # untyped → applies to every type
    ):
        assert client.post(
            "/api/product-models", json=payload, headers=auth_headers
        ).status_code == 201

    frames = client.get(
        f"/api/product-models?product_type_id={product_type_id}", headers=auth_headers
    ).json()
    assert sorted(m["name"] for m in frames) == ["Aviador", "Clipper", "Redondo"]

    liquids = client.get(
        f"/api/product-models?product_type_id={other_type}", headers=auth_headers
    ).json()
    assert sorted(m["name"] for m in liquids) == ["Gotero", "Redondo"]

    # No filter → everything.
    assert len(client.get("/api/product-models", headers=auth_headers).json()) == 4


def test_duplicate_name_is_rejected(client, auth_headers):
    assert client.post(
        "/api/product-models", json={"name": "Clipper"}, headers=auth_headers
    ).status_code == 201
    dup = client.post(
        "/api/product-models", json={"name": "Clipper"}, headers=auth_headers
    )
    assert dup.status_code == 409, dup.text
