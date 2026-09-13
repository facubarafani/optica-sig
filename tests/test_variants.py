"""A product is a style; each colour it is stocked in is its own article.

The style groups; the variants are what a shop counts, prices and sells. These
tests pin the two halves of that: the generator that turns colours into coded
articles, and the rule that a style is never itself sold or stocked.
"""
import pytest

from tests.test_imports import run_import, upload, xlsx


@pytest.fixture()
def palette(client, auth_headers):
    """{name: id} for a small palette, each with its derived code."""
    return {
        name: client.post(
            "/api/colors", json={"name": name}, headers=auth_headers
        ).json()["id"]
        for name in ("Negro", "Havana", "Dorado")
    }


@pytest.fixture()
def style(client, auth_headers, product_type_id):
    """A style with everything a variant should inherit."""
    return client.post(
        "/api/products",
        json={"code": "ARM-001", "description": "Armazón clásico",
              "product_type_id": product_type_id, "min_stock": "3",
              "current_cost": "20000.00", "price_category_code": "AB"},
        headers=auth_headers,
    ).json()


# --- colour codes ----------------------------------------------------------

def test_color_code_is_derived_from_the_name(client, auth_headers):
    created = client.post(
        "/api/colors", json={"name": "Havana"}, headers=auth_headers
    ).json()
    assert created["code"] == "HAV"


def test_derived_codes_lengthen_before_they_number(client, auth_headers):
    """"Verde"/"Verde militar" read better as VER/VERD than VER/VER2."""
    codes = [
        client.post("/api/colors", json={"name": n}, headers=auth_headers)
              .json()["code"]
        for n in ("Verde", "Verde militar", "Verde agua")
    ]
    assert codes == ["VER", "VERD", "VERDE"]


def test_a_name_shorter_than_three_is_its_own_code(client, auth_headers):
    """"C1" used to skip the length loop and number straight to C12."""
    assert client.post(
        "/api/colors", json={"name": "C1"}, headers=auth_headers
    ).json()["code"] == "C1"


def test_accents_are_folded(client, auth_headers):
    assert client.post(
        "/api/colors", json={"name": "Marrón"}, headers=auth_headers
    ).json()["code"] == "MAR"


def test_an_explicit_code_wins(client, auth_headers):
    assert client.post(
        "/api/colors", json={"name": "Havana", "code": "hv"}, headers=auth_headers
    ).json()["code"] == "HV"        # upper-cased, not derived


def test_duplicate_code_is_rejected(client, auth_headers):
    client.post("/api/colors", json={"name": "Negro", "code": "N1"},
                headers=auth_headers)
    dup = client.post("/api/colors", json={"name": "Nuevo", "code": "N1"},
                      headers=auth_headers)
    assert dup.status_code == 409, dup.text


# --- generating variants ---------------------------------------------------

def test_variants_are_coded_from_the_style_and_the_colour(
    client, auth_headers, style, palette
):
    resp = client.post(
        f"/api/products/{style['id']}/variants",
        json={"color_ids": [palette["Negro"], palette["Havana"]]},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    assert [v["code"] for v in resp.json()] == ["ARM-001-NEG", "ARM-001-HAV"]
    assert all(v["parent_id"] == style["id"] for v in resp.json())
    assert [[c["name"] for c in v["colors"]] for v in resp.json()] \
        == [["Negro"], ["Havana"]]


def test_a_short_colour_name_suffixes_the_code_as_is(client, auth_headers, style):
    c1 = client.post(
        "/api/colors", json={"name": "C1"}, headers=auth_headers
    ).json()["id"]
    resp = client.post(
        f"/api/products/{style['id']}/variants",
        json={"color_ids": [c1]}, headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    assert [v["code"] for v in resp.json()] == ["ARM-001-C1"]


def test_a_variant_inherits_the_style(client, auth_headers, style, palette):
    """It is the same article in another colour, so it starts out identical."""
    variant = client.post(
        f"/api/products/{style['id']}/variants",
        json={"color_ids": [palette["Negro"]]}, headers=auth_headers,
    ).json()[0]
    for field in ("description", "product_type_id", "min_stock",
                  "current_cost", "price_category_code", "pricing_mode"):
        assert variant[field] == style[field], field
    # ...but its identity is its own
    assert variant["code"] != style["code"]


def test_a_bicolour_variant_is_one_article(client, auth_headers, style, palette):
    variant = client.post(
        f"/api/products/{style['id']}/variants",
        json={"variants": [{"color_ids": [palette["Negro"], palette["Dorado"]]}]},
        headers=auth_headers,
    ).json()[0]
    assert variant["code"] == "ARM-001-NEG-DOR"
    assert sorted(c["name"] for c in variant["colors"]) == ["Dorado", "Negro"]


def test_an_explicit_variant_code_wins(client, auth_headers, style, palette):
    variant = client.post(
        f"/api/products/{style['id']}/variants",
        json={"variants": [{"color_ids": [palette["Negro"]], "code": "ARM-1-N"}]},
        headers=auth_headers,
    ).json()[0]
    assert variant["code"] == "ARM-1-N"


def test_a_taken_code_is_bumped_not_rejected(client, auth_headers, style, palette,
                                             product_type_id):
    """Re-running a generation must not fail on a code someone already used."""
    client.post("/api/products",
                json={"code": "ARM-001-NEG", "product_type_id": product_type_id},
                headers=auth_headers)
    variant = client.post(
        f"/api/products/{style['id']}/variants",
        json={"color_ids": [palette["Negro"]]}, headers=auth_headers,
    ).json()[0]
    assert variant["code"] == "ARM-001-NEG-2"


def test_variants_do_not_nest(client, auth_headers, style, palette):
    variant = client.post(
        f"/api/products/{style['id']}/variants",
        json={"color_ids": [palette["Negro"]]}, headers=auth_headers,
    ).json()[0]
    resp = client.post(
        f"/api/products/{variant['id']}/variants",
        json={"color_ids": [palette["Havana"]]}, headers=auth_headers,
    )
    assert resp.status_code == 400
    assert "no se anidan" in resp.json()["detail"]


def test_a_failed_batch_leaves_no_half_family(client, auth_headers, style, palette):
    resp = client.post(
        f"/api/products/{style['id']}/variants",
        json={"variants": [{"color_ids": [palette["Negro"]]},
                           {"color_ids": [9999]}]},     # second one cannot resolve
        headers=auth_headers,
    )
    assert resp.status_code == 400, resp.text
    assert client.get(f"/api/products/{style['id']}/variants",
                      headers=auth_headers).json() == []


# --- a style is not an article ---------------------------------------------

def test_a_style_cannot_be_sold(client, auth_headers, style, palette, branch_id):
    client.post(f"/api/products/{style['id']}/variants",
                json={"color_ids": [palette["Negro"]]}, headers=auth_headers)
    resp = client.post(
        "/api/sales",
        json={"branch_id": branch_id,
              "items": [{"product_id": style["id"], "quantity": "1",
                         "unit_price": "1000"}]},
        headers=auth_headers,
    )
    assert resp.status_code == 400, resp.text
    assert "producto base" in resp.json()["detail"]


def test_a_style_cannot_be_stocked(client, auth_headers, style, palette, branch_id):
    client.post(f"/api/products/{style['id']}/variants",
                json={"color_ids": [palette["Negro"]]}, headers=auth_headers)
    resp = client.post(
        "/api/stock/movements",
        json={"product_id": style["id"], "branch_id": branch_id,
              "movement_type": "inbound", "quantity": "5"},
        headers=auth_headers,
    )
    assert resp.status_code == 400, resp.text
    assert "producto base" in resp.json()["detail"]


def test_its_variants_can_be_sold_and_stocked(
    client, auth_headers, style, palette, branch_id
):
    variant = client.post(
        f"/api/products/{style['id']}/variants",
        json={"color_ids": [palette["Negro"]]}, headers=auth_headers,
    ).json()[0]
    assert client.post(
        "/api/stock/movements",
        json={"product_id": variant["id"], "branch_id": branch_id,
              "movement_type": "inbound", "quantity": "5"},
        headers=auth_headers,
    ).status_code == 201
    sale = client.post(
        "/api/sales",
        json={"branch_id": branch_id,
              "items": [{"product_id": variant["id"], "quantity": "1",
                         "unit_price": "1000"}],
              "payments": [{"amount": "1000", "method": "cash"}]},
        headers=auth_headers,
    )
    assert sale.status_code == 201, sale.text


def test_a_stocked_product_refuses_to_become_a_style(
    client, auth_headers, style, palette, branch_id
):
    """Its stock belongs to a colour nobody recorded — the shop has to say which."""
    client.post(
        "/api/stock/movements",
        json={"product_id": style["id"], "branch_id": branch_id,
              "movement_type": "inbound", "quantity": "4"},
        headers=auth_headers,
    )
    resp = client.post(
        f"/api/products/{style['id']}/variants",
        json={"color_ids": [palette["Negro"]]}, headers=auth_headers,
    )
    assert resp.status_code == 400, resp.text
    assert "ajustalo a cero" in resp.json()["detail"]


def test_a_hand_set_parent_refuses_a_stocked_style(
    client, auth_headers, style, palette, branch_id, product_type_id
):
    """The same rule, reached the other way round.

    ``POST /products`` and ``PUT /products/{id}`` both accept a parent_id, so
    naming a stocked article as your parent is a second way to turn it into a
    style — and it used to succeed, stranding that stock on a row nothing may
    sell or move. Both doors have to refuse it, or the two ways of building a
    family disagree.
    """
    client.post(
        "/api/stock/movements",
        json={"product_id": style["id"], "branch_id": branch_id,
              "movement_type": "inbound", "quantity": "4"},
        headers=auth_headers,
    )
    resp = client.post(
        "/api/products",
        json={"code": "ARM-001-NEG", "product_type_id": product_type_id,
              "parent_id": style["id"]},
        headers=auth_headers,
    )
    assert resp.status_code == 400, resp.text
    assert "ajustalo a cero" in resp.json()["detail"]


# --- how the lists slice the family ----------------------------------------

def test_the_filters_slice_the_family(client, auth_headers, style, palette,
                                      product_type_id):
    client.post("/api/products",
                json={"code": "LC-001", "product_type_id": product_type_id},
                headers=auth_headers)                       # plain article
    client.post(f"/api/products/{style['id']}/variants",
                json={"color_ids": [palette["Negro"], palette["Havana"]]},
                headers=auth_headers)

    def codes(qs):
        listed = client.get(f"/api/products{qs}", headers=auth_headers).json()
        return sorted(p["code"] for p in listed)

    assert codes("") == ["ARM-001", "ARM-001-HAV", "ARM-001-NEG", "LC-001"]
    # the grid: one line per family
    assert codes("?only_base=true") == ["ARM-001", "LC-001"]
    # the sales picker: everything that can go on a line, never the style
    assert codes("?sellable_only=true") == ["ARM-001-HAV", "ARM-001-NEG", "LC-001"]
    assert codes(f"?parent_id={style['id']}") == ["ARM-001-HAV", "ARM-001-NEG"]

    listed = client.get("/api/products?only_base=true", headers=auth_headers).json()
    counts = {p["code"]: p["variant_count"] for p in listed}
    assert counts == {"ARM-001": 2, "LC-001": 0}


def test_a_variant_reports_the_style_it_belongs_to(
    client, auth_headers, style, palette
):
    variant = client.post(
        f"/api/products/{style['id']}/variants",
        json={"color_ids": [palette["Negro"]]}, headers=auth_headers,
    ).json()[0]
    fetched = client.get(f"/api/products/{variant['id']}", headers=auth_headers).json()
    assert fetched["parent_id"] == style["id"]
    assert fetched["parent_code"] == "ARM-001"


# --- bulk import / export --------------------------------------------------

def test_import_links_a_variant_to_its_style(client, auth_headers):
    _, result = run_import(client, auth_headers, "products", [
        ["Código", "Tipo de producto", "Producto base", "Color"],
        ["ARM-001", "Armazones", "", ""],
        ["ARM-001-NEG", "Armazones", "ARM-001", "Negro"],
        ["ARM-001-HAV", "Armazones", "ARM-001", "Havana"],
    ])
    assert result["created"] == 3
    by_code = {p["code"]: p
               for p in client.get("/api/products", headers=auth_headers).json()}
    assert by_code["ARM-001"]["variant_count"] == 2
    assert by_code["ARM-001-NEG"]["parent_code"] == "ARM-001"


def _try_import(client, headers, rows):
    """Preview a products file, then try to commit it anyway."""
    up = upload(client, headers, "products", xlsx(rows)).json()
    opts = {"mapping": up["suggested_mapping"], "decimal_format": "es",
            "create_missing": True}
    preview = client.post(f"/api/imports/batches/{up['batch_id']}/preview",
                          json=opts, headers=headers).json()
    commit = client.post(f"/api/imports/batches/{up['batch_id']}/commit",
                         json=opts, headers=headers)
    return preview, commit


def _codes(client, headers):
    return {p["code"] for p in client.get("/api/products", headers=headers).json()}


def test_import_refuses_to_nest_variants(client, auth_headers):
    """Caught by the preview, not on confirm: a file that reads "ok" applies."""
    run_import(client, auth_headers, "products", [
        ["Código", "Tipo de producto", "Producto base"],
        ["ARM-001", "Armazones", ""],
        ["ARM-001-NEG", "Armazones", "ARM-001"],
    ])
    preview, commit = _try_import(client, auth_headers, [
        ["Código", "Tipo de producto", "Producto base"],
        ["ARM-001-NEG-X", "Armazones", "ARM-001-NEG"],
    ])
    assert not preview["ok"]
    assert "no se anidan" in preview["errors"][0]["message"]
    assert commit.status_code == 400, commit.text
    # ...and the batch left nothing behind
    assert "ARM-001-NEG-X" not in _codes(client, auth_headers)


def test_import_refuses_to_nest_variants_within_one_file(client, auth_headers):
    preview, commit = _try_import(client, auth_headers, [
        ["Código", "Tipo de producto", "Producto base"],
        ["ARM-001", "Armazones", ""],
        ["ARM-001-NEG", "Armazones", "ARM-001"],
        ["ARM-001-NEG-X", "Armazones", "ARM-001-NEG"],
    ])
    assert [(e["row"], e["field"]) for e in preview["errors"]] == [(4, "parent")]
    assert "no se anidan" in preview["errors"][0]["message"]
    assert commit.status_code == 400, commit.text
    assert _codes(client, auth_headers) == set()


def test_import_refuses_to_make_a_style_a_variant(
    client, auth_headers, style, palette
):
    client.post(f"/api/products/{style['id']}/variants",
                json={"color_ids": [palette["Negro"]]}, headers=auth_headers)
    preview, commit = _try_import(client, auth_headers, [
        ["Código", "Tipo de producto", "Producto base"],
        ["ARM-002", "Armazones", ""],
        ["ARM-001", "Armazones", "ARM-002"],
    ])
    assert "ya tiene variantes propias" in preview["errors"][0]["message"]
    assert commit.status_code == 400, commit.text
    fetched = client.get(f"/api/products/{style['id']}", headers=auth_headers).json()
    assert fetched["parent_id"] is None and fetched["variant_count"] == 1


def test_import_refuses_a_style_that_holds_stock(
    client, auth_headers, product_type_id, branch_id
):
    """The API refuses this; a spreadsheet used to strand the stock instead."""
    plain = client.post(
        "/api/products",
        json={"code": "ARM-001", "product_type_id": product_type_id},
        headers=auth_headers,
    ).json()
    client.post("/api/stock/movements",
                json={"product_id": plain["id"], "branch_id": branch_id,
                      "movement_type": "inbound", "quantity": "5"},
                headers=auth_headers)
    preview, commit = _try_import(client, auth_headers, [
        ["Código", "Tipo de producto", "Producto base"],
        ["ARM-001-NEG", "Armazones", "ARM-001"],
    ])
    assert "de stock" in preview["errors"][0]["message"]
    assert commit.status_code == 400, commit.text
    assert _codes(client, auth_headers) == {"ARM-001"}


def test_import_refuses_a_product_as_its_own_style(client, auth_headers):
    preview, commit = _try_import(client, auth_headers, [
        ["Código", "Tipo de producto", "Producto base"],
        ["ARM-001", "Armazones", "ARM-001"],
    ])
    assert "su propio producto base" in preview["errors"][0]["message"]
    assert commit.status_code == 400, commit.text


def test_an_exported_family_reimports_cleanly(
    client, auth_headers, style, palette, branch_id
):
    """The family checks must not trip over a file we wrote ourselves."""
    variants = client.post(
        f"/api/products/{style['id']}/variants",
        json={"color_ids": [palette["Negro"], palette["Havana"]]},
        headers=auth_headers,
    ).json()
    client.post("/api/stock/movements",
                json={"product_id": variants[0]["id"], "branch_id": branch_id,
                      "movement_type": "inbound", "quantity": "3"},
                headers=auth_headers)
    exported = client.get("/api/imports/products/export?format=xlsx",
                          headers=auth_headers).content
    _, result = run_import(client, auth_headers, "products", None,
                           content=exported, filename="products.xlsx")
    assert result == {**result, "created": 0, "updated": 3}


def test_export_writes_the_style_so_the_file_round_trips(
    client, auth_headers, style, palette
):
    client.post(f"/api/products/{style['id']}/variants",
                json={"color_ids": [palette["Havana"]]}, headers=auth_headers)
    body = client.get("/api/imports/products/export?format=csv",
                      headers=auth_headers).content.decode("utf-8-sig")
    lines = body.splitlines()
    header = lines[0].split(";")
    rows = {l.split(";")[0]: l.split(";") for l in lines[1:]}
    assert rows["ARM-001-HAV"][header.index("Producto base")] == "ARM-001"
    assert rows["ARM-001"][header.index("Producto base")] == ""


# --- a hand-set parent is vetted the same way ------------------------------

def test_a_product_cannot_be_its_own_style(client, auth_headers, style):
    resp = client.put(f"/api/products/{style['id']}",
                      json={"parent_id": style["id"]}, headers=auth_headers)
    assert resp.status_code == 400
    assert "su propio producto base" in resp.json()["detail"]


def test_a_style_cannot_be_demoted_to_a_variant(
    client, auth_headers, style, palette, product_type_id
):
    """Families are two levels deep; this would make a third."""
    client.post(f"/api/products/{style['id']}/variants",
                json={"color_ids": [palette["Negro"]]}, headers=auth_headers)
    other = client.post("/api/products",
                        json={"code": "ARM-002", "product_type_id": product_type_id},
                        headers=auth_headers).json()
    resp = client.put(f"/api/products/{style['id']}",
                      json={"parent_id": other["id"]}, headers=auth_headers)
    assert resp.status_code == 400
    assert "ya tiene variantes propias" in resp.json()["detail"]


def test_a_variant_cannot_be_a_style_for_others(
    client, auth_headers, style, palette, product_type_id
):
    variant = client.post(
        f"/api/products/{style['id']}/variants",
        json={"color_ids": [palette["Negro"]]}, headers=auth_headers,
    ).json()[0]
    resp = client.post(
        "/api/products",
        json={"code": "X-1", "product_type_id": product_type_id,
              "parent_id": variant["id"]},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert "no se anidan" in resp.json()["detail"]


def test_existing_separate_products_can_be_linked_into_a_family(
    client, auth_headers, style, product_type_id
):
    """The path for a catalogue that already codes each colour separately."""
    loose = client.post(
        "/api/products",
        json={"code": "ARM-001-NEG", "product_type_id": product_type_id},
        headers=auth_headers,
    ).json()
    linked = client.put(f"/api/products/{loose['id']}",
                        json={"parent_id": style["id"]}, headers=auth_headers)
    assert linked.status_code == 200, linked.text
    assert linked.json()["parent_code"] == "ARM-001"
    assert client.get(f"/api/products/{style['id']}",
                      headers=auth_headers).json()["variant_count"] == 1


# --- the colours ticked on a product ARE its variants -----------------------

def test_creating_with_several_colors_creates_the_articles(
    client, auth_headers, product_type_id, palette
):
    """No second step: the colours are the declaration."""
    created = client.post(
        "/api/products",
        json={"code": "ARM-009", "product_type_id": product_type_id,
              "color_ids": [palette["Negro"], palette["Havana"]]},
        headers=auth_headers,
    ).json()
    assert created["variant_count"] == 2
    variants = client.get(f"/api/products/{created['id']}/variants",
                          headers=auth_headers).json()
    assert [v["code"] for v in variants] == ["ARM-009-HAV", "ARM-009-NEG"]


def test_one_colour_stays_a_plain_article(
    client, auth_headers, product_type_id, palette
):
    """Splitting a single-colour product into a family of one helps nobody."""
    created = client.post(
        "/api/products",
        json={"code": "LC-009", "product_type_id": product_type_id,
              "color_ids": [palette["Negro"]]},
        headers=auth_headers,
    ).json()
    assert created["variant_count"] == 0
    assert [c["name"] for c in created["colors"]] == ["Negro"]


def test_adding_a_colour_later_adds_the_article(
    client, auth_headers, style, palette
):
    updated = client.put(
        f"/api/products/{style['id']}",
        json={"color_ids": [palette["Negro"], palette["Havana"]]},
        headers=auth_headers,
    ).json()
    assert updated["variant_count"] == 2
    # ...and a third colour later only adds the one that is missing
    again = client.put(
        f"/api/products/{style['id']}",
        json={"color_ids": [palette["Negro"], palette["Havana"],
                            palette["Dorado"]]},
        headers=auth_headers,
    ).json()
    assert again["variant_count"] == 3
    codes = [v["code"] for v in client.get(
        f"/api/products/{style['id']}/variants", headers=auth_headers).json()]
    assert codes == ["ARM-001-DOR", "ARM-001-HAV", "ARM-001-NEG"]


def test_unticking_a_colour_leaves_its_article_alone(
    client, auth_headers, style, palette
):
    """It may hold stock or sit on last month's sales — retiring it is a
    decision, not a side effect of an edit."""
    client.put(f"/api/products/{style['id']}",
               json={"color_ids": [palette["Negro"], palette["Havana"]]},
               headers=auth_headers)
    client.put(f"/api/products/{style['id']}",
               json={"color_ids": [palette["Negro"]]}, headers=auth_headers)
    codes = [v["code"] for v in client.get(
        f"/api/products/{style['id']}/variants", headers=auth_headers).json()]
    assert codes == ["ARM-001-HAV", "ARM-001-NEG"]


def test_a_bicolour_variant_covers_both_its_colours(
    client, auth_headers, style, palette
):
    """"Covered", not "one per colour" — otherwise the sync would duplicate it."""
    client.post(
        f"/api/products/{style['id']}/variants",
        json={"variants": [{"color_ids": [palette["Negro"], palette["Dorado"]]}]},
        headers=auth_headers,
    )
    updated = client.put(
        f"/api/products/{style['id']}",
        json={"color_ids": [palette["Negro"], palette["Dorado"]]},
        headers=auth_headers,
    ).json()
    assert updated["variant_count"] == 1        # nothing new was needed


def test_stock_follows_the_colour_it_already_was(
    client, auth_headers, style, palette, branch_id
):
    """The everyday case: a stocked product gains a second colour."""
    client.put(f"/api/products/{style['id']}",
               json={"color_ids": [palette["Havana"]]}, headers=auth_headers)
    client.post("/api/stock/movements",
                json={"product_id": style["id"], "branch_id": branch_id,
                      "movement_type": "inbound", "quantity": "5"},
                headers=auth_headers)

    client.put(f"/api/products/{style['id']}",
               json={"color_ids": [palette["Havana"], palette["Negro"]]},
               headers=auth_headers)

    levels = {l["product_id"]: l["quantity"] for l in client.get(
        "/api/stock/levels", headers=auth_headers).json()}
    variants = {v["code"]: v for v in client.get(
        f"/api/products/{style['id']}/variants", headers=auth_headers).json()}
    # The five went to Havana — the colour they were — and the style holds none.
    assert levels.get(variants["ARM-001-HAV"]["id"]) == "5.00"
    assert levels.get(style["id"], "0") in ("0.00", "0")
    assert variants["ARM-001-NEG"]["id"] not in levels or \
        levels[variants["ARM-001-NEG"]["id"]] == "0.00"


def test_the_move_is_a_real_movement_not_a_silent_edit(
    client, auth_headers, style, palette, branch_id
):
    client.put(f"/api/products/{style['id']}",
               json={"color_ids": [palette["Havana"]]}, headers=auth_headers)
    client.post("/api/stock/movements",
                json={"product_id": style["id"], "branch_id": branch_id,
                      "movement_type": "inbound", "quantity": "5"},
                headers=auth_headers)
    client.put(f"/api/products/{style['id']}",
               json={"color_ids": [palette["Havana"], palette["Negro"]]},
               headers=auth_headers)

    moves = client.get("/api/stock/movements", headers=auth_headers).json()
    split = [m for m in moves if m["reference"] == "SPLIT"]
    assert len(split) == 2                      # off the style, onto the colour
    assert sorted(m["quantity"] for m in split) == ["-5.00", "5.00"]


def test_a_split_with_nowhere_to_put_the_stock_is_refused(
    client, auth_headers, style, palette, branch_id
):
    """No colour recorded, so nobody knows what those five things are."""
    client.post("/api/stock/movements",
                json={"product_id": style["id"], "branch_id": branch_id,
                      "movement_type": "inbound", "quantity": "5"},
                headers=auth_headers)
    resp = client.put(
        f"/api/products/{style['id']}",
        json={"color_ids": [palette["Havana"], palette["Negro"]]},
        headers=auth_headers,
    )
    assert resp.status_code == 400, resp.text
    assert "no se sabe de qué color es" in resp.json()["detail"]
    # ...and the refusal left the product exactly as it was
    after = client.get(f"/api/products/{style['id']}", headers=auth_headers).json()
    assert after["variant_count"] == 0 and after["color_ids"] == []


def test_import_splits_the_same_way_the_api_does(client, auth_headers):
    _, result = run_import(client, auth_headers, "products", [
        ["Código", "Tipo de producto", "Color"],
        ["ARM-100", "Armazones", "Negro, Havana"],
        ["LC-100", "Armazones", "Transparente"],
    ])
    assert result["created"] == 2
    by_code = {p["code"]: p
               for p in client.get("/api/products", headers=auth_headers).json()}
    assert by_code["ARM-100"]["variant_count"] == 2
    assert set(by_code) >= {"ARM-100-NEG", "ARM-100-HAV"}
    assert by_code["LC-100"]["variant_count"] == 0      # one colour, plain


# --- no colour is a real answer --------------------------------------------

def test_a_product_can_have_no_colour_at_all(
    client, auth_headers, product_type_id, branch_id
):
    """"Transparente" on a contact lens is not a colour, it is a description of
    what a contact lens is. Plenty of products simply have none."""
    created = client.post(
        "/api/products",
        json={"code": "LC-009", "product_type_id": product_type_id},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    product = created.json()
    assert product["colors"] == [] and product["color_ids"] == []
    assert product["variant_count"] == 0        # nothing to split

    # ...and it behaves like any other article
    assert client.post(
        "/api/stock/movements",
        json={"product_id": product["id"], "branch_id": branch_id,
              "movement_type": "inbound", "quantity": "4"},
        headers=auth_headers,
    ).status_code == 201
    assert [p["code"] for p in client.get(
        "/api/products?sellable_only=true", headers=auth_headers).json()] == ["LC-009"]


def test_colours_can_be_cleared_from_an_existing_product(
    client, auth_headers, product_type_id, palette
):
    pid = client.post(
        "/api/products",
        json={"code": "LC-009", "product_type_id": product_type_id,
              "color_ids": [palette["Negro"]]},
        headers=auth_headers,
    ).json()["id"]
    cleared = client.put(f"/api/products/{pid}", json={"color_ids": []},
                         headers=auth_headers)
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["color_ids"] == []


def test_import_leaves_the_colour_column_empty_alone(client, auth_headers):
    _, result = run_import(client, auth_headers, "products", [
        ["Código", "Tipo de producto", "Color"],
        ["LC-100", "Lentes de contacto", ""],
    ])
    assert result["created"] == 1
    product = client.get("/api/products", headers=auth_headers).json()[0]
    assert product["colors"] == [] and product["variant_count"] == 0


# --- one article in several colours ------------------------------------------

def _bicolour(client, headers, product_type_id, palette, **extra):
    resp = client.post(
        "/api/products",
        json={"code": "ARM-BI", "product_type_id": product_type_id,
              "color_ids": [palette["Negro"], palette["Dorado"]], "multicolor": True,
              **extra},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_a_multicolor_product_is_one_sellable_article(
    client, auth_headers, product_type_id, palette, branch_id
):
    bi = _bicolour(client, auth_headers, product_type_id, palette)
    assert bi["multicolor"] and bi["variant_count"] == 0 and len(bi["colors"]) == 2
    assert client.post(
        "/api/stock/movements",
        json={"product_id": bi["id"], "branch_id": branch_id,
              "movement_type": "inbound", "quantity": "2"},
        headers=auth_headers,
    ).status_code == 201


def test_unticking_multicolor_splits_like_a_colour_change(
    client, auth_headers, product_type_id, palette
):
    bi = _bicolour(client, auth_headers, product_type_id, palette)
    resp = client.put(f"/api/products/{bi['id']}", json={"multicolor": False},
                      headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["variant_count"] == 2


def test_a_style_cannot_be_marked_multicolor(client, auth_headers, style, palette):
    client.post(f"/api/products/{style['id']}/variants",
                json={"color_ids": [palette["Negro"], palette["Havana"]]},
                headers=auth_headers)
    resp = client.put(f"/api/products/{style['id']}", json={"multicolor": True},
                      headers=auth_headers)
    assert resp.status_code == 400
    assert "ya tiene variantes" in resp.json()["detail"]


def test_a_multicolor_article_cannot_be_a_base(
    client, auth_headers, product_type_id, palette
):
    bi = _bicolour(client, auth_headers, product_type_id, palette)
    resp = client.post("/api/products",
                       json={"code": "ARM-BI-X", "product_type_id": product_type_id,
                             "parent_id": bi["id"]},
                       headers=auth_headers)
    assert resp.status_code == 400
    assert "varios colores" in resp.json()["detail"]


def test_import_reads_the_multicolor_column(client, auth_headers):
    run_import(client, auth_headers, "products", [
        ["Código", "Tipo de producto", "Colores", "Multicolor"],
        ["ARM-BI", "Armazones", "Negro, Dorado", "Sí"],
        ["ARM-100", "Armazones", "Negro, Havana", ""],
    ])
    by_code = {p["code"]: p
               for p in client.get("/api/products", headers=auth_headers).json()}
    assert by_code["ARM-BI"]["multicolor"] and by_code["ARM-BI"]["variant_count"] == 0
    assert by_code["ARM-100"]["variant_count"] == 2      # unflagged: one per colour


def test_import_refuses_a_nonsense_multicolor_value(client, auth_headers):
    preview, _ = run_import(client, auth_headers, "products", [
        ["Código", "Tipo de producto", "Multicolor"],
        ["ARM-1", "Armazones", "tal vez"],
    ], expect_preview_ok=False)
    assert "sí o no" in preview["errors"][0]["message"]


def test_import_refuses_multicolor_on_a_style(client, auth_headers, style, palette):
    client.post(f"/api/products/{style['id']}/variants",
                json={"color_ids": [palette["Negro"]]}, headers=auth_headers)
    preview, commit = _try_import(client, auth_headers, [
        ["Código", "Tipo de producto", "Multicolor"],
        ["ARM-001", "Armazones", "sí"],
    ])
    assert "ya tiene variantes" in preview["errors"][0]["message"]
    assert commit.status_code == 400, commit.text
