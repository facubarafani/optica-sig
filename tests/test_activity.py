"""Operation journal: catalogue, price and stock writes can be undone and redone.

Every test drives the API the way the console does: make a change, find it in
Actividad, undo it (or preview the undo), redo it. The import tests reuse the
supplier-sheet fixture from the colours-in-codes tests, because an import is
the change a shop most needs to take back.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import update

from app.models.journal import Operation
from app.services import journal
from tests.test_code_colors import NOT_COLOUR, SHEET, _import, _products


def _create(client, headers, product_type_id, code="ARM-UNDO", **extra):
    resp = client.post(
        "/api/products",
        json={"code": code, "product_type_id": product_type_id,
              "description": "Original", "min_stock": "1", **extra},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


def _ops(client, headers, **params):
    resp = client.get("/api/activity", params=params, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _revert(client, headers, op_id, *, action="undo", dry_run=False):
    return client.post(f"/api/activity/{op_id}/{action}",
                       json={"dry_run": dry_run}, headers=headers)


def _product(client, headers, pid):
    return client.get(f"/api/products/{pid}", headers=headers).json()


def _edit(client, headers, pid, **fields):
    resp = client.put(f"/api/products/{pid}", json=fields, headers=headers)
    assert resp.status_code == 200, resp.text


# --- journaling --------------------------------------------------------------

def test_an_edit_is_journaled_with_before_and_after(client, auth_headers, product_type_id):
    p = _create(client, auth_headers, product_type_id)
    _edit(client, auth_headers, p["id"], description="Nueva")
    latest = _ops(client, auth_headers)[0]
    assert latest["label"] == "Cambios en producto ARM-UNDO"
    assert latest["can_undo"] and not latest["undone"]
    detail = client.get(f"/api/activity/{latest['id']}", headers=auth_headers).json()
    [entity] = detail["entities"]
    assert {f["field"]: (f["before"], f["after"]) for f in entity["fields"]} \
        == {"description": ("Original", "Nueva")}


def test_reads_and_modules_outside_the_journal_leave_no_entry(client, auth_headers):
    client.get("/api/products", headers=auth_headers)
    client.post("/api/roles", json={"name": "Otro", "permission_ids": []},
                headers=auth_headers)
    assert _ops(client, auth_headers) == []
    # a sale must never be undoable from here: it is cancelled, not reverted
    assert "sales" not in journal.AREAS


# --- undo and redo -----------------------------------------------------------

def test_undo_and_redo_an_edit(client, auth_headers, product_type_id):
    p = _create(client, auth_headers, product_type_id)
    _edit(client, auth_headers, p["id"], description="Nueva", min_stock="5")
    op = _ops(client, auth_headers)[0]

    resp = _revert(client, auth_headers, op["id"])
    assert resp.status_code == 200, resp.text
    assert resp.json()["applied"] == 1 and resp.json()["skipped"] == []
    back = _product(client, auth_headers, p["id"])
    assert back["description"] == "Original" and Decimal(back["min_stock"]) == 1
    assert _ops(client, auth_headers)[0]["undone"]

    assert _revert(client, auth_headers, op["id"], action="redo").status_code == 200
    assert _product(client, auth_headers, p["id"])["description"] == "Nueva"
    assert not _ops(client, auth_headers)[0]["undone"]


def test_undoing_a_creation_deactivates_and_redo_restores(client, auth_headers, product_type_id):
    p = _create(client, auth_headers, product_type_id)
    op = _ops(client, auth_headers)[0]
    assert op["label"] == "Alta de producto ARM-UNDO"
    assert _revert(client, auth_headers, op["id"]).json()["applied"] == 1
    assert _product(client, auth_headers, p["id"])["is_active"] is False   # never deleted
    _revert(client, auth_headers, op["id"], action="redo")
    assert _product(client, auth_headers, p["id"])["is_active"] is True


def test_undoing_a_cost_change_keeps_the_cost_history(client, auth_headers, product_id):
    client.post(f"/api/products/{product_id}/cost", json={"new_cost": "150"},
                headers=auth_headers)
    _revert(client, auth_headers, _ops(client, auth_headers)[0]["id"])
    assert Decimal(_product(client, auth_headers, product_id)["current_cost"]) == 100
    history = client.get(f"/api/products/{product_id}/cost-history",
                         headers=auth_headers).json()
    assert sorted(Decimal(h["new_cost"]) for h in history) == [100, 150]


def test_undoing_a_stock_movement_compensates_it(client, auth_headers, product_id, branch_id):
    client.post("/api/stock/movements",
                json={"product_id": product_id, "branch_id": branch_id,
                      "movement_type": "inbound", "quantity": "5"},
                headers=auth_headers)
    op = _ops(client, auth_headers)[0]
    assert op["label"] == "Movimiento de stock de P-1"
    assert _revert(client, auth_headers, op["id"]).status_code == 200
    [level] = client.get(f"/api/stock/levels?product_id={product_id}",
                         headers=auth_headers).json()
    assert Decimal(level["quantity"]) == 0
    # the ledger explains it: nothing was rewritten, a movement was added
    moves = client.get("/api/stock/movements", headers=auth_headers).json()
    assert sorted(Decimal(m["quantity"]) for m in moves) == [-5, 5]


def test_a_row_that_changed_since_is_skipped(client, auth_headers, product_type_id):
    p = _create(client, auth_headers, product_type_id)
    _edit(client, auth_headers, p["id"], description="Primera")
    first = _ops(client, auth_headers)[0]
    _edit(client, auth_headers, p["id"], description="Segunda")

    preview = _revert(client, auth_headers, first["id"], dry_run=True).json()
    assert preview["applied"] == 0
    [skip] = preview["skipped"]
    assert skip["entity"] == "producto ARM-UNDO"
    assert "cambió después" in skip["reason"]
    assert _product(client, auth_headers, p["id"])["description"] == "Segunda"


def test_a_preview_writes_nothing(client, auth_headers, product_type_id):
    p = _create(client, auth_headers, product_type_id)
    _edit(client, auth_headers, p["id"], description="Nueva")
    op = _ops(client, auth_headers)[0]
    preview = _revert(client, auth_headers, op["id"], dry_run=True).json()
    assert preview["dry_run"] and preview["applied"] == 1
    assert preview["operation_id"] is None
    assert _product(client, auth_headers, p["id"])["description"] == "Nueva"
    assert not _ops(client, auth_headers)[0]["undone"]


def test_an_undo_is_not_undone_directly(client, auth_headers, product_type_id):
    _create(client, auth_headers, product_type_id)
    op = _ops(client, auth_headers)[0]
    undo_id = _revert(client, auth_headers, op["id"]).json()["operation_id"]
    assert _revert(client, auth_headers, undo_id).status_code == 400


def test_latest_follows_the_undo_stack(client, auth_headers, product_type_id):
    p = _create(client, auth_headers, product_type_id)
    _edit(client, auth_headers, p["id"], description="Uno")
    _edit(client, auth_headers, p["id"], description="Dos")

    def latest(action):
        return client.get("/api/activity/latest", params={"action": action},
                          headers=auth_headers)

    newest = latest("undo").json()
    _revert(client, auth_headers, newest["id"])
    assert latest("redo").json()["id"] == newest["id"]
    second = latest("undo").json()
    assert second["id"] != newest["id"]
    _revert(client, auth_headers, second["id"])
    assert _product(client, auth_headers, p["id"])["description"] == "Original"

    assert latest("redo").json()["id"] == second["id"]
    _revert(client, auth_headers, second["id"], action="redo")
    assert latest("redo").json()["id"] == newest["id"]
    _revert(client, auth_headers, newest["id"], action="redo")
    assert latest("redo").json() is None                  # nothing left to redo
    assert _product(client, auth_headers, p["id"])["description"] == "Dos"


# --- imports -----------------------------------------------------------------

def test_an_import_can_be_undone_and_redone(client, auth_headers):
    _import(client, auth_headers, SHEET, COMUNES=NOT_COLOUR)
    op = _ops(client, auth_headers)[0]
    assert op["label"].startswith("Importación de datos.xlsx")

    result = _revert(client, auth_headers, op["id"]).json()
    assert result["skipped"] == [], result["skipped"]
    assert _products(client, auth_headers) == {}
    assert client.get("/api/colors", headers=auth_headers).json() == []

    assert _revert(client, auth_headers, op["id"], action="redo").status_code == 200
    by_code = _products(client, auth_headers)
    assert len(by_code) == len(SHEET) + 2
    assert by_code["01/1009"]["variant_count"] == 2


def test_undoing_an_import_leaves_what_has_moved_on(client, auth_headers, branch_id):
    _import(client, auth_headers, SHEET, COMUNES=NOT_COLOUR)
    op = _ops(client, auth_headers)[0]
    roatan = _products(client, auth_headers)["03/ROATAN NERO"]
    client.post("/api/stock/movements",
                json={"product_id": roatan["id"], "branch_id": branch_id,
                      "movement_type": "inbound", "quantity": "2"},
                headers=auth_headers)

    preview = _revert(client, auth_headers, op["id"], dry_run=True).json()
    reasons = {s["entity"]: s["reason"] for s in preview["skipped"]}
    assert reasons["producto 03/ROATAN NERO"] == "tiene 2 de stock"
    assert "lo usan" in reasons["color Negro"]
    assert preview["applied"] > 0

    _revert(client, auth_headers, op["id"])
    assert set(_products(client, auth_headers)) == {"03/ROATAN NERO"}


# --- who and how long --------------------------------------------------------

def _staff(client, auth_headers):
    """A shop user who may edit products but manages nobody."""
    perms = {p["code"]: p["id"] for p in
             client.get("/api/permissions", headers=auth_headers).json()}
    role = client.post(
        "/api/roles",
        json={"name": "Catálogo", "permission_ids": [perms["products:read"],
                                                     perms["products:write"]]},
        headers=auth_headers,
    ).json()
    resp = client.post(
        "/api/users",
        json={"email": "catalogo@test.com", "full_name": "Catálogo",
              "password": "catalogo1234", "role_ids": [role["id"]]},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    token = client.post("/api/auth/login", json={
        "email": "catalogo@test.com", "password": "catalogo1234"}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_only_the_author_or_an_admin_can_undo(client, auth_headers, product_type_id):
    staff = _staff(client, auth_headers)
    p = _create(client, auth_headers, product_type_id)
    admin_op = _ops(client, auth_headers)[0]
    # not theirs and not an admin: they cannot even see it
    assert _revert(client, staff, admin_op["id"]).status_code == 404
    assert _ops(client, staff) == []

    _edit(client, staff, p["id"], description="Del vendedor")
    [staff_op] = _ops(client, staff)
    assert staff_op["can_undo"]
    # an admin sees everybody's changes and may undo them
    assert _revert(client, auth_headers, staff_op["id"]).status_code == 200
    assert _product(client, auth_headers, p["id"])["description"] == "Original"


def test_after_90_days_it_can_no_longer_be_undone(client, auth_headers, product_type_id, db):
    p = _create(client, auth_headers, product_type_id)
    _edit(client, auth_headers, p["id"], description="Nueva")
    op = _ops(client, auth_headers)[0]
    db.execute(update(Operation).where(Operation.id == op["id"]).values(
        created_at=datetime.now(timezone.utc) - timedelta(days=91)))
    db.commit()

    resp = _revert(client, auth_headers, op["id"])
    assert resp.status_code == 403
    assert "90 días" in resp.json()["detail"]
    # and the next look at Actividad forgets it
    assert all(o["id"] != op["id"] for o in _ops(client, auth_headers))
