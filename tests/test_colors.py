"""Colours as catalogue master data, and the colours a product comes in."""
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


@pytest.fixture()
def palette(client, auth_headers):
    """{name: id} for a small palette."""
    out = {}
    for name, hex_code in [("Negro", "#1a1a1a"), ("Dorado", None),
                           ("Havana", "#6b4423")]:
        out[name] = client.post(
            "/api/colors", json={"name": name, "hex_code": hex_code},
            headers=auth_headers,
        ).json()["id"]
    return out


def test_a_product_carries_its_colors_and_is_found_by_them(
    client, auth_headers, product_type_id, palette
):
    black, gold, havana = palette["Negro"], palette["Dorado"], palette["Havana"]
    for code, color_ids in (
        ("P-1", [gold]),
        ("P-2", []),                   # none picked yet
    ):
        resp = client.post(
            "/api/products",
            json={"code": code, "product_type_id": product_type_id,
                  "color_ids": color_ids},
            headers=auth_headers,
        )
        assert resp.status_code == 201, resp.text

    found = client.get(f"/api/products?color_id={gold}", headers=auth_headers).json()
    assert [p["code"] for p in found] == ["P-1"]
    assert client.get(f"/api/products?color_id={black}",
                      headers=auth_headers).json() == []

    # Several colours on one row means several articles — see test_variants.
    p3 = client.post(
        "/api/products",
        json={"code": "P-3", "product_type_id": product_type_id,
              "color_ids": [havana, black]},
        headers=auth_headers,
    ).json()
    # Ordered by name, and expanded so a grid can paint swatches in one request.
    assert [c["name"] for c in p3["colors"]] == ["Havana", "Negro"]
    assert [c["hex_code"] for c in p3["colors"]] == ["#6b4423", "#1a1a1a"]
    assert p3["color_ids"] == [havana, black]
    # The filter reaches the family: the style and the article for that colour.
    assert sorted(p["code"] for p in client.get(
        f"/api/products?color_id={black}", headers=auth_headers).json()
    ) == ["P-3", "P-3-NEG"]


def test_colors_are_replaced_wholesale_and_only_when_sent(
    client, auth_headers, product_type_id, palette
):
    black, gold, havana = palette["Negro"], palette["Dorado"], palette["Havana"]
    pid = client.post(
        "/api/products",
        json={"code": "P-1", "product_type_id": product_type_id,
              "color_ids": [black, gold]},
        headers=auth_headers,
    ).json()["id"]

    def colors_of(resp):
        return sorted(resp.json()["color_ids"])

    # A payload without color_ids leaves them alone...
    untouched = client.put(
        f"/api/products/{pid}", json={"description": "Otra"}, headers=auth_headers
    )
    assert colors_of(untouched) == sorted([black, gold])

    # ...one with them replaces the whole set (no merge)...
    replaced = client.put(
        f"/api/products/{pid}", json={"color_ids": [havana]}, headers=auth_headers
    )
    assert colors_of(replaced) == [havana]

    # ...and an empty list clears it.
    cleared = client.put(
        f"/api/products/{pid}", json={"color_ids": []}, headers=auth_headers
    )
    assert cleared.json()["color_ids"] == []


def test_repeated_ids_collapse(client, auth_headers, product_type_id, palette):
    resp = client.post(
        "/api/products",
        json={"code": "P-1", "product_type_id": product_type_id,
              "color_ids": [palette["Negro"], palette["Negro"]]},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["color_ids"] == [palette["Negro"]]


def test_unknown_color_is_rejected(client, auth_headers, product_type_id):
    resp = client.post(
        "/api/products",
        json={"code": "P-1", "product_type_id": product_type_id,
              "color_ids": [9999]},
        headers=auth_headers,
    )
    assert resp.status_code == 400, resp.text
    assert "9999" in resp.json()["detail"]
    # The failed create left nothing behind.
    assert client.get("/api/products", headers=auth_headers).json() == []


def test_deactivating_a_color_leaves_the_product_pointing_at_it(
    client, auth_headers, product_type_id
):
    """Soft delete, so the FK stays valid and history is not rewritten."""
    cid = client.post(
        "/api/colors", json={"name": "Negro"}, headers=auth_headers
    ).json()["id"]
    pid = client.post(
        "/api/products",
        json={"code": "P-1", "product_type_id": product_type_id,
              "color_ids": [cid]},
        headers=auth_headers,
    ).json()["id"]

    assert client.delete(f"/api/colors/{cid}", headers=auth_headers).status_code == 204
    product = client.get(f"/api/products/{pid}", headers=auth_headers).json()
    assert product["color_ids"] == [cid]


# --- bulk import / export --------------------------------------------------

def test_import_creates_missing_colors_by_name(client, auth_headers):
    """The file carries colour *names*; the importer resolves or creates each."""
    _, result = run_import(client, auth_headers, "products", [
        ["Código", "Tipo de producto", "Color", "Costo"],
        ["ARM-001", "Armazones", "Negro", "20000,00"],
        ["ARM-002", "Armazones", "negro", "21000,00"],   # same colour, other case
        ["ARM-003", "Armazones", "Havana , Negro", "22000,00"],   # several
        ["ARM-004", "Armazones", "Carey, carey", "23000,00"],     # a repeat
    ])
    assert result["created"] == 4
    assert sorted(result["created_refs"]["Color"]) == ["Carey", "Havana", "Negro"]

    colors = {c["name"]: c["id"]
              for c in client.get("/api/colors", headers=auth_headers).json()}
    assert sorted(colors) == ["Carey", "Havana", "Negro"]
    # A colour born of an import has no swatch until someone picks one.
    assert all(c["hex_code"] is None
               for c in client.get("/api/colors", headers=auth_headers).json())

    products = {p["code"]: sorted(p["color_ids"])
                for p in client.get("/api/products", headers=auth_headers).json()}
    assert products["ARM-001"] == products["ARM-002"] == [colors["Negro"]]
    assert products["ARM-003"] == sorted([colors["Havana"], colors["Negro"]])
    assert products["ARM-004"] == [colors["Carey"]]


def test_reimporting_replaces_the_color_set(client, auth_headers):
    def rows(colors):
        return [["Código", "Tipo de producto", "Color"],
                ["ARM-001", "Armazones", colors]]

    run_import(client, auth_headers, "products", rows("Negro, Havana"))
    run_import(client, auth_headers, "products", rows("Dorado"))

    product = client.get("/api/products", headers=auth_headers).json()[0]
    assert [c["name"] for c in product["colors"]] == ["Dorado"]


def test_export_writes_the_color_names_so_the_file_round_trips(
    client, auth_headers, product_type_id
):
    ids = [
        client.post("/api/colors", json={"name": name}, headers=auth_headers)
              .json()["id"]
        for name in ("Havana", "Negro")
    ]
    client.post(
        "/api/products",
        json={"code": "ARM-001", "product_type_id": product_type_id,
              "color_ids": ids},
        headers=auth_headers,
    )

    resp = client.get("/api/imports/products/export?format=csv", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    body = resp.content.decode("utf-8-sig")
    lines = body.splitlines()
    header, row = lines[0].split(";"), lines[1].split(";")
    # The importer splits this cell back into the same two colours.
    assert row[header.index("Colores")] == "Havana, Negro"
