"""Provider console: onboarding tenants, supporting them, and staying out.

The isolation tests at the bottom are the ones that matter most: the whole
argument for a shared database instead of one deployment per shop rests on
company scoping actually holding.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.auth import User
from app.models.company import Company, CompanySettings
from app.models.enums import PlatformAction
from app.models.platform import PlatformAuditLog


TENANT = {
    "name": "Óptica San Martín",
    "legal_name": "San Martín SRL",
    "tax_id": "30-99887766-5",
    "admin_email": "dueno@sanmartin.com",
    "admin_full_name": "Dueño",
    "admin_password": "sanmartin1234",
}


def _create_tenant(client, platform_headers, **overrides):
    resp = client.post(
        "/api/admin/tenants", json={**TENANT, **overrides}, headers=platform_headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- identity separation --------------------------------------------------
def test_tenant_token_is_rejected_by_the_admin_api(client, auth_headers):
    """A shop's superuser token must not open the provider console.

    This is the structural guarantee behind putting platform users in their own
    table: even a company superuser, whose permission set is "*", gets 401.
    """
    resp = client.get("/api/admin/tenants", headers=auth_headers)
    assert resp.status_code == 401


def test_platform_token_is_rejected_by_tenant_api(client, platform_headers):
    """And the reverse: a provider token cannot read a shop's data directly."""
    for path in ("/api/auth/me", "/api/products", "/api/sales", "/api/company"):
        resp = client.get(path, headers=platform_headers)
        assert resp.status_code == 401, f"{path} accepted a platform token"


def test_platform_login_rejects_a_tenant_users_credentials(client):
    resp = client.post(
        "/api/admin/login", json={"email": "admin@test.com", "password": "admin1234"}
    )
    assert resp.status_code == 401


def test_tenant_login_rejects_a_platform_users_credentials(client):
    resp = client.post(
        "/api/auth/login", json={"email": "owner@test.com", "password": "owner1234"}
    )
    assert resp.status_code == 401


# --- provisioning ---------------------------------------------------------
def test_create_tenant_provisions_a_working_shop(client, platform_headers, db):
    created = _create_tenant(client, platform_headers)
    company_id = created["company"]["id"]
    assert company_id != settings.default_company_id

    # The password is echoed once so it can be read out, and never again.
    assert created["admin_password"] == TENANT["admin_password"]

    # Everything a shop needs before its first sale.
    settings_row = db.execute(
        select(CompanySettings).where(CompanySettings.company_id == company_id)
    ).scalar_one()
    assert settings_row.default_branch_id is not None
    assert settings_row.default_price_list_id is not None

    admin = db.execute(
        select(User).where(User.company_id == company_id)
    ).scalar_one()
    assert admin.is_superuser
    assert admin.email == TENANT["admin_email"]
    assert {r.name for r in admin.roles} == {"Administrator"}
    # The Administrator role carries the whole catalogue, not a subset.
    assert "sales:write" in admin.permission_codes or "*" in admin.permission_codes


def test_the_new_admin_can_log_in_and_work(client, platform_headers):
    _create_tenant(client, platform_headers)
    resp = client.post(
        "/api/auth/login",
        json={"email": TENANT["admin_email"], "password": TENANT["admin_password"]},
    )
    assert resp.status_code == 200, resp.text
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    # Their session is scoped to their own company, not the seeded one.
    me = client.get("/api/auth/me", headers=headers).json()
    assert me["email"] == TENANT["admin_email"]

    # And provisioning left them able to actually sell: a branch, a price list
    # and the counters are all there.
    branches = client.get("/api/branches", headers=headers).json()
    assert [b["code"] for b in branches] == ["MAIN"]
    assert client.get("/api/price-lists", headers=headers).json()


def test_a_new_tenant_can_create_its_first_product(client, platform_headers):
    """The regression this exists for: provisioning used to skip product types.

    ``products.product_type_id`` is NOT NULL and the console's field is
    required, so a shop with an empty type list could not create a single
    product — and the seed only ever built types for the demo company, so
    every shop onboarded through /admin was born unable to sell anything.
    """
    _create_tenant(client, platform_headers)
    resp = client.post(
        "/api/auth/login",
        json={"email": TENANT["admin_email"], "password": TENANT["admin_password"]},
    )
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}

    types = client.get("/api/product-types", headers=headers).json()
    assert [t["name"] for t in types] == [
        "Armazones", "Lentes de sol", "Lentes de contacto",
    ]

    created = client.post(
        "/api/products",
        json={"code": "ARM-100", "product_type_id": types[0]["id"],
              "current_cost": "1000"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["product_type_id"] == types[0]["id"]


def test_create_tenant_is_all_or_nothing(client, platform_headers, db):
    """A rejected tenant must leave no half-built company behind."""
    before = db.execute(select(Company)).scalars().all()
    resp = client.post(
        "/api/admin/tenants",
        json={**TENANT, "name": ""},
        headers=platform_headers,
    )
    assert resp.status_code == 422  # schema catches the empty name
    db.expire_all()
    assert len(db.execute(select(Company)).scalars().all()) == len(before)


# --- suspension -----------------------------------------------------------
def test_suspension_blocks_login_and_live_sessions(client, platform_headers):
    created = _create_tenant(client, platform_headers)
    company_id = created["company"]["id"]

    login = client.post(
        "/api/auth/login",
        json={"email": TENANT["admin_email"], "password": TENANT["admin_password"]},
    )
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    assert client.get("/api/auth/me", headers=headers).status_code == 200

    client.post(f"/api/admin/tenants/{company_id}/suspend", headers=platform_headers)

    # The token they already hold stops working — not just the next login.
    assert client.get("/api/auth/me", headers=headers).status_code == 403
    again = client.post(
        "/api/auth/login",
        json={"email": TENANT["admin_email"], "password": TENANT["admin_password"]},
    )
    assert again.status_code == 403
    assert "suspended" in again.json()["detail"].lower()

    client.post(f"/api/admin/tenants/{company_id}/reactivate", headers=platform_headers)
    assert client.get("/api/auth/me", headers=headers).status_code == 200


def test_suspending_does_not_touch_the_other_tenants(client, platform_headers, auth_headers):
    created = _create_tenant(client, platform_headers)
    client.post(
        f"/api/admin/tenants/{created['company']['id']}/suspend", headers=platform_headers
    )
    assert client.get("/api/auth/me", headers=auth_headers).status_code == 200


# --- the login chooser ----------------------------------------------------
def test_one_email_at_two_shops_returns_a_chooser(client, platform_headers):
    shared = "contadora@estudio.com"
    password = "contadora1234"
    a = _create_tenant(
        client, platform_headers,
        name="Óptica A", admin_email=shared, admin_password=password,
    )
    b = _create_tenant(
        client, platform_headers,
        name="Óptica B", admin_email=shared, admin_password=password,
    )

    resp = client.post("/api/auth/login", json={"email": shared, "password": password})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["access_token"] is None
    assert {c["id"] for c in data["companies"]} == {
        a["company"]["id"], b["company"]["id"]
    }

    # Posting again with the choice hands over a token for that company only.
    chosen = client.post(
        "/api/auth/login",
        json={"email": shared, "password": password, "company_id": b["company"]["id"]},
    )
    token = chosen.json()["access_token"]
    assert token
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200

    # A suspended shop drops out of the chooser rather than being offered.
    client.post(
        f"/api/admin/tenants/{a['company']['id']}/suspend", headers=platform_headers
    )
    resp = client.post("/api/auth/login", json={"email": shared, "password": password})
    assert resp.json()["access_token"], "one active match should log straight in"


def test_wrong_password_is_still_a_401(client):
    resp = client.post(
        "/api/auth/login", json={"email": "admin@test.com", "password": "nope"}
    )
    assert resp.status_code == 401


# --- support access -------------------------------------------------------
def test_impersonation_mints_a_scoped_token_and_is_audited(
    client, platform_headers, db
):
    created = _create_tenant(client, platform_headers)
    company_id = created["company"]["id"]

    resp = client.post(
        f"/api/admin/tenants/{company_id}/impersonate",
        json={"reason": "stock que no cierra"},
        headers=platform_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["user_email"] == TENANT["admin_email"]
    assert body["expires_in_minutes"] == 30

    # The token works against the tenant API, and only for that company.
    headers = {"Authorization": f"Bearer {body['access_token']}"}
    me = client.get("/api/auth/me", headers=headers).json()
    assert me["email"] == TENANT["admin_email"]
    # It is a tenant token, so it cannot climb back into the admin API.
    assert client.get("/api/admin/tenants", headers=headers).status_code == 401

    entry = db.execute(
        select(PlatformAuditLog)
        .where(PlatformAuditLog.action == PlatformAction.TENANT_IMPERSONATE.value)
    ).scalar_one()
    assert entry.company_id == company_id
    assert "stock que no cierra" in entry.detail


def test_impersonating_a_suspended_shop_is_refused(client, platform_headers):
    created = _create_tenant(client, platform_headers)
    company_id = created["company"]["id"]
    client.post(f"/api/admin/tenants/{company_id}/suspend", headers=platform_headers)
    resp = client.post(
        f"/api/admin/tenants/{company_id}/impersonate", json={}, headers=platform_headers
    )
    assert resp.status_code == 400


def test_every_provider_action_lands_in_the_audit_log(client, platform_headers, db):
    created = _create_tenant(client, platform_headers)
    cid = created["company"]["id"]
    client.put(f"/api/admin/tenants/{cid}", json={"phone": "11-5555"}, headers=platform_headers)
    client.post(f"/api/admin/tenants/{cid}/suspend", headers=platform_headers)
    client.post(f"/api/admin/tenants/{cid}/reactivate", headers=platform_headers)
    client.post(
        f"/api/admin/tenants/{cid}/users",
        json={"email": "socio@sanmartin.com", "full_name": "Socio", "password": "socio12345"},
        headers=platform_headers,
    )

    actions = {
        row.action for row in
        db.execute(select(PlatformAuditLog).where(PlatformAuditLog.company_id == cid)).scalars()
    }
    assert actions == {
        PlatformAction.TENANT_CREATE.value,
        PlatformAction.TENANT_UPDATE.value,
        PlatformAction.TENANT_SUSPEND.value,
        PlatformAction.TENANT_REACTIVATE.value,
        PlatformAction.TENANT_USER_CREATE.value,
    }


def test_added_admin_can_log_in(client, platform_headers):
    created = _create_tenant(client, platform_headers)
    cid = created["company"]["id"]
    resp = client.post(
        f"/api/admin/tenants/{cid}/users",
        json={"email": "socio@sanmartin.com", "full_name": "Socio", "password": "socio12345"},
        headers=platform_headers,
    )
    assert resp.status_code == 201, resp.text
    login = client.post(
        "/api/auth/login",
        json={"email": "socio@sanmartin.com", "password": "socio12345"},
    )
    assert login.status_code == 200
    assert login.json()["access_token"]


def test_password_reset_replaces_the_old_one(client, platform_headers):
    created = _create_tenant(client, platform_headers)
    cid = created["company"]["id"]
    users = client.get(f"/api/admin/tenants/{cid}/users", headers=platform_headers).json()
    uid = users[0]["id"]

    resp = client.post(
        f"/api/admin/tenants/{cid}/users/{uid}/password",
        json={"new_password": "otracosa123"},
        headers=platform_headers,
    )
    assert resp.status_code == 200, resp.text
    assert client.post(
        "/api/auth/login",
        json={"email": TENANT["admin_email"], "password": TENANT["admin_password"]},
    ).status_code == 401
    assert client.post(
        "/api/auth/login",
        json={"email": TENANT["admin_email"], "password": "otracosa123"},
    ).status_code == 200


# --- tenant isolation -----------------------------------------------------
# The shared-database model is only safe if company scoping actually holds.
# These walk a real second tenant through the endpoints a shop uses daily.
@pytest.fixture
def other_tenant(client, platform_headers):
    created = _create_tenant(client, platform_headers)
    login = client.post(
        "/api/auth/login",
        json={"email": TENANT["admin_email"], "password": TENANT["admin_password"]},
    )
    return {
        "company_id": created["company"]["id"],
        "headers": {"Authorization": f"Bearer {login.json()['access_token']}"},
    }


LIST_ENDPOINTS = [
    "/api/products", "/api/customers", "/api/suppliers", "/api/branches",
    "/api/brands", "/api/product-types", "/api/colors", "/api/price-lists",
    "/api/sales", "/api/users", "/api/roles",
]


def test_a_new_tenant_sees_none_of_the_other_shops_rows(
    client, auth_headers, other_tenant, product_id, supplier_id, brand_id
):
    """Seeded company 1 has products/suppliers/brands; the new shop must not
    see any of them through any list endpoint."""
    client.post(
        "/api/customers",
        json={"first_name": "Juan", "last_name": "Pérez"},
        headers=auth_headers,
    )
    for path in LIST_ENDPOINTS:
        mine = client.get(path, headers=auth_headers)
        theirs = client.get(path, headers=other_tenant["headers"])
        assert mine.status_code == 200 and theirs.status_code == 200, path
        mine_ids = {r["id"] for r in mine.json()}
        their_ids = {r["id"] for r in theirs.json()}
        assert not (mine_ids & their_ids), f"{path} leaked rows across companies"


def test_fetching_another_companys_row_by_id_is_a_404(
    client, other_tenant, product_id, supplier_id
):
    """Guessing an id must not work — scoping is on the query, not the listing."""
    for path in (f"/api/products/{product_id}", f"/api/suppliers/{supplier_id}"):
        resp = client.get(path, headers=other_tenant["headers"])
        assert resp.status_code == 404, f"{path} was readable across companies"


def test_writing_to_another_companys_row_is_a_404(client, other_tenant, product_id):
    resp = client.put(
        f"/api/products/{product_id}",
        json={"description": "hijacked"},
        headers=other_tenant["headers"],
    )
    assert resp.status_code == 404


# --- provider accounts (CLI-managed) --------------------------------------
def test_password_policy_rejects_demo_and_short_passwords(db):
    """A provider password is the highest-value credential in the system.

    The demo default is checked before the length rule on purpose: every known
    default is also too short, so the other order would make that branch
    unreachable and report the wrong reason for the mistake people actually
    make — pasting the repo's demo password into a real deployment.
    """
    from app.services import platform as svc

    with pytest.raises(svc.PlatformError, match="demo"):
        svc.validate_password("owner1234")
    with pytest.raises(svc.PlatformError, match="12 caracteres"):
        svc.validate_password("corta")
    svc.validate_password("una-clave-suficientemente-larga")


def test_platform_account_lifecycle(db):
    from app.services import platform as svc

    user = svc.create_platform_user(
        db, email="Nuevo@SGI.com", full_name="Nuevo", password="clave-larga-99"
    )
    assert user.email == "nuevo@sgi.com", "emails are normalised"

    with pytest.raises(svc.PlatformError, match="Ya existe"):
        svc.create_platform_user(
            db, email="nuevo@sgi.com", full_name="Dup", password="otra-clave-larga"
        )

    svc.set_platform_password(db, user, "otra-clave-bien-larga")
    assert svc.authenticate(db, "nuevo@sgi.com", "otra-clave-bien-larga") is not None
    assert svc.authenticate(db, "nuevo@sgi.com", "clave-larga-99") is None

    svc.set_platform_active(db, user, False)
    assert svc.authenticate(db, "nuevo@sgi.com", "otra-clave-bien-larga") is None


def test_a_disabled_provider_token_stops_working(client, platform_headers, db):
    """Disabling an account must cut the session it already holds."""
    from app.services import platform as svc

    assert client.get("/api/admin/tenants", headers=platform_headers).status_code == 200
    svc.set_platform_active(db, svc.get_platform_user(db, "owner@test.com"), False)
    assert client.get("/api/admin/tenants", headers=platform_headers).status_code == 401


# --- front doors -----------------------------------------------------------
def test_the_bare_domain_opens_the_console_that_matches_the_host(client):
    """admin.<domain> is the provider's front door; anything else is a shop's.

    Without this the provider subdomain would redirect to /app and land the
    provider on a shop's console. Both pages stay reachable on both hosts on
    purpose: impersonation hands the tenant token over through same-origin
    localStorage, so splitting them across origins would break that.
    """
    for host, expected in [
        ("admin.miopticadigital.com.ar", "/admin"),
        ("ADMIN.MIOPTICADIGITAL.COM.AR", "/admin"),
        ("app.miopticadigital.com.ar", "/app"),
        ("sgi-optica.onrender.com", "/app"),
        # A label that merely starts with "admin" is a shop, not the provider.
        ("administracion.miopticadigital.com.ar", "/app"),
    ]:
        resp = client.get("/", headers={"host": host}, follow_redirects=False)
        assert resp.headers["location"] == expected, host

    # And the provider page is still served on whatever host asked for it.
    assert client.get("/admin", headers={"host": "admin.miopticadigital.com.ar"}
                      ).status_code == 200
    assert client.get("/app", headers={"host": "admin.miopticadigital.com.ar"}
                      ).status_code == 200
