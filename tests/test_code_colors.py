"""Colours read out of product codes during a products import.

Two halves: the reading itself (pure: a rule, a vocabulary, a code), and the
import that uses the shop's answers to build families through the ordinary
products path. The sample sheet is shaped like a real supplier export: model
numbers with the supplier's C-numbers, colour words in several languages, a
two-word colour and rows that carry no colour at all.
"""
from app.models.product import Color
from app.services.importer.code_colors import CodeRule, Vocabulary, split_code
from tests.test_imports import upload, xlsx

SHEET = [
    "01/1009 C1", "01/1009 C2", "01/306 C1", "01/088 C4",
    "03/INDAH BLACK", "03/INDAH MATTE BLACK", "03/ROATAN NERO",
    "PATILLAS COMUNES", "ROSCA",
]


# --- reading a code --------------------------------------------------------

def test_the_tail_keeps_two_word_colours_together():
    vocab, rule = Vocabulary([]), CodeRule(" ", 2)
    assert split_code("03/AGREV MATTE BLACK", rule, vocab) == ("03/AGREV", "MATTE BLACK")
    # ...but only colour words join it: the M stays with the model
    assert split_code("03/C09 M AZUL", rule, vocab) == ("03/C09 M", "AZUL")
    assert split_code("03/AGREV MATTE BLACK", CodeRule(" ", 1), vocab) \
        == ("03/AGREV MATTE", "BLACK")
    assert split_code("ARM-001-NEG", CodeRule("-"), vocab) == ("ARM-001", "NEG")
    assert split_code("ROSCA", rule, vocab) is None


def test_cut_off_words_are_read_unless_they_are_ambiguous():
    vocab = Vocabulary([])
    assert vocab.names_for(vocab.meaning("BLAC")) == ["Negro"]
    assert vocab.meaning("GRE") is None                 # grey or green: ask
    assert vocab.names_for(vocab.meaning("NERO MATE")) == ["Negro mate"]
    assert vocab.names_for(vocab.meaning("GRIS/ROJO")) == ["Gris", "Rojo"]


def test_glued_and_packed_spellings_are_read():
    vocab = Vocabulary([])
    assert vocab.names_for(vocab.meaning("NEROMATE")) == ["Negro mate"]
    assert vocab.names_for(vocab.meaning("GREYBLK")) == ["Gris", "Negro"]
    assert vocab.names_for(vocab.meaning("MBLK")) == ["Negro mate"]


def test_the_shops_own_colour_names_win():
    vocab = Vocabulary([Color(name="Black"), Color(name="Jade", code="JD")])
    assert vocab.names_for(vocab.meaning("NERO")) == ["Black"]   # not a new "Negro"
    assert vocab.names_for(vocab.meaning("JADE MATE")) == ["Jade mate"]
    assert vocab.catalog["JD"] == "Jade"


# --- helpers ---------------------------------------------------------------

def _stage(client, headers, codes, *, extra=None):
    header = ["Código", "Tipo de producto", *(extra or {}).keys()]
    rows = [[c, "Armazones", *[col.get(c, "") for col in (extra or {}).values()]]
            for c in codes]
    resp = upload(client, headers, "products", xlsx([header, *rows]))
    assert resp.status_code == 200, resp.text
    return resp.json()


def _analysis(client, headers, up, **rule):
    resp = client.post(f"/api/imports/batches/{up['batch_id']}/code-colors",
                       json={"mapping": up["suggested_mapping"], **rule},
                       headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _accept(analysis, **answers):
    """The step as a shop that takes every suggestion, plus ``answers``."""
    decisions = {t["phrase"]: {"kind": t["kind"], "colors": t["colors"]}
                 for t in analysis["tails"] if t["kind"]}
    decisions.update(answers)
    return {"separator": analysis["separator"], "max_words": analysis["max_words"],
            "decisions": decisions}


def _post(client, headers, up, step, code_colors):
    return client.post(
        f"/api/imports/batches/{up['batch_id']}/{step}",
        json={"mapping": up["suggested_mapping"], "decimal_format": "es",
              "create_missing": True, "code_colors": code_colors},
        headers=headers,
    )


def _import(client, headers, codes, **answers):
    up = _stage(client, headers, codes)
    cc = _accept(_analysis(client, headers, up), **answers)
    preview = _post(client, headers, up, "preview", cc).json()
    assert preview["ok"], preview["errors"]
    commit = _post(client, headers, up, "commit", cc)
    assert commit.status_code == 200, commit.text
    return preview, commit.json()


def _products(client, headers):
    return {p["code"]: p for p in client.get("/api/products", headers=headers).json()}


NOT_COLOUR = {"kind": "not_color", "colors": []}


# --- detection and suggestions ---------------------------------------------

def test_a_supplier_sheet_is_read_with_its_own_rule(client, auth_headers):
    got = _analysis(client, auth_headers, _stage(client, auth_headers, SHEET))
    assert got["separator"] == " " and got["likely"]
    assert got["rows_without_tail"] == 1                      # ROSCA
    tails = {t["phrase"]: t for t in got["tails"]}
    # C1 recurs under two models, so the C-numbering is the supplier's; C2 and
    # C4 are recognised as more of the same even on a single row
    assert {k: tails[k]["kind"] for k in ("C1", "C2", "C4")} == dict.fromkeys(
        ("C1", "C2", "C4"), "supplier_number")
    assert tails["BLACK"]["colors"] == ["Negro"]
    assert tails["NERO"]["colors"] == ["Negro"]
    assert tails["MATTE BLACK"]["colors"] == ["Negro mate"]
    assert tails["COMUNES"]["kind"] is None                   # nobody knows: ask


def test_a_numbering_is_one_series_even_against_the_colour_list(client, auth_headers):
    """A shop that once made a colour called "C1" still reads C1 like C3."""
    client.post("/api/colors", json={"name": "C1"}, headers=auth_headers)
    got = _analysis(client, auth_headers, _stage(client, auth_headers, SHEET))
    assert {t["phrase"]: t["kind"] for t in got["tails"]}["C1"] == "supplier_number"


def test_noise_after_a_colour_is_only_a_hint(client, auth_headers):
    """A lens code (G15) is not safe to drop silently, so the shop still picks."""
    up = _stage(client, auth_headers, ["03/ATAN BLACK G15", "03/ATAN GREY"])
    tail = {t["phrase"]: t for t in _analysis(client, auth_headers, up)["tails"]}["BLACK G15"]
    assert (tail["kind"], tail["colors"], tail["source"]) == (None, ["Negro"], "partial")


def test_model_numbers_are_not_mistaken_for_colours(client, auth_headers):
    codes = [f"ARM-00{i}" for i in range(1, 7)]
    got = _analysis(client, auth_headers, _stage(client, auth_headers, codes))
    assert not got["likely"]
    assert all(t["kind"] is None for t in got["tails"])


def test_rows_that_name_their_base_are_not_asked_about(client, auth_headers):
    """Our own export names every variant's base, so it never needs the step."""
    up = _stage(client, auth_headers, ["ARM-001", "ARM-001-NEG", "ARM-001-HAV"],
                extra={"Producto base": {"ARM-001-NEG": "ARM-001",
                                         "ARM-001-HAV": "ARM-001"}})
    got = _analysis(client, auth_headers, up)
    assert [t["phrase"] for t in got["tails"]] == ["001"]
    assert not got["likely"]


def test_the_shop_can_override_the_rule(client, auth_headers):
    up = _stage(client, auth_headers, SHEET)
    got = _analysis(client, auth_headers, up, separator="/", max_words=1)
    assert got["separator"] == "/" and got["max_words"] == 1
    assert not got["likely"]


# --- importing ---------------------------------------------------------------

def test_families_are_built_from_the_codes(client, auth_headers):
    preview, result = _import(client, auth_headers, SHEET, COMUNES=NOT_COLOUR)
    assert preview["family_count"] == 2
    assert result["created"] == len(SHEET) + 2                 # plus two bases

    by_code = _products(client, auth_headers)
    assert len(by_code) == len(SHEET) + 2       # nothing split behind our back
    assert by_code["01/1009"]["variant_count"] == 2
    assert by_code["01/1009 C1"]["parent_code"] == "01/1009"
    assert by_code["01/1009 C1"]["colors"] == []      # a supplier number, no guess
    assert by_code["03/INDAH"]["variant_count"] == 2
    assert [c["name"] for c in by_code["03/INDAH MATTE BLACK"]["colors"]] == ["Negro mate"]
    # one colour of a model stays a plain article, with its colour
    assert by_code["03/ROATAN NERO"]["parent_code"] is None
    assert [c["name"] for c in by_code["03/ROATAN NERO"]["colors"]] == ["Negro"]
    assert by_code["01/306 C1"]["parent_code"] is None
    assert by_code["PATILLAS COMUNES"]["colors"] == []


def test_an_unanswered_tail_blocks_the_batch(client, auth_headers):
    up = _stage(client, auth_headers, SHEET)
    cc = _accept(_analysis(client, auth_headers, up))          # COMUNES left open
    preview = _post(client, auth_headers, up, "preview", cc).json()
    assert not preview["ok"]
    assert any('"COMUNES"' in e["message"] for e in preview["errors"])
    assert _post(client, auth_headers, up, "commit", cc).status_code == 400
    assert _products(client, auth_headers) == {}


def test_answers_and_rule_are_remembered(client, auth_headers):
    _import(client, auth_headers, SHEET, COMUNES=NOT_COLOUR)
    up = _stage(client, auth_headers, ["01/1009 C3", "PATILLAS COMUNES", "03/INDAH NERO"])
    got = _analysis(client, auth_headers, up)
    assert got["remembered"] and got["separator"] == " "
    tails = {t["phrase"]: t for t in got["tails"]}
    assert (tails["COMUNES"]["kind"], tails["COMUNES"]["source"]) == ("not_color", "saved")
    assert (tails["NERO"]["colors"], tails["NERO"]["source"]) == (["Negro"], "saved")
    assert tails["C3"]["kind"] == "supplier_number"   # C was answered as numbering

    cc = _accept(got)
    assert _post(client, auth_headers, up, "preview", cc).json()["ok"]
    assert _post(client, auth_headers, up, "commit", cc).status_code == 200
    by_code = _products(client, auth_headers)
    assert by_code["01/1009 C3"]["parent_code"] == "01/1009"   # joins its family
    assert by_code["01/1009"]["variant_count"] == 3


def test_reimporting_the_same_sheet_changes_nothing(client, auth_headers):
    _import(client, auth_headers, SHEET, COMUNES=NOT_COLOUR)
    preview, result = _import(client, auth_headers, SHEET)
    assert preview["to_create"] == 0
    assert result["created"] == 0
    assert len(_products(client, auth_headers)) == len(SHEET) + 2


def test_a_second_colour_moves_the_first_under_a_new_base(
    client, auth_headers, branch_id
):
    """Option B: one colour stays plain until its sibling turns up."""
    _import(client, auth_headers, ["03/KIKIO BLACK"])
    first = _products(client, auth_headers)["03/KIKIO BLACK"]
    assert first["parent_code"] is None
    client.post("/api/stock/movements",
                json={"product_id": first["id"], "branch_id": branch_id,
                      "movement_type": "inbound", "quantity": "3"},
                headers=auth_headers)

    preview, _ = _import(client, auth_headers, ["03/KIKIO GREY"])
    [family] = preview["families"]
    assert family["base"] == "03/KIKIO" and family["new"]
    assert {v["code"]: v["status"] for v in family["variants"]} == {
        "03/KIKIO BLACK": "moved", "03/KIKIO GREY": "file"}

    by_code = _products(client, auth_headers)
    assert by_code["03/KIKIO BLACK"]["parent_code"] == "03/KIKIO"
    assert by_code["03/KIKIO"]["variant_count"] == 2
    # its stock stayed on the article, where it can still be sold
    sale = client.post("/api/stock/movements",
                       json={"product_id": first["id"], "branch_id": branch_id,
                             "movement_type": "outbound", "quantity": "1"},
                       headers=auth_headers)
    assert sale.status_code == 201, sale.text


def test_a_bicolour_article_stays_one_article(client, auth_headers):
    """Two colours in one tail describe the article: flagged, never split."""
    _import(client, auth_headers, ["03/CHICAMA BLACK BLUE"])
    by_code = _products(client, auth_headers)
    assert set(by_code) == {"03/CHICAMA BLACK BLUE"}
    article = by_code["03/CHICAMA BLACK BLUE"]
    assert article["multicolor"] and article["variant_count"] == 0
    assert article["parent_code"] is None
    assert [c["name"] for c in article["colors"]] == ["Azul", "Negro"]


def test_a_bicolour_colourway_joins_its_family(client, auth_headers):
    _import(client, auth_headers, ["03/CHICAMA BLACK BLUE", "03/CHICAMA GREY"])
    by_code = _products(client, auth_headers)
    assert by_code["03/CHICAMA"]["variant_count"] == 2
    assert by_code["03/CHICAMA BLACK BLUE"]["parent_code"] == "03/CHICAMA"
    assert len(by_code["03/CHICAMA BLACK BLUE"]["colors"]) == 2


def test_what_the_file_states_wins(client, auth_headers):
    codes = ["03/INDAH BLACK", "03/INDAH GREY"]
    up = _stage(client, auth_headers, codes,
                extra={"Colores": {"03/INDAH BLACK": "Rojo"}})
    cc = _accept(_analysis(client, auth_headers, up))
    assert _post(client, auth_headers, up, "commit", cc).status_code == 200
    by_code = _products(client, auth_headers)
    assert [c["name"] for c in by_code["03/INDAH BLACK"]["colors"]] == ["Rojo"]
    assert by_code["03/INDAH BLACK"]["parent_code"] == "03/INDAH"


def test_a_stocked_article_cannot_become_the_base(
    client, auth_headers, product_type_id, branch_id
):
    base = client.post("/api/products",
                       json={"code": "03/INDAH", "product_type_id": product_type_id},
                       headers=auth_headers).json()
    client.post("/api/stock/movements",
                json={"product_id": base["id"], "branch_id": branch_id,
                      "movement_type": "inbound", "quantity": "2"},
                headers=auth_headers)
    up = _stage(client, auth_headers, ["03/INDAH BLACK", "03/INDAH GREY"])
    cc = _accept(_analysis(client, auth_headers, up))
    preview = _post(client, auth_headers, up, "preview", cc).json()
    assert not preview["ok"]
    assert any("de stock" in e["message"] for e in preview["errors"])
