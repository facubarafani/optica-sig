"""RBAC: a non-superuser only gets through where its role grants permission."""


def _seed_role_and_user(client, auth_headers):
    # read-only permissions for products
    perms = client.get("/api/permissions", headers=auth_headers).json()
    read_perm = next(p for p in perms if p["code"] == "products:read")
    role = client.post(
        "/api/roles",
        json={"name": "Viewer", "permission_ids": [read_perm["id"]]},
        headers=auth_headers,
    ).json()
    user = client.post(
        "/api/users",
        json={
            "email": "viewer@test.com", "full_name": "Viewer",
            "password": "viewer1234", "role_ids": [role["id"]],
        },
        headers=auth_headers,
    )
    assert user.status_code == 201, user.text
    return "viewer@test.com", "viewer1234"


def _login(client, email, password):
    token = client.post(
        "/api/auth/login", json={"email": email, "password": password}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_permission_grants_read_but_denies_write(client, auth_headers):
    email, password = _seed_role_and_user(client, auth_headers)
    viewer = _login(client, email, password)

    # granted: products:read
    assert client.get("/api/products", headers=viewer).status_code == 200

    # denied: products:write
    resp = client.post(
        "/api/products",
        json={"code": "X", "name": "X", "product_type_id": 1},
        headers=viewer,
    )
    assert resp.status_code == 403
    assert "products:write" in resp.json()["detail"]

    # denied: a permission the role doesn't have at all
    assert client.get("/api/customers", headers=viewer).status_code == 403


def test_duplicate_user_email_rejected(client, auth_headers):
    client.post(
        "/api/users",
        json={"email": "dup@test.com", "full_name": "A", "password": "x123456"},
        headers=auth_headers,
    )
    dup = client.post(
        "/api/users",
        json={"email": "dup@test.com", "full_name": "B", "password": "x123456"},
        headers=auth_headers,
    )
    assert dup.status_code == 400
