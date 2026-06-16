"""Test fixtures. Uses an in-memory SQLite DB — no Postgres required."""
from __future__ import annotations

import os

# Configure environment BEFORE importing the app (settings is cached on import).
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "test-secret-key-0123456789abcdef0123456789")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

import app.models  # noqa: E402,F401  (populate metadata)
from app.core.config import settings  # noqa: E402
from app.core.database import Base, get_db  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.main import app  # noqa: E402
from app.models.auth import Permission, User  # noqa: E402
from app.models.company import Company, CompanySettings  # noqa: E402
from scripts.seed import PERMISSIONS  # noqa: E402

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
        json={"code": "P-1", "name": "Test product", "product_type_id": product_type_id,
              "current_cost": "100.00", "min_stock": "1"},
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]
