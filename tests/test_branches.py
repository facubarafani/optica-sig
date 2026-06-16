def test_branch_crud_and_soft_delete(client, auth_headers):
    # create
    resp = client.post(
        "/api/branches",
        json={"name": "Central", "code": "MAIN", "phone": "111"},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    branch = resp.json()
    bid = branch["id"]
    assert branch["is_active"] is True

    # get
    assert client.get(f"/api/branches/{bid}", headers=auth_headers).status_code == 200

    # update
    resp = client.put(
        f"/api/branches/{bid}", json={"name": "Central 2"}, headers=auth_headers
    )
    assert resp.json()["name"] == "Central 2"

    # list shows it
    listed = client.get("/api/branches", headers=auth_headers).json()
    assert any(b["id"] == bid for b in listed)

    # soft delete
    assert client.delete(f"/api/branches/{bid}", headers=auth_headers).status_code == 204

    # default list hides inactive
    listed = client.get("/api/branches", headers=auth_headers).json()
    assert all(b["id"] != bid for b in listed)

    # include_inactive shows it again, still in DB (not physically deleted)
    listed = client.get(
        "/api/branches?include_inactive=true", headers=auth_headers
    ).json()
    inactive = next(b for b in listed if b["id"] == bid)
    assert inactive["is_active"] is False


def test_branch_not_found(client, auth_headers):
    assert client.get("/api/branches/999", headers=auth_headers).status_code == 404
