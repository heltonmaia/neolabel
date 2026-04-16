def _create(client, headers, **overrides) -> dict:
    body = {"name": "P1", "type": "pose_detection", **overrides}
    r = client.post("/api/v1/projects", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()


def test_create_and_get_project(client, auth_headers):
    p = _create(client, auth_headers)
    assert p["id"] >= 1
    assert p["name"] == "P1"
    assert p["type"] == "pose_detection"
    assert p["labels"] == []

    r = client.get(f"/api/v1/projects/{p['id']}", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["id"] == p["id"]


def test_list_only_returns_own_projects(client, auth_headers, second_user_headers):
    _create(client, auth_headers, name="mine")
    _create(client, second_user_headers, name="theirs")
    r = client.get("/api/v1/projects", headers=auth_headers)
    assert [p["name"] for p in r.json()] == ["mine"]


def test_cannot_access_other_users_project(client, auth_headers, second_user_headers):
    p = _create(client, auth_headers)
    r = client.get(f"/api/v1/projects/{p['id']}", headers=second_user_headers)
    assert r.status_code == 404  # not 403 — don't leak existence


def test_update_project(client, auth_headers):
    p = _create(client, auth_headers)
    r = client.patch(
        f"/api/v1/projects/{p['id']}",
        json={"name": "renamed"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["name"] == "renamed"


def test_delete_project_requires_admin(client, auth_headers, admin_headers):
    p = _create(client, auth_headers)
    # Owner (annotator) is forbidden
    r = client.delete(f"/api/v1/projects/{p['id']}", headers=auth_headers)
    assert r.status_code == 403
    # Admin can delete
    r = client.delete(f"/api/v1/projects/{p['id']}", headers=admin_headers)
    assert r.status_code == 204
    assert client.get(f"/api/v1/projects/{p['id']}", headers=auth_headers).status_code == 404


def test_delete_project_404_admin_unknown_id(client, admin_headers):
    r = client.delete("/api/v1/projects/99999", headers=admin_headers)
    assert r.status_code == 404


def test_projects_endpoint_requires_auth(client):
    assert client.get("/api/v1/projects").status_code == 401


def test_invalid_project_type_rejected(client, auth_headers):
    r = client.post(
        "/api/v1/projects",
        json={"name": "x", "type": "nonsense"},
        headers=auth_headers,
    )
    assert r.status_code == 422
