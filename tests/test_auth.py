def test_login_success(client):
    resp = client.post(
        "/api/auth/login",
        json={"email": "admin@test.com", "password": "admin1234"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]


def test_login_wrong_password(client):
    resp = client.post(
        "/api/auth/login",
        json={"email": "admin@test.com", "password": "nope"},
    )
    assert resp.status_code == 401


def test_me_requires_auth(client):
    assert client.get("/api/auth/me").status_code == 401


def test_me_returns_current_user(client, auth_headers):
    resp = client.get("/api/auth/me", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["email"] == "admin@test.com"
    assert resp.json()["is_superuser"] is True


def test_protected_endpoint_without_token(client):
    assert client.get("/api/branches").status_code == 401


def test_oauth2_token_form(client):
    resp = client.post(
        "/api/auth/token",
        data={"username": "admin@test.com", "password": "admin1234"},
    )
    assert resp.status_code == 200
    assert resp.json()["access_token"]


# --- changing your own password ----------------------------------------------

def _login(client, password):
    return client.post("/api/auth/login",
                       json={"email": "admin@test.com", "password": password})


def test_change_password_with_the_current_one(client, auth_headers):
    resp = client.post(
        "/api/auth/change-password",
        json={"current_password": "admin1234", "new_password": "otra-clave-9"},
        headers=auth_headers,
    )
    assert resp.status_code == 204, resp.text
    assert _login(client, "otra-clave-9").status_code == 200
    assert _login(client, "admin1234").status_code == 401


def test_change_password_refuses_a_wrong_current_one(client, auth_headers):
    resp = client.post(
        "/api/auth/change-password",
        json={"current_password": "no-es-esta", "new_password": "otra-clave-9"},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "La contraseña actual no es correcta."
    assert _login(client, "admin1234").status_code == 200


def test_change_password_wants_a_long_enough_new_one(client, auth_headers):
    resp = client.post(
        "/api/auth/change-password",
        json={"current_password": "admin1234", "new_password": "corta"},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert resp.json()["detail"][0]["msg"] == "Necesita al menos 8 caracteres."


def test_change_password_needs_a_login(client):
    resp = client.post(
        "/api/auth/change-password",
        json={"current_password": "admin1234", "new_password": "otra-clave-9"},
    )
    assert resp.status_code == 401


def test_a_support_session_cannot_change_the_password(client, db):
    """The provider may act as a shop's user to help, never take the account."""
    from app.core.security import SCOPE_TENANT, create_access_token
    from app.models.auth import User

    user = db.query(User).filter_by(email="admin@test.com").one()
    token = create_access_token(
        user.id,
        extra={"company_id": user.company_id, "impersonated_by": "owner@test.com"},
        scope=SCOPE_TENANT,
    )
    resp = client.post(
        "/api/auth/change-password",
        json={"current_password": "admin1234", "new_password": "otra-clave-9"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
    assert "soporte" in resp.json()["detail"]
    assert _login(client, "admin1234").status_code == 200


def test_change_password_is_rate_limited(client, auth_headers):
    """A stolen session must not be able to guess the current password."""
    for _ in range(10):
        client.post(
            "/api/auth/change-password",
            json={"current_password": "no-es-esta", "new_password": "otra-clave-9"},
            headers=auth_headers,
        )
    resp = client.post(
        "/api/auth/change-password",
        json={"current_password": "admin1234", "new_password": "otra-clave-9"},
        headers=auth_headers,
    )
    assert resp.status_code == 429


def test_change_password_service(db):
    import pytest
    from app.core.security import verify_password
    from app.models.auth import User
    from app.services import auth as auth_service

    user = db.query(User).filter_by(email="admin@test.com").one()
    with pytest.raises(auth_service.AuthError):
        auth_service.change_password(db, user, "no-es-esta", "otra-clave-9")
    assert verify_password("admin1234", user.hashed_password)

    auth_service.change_password(db, user, "admin1234", "otra-clave-9")
    db.refresh(user)
    assert verify_password("otra-clave-9", user.hashed_password)
    assert not verify_password("admin1234", user.hashed_password)
