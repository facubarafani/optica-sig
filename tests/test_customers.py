def _make_customer(client, headers):
    resp = client.post(
        "/api/customers",
        json={"first_name": "Juan", "last_name": "Pérez", "document_number": "30111222"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def test_customer_crud(client, auth_headers):
    cid = _make_customer(client, auth_headers)
    got = client.get(f"/api/customers/{cid}", headers=auth_headers).json()
    assert got["last_name"] == "Pérez"

    upd = client.put(
        f"/api/customers/{cid}", json={"phone": "11-1234"}, headers=auth_headers
    )
    assert upd.json()["phone"] == "11-1234"

    assert client.delete(f"/api/customers/{cid}", headers=auth_headers).status_code == 204
    listed = client.get("/api/customers", headers=auth_headers).json()
    assert all(c["id"] != cid for c in listed)


def test_prescription_history(client, auth_headers):
    cid = _make_customer(client, auth_headers)
    resp = client.post(
        f"/api/customers/{cid}/prescriptions",
        json={
            "doctor_name": "Dr. House",
            "right_sphere": "-1.25", "right_cylinder": "-0.50", "right_axis": 90,
            "left_sphere": "-1.00", "pupillary_distance": "62",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["right_sphere"] == "-1.25"
    assert body["right_axis"] == 90

    history = client.get(
        f"/api/customers/{cid}/prescriptions", headers=auth_headers
    ).json()
    assert len(history) == 1


def test_treatment_history(client, auth_headers):
    cid = _make_customer(client, auth_headers)
    resp = client.post(
        f"/api/customers/{cid}/treatments",
        json={"treatment_type": "myopia", "description": "Progressive myopia"},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["treatment_type"] == "myopia"

    history = client.get(
        f"/api/customers/{cid}/treatments", headers=auth_headers
    ).json()
    assert len(history) == 1
