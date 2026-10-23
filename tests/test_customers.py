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


def test_create_customer_with_treatments(client, auth_headers):
    """The new-customer form's last step sends the treatments along."""
    resp = client.post(
        "/api/customers",
        json={
            "first_name": "Ana", "last_name": "Gómez",
            "treatments": [
                {"treatment_type": "myopia", "diagnosed_at": "2024-03-01",
                 "description": "Progresiva"},
                {"treatment_type": "astigmatism"},
            ],
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    cid = resp.json()["id"]

    history = client.get(
        f"/api/customers/{cid}/treatments", headers=auth_headers
    ).json()
    by_type = {t["treatment_type"]: t for t in history}
    assert set(by_type) == {"myopia", "astigmatism"}
    assert by_type["myopia"]["diagnosed_at"] == "2024-03-01"
    assert by_type["myopia"]["description"] == "Progresiva"
    assert by_type["astigmatism"]["diagnosed_at"] is None


def test_create_customer_with_prescription(client, auth_headers):
    """The new-customer form's receta step: saved with the customer."""
    resp = client.post(
        "/api/customers",
        json={
            "first_name": "Ana", "last_name": "Gómez",
            "prescription": {
                "doctor_name": "Dra. Paz",
                "right_sphere": "-2.25", "right_cylinder": "-0.50", "right_axis": 180,
                "right_addition": "2.00", "left_sphere": "-2.00", "left_addition": "2.00",
            },
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    recetas = client.get(
        f"/api/customers/{resp.json()['id']}/prescriptions", headers=auth_headers
    ).json()
    assert len(recetas) == 1
    assert recetas[0]["right_sphere"] == "-2.25"
    assert recetas[0]["right_axis"] == 180
    assert recetas[0]["created_by_user_id"] is not None


def test_prescription_axis_is_0_to_180(client, auth_headers):
    cid = _make_customer(client, auth_headers)
    resp = client.post(
        f"/api/customers/{cid}/prescriptions",
        json={"right_cylinder": "-0.50", "right_axis": 190},
        headers=auth_headers,
    )
    assert resp.status_code == 422


def test_list_carries_treatments(client, auth_headers):
    """The list's Tratamientos column: each kind once, in the enum's order."""
    resp = client.post(
        "/api/customers",
        json={"first_name": "Ana", "last_name": "Gómez", "treatments": [
            {"treatment_type": "presbyopia"},
            {"treatment_type": "myopia", "description": "2019"},
            {"treatment_type": "myopia", "description": "2024"},
        ]},
        headers=auth_headers,
    )
    with_treatments = resp.json()["id"]
    without = _make_customer(client, auth_headers)

    rows = {c["id"]: c for c in
            client.get("/api/customers", headers=auth_headers).json()}
    assert rows[with_treatments]["treatments"] == ["myopia", "presbyopia"]
    assert rows[without]["treatments"] == []


def test_create_customer_refuses_unknown_treatment(client, auth_headers):
    """One bad treatment refuses the whole form: no customer is left behind."""
    resp = client.post(
        "/api/customers",
        json={"first_name": "Ana", "last_name": "Gómez",
              "treatments": [{"treatment_type": "glaucoma"}]},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    listed = client.get("/api/customers", headers=auth_headers).json()
    assert all(c["last_name"] != "Gómez" for c in listed)


def test_an_axis_past_180_still_reads_but_is_never_written(client, auth_headers, db):
    """Recetas typed before the 0-180 check may hold one; reading must not fail."""
    from app.core.config import settings
    from app.models.customer import Prescription

    cid = client.post("/api/customers", json={"first_name": "Laura", "last_name": "Giménez"},
                      headers=auth_headers).json()["id"]
    db.add(Prescription(company_id=settings.default_company_id, customer_id=cid, right_axis=190))
    db.commit()

    resp = client.get(f"/api/customers/{cid}/prescriptions", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()[0]["right_axis"] == 190
    resp = client.post(f"/api/customers/{cid}/prescriptions", json={"right_axis": 190},
                       headers=auth_headers)
    assert resp.status_code == 422


def test_a_dioptre_past_its_column_is_a_422(client, auth_headers):
    cid = client.post("/api/customers", json={"first_name": "Laura", "last_name": "Giménez"},
                      headers=auth_headers).json()["id"]
    resp = client.post(f"/api/customers/{cid}/prescriptions", json={"right_sphere": "1234.5"},
                       headers=auth_headers)
    assert resp.status_code == 422
    resp = client.post(f"/api/customers/{cid}/prescriptions", json={"right_sphere": "-2.25"},
                       headers=auth_headers)
    assert resp.status_code == 201, resp.text
