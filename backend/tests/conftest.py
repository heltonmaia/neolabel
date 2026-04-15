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


@pytest.fixture
def client() -> TestClient:
    from app.main import app

    return TestClient(app)


@pytest.fixture
def auth_headers(client) -> dict[str, str]:
    client.post(
        "/api/v1/auth/register",
        json={"username": "alice", "password": "secret123"},
    )
    r = client.post(
        "/api/v1/auth/login",
        data={"username": "alice", "password": "secret123"},
    )
    token = r.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def second_user_headers(client) -> dict[str, str]:
    client.post(
        "/api/v1/auth/register",
        json={"username": "bob", "password": "secret456"},
    )
    r = client.post(
        "/api/v1/auth/login",
        data={"username": "bob", "password": "secret456"},
    )
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
