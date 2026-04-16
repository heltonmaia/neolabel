def test_register_endpoint_removed(client):
    # Public registration is disabled — users are provisioned via seed_users.json.
    r = client.post(
        "/api/v1/auth/register",
        json={"username": "alice", "password": "secret123"},
    )
    assert r.status_code == 404


def test_login_returns_bearer_token(client, auth_headers):
    r = client.post(
        "/api/v1/auth/login",
        data={"username": "alice", "password": "secret123"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["access_token"]
    assert body["token_type"].lower() == "bearer"


def test_login_wrong_password(client, auth_headers):
    r = client.post(
        "/api/v1/auth/login",
        data={"username": "alice", "password": "wrong"},
    )
    assert r.status_code == 401


def test_me_requires_auth(client):
    assert client.get("/api/v1/auth/me").status_code == 401


def test_me_returns_current_user(client, auth_headers):
    r = client.get("/api/v1/auth/me", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["username"] == "alice"


def test_me_rejects_garbage_token(client):
    r = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401
