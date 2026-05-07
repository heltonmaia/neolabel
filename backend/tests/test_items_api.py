import json
import struct

import pytest


def _tiny_jpeg(width: int, height: int) -> bytes:
    """Produce a minimal SOI+SOF0+EOI JPEG blob — enough for _jpeg_size()."""
    sof0 = (
        b"\xff\xc0"
        + struct.pack(">H", 11)      # segment length
        + b"\x08"                    # precision
        + struct.pack(">H", height)
        + struct.pack(">H", width)
        + b"\x01\x01\x11\x00"        # 1 component
    )
    return b"\xff\xd8" + sof0 + b"\xff\xd9"


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


def test_out_of_frame_keypoints_count_as_addressed(
    client, auth_headers, project
):
    """Pose items reach `done` when every keypoint is either labeled (v>0) or
    explicitly marked out-of-frame via the parallel `out_of_frame` array."""
    client.post(
        f"/api/v1/projects/{project['id']}/items/bulk",
        json={"items": [{"payload": {"image_url": "/x.jpg"}}]},
        headers=auth_headers,
    )
    iid = client.get(
        f"/api/v1/projects/{project['id']}/items", headers=auth_headers
    ).json()["items"][0]["id"]

    # 16 keypoints placed, 1 left as [0,0,0] without an OOF flag → still in_progress.
    kps = [[i * 10, i * 10, 2] for i in range(16)] + [[0, 0, 0]]
    client.put(
        f"/api/v1/items/{iid}/annotation",
        json={"value": {"keypoints": kps}},
        headers=auth_headers,
    )
    item = client.get(f"/api/v1/items/{iid}", headers=auth_headers).json()
    assert item["status"] == "in_progress"

    # Same shape, but with out_of_frame[16]=true → addressed → done.
    oof = [False] * 16 + [True]
    client.put(
        f"/api/v1/items/{iid}/annotation",
        json={"value": {"keypoints": kps, "out_of_frame": oof}},
        headers=auth_headers,
    )
    item = client.get(f"/api/v1/items/{iid}", headers=auth_headers).json()
    assert item["status"] == "done"
    # Saved annotation round-trips both fields.
    assert item["annotation"]["value"]["keypoints"][16] == [0, 0, 0]
    assert item["annotation"]["value"]["out_of_frame"][16] is True


def test_legacy_annotation_without_out_of_frame_still_works(
    client, auth_headers, project
):
    """Pre-existing annotations omit the `out_of_frame` field; the v>0 rule
    still decides done/in_progress, so historical data behaves unchanged."""
    client.post(
        f"/api/v1/projects/{project['id']}/items/bulk",
        json={"items": [{"payload": {"image_url": "/x.jpg"}}]},
        headers=auth_headers,
    )
    iid = client.get(
        f"/api/v1/projects/{project['id']}/items", headers=auth_headers
    ).json()["items"][0]["id"]

    full = [[i * 10, i * 10, 2] for i in range(17)]
    client.put(
        f"/api/v1/items/{iid}/annotation",
        json={"value": {"keypoints": full}},
        headers=auth_headers,
    )
    item = client.get(f"/api/v1/items/{iid}", headers=auth_headers).json()
    assert item["status"] == "done"


def test_export_yolo_zip_contains_dataset(client, auth_headers, project, tmp_path):
    import io
    import zipfile

    # Create a minimal JPEG so _jpeg_size returns real dims
    img_path = tmp_path / "projects" / str(project["id"]) / "frames" / "vid" / "f_000001.jpg"
    img_path.parent.mkdir(parents=True, exist_ok=True)
    img_path.write_bytes(_tiny_jpeg(640, 480))

    client.post(
        f"/api/v1/projects/{project['id']}/items/bulk",
        json={
            "items": [
                {"payload": {"image_url": "/files/projects/"
                             f"{project['id']}/frames/vid/f_000001.jpg"}}
            ]
        },
        headers=auth_headers,
    )
    iid = client.get(
        f"/api/v1/projects/{project['id']}/items", headers=auth_headers
    ).json()["items"][0]["id"]
    full = [[10 + i * 5, 20 + i * 5, 2] for i in range(17)]
    client.put(
        f"/api/v1/items/{iid}/annotation",
        json={"value": {"keypoints": full}},
        headers=auth_headers,
    )

    r = client.get(
        f"/api/v1/projects/{project['id']}/export?format=yolo", headers=auth_headers
    )
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"

    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = zf.namelist()
    assert "data.yaml" in names
    image_entry = next((n for n in names if n.startswith("images/train/")), None)
    assert image_entry is not None, "YOLO export must bundle the source frames"
    # The image bytes must be the actual JPG (starts with the SOI marker), not
    # a placeholder or truncated copy — guards against the streaming refactor
    # accidentally dropping image payloads.
    img_bytes = zf.read(image_entry)
    assert img_bytes == _tiny_jpeg(640, 480)
    assert any(n.startswith("labels/train/") and n.endswith(".txt") for n in names)
    # The yaml must NOT pin `path:` — Ultralytics resolves missing `path`
    # against the yaml file's own parent directory, which is the only
    # CWD-independent behaviour for an extracted export.
    yaml_text = zf.read("data.yaml").decode()
    assert "path:" not in yaml_text
    label_file = next(n for n in names if n.startswith("labels/train/"))
    line = zf.read(label_file).decode().strip().split()
    # class + 4 bbox + 17*3 keypoints = 56 fields
    assert len(line) == 1 + 4 + 17 * 3
    assert line[0] == "0"


def test_export_bundle_ships_annotations_and_images(client, auth_headers, project, tmp_path):
    import io
    import zipfile

    frames_dir = tmp_path / "projects" / str(project["id"]) / "frames" / "vid"
    frames_dir.mkdir(parents=True, exist_ok=True)
    (frames_dir / "f_000001.jpg").write_bytes(_tiny_jpeg(320, 240))
    (frames_dir / "f_000002.jpg").write_bytes(_tiny_jpeg(320, 240))

    client.post(
        f"/api/v1/projects/{project['id']}/items/bulk",
        json={
            "items": [
                {"payload": {"image_url": f"/files/projects/{project['id']}/frames/vid/f_000001.jpg"}},
                {"payload": {"image_url": f"/files/projects/{project['id']}/frames/vid/f_000002.jpg"}},
            ]
        },
        headers=auth_headers,
    )
    item_ids = [
        i["id"]
        for i in client.get(
            f"/api/v1/projects/{project['id']}/items", headers=auth_headers
        ).json()["items"]
    ]
    full = [[i * 10, i * 10, 2] for i in range(17)]
    # Annotate only the first item; leave the second pending.
    client.put(
        f"/api/v1/items/{item_ids[0]}/annotation",
        json={"value": {"keypoints": full}},
        headers=auth_headers,
    )

    r = client.get(
        f"/api/v1/projects/{project['id']}/export?format=bundle",
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert "_bundle.zip" in r.headers["content-disposition"]

    zf = zipfile.ZipFile(io.BytesIO(r.content))
    names = set(zf.namelist())
    assert "annotations.json" in names
    assert "README.txt" in names
    image_entries = [n for n in names if n.startswith("images/")]
    # Both frames ship even though only one item is annotated — the bundle
    # is a full project snapshot, not a training dataset.
    assert len(image_entries) == 2

    rows = json.loads(zf.read("annotations.json"))
    assert len(rows) == 2
    assert any(r_["annotation"] is None for r_ in rows)
    # image_url is rewritten to the archive-relative path so the bundle is
    # self-contained and portable.
    for r_ in rows:
        url = r_["payload"]["image_url"]
        assert url.startswith("images/")
        assert url in names


def test_clear_annotation_resets_status(client, auth_headers, project):
    client.post(
        f"/api/v1/projects/{project['id']}/items/bulk",
        json={"items": [{"payload": {"text": "a"}}]},
        headers=auth_headers,
    )
    iid = client.get(
        f"/api/v1/projects/{project['id']}/items", headers=auth_headers
    ).json()["items"][0]["id"]
    full = [[i * 10, i * 10, 2] for i in range(17)]
    client.put(
        f"/api/v1/items/{iid}/annotation",
        json={"value": {"keypoints": full}},
        headers=auth_headers,
    )
    assert client.get(f"/api/v1/items/{iid}", headers=auth_headers).json()["status"] == "done"

    r = client.delete(f"/api/v1/items/{iid}/annotation", headers=auth_headers)
    assert r.status_code == 204

    detail = client.get(f"/api/v1/items/{iid}", headers=auth_headers).json()
    assert detail["status"] == "pending"
    assert detail["annotation"] is None


def test_delete_item(client, auth_headers, project):
    client.post(
        f"/api/v1/projects/{project['id']}/items/bulk",
        json={"items": [{"payload": {"text": "a"}}, {"payload": {"text": "b"}}]},
        headers=auth_headers,
    )
    items = client.get(
        f"/api/v1/projects/{project['id']}/items", headers=auth_headers
    ).json()["items"]
    target = items[0]["id"]

    r = client.delete(f"/api/v1/items/{target}", headers=auth_headers)
    assert r.status_code == 204

    remaining = client.get(
        f"/api/v1/projects/{project['id']}/items", headers=auth_headers
    ).json()
    assert remaining["total"] == 1
    assert all(i["id"] != target for i in remaining["items"])


def test_delete_item_blocked_for_other_user(
    client, auth_headers, second_user_headers, project
):
    client.post(
        f"/api/v1/projects/{project['id']}/items/bulk",
        json={"items": [{"payload": {"text": "a"}}]},
        headers=auth_headers,
    )
    iid = client.get(
        f"/api/v1/projects/{project['id']}/items", headers=auth_headers
    ).json()["items"][0]["id"]

    r = client.delete(f"/api/v1/items/{iid}", headers=second_user_headers)
    assert r.status_code == 404


def test_delete_annotated_requires_admin(client, auth_headers, admin_headers, project):
    client.post(
        f"/api/v1/projects/{project['id']}/items/bulk",
        json={"items": [{"payload": {"text": "a"}}, {"payload": {"text": "b"}}]},
        headers=auth_headers,
    )
    items = client.get(
        f"/api/v1/projects/{project['id']}/items", headers=auth_headers
    ).json()["items"]
    full = [[i * 10, i * 10, 2] for i in range(17)]
    client.put(
        f"/api/v1/items/{items[0]['id']}/annotation",
        json={"value": {"keypoints": full}},
        headers=auth_headers,
    )

    # Annotator is forbidden
    r = client.post(
        f"/api/v1/projects/{project['id']}/items/delete-annotated", headers=auth_headers
    )
    assert r.status_code == 403

    # Admin can do it
    r = client.post(
        f"/api/v1/projects/{project['id']}/items/delete-annotated", headers=admin_headers
    )
    assert r.status_code == 200
    assert r.json() == {"deleted": 1}

    left = client.get(
        f"/api/v1/projects/{project['id']}/items", headers=auth_headers
    ).json()
    assert left["total"] == 1
    assert left["items"][0]["id"] == items[1]["id"]


def test_export_rejects_invalid_format(client, auth_headers, project):
    r = client.get(
        f"/api/v1/projects/{project['id']}/export?format=xml", headers=auth_headers
    )
    assert r.status_code == 422
