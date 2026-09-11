"""Emailed invitations and self-service password resets.

The properties worth pinning down are the security ones: a link works once,
expires, is stored only as a hash, and the reset endpoint tells an attacker
nothing about which addresses have accounts.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core import ratelimit
from app.models.auth import User
from app.models.enums import TokenPurpose
from app.models.token import UserToken
from app.services import invitations


def _link_token(message) -> str:
    """Pull the raw token out of a sent email, the way a user's browser would."""
    marker = "#/password/"
    assert marker in message.text, message.text
    return message.text.split(marker)[1].split()[0].strip()


# --- token handling -------------------------------------------------------
def test_the_raw_token_is_never_stored(db, outbox):
    user = db.execute(select(User)).scalars().first()
    raw = invitations.issue(db, user, TokenPurpose.PASSWORD_RESET)

    row = db.execute(select(UserToken)).scalars().one()
    assert row.token_hash != raw
    assert row.token_hash == hashlib.sha256(raw.encode()).hexdigest()
    # Nothing anywhere in the row can be turned back into the link.
    assert raw not in str(row.__dict__)


def test_issuing_a_new_link_voids_the_previous_one(db):
    user = db.execute(select(User)).scalars().first()
    first = invitations.issue(db, user, TokenPurpose.PASSWORD_RESET)
    second = invitations.issue(db, user, TokenPurpose.PASSWORD_RESET)

    with pytest.raises(invitations.InvitationError, match="ya fue usado"):
        invitations.resolve(db, first)
    assert invitations.resolve(db, second)


def test_an_expired_link_is_refused(db):
    user = db.execute(select(User)).scalars().first()
    raw = invitations.issue(db, user, TokenPurpose.PASSWORD_RESET)
    row = db.execute(select(UserToken)).scalars().one()
    row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()

    with pytest.raises(invitations.InvitationError, match="venció"):
        invitations.resolve(db, raw)


def test_a_garbage_token_is_refused(db):
    with pytest.raises(invitations.InvitationError, match="no es válido"):
        invitations.resolve(db, "no-es-un-token")


def test_the_link_carries_the_token_in_the_fragment(db):
    """Fragments are never sent to the server, keeping tokens out of logs."""
    link = invitations.build_link("abc123")
    assert "#/password/abc123" in link
    assert "?" not in link.split("#")[0].split("//", 1)[1]


# --- the reset flow -------------------------------------------------------
def test_forgot_password_emails_a_working_link(client, outbox):
    resp = client.post(
        "/api/auth/forgot-password", json={"email": "admin@test.com"}
    )
    assert resp.status_code == 202
    assert len(outbox) == 1
    assert outbox[0].to == "admin@test.com"

    token = _link_token(outbox[0])
    check = client.get(f"/api/auth/password-token/{token}")
    assert check.status_code == 200
    assert check.json()["purpose"] == "password_reset"

    done = client.post(
        "/api/auth/set-password",
        json={"token": token, "new_password": "mi-clave-nueva"},
    )
    assert done.status_code == 200
    assert done.json()["access_token"], "should hand back a session, not a login form"

    assert client.post(
        "/api/auth/login", json={"email": "admin@test.com", "password": "admin1234"}
    ).status_code == 401
    assert client.post(
        "/api/auth/login",
        json={"email": "admin@test.com", "password": "mi-clave-nueva"},
    ).status_code == 200


def test_a_link_works_exactly_once(client, outbox):
    client.post("/api/auth/forgot-password", json={"email": "admin@test.com"})
    token = _link_token(outbox[0])
    assert client.post(
        "/api/auth/set-password", json={"token": token, "new_password": "primera-clave"}
    ).status_code == 200
    second = client.post(
        "/api/auth/set-password", json={"token": token, "new_password": "segunda-clave"}
    )
    assert second.status_code == 400
    assert "ya fue usado" in second.json()["detail"]
    # And the first password is still the live one.
    assert client.post(
        "/api/auth/login", json={"email": "admin@test.com", "password": "primera-clave"}
    ).status_code == 200


def test_forgot_password_does_not_reveal_whether_an_account_exists(client, outbox):
    """Identical status and body either way — only the inbox differs."""
    real = client.post("/api/auth/forgot-password", json={"email": "admin@test.com"})
    ratelimit.reset()
    fake = client.post("/api/auth/forgot-password", json={"email": "nadie@ejemplo.com"})

    assert real.status_code == fake.status_code == 202
    assert real.json() == fake.json()
    assert [m.to for m in outbox] == ["admin@test.com"]


def test_reset_is_rate_limited_per_address(client, outbox):
    for _ in range(5):
        assert client.post(
            "/api/auth/forgot-password", json={"email": "admin@test.com"}
        ).status_code == 202
    blocked = client.post("/api/auth/forgot-password", json={"email": "admin@test.com"})
    assert blocked.status_code == 429
    assert len(outbox) == 5, "the blocked attempt must not send"


def test_a_suspended_shop_gets_no_reset_link(client, platform_headers, outbox):
    """Cutting a tenant off must not leave a working way back in."""
    resp = client.post(
        "/api/admin/tenants",
        json={
            "name": "Óptica Suspendida",
            "admin_email": "duena@suspendida.com",
            "admin_password": "clave-inicial",
        },
        headers=platform_headers,
    )
    company_id = resp.json()["company"]["id"]
    client.post(f"/api/admin/tenants/{company_id}/suspend", headers=platform_headers)
    outbox.clear()

    assert client.post(
        "/api/auth/forgot-password", json={"email": "duena@suspendida.com"}
    ).status_code == 202
    assert outbox == [], "no link for a suspended company"


# --- the invitation flow --------------------------------------------------
def test_onboarding_without_a_password_invites_the_owner(
    client, platform_headers, outbox
):
    resp = client.post(
        "/api/admin/tenants",
        json={
            "name": "Óptica Belgrano",
            "admin_email": "ana@belgrano.com",
            "admin_full_name": "Ana Belgrano",
        },
        headers=platform_headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["admin_password"] is None, "we never choose their credential"
    assert body["invitation_sent"] is True
    assert len(outbox) == 1 and outbox[0].to == "ana@belgrano.com"

    # Until they accept, nothing opens the account.
    assert client.post(
        "/api/auth/login",
        json={"email": "ana@belgrano.com", "password": "cualquier-cosa"},
    ).status_code == 401

    token = _link_token(outbox[0])
    check = client.get(f"/api/auth/password-token/{token}").json()
    assert check["purpose"] == "invitation"
    assert check["company_name"] == "Óptica Belgrano"

    client.post(
        "/api/auth/set-password",
        json={"token": token, "new_password": "la-que-elijo-yo"},
    )
    assert client.post(
        "/api/auth/login",
        json={"email": "ana@belgrano.com", "password": "la-que-elijo-yo"},
    ).status_code == 200


def test_onboarding_with_a_password_still_works_and_sends_nothing(
    client, platform_headers, outbox
):
    """The fallback for an owner whose email is not working yet."""
    resp = client.post(
        "/api/admin/tenants",
        json={
            "name": "Óptica Sin Mail",
            "admin_email": "duena@sinmail.com",
            "admin_password": "una-clave-larga",
        },
        headers=platform_headers,
    )
    assert resp.json()["admin_password"] == "una-clave-larga"
    assert resp.json()["invitation_sent"] is False
    assert outbox == []
    assert client.post(
        "/api/auth/login",
        json={"email": "duena@sinmail.com", "password": "una-clave-larga"},
    ).status_code == 200


def test_resending_an_invitation_voids_the_earlier_link(
    client, platform_headers, outbox
):
    created = client.post(
        "/api/admin/tenants",
        json={"name": "Óptica Reenvío", "admin_email": "re@envio.com"},
        headers=platform_headers,
    ).json()
    cid = created["company"]["id"]
    first_token = _link_token(outbox[0])
    user_id = client.get(
        f"/api/admin/tenants/{cid}/users", headers=platform_headers
    ).json()[0]["id"]

    resp = client.post(
        f"/api/admin/tenants/{cid}/users/{user_id}/invite", headers=platform_headers
    )
    assert resp.status_code == 200 and resp.json()["sent"] is True
    assert len(outbox) == 2

    assert client.get(f"/api/auth/password-token/{first_token}").status_code == 400
    assert client.get(
        f"/api/auth/password-token/{_link_token(outbox[1])}"
    ).status_code == 200


def test_adding_an_admin_without_a_password_invites_them(
    client, platform_headers, outbox
):
    created = client.post(
        "/api/admin/tenants",
        json={
            "name": "Óptica Socios",
            "admin_email": "uno@socios.com",
            "admin_password": "clave-del-uno",
        },
        headers=platform_headers,
    ).json()
    cid = created["company"]["id"]
    outbox.clear()

    resp = client.post(
        f"/api/admin/tenants/{cid}/users",
        json={"email": "dos@socios.com", "full_name": "Socio Dos"},
        headers=platform_headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["invitation_sent"] is True
    assert resp.json()["password"] is None
    assert len(outbox) == 1 and outbox[0].to == "dos@socios.com"


def test_one_address_at_two_shops_gets_a_link_for_each(
    client, platform_headers, outbox
):
    """Each mail names its óptica, so the owner knows which one they are fixing."""
    shared = "contadora@estudio.com"
    for name in ("Óptica Norte", "Óptica Sur"):
        client.post(
            "/api/admin/tenants",
            json={"name": name, "admin_email": shared, "admin_password": "clave-inicial"},
            headers=platform_headers,
        )
    outbox.clear()

    client.post("/api/auth/forgot-password", json={"email": shared})
    assert len(outbox) == 2
    assert {"Óptica Norte", "Óptica Sur"} == {
        n for n in ("Óptica Norte", "Óptica Sur")
        for m in outbox if n in m.text
    }
    # The two links are different accounts, and each works on its own.
    tokens = [_link_token(m) for m in outbox]
    assert len(set(tokens)) == 2
    for t in tokens:
        assert client.get(f"/api/auth/password-token/{t}").status_code == 200


# --- the email backend seam ----------------------------------------------
def test_an_unknown_backend_fails_loudly_but_does_not_raise(monkeypatch):
    """A misconfigured provider must not take down the request that sent."""
    from app.core.config import settings
    from app.services import email as email_service

    monkeypatch.setattr(settings, "email_backend", "no-existe")
    sent = email_service.send(
        email_service.Message(to="a@b.com", subject="x", text="t", html="<p>t</p>")
    )
    assert sent is False


def test_a_failing_provider_does_not_undo_the_tenant(
    client, platform_headers, monkeypatch
):
    """The shop is real whether or not the mail went out; resend, don't re-onboard."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "email_backend", "smtp")
    monkeypatch.setattr(settings, "smtp_host", "")  # guarantees an EmailError

    resp = client.post(
        "/api/admin/tenants",
        json={"name": "Óptica Sin Correo", "admin_email": "x@sincorreo.com"},
        headers=platform_headers,
    )
    assert resp.status_code == 201
    assert resp.json()["invitation_sent"] is False
    users = client.get(
        f"/api/admin/tenants/{resp.json()['company']['id']}/users",
        headers=platform_headers,
    ).json()
    assert len(users) == 1, "the account exists and can be re-invited"


# --- the Resend backend ---------------------------------------------------
def test_resend_backend_posts_the_expected_payload(monkeypatch):
    """Pin the request shape so a provider change is a deliberate edit."""
    import httpx

    from app.core.config import settings
    from app.services import email as email_service

    captured = {}

    class _Resp:
        status_code = 200
        text = '{"id":"abc"}'

    def fake_post(url, **kw):
        captured["url"] = url
        captured["headers"] = kw["headers"]
        captured["json"] = kw["json"]
        return _Resp()

    monkeypatch.setattr(settings, "email_backend", "resend")
    monkeypatch.setattr(settings, "resend_api_key", "re_test_key")
    monkeypatch.setattr(settings, "email_from", "Mi Óptica <no-reply@ejemplo.com.ar>")
    monkeypatch.setattr(httpx, "post", fake_post)

    ok = email_service.send(
        email_service.Message(
            to="ana@belgrano.com", subject="Hola", text="texto", html="<p>html</p>"
        )
    )
    assert ok is True
    assert captured["url"] == "https://api.resend.com/emails"
    assert captured["headers"]["Authorization"] == "Bearer re_test_key"
    assert captured["json"] == {
        "from": "Mi Óptica <no-reply@ejemplo.com.ar>",
        "to": ["ana@belgrano.com"],
        "subject": "Hola",
        "text": "texto",
        "html": "<p>html</p>",
    }


def test_resend_without_a_key_fails_without_raising(monkeypatch):
    from app.core.config import settings
    from app.services import email as email_service

    monkeypatch.setattr(settings, "email_backend", "resend")
    monkeypatch.setattr(settings, "resend_api_key", "")
    assert email_service.send(
        email_service.Message(to="a@b.com", subject="x", text="t", html="<p>t</p>")
    ) is False


def test_resend_reports_an_unverified_domain(monkeypatch):
    """403 from Resend means the domain is not verified — the usual first error."""
    import httpx

    from app.core.config import settings
    from app.services import email as email_service

    class _Resp:
        status_code = 403
        text = '{"message":"The miopticadigital.com.ar domain is not verified"}'

    monkeypatch.setattr(settings, "email_backend", "resend")
    monkeypatch.setattr(settings, "resend_api_key", "re_test_key")
    monkeypatch.setattr(httpx, "post", lambda url, **kw: _Resp())

    assert email_service.send(
        email_service.Message(to="a@b.com", subject="x", text="t", html="<p>t</p>")
    ) is False
