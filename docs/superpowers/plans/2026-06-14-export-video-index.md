# Export video index (per-video frame boundaries) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in `video_index=true` flag to the flat exports that ships a `video_index.csv` describing, per source video, the first/last frame and frame count actually present in that export.

**Architecture:** Two pure helpers in `services/item.py` (`_frame_ref`, `build_video_index_csv`) plus a `zip_bytes` wrapper. ZIP-native formats (`yolo`, `bundle`) gain a `video_index=False` param that injects `video_index.csv` into their existing archive; single-file formats (`coco`, `json`, `jsonl`, `csv`) are wrapped in a ZIP (native file + manifest) only when the flag is on. With the flag off, every export is byte-identical to today.

**Tech Stack:** Python 3.12, FastAPI, pytest + httpx TestClient (backend); React + TypeScript, Vite (frontend). Spec: `docs/superpowers/specs/2026-06-14-export-video-index-design.md`.

**Conventions:** ruff line-length 100. Commit messages use the repo's `feat(...)`/`test(...)` style and carry **no** `Co-Authored-By` trailer. Run backend tests inside the container: `docker compose exec backend pytest`.

---

### Task 1: Pure helpers — `_frame_ref`, `build_video_index_csv`, `zip_bytes`

**Files:**
- Modify: `backend/app/services/item.py` (add three functions; all needed imports — `csv`, `io`, `zipfile`, `tempfile`, `Path`, `BinaryIO`, `Iterator` — are already imported at the top)
- Test: `backend/tests/test_export_video_index.py` (create)

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_export_video_index.py`:

```python
import csv
import io
import zipfile


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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `docker compose exec backend pytest tests/test_export_video_index.py -v`
Expected: FAIL — `ImportError: cannot import name '_frame_ref'` (etc.)

- [ ] **Step 3: Implement the three helpers**

In `backend/app/services/item.py`, add near the other export helpers (e.g. just above `_iter_export_rows`):

```python
def _frame_ref(payload: dict) -> tuple[str, str] | None:
    """(source_video, frame_stem) for a payload that references a frame, else None.

    frame_stem is the image's file stem, e.g. "f_000123". source_video defaults
    to "" when absent (COCO-imported standalone images have no source video).
    """
    image_url = (payload or {}).get("image_url")
    if not isinstance(image_url, str) or not image_url:
        return None
    source_video = (payload or {}).get("source_video") or ""
    return source_video, Path(image_url).stem


def _frame_sort_key(stem: str) -> tuple[int, object]:
    """Numeric "f_<digits>" stems sort by their integer; anything else sorts
    after, lexicographically. Keeps min/max well-defined for imported data."""
    if stem.startswith("f_") and stem[2:].isdigit():
        return (0, int(stem[2:]))
    return (1, stem)


def _frame_label(stem: str) -> object:
    """Display value for a frame boundary: the int for "f_<digits>", else the stem."""
    if stem.startswith("f_") and stem[2:].isdigit():
        return int(stem[2:])
    return stem


def build_video_index_csv(pairs: Iterable[tuple[str, str]]) -> str:
    """Per-video manifest CSV from (source_video, frame_stem) pairs.

    Columns: source_video, first_frame, last_frame, num_frames. Rows are ordered
    by each video's first appearance in `pairs`. first/last are the min/max frame
    by `_frame_sort_key`; num_frames is the count of that video's frames present.
    """
    groups: dict[str, list[str]] = {}
    for source_video, stem in pairs:
        groups.setdefault(source_video, []).append(stem)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["source_video", "first_frame", "last_frame", "num_frames"])
    for source_video, stems in groups.items():
        ordered = sorted(stems, key=_frame_sort_key)
        writer.writerow(
            [source_video, _frame_label(ordered[0]), _frame_label(ordered[-1]), len(stems)]
        )
    return buf.getvalue()


def zip_bytes(entries: list[tuple[str, bytes]]) -> tuple[BinaryIO, int]:
    """Spooled (64 MiB) ZIP_DEFLATED archive from in-memory (name, bytes)
    entries. Returns (file-like at position 0, byte size); caller closes."""
    spooled = tempfile.SpooledTemporaryFile(max_size=64 * 1024 * 1024, mode="w+b")
    with zipfile.ZipFile(spooled, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries:
            zf.writestr(name, data)
    size = spooled.tell()
    spooled.seek(0)
    return spooled, size
```

Add `Iterable` to the existing `collections.abc` import line so it reads:

```python
from collections.abc import Iterable, Iterator
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `docker compose exec backend pytest tests/test_export_video_index.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Lint**

Run: `ruff check backend/app/services/item.py backend/tests/test_export_video_index.py`
Expected: no errors.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/item.py backend/tests/test_export_video_index.py
git commit -m "feat(export): video-index csv + zip helpers"
```

---

### Task 2: Wire YOLO flat export

**Files:**
- Modify: `backend/app/services/item.py` — `_yolo_records` (616-652), `build_yolo_export` (655-704), `build_yolo_split_export` (inner loop ~781-786)
- Test: `backend/tests/test_export_video_index.py` (append seeders + tests)

- [ ] **Step 1: Add shared test seeders + the failing YOLO tests**

First, replace the import block at the **top** of `backend/tests/test_export_video_index.py` (keeps all module-level imports at the top — ruff E402):

```python
import csv
import io
import os
import struct
import zipfile

import pytest
```

Then append the seeders and tests **below** the Task 1 tests:

```python
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
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `docker compose exec backend pytest tests/test_export_video_index.py -k yolo -v`
Expected: FAIL — `build_yolo_export()` got an unexpected keyword argument `video_index`.

- [ ] **Step 3: Widen `_yolo_records` to surface `source_video`**

In `backend/app/services/item.py`, change `_yolo_records`'s signature docstring tail and its `yield`. The loop body up to `stem = ...` is unchanged; replace the final two lines:

```python
        label_line = f"0 {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f} {kp_str}\n"
        stem = f"{item['id']:06d}_{src.stem}"
        source_video = (item.get("payload") or {}).get("source_video") or ""
        yield src, stem, label_line, source_video
```

And update its return annotation:

```python
def _yolo_records(
    project_id: int, num_kpts: int, exclude_occluded: bool = False
) -> Iterator[tuple[Path, str, str, str]]:
```

- [ ] **Step 4: Collect + write the index in `build_yolo_export`**

In `build_yolo_export`, change the signature and the write loop. Signature:

```python
def build_yolo_export(
    project_id: int, exclude_occluded: bool = False, video_index: bool = False
) -> tuple[BinaryIO, int]:
```

Replace the export loop:

```python
        exported = 0
        index_pairs: list[tuple[str, str]] = []
        for src, stem, label_line, source_video in _yolo_records(
            project_id, num_kpts, exclude_occluded
        ):
            zf.write(src, f"images/train/{stem}{src.suffix}")
            zf.writestr(f"labels/train/{stem}.txt", label_line)
            exported += 1
            if video_index:
                index_pairs.append((source_video, src.stem))
```

Then, after the `README.txt` `writestr` and before the `with` block closes, add:

```python
        if video_index:
            zf.writestr("video_index.csv", build_video_index_csv(index_pairs))
```

- [ ] **Step 5: Fix the split builder's tuple unpack**

In `build_yolo_split_export`, the inner loop currently unpacks a 3-tuple. Change it to ignore the new field:

```python
            for src, stem, label_line, _source_video in recs:
                zf.write(src, f"images/{split_name}/{stem}{src.suffix}")
                zf.writestr(f"labels/{split_name}/{stem}.txt", label_line)
```

- [ ] **Step 6: Run the YOLO tests + the split regression**

Run: `docker compose exec backend pytest tests/test_export_video_index.py -k yolo -v`
Expected: PASS (3 tests).

Run the existing export suite to confirm no regression:
Run: `docker compose exec backend pytest tests/test_items_api.py -v`
Expected: PASS.

- [ ] **Step 7: Lint + commit**

```bash
ruff check backend/app/services/item.py backend/tests/test_export_video_index.py
git add backend/app/services/item.py backend/tests/test_export_video_index.py
git commit -m "feat(export): video_index for flat YOLO-pose export"
```

---

### Task 3: Wire bundle export

**Files:**
- Modify: `backend/app/services/item.py` — `build_bundle_export` (807-871)
- Test: `backend/tests/test_export_video_index.py` (append)

- [ ] **Step 1: Write the failing test**

Append:

```python
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `docker compose exec backend pytest tests/test_export_video_index.py -k bundle -v`
Expected: FAIL — unexpected keyword argument `video_index`.

- [ ] **Step 3: Implement**

Change `build_bundle_export`'s signature:

```python
def build_bundle_export(project_id: int, video_index: bool = False) -> tuple[BinaryIO, int]:
```

Inside the `for item in items:` loop, after `payload = dict(item.get("payload") or {})` and before the `image_url` rewrite logic, collect the index pair from the **original** payload (so the stem is `f_NNNNNN`, not the rewritten `images/<stem>` path):

```python
        for item in items:
            ann_value = anns.get(item["id"], {}).get("value") if item["id"] in anns else None
            payload = dict(item.get("payload") or {})
            if video_index:
                ref = _frame_ref(item.get("payload") or {})
                if ref:
                    index_pairs.append(ref)
            image_url = payload.get("image_url")
```

Declare `index_pairs` just before the loop (next to `rows`/`included_images`/`seen`):

```python
    rows: list[dict] = []
    included_images = 0
    seen: set[str] = set()
    index_pairs: list[tuple[str, str]] = []
```

After the `README.txt` `writestr` (still inside the `with zipfile...` block), add:

```python
        if video_index:
            zf.writestr("video_index.csv", build_video_index_csv(index_pairs))
```

- [ ] **Step 4: Run it to verify it passes**

Run: `docker compose exec backend pytest tests/test_export_video_index.py -k bundle -v`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
ruff check backend/app/services/item.py
git add backend/app/services/item.py backend/tests/test_export_video_index.py
git commit -m "feat(export): video_index for bundle export"
```

---

### Task 4: Text exports wrapped in a zip (`build_text_export_zip`)

**Files:**
- Modify: `backend/app/services/item.py` — add `build_text_export_zip` after `iter_export_csv` (~924)
- Test: `backend/tests/test_export_video_index.py` (append)

- [ ] **Step 1: Write the failing test**

Append:

```python
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `docker compose exec backend pytest tests/test_export_video_index.py -k text_export_zip -v`
Expected: FAIL — `build_text_export_zip` not defined.

- [ ] **Step 3: Implement**

Add after `iter_export_csv` in `backend/app/services/item.py`:

```python
_TEXT_SERIALIZERS = {
    "json": iter_export_json,
    "jsonl": iter_export_jsonl,
    "csv": iter_export_csv,
}


def build_text_export_zip(project_id: int, fmt: str) -> tuple[BinaryIO, int]:
    """ZIP [project_<id>.<fmt> + video_index.csv] for the text formats.

    The inner file is byte-identical to the streamed (flag-off) output — it
    reuses the same serializer. The manifest reflects every exported row that
    references a frame (these formats include pending items too)."""
    body = b"".join(_TEXT_SERIALIZERS[fmt](project_id))
    pairs = [
        ref for row in _iter_export_rows(project_id) if (ref := _frame_ref(row["payload"]))
    ]
    csv_text = build_video_index_csv(pairs)
    return zip_bytes(
        [(f"project_{project_id}.{fmt}", body), ("video_index.csv", csv_text.encode("utf-8"))]
    )
```

- [ ] **Step 4: Run it to verify it passes**

Run: `docker compose exec backend pytest tests/test_export_video_index.py -k text_export_zip -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Lint + commit**

```bash
ruff check backend/app/services/item.py
git add backend/app/services/item.py backend/tests/test_export_video_index.py
git commit -m "feat(export): zip-wrap json/jsonl/csv with video_index"
```

---

### Task 5: COCO pairs helper

**Files:**
- Modify: `backend/app/services/coco_export.py` — add `video_index_pairs` (after `build_coco_export`, ~131)
- Test: `backend/tests/test_export_video_index.py` (append)

- [ ] **Step 1: Write the failing test**

Append:

```python
def test_coco_video_index_pairs(client, auth_headers, pose_project):
    from app.services import coco_export
    from app.services.item import build_video_index_csv

    pid = pose_project["id"]
    _seed_frames(client, auth_headers, pid, "vid_a", [0, 3])
    _seed_frames(client, auth_headers, pid, "vid_b", [1])
    _annotate(client, auth_headers, _all_items(client, auth_headers, pid))

    pairs = coco_export.video_index_pairs(pid)
    rows = {
        r["source_video"]: r
        for r in csv.DictReader(io.StringIO(build_video_index_csv(pairs)))
    }
    assert rows["vid_a"] == {
        "source_video": "vid_a",
        "first_frame": "0",
        "last_frame": "3",
        "num_frames": "2",
    }
    assert rows["vid_b"]["num_frames"] == "1"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `docker compose exec backend pytest tests/test_export_video_index.py -k coco_video_index_pairs -v`
Expected: FAIL — module `coco_export` has no attribute `video_index_pairs`.

- [ ] **Step 3: Implement**

Add to `backend/app/services/coco_export.py` after `build_coco_export`:

```python
def video_index_pairs(project_id: int) -> list[tuple[str, str]]:
    """(source_video, frame_stem) for every frame in the flat COCO export — the
    SAME eligible stream `build_coco_export` consumes, so the manifest matches
    the doc's images[] exactly."""
    return [
        ((item.get("payload") or {}).get("source_video") or "", src.stem)
        for item, src, _w, _h, _kps in eligible_pose_items(project_id, _NUM_KPTS)
    ]
```

- [ ] **Step 4: Run it to verify it passes**

Run: `docker compose exec backend pytest tests/test_export_video_index.py -k coco_video_index_pairs -v`
Expected: PASS.

- [ ] **Step 5: Lint + commit**

```bash
ruff check backend/app/services/coco_export.py
git add backend/app/services/coco_export.py backend/tests/test_export_video_index.py
git commit -m "feat(export): coco video_index_pairs helper"
```

---

### Task 6: Endpoint — `video_index` query param + wiring

**Files:**
- Modify: `backend/app/api/v1/items.py` — `export_project` (239-320)
- Test: `backend/tests/test_export_video_index.py` (append endpoint tests)

- [ ] **Step 1: Write the failing endpoint tests**

Append:

```python
def test_export_yolo_endpoint_video_index(client, auth_headers, pose_project):
    pid = pose_project["id"]
    _seed_frames(client, auth_headers, pid, "vid_a", [0, 1])
    _annotate(client, auth_headers, _all_items(client, auth_headers, pid))

    r = client.get(
        f"/api/v1/projects/{pid}/export?format=yolo&video_index=true", headers=auth_headers
    )
    assert r.status_code == 200
    assert "application/zip" in r.headers["content-type"]
    assert f"project_{pid}_yolo.zip" in r.headers["content-disposition"]
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    assert "video_index.csv" in zf.namelist()
    assert _index_rows(zf)["vid_a"]["num_frames"] == "2"


def test_export_json_endpoint_becomes_zip(client, auth_headers, pose_project):
    pid = pose_project["id"]
    _seed_frames(client, auth_headers, pid, "vid_a", [0])
    _annotate(client, auth_headers, _all_items(client, auth_headers, pid))

    r = client.get(
        f"/api/v1/projects/{pid}/export?format=json&video_index=true", headers=auth_headers
    )
    assert r.status_code == 200
    assert "application/zip" in r.headers["content-type"]
    assert f"project_{pid}_json.zip" in r.headers["content-disposition"]
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert set(names) == {f"project_{pid}.json", "video_index.csv"}


def test_export_csv_endpoint_becomes_zip(client, auth_headers, pose_project):
    pid = pose_project["id"]
    _seed_frames(client, auth_headers, pid, "vid_a", [0])
    _annotate(client, auth_headers, _all_items(client, auth_headers, pid))

    r = client.get(
        f"/api/v1/projects/{pid}/export?format=csv&video_index=true", headers=auth_headers
    )
    assert "application/zip" in r.headers["content-type"]
    assert f"project_{pid}_csv.zip" in r.headers["content-disposition"]


def test_export_coco_endpoint_video_index(client, auth_headers, pose_project):
    pid = pose_project["id"]
    _seed_frames(client, auth_headers, pid, "vid_a", [0, 1])
    _annotate(client, auth_headers, _all_items(client, auth_headers, pid))

    r = client.get(
        f"/api/v1/projects/{pid}/export?format=coco&video_index=true", headers=auth_headers
    )
    assert "application/zip" in r.headers["content-type"]
    assert f"project_{pid}_coco.zip" in r.headers["content-disposition"]
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    assert set(zf.namelist()) == {f"project_{pid}_coco.json", "video_index.csv"}


def test_export_json_no_flag_stays_plain(client, auth_headers, pose_project):
    pid = pose_project["id"]
    _seed_frames(client, auth_headers, pid, "vid_a", [0])
    _annotate(client, auth_headers, _all_items(client, auth_headers, pid))

    r = client.get(f"/api/v1/projects/{pid}/export?format=json", headers=auth_headers)
    assert "application/json" in r.headers["content-type"]
    assert f"project_{pid}.json" in r.headers["content-disposition"]


def test_export_yolo_split_ignores_flag(client, auth_headers, pose_project):
    pid = pose_project["id"]
    _seed_frames(client, auth_headers, pid, "vid_a", list(range(10)))
    _annotate(client, auth_headers, _all_items(client, auth_headers, pid))

    r = client.get(
        f"/api/v1/projects/{pid}/export?format=yolo_split"
        "&train=70&val=20&test=10&seed=42&video_index=true",
        headers=auth_headers,
    )
    assert "application/zip" in r.headers["content-type"]
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert "video_index.csv" not in names


def test_membership_yolo_excludes_unannotated_json_includes(client, auth_headers, pose_project):
    pid = pose_project["id"]
    _seed_frames(client, auth_headers, pid, "vid_a", [0, 1, 2])
    items = _all_items(client, auth_headers, pid)
    _annotate(client, auth_headers, items[:2])  # leave frame 2 unannotated

    ry = client.get(
        f"/api/v1/projects/{pid}/export?format=yolo&video_index=true", headers=auth_headers
    )
    yolo_rows = _index_rows(zipfile.ZipFile(io.BytesIO(ry.content)))
    assert yolo_rows["vid_a"]["num_frames"] == "2"  # annotated-only

    rj = client.get(
        f"/api/v1/projects/{pid}/export?format=json&video_index=true", headers=auth_headers
    )
    json_rows = _index_rows(zipfile.ZipFile(io.BytesIO(rj.content)))
    assert json_rows["vid_a"]["num_frames"] == "3"  # all items
```

- [ ] **Step 2: Run them to verify they fail**

Run: `docker compose exec backend pytest tests/test_export_video_index.py -k endpoint -v`
Expected: FAIL — flag is ignored, so YOLO/coco zips lack `video_index.csv` and json/csv return their plain single-file responses.

- [ ] **Step 3: Add the query param**

In `backend/app/api/v1/items.py::export_project`, add after `exclude_occluded`:

```python
    exclude_occluded: bool = Query(False),
    video_index: bool = Query(False),
) -> Response:
```

- [ ] **Step 4: Wire the COCO flat branch**

Replace the `if format == "coco":` block:

```python
        if format == "coco":
            data = coco_service.build_coco_export(project_id)
            if video_index:
                csv_text = item_service.build_video_index_csv(
                    coco_service.video_index_pairs(project_id)
                )
                stream, size = item_service.zip_bytes(
                    [
                        (f"project_{project_id}_coco.json", data),
                        ("video_index.csv", csv_text.encode("utf-8")),
                    ]
                )
                return _stream_zip(stream, size, f"project_{project_id}_coco.zip")
            return Response(
                content=data,
                media_type="application/json",
                headers={
                    "Content-Disposition": f'attachment; filename="project_{project_id}_coco.json"'
                },
            )
```

- [ ] **Step 5: Wire YOLO + bundle branches**

Change the `yolo` and `bundle` builder calls to pass the flag (ZIP name unchanged):

```python
    if format == "yolo":
        stream, size = item_service.build_yolo_export(
            project_id, exclude_occluded, video_index=video_index
        )
        return _stream_zip(stream, size, f"project_{project_id}_yolo.zip")
```

```python
    if format == "bundle":
        stream, size = item_service.build_bundle_export(project_id, video_index=video_index)
        return _stream_zip(stream, size, f"project_{project_id}_bundle.zip")
```

- [ ] **Step 6: Wire json/jsonl/csv branches**

Immediately before `if format == "json":`, add the zip short-circuit:

```python
    if video_index:
        # the text formats have no container, so wrap [native file + manifest]
        stream, size = item_service.build_text_export_zip(project_id, format)
        return _stream_zip(stream, size, f"project_{project_id}_{format}.zip")

    if format == "json":
```

(The existing `json`/`jsonl`/`csv` `StreamingResponse` returns below now handle only the flag-off path.)

- [ ] **Step 7: Run the endpoint tests + full suite**

Run: `docker compose exec backend pytest tests/test_export_video_index.py -v`
Expected: PASS (all tests in the file).

Run: `docker compose exec backend pytest`
Expected: PASS (no regression across the suite).

- [ ] **Step 8: Lint + commit**

```bash
ruff check backend/app/api/v1/items.py
git add backend/app/api/v1/items.py backend/tests/test_export_video_index.py
git commit -m "feat(export): video_index query param wiring"
```

---

### Task 7: Frontend — flag plumbing + modal checkbox

**Files:**
- Modify: `frontend/src/lib/download.ts` — `DownloadOptions`, `downloadExport`
- Modify: `frontend/src/pages/ProjectDetailPage.tsx` — export modal (state ~112, `handleExport` ~122, render ~656)

- [ ] **Step 1: Add the `videoIndex` option + zip filename in `download.ts`**

In `DownloadOptions`, add the field:

```typescript
export interface DownloadOptions {
  onProgress?: (p: DownloadProgress) => void;
  signal?: AbortSignal;
  split?: { train: number; val: number; test: number; seed: number };
  excludeOccluded?: boolean;
  videoIndex?: boolean;
}
```

In `downloadExport`, after the `exclude_occluded` param block, add:

```typescript
  if (opts?.videoIndex) {
    params.video_index = true;
  }
```

Replace the `a.download = ...` line so the single-file formats become `.zip` when the flag is on:

```typescript
  let name = archiveNames[format] ?? `project_${projectId}.${format}`;
  if (
    opts?.videoIndex &&
    (format === 'coco' || format === 'json' || format === 'jsonl' || format === 'csv')
  ) {
    // backend wraps these in a zip when video_index is set
    name = `project_${projectId}_${format}.zip`;
  }
  a.download = name;
```

- [ ] **Step 2: Add modal state + pass the flag in `ProjectDetailPage.tsx`**

After `const [excludeOccluded, setExcludeOccluded] = useState(false);` (~line 112):

```typescript
  const [videoIndex, setVideoIndex] = useState(false);
```

In `handleExport`, add to the `downloadExport` options object (after `excludeOccluded`):

```typescript
        videoIndex:
          fmt === 'yolo_split' || fmt === 'coco_split' ? undefined : videoIndex,
```

- [ ] **Step 3: Render the checkbox (flat formats only)**

Immediately after the `excludeOccluded` `</label>` block closes (the `)}` at ~line 656), add:

```tsx
              {exportFormat !== 'yolo_split' && exportFormat !== 'coco_split' && (
                <label className="flex items-start gap-2 text-xs text-slate-600 cursor-pointer border-t pt-2 mt-1">
                  <input
                    type="checkbox"
                    checked={videoIndex}
                    onChange={(e) => setVideoIndex(e.target.checked)}
                    className="mt-0.5"
                  />
                  <span>
                    Incluir índice de vídeos (video_index.csv)
                    <span className="block text-slate-400">
                      início/fim dos frames por vídeo; json/jsonl/csv/coco saem como .zip
                    </span>
                  </span>
                </label>
              )}
```

- [ ] **Step 4: Typecheck**

Run: `cd frontend && npx tsc -b --noEmit`
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/download.ts frontend/src/pages/ProjectDetailPage.tsx
git commit -m "feat(export-ui): video index checkbox for flat exports"
```

---

## Done criteria

- `?format=yolo&video_index=true` (and `bundle`) → same ZIP name, now containing `video_index.csv`.
- `?format=coco|json|jsonl|csv&video_index=true` → `project_<id>_<fmt>.zip` = native file + `video_index.csv`.
- Flag off → every export byte-identical to today; split formats ignore the flag.
- `video_index.csv` columns `source_video,first_frame,last_frame,num_frames` reflect exactly the frames in that export (annotated-only for yolo/coco; all rows for bundle/json/jsonl/csv).
- `docker compose exec backend pytest` green; `npx tsc -b --noEmit` clean.

## Spec reference

`docs/superpowers/specs/2026-06-14-export-video-index-design.md`
