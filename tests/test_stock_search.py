"""Search and filtering on the Stock section."""
import pytest

from app.core import search


# --- the folding helper ----------------------------------------------------

@pytest.mark.parametrize("raw, expected", [
    ("Armazón", "armazon"),
    ("  BORDÓ  ", "bordo"),
    ("Niño", "nino"),
    ("Lentes de sol", "lentes de sol"),
    (None, ""),
])
def test_normalize_folds_case_and_accents(raw, expected):
    assert search.normalize(raw) == expected


@pytest.mark.parametrize("q, expected", [
    ("armazon negro", ["armazon", "negro"]),
    ("  doble   espacio ", ["doble", "espacio"]),
    ("", []),
    (None, []),
])
def test_terms_splits_on_whitespace(q, expected):
    assert search.terms(q) == expected


def test_matches_is_none_when_there_is_nothing_to_search():
    assert search.matches("   ") is None


# --- fixtures --------------------------------------------------------------

@pytest.fixture
def catalogue(client, auth_headers, product_type_id, branch_id):
    """Three products in one branch, with distinct words and accents."""
    other_type = client.post(
        "/api/product-types", json={"name": "Lentes de sol"}, headers=auth_headers
    ).json()["id"]
    black = client.post(
        "/api/colors", json={"name": "Negro"}, headers=auth_headers
    ).json()["id"]

    ids = {}
    for code, desc, ptype, color, min_stock in [
        ("ARM-001", "Armazón clásico negro", product_type_id, black, "2"),
        ("SOL-001", "Lente de sol aviador", other_type, None, "2"),
        ("LC-001", "Lentes de contacto mensual", product_type_id, None, "0"),
    ]:
        ids[code] = client.post(
            "/api/products",
            json={"code": code, "description": desc, "product_type_id": ptype,
                  "color_id": color, "min_stock": min_stock},
            headers=auth_headers,
        ).json()["id"]

    for code, qty in [("ARM-001", 1), ("SOL-001", 10), ("LC-001", 5)]:
        client.post(
            "/api/stock/movements",
            json={"product_id": ids[code], "branch_id": branch_id,
                  "movement_type": "inbound", "quantity": str(qty)},
            headers=auth_headers,
        )
    return {"ids": ids, "branch_id": branch_id, "type": product_type_id,
            "other_type": other_type, "color": black}


def codes(client, auth_headers, query=""):
    levels = client.get(f"/api/stock/levels{query}", headers=auth_headers).json()
    # include_inactive, so the map still names a product this test deactivated.
    products = client.get(
        "/api/products?include_inactive=true", headers=auth_headers
    ).json()
    by_id = {p["id"]: p["code"] for p in products}
    return sorted(by_id[level["product_id"]] for level in levels)


# --- searching -------------------------------------------------------------

def test_search_ignores_accents_and_case(client, auth_headers, catalogue):
    """Nobody types "Armazón" with the accent."""
    assert codes(client, auth_headers, "?q=armazon") == ["ARM-001"]
    assert codes(client, auth_headers, "?q=ARMAZON") == ["ARM-001"]
    assert codes(client, auth_headers, "?q=Armazón") == ["ARM-001"]


def test_search_matches_the_code_too(client, auth_headers, catalogue):
    assert codes(client, auth_headers, "?q=SOL-") == ["SOL-001"]


def test_every_term_must_match_but_order_does_not(client, auth_headers, catalogue):
    assert codes(client, auth_headers, "?q=negro armazon") == ["ARM-001"]
    assert codes(client, auth_headers, "?q=armazon negro") == ["ARM-001"]
    # "lente" alone hits two rows; adding a second term narrows it.
    assert codes(client, auth_headers, "?q=lente") == ["LC-001", "SOL-001"]
    assert codes(client, auth_headers, "?q=lente sol") == ["SOL-001"]
    # A term that matches nothing rules the row out.
    assert codes(client, auth_headers, "?q=armazon inexistente") == []


def test_blank_search_returns_everything(client, auth_headers, catalogue):
    assert codes(client, auth_headers, "?q=") == ["ARM-001", "LC-001", "SOL-001"]
    assert codes(client, auth_headers, "?q=   ") == ["ARM-001", "LC-001", "SOL-001"]


# --- filtering -------------------------------------------------------------

def test_filter_by_product_type_brand_and_color(client, auth_headers, catalogue):
    assert codes(client, auth_headers,
                 f"?product_type_id={catalogue['other_type']}") == ["SOL-001"]
    assert codes(client, auth_headers,
                 f"?color_id={catalogue['color']}") == ["ARM-001"]


def test_low_only_uses_the_product_default_when_there_is_no_override(
    client, auth_headers, catalogue
):
    """The per-branch min_stock is almost always NULL, so the filter has to fall
    back to the product's own minimum — otherwise nothing is ever 'low'."""
    levels = client.get("/api/stock/levels", headers=auth_headers).json()
    assert all(level["min_stock"] is None for level in levels)

    # ARM-001 has 1 on hand against a product minimum of 2.
    assert codes(client, auth_headers, "?low_only=true") == ["ARM-001"]
    # ...and the response exposes what it compared against.
    arm = next(level for level in levels
               if level["product_id"] == catalogue["ids"]["ARM-001"])
    assert arm["effective_min_stock"] == "2.00"


def test_low_only_counts_a_zero_minimum_only_when_stock_runs_out(
    client, auth_headers, catalogue
):
    """LC-001's minimum is 0, so it is low only once it hits 0."""
    assert "LC-001" not in codes(client, auth_headers, "?low_only=true")
    client.post(
        "/api/stock/movements",
        json={"product_id": catalogue["ids"]["LC-001"],
              "branch_id": catalogue["branch_id"],
              "movement_type": "outbound", "quantity": "5"},
        headers=auth_headers,
    )
    assert "LC-001" in codes(client, auth_headers, "?low_only=true")


def test_filters_combine(client, auth_headers, catalogue):
    q = f"?q=armazon&low_only=true&product_type_id={catalogue['type']}"
    assert codes(client, auth_headers, q) == ["ARM-001"]
    # Same search, but the wrong type → nothing.
    assert codes(client, auth_headers,
                 f"?q=armazon&product_type_id={catalogue['other_type']}") == []


def test_inactive_products_are_hidden_unless_asked_for(
    client, auth_headers, catalogue
):
    client.delete(f"/api/products/{catalogue['ids']['ARM-001']}", headers=auth_headers)
    assert codes(client, auth_headers) == ["LC-001", "SOL-001"]
    assert codes(client, auth_headers, "?include_inactive=true") == [
        "ARM-001", "LC-001", "SOL-001"
    ]


# --- the movement ledger ---------------------------------------------------

def test_movements_search_covers_reference_and_note(
    client, auth_headers, catalogue
):
    client.post(
        "/api/stock/movements",
        json={"product_id": catalogue["ids"]["SOL-001"],
              "branch_id": catalogue["branch_id"], "movement_type": "outbound",
              "quantity": "1", "reference": "FAC-0001", "note": "Venta mostrador"},
        headers=auth_headers,
    )

    def refs(query):
        rows = client.get(f"/api/stock/movements{query}", headers=auth_headers).json()
        return [r["reference"] for r in rows]

    assert refs("?q=FAC-0001") == ["FAC-0001"]
    assert refs("?q=mostrador") == ["FAC-0001"]
    assert refs("?q=aviador&movement_type=outbound") == ["FAC-0001"]
    assert refs("?q=aviador&movement_type=inbound") == [None]
    assert refs("?q=no-existe") == []


def test_movement_type_filter(client, auth_headers, catalogue):
    inbound = client.get(
        "/api/stock/movements?movement_type=inbound", headers=auth_headers
    ).json()
    assert len(inbound) == 3
    assert all(m["movement_type"] == "inbound" for m in inbound)
    assert client.get(
        "/api/stock/movements?movement_type=transfer", headers=auth_headers
    ).json() == []


# --- export mirrors the screen ---------------------------------------------

def test_stock_export_respects_the_screen_filters(client, auth_headers, catalogue):
    resp = client.get(
        "/api/imports/stock/export?format=csv&low_only=true", headers=auth_headers
    )
    assert resp.status_code == 200, resp.text
    lines = resp.content.decode("utf-8-sig").splitlines()
    header = lines[0].split(";")
    rows = [line.split(";") for line in lines[1:]]
    assert [r[header.index("Código")] for r in rows] == ["ARM-001"]
