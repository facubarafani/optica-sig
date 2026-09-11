"""Test fixtures. Uses an in-memory SQLite DB — no Postgres required."""
from __future__ import annotations

import os

# Configure environment BEFORE importing the app (settings is cached on import).
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key-0123456789abcdef0123456789")
# Capture mail instead of sending it. Set before app import, because settings
# is cached at import time.
#
# Forced, not setdefault: a developer with EMAIL_BACKEND=smtp exported — or who
# simply sourced .env — would otherwise have the test suite mail real people at
# whatever addresses the fixtures happen to use. The test suite must never be
# able to send, whatever the ambient environment says.
os.environ["EMAIL_BACKEND"] = "memory"
os.environ["PUBLIC_BASE_URL"] = "https://test.sgi"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import app.models  # noqa: E402,F401  (populate metadata)
from app.core.config import settings  # noqa: E402
from app.core.database import Base, get_db  # noqa: E402
from app.core import ratelimit  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.services import email as email_service  # noqa: E402
from app.main import app  # noqa: E402
from app.models.auth import Permission, User  # noqa: E402
from app.models.company import Company, CompanySettings  # noqa: E402
from app.models.platform import PlatformUser  # noqa: E402
from app.services.provisioning import PERMISSIONS  # noqa: E402

# A single shared in-memory connection across the whole test session.
engine = create_engine(
    "sqlite+pysqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
    future=True,
)
TestingSessionLocal = sessionmaker(
    bind=engine, autoflush=False, autocommit=False, future=True
)


def _override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = _override_get_db


@pytest.fixture(autouse=True)
def _fresh_state():
    """Both of these are process-global, so they leak between tests otherwise."""
    email_service.outbox.clear()
    ratelimit.reset()
    yield


@pytest.fixture
def outbox():
    return email_service.outbox


@pytest.fixture(autouse=True)
def _fresh_db():
    """Recreate the schema and a minimal seed (company + admin) per test."""
    Base.metadata.create_all(engine)
    db = TestingSessionLocal()
    company = Company(id=settings.default_company_id, name="Test Co", currency="ARS")
    db.add(company)
    db.flush()
    db.add(CompanySettings(company_id=company.id))
    for code, name in PERMISSIONS:
        db.add(Permission(code=code, name=name))
    db.add(
        User(
            company_id=company.id,
            email="admin@test.com",
            full_name="Admin",
            hashed_password=hash_password("admin1234"),
            is_superuser=True,
        )
    )
    # The provider account lives in its own table, so /admin has something to
    # authenticate and the isolation tests have a real cross-tenant identity.
    db.add(
        PlatformUser(
            email="owner@test.com",
            full_name="Platform Owner",
            hashed_password=hash_password("owner1234"),
        )
    )
    db.commit()
    db.close()
    yield
    Base.metadata.drop_all(engine)


@pytest.fixture
def db():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers(client):
    resp = client.post(
        "/api/auth/login",
        json={"email": "admin@test.com", "password": "admin1234"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
def platform_headers(client):
    resp = client.post(
        "/api/admin/login",
        json={"email": "owner@test.com", "password": "owner1234"},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
def product_type_id(client, auth_headers):
    resp = client.post(
        "/api/product-types", json={"name": "Armazones"}, headers=auth_headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.fixture
def branch_id(client, auth_headers):
    resp = client.post(
        "/api/branches", json={"name": "Central", "code": "MAIN"}, headers=auth_headers
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.fixture
def product_id(client, auth_headers, product_type_id):
    resp = client.post(
        "/api/products",
        json={"code": "P-1", "description": "Test product",
              "product_type_id": product_type_id,
              "current_cost": "100.00", "min_stock": "1"},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.fixture
def brand_id(client, auth_headers):
    resp = client.post("/api/brands", json={"name": "Vulk"}, headers=auth_headers)
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


@pytest.fixture
def supplier_id(client, auth_headers):
    resp = client.post(
        "/api/suppliers",
        json={"name": "Distribuidora SA", "supplier_type": "merchandise"},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]
