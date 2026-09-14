"""Bulk deactivation from a spreadsheet: the products file's "Activo" column.

Nothing is deleted (CLAUDE.md rule 3): "no" switches a product off, "sí"
brings it back. It needs its own permission, refuses a base whose variants stay
active, reports stock instead of refusing it, round-trips through the export
and can be undone like any import.
"""
from tests.test_activity import _ops, _revert, _staff
from tests.test_imports import run_import
from tests.test_variants import _try_import

HEADER = ["Código", "Tipo de producto", "Activo"]


def _seed(client, headers, *codes):
    run_import(client, headers, "products",
               [["Código", "Tipo de producto"], *[[c, "Armazones"] for c in codes]])


def _family(client, headers):
    run_import(client, headers, "products", [
        ["Código", "Tipo de producto", "Producto base"],
        ["ARM-001", "Armazones", ""],
        ["ARM-001-NEG", "Armazones", "ARM-001"],
        ["ARM-001-HAV", "Armazones", "ARM-001"],
    ])


def _active(client, headers):
    return {p["code"] for p in client.get("/api/products", headers=headers).json()}


def _login(client, email, password):
    token = client.post("/api/auth/login",
                        json={"email": email, "password": password}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_no_deactivates_and_si_brings_it_back(client, auth_headers):
    _seed(client, auth_headers, "ARM-1", "ARM-2")
    preview, commit = _try_import(client, auth_headers, [HEADER, ["ARM-1", "Armazones", "no"]])
    assert preview["ok"], preview["errors"]
    assert (preview["to_deactivate"], preview["deactivate_sample"]) == (1, ["ARM-1"])
    assert commit.status_code == 200, commit.text
    assert _active(client, auth_headers) == {"ARM-2"}

    preview, commit = _try_import(client, auth_headers, [HEADER, ["ARM-1", "Armazones", "sí"]])
    assert (preview["to_reactivate"], preview["to_deactivate"]) == (1, 0)
    assert commit.status_code == 200, commit.text
    assert _active(client, auth_headers) == {"ARM-1", "ARM-2"}


def test_deactivating_in_bulk_needs_its_own_permission(client, auth_headers):
    _seed(client, auth_headers, "ARM-1")
    staff = _staff(client, auth_headers)        # products:read and :write only
    preview, commit = _try_import(client, staff, [HEADER, ["ARM-1", "Armazones", "no"]])
    assert not preview["ok"]
    assert "Eliminar productos en masa" in preview["errors"][0]["message"]
    assert commit.status_code == 400
    assert _active(client, auth_headers) == {"ARM-1"}


def test_the_permission_can_be_granted(client, auth_headers):
    _seed(client, auth_headers, "ARM-1")
    perms = {p["code"]: p["id"] for p in
             client.get("/api/permissions", headers=auth_headers).json()}
    role = client.post("/api/roles", json={
        "name": "Depósito",
        "permission_ids": [perms["products:read"], perms["products:write"],
                           perms["products:bulk_delete"]],
    }, headers=auth_headers).json()
    client.post("/api/users", json={
        "email": "deposito@test.com", "full_name": "Depósito",
        "password": "deposito1234", "role_ids": [role["id"]],
    }, headers=auth_headers)
    keeper = _login(client, "deposito@test.com", "deposito1234")
    preview, commit = _try_import(client, keeper, [HEADER, ["ARM-1", "Armazones", "no"]])
    assert preview["ok"] and commit.status_code == 200, (preview["errors"], commit.text)
    assert _active(client, auth_headers) == set()


def test_bringing_products_back_needs_no_special_permission(client, auth_headers):
    _seed(client, auth_headers, "ARM-1")
    _try_import(client, auth_headers, [HEADER, ["ARM-1", "Armazones", "no"]])
    staff = _staff(client, auth_headers)
    preview, commit = _try_import(client, staff, [HEADER, ["ARM-1", "Armazones", "sí"]])
    assert preview["ok"] and commit.status_code == 200, (preview["errors"], commit.text)
    assert _active(client, auth_headers) == {"ARM-1"}


def test_a_base_goes_only_with_its_variants(client, auth_headers):
    _family(client, auth_headers)
    preview, commit = _try_import(client, auth_headers, [HEADER, ["ARM-001", "Armazones", "no"]])
    assert "2 variante(s) activa(s)" in preview["errors"][0]["message"]
    assert commit.status_code == 400

    preview, commit = _try_import(client, auth_headers, [
        HEADER, ["ARM-001", "Armazones", "no"],
        ["ARM-001-NEG", "Armazones", "no"], ["ARM-001-HAV", "Armazones", "no"],
    ])
    assert preview["ok"] and preview["to_deactivate"] == 3, preview["errors"]
    assert commit.status_code == 200
    assert _active(client, auth_headers) == set()


def test_a_code_that_does_not_exist_cannot_be_deactivated(client, auth_headers):
    preview, _ = _try_import(client, auth_headers, [HEADER, ["NO-EXISTE", "Armazones", "no"]])
    assert "no existe" in preview["errors"][0]["message"]


def test_stock_is_reported_not_refused(client, auth_headers, branch_id):
    _seed(client, auth_headers, "ARM-1")
    [product] = client.get("/api/products", headers=auth_headers).json()
    client.post("/api/stock/movements", json={
        "product_id": product["id"], "branch_id": branch_id,
        "movement_type": "inbound", "quantity": "3"}, headers=auth_headers)
    preview, commit = _try_import(client, auth_headers, [HEADER, ["ARM-1", "Armazones", "no"]])
    assert preview["ok"] and preview["deactivate_with_stock"] == 1
    assert commit.status_code == 200


def test_the_single_delete_refuses_a_base_with_active_variants(client, auth_headers):
    _family(client, auth_headers)
    base = next(p for p in client.get("/api/products", headers=auth_headers).json()
                if p["code"] == "ARM-001")
    resp = client.delete(f"/api/products/{base['id']}", headers=auth_headers)
    assert resp.status_code == 400
    assert "variante(s) activa(s)" in resp.json()["detail"]


def test_the_export_carries_activo_so_the_file_round_trips(client, auth_headers):
    _seed(client, auth_headers, "ARM-1", "ARM-2")
    _try_import(client, auth_headers, [HEADER, ["ARM-1", "Armazones", "no"]])
    body = client.get("/api/imports/products/export?format=csv&include_inactive=true",
                      headers=auth_headers).content.decode("utf-8-sig")
    header, *lines = body.splitlines()
    col = header.split(";").index("Activo")
    rows = {line.split(";")[0]: line.split(";") for line in lines}
    assert (rows["ARM-1"][col], rows["ARM-2"][col]) == ("no", "sí")


def test_a_bulk_deactivation_can_be_undone(client, auth_headers):
    _seed(client, auth_headers, "ARM-1", "ARM-2")
    _try_import(client, auth_headers, [HEADER, ["ARM-1", "Armazones", "no"],
                                       ["ARM-2", "Armazones", "no"]])
    op = _ops(client, auth_headers)[0]
    assert _revert(client, auth_headers, op["id"]).status_code == 200
    assert _active(client, auth_headers) == {"ARM-1", "ARM-2"}
