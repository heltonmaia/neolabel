# COCO Keypoints JSON export (ViTPose) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add COCO Keypoints JSON exporters (`coco` → single `annotations.json`, `coco_split` → ZIP of `train/val/test.json`) for infant pose projects, with splits guaranteed identical to the YOLO splits so YOLO and ViTPose are comparable.

**Architecture:** Extract two shared helpers in `item.py` (`eligible_pose_items` for the canonical ordered eligible-item stream, `partition_records` for the seeded floor partition) and refactor `_yolo_records` / `build_yolo_split_export` onto them without changing YOLO output. A new `coco_export.py` service builds COCO docs over the same helpers, so the same `seed/ratios` yield the same per-frame split. The export endpoint gains `coco`/`coco_split` formats with an infant-only 422 guard.

**Tech Stack:** Python 3.12 / FastAPI / Pydantic v2 (backend), pytest + httpx TestClient + pycocotools (test-only) (tests), React 18 + TypeScript + Tailwind (frontend).

**Reference spec:** `docs/superpowers/specs/2026-05-30-coco-keypoints-export-design.md`

**Branch:** all work on `feat/coco-export` (controller creates it before Task 1; do not commit to `main`).

---

## Background the engineer needs

- Pose keypoints are stored in **COCO-17 order already** and visibility is the **COCO 0/1/2 convention natively** (`0`=not labeled/OOF `[0,0,0]`, `1`=occluded, `2`=visible). No reordering, identity visibility mapping.
- Coordinates are stored in the **annotated frame's pixel resolution**; `_jpeg_size(src)` returns that resolution. So keypoints are already absolute pixels and `images[].width/height = _jpeg_size`.
- The YOLO export names a frame `f"{item['id']:06d}_{src.stem}{src.suffix}"` (e.g. `000726_f_000002.jpg`). COCO `file_name` uses the **same** string so frames line up across datasets.
- Splits are computed at export time (no persistent split). The YOLO split shuffles the eligible-record list with `random.Random(seed)` then partitions by floor. COCO reuses the exact same routine and ordering → identical assignment for the same params.
- Backend tests run **inside the container as a module**: `docker compose exec -T backend python -m pytest tests/<file>::<test> -v` (always `-T`, always `python -m pytest`). The dev stack is up; pytest/ruff are installed in the container.
- Lint **scoped to changed files**: `ruff check <files>` / `ruff format <files>` — never `ruff format backend`. A pre-existing `E741` at `backend/app/services/item.py:286` is unrelated — ignore it.
- Frontend has **no test suite**; verify with `cd frontend && npx tsc -b --noEmit` (clean; delete any `.js` emitted under `src/`). `npm run lint` is broken — not a gate.
- Commits omit the `Co-Authored-By` trailer. Never `git add` CLAUDE.md (gitignored).
- `project_service.get_raw(project_id)` returns the raw project dict (has `keypoint_schema`). `project_service` is already imported in `items.py`.

---

## File structure

**Modified:**
- `backend/app/services/item.py` — extract `eligible_pose_items` + `partition_records`; refactor `_yolo_records` and `build_yolo_split_export` onto them (behavior-preserving).
- `backend/app/api/v1/items.py` — `coco|coco_split` formats + infant 422 guard + wiring.
- `backend/pyproject.toml` — add `pycocotools` to the dev dependency group.
- `frontend/src/lib/download.ts` — `coco`/`coco_split` filenames + split params.
- `frontend/src/pages/ProjectDetailPage.tsx` — `coco`/`coco_split` radio options.
- `SPEC.md` — document the formats.

**Created:**
- `backend/app/services/coco_export.py` — COCO doc builders.
- `backend/tests/test_coco_export.py` — COCO tests.

---

## Task 1: Refactor `item.py` — extract `eligible_pose_items` + `partition_records`

**Files:**
- Modify: `backend/app/services/item.py`
- Regression guard (do not modify): existing YOLO/occluded tests in `backend/tests/test_items_api.py`.

The two new helpers get **non-underscore** names because they are a deliberately shared internal API consumed by `coco_export.py`. `_yolo_records` stays private.

- [ ] **Step 1: Confirm green baseline**

Run: `docker compose exec -T backend python -m pytest tests/test_items_api.py -k "export or occluded" -v`
Expected: all PASS.

- [ ] **Step 2: Add `eligible_pose_items` and refactor `_yolo_records`**

In `backend/app/services/item.py`, replace the current `_yolo_records` function (signature `def _yolo_records(project_id: int, num_kpts: int, exclude_occluded: bool = False)` through its final `yield src, stem, label_line`) with these TWO functions:

```python
def eligible_pose_items(
    project_id: int, num_kpts: int
) -> Iterator[tuple[dict, Path, int, int, list]]:
    """Yield (item, src, w, h, kps) for every export-eligible pose item, in
    `storage.list_items` order. Shared by the YOLO and COCO exporters so both
    see the SAME ordered set — which is what makes their seeded splits match.

    Eligibility (all must hold): has an annotation; keypoint count matches the
    schema; `image_url` is under `/files/`; the source frame exists; its JPEG
    dims are readable; at least one keypoint is visible (v>0).
    """
    items = storage.list_items(project_id)
    anns = {a["item_id"]: a for a in storage.list_annotations_for_project(project_id)}
    data_root = Path(settings.DATA_DIR)

    for item in items:
        ann = anns.get(item["id"])
        if not ann:
            continue
        kps = (ann.get("value") or {}).get("keypoints") or []
        if len(kps) != num_kpts:
            continue
        image_url = (item.get("payload") or {}).get("image_url")
        if not image_url or not image_url.startswith("/files/"):
            continue
        src = data_root / image_url[len("/files/") :]
        if not src.exists():
            continue
        dims = _jpeg_size(src)
        if not dims:
            continue
        w, h = dims
        if not any(v > 0 for *_, v in kps):
            continue
        yield item, src, w, h, kps


def _yolo_records(
    project_id: int, num_kpts: int, exclude_occluded: bool = False
) -> Iterator[tuple[Path, str, str]]:
    """Yield (src_path, stem, label_line) for every export-eligible item.

    The label line is the normalized YOLO-pose row `0 cx cy w h x1 y1 v1 ...`.
    When `exclude_occluded` is set, occluded keypoints (v=1) are written as
    `0 0 0` (demoted to v=0) so they carry no keypoint supervision; the bbox
    still uses them.
    """
    for item, src, w, h, kps in eligible_pose_items(project_id, num_kpts):
        visible_pts = [(x, y) for x, y, v in kps if v > 0]
        xs = [p[0] for p in visible_pts]
        ys = [p[1] for p in visible_pts]
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        # pad bbox by 10% on each side
        pad_x = (x1 - x0) * 0.1 or 5
        pad_y = (y1 - y0) * 0.1 or 5
        x0 = max(0, x0 - pad_x)
        x1 = min(w, x1 + pad_x)
        y0 = max(0, y0 - pad_y)
        y1 = min(h, y1 + pad_y)
        cx = (x0 + x1) / 2 / w
        cy = (y0 + y1) / 2 / h
        bw = (x1 - x0) / w
        bh = (y1 - y0) / h

        kp_str = " ".join(
            "0.000000 0.000000 0"
            if (exclude_occluded and v == 1)
            else f"{x / w:.6f} {y / h:.6f} {int(v)}"
            for x, y, v in kps
        )
        label_line = f"0 {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f} {kp_str}\n"
        stem = f"{item['id']:06d}_{src.stem}"
        yield src, stem, label_line
```

- [ ] **Step 3: Add `partition_records` and refactor `build_yolo_split_export`**

Add this function ABOVE `build_yolo_split_export`:

```python
def partition_records(
    seq: list, train: int, val: int, test: int, seed: int
) -> list[tuple[str, list]]:
    """Shuffle `seq` with a seeded RNG and partition by floor counts.

    Returns [("train", [...]), ("val", [...]), ("test", [...])]. When test == 0
    the test split is omitted and `val` is the catch-all so no element is
    dropped. Shared by the YOLO and COCO split exporters so identical inputs +
    params produce identical assignments.
    """
    seq = list(seq)
    random.Random(seed).shuffle(seq)
    n = len(seq)
    n_train = n * train // 100
    n_val = n * val // 100
    if test > 0:
        return [
            ("train", seq[:n_train]),
            ("val", seq[n_train : n_train + n_val]),
            ("test", seq[n_train + n_val :]),
        ]
    return [
        ("train", seq[:n_train]),
        ("val", seq[n_train:]),
    ]
```

Then in `build_yolo_split_export`, replace the current shuffle/partition block. Current:

```python
    records = list(_yolo_records(project_id, num_kpts, exclude_occluded))
    random.Random(seed).shuffle(records)
    n = len(records)
    n_train = n * train // 100
    n_val = n * val // 100

    if test > 0:
        splits = [
            ("train", records[:n_train]),
            ("val", records[n_train : n_train + n_val]),
            ("test", records[n_train + n_val :]),
        ]
    else:
        # val is the catch-all so flooring never drops the remainder.
        splits = [
            ("train", records[:n_train]),
            ("val", records[n_train:]),
        ]
```

becomes:

```python
    records = list(_yolo_records(project_id, num_kpts, exclude_occluded))
    splits = partition_records(records, train, val, test, seed)
```

- [ ] **Step 4: Run the YOLO regression suite**

Run: `docker compose exec -T backend python -m pytest tests/test_items_api.py -k "export or occluded" -v`
Expected: all PASS — YOLO output unchanged.

- [ ] **Step 5: Lint (scoped)**

Run: `ruff check backend/app/services/item.py && ruff format backend/app/services/item.py`
(Ignore the pre-existing E741 at item.py:286.)

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/item.py
git commit -m "refactor(export): share eligible-item stream and split partition for COCO reuse"
```

---

## Task 2: `coco_export.py` service + tests

**Files:**
- Create: `backend/app/services/coco_export.py`
- Create: `backend/tests/test_coco_export.py`
- Modify: `backend/pyproject.toml` (add pycocotools to dev group)

- [ ] **Step 1: Add pycocotools to the dev dependency group + install it in the container**

In `backend/pyproject.toml`, the `[dependency-groups]` block currently is:

```toml
[dependency-groups]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "httpx>=0.27",
    "ruff>=0.7",
]
```

Add `pycocotools`:

```toml
[dependency-groups]
dev = [
    "pytest>=8.3",
    "pytest-asyncio>=0.24",
    "httpx>=0.27",
    "ruff>=0.7",
    "pycocotools>=2.0",
]
```

Install it into the running container for this session:
Run: `docker compose exec -T backend uv pip install --system pycocotools`
Expected: installs pycocotools (+ numpy) successfully.

- [ ] **Step 2: Write the failing service tests**

Create `backend/tests/test_coco_export.py`:

```python
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
    """n annotated 17-keypoint items; item k gets one occluded (v=1) kp at
    an extreme corner so coords are clearly absolute pixels."""
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
        # 16 visible + 1 occluded = 17 with v>0
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
    # the occluded keypoint is at x=600 (absolute pixels, > 1.0, within width)
    assert max(xs) == 600
    assert all(0 <= x <= 640 for x in xs)


def test_build_coco_export_loads_with_pycocotools(client, auth_headers, project, tmp_path):
    from pycocotools.coco import COCO

    from app.services import coco_export

    _seed_pose_items(client, auth_headers, project, 2)
    p = tmp_path / "annotations.json"
    p.write_bytes(coco_export.build_coco_export(project["id"]))
    coco = COCO(str(p))  # must not raise
    assert len(coco.getImgIds()) == 2
    assert len(coco.getAnnIds()) == 2


def test_coco_split_matches_yolo_split(client, auth_headers, project):
    """The killer test: coco_split and yolo_split assign every frame to the
    same split for the same seed/ratios."""
    from app.services import coco_export
    from app.services import item as item_service

    _seed_pose_items(client, auth_headers, project, 10)

    # COCO split -> {file_name: split}
    cstream, _ = coco_export.build_coco_split_export(
        project["id"], train=70, val=20, test=10, seed=42
    )
    try:
        czf = zipfile.ZipFile(io.BytesIO(cstream.read()))
    finally:
        cstream.close()
    coco_map = {}
    for name in czf.namelist():
        split = name[: -len(".json")]  # "train", "val", "test"
        doc = json.loads(czf.read(name))
        for im in doc["images"]:
            coco_map[im["file_name"]] = split

    # YOLO split -> {file_name: split}
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
            # images/<split>/<file_name>
            _, split, fname = name.split("/", 2)
            yolo_map[fname] = split

    assert coco_map == yolo_map
    assert len(coco_map) == 10
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `docker compose exec -T backend python -m pytest tests/test_coco_export.py -v`
Expected: FAIL — `app.services.coco_export` does not exist.

- [ ] **Step 4: Implement `coco_export.py`**

Create `backend/app/services/coco_export.py`:

```python
import io
import json
import tempfile
import zipfile
from pathlib import Path
from typing import BinaryIO

from app.services.item import eligible_pose_items, partition_records

# COCO export is infant-only (the endpoint rejects rodent), so the keypoint
# count is always the COCO-17 person layout.
_NUM_KPTS = 17

# Fixed COCO Keypoints `categories` entry (1-indexed skeleton, COCO convention).
_COCO_CATEGORIES = [
    {
        "id": 1,
        "name": "person",
        "supercategory": "person",
        "keypoints": [
            "nose", "left_eye", "right_eye", "left_ear", "right_ear",
            "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
            "left_wrist", "right_wrist", "left_hip", "right_hip",
            "left_knee", "right_knee", "left_ankle", "right_ankle",
        ],
        "skeleton": [
            [16, 14], [14, 12], [17, 15], [15, 13], [12, 13], [6, 12], [7, 13],
            [6, 7], [6, 8], [7, 9], [8, 10], [9, 11], [2, 3], [1, 2], [1, 3],
            [2, 4], [3, 5], [4, 6], [5, 7],
        ],
    }
]

# Annotation ids are offset from image ids so an annotation's id never equals
# its image_id (COCO requires both, and they must be distinguishable).
_ANN_ID_OFFSET = 1_000_000


def _image_and_annotation(
    image_id: int, item: dict, src: Path, w: int, h: int, kps: list
) -> tuple[dict, dict]:
    """Build the COCO images[] and annotations[] entries for one frame.

    Keypoints are absolute pixels in COCO-17 order with native 0/1/2
    visibility. The bbox is derived from the visible (v>0) keypoints, padded
    12% per side and clamped to the image — NeoLabel stores no person box.
    """
    file_name = f"{item['id']:06d}_{src.stem}{src.suffix}"
    image = {"id": image_id, "file_name": file_name, "width": w, "height": h}

    keypoints: list = []
    num_keypoints = 0
    for x, y, v in kps:
        keypoints.extend([x, y, v])
        if v > 0:
            num_keypoints += 1

    vis = [(x, y) for x, y, v in kps if v > 0]
    xs = [p[0] for p in vis]
    ys = [p[1] for p in vis]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    pad_x = (x1 - x0) * 0.12 or 5
    pad_y = (y1 - y0) * 0.12 or 5
    bx0 = max(0, x0 - pad_x)
    by0 = max(0, y0 - pad_y)
    bx1 = min(w, x1 + pad_x)
    by1 = min(h, y1 + pad_y)
    bw = bx1 - bx0
    bh = by1 - by0

    annotation = {
        "id": image_id + _ANN_ID_OFFSET,
        "image_id": image_id,
        "category_id": 1,
        "keypoints": keypoints,
        "num_keypoints": num_keypoints,
        "bbox": [bx0, by0, bw, bh],
        "area": bw * bh,
        "iscrowd": 0,
    }
    return image, annotation


def _coco_doc(eligible: list) -> dict:
    """Build a COCO dict from an ordered list of (item, src, w, h, kps)."""
    images = []
    annotations = []
    for i, (item, src, w, h, kps) in enumerate(eligible, start=1):
        image, ann = _image_and_annotation(i, item, src, w, h, kps)
        images.append(image)
        annotations.append(ann)
    return {"images": images, "annotations": annotations, "categories": _COCO_CATEGORIES}


def build_coco_export(project_id: int) -> bytes:
    """Single COCO Keypoints annotations.json over every annotated frame."""
    eligible = list(eligible_pose_items(project_id, _NUM_KPTS))
    return json.dumps(_coco_doc(eligible)).encode("utf-8")


def build_coco_split_export(
    project_id: int, train: int, val: int, test: int, seed: int
) -> tuple[BinaryIO, int]:
    """ZIP with train.json/val.json/test.json. Uses the SAME ordered eligible
    items and the SAME seeded partition as the YOLO split, so the per-frame
    assignment is identical for matching params. test.json is omitted when
    test == 0 (val is the catch-all). Spills to disk past 64 MiB.
    """
    eligible = list(eligible_pose_items(project_id, _NUM_KPTS))
    splits = partition_records(eligible, train, val, test, seed)

    spooled = tempfile.SpooledTemporaryFile(max_size=64 * 1024 * 1024, mode="w+b")
    with zipfile.ZipFile(spooled, "w", zipfile.ZIP_DEFLATED) as zf:
        for split_name, split_items in splits:
            zf.writestr(f"{split_name}.json", json.dumps(_coco_doc(split_items)))

    size = spooled.tell()
    spooled.seek(0)
    return spooled, size
```

Note: `io` is imported for symmetry with sibling modules but only `tempfile`/`zipfile`/`json` are strictly used — if `ruff` flags the unused `io` import, remove it.

- [ ] **Step 5: Run the COCO tests to verify they pass**

Run: `docker compose exec -T backend python -m pytest tests/test_coco_export.py -v`
Expected: 4 passed.

- [ ] **Step 6: Lint (scoped)**

Run: `ruff check backend/app/services/coco_export.py backend/tests/test_coco_export.py && ruff format backend/app/services/coco_export.py backend/tests/test_coco_export.py`

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/coco_export.py backend/tests/test_coco_export.py backend/pyproject.toml
git commit -m "feat(coco-export): COCO Keypoints builders with YOLO-matching splits"
```

---

## Task 3: Wire `coco` / `coco_split` into the export endpoint

**Files:**
- Modify: `backend/app/api/v1/items.py`
- Test: `backend/tests/test_coco_export.py`

- [ ] **Step 1: Write the failing endpoint tests**

Append to `backend/tests/test_coco_export.py`:

```python
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
```

- [ ] **Step 2: Run them, expect failure**

Run: `docker compose exec -T backend python -m pytest tests/test_coco_export.py -k "endpoint or rodent" -v`
Expected: FAIL — the `format` regex rejects `coco`/`coco_split` (422 for the wrong reason / no JSON body).

- [ ] **Step 3: Wire the endpoint**

In `backend/app/api/v1/items.py`:

Add the import near the other service imports (after `from app.services import project as project_service`):

```python
from app.services import coco_export as coco_service
```

Extend the `format` regex. Current:

```python
    format: str = Query("json", pattern="^(json|jsonl|csv|yolo|bundle|yolo_split)$"),
```

becomes:

```python
    format: str = Query(
        "json",
        pattern="^(json|jsonl|csv|yolo|bundle|yolo_split|coco|coco_split)$",
    ),
```

Then, immediately AFTER `_require_project_for_owner(project_id, current_user)` and BEFORE the `if format == "yolo":` block, add the COCO branches (infant guard first):

```python
    if format in ("coco", "coco_split"):
        proj = project_service.get_raw(project_id) or {}
        if (proj.get("keypoint_schema") or "infant") != "infant":
            raise HTTPException(
                status_code=422,
                detail="COCO export is only available for infant (17-keypoint) pose projects",
            )
        if format == "coco":
            data = coco_service.build_coco_export(project_id)
            return Response(
                content=data,
                media_type="application/json",
                headers={
                    "Content-Disposition": f'attachment; filename="project_{project_id}_coco.json"'
                },
            )
        if train + val + test != 100:
            raise HTTPException(
                status_code=422,
                detail="train + val + test must sum to 100",
            )
        stream, size = coco_service.build_coco_split_export(
            project_id, train, val, test, seed
        )
        return _stream_zip(stream, size, f"project_{project_id}_coco_split.zip")
```

(`Response`, `HTTPException`, `Query` are already imported. Leave all existing branches unchanged.)

- [ ] **Step 4: Run the endpoint tests, expect PASS**

Run: `docker compose exec -T backend python -m pytest tests/test_coco_export.py -k "endpoint or rodent" -v`
Expected: 3 passed.

- [ ] **Step 5: Run the full COCO + export groups (regression)**

Run: `docker compose exec -T backend python -m pytest tests/test_coco_export.py tests/test_items_api.py -k "coco or export or occluded" -v`
Expected: all PASS.

- [ ] **Step 6: Lint (scoped)**

Run: `ruff check backend/app/api/v1/items.py backend/tests/test_coco_export.py && ruff format backend/app/api/v1/items.py backend/tests/test_coco_export.py`

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/v1/items.py backend/tests/test_coco_export.py
git commit -m "feat(export): coco + coco_split formats with infant-only guard"
```

---

## Task 4: Frontend — `coco` / `coco_split` in the export modal

**Files:**
- Modify: `frontend/src/lib/download.ts`
- Modify: `frontend/src/pages/ProjectDetailPage.tsx`

- [ ] **Step 1: Widen `ExportFormat` and add filenames/params in `download.ts`**

In `frontend/src/lib/download.ts`, widen the type:

```typescript
export type ExportFormat =
  | 'json'
  | 'jsonl'
  | 'csv'
  | 'yolo'
  | 'bundle'
  | 'yolo_split'
  | 'coco'
  | 'coco_split';
```

Extend the split-params guard to also send them for `coco_split`. Current:

```typescript
  const params: Record<string, string | number | boolean> = { format };
  if (format === 'yolo_split' && opts?.split) {
    Object.assign(params, opts.split);
  }
```

becomes:

```typescript
  const params: Record<string, string | number | boolean> = { format };
  if ((format === 'yolo_split' || format === 'coco_split') && opts?.split) {
    Object.assign(params, opts.split);
  }
```

(Leave the `exclude_occluded` block exactly as-is — it stays `yolo`/`yolo_split` only.)

Add the filenames. Current `a.download` ternary chain:

```typescript
  a.download =
    format === 'yolo'
      ? `project_${projectId}_yolo.zip`
      : format === 'yolo_split'
        ? `project_${projectId}_yolo_split.zip`
        : format === 'bundle'
          ? `project_${projectId}_bundle.zip`
          : `project_${projectId}.${format}`;
```

becomes:

```typescript
  a.download =
    format === 'yolo'
      ? `project_${projectId}_yolo.zip`
      : format === 'yolo_split'
        ? `project_${projectId}_yolo_split.zip`
        : format === 'coco'
          ? `project_${projectId}_coco.json`
          : format === 'coco_split'
            ? `project_${projectId}_coco_split.zip`
            : format === 'bundle'
              ? `project_${projectId}_bundle.zip`
              : `project_${projectId}.${format}`;
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npx tsc -b --noEmit`
Expected: no errors. (`download.ts` types compile with the wider union.)

- [ ] **Step 3: Add the radio options + split panel gating in `ProjectDetailPage.tsx`**

In `frontend/src/pages/ProjectDetailPage.tsx`, find the pose-only options block (the `...(isPose ? ([...] as const) : [])`). Add `coco` and `coco_split` entries after `yolo_split` and before `bundle`:

```typescript
                  ...(isPose
                    ? ([
                        { v: 'yolo', label: 'YOLO-pose (ZIP)', hint: 'Ultralytics, COCO 17 kp' },
                        {
                          v: 'yolo_split',
                          label: 'YOLO-pose split (ZIP)',
                          hint: 'train / valid / test, seeded',
                        },
                        { v: 'coco', label: 'COCO Keypoints (JSON)', hint: 'ViTPose / MMPose' },
                        {
                          v: 'coco_split',
                          label: 'COCO split (ZIP)',
                          hint: 'train/val/test.json, seeded',
                        },
                        {
                          v: 'bundle',
                          label: 'Full bundle (ZIP)',
                          hint: 'annotations.json + all source images',
                        },
                      ] as const)
                    : []),
```

The split panel and the download-button sum gate currently check `exportFormat === 'yolo_split'`. Update BOTH to also include `coco_split`.

The split panel opening line. Current:

```tsx
              {exportFormat === 'yolo_split' && (
```

becomes:

```tsx
              {(exportFormat === 'yolo_split' || exportFormat === 'coco_split') && (
```

The Download button `disabled`. Current:

```tsx
                disabled={!!exportProgress || (exportFormat === 'yolo_split' && splitSum !== 100)}
```

becomes:

```tsx
                disabled={
                  !!exportProgress ||
                  ((exportFormat === 'yolo_split' || exportFormat === 'coco_split') &&
                    splitSum !== 100)
                }
```

In `handleExport`, the `split` forwarding currently is:

```typescript
        split: fmt === 'yolo_split' ? splitCfg : undefined,
```

becomes:

```typescript
        split: fmt === 'yolo_split' || fmt === 'coco_split' ? splitCfg : undefined,
```

(Leave the `excludeOccluded` line unchanged — COCO doesn't use it.)

- [ ] **Step 4: Typecheck**

Run: `cd frontend && npx tsc -b --noEmit`
Expected: no errors. Delete any `.js` emitted under `src/` (do not stage).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/download.ts frontend/src/pages/ProjectDetailPage.tsx
git commit -m "feat(export-ui): COCO Keypoints + COCO split options in export modal"
```

---

## Task 5: SPEC.md + final verification

**Files:**
- Modify: `SPEC.md`

- [ ] **Step 1: Document the COCO formats in SPEC.md**

In `SPEC.md`, find the export endpoint bullet (lists `format=...`). Update the format list to include `coco|coco_split` and add a describing bullet after the `exclude_occluded` bullet:

Change the format-list line to end with `|coco|coco_split` and add:

```markdown
- `coco` / `coco_split` — COCO Keypoints JSON for ViTPose/MMPose/pycocotools.
  `coco` streams a single `annotations.json` (`images`/`annotations`/
  `categories`, absolute-pixel keypoints in COCO-17 order, person bbox
  padded 12% from the visible keypoints). `coco_split` returns a ZIP of
  `train.json`/`val.json`/`test.json` using the **same** `train/val/test/seed`
  partition as `yolo_split`, so the COCO and YOLO splits match frame-for-frame
  (the `file_name` is the same `NNNNNN_<stem>.jpg` as the YOLO export).
  **Infant pose only** — a rodent project returns **422**.
```

- [ ] **Step 2: Commit SPEC**

```bash
git add SPEC.md
git commit -m "docs(spec): document coco + coco_split export formats"
```

- [ ] **Step 3: Full backend suite**

Run: `docker compose exec -T backend python -m pytest -q`
Expected: all PASS (COCO + existing). Note: if a flaky unrelated test fails, re-run once to confirm it's not from this change.

- [ ] **Step 4: Frontend build**

Run: `cd frontend && npm run build`
Expected: `tsc -b` clean + `vite build` succeeds. Delete any `.js` emitted under `src/`.

- [ ] **Step 5: Manual smoke (optional)**

With the dev stack up, open an infant pose project → Export → choose **COCO Keypoints (JSON)** (a `project_<id>_coco.json` downloads) and **COCO split (ZIP)** with ratios (a `project_<id>_coco_split.zip` with `train/val/test.json` downloads). Optionally diff the split assignment against the YOLO split for the same seed.

- [ ] **Step 6: Confirm clean tree**

Run: `git status` — expected clean (all committed; no stray `.js`).

---

## Self-review notes

- **Spec coverage:** single `coco` JSON + `coco_split` ZIP (Task 2/3); 3 top-level keys, absolute-pixel COCO-17 keypoints, 12% bbox, num_keypoints, area, iscrowd, ann-id≠image_id, verbatim categories/skeleton (Task 2 `_image_and_annotation`/`_COCO_CATEGORIES` + tests); file_name == YOLO name (Task 2, asserted via the split-matching test comparing file_name keys); split == YOLO split via shared `eligible_pose_items` + `partition_records` (Task 1) and proven by `test_coco_split_matches_yolo_split` (Task 2); infant-only 422 (Task 3); pycocotools load test (Task 2); only annotated frames (eligibility filter, Task 1); resolution = annotated (Task 1 `_jpeg_size`); frontend options + split reuse (Task 4); SPEC (Task 5). All spec sections map to a task.
- **Type/signature consistency:** `eligible_pose_items(project_id, num_kpts)` and `partition_records(seq, train, val, test, seed)` are defined in Task 1 and consumed identically in `coco_export.py` (Task 2). `build_coco_export(project_id) -> bytes` and `build_coco_split_export(project_id, train, val, test, seed) -> (BinaryIO, int)` match between the service (Task 2), the endpoint calls (Task 3), and the tests (Task 2/3). Frontend `ExportFormat` includes `coco`/`coco_split` in `download.ts` (Task 4); the split panel, button gate, and `handleExport` all branch on `yolo_split || coco_split` consistently.
- **Split-match guarantee:** YOLO partitions `_yolo_records(...)` (a 1:1 ordered map over `eligible_pose_items`); COCO partitions `eligible_pose_items(...)` directly. Same order + same `partition_records(seed)` → same index→split → same per-frame assignment. The `file_name` (`NNNNNN_<stem>.jpg`) is identical on both sides, so `test_coco_split_matches_yolo_split` is a true end-to-end proof.
- **No placeholders:** every code step contains full code; commands have expected output.
