"""Phone handoff: the PC asks for a photo, the phone sends it (receta scanner)."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone

from app.models.handoff import PhotoHandoff
from app.services import handoffs

# Only the first bytes matter: they are what says it is a photo.
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 200
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 200

OTHER_SHOP = {
    "name": "Óptica San Martín",
    "legal_name": "San Martín SRL",
    "tax_id": "30-99887766-5",
    "admin_email": "dueno@sanmartin.com",
    "admin_full_name": "Dueño",
    "admin_password": "sanmartin1234",
}


def _create(client, headers):
    resp = client.post("/api/handoffs", headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _token(handoff) -> str:
    return handoff["url"].split("#", 1)[1]


def _upload(client, token, data=JPEG, name="receta.jpg"):
    """What the phone page sends: no login, just the token from the QR."""
    return client.post(
        "/api/handoffs/upload",
        data={"token": token}, files={"photo": (name, data, "image/jpeg")},
    )


def test_photo_goes_from_phone_to_pc_and_then_is_gone(client, auth_headers, db):
    h = _create(client, auth_headers)
    assert "/foto#" in h["url"]
    assert h["qr_svg"].startswith("<svg")
    state = client.get(f"/api/handoffs/{h['id']}", headers=auth_headers)
    assert state.json()["status"] == "waiting"

    assert _upload(client, _token(h)).status_code == 200

    state = client.get(f"/api/handoffs/{h['id']}", headers=auth_headers)
    assert state.json()["status"] == "received"
    photo = client.get(f"/api/handoffs/{h['id']}/photo", headers=auth_headers)
    assert photo.content == JPEG
    assert photo.headers["content-type"] == "image/jpeg"
    assert photo.headers["cache-control"] == "no-store"

    # The PC has the photo, so the row goes with it.
    assert client.delete(f"/api/handoffs/{h['id']}", headers=auth_headers).status_code == 204
    assert db.query(PhotoHandoff).count() == 0
    assert client.get(f"/api/handoffs/{h['id']}", headers=auth_headers).status_code == 404


def test_only_the_tokens_hash_is_stored(client, auth_headers, db):
    h = _create(client, auth_headers)
    row = db.query(PhotoHandoff).one()
    assert row.token_hash == hashlib.sha256(_token(h).encode()).hexdigest()


def test_a_token_works_once(client, auth_headers):
    h = _create(client, auth_headers)
    assert _upload(client, _token(h)).status_code == 200
    assert _upload(client, _token(h)).status_code == 409


def test_an_expired_token_is_refused(client, auth_headers, db):
    h = _create(client, auth_headers)
    row = db.get(PhotoHandoff, h["id"])
    row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.commit()
    assert _upload(client, _token(h)).status_code == 410
    state = client.get(f"/api/handoffs/{h['id']}", headers=auth_headers)
    assert state.json()["status"] == "expired"


def test_unknown_tokens_and_non_photos_are_refused(client, auth_headers):
    assert _upload(client, "not-a-token").status_code == 404
    h = _create(client, auth_headers)
    # Judged by its first bytes, not by the type the phone claims.
    assert _upload(client, _token(h), data=b"%PDF-1.7 not a photo").status_code == 415
    # A refused upload does not use the token up.
    assert _upload(client, _token(h), data=PNG, name="receta.png").status_code == 200


def test_an_oversized_photo_is_refused(client, auth_headers, monkeypatch):
    monkeypatch.setattr(handoffs, "MAX_PHOTO_BYTES", 100)
    h = _create(client, auth_headers)
    assert _upload(client, _token(h)).status_code == 413


def test_uploads_are_rate_limited(client):
    for _ in range(20):
        _upload(client, "guess")
    assert _upload(client, "guess").status_code == 429


def test_another_shop_cannot_reach_the_photo(client, auth_headers, platform_headers):
    h = _create(client, auth_headers)
    _upload(client, _token(h))
    resp = client.post("/api/admin/tenants", json=OTHER_SHOP, headers=platform_headers)
    assert resp.status_code == 201, resp.text
    login = client.post("/api/auth/login", json={
        "email": OTHER_SHOP["admin_email"], "password": OTHER_SHOP["admin_password"]})
    other = {"Authorization": f"Bearer {login.json()['access_token']}"}

    assert client.get(f"/api/handoffs/{h['id']}", headers=other).status_code == 404
    assert client.get(f"/api/handoffs/{h['id']}/photo", headers=other).status_code == 404
    client.delete(f"/api/handoffs/{h['id']}", headers=other)
    assert client.get(f"/api/handoffs/{h['id']}", headers=auth_headers).status_code == 200


def test_left_behind_handoffs_are_swept(client, auth_headers, db):
    """A tab closed before the photo was fetched leaves a row: the next
    handoff anyone asks for clears it once it is past its time."""
    old = _create(client, auth_headers)
    _upload(client, _token(old))
    row = db.get(PhotoHandoff, old["id"])
    row.created_at = datetime.now(timezone.utc) - timedelta(
        minutes=handoffs.RETENTION_MINUTES + 1)
    db.commit()

    _create(client, auth_headers)
    # By token, not id: SQLite hands the freed id to the new row.
    old_hash = hashlib.sha256(_token(old).encode()).hexdigest()
    assert db.query(PhotoHandoff).filter_by(token_hash=old_hash).count() == 0
    assert db.query(PhotoHandoff).count() == 1


def test_asking_for_a_handoff_needs_a_login(client):
    assert client.post("/api/handoffs").status_code == 401


def test_on_a_developer_machine_the_qr_points_to_the_wifi_address(monkeypatch):
    monkeypatch.setattr(handoffs.settings, "public_base_url", "http://localhost:8000")
    monkeypatch.setattr(handoffs, "_lan_ip", lambda: "192.168.1.20")
    monkeypatch.setattr(handoffs.settings, "environment", "local")
    assert handoffs.phone_url("tok") == "http://192.168.1.20:8000/foto#tok"
    monkeypatch.setattr(handoffs.settings, "environment", "production")
    assert handoffs.phone_url("tok") == "http://localhost:8000/foto#tok"


def _backdate(db, handoff_id, minutes):
    row = db.get(PhotoHandoff, handoff_id)
    row.created_at = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    db.commit()


def test_a_photo_past_its_time_is_never_served(client, auth_headers, db):
    """A photo the PC never came for goes once it is RETENTION_MINUTES old,
    whatever the page that asks."""
    h = _create(client, auth_headers)
    _upload(client, _token(h))
    _backdate(db, h["id"], handoffs.RETENTION_MINUTES + 1)

    state = client.get(f"/api/handoffs/{h['id']}", headers=auth_headers)
    assert state.json()["status"] == "expired"
    assert client.get(f"/api/handoffs/{h['id']}/photo", headers=auth_headers).status_code == 410
    db.expire_all()
    assert db.query(PhotoHandoff).count() == 0


def test_the_app_sweeps_without_waiting_for_a_new_qr(client, auth_headers, db):
    from sqlalchemy.orm import sessionmaker

    h = _create(client, auth_headers)
    _upload(client, _token(h))
    _backdate(db, h["id"], handoffs.RETENTION_MINUTES + 1)

    handoffs.sweep_once(sessionmaker(bind=db.get_bind()))
    db.expire_all()
    assert db.query(PhotoHandoff).count() == 0


def test_a_body_with_no_length_is_capped_before_it_is_read(client, monkeypatch):
    """A chunked body declares no length. The cap holds anyway, before the
    form is parsed, or a guessed token would let anyone fill the disk."""
    monkeypatch.setattr(handoffs, "MAX_PHOTO_BYTES", 100)
    boundary = "receta-boundary"

    def body():
        yield (f'--{boundary}\r\nContent-Disposition: form-data; name="token"\r\n\r\n'
               f'not-a-token\r\n--{boundary}\r\nContent-Disposition: form-data; '
               f'name="photo"; filename="r.jpg"\r\nContent-Type: image/jpeg\r\n\r\n').encode()
        for _ in range(100):
            yield b"\xff" * 1000
        yield f"\r\n--{boundary}--\r\n".encode()

    resp = client.post(
        "/api/handoffs/upload", content=body(),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    assert resp.status_code == 413


def test_a_token_cannot_be_spent_twice_at_once(client, auth_headers, db, monkeypatch):
    """Two uploads racing on one token: the first stands, the second is told."""
    from sqlalchemy import update

    h = _create(client, auth_headers)
    sniff = handoffs._sniff

    def racing(data):
        # The other upload lands between this one's checks and its write.
        db.execute(update(PhotoHandoff).where(PhotoHandoff.id == h["id"]).values(
            photo=PNG, photo_type="image/png", received_at=datetime.now(timezone.utc)))
        db.commit()
        return sniff(data)

    monkeypatch.setattr(handoffs, "_sniff", racing)
    assert _upload(client, _token(h)).status_code == 409
    db.expire_all()
    assert db.get(PhotoHandoff, h["id"]).photo == PNG


def test_a_suspended_shop_receives_no_photo(client, auth_headers, db):
    from app.models.company import Company

    h = _create(client, auth_headers)
    company = db.get(Company, db.get(PhotoHandoff, h["id"]).company_id)
    company.is_active = False
    db.commit()
    assert _upload(client, _token(h)).status_code == 403


def test_a_short_window_does_not_reset_a_long_one(monkeypatch):
    """Ten minutes of anonymous uploads must not wipe an hour of password
    guesses: each key is swept by its own window."""
    from app.core import ratelimit

    now = [10_000.0]
    monkeypatch.setattr(ratelimit.time, "monotonic", lambda: now[0])
    for _ in range(5):
        assert ratelimit.hit("forgot:x", limit=5, window_seconds=3600)
    assert not ratelimit.hit("forgot:x", limit=5, window_seconds=3600)

    now[0] += 601          # past the upload window, well inside the hour
    assert ratelimit.hit("handoff-upload:1.2.3.4", limit=20, window_seconds=600)
    assert not ratelimit.hit("forgot:x", limit=5, window_seconds=3600)
