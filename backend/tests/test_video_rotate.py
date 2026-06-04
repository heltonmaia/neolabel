"""Video rotation — coordinate transform + endpoint."""
import subprocess
from pathlib import Path

import pytest

from app.core import storage
from app.services import video as video_service
from app.services.item import _jpeg_size
from app.services.video import rotate_keypoints


def test_rotate_90_clockwise_maps_point_and_swaps_dims():
    # point (10, 20) in a 100w x 200h image
    kps = [[10, 20, 2]]
    new_kps, w, h = rotate_keypoints(kps, 100, 200, 90)
    assert new_kps == [[180, 10, 2]]  # x'=h-y=180, y'=x=10
    assert (w, h) == (200, 100)


def test_rotate_270_counter_clockwise():
    new_kps, w, h = rotate_keypoints([[10, 20, 2]], 100, 200, 270)
    assert new_kps == [[20, 90, 2]]  # x'=y=20, y'=w-x=90
    assert (w, h) == (200, 100)


def test_rotate_180_keeps_dims():
    new_kps, w, h = rotate_keypoints([[10, 20, 2]], 100, 200, 180)
    assert new_kps == [[90, 180, 2]]  # x'=w-x=90, y'=h-y=180
    assert (w, h) == (100, 200)


def test_unset_keypoints_are_untouched():
    # v == 0 means "unset" ([0,0,0]); must not be moved.
    new_kps, _, _ = rotate_keypoints([[0, 0, 0], [10, 20, 2]], 100, 200, 90)
    assert new_kps[0] == [0, 0, 0]


def test_four_90_rotations_return_original_square():
    kps = [[100, 50, 2], [600, 10, 1]]
    cur, w, h = kps, 640, 640
    for _ in range(4):
        cur, w, h = rotate_keypoints(cur, w, h, 90)
    assert cur == kps
    assert (w, h) == (640, 640)


def _make_frame(pdir: Path, video: str, w: int, h: int):
    """Render one solid-color non-square JPG into the video's frames dir."""
    frames_dir = pdir / "frames" / video
    frames_dir.mkdir(parents=True, exist_ok=True)
    out = frames_dir / "f_000001.jpg"
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi",
         "-i", f"color=c=red:s={w}x{h}", "-frames:v", "1", str(out)],
        check=True,
    )
    return out


def test_rotate_video_swaps_dims_and_transforms_annotation():
    pid = storage.next_id("projects")
    storage.save_project({
        "id": pid, "name": "rot", "type": "pose_detection",
        "owner_id": 1, "created_at": "2026-06-04T00:00:00Z",
    })
    pdir = storage.project_dir(pid)
    frame_path = _make_frame(pdir, "clip", 320, 240)
    assert _jpeg_size(frame_path) == (320, 240)

    iid = storage.next_id("items")
    storage.save_item({
        "id": iid, "project_id": pid,
        "payload": {"image_url": f"/files/projects/{pid}/frames/clip/f_000001.jpg",
                    "source_video": "clip", "frame_index": 1,
                    "width": 320, "height": 240},
        "status": "done", "created_at": "2026-06-04T00:00:00Z", "assigned_to": 1,
    })
    storage.save_annotation(pid, {
        "id": storage.next_id("annotations"), "item_id": iid, "annotator_id": 1,
        "value": {"keypoints": [[50, 60, 2], [0, 0, 0]]},
        "created_at": "2026-06-04T00:00:00Z", "updated_at": "2026-06-04T00:00:00Z",
    })

    n = video_service.rotate_video(pid, "clip", 90)
    assert n == 1

    item = storage.load_item(pid, iid)
    assert (item["payload"]["width"], item["payload"]["height"]) == (240, 320)
    assert item["payload"]["frame_rev"] == 1
    assert _jpeg_size(frame_path) == (240, 320)

    ann = storage.find_any_annotation_for_item(pid, iid)
    # 90° CW in 320x240: (50,60) -> (h-y, x) = (180, 50); unset stays [0,0,0]
    assert ann["value"]["keypoints"] == [[180, 50, 2], [0, 0, 0]]


def test_rotate_video_missing_video_returns_zero():
    pid = storage.next_id("projects")
    storage.save_project({
        "id": pid, "name": "rot2", "type": "pose_detection",
        "owner_id": 1, "created_at": "2026-06-04T00:00:00Z",
    })
    assert video_service.rotate_video(pid, "nope", 90) == 0


def test_rotate_video_rejects_bad_degrees():
    pid = storage.next_id("projects")
    storage.save_project({
        "id": pid, "name": "rot3", "type": "pose_detection",
        "owner_id": 1, "created_at": "2026-06-04T00:00:00Z",
    })
    with pytest.raises(ValueError):
        video_service.rotate_video(pid, "clip", 45)


def test_rotate_video_180_keeps_dims_and_bumps_rev():
    pid = storage.next_id("projects")
    storage.save_project({
        "id": pid, "name": "rot180", "type": "pose_detection",
        "owner_id": 1, "created_at": "2026-06-04T00:00:00Z",
    })
    pdir = storage.project_dir(pid)
    frame_path = _make_frame(pdir, "clip", 320, 240)
    iid = storage.next_id("items")
    storage.save_item({
        "id": iid, "project_id": pid,
        "payload": {"image_url": f"/files/projects/{pid}/frames/clip/f_000001.jpg",
                    "source_video": "clip", "frame_index": 1,
                    "width": 320, "height": 240},
        "status": "done", "created_at": "2026-06-04T00:00:00Z", "assigned_to": 1,
    })
    storage.save_annotation(pid, {
        "id": storage.next_id("annotations"), "item_id": iid, "annotator_id": 1,
        "value": {"keypoints": [[50, 60, 2]]},
        "created_at": "2026-06-04T00:00:00Z", "updated_at": "2026-06-04T00:00:00Z",
    })

    n = video_service.rotate_video(pid, "clip", 180)
    assert n == 1

    item = storage.load_item(pid, iid)
    assert (item["payload"]["width"], item["payload"]["height"]) == (320, 240)
    assert item["payload"]["frame_rev"] == 1
    assert _jpeg_size(frame_path) == (320, 240)
    ann = storage.find_any_annotation_for_item(pid, iid)
    # 180° in 320x240: (50,60) -> (w-x, h-y) = (270, 180)
    assert ann["value"]["keypoints"] == [[270, 180, 2]]


def test_rotate_video_ffmpeg_failure_leaves_originals_untouched(monkeypatch):
    pid = storage.next_id("projects")
    storage.save_project({
        "id": pid, "name": "rotfail", "type": "pose_detection",
        "owner_id": 1, "created_at": "2026-06-04T00:00:00Z",
    })
    pdir = storage.project_dir(pid)
    frame_path = _make_frame(pdir, "clip", 320, 240)
    iid = storage.next_id("items")
    storage.save_item({
        "id": iid, "project_id": pid,
        "payload": {"image_url": f"/files/projects/{pid}/frames/clip/f_000001.jpg",
                    "source_video": "clip", "frame_index": 1,
                    "width": 320, "height": 240},
        "status": "done", "created_at": "2026-06-04T00:00:00Z", "assigned_to": 1,
    })
    storage.save_annotation(pid, {
        "id": storage.next_id("annotations"), "item_id": iid, "annotator_id": 1,
        "value": {"keypoints": [[50, 60, 2]]},
        "created_at": "2026-06-04T00:00:00Z", "updated_at": "2026-06-04T00:00:00Z",
    })

    def _fail(*args, **kwargs):
        return subprocess.CompletedProcess(args[0] if args else [], 1, "", "boom")
    monkeypatch.setattr(video_service.subprocess, "run", _fail)

    with pytest.raises(RuntimeError):
        video_service.rotate_video(pid, "clip", 90)

    # Originals untouched: dims unchanged, no frame_rev, annotation not transformed.
    assert _jpeg_size(frame_path) == (320, 240)
    item = storage.load_item(pid, iid)
    assert "frame_rev" not in item["payload"]
    assert (item["payload"]["width"], item["payload"]["height"]) == (320, 240)
    ann = storage.find_any_annotation_for_item(pid, iid)
    assert ann["value"]["keypoints"] == [[50, 60, 2]]


@pytest.fixture
def pose_project(client, admin_headers) -> dict:
    r = client.post(
        "/api/v1/projects",
        json={"name": "rot-http", "type": "pose_detection"},
        headers=admin_headers,
    )
    return r.json()


def _seed_video_frame(pid: int, video: str, w: int, h: int) -> int:
    pdir = storage.project_dir(pid)
    _make_frame(pdir, video, w, h)
    iid = storage.next_id("items")
    storage.save_item({
        "id": iid, "project_id": pid,
        "payload": {"image_url": f"/files/projects/{pid}/frames/{video}/f_000001.jpg",
                    "source_video": video, "frame_index": 1, "width": w, "height": h},
        "status": "done", "created_at": "2026-06-04T00:00:00Z", "assigned_to": 1,
    })
    return iid


def test_rotate_endpoint_admin_ok(client, admin_headers, pose_project):
    pid = pose_project["id"]
    _seed_video_frame(pid, "clip", 320, 240)
    r = client.post(
        f"/api/v1/projects/{pid}/videos/clip/rotate",
        json={"degrees": 90}, headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"rotated": 1, "degrees": 90}


def test_rotate_endpoint_404_when_no_frames(client, admin_headers, pose_project):
    pid = pose_project["id"]
    r = client.post(
        f"/api/v1/projects/{pid}/videos/ghost/rotate",
        json={"degrees": 90}, headers=admin_headers,
    )
    assert r.status_code == 404


def test_rotate_endpoint_422_bad_degrees(client, admin_headers, pose_project):
    pid = pose_project["id"]
    _seed_video_frame(pid, "clip", 320, 240)
    r = client.post(
        f"/api/v1/projects/{pid}/videos/clip/rotate",
        json={"degrees": 45}, headers=admin_headers,
    )
    assert r.status_code == 422


def test_rotate_endpoint_forbidden_for_non_admin(client, auth_headers, admin_headers):
    # Project owned by a non-admin; that owner still can't rotate (admin-only).
    pid = client.post(
        "/api/v1/projects",
        json={"name": "owned", "type": "pose_detection"},
        headers=auth_headers,
    ).json()["id"]
    _seed_video_frame(pid, "clip", 320, 240)
    r = client.post(
        f"/api/v1/projects/{pid}/videos/clip/rotate",
        json={"degrees": 90}, headers=auth_headers,
    )
    assert r.status_code == 403
