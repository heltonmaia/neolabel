import io
import json
import struct
import zipfile

import pytest


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


@pytest.fixture
def project(client, auth_headers) -> dict:
    r = client.post(
        "/api/v1/projects",
        json={"name": "P-coco", "type": "pose_detection"},
        headers=auth_headers,
    )
    return r.json()


def _seed_pose_items(client, auth_headers, project, n):
    import os

    from app.core.config import settings

    for k in range(n):
        rel = f"projects/{project['id']}/frames/vid/f_{k:06d}.jpg"
        path = os.path.join(settings.DATA_DIR, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as f:
            f.write(_tiny_jpeg(640, 480))
        client.post(
            f"/api/v1/projects/{project['id']}/items/bulk",
            json={"items": [{"payload": {"image_url": f"/files/{rel}"}}]},
            headers=auth_headers,
        )
    items = client.get(
        f"/api/v1/projects/{project['id']}/items?limit=500", headers=auth_headers
    ).json()["items"]
    kps = [[50 + i * 5, 60 + i * 5, 2] for i in range(16)] + [[600, 470, 1]]
    for it in items:
        client.put(
            f"/api/v1/items/{it['id']}/annotation",
            json={"value": {"keypoints": kps}},
            headers=auth_headers,
        )


def test_build_coco_export_structure(client, auth_headers, project):
    from app.services import coco_export

    _seed_pose_items(client, auth_headers, project, 3)
    doc = json.loads(coco_export.build_coco_export(project["id"]))

    assert set(doc.keys()) == {"images", "annotations", "categories"}
    assert len(doc["images"]) == 3
    assert len(doc["annotations"]) == 3

    img_ids = [im["id"] for im in doc["images"]]
    ann_ids = [a["id"] for a in doc["annotations"]]
    assert all(i > 0 for i in img_ids + ann_ids)
    assert len(set(img_ids)) == 3 and len(set(ann_ids)) == 3

    for a in doc["annotations"]:
        assert len(a["keypoints"]) == 51
        assert len(a["bbox"]) == 4
        assert a["id"] != a["image_id"]
        assert a["category_id"] == 1
        assert a["iscrowd"] == 0
        assert a["num_keypoints"] == 17

    cats = doc["categories"]
    assert cats[0]["id"] == 1 and cats[0]["name"] == "person"
    assert len(cats[0]["keypoints"]) == 17
    assert cats[0]["keypoints"][0] == "nose"
    assert cats[0]["skeleton"][0] == [16, 14]


def test_build_coco_export_absolute_pixels(client, auth_headers, project):
    from app.services import coco_export

    _seed_pose_items(client, auth_headers, project, 1)
    doc = json.loads(coco_export.build_coco_export(project["id"]))
    kp = doc["annotations"][0]["keypoints"]
    xs = kp[0::3]
    assert max(xs) == 600
    assert all(0 <= x <= 640 for x in xs)


def test_build_coco_export_loads_with_pycocotools(client, auth_headers, project, tmp_path):
    from pycocotools.coco import COCO

    from app.services import coco_export

    _seed_pose_items(client, auth_headers, project, 2)
    p = tmp_path / "annotations.json"
    p.write_bytes(coco_export.build_coco_export(project["id"]))
    coco = COCO(str(p))
    assert len(coco.getImgIds()) == 2
    assert len(coco.getAnnIds()) == 2


def test_coco_split_matches_yolo_split(client, auth_headers, project):
    from app.services import coco_export
    from app.services import item as item_service

    _seed_pose_items(client, auth_headers, project, 10)

    cstream, _ = coco_export.build_coco_split_export(
        project["id"], train=70, val=20, test=10, seed=42
    )
    try:
        czf = zipfile.ZipFile(io.BytesIO(cstream.read()))
    finally:
        cstream.close()
    coco_map = {}
    for name in czf.namelist():
        split = name[: -len(".json")]
        doc = json.loads(czf.read(name))
        for im in doc["images"]:
            coco_map[im["file_name"]] = split

    ystream, _ = item_service.build_yolo_split_export(
        project["id"], train=70, val=20, test=10, seed=42
    )
    try:
        yzf = zipfile.ZipFile(io.BytesIO(ystream.read()))
    finally:
        ystream.close()
    yolo_map = {}
    for name in yzf.namelist():
        if name.startswith("images/"):
            _, split, fname = name.split("/", 2)
            yolo_map[fname] = split

    assert coco_map == yolo_map
    assert len(coco_map) == 10


def test_export_coco_endpoint(client, auth_headers, project):
    _seed_pose_items(client, auth_headers, project, 2)
    r = client.get(
        f"/api/v1/projects/{project['id']}/export?format=coco",
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert "application/json" in r.headers["content-type"]
    assert "project_%d_coco.json" % project["id"] in r.headers["content-disposition"]
    doc = json.loads(r.content)
    assert set(doc.keys()) == {"images", "annotations", "categories"}
    assert len(doc["images"]) == 2


def test_export_coco_split_endpoint(client, auth_headers, project):
    _seed_pose_items(client, auth_headers, project, 10)
    r = client.get(
        f"/api/v1/projects/{project['id']}/export"
        "?format=coco_split&train=70&val=20&test=10&seed=42",
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert "application/zip" in r.headers["content-type"]
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert set(names) == {"train.json", "val.json", "test.json"}


def test_export_coco_rejects_rodent(client, auth_headers):
    r = client.post(
        "/api/v1/projects",
        json={"name": "rodent-p", "type": "pose_detection", "keypoint_schema": "rodent"},
        headers=auth_headers,
    )
    rid = r.json()["id"]
    r1 = client.get(f"/api/v1/projects/{rid}/export?format=coco", headers=auth_headers)
    r2 = client.get(f"/api/v1/projects/{rid}/export?format=coco_split", headers=auth_headers)
    assert r1.status_code == 422
    assert r2.status_code == 422
