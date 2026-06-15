"""Tests for the raw-image ZIP importer (POST /projects/{id}/import-images).

Unlike the assignment tests, these exercise the real ffmpeg resize path so we
can assert that imported frames land at 640x640 just like video frames. Test
images are generated with ffmpeg's lavfi source and probed back with ffprobe;
both binaries are a hard dependency of the feature anyway.
"""
from __future__ import annotations

import io
import subprocess
import zipfile

import pytest


# --- helpers ---------------------------------------------------------------

def _img_bytes(w: int, h: int, color: str = "red", fmt: str = "mjpeg") -> bytes:
    """A real JPEG/PNG of size w x h via ffmpeg, returned as bytes (no temp file)."""
    cmd = [
        "ffmpeg", "-v", "error",
        "-f", "lavfi", "-i", f"color=c={color}:s={w}x{h}",
        "-frames:v", "1", "-f", "image2pipe", "-vcodec", fmt, "-",
    ]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode())
    return r.stdout


def _zip(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _probe_size(path) -> tuple[int, int]:
    r = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path),
        ],
        capture_output=True, text=True,
    )
    w, h = r.stdout.strip().split(",")
    return int(w), int(h)


def _frames_dir(data_dir, project_id: int, source: str):
    return data_dir / "projects" / str(project_id) / "frames" / source


# --- fixtures --------------------------------------------------------------

@pytest.fixture
def pose_project(client, admin_headers) -> dict:
    r = client.post(
        "/api/v1/projects",
        json={"name": "img-proj", "type": "pose_detection"},
        headers=admin_headers,
    )
    return r.json()


def _post_images(client, headers, project_id, zip_bytes, **data):
    return client.post(
        f"/api/v1/projects/{project_id}/import-images",
        files={"file": ("photos.zip", zip_bytes, "application/zip")},
        data={k: str(v) for k, v in data.items()},
        headers=headers,
    )


# --- tests -----------------------------------------------------------------

def test_imports_images_as_pending_640_frames(
    client, admin_headers, pose_project, _isolated_data_dir
):
    z = _zip({
        "a.jpg": _img_bytes(320, 240),
        "b.jpg": _img_bytes(800, 600),
        "c.png": _img_bytes(100, 400, fmt="png"),
    })
    r = _post_images(client, admin_headers, pose_project["id"], z)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["items_created"] == 3
    assert body["source_video"] == "photos"

    # every imported item is a pending frame in the "photos" group
    items = client.get(
        f"/api/v1/projects/{pose_project['id']}/items", headers=admin_headers
    ).json()["items"]
    assert len(items) == 3
    assert all(i["status"] == "pending" for i in items)
    assert all(i["payload"]["source_video"] == "photos" for i in items)
    assert sorted(i["payload"]["frame_index"] for i in items) == [1, 2, 3]

    # frames are physically 640x640 on disk (always re-encoded to .jpg)
    fdir = _frames_dir(_isolated_data_dir, pose_project["id"], "photos")
    frames = sorted(fdir.glob("f_*.jpg"))
    assert len(frames) == 3
    for f in frames:
        assert _probe_size(f) == (640, 640)


def test_imported_items_carry_assignee(client, admin_headers, pose_project):
    from app.schemas.user import UserRole
    from app.services import user as user_service

    user_service.ensure_seed_user("mate", "secret", UserRole.annotator)
    uid = next(
        u["id"] for u in client.get("/api/v1/users", headers=admin_headers).json()
        if u["username"] == "mate"
    )

    z = _zip({"a.jpg": _img_bytes(320, 240), "b.jpg": _img_bytes(320, 240)})
    r = _post_images(client, admin_headers, pose_project["id"], z, assignee_id=uid)
    assert r.status_code == 201, r.text

    items = client.get(
        f"/api/v1/projects/{pose_project['id']}/items", headers=admin_headers
    ).json()["items"]
    assert len(items) == 2
    assert all(i["assigned_to"] == uid for i in items)


def test_rejects_non_pose_project(client, admin_headers):
    seg = client.post(
        "/api/v1/projects",
        json={"name": "seg", "type": "image_segmentation"},
        headers=admin_headers,
    ).json()
    z = _zip({"a.jpg": _img_bytes(320, 240)})
    r = _post_images(client, admin_headers, seg["id"], z)
    assert r.status_code == 400
    assert "pose_detection" in r.json()["detail"]


def test_rejects_non_admin(client, admin_headers, auth_headers, pose_project):
    z = _zip({"a.jpg": _img_bytes(320, 240)})
    r = _post_images(client, auth_headers, pose_project["id"], z)
    assert r.status_code == 403


def test_empty_file_rejected(client, admin_headers, pose_project):
    r = _post_images(client, admin_headers, pose_project["id"], b"")
    assert r.status_code == 400
    assert "Empty" in r.json()["detail"]


def test_corrupt_zip_rejected(client, admin_headers, pose_project):
    r = _post_images(client, admin_headers, pose_project["id"], b"not a zip at all")
    assert r.status_code == 400
    assert "valid ZIP" in r.json()["detail"]


def test_no_images_rejected(client, admin_headers, pose_project):
    z = _zip({"notes.txt": b"hello", "data.csv": b"1,2,3"})
    r = _post_images(client, admin_headers, pose_project["id"], z)
    assert r.status_code == 400
    assert "No images" in r.json()["detail"]


def test_nested_folders_flatten_into_one_group(client, admin_headers, pose_project):
    z = _zip({
        "sub/dir/a.jpg": _img_bytes(320, 240),
        "other/b.png": _img_bytes(320, 240, fmt="png"),
        "c.jpg": _img_bytes(320, 240),
    })
    r = _post_images(client, admin_headers, pose_project["id"], z)
    assert r.status_code == 201, r.text
    assert r.json()["items_created"] == 3
    items = client.get(
        f"/api/v1/projects/{pose_project['id']}/items", headers=admin_headers
    ).json()["items"]
    assert {i["payload"]["source_video"] for i in items} == {"photos"}


def test_non_image_files_skipped_and_counted(client, admin_headers, pose_project):
    z = _zip({
        "a.jpg": _img_bytes(320, 240),
        "notes.txt": b"hello",
        "readme.md": b"x",
    })
    r = _post_images(client, admin_headers, pose_project["id"], z)
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["items_created"] == 1
    assert body["skipped_files"] == 2


def test_stretch_mode_accepted_invalid_rejected(client, admin_headers, pose_project):
    z = _zip({"a.jpg": _img_bytes(320, 240)})
    ok = _post_images(client, admin_headers, pose_project["id"], z, resize_mode="stretch")
    assert ok.status_code == 201, ok.text
    assert ok.json()["resize_mode"] == "stretch"

    z2 = _zip({"a.jpg": _img_bytes(320, 240)})
    bad = _post_images(client, admin_headers, pose_project["id"], z2, resize_mode="weird")
    assert bad.status_code == 400


def test_reupload_continues_frame_index(client, admin_headers, pose_project):
    first = _post_images(
        client, admin_headers, pose_project["id"],
        _zip({"a.jpg": _img_bytes(320, 240), "b.jpg": _img_bytes(320, 240)}),
    )
    assert first.status_code == 201, first.text
    second = _post_images(
        client, admin_headers, pose_project["id"],
        _zip({"c.jpg": _img_bytes(320, 240), "d.jpg": _img_bytes(320, 240)}),
    )
    assert second.status_code == 201, second.text
    assert second.json()["source_video"] == "photos"

    items = client.get(
        f"/api/v1/projects/{pose_project['id']}/items", headers=admin_headers
    ).json()["items"]
    assert sorted(i["payload"]["frame_index"] for i in items) == [1, 2, 3, 4]
