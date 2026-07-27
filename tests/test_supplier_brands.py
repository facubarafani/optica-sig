"""Supplier ↔ brands (N-N). Drives the strict brand filter in the product form."""


def _brand(client, headers, name):
    resp = client.post("/api/brands", json={"name": name}, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_set_and_list_brands(client, auth_headers, supplier_id):
    vulk = _brand(client, auth_headers, "Vulk")
    rusty = _brand(client, auth_headers, "Rusty")
    _brand(client, auth_headers, "Ray-Ban")  # not associated

    assert client.get(
        f"/api/suppliers/{supplier_id}/brands", headers=auth_headers
    ).json() == []

    resp = client.put(
        f"/api/suppliers/{supplier_id}/brands",
        json={"brand_ids": [vulk, rusty]},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert sorted(b["name"] for b in resp.json()) == ["Rusty", "Vulk"]

    listed = client.get(
        f"/api/suppliers/{supplier_id}/brands", headers=auth_headers
    ).json()
    assert sorted(b["name"] for b in listed) == ["Rusty", "Vulk"]


def test_put_replaces_the_whole_set(client, auth_headers, supplier_id):
    vulk = _brand(client, auth_headers, "Vulk")
    rusty = _brand(client, auth_headers, "Rusty")

    client.put(
        f"/api/suppliers/{supplier_id}/brands",
        json={"brand_ids": [vulk, rusty]},
        headers=auth_headers,
    )
    resp = client.put(
        f"/api/suppliers/{supplier_id}/brands",
        json={"brand_ids": [rusty]},
        headers=auth_headers,
    )
    assert [b["name"] for b in resp.json()] == ["Rusty"]

    # Re-sending the same set must not blow up on the unique constraint.
    again = client.put(
        f"/api/suppliers/{supplier_id}/brands",
        json={"brand_ids": [rusty, rusty]},
        headers=auth_headers,
    )
    assert again.status_code == 200
    assert [b["name"] for b in again.json()] == ["Rusty"]


def test_clearing_brands(client, auth_headers, supplier_id, brand_id):
    client.put(
        f"/api/suppliers/{supplier_id}/brands",
        json={"brand_ids": [brand_id]},
        headers=auth_headers,
    )
    resp = client.put(
        f"/api/suppliers/{supplier_id}/brands",
        json={"brand_ids": []},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json() == []


def test_unknown_brand_is_rejected(client, auth_headers, supplier_id):
    resp = client.put(
        f"/api/suppliers/{supplier_id}/brands",
        json={"brand_ids": [9999]},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert "9999" in resp.json()["detail"]


def test_unknown_supplier_is_404(client, auth_headers, brand_id):
    assert client.get(
        "/api/suppliers/9999/brands", headers=auth_headers
    ).status_code == 404
    assert client.put(
        "/api/suppliers/9999/brands",
        json={"brand_ids": [brand_id]},
        headers=auth_headers,
    ).status_code == 404


def test_deactivated_brand_drops_out_of_the_listing(
    client, auth_headers, supplier_id, brand_id
):
    client.put(
        f"/api/suppliers/{supplier_id}/brands",
        json={"brand_ids": [brand_id]},
        headers=auth_headers,
    )
    client.delete(f"/api/brands/{brand_id}", headers=auth_headers)
    assert client.get(
        f"/api/suppliers/{supplier_id}/brands", headers=auth_headers
    ).json() == []
