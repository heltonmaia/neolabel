"""Video rotation — coordinate transform + endpoint."""
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


import subprocess
from pathlib import Path

import pytest

from app.core import storage
from app.services import video as video_service


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


def test_rotate_video_swaps_dims_and_transforms_annotation(tmp_path):
    pid = storage.next_id("projects")
    storage.save_project({
        "id": pid, "name": "rot", "type": "pose_detection",
        "owner_id": 1, "created_at": "2026-06-04T00:00:00Z",
    })
    pdir = storage.project_dir(pid)
    frame_path = _make_frame(pdir, "clip", 320, 240)
    assert video_service._jpeg_size_for_test(frame_path) == (320, 240)

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
    assert video_service._jpeg_size_for_test(frame_path) == (240, 320)

    ann = storage.find_any_annotation_for_item(pid, iid)
    # 90° CW in 320x240: (50,60) -> (h-y, x) = (180, 50); unset stays [0,0,0]
    assert ann["value"]["keypoints"] == [[180, 50, 2], [0, 0, 0]]


def test_rotate_video_missing_video_returns_zero(tmp_path):
    pid = storage.next_id("projects")
    storage.save_project({
        "id": pid, "name": "rot2", "type": "pose_detection",
        "owner_id": 1, "created_at": "2026-06-04T00:00:00Z",
    })
    assert video_service.rotate_video(pid, "nope", 90) == 0


def test_rotate_video_rejects_bad_degrees(tmp_path):
    pid = storage.next_id("projects")
    storage.save_project({
        "id": pid, "name": "rot3", "type": "pose_detection",
        "owner_id": 1, "created_at": "2026-06-04T00:00:00Z",
    })
    with pytest.raises(ValueError):
        video_service.rotate_video(pid, "clip", 45)
