import json

import pytest


@pytest.fixture
def project(client, auth_headers) -> dict:
    r = client.post(
        "/api/v1/projects",
        json={"name": "P1", "type": "pose_detection"},
        headers=auth_headers,
    )
    return r.json()


def test_bulk_upload_creates_items(client, auth_headers, project):
    r = client.post(
        f"/api/v1/projects/{project['id']}/items/bulk",
        json={"items": [{"payload": {"text": "a"}}, {"payload": {"text": "b"}}]},
        headers=auth_headers,
    )
    assert r.status_code == 201
    assert r.json() == {"created": 2}

    r = client.get(f"/api/v1/projects/{project['id']}/items", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2


def test_bulk_upload_isolated_per_project(client, auth_headers, second_user_headers, project):
    # Second user's project
    r = client.post(
        "/api/v1/projects",
        json={"name": "other", "type": "pose_detection"},
        headers=second_user_headers,
    )
    other = r.json()

    client.post(
        f"/api/v1/projects/{project['id']}/items/bulk",
        json={"items": [{"payload": {"t": 1}}]},
        headers=auth_headers,
    )
    client.post(
        f"/api/v1/projects/{other['id']}/items/bulk",
        json={"items": [{"payload": {"t": 2}}, {"payload": {"t": 3}}]},
        headers=second_user_headers,
    )

    r1 = client.get(f"/api/v1/projects/{project['id']}/items", headers=auth_headers)
    r2 = client.get(f"/api/v1/projects/{other['id']}/items", headers=second_user_headers)
    assert r1.json()["total"] == 1
    assert r2.json()["total"] == 2


def test_bulk_upload_blocked_for_other_user(
    client, auth_headers, second_user_headers, project
):
    r = client.post(
        f"/api/v1/projects/{project['id']}/items/bulk",
        json={"items": [{"payload": {"t": 1}}]},
        headers=second_user_headers,
    )
    assert r.status_code == 404


def test_annotation_upsert_and_roundtrip(client, auth_headers, project):
    client.post(
        f"/api/v1/projects/{project['id']}/items/bulk",
        json={"items": [{"payload": {"text": "a"}}]},
        headers=auth_headers,
    )
    items = client.get(
        f"/api/v1/projects/{project['id']}/items", headers=auth_headers
    ).json()["items"]
    item_id = items[0]["id"]

    r = client.put(
        f"/api/v1/items/{item_id}/annotation",
        json={"value": {"label": "cat"}},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["value"] == {"label": "cat"}

    r = client.get(f"/api/v1/items/{item_id}", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["annotation"]["value"] == {"label": "cat"}


def test_annotation_updates_overwrite(client, auth_headers, project):
    client.post(
        f"/api/v1/projects/{project['id']}/items/bulk",
        json={"items": [{"payload": {"text": "a"}}]},
        headers=auth_headers,
    )
    iid = client.get(
        f"/api/v1/projects/{project['id']}/items", headers=auth_headers
    ).json()["items"][0]["id"]

    client.put(
        f"/api/v1/items/{iid}/annotation",
        json={"value": {"label": "cat"}},
        headers=auth_headers,
    )
    r = client.put(
        f"/api/v1/items/{iid}/annotation",
        json={"value": {"label": "dog"}},
        headers=auth_headers,
    )
    assert r.json()["value"] == {"label": "dog"}


def test_get_item_not_found(client, auth_headers):
    r = client.get("/api/v1/items/99999", headers=auth_headers)
    assert r.status_code == 404


def test_export_json(client, auth_headers, project):
    client.post(
        f"/api/v1/projects/{project['id']}/items/bulk",
        json={"items": [{"payload": {"text": "a"}}]},
        headers=auth_headers,
    )
    r = client.get(
        f"/api/v1/projects/{project['id']}/export?format=json", headers=auth_headers
    )
    assert r.status_code == 200
    rows = json.loads(r.content)
    assert len(rows) == 1
    assert rows[0]["payload"] == {"text": "a"}


def test_export_jsonl(client, auth_headers, project):
    client.post(
        f"/api/v1/projects/{project['id']}/items/bulk",
        json={"items": [{"payload": {"text": "a"}}, {"payload": {"text": "b"}}]},
        headers=auth_headers,
    )
    r = client.get(
        f"/api/v1/projects/{project['id']}/export?format=jsonl", headers=auth_headers
    )
    assert r.status_code == 200
    lines = r.text.strip().split("\n")
    assert len(lines) == 2
    assert all(json.loads(line)["payload"] for line in lines)


def test_export_csv(client, auth_headers, project):
    client.post(
        f"/api/v1/projects/{project['id']}/items/bulk",
        json={"items": [{"payload": {"text": "a"}}]},
        headers=auth_headers,
    )
    r = client.get(
        f"/api/v1/projects/{project['id']}/export?format=csv", headers=auth_headers
    )
    assert r.status_code == 200
    assert r.text.splitlines()[0] == "id,payload,status,annotation"


def test_pose_item_stays_in_progress_until_all_17_keypoints(
    client, auth_headers, project
):
    client.post(
        f"/api/v1/projects/{project['id']}/items/bulk",
        json={"items": [{"payload": {"image_url": "/x.jpg"}}]},
        headers=auth_headers,
    )
    iid = client.get(
        f"/api/v1/projects/{project['id']}/items", headers=auth_headers
    ).json()["items"][0]["id"]

    # Partial: only 3 keypoints placed
    partial = [[0, 0, 0]] * 17
    partial[0] = [100, 100, 2]
    partial[1] = [110, 90, 2]
    partial[2] = [120, 90, 1]
    client.put(
        f"/api/v1/items/{iid}/annotation",
        json={"value": {"keypoints": partial}},
        headers=auth_headers,
    )
    items = client.get(
        f"/api/v1/projects/{project['id']}/items", headers=auth_headers
    ).json()["items"]
    assert items[0]["status"] == "in_progress"

    # Complete: all 17 labeled (mix of visible/occluded both count)
    full = [[i * 10, i * 10, 2 if i % 2 == 0 else 1] for i in range(17)]
    client.put(
        f"/api/v1/items/{iid}/annotation",
        json={"value": {"keypoints": full}},
        headers=auth_headers,
    )
    items = client.get(
        f"/api/v1/projects/{project['id']}/items", headers=auth_headers
    ).json()["items"]
    assert items[0]["status"] == "done"


def test_export_rejects_invalid_format(client, auth_headers, project):
    r = client.get(
        f"/api/v1/projects/{project['id']}/export?format=xml", headers=auth_headers
    )
    assert r.status_code == 422
