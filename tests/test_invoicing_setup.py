"""The facturación electrónica guide: the shop's side and ours.

The shop does its steps at ARCA, fills the guide and sends it; we accept the
delegation at ARCA and activate it from /admin. What matters most: the guide
only ever writes a request (activating stays ours), sending it reaches us,
and our answer reaches the shop.
"""
from __future__ import annotations

import pytest
from sqlalchemy import select

from app.core.config import settings
from app.models.enums import PlatformAction
from app.models.platform import PlatformAuditLog
from app.schemas.invoicing import valid_cuit
from app.services import arca

COMPANY = settings.default_company_id
SHOP_CUIT = "20111111112"
READY = {
    "cuit": "20-11111111-2", "legal_name": "OPTICA DE PRUEBA SRL", "iva_condition": "monotributo",
    "point_of_sale": 3, "commercial_address": "Av. Colón 1234, Mar del Plata",
    "gross_income_tax": "Exento", "activity_start_date": "2019-03-01",
    "trade_name": "Óptica de Prueba",
}


def setup_of(client, headers):
    resp = client.get("/api/invoicing/setup", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def send(client, headers, **overrides):
    return client.put("/api/invoicing/setup", json={**READY, "submit": True, **overrides},
                      headers=headers)


def activate(client, platform_headers, **overrides):
    body = {k: v for k, v in READY.items() if k != "cuit"}
    resp = client.post(f"/api/admin/tenants/{COMPANY}/invoicing",
                       json={**body, "cuit": SHOP_CUIT, **overrides}, headers=platform_headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.parametrize("cuit, ok", [
    ("20111111112", True), ("30712345671", True), ("20111111113", False),
    ("2011111111", False), ("2011111111x", False),
])
def test_the_cuit_check_digit_catches_typos(cuit, ok):
    assert valid_cuit(cuit) is ok


# --- the shop's side ---------------------------------------------------------------

def test_the_guide_starts_with_our_cuit(client, auth_headers):
    got = setup_of(client, auth_headers)
    assert got["available"] is True
    assert got["state"] == "not_started"
    assert got["platform_cuit"] == "30712345671"
    assert got["platform_name"] == "MI OPTICA DIGITAL"
    assert client.get("/api/invoicing/status", headers=auth_headers).json()["available"] is True


def test_without_our_cuit_the_guide_is_off(client, auth_headers, monkeypatch):
    monkeypatch.setattr(settings, "arca_platform_cuit", "")
    assert setup_of(client, auth_headers)["available"] is False
    assert send(client, auth_headers).status_code == 400


def test_a_draft_keeps_what_was_typed(client, auth_headers, outbox):
    resp = client.put("/api/invoicing/setup",
                      json={"cuit": "20-11111111-2", "legal_name": "A medias"}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    got = setup_of(client, auth_headers)
    assert got["state"] == "draft"
    assert got["request"]["cuit"] == SHOP_CUIT
    assert got["request"]["legal_name"] == "A medias"
    assert outbox == []


def test_sending_needs_everything_the_issuer_needs(client, auth_headers):
    resp = send(client, auth_headers, gross_income_tax=None, activity_start_date=None)
    assert resp.status_code == 400
    assert "Ingresos Brutos" in resp.json()["detail"]
    assert "inicio de actividades" in resp.json()["detail"]
    assert setup_of(client, auth_headers)["state"] == "not_started"


def test_a_mistyped_cuit_is_refused(client, auth_headers):
    resp = send(client, auth_headers, cuit="20-11111111-3")
    assert resp.status_code == 422


def test_sending_reaches_us(client, auth_headers, platform_headers, outbox):
    resp = send(client, auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["state"] == "submitted"
    assert [m.to for m in outbox] == ["owner@test.com"]
    assert outbox[0].subject == "Facturación por activar: Test Co"
    assert SHOP_CUIT in outbox[0].text and "punto de venta 3" in outbox[0].text
    tenants = client.get("/api/admin/tenants", headers=platform_headers).json()
    assert next(t for t in tenants if t["id"] == COMPANY)["invoicing"] == "submitted"


def test_we_see_the_request_beside_arcas_padron(client, auth_headers, platform_headers):
    send(client, auth_headers)
    got = client.get(f"/api/admin/tenants/{COMPANY}/invoicing", headers=platform_headers).json()
    assert got["linked"] is False
    assert got["request"]["iva_condition"] == "monotributo"
    assert got["taxpayer"] is None and "no tiene ese CUIT" in got["taxpayer_error"]

    arca.fake.add_taxpayer(SHOP_CUIT, name="OPTICA DE PRUEBA SRL", suggested="RESPONSABLE_INSCRIPTO")
    got = client.get(f"/api/admin/tenants/{COMPANY}/invoicing", headers=platform_headers).json()
    assert got["taxpayer"]["ivaCondition"]["suggested"] == "RESPONSABLE_INSCRIPTO"


def test_our_note_reaches_the_shop_and_sending_again_clears_it(
    client, auth_headers, platform_headers, outbox, db
):
    send(client, auth_headers)
    outbox.clear()
    resp = client.put(f"/api/admin/tenants/{COMPANY}/invoicing/note",
                      json={"note": "Todavía no vemos la delegación."}, headers=platform_headers)
    assert resp.status_code == 200, resp.text
    assert setup_of(client, auth_headers)["request"]["provider_note"] == "Todavía no vemos la delegación."
    assert [m.to for m in outbox] == ["admin@test.com"]
    assert "Todavía no vemos la delegación." in outbox[0].text
    actions = db.execute(select(PlatformAuditLog.action)).scalars().all()
    assert PlatformAction.TENANT_INVOICING_NOTE.value in actions

    send(client, auth_headers)
    assert setup_of(client, auth_headers)["request"]["provider_note"] is None


def test_activating_answers_the_request(client, auth_headers, platform_headers, outbox):
    send(client, auth_headers)
    outbox.clear()
    activate(client, platform_headers)
    got = setup_of(client, auth_headers)
    assert got["state"] == "active"
    assert got["issuer"]["cuit"] == SHOP_CUIT
    assert got["issuer"]["classes"] == ["C"]
    assert got["issuer"]["point_of_sale"] == 3
    assert [m.to for m in outbox] == ["admin@test.com"]
    assert outbox[0].subject.startswith("Tu facturación electrónica está activa")
    # Activo, the guide is read-only: the CUIT and the condition are fixed.
    assert send(client, auth_headers).status_code == 400
    tenants = client.get("/api/admin/tenants", headers=platform_headers).json()
    assert next(t for t in tenants if t["id"] == COMPANY)["invoicing"] == "active"


def test_pausing_shows_as_paused(client, auth_headers, platform_headers):
    send(client, auth_headers)
    activate(client, platform_headers)
    client.patch(f"/api/admin/tenants/{COMPANY}/invoicing", json={"is_active": False},
                 headers=platform_headers)
    assert setup_of(client, auth_headers)["state"] == "paused"


def test_the_guide_never_activates_by_itself(client, auth_headers):
    send(client, auth_headers)
    assert client.get("/api/invoicing/status", headers=auth_headers).json()["enabled"] is False
    assert arca.fake.issuers == {}


def test_only_company_writers_send(client, auth_headers):
    perms = client.get("/api/permissions", headers=auth_headers).json()
    read = next(p for p in perms if p["code"] == "company:read")
    role = client.post("/api/roles", json={"name": "Mirada", "permission_ids": [read["id"]]},
                       headers=auth_headers).json()
    client.post("/api/users", json={"email": "mira@test.com", "full_name": "Mira",
                                    "password": "mira123456", "role_ids": [role["id"]]},
                headers=auth_headers)
    token = client.post("/api/auth/login",
                        json={"email": "mira@test.com", "password": "mira123456"}).json()
    viewer = {"Authorization": f"Bearer {token['access_token']}"}
    assert setup_of(client, viewer)["state"] == "not_started"
    assert send(client, viewer).status_code == 403


def test_each_shop_sees_only_its_own_guide(client, auth_headers, platform_headers):
    send(client, auth_headers)
    resp = client.post("/api/admin/tenants", json={
        "name": "Otra", "admin_email": "otra@test.com", "admin_password": "otra123456",
    }, headers=platform_headers)
    assert resp.status_code == 201, resp.text
    token = client.post("/api/auth/login",
                        json={"email": "otra@test.com", "password": "otra123456"}).json()
    other = {"Authorization": f"Bearer {token['access_token']}"}
    got = setup_of(client, other)
    assert got["state"] == "not_started" and got["request"] is None


# --- Verificar --------------------------------------------------------------------------

def test_verificar_needs_it_active(client, auth_headers):
    resp = client.post("/api/invoicing/setup/check", headers=auth_headers)
    assert resp.status_code == 400


def test_verificar_says_it_works(client, auth_headers, platform_headers):
    send(client, auth_headers)
    activate(client, platform_headers)
    got = client.post("/api/invoicing/setup/check", headers=auth_headers).json()
    assert got["ok"] is True
    assert "Ya podés facturar" in got["message"]


def _health(invoicing_part):
    return {"ready": True, "credentialStatus": "ACTIVE",
            "arca": {"ok": True, "app": "OK", "db": "OK", "auth": "OK", "error": None},
            "authentication": {"ok": True, "expiresAt": None, "error": None},
            "invoicing": invoicing_part}


def test_verificar_explains_a_missing_delegation(client, auth_headers, platform_headers):
    send(client, auth_headers)
    activate(client, platform_headers)
    arca.fake.health = _health({"ok": False, "pointsOfSale": None, "error":
                                "ValidacionDeToken: No aparecio CUIT en lista de relaciones: 20111111112"})
    got = client.post("/api/invoicing/setup/check", headers=auth_headers).json()
    assert got["ok"] is False
    assert "delegación" in got["message"]


def test_verificar_catches_a_point_of_sale_arca_does_not_list(client, auth_headers, platform_headers):
    send(client, auth_headers)
    activate(client, platform_headers)
    arca.fake.health = _health({"ok": True, "error": None, "pointsOfSale": [
        {"number": 4, "emissionType": "CAE - Monotributo", "blocked": False}]})
    got = client.post("/api/invoicing/setup/check", headers=auth_headers).json()
    assert got["ok"] is False
    assert "punto de venta 3" in got["message"]
    assert got["points_of_sale"] == [4]


# --- ARCA's screenshots in the guide ------------------------------------------------------

def test_the_guide_screenshots_are_served(client, monkeypatch):
    # As on python:3.12 (production), which has no media type for .webp: the
    # route states it instead of guessing.
    import mimetypes
    monkeypatch.setattr(mimetypes, "guess_type", lambda *a, **k: (None, None))
    resp = client.get("/app/guia/pdv-3-formulario.webp")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/webp"
    assert resp.content[:4] == b"RIFF"


@pytest.mark.parametrize("name", ["nope.webp", "..%2Findex.html", "pdv-3-formulario.png", "%2Fetc%2Fpasswd"])
def test_only_the_guide_images_are_served(client, name):
    assert client.get(f"/app/guia/{name}").status_code == 404


def test_every_screenshot_the_guide_names_exists():
    """A renamed or missing file would leave a step with a broken image."""
    import re
    from pathlib import Path

    web = Path(__file__).resolve().parent.parent / "app" / "web"
    html = (web / "index.html").read_text()
    names = set(re.findall(r'\["((?:pdv|del)-\d-[a-z-]+)"', html))
    assert len(names) == 10
    files = {p.stem for p in (web / "guia").glob("*.webp")}
    assert names == files
