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
