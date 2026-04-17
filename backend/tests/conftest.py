"""Shared fixtures.

Every test gets an isolated DATA_DIR (tmp_path) so tests never touch each other
or the developer's local ./data.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", str(tmp_path))
    yield tmp_path


@pytest.fixture(autouse=True)
def _disable_rate_limit():
    from app.core.ratelimit import limiter

    limiter.enabled = False
    yield
    limiter.enabled = True


@pytest.fixture
def client() -> TestClient:
    from app.main import app

    return TestClient(app)


def _seed_and_login(client, username: str, password: str, role: str = "annotator") -> dict:
    from app.schemas.user import UserRole
    from app.services import user as user_service

    user_service.ensure_seed_user(username, password, UserRole(role))
    r = client.post(
        "/api/v1/auth/login",
        data={"username": username, "password": password},
    )
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def auth_headers(client) -> dict[str, str]:
    return _seed_and_login(client, "alice", "secret123")


@pytest.fixture
def second_user_headers(client) -> dict[str, str]:
    return _seed_and_login(client, "bob", "secret456")


@pytest.fixture
def admin_headers(client) -> dict[str, str]:
    return _seed_and_login(client, "admin", "12345", role="admin")
