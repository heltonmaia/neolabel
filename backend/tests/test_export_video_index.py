import csv
import io
import os
import struct
import zipfile

import pytest


def test_frame_ref():
    from app.services.item import _frame_ref

    assert _frame_ref(
        {"image_url": "/files/projects/1/frames/v/f_000003.jpg", "source_video": "v"}
    ) == ("v", "f_000003")
    # image_url present but no source_video -> empty bucket
    assert _frame_ref({"image_url": "/files/x/y/f_000001.jpg"}) == ("", "f_000001")
    # no frame referenced
    assert _frame_ref({"source_video": "v"}) is None
    assert _frame_ref({}) is None


def test_video_index_csv_numeric():
    from app.services.item import build_video_index_csv

    pairs = [
        ("vid_a", "f_000000"),
        ("vid_a", "f_000002"),
        ("vid_b", "f_000005"),
        ("vid_a", "f_000001"),
    ]
    rows = list(csv.DictReader(io.StringIO(build_video_index_csv(pairs))))
    # order = first appearance; first/last numeric; count = frames present
    assert rows[0] == {
        "source_video": "vid_a",
        "first_frame": "0",
        "last_frame": "2",
        "num_frames": "3",
    }
    assert rows[1] == {
        "source_video": "vid_b",
        "first_frame": "5",
        "last_frame": "5",
        "num_frames": "1",
    }


def test_video_index_csv_fallback_and_empty_bucket():
    from app.services.item import build_video_index_csv

    # non-"f_<digits>" stems fall back to the raw stem (lexicographic)
    rows = list(csv.DictReader(io.StringIO(build_video_index_csv([("", "img_7"), ("", "img_3")]))))
    assert rows[0]["source_video"] == ""
    assert rows[0]["first_frame"] == "img_3"
    assert rows[0]["last_frame"] == "img_7"
    assert rows[0]["num_frames"] == "2"


def test_zip_bytes_roundtrip():
    from app.services.item import zip_bytes

    stream, size = zip_bytes([("a.txt", b"hello"), ("b.csv", b"x,y\n")])
    try:
        zf = zipfile.ZipFile(io.BytesIO(stream.read()))
    finally:
        stream.close()
    assert zf.read("a.txt") == b"hello"
    assert zf.read("b.csv") == b"x,y\n"
    assert size > 0


def _tiny_jpeg(width: int, height: int) -> bytes:
    sof0 = (
        b"\xff\xc0"
        + struct.pack(">H", 11)
        + b"\x08"
        + struct.pack(">H", height)
        + struct.pack(">H", width)
        + b"\x01\x01\x11\x00"
    )
    return b"\xff\xd8" + sof0 + b"\xff\xd9"


# 17 infant keypoints: 16 visible (v=2) + 1 occluded (v=1).
_KPS = [[50 + i * 5, 60 + i * 5, 2] for i in range(16)] + [[600, 470, 1]]


@pytest.fixture
def pose_project(client, auth_headers) -> dict:
    r = client.post(
        "/api/v1/projects",
        json={"name": "P-vindex", "type": "pose_detection"},
        headers=auth_headers,
    )
    return r.json()


def _seed_frames(client, auth_headers, pid: int, video: str, indices: list[int]) -> None:
    """Create a frame JPG + item (payload.source_video=video) for each index."""
    from app.core.config import settings

    for k in indices:
        rel = f"projects/{pid}/frames/{video}/f_{k:06d}.jpg"
        path = os.path.join(settings.DATA_DIR, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(_tiny_jpeg(640, 480))
        client.post(
            f"/api/v1/projects/{pid}/items/bulk",
            json={"items": [{"payload": {"image_url": f"/files/{rel}", "source_video": video}}]},
            headers=auth_headers,
        )


def _all_items(client, auth_headers, pid: int) -> list[dict]:
    return client.get(
        f"/api/v1/projects/{pid}/items?limit=500", headers=auth_headers
    ).json()["items"]


def _annotate(client, auth_headers, items: list[dict]) -> None:
    for it in items:
        client.put(
            f"/api/v1/items/{it['id']}/annotation",
            json={"value": {"keypoints": _KPS}},
            headers=auth_headers,
        )


def _index_rows(zf: zipfile.ZipFile) -> dict[str, dict]:
    text = zf.read("video_index.csv").decode("utf-8")
    return {r["source_video"]: r for r in csv.DictReader(io.StringIO(text))}


def test_yolo_video_index(client, auth_headers, pose_project):
    from app.services import item as item_service

    pid = pose_project["id"]
    _seed_frames(client, auth_headers, pid, "vid_a", [0, 1, 2, 5])
    _seed_frames(client, auth_headers, pid, "vid_b", [3, 7])
    _annotate(client, auth_headers, _all_items(client, auth_headers, pid))

    stream, _ = item_service.build_yolo_export(pid, video_index=True)
    try:
        zf = zipfile.ZipFile(io.BytesIO(stream.read()))
    finally:
        stream.close()

    assert "video_index.csv" in zf.namelist()
    rows = _index_rows(zf)
    # vid_a created [0,1,2,5] -> first=0 last=5 count=4 (count < range; gaps OK)
    assert rows["vid_a"] == {
        "source_video": "vid_a",
        "first_frame": "0",
        "last_frame": "5",
        "num_frames": "4",
    }
    assert rows["vid_b"] == {
        "source_video": "vid_b",
        "first_frame": "3",
        "last_frame": "7",
        "num_frames": "2",
    }
    # sum of counts == number of label files written
    n_labels = sum(1 for n in zf.namelist() if n.startswith("labels/train/"))
    assert n_labels == 6


def test_yolo_no_flag_has_no_index(client, auth_headers, pose_project):
    from app.services import item as item_service

    pid = pose_project["id"]
    _seed_frames(client, auth_headers, pid, "vid_a", [0, 1])
    _annotate(client, auth_headers, _all_items(client, auth_headers, pid))

    stream, _ = item_service.build_yolo_export(pid)
    try:
        names = zipfile.ZipFile(io.BytesIO(stream.read())).namelist()
    finally:
        stream.close()
    assert "video_index.csv" not in names


def test_yolo_split_still_builds(client, auth_headers, pose_project):
    # Guards the widened _yolo_records tuple unpack in the split builder.
    from app.services import item as item_service

    pid = pose_project["id"]
    _seed_frames(client, auth_headers, pid, "vid_a", [0, 1, 2, 3, 4, 5, 6, 7, 8, 9])
    _annotate(client, auth_headers, _all_items(client, auth_headers, pid))

    stream, _ = item_service.build_yolo_split_export(pid, train=70, val=20, test=10, seed=42)
    try:
        names = zipfile.ZipFile(io.BytesIO(stream.read())).namelist()
    finally:
        stream.close()
    assert any(n.startswith("images/train/") for n in names)
    assert "video_index.csv" not in names


def test_bundle_video_index(client, auth_headers, pose_project):
    from app.services import item as item_service

    pid = pose_project["id"]
    _seed_frames(client, auth_headers, pid, "vid_a", [0, 1, 4])
    _seed_frames(client, auth_headers, pid, "vid_b", [2])
    # bundle includes ALL items (annotation optional); annotate only some
    items = _all_items(client, auth_headers, pid)
    _annotate(client, auth_headers, items[:2])

    stream, _ = item_service.build_bundle_export(pid, video_index=True)
    try:
        zf = zipfile.ZipFile(io.BytesIO(stream.read()))
    finally:
        stream.close()

    assert "video_index.csv" in zf.namelist()
    rows = _index_rows(zf)
    # all 4 items counted regardless of annotation status
    assert rows["vid_a"] == {
        "source_video": "vid_a",
        "first_frame": "0",
        "last_frame": "4",
        "num_frames": "3",
    }
    assert rows["vid_b"]["num_frames"] == "1"


def test_build_text_export_zip_json(client, auth_headers, pose_project):
    import json as _json

    from app.services import item as item_service

    pid = pose_project["id"]
    _seed_frames(client, auth_headers, pid, "vid_a", [0, 1])
    _seed_frames(client, auth_headers, pid, "vid_b", [4])
    _annotate(client, auth_headers, _all_items(client, auth_headers, pid))

    stream, _ = item_service.build_text_export_zip(pid, "json")
    try:
        zf = zipfile.ZipFile(io.BytesIO(stream.read()))
    finally:
        stream.close()

    assert set(zf.namelist()) == {f"project_{pid}.json", "video_index.csv"}
    # inner json equals the streamed body
    inner = zf.read(f"project_{pid}.json")
    streamed = b"".join(item_service.iter_export_json(pid))
    assert inner == streamed
    body = _json.loads(inner)
    assert len(body) == 3
    rows = _index_rows(zf)
    assert rows["vid_a"]["num_frames"] == "2"
    assert rows["vid_b"]["num_frames"] == "1"


def test_build_text_export_zip_csv(client, auth_headers, pose_project):
    from app.services import item as item_service

    pid = pose_project["id"]
    _seed_frames(client, auth_headers, pid, "vid_a", [0])
    _annotate(client, auth_headers, _all_items(client, auth_headers, pid))

    stream, _ = item_service.build_text_export_zip(pid, "csv")
    try:
        zf = zipfile.ZipFile(io.BytesIO(stream.read()))
    finally:
        stream.close()
    assert set(zf.namelist()) == {f"project_{pid}.csv", "video_index.csv"}
    assert zf.read(f"project_{pid}.csv") == b"".join(item_service.iter_export_csv(pid))
