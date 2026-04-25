"""Tests for admin-only video distribution / per-user assignments.

The project owner here is the admin; annotators can only see frames that were
assigned to them via video upload or reassign.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services import item as item_service


@pytest.fixture
def admin_project(client, admin_headers) -> dict:
    r = client.post(
        "/api/v1/projects",
        json={"name": "admin-proj", "type": "pose_detection"},
        headers=admin_headers,
    )
    return r.json()


@pytest.fixture
def neuro_headers(client) -> dict[str, str]:
    from app.schemas.user import UserRole
    from app.services import user as user_service

    user_service.ensure_seed_user("neuromate1", "secret", UserRole.annotator)
    r = client.post("/api/v1/auth/login", data={"username": "neuromate1", "password": "secret"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
def neuro2_headers(client) -> dict[str, str]:
    from app.schemas.user import UserRole
    from app.services import user as user_service

    user_service.ensure_seed_user("neuromate2", "secret", UserRole.annotator)
    r = client.post("/api/v1/auth/login", data={"username": "neuromate2", "password": "secret"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _neuro_id(client, admin_headers, username: str) -> int:
    users = client.get("/api/v1/users", headers=admin_headers).json()
    return next(u["id"] for u in users if u["username"] == username)


def _fake_extract(pid, _source, _name, _fps, rotation=0, assignee_id=None, resize_mode="pad"):
    """Bypass ffmpeg: create 3 frames directly through the item service."""
    from app.core import storage
    from app.schemas.item import ItemStatus

    for i in range(1, 4):
        iid = storage.next_id("items")
        storage.save_item(
            {
                "id": iid,
                "project_id": pid,
                "payload": {
                    "image_url": f"/files/projects/{pid}/frames/clip/f_{i:06d}.jpg",
                    "source_video": "clip",
                    "frame_index": i,
                },
                "status": ItemStatus.pending.value,
                "created_at": "2026-01-01T00:00:00Z",
                "assigned_to": assignee_id,
            }
        )
    return {"video": "clip", "frames": 3}


def test_video_upload_rejects_annotator(
    client, neuro_headers, admin_project, admin_headers
):
    # Even if the annotator somehow reaches the endpoint, assignee_id + admin check guards it.
    n1 = _neuro_id(client, admin_headers, "neuromate1")
    r = client.post(
        f"/api/v1/projects/{admin_project['id']}/videos",
        files={"file": ("v.mp4", b"dummy", "video/mp4")},
        data={"fps": "1", "assignee_id": str(n1)},
        headers=neuro_headers,
    )
    assert r.status_code == 403


def test_video_upload_without_assignee_ok(client, admin_headers, admin_project):
    with patch("app.api.v1.videos.video_service.extract_frames", side_effect=_fake_extract):
        r = client.post(
            f"/api/v1/projects/{admin_project['id']}/videos",
            files={"file": ("v.mp4", b"dummy", "video/mp4")},
            data={"fps": "1"},
            headers=admin_headers,
        )
    assert r.status_code == 201
    items = client.get(
        f"/api/v1/projects/{admin_project['id']}/items", headers=admin_headers
    ).json()["items"]
    assert items and all(i["assigned_to"] is None for i in items)


def test_video_upload_rejects_unknown_assignee(client, admin_headers, admin_project):
    r = client.post(
        f"/api/v1/projects/{admin_project['id']}/videos",
        files={"file": ("v.mp4", b"dummy", "video/mp4")},
        data={"fps": "1", "assignee_id": "99999"},
        headers=admin_headers,
    )
    assert r.status_code == 400


def test_upload_assigns_frames_to_user(
    client, admin_headers, admin_project, neuro_headers, neuro2_headers
):
    n1 = _neuro_id(client, admin_headers, "neuromate1")
    with patch("app.api.v1.videos.video_service.extract_frames", side_effect=_fake_extract):
        r = client.post(
            f"/api/v1/projects/{admin_project['id']}/videos",
            files={"file": ("v.mp4", b"dummy", "video/mp4")},
            data={"fps": "1", "assignee_id": str(n1)},
            headers=admin_headers,
        )
    assert r.status_code == 201
    assert r.json() == {"video": "clip", "frames": 3}

    # neuromate1 sees all 3 frames; neuromate2 sees none.
    r1 = client.get(f"/api/v1/projects/{admin_project['id']}/items", headers=neuro_headers)
    assert r1.json()["total"] == 3
    assert all(i["assigned_to"] == n1 for i in r1.json()["items"])

    # neuromate2 can't even see the project (no assignments)
    r2 = client.get(f"/api/v1/projects/{admin_project['id']}/items", headers=neuro2_headers)
    assert r2.status_code == 404


def test_annotator_cannot_access_unassigned_item(
    client, admin_headers, admin_project, neuro_headers, neuro2_headers
):
    n1 = _neuro_id(client, admin_headers, "neuromate1")
    with patch("app.api.v1.videos.video_service.extract_frames", side_effect=_fake_extract):
        client.post(
            f"/api/v1/projects/{admin_project['id']}/videos",
            files={"file": ("v.mp4", b"dummy", "video/mp4")},
            data={"fps": "1", "assignee_id": str(n1)},
            headers=admin_headers,
        )
    # Grab one of neuromate1's items
    iid = client.get(
        f"/api/v1/projects/{admin_project['id']}/items", headers=neuro_headers
    ).json()["items"][0]["id"]

    # neuromate2 cannot see or annotate it
    assert client.get(f"/api/v1/items/{iid}", headers=neuro2_headers).status_code == 404
    r = client.put(
        f"/api/v1/items/{iid}/annotation",
        json={"value": {"keypoints": [[0, 0, 0]] * 17}},
        headers=neuro2_headers,
    )
    assert r.status_code == 404


def test_admin_reassigns_video(
    client, admin_headers, admin_project, neuro_headers, neuro2_headers
):
    n1 = _neuro_id(client, admin_headers, "neuromate1")
    n2 = _neuro_id(client, admin_headers, "neuromate2")
    with patch("app.api.v1.videos.video_service.extract_frames", side_effect=_fake_extract):
        client.post(
            f"/api/v1/projects/{admin_project['id']}/videos",
            files={"file": ("v.mp4", b"dummy", "video/mp4")},
            data={"fps": "1", "assignee_id": str(n1)},
            headers=admin_headers,
        )
    r = client.patch(
        f"/api/v1/projects/{admin_project['id']}/videos/clip/assign",
        json={"assignee_id": n2},
        headers=admin_headers,
    )
    assert r.status_code == 200
    assert r.json() == {"reassigned": 3, "assignee_id": n2}

    # Now neuromate1 sees nothing; neuromate2 sees all 3.
    assert client.get(
        f"/api/v1/projects/{admin_project['id']}/items", headers=neuro_headers
    ).status_code == 404
    assert client.get(
        f"/api/v1/projects/{admin_project['id']}/items", headers=neuro2_headers
    ).json()["total"] == 3


def test_admin_reassigns_video_to_none(
    client, admin_headers, admin_project, neuro_headers
):
    n1 = _neuro_id(client, admin_headers, "neuromate1")
    with patch("app.api.v1.videos.video_service.extract_frames", side_effect=_fake_extract):
        client.post(
            f"/api/v1/projects/{admin_project['id']}/videos",
            files={"file": ("v.mp4", b"dummy", "video/mp4")},
            data={"fps": "1", "assignee_id": str(n1)},
            headers=admin_headers,
        )
    r = client.patch(
        f"/api/v1/projects/{admin_project['id']}/videos/clip/assign",
        json={"assignee_id": None},
        headers=admin_headers,
    )
    assert r.status_code == 200
    assert r.json() == {"reassigned": 3, "assignee_id": None}
    # neuromate1 no longer sees the project.
    assert client.get(
        f"/api/v1/projects/{admin_project['id']}/items", headers=neuro_headers
    ).status_code == 404


def test_admin_deletes_video(
    client, admin_headers, admin_project, neuro_headers, _isolated_data_dir
):
    n1 = _neuro_id(client, admin_headers, "neuromate1")
    with patch("app.api.v1.videos.video_service.extract_frames", side_effect=_fake_extract):
        client.post(
            f"/api/v1/projects/{admin_project['id']}/videos",
            files={"file": ("v.mp4", b"dummy", "video/mp4")},
            data={"fps": "1", "assignee_id": str(n1)},
            headers=admin_headers,
        )
    # Seed a fake source video file + frames dir to verify disk cleanup.
    pdir = _isolated_data_dir / "projects" / str(admin_project["id"])
    (pdir / "_videos").mkdir(parents=True, exist_ok=True)
    (pdir / "_videos" / "clip.mp4").write_bytes(b"dummy")
    (pdir / "frames" / "clip").mkdir(parents=True, exist_ok=True)
    (pdir / "frames" / "clip" / "extra.jpg").write_bytes(b"x")

    r = client.delete(
        f"/api/v1/projects/{admin_project['id']}/videos/clip", headers=admin_headers
    )
    assert r.status_code == 200
    assert r.json() == {"deleted": 3}

    # Items gone; disk artifacts gone.
    r2 = client.get(f"/api/v1/projects/{admin_project['id']}/items", headers=admin_headers)
    assert r2.json()["total"] == 0
    assert not (pdir / "_videos" / "clip.mp4").exists()
    assert not (pdir / "frames" / "clip").exists()


def test_delete_video_requires_admin(
    client, admin_headers, admin_project, neuro_headers
):
    n1 = _neuro_id(client, admin_headers, "neuromate1")
    with patch("app.api.v1.videos.video_service.extract_frames", side_effect=_fake_extract):
        client.post(
            f"/api/v1/projects/{admin_project['id']}/videos",
            files={"file": ("v.mp4", b"dummy", "video/mp4")},
            data={"fps": "1", "assignee_id": str(n1)},
            headers=admin_headers,
        )
    r = client.delete(
        f"/api/v1/projects/{admin_project['id']}/videos/clip", headers=neuro_headers
    )
    assert r.status_code == 403


def test_delete_unknown_video_404(client, admin_headers, admin_project):
    r = client.delete(
        f"/api/v1/projects/{admin_project['id']}/videos/ghost", headers=admin_headers
    )
    assert r.status_code == 404


def test_reassign_requires_admin(client, admin_project, neuro_headers, admin_headers):
    n1 = _neuro_id(client, admin_headers, "neuromate1")
    r = client.patch(
        f"/api/v1/projects/{admin_project['id']}/videos/clip/assign",
        json={"assignee_id": n1},
        headers=neuro_headers,
    )
    assert r.status_code == 403


def test_list_videos_admin_overview(
    client, admin_headers, admin_project, neuro_headers
):
    n1 = _neuro_id(client, admin_headers, "neuromate1")
    with patch("app.api.v1.videos.video_service.extract_frames", side_effect=_fake_extract):
        client.post(
            f"/api/v1/projects/{admin_project['id']}/videos",
            files={"file": ("v.mp4", b"dummy", "video/mp4")},
            data={"fps": "1", "assignee_id": str(n1)},
            headers=admin_headers,
        )
    r = client.get(f"/api/v1/projects/{admin_project['id']}/videos", headers=admin_headers)
    assert r.status_code == 200
    videos = r.json()
    assert len(videos) == 1
    assert videos[0]["source_video"] == "clip"
    assert videos[0]["frames"] == 3
    assert videos[0]["assigned_to"] == n1


def test_assigned_project_shows_up_in_user_listing(
    client, admin_headers, admin_project, neuro_headers
):
    n1 = _neuro_id(client, admin_headers, "neuromate1")
    # Before assignment: annotator sees nothing.
    assert client.get("/api/v1/projects", headers=neuro_headers).json() == []
    with patch("app.api.v1.videos.video_service.extract_frames", side_effect=_fake_extract):
        client.post(
            f"/api/v1/projects/{admin_project['id']}/videos",
            files={"file": ("v.mp4", b"dummy", "video/mp4")},
            data={"fps": "1", "assignee_id": str(n1)},
            headers=admin_headers,
        )
    projs = client.get("/api/v1/projects", headers=neuro_headers).json()
    assert [p["id"] for p in projs] == [admin_project["id"]]


def test_annotator_filter_is_forced_to_self(
    client, admin_headers, admin_project, neuro_headers, neuro2_headers
):
    """?assigned_to= is ignored for non-admin — they only see their own assignments."""
    n1 = _neuro_id(client, admin_headers, "neuromate1")
    n2 = _neuro_id(client, admin_headers, "neuromate2")
    with patch("app.api.v1.videos.video_service.extract_frames", side_effect=_fake_extract):
        client.post(
            f"/api/v1/projects/{admin_project['id']}/videos",
            files={"file": ("v.mp4", b"dummy", "video/mp4")},
            data={"fps": "1", "assignee_id": str(n1)},
            headers=admin_headers,
        )
        # Upload again so neuromate2 has assignments (reset counter name by service).
        client.post(
            f"/api/v1/projects/{admin_project['id']}/videos",
            files={"file": ("v2.mp4", b"dummy", "video/mp4")},
            data={"fps": "1", "assignee_id": str(n2)},
            headers=admin_headers,
        )

    # neuromate1 can't peek at neuromate2's items even with ?assigned_to=n2.
    r = client.get(
        f"/api/v1/projects/{admin_project['id']}/items?assigned_to={n2}",
        headers=neuro_headers,
    )
    assert r.status_code == 200
    assert all(i["assigned_to"] == n1 for i in r.json()["items"])
