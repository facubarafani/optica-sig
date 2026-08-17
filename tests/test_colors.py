"""Colours as catalogue master data, and the product's link to one."""
import pytest

from tests.test_imports import run_import


def test_crud_roundtrip(client, auth_headers):
    created = client.post(
        "/api/colors", json={"name": "Havana", "hex_code": "#6B4423"},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    cid = created.json()["id"]
    assert created.json()["hex_code"] == "#6b4423"      # stored lower-cased

    updated = client.put(
        f"/api/colors/{cid}", json={"hex_code": "#8b5a2b"}, headers=auth_headers
    )
    assert updated.status_code == 200
    assert updated.json() == {**updated.json(), "name": "Havana",
                              "hex_code": "#8b5a2b"}

    assert client.delete(f"/api/colors/{cid}", headers=auth_headers).status_code == 204
    # soft delete: gone from the default listing, still there with include_inactive
    assert client.get("/api/colors", headers=auth_headers).json() == []
    inactive = client.get(
        "/api/colors?include_inactive=true", headers=auth_headers
    ).json()
    assert [c["is_active"] for c in inactive] == [False]


@pytest.mark.parametrize("raw, stored", [
    ("#1A1A1A", "#1a1a1a"),
    ("1a1a1a", "#1a1a1a"),       # the '#' is optional
    ("#abc", "#aabbcc"),         # 3-digit shorthand is expanded
    ("  #ABC  ", "#aabbcc"),
    ("", None),                  # blank means "no swatch"
    (None, None),
])
def test_hex_is_normalised(client, auth_headers, raw, stored):
    resp = client.post(
        "/api/colors", json={"name": f"C-{raw!r}", "hex_code": raw},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["hex_code"] == stored


@pytest.mark.parametrize("bad", ["rojo", "#12345", "#gggggg", "#1234567"])
def test_invalid_hex_is_rejected(client, auth_headers, bad):
    resp = client.post(
        "/api/colors", json={"name": "Malo", "hex_code": bad}, headers=auth_headers
    )
    assert resp.status_code == 422, resp.text


def test_duplicate_name_is_rejected(client, auth_headers):
    assert client.post(
        "/api/colors", json={"name": "Negro"}, headers=auth_headers
    ).status_code == 201
    dup = client.post("/api/colors", json={"name": "Negro"}, headers=auth_headers)
    assert dup.status_code == 409, dup.text


def test_product_carries_and_filters_by_color(client, auth_headers, product_type_id):
    black = client.post(
        "/api/colors", json={"name": "Negro", "hex_code": "#1a1a1a"},
        headers=auth_headers,
    ).json()["id"]
    gold = client.post(
        "/api/colors", json={"name": "Dorado"}, headers=auth_headers
    ).json()["id"]

    for code, color_id in (("P-1", black), ("P-2", gold), ("P-3", None)):
        resp = client.post(
            "/api/products",
            json={"code": code, "product_type_id": product_type_id,
                  "color_id": color_id},
            headers=auth_headers,
        )
        assert resp.status_code == 201, resp.text

    only_black = client.get(
        f"/api/products?color_id={black}", headers=auth_headers
    ).json()
    assert [p["code"] for p in only_black] == ["P-1"]
    assert len(client.get("/api/products", headers=auth_headers).json()) == 3


def test_deactivating_a_color_leaves_the_product_pointing_at_it(
    client, auth_headers, product_type_id
):
    """Soft delete, so the FK stays valid and history is not rewritten."""
    cid = client.post(
        "/api/colors", json={"name": "Negro"}, headers=auth_headers
    ).json()["id"]
    pid = client.post(
        "/api/products",
        json={"code": "P-1", "product_type_id": product_type_id, "color_id": cid},
        headers=auth_headers,
    ).json()["id"]

    assert client.delete(f"/api/colors/{cid}", headers=auth_headers).status_code == 204
    product = client.get(f"/api/products/{pid}", headers=auth_headers).json()
    assert product["color_id"] == cid


# --- bulk import / export --------------------------------------------------

def test_import_creates_missing_colors_by_name(client, auth_headers):
    """The file carries the colour *name*; the importer resolves or creates it."""
    _, result = run_import(client, auth_headers, "products", [
        ["Código", "Tipo de producto", "Color", "Costo"],
        ["ARM-001", "Armazones", "Negro", "20000,00"],
        ["ARM-002", "Armazones", "negro", "21000,00"],   # same colour, other case
        ["ARM-003", "Armazones", "Havana", "22000,00"],
    ])
    assert result["created"] == 3
    assert sorted(result["created_refs"]["Color"]) == ["Havana", "Negro"]

    colors = {c["name"]: c["id"]
              for c in client.get("/api/colors", headers=auth_headers).json()}
    assert sorted(colors) == ["Havana", "Negro"]
    # A colour born of an import has no swatch until someone picks one.
    assert all(c["hex_code"] is None
               for c in client.get("/api/colors", headers=auth_headers).json())

    products = {p["code"]: p["color_id"]
                for p in client.get("/api/products", headers=auth_headers).json()}
    assert products["ARM-001"] == products["ARM-002"] == colors["Negro"]
    assert products["ARM-003"] == colors["Havana"]


def test_export_writes_the_color_name_so_the_file_round_trips(
    client, auth_headers, product_type_id
):
    cid = client.post(
        "/api/colors", json={"name": "Havana", "hex_code": "#6b4423"},
        headers=auth_headers,
    ).json()["id"]
    client.post(
        "/api/products",
        json={"code": "ARM-001", "product_type_id": product_type_id,
              "color_id": cid},
        headers=auth_headers,
    )

    resp = client.get("/api/imports/products/export?format=csv", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.content.decode("utf-8-sig")
    header, row = body.splitlines()[0].split(";"), body.splitlines()[1].split(";")
    assert row[header.index("Color")] == "Havana"
