"""POST /items/{id}/review — admin/owner curation workflow."""
import pytest


@pytest.fixture
def project(client, auth_headers) -> dict:
    r = client.post(
        "/api/v1/projects",
        json={"name": "P-review", "type": "pose_detection"},
        headers=auth_headers,
    )
    return r.json()


def _full_kps(n: int = 17) -> list[list[int]]:
    return [[i * 10, i * 10, 2] for i in range(n)]


def _make_done_item(client, project_id: int, headers: dict) -> int:
    """Bulk-create one item, annotate it fully, return its id (status=done)."""
    client.post(
        f"/api/v1/projects/{project_id}/items/bulk",
        json={"items": [{"payload": {"image_url": "/x.jpg"}}]},
        headers=headers,
    )
    iid = client.get(
        f"/api/v1/projects/{project_id}/items", headers=headers
    ).json()["items"][0]["id"]
    client.put(
        f"/api/v1/items/{iid}/annotation",
        json={"value": {"keypoints": _full_kps()}},
        headers=headers,
    )
    return iid


def test_approve_marks_reviewed(client, auth_headers, project):
    iid = _make_done_item(client, project["id"], auth_headers)
    r = client.post(
        f"/api/v1/items/{iid}/review",
        json={"approve": True},
        headers=auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "reviewed"
    assert body["review_note"] is None


def test_send_back_marks_in_progress_with_note(client, auth_headers, project):
    iid = _make_done_item(client, project["id"], auth_headers)
    r = client.post(
        f"/api/v1/items/{iid}/review",
        json={"approve": False, "note": "left ear off"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "in_progress"
    assert body["review_note"] == "left ear off"


def test_send_back_preserves_annotation(client, auth_headers, project):
    iid = _make_done_item(client, project["id"], auth_headers)
    client.post(
        f"/api/v1/items/{iid}/review",
        json={"approve": False, "note": "redo nose"},
        headers=auth_headers,
    )
    # Annotation should still be there — assignee refines, not redoes.
    detail = client.get(f"/api/v1/items/{iid}", headers=auth_headers).json()
    assert detail["annotation"] is not None
    assert detail["annotation"]["value"]["keypoints"] == _full_kps()


def test_approve_clears_prior_note(client, auth_headers, project):
    iid = _make_done_item(client, project["id"], auth_headers)
    client.post(
        f"/api/v1/items/{iid}/review",
        json={"approve": False, "note": "fix it"},
        headers=auth_headers,
    )
    # Re-save to bring back to done so approve is allowed.
    client.put(
        f"/api/v1/items/{iid}/annotation",
        json={"value": {"keypoints": _full_kps()}},
        headers=auth_headers,
    )
    r = client.post(
        f"/api/v1/items/{iid}/review",
        json={"approve": True},
        headers=auth_headers,
    )
    assert r.json()["status"] == "reviewed"
    assert r.json()["review_note"] is None


def test_send_back_with_no_note_clears_existing(client, auth_headers, project):
    iid = _make_done_item(client, project["id"], auth_headers)
    client.post(
        f"/api/v1/items/{iid}/review",
        json={"approve": False, "note": "first attempt"},
        headers=auth_headers,
    )
    # Send back again, without a note — old note should be cleared, not retained.
    client.put(
        f"/api/v1/items/{iid}/annotation",
        json={"value": {"keypoints": _full_kps()}},
        headers=auth_headers,
    )
    r = client.post(
        f"/api/v1/items/{iid}/review",
        json={"approve": False},
        headers=auth_headers,
    )
    assert r.json()["review_note"] is None


def test_approve_blocked_when_not_done(client, auth_headers, project):
    """Can't sign off on an item that isn't done yet."""
    client.post(
        f"/api/v1/projects/{project['id']}/items/bulk",
        json={"items": [{"payload": {"image_url": "/x.jpg"}}]},
        headers=auth_headers,
    )
    iid = client.get(
        f"/api/v1/projects/{project['id']}/items", headers=auth_headers
    ).json()["items"][0]["id"]
    r = client.post(
        f"/api/v1/items/{iid}/review",
        json={"approve": True},
        headers=auth_headers,
    )
    assert r.status_code == 409


def test_owner_can_review(client, auth_headers, project):
    """Project owner (alice here, even though she's an annotator role) can curate her own project."""
    iid = _make_done_item(client, project["id"], auth_headers)
    r = client.post(
        f"/api/v1/items/{iid}/review",
        json={"approve": True},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "reviewed"


def test_admin_can_review_any_project(client, auth_headers, admin_headers, project):
    iid = _make_done_item(client, project["id"], auth_headers)
    r = client.post(
        f"/api/v1/items/{iid}/review",
        json={"approve": True},
        headers=admin_headers,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "reviewed"


def test_non_owner_non_admin_cannot_review(
    client, auth_headers, second_user_headers, project
):
    iid = _make_done_item(client, project["id"], auth_headers)
    r = client.post(
        f"/api/v1/items/{iid}/review",
        json={"approve": True},
        headers=second_user_headers,
    )
    # Owner-gate returns 404 (hides existence) for unauthorized users.
    assert r.status_code == 404


def test_assignee_save_after_send_back_clears_note(client, auth_headers, project):
    """When annotator brings the item back to 'done' after a kickback, the
    review_note disappears — the feedback loop is closed."""
    iid = _make_done_item(client, project["id"], auth_headers)
    client.post(
        f"/api/v1/items/{iid}/review",
        json={"approve": False, "note": "wrong shoulder"},
        headers=auth_headers,
    )
    assert client.get(
        f"/api/v1/projects/{project['id']}/items", headers=auth_headers
    ).json()["items"][0]["review_note"] == "wrong shoulder"

    # Annotator re-saves complete keypoints → status=done, note cleared.
    client.put(
        f"/api/v1/items/{iid}/annotation",
        json={"value": {"keypoints": _full_kps()}},
        headers=auth_headers,
    )
    items = client.get(
        f"/api/v1/projects/{project['id']}/items", headers=auth_headers
    ).json()["items"]
    assert items[0]["status"] == "done"
    assert items[0]["review_note"] is None


def test_approve_all_done_marks_only_done(client, auth_headers, project):
    """Bulk approve sweeps every 'done' item and skips others (pending,
    in_progress, already-reviewed)."""
    pid = project["id"]
    # 3 items: leave one pending, fully annotate two.
    client.post(
        f"/api/v1/projects/{pid}/items/bulk",
        json={
            "items": [
                {"payload": {"image_url": "/a.jpg"}},
                {"payload": {"image_url": "/b.jpg"}},
                {"payload": {"image_url": "/c.jpg"}},
            ]
        },
        headers=auth_headers,
    )
    items = client.get(
        f"/api/v1/projects/{pid}/items", headers=auth_headers
    ).json()["items"]
    # Annotate first two fully, leave third pending.
    for it in items[:2]:
        client.put(
            f"/api/v1/items/{it['id']}/annotation",
            json={"value": {"keypoints": _full_kps()}},
            headers=auth_headers,
        )

    r = client.post(
        f"/api/v1/projects/{pid}/items/approve-all-done",
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json() == {"approved": 2}

    statuses = sorted(
        i["status"]
        for i in client.get(
            f"/api/v1/projects/{pid}/items", headers=auth_headers
        ).json()["items"]
    )
    assert statuses == ["pending", "reviewed", "reviewed"]


def test_approve_all_done_filtered_by_source_video(client, auth_headers, project):
    pid = project["id"]
    client.post(
        f"/api/v1/projects/{pid}/items/bulk",
        json={
            "items": [
                {"payload": {"image_url": "/v1-1.jpg", "source_video": "v1.mp4"}},
                {"payload": {"image_url": "/v1-2.jpg", "source_video": "v1.mp4"}},
                {"payload": {"image_url": "/v2-1.jpg", "source_video": "v2.mp4"}},
            ]
        },
        headers=auth_headers,
    )
    items = client.get(
        f"/api/v1/projects/{pid}/items", headers=auth_headers
    ).json()["items"]
    for it in items:
        client.put(
            f"/api/v1/items/{it['id']}/annotation",
            json={"value": {"keypoints": _full_kps()}},
            headers=auth_headers,
        )

    r = client.post(
        f"/api/v1/projects/{pid}/items/approve-all-done?source_video=v1.mp4",
        headers=auth_headers,
    )
    assert r.json() == {"approved": 2}

    by_video = {
        i["payload"]["source_video"]: i["status"]
        for i in client.get(
            f"/api/v1/projects/{pid}/items", headers=auth_headers
        ).json()["items"]
    }
    # v1 frames are reviewed, v2 stays at done.
    assert by_video["v1.mp4"] == "reviewed"
    assert by_video["v2.mp4"] == "done"


def test_approve_all_done_requires_owner_or_admin(
    client, auth_headers, second_user_headers, project
):
    iid = _make_done_item(client, project["id"], auth_headers)
    assert iid  # silence unused var
    r = client.post(
        f"/api/v1/projects/{project['id']}/items/approve-all-done",
        headers=second_user_headers,
    )
    assert r.status_code == 404


def test_partial_save_after_send_back_keeps_note(client, auth_headers, project):
    """A partial save (still in_progress) shouldn't drop the note — annotator
    is mid-fix, the prompt should stay until they finish."""
    iid = _make_done_item(client, project["id"], auth_headers)
    client.post(
        f"/api/v1/items/{iid}/review",
        json={"approve": False, "note": "redo eye"},
        headers=auth_headers,
    )
    partial = [[0, 0, 0]] * 17
    partial[0] = [10, 10, 2]
    client.put(
        f"/api/v1/items/{iid}/annotation",
        json={"value": {"keypoints": partial}},
        headers=auth_headers,
    )
    items = client.get(
        f"/api/v1/projects/{project['id']}/items", headers=auth_headers
    ).json()["items"]
    assert items[0]["status"] == "in_progress"
    assert items[0]["review_note"] == "redo eye"
