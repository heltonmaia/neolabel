# YOLO-pose train/val/test split export — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `yolo_split` export format that produces a reproducible, user-configurable train/val/test YOLO-pose dataset ZIP, alongside the existing flat `yolo` export.

**Architecture:** Refactor the existing `build_yolo_export` to share its per-item label math and schema metadata via two helpers, then add a `build_yolo_split_export` that shuffles the eligible records with a seeded RNG and partitions them into `images/{train,val,test}` + `labels/{train,val,test}`. The export endpoint gains the `yolo_split` format plus `train/val/test/seed` query params (validated to sum to 100). The frontend export modal gains a new radio that reveals ratio + seed inputs and gates the download button on a valid sum.

**Tech Stack:** Python 3.12 / FastAPI / Pydantic v2 (backend), pytest + httpx TestClient (tests), React 18 + TypeScript + Tailwind (frontend). Backend tests run inside the container: `docker compose exec backend pytest`.

**Reference spec:** `docs/superpowers/specs/2026-05-30-yolo-pose-split-export-design.md`

---

## Background the engineer needs

- **All backend I/O goes through `app/core/storage.py`.** Services are sync and call `storage.*`. Don't read/write files directly except the media paths under `settings.DATA_DIR` (the YOLO builders already do this for source frames).
- **Export endpoint** is `GET /projects/{project_id}/export` in `backend/app/api/v1/items.py`. It streams ZIPs via the local `_stream_zip(stream, size, filename)` helper, which expects a file-like positioned at 0 plus its byte size.
- **`build_yolo_export`** lives in `backend/app/services/item.py` (around lines 523–637 at time of writing). It spools to a `tempfile.SpooledTemporaryFile(max_size=64 MiB)` so large projects don't pin RAM. The YOLO label line is `0 cx cy w h  x1 y1 v1 ... xN yN vN` (all normalized), bbox is the visible-keypoint bounding box padded 10% per side.
- **Keypoint schema** comes from `project["keypoint_schema"]` (`"infant"` → 17 COCO kpts, `"rodent"` → 7 kpts). Default is `"infant"` when the field is absent.
- **Tests** use fixtures `client`, `auth_headers`, `project` (a `pose_detection` project owned by the auth user) and the `_tiny_jpeg(w, h)` helper in `backend/tests/test_items_api.py`. Each test isolates `DATA_DIR`; `tmp_path` in those tests is the data root, so frames go under `tmp_path / "projects" / str(project["id"]) / "frames" / ...`.
- **Frontend never sets `Authorization`** — the axios interceptor handles it. Export download goes through `frontend/src/lib/download.ts::downloadExport`.
- **Run backend tests:** `docker compose exec backend pytest backend/tests/test_items_api.py -v` (or `-k <name>` for one test). If the container path differs, the working dir inside the backend container is the repo's `backend/`, so `pytest tests/test_items_api.py` also works — both forms are shown per task; use whichever your container resolves.

---

## File structure

**Modified:**
- `backend/app/services/item.py` — extract `_yolo_schema_meta` + `_yolo_records` helpers from `build_yolo_export`; add `build_yolo_split_export`. Add `import random`.
- `backend/app/api/v1/items.py` — extend `format` regex with `yolo_split`; add `train/val/test/seed` query params; branch to the new builder with sum validation.
- `backend/tests/test_items_api.py` — new split-export tests.
- `SPEC.md` — document the `yolo_split` format + params.
- `frontend/src/lib/download.ts` — widen `ExportFormat`; append split params + filename for `yolo_split`.
- `frontend/src/api/items.ts` — widen the `exportUrl` format union (kept consistent even though `downloadExport` is the live path).
- `frontend/src/pages/ProjectDetailPage.tsx` — new radio option, ratio/seed inputs, sum gating, pass params through `handleExport`.

No new files.

---

## Task 1: Backend refactor — extract shared YOLO helpers (no behavior change)

**Files:**
- Modify: `backend/app/services/item.py`
- Test: `backend/tests/test_items_api.py` (existing `test_export_yolo_zip_contains_dataset` is the regression guard)

- [ ] **Step 1: Run the existing YOLO test to confirm green baseline**

Run: `docker compose exec backend pytest tests/test_items_api.py::test_export_yolo_zip_contains_dataset -v`
Expected: PASS (1 passed)

- [ ] **Step 2: Add `import random` to the imports block**

In `backend/app/services/item.py`, the top imports are:

```python
import csv
import io
import json
import tempfile
import zipfile
```

Change to (keep alphabetical):

```python
import csv
import io
import json
import random
import tempfile
import zipfile
```

- [ ] **Step 3: Replace `build_yolo_export` with two helpers + a thin builder**

Find the current `def build_yolo_export(project_id: int) -> tuple[BinaryIO, int]:` block (ends at `return spooled, size`). Replace the **entire** function with the following three definitions. The per-item math is copied verbatim from the original loop — do not change any number.

```python
def _yolo_schema_meta(project: dict) -> tuple[int, list[int], str, str]:
    """Return (num_kpts, flip_idx, class_name, schema_label) for a pose project.

    `infant` → 17 COCO keypoints (default when the field predates the schema).
    `rodent` → 7 keypoints (N, LEar, REar, BC, TB, TM, TT) for OF / EPM.
    """
    schema = project.get("keypoint_schema") or "infant"
    if schema == "rodent":
        # Top-down horizontal flip: LEar (1) and REar (2) swap; rest self-map.
        return 7, [0, 2, 1, 3, 4, 5, 6], "rodent", (
            "rodent (7 keypoints: N, LEar, REar, BC, TB, TM, TT)"
        )
    # COCO horizontal-flip index: swaps left<->right joints.
    return (
        17,
        [0, 2, 1, 4, 3, 6, 5, 8, 7, 10, 9, 12, 11, 14, 13, 16, 15],
        "person",
        "COCO 17 keypoints",
    )


def _yolo_records(project_id: int, num_kpts: int) -> Iterator[tuple[Path, str, str]]:
    """Yield (src_path, stem, label_line) for every export-eligible item.

    Eligibility (all must hold): has an annotation, keypoint count matches the
    project schema, `image_url` is under `/files/`, the source frame exists on
    disk, its JPEG dims are readable, and at least one keypoint is visible.
    The label line is the normalized YOLO-pose row `0 cx cy w h x1 y1 v1 ...`.
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
        src = data_root / image_url[len("/files/"):]
        if not src.exists():
            continue
        dims = _jpeg_size(src)
        if not dims:
            continue
        w, h = dims

        visible_pts = [(x, y) for x, y, v in kps if v > 0]
        if not visible_pts:
            continue
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

        kp_str = " ".join(f"{x / w:.6f} {y / h:.6f} {int(v)}" for x, y, v in kps)
        label_line = f"0 {cx:.6f} {cy:.6f} {bw:.6f} {bh:.6f} {kp_str}\n"
        stem = f"{item['id']:06d}_{src.stem}"
        yield src, stem, label_line


def build_yolo_export(project_id: int) -> tuple[BinaryIO, int]:
    """Build a flat YOLO-pose dataset ZIP (Ultralytics format).

    Everything lands in images/train + labels/train; data.yaml points both
    train and val at images/train. Spills to disk past 64 MiB. Returns a
    file-like at position 0 plus its byte size; caller must close() it.
    """
    project = storage.load_project(project_id) or {}
    num_kpts, flip_idx, class_name, schema_label = _yolo_schema_meta(project)

    spooled = tempfile.SpooledTemporaryFile(max_size=64 * 1024 * 1024, mode="w+b")
    with zipfile.ZipFile(spooled, "w", zipfile.ZIP_DEFLATED) as zf:
        # NOTE: intentionally no `path:` key. Ultralytics resolves relative
        # train/val against `path`; when missing it falls back to the yaml
        # file's own parent (see ultralytics/data/utils.py check_det_dataset).
        zf.writestr(
            "data.yaml",
            f"# YOLO-pose dataset ({schema_label})\n"
            "train: images/train\n"
            "val: images/train\n"
            f"kpt_shape: [{num_kpts}, 3]\n"
            f"flip_idx: {flip_idx}\n"
            f"names:\n  0: {class_name}\n",
        )

        exported = 0
        for src, stem, label_line in _yolo_records(project_id, num_kpts):
            zf.write(src, f"images/train/{stem}{src.suffix}")
            zf.writestr(f"labels/train/{stem}.txt", label_line)
            exported += 1

        zf.writestr(
            "README.txt",
            f"NeoLabel YOLO-pose export\n"
            f"Project: {project_id}\n"
            f"Exported: {exported} annotated frames\n"
            f"Format: Ultralytics YOLO-pose, {schema_label}\n"
            f"Train with e.g.:\n"
            f"  yolo pose train data=data.yaml model=yolo11n-pose.pt epochs=100\n"
            f"(same yaml works for YOLOv8/v11/v12/v26 pose.)\n",
        )

    size = spooled.tell()
    spooled.seek(0)
    return spooled, size
```

- [ ] **Step 4: Run the existing YOLO test to confirm no behavior change**

Run: `docker compose exec backend pytest tests/test_items_api.py::test_export_yolo_zip_contains_dataset -v`
Expected: PASS (1 passed) — byte-identical output, same `images/train/` + `labels/train/` layout.

- [ ] **Step 5: Run the full export test group as a sanity check**

Run: `docker compose exec backend pytest tests/test_items_api.py -k export -v`
Expected: all export tests PASS.

- [ ] **Step 6: Lint**

Run: `ruff check backend && ruff format backend`
Expected: no errors (format may reformat; that's fine).

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/item.py
git commit -m "refactor(yolo-export): extract shared schema + record helpers"
```

---

## Task 2: Backend — `build_yolo_split_export`

**Files:**
- Modify: `backend/app/services/item.py`
- Test: `backend/tests/test_items_api.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_items_api.py`. This builds 10 annotated frames, exports a 70/20/10 split, and asserts the partition is loss-free, reproducible, and correctly shaped. It calls the service directly (no HTTP) to keep the unit focused.

```python
def _seed_pose_items(client, auth_headers, project, tmp_path, n):
    """Create n annotated 17-keypoint pose items with real on-disk JPEGs."""
    iids = []
    for k in range(n):
        rel = f"projects/{project['id']}/frames/vid/f_{k:06d}.jpg"
        img_path = tmp_path / rel
        img_path.parent.mkdir(parents=True, exist_ok=True)
        img_path.write_bytes(_tiny_jpeg(640, 480))
        client.post(
            f"/api/v1/projects/{project['id']}/items/bulk",
            json={"items": [{"payload": {"image_url": f"/files/{rel}"}}]},
            headers=auth_headers,
        )
    items = client.get(
        f"/api/v1/projects/{project['id']}/items?limit=500", headers=auth_headers
    ).json()["items"]
    full = [[10 + i * 5, 20 + i * 5, 2] for i in range(17)]
    for it in items:
        client.put(
            f"/api/v1/items/{it['id']}/annotation",
            json={"value": {"keypoints": full}},
            headers=auth_headers,
        )
        iids.append(it["id"])
    return iids


def test_build_yolo_split_partitions_without_loss(
    client, auth_headers, project, tmp_path
):
    import io
    import zipfile

    from app.services import item as item_service

    _seed_pose_items(client, auth_headers, project, tmp_path, 10)

    stream, size = item_service.build_yolo_split_export(
        project["id"], train=70, val=20, test=10, seed=42
    )
    try:
        zf = zipfile.ZipFile(io.BytesIO(stream.read()))
    finally:
        stream.close()
    names = zf.namelist()

    def imgs(split):
        return [n for n in names if n.startswith(f"images/{split}/")]

    assert len(imgs("train")) == 7
    assert len(imgs("val")) == 2
    assert len(imgs("test")) == 1
    # every frame placed exactly once
    total = len(imgs("train")) + len(imgs("val")) + len(imgs("test"))
    assert total == 10
    yaml_text = zf.read("data.yaml").decode()
    assert "train: images/train" in yaml_text
    assert "val: images/val" in yaml_text
    assert "test: images/test" in yaml_text
    assert "path:" not in yaml_text
    assert "kpt_shape: [17, 3]" in yaml_text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `docker compose exec backend pytest tests/test_items_api.py::test_build_yolo_split_partitions_without_loss -v`
Expected: FAIL with `AttributeError: module 'app.services.item' has no attribute 'build_yolo_split_export'`

- [ ] **Step 3: Implement `build_yolo_split_export`**

Add this function in `backend/app/services/item.py` directly after `build_yolo_export`:

```python
def build_yolo_split_export(
    project_id: int, train: int, val: int, test: int, seed: int
) -> tuple[BinaryIO, int]:
    """Build a YOLO-pose dataset ZIP split into train/val/test (Ultralytics).

    Ratios are integer percentages that the caller has already validated to
    sum to 100. The eligible records (same filter as the flat export) are
    shuffled with a seeded RNG and partitioned by floor counts; the catch-all
    split takes the remainder so no frame is dropped. When test == 0 the test
    folders and the data.yaml `test:` key are omitted and val is the catch-all.

    Layout:
        data.yaml
        images/{train,val,test}/<stem>.jpg
        labels/{train,val,test}/<stem>.txt
    """
    project = storage.load_project(project_id) or {}
    num_kpts, flip_idx, class_name, schema_label = _yolo_schema_meta(project)

    records = list(_yolo_records(project_id, num_kpts))
    random.Random(seed).shuffle(records)
    n = len(records)
    n_train = n * train // 100
    n_val = n * val // 100

    if test > 0:
        splits = [
            ("train", records[:n_train]),
            ("val", records[n_train:n_train + n_val]),
            ("test", records[n_train + n_val:]),
        ]
    else:
        # val is the catch-all so flooring never drops the remainder.
        splits = [
            ("train", records[:n_train]),
            ("val", records[n_train:]),
        ]

    spooled = tempfile.SpooledTemporaryFile(max_size=64 * 1024 * 1024, mode="w+b")
    with zipfile.ZipFile(spooled, "w", zipfile.ZIP_DEFLATED) as zf:
        yaml_lines = [
            f"# YOLO-pose dataset ({schema_label})",
            "train: images/train",
            "val: images/val",
        ]
        if test > 0:
            yaml_lines.append("test: images/test")
        yaml_lines += [
            f"kpt_shape: [{num_kpts}, 3]",
            f"flip_idx: {flip_idx}",
            "names:",
            f"  0: {class_name}",
            "",
        ]
        zf.writestr("data.yaml", "\n".join(yaml_lines))

        counts: dict[str, int] = {}
        for split_name, recs in splits:
            counts[split_name] = len(recs)
            for src, stem, label_line in recs:
                zf.write(src, f"images/{split_name}/{stem}{src.suffix}")
                zf.writestr(f"labels/{split_name}/{stem}.txt", label_line)

        count_str = ", ".join(f"{k}={v}" for k, v in counts.items())
        zf.writestr(
            "README.txt",
            f"NeoLabel YOLO-pose split export\n"
            f"Project: {project_id}\n"
            f"Format: Ultralytics YOLO-pose, {schema_label}\n"
            f"Split: train={train}% val={val}% test={test}% (seed={seed})\n"
            f"Frames per split: {count_str}\n"
            f"Train with e.g.:\n"
            f"  yolo pose train data=data.yaml model=yolo11n-pose.pt epochs=100\n"
            f"(same yaml works for YOLOv8/v11/v12/v26 pose.)\n",
        )

    size = spooled.tell()
    spooled.seek(0)
    return spooled, size
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `docker compose exec backend pytest tests/test_items_api.py::test_build_yolo_split_partitions_without_loss -v`
Expected: PASS

- [ ] **Step 5: Add reproducibility + test=0 unit tests**

Append to `backend/tests/test_items_api.py`:

```python
def test_build_yolo_split_is_reproducible_for_a_seed(
    client, auth_headers, project, tmp_path
):
    import io
    import zipfile

    from app.services import item as item_service

    _seed_pose_items(client, auth_headers, project, tmp_path, 12)

    def split_map(seed):
        stream, _ = item_service.build_yolo_split_export(
            project["id"], train=70, val=20, test=10, seed=seed
        )
        try:
            names = zipfile.ZipFile(io.BytesIO(stream.read())).namelist()
        finally:
            stream.close()
        # map each frame stem -> its split
        out = {}
        for n in names:
            for split in ("train", "val", "test"):
                prefix = f"images/{split}/"
                if n.startswith(prefix):
                    out[n[len(prefix):]] = split
        return out

    assert split_map(42) == split_map(42)          # same seed -> identical
    assert split_map(42) != split_map(7)           # different seed -> differs


def test_build_yolo_split_test_zero_omits_test(
    client, auth_headers, project, tmp_path
):
    import io
    import zipfile

    from app.services import item as item_service

    _seed_pose_items(client, auth_headers, project, tmp_path, 10)

    stream, _ = item_service.build_yolo_split_export(
        project["id"], train=80, val=20, test=0, seed=42
    )
    try:
        zf = zipfile.ZipFile(io.BytesIO(stream.read()))
    finally:
        stream.close()
    names = zf.namelist()
    assert not any(n.startswith("images/test/") for n in names)
    assert not any(n.startswith("labels/test/") for n in names)
    assert "test:" not in zf.read("data.yaml").decode()
    # no frame lost: train + val == 10
    n_train = len([n for n in names if n.startswith("images/train/")])
    n_val = len([n for n in names if n.startswith("images/val/")])
    assert n_train + n_val == 10


def test_build_yolo_split_tiny_dataset_does_not_crash(
    client, auth_headers, project, tmp_path
):
    import io
    import zipfile

    from app.services import item as item_service

    _seed_pose_items(client, auth_headers, project, tmp_path, 3)

    stream, _ = item_service.build_yolo_split_export(
        project["id"], train=70, val=20, test=10, seed=42
    )
    try:
        names = zipfile.ZipFile(io.BytesIO(stream.read())).namelist()
    finally:
        stream.close()
    total = len([n for n in names if n.startswith("images/")])
    assert total == 3  # every frame placed exactly once, no crash
```

- [ ] **Step 6: Run the new tests**

Run: `docker compose exec backend pytest tests/test_items_api.py -k "yolo_split" -v`
Expected: 4 passed.

- [ ] **Step 7: Lint**

Run: `ruff check backend && ruff format backend`
Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/item.py backend/tests/test_items_api.py
git commit -m "feat(yolo-export): seeded train/val/test split builder"
```

---

## Task 3: Backend — wire `yolo_split` into the export endpoint

**Files:**
- Modify: `backend/app/api/v1/items.py`
- Test: `backend/tests/test_items_api.py`

- [ ] **Step 1: Write the failing endpoint tests**

Append to `backend/tests/test_items_api.py`:

```python
def test_export_yolo_split_endpoint(client, auth_headers, project, tmp_path):
    import io
    import zipfile

    _seed_pose_items(client, auth_headers, project, tmp_path, 10)

    r = client.get(
        f"/api/v1/projects/{project['id']}/export"
        "?format=yolo_split&train=70&val=20&test=10&seed=42",
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert "project_%d_yolo_split.zip" % project["id"] in r.headers[
        "content-disposition"
    ]
    names = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
    assert "data.yaml" in names
    assert any(n.startswith("images/train/") for n in names)
    assert any(n.startswith("images/val/") for n in names)


def test_export_yolo_split_rejects_bad_ratio_sum(client, auth_headers, project):
    r = client.get(
        f"/api/v1/projects/{project['id']}/export"
        "?format=yolo_split&train=70&val=20&test=20&seed=42",
        headers=auth_headers,
    )
    assert r.status_code == 422
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `docker compose exec backend pytest tests/test_items_api.py -k "yolo_split_endpoint or bad_ratio" -v`
Expected: FAIL — the first returns 422 (format regex rejects `yolo_split`); both fail their assertions.

- [ ] **Step 3: Extend the export endpoint**

In `backend/app/api/v1/items.py`, find `export_project`. Update the signature to add the format value and the four query params:

```python
@router.get("/projects/{project_id}/export", tags=["items"])
def export_project(
    project_id: int,
    current_user: CurrentUser,
    format: str = Query(
        "json", pattern="^(json|jsonl|csv|yolo|bundle|yolo_split)$"
    ),
    train: int = Query(70, ge=0, le=100),
    val: int = Query(20, ge=0, le=100),
    test: int = Query(10, ge=0, le=100),
    seed: int = Query(42),
) -> Response:
    _require_project_for_owner(project_id, current_user)
```

Then, immediately after the existing `if format == "yolo":` block (which returns the flat export), add the `yolo_split` branch:

```python
    if format == "yolo_split":
        if train + val + test != 100:
            raise HTTPException(
                status_code=422,
                detail="train + val + test must sum to 100",
            )
        stream, size = item_service.build_yolo_split_export(
            project_id, train, val, test, seed
        )
        return _stream_zip(stream, size, f"project_{project_id}_yolo_split.zip")
```

(Leave the `yolo`, `bundle`, `json`, `jsonl`, `csv` branches exactly as they are. `HTTPException` and `Query` are already imported.)

- [ ] **Step 4: Run the endpoint tests to verify they pass**

Run: `docker compose exec backend pytest tests/test_items_api.py -k "yolo_split_endpoint or bad_ratio" -v`
Expected: 2 passed.

- [ ] **Step 5: Run the whole export test group**

Run: `docker compose exec backend pytest tests/test_items_api.py -k export -v`
Expected: all PASS (existing format-rejection test still 422s on `xml`).

- [ ] **Step 6: Lint**

Run: `ruff check backend && ruff format backend`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/v1/items.py backend/tests/test_items_api.py
git commit -m "feat(export): add yolo_split format with seed and ratio params"
```

---

## Task 4: SPEC.md — document the new format

**Files:**
- Modify: `SPEC.md`

- [ ] **Step 1: Locate the export documentation**

Run: `grep -n "yolo\|export\|format=" SPEC.md`
Expected: lines describing the export endpoint / formats. Read the surrounding section.

- [ ] **Step 2: Add the `yolo_split` description**

In the export section of `SPEC.md`, add a bullet/paragraph next to the existing `yolo` description. Use this text (adapt the surrounding markdown style to match the file):

```markdown
- `yolo_split` — same Ultralytics YOLO-pose dataset as `yolo`, but
  partitioned into `images/{train,val,test}` + `labels/{train,val,test}`
  from a seeded random shuffle. Query params: `train`, `val`, `test`
  (integer percentages, each 0–100, **must sum to 100**; default
  70/20/10) and `seed` (integer, default 42). A given seed + the same
  eligible frames always yields the same split. When `test=0`, the test
  folders and the `test:` key in `data.yaml` are omitted and `val`
  absorbs the rounding remainder. Annotated-only, like `yolo`.
```

- [ ] **Step 3: Commit**

```bash
git add SPEC.md
git commit -m "docs(spec): document yolo_split export format"
```

---

## Task 5: Frontend — download helper + API types

**Files:**
- Modify: `frontend/src/lib/download.ts`
- Modify: `frontend/src/api/items.ts`

- [ ] **Step 1: Widen `ExportFormat` and pass split params in `download.ts`**

In `frontend/src/lib/download.ts`, change the `ExportFormat` type:

```typescript
export type ExportFormat = 'json' | 'jsonl' | 'csv' | 'yolo' | 'bundle' | 'yolo_split';
```

Add an optional split-config field to `DownloadOptions`:

```typescript
export interface DownloadOptions {
  onProgress?: (p: DownloadProgress) => void;
  signal?: AbortSignal;
  split?: { train: number; val: number; test: number; seed: number };
}
```

In `downloadExport`, build the request params so the split config is attached only for `yolo_split`, and add the filename case. Replace the `const res = await api.get(...)` params and the `a.download` assignment:

```typescript
  const params: Record<string, string | number> =
    format === 'yolo_split' && opts?.split
      ? { format, ...opts.split }
      : { format };
  const res = await api.get(`/projects/${projectId}/export`, {
    params,
    responseType: 'blob',
    signal: opts?.signal,
    onDownloadProgress: (e) => {
      if (!opts?.onProgress) return;
      const total = typeof e.total === 'number' && e.total > 0 ? e.total : null;
      opts.onProgress({ loaded: e.loaded ?? 0, total });
    },
  });
  const url = URL.createObjectURL(res.data);
  const a = document.createElement('a');
  a.href = url;
  a.download =
    format === 'yolo'
      ? `project_${projectId}_yolo.zip`
      : format === 'yolo_split'
        ? `project_${projectId}_yolo_split.zip`
        : format === 'bundle'
          ? `project_${projectId}_bundle.zip`
          : `project_${projectId}.${format}`;
  a.click();
  URL.revokeObjectURL(url);
```

- [ ] **Step 2: Keep the `exportUrl` union consistent in `items.ts`**

In `frontend/src/api/items.ts`, widen the `exportUrl` signature (it is not the live download path but should not contradict the new format):

```typescript
export function exportUrl(
  projectId: number,
  format: 'json' | 'jsonl' | 'csv' | 'yolo' | 'bundle' | 'yolo_split',
) {
  return `/projects/${projectId}/export?format=${format}`;
}
```

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npx tsc -b --noEmit`
Expected: no errors (no `.js` emitted into `src/`).

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/download.ts frontend/src/api/items.ts
git commit -m "feat(export-ui): download.ts support for yolo_split params"
```

---

## Task 6: Frontend — export modal radio + ratio/seed inputs

**Files:**
- Modify: `frontend/src/pages/ProjectDetailPage.tsx`

- [ ] **Step 1: Widen the format unions and add split state**

Find the export state declarations (the `useState` for `exportFormat` and `exportProgress`). Update both union types to include `'yolo_split'`, and add the split-config state. Replace:

```typescript
  const [exportFormat, setExportFormat] = useState<
    'json' | 'jsonl' | 'csv' | 'yolo' | 'bundle'
  >('json');
  const [exportProgress, setExportProgress] = useState<
    | null
    | {
        format: 'json' | 'jsonl' | 'csv' | 'yolo' | 'bundle';
        loaded: number;
        total: number | null;
      }
  >(null);
```

with:

```typescript
  const [exportFormat, setExportFormat] = useState<
    'json' | 'jsonl' | 'csv' | 'yolo' | 'bundle' | 'yolo_split'
  >('json');
  const [exportProgress, setExportProgress] = useState<
    | null
    | {
        format: 'json' | 'jsonl' | 'csv' | 'yolo' | 'bundle' | 'yolo_split';
        loaded: number;
        total: number | null;
      }
  >(null);
  const [splitCfg, setSplitCfg] = useState({ train: 70, val: 20, test: 10, seed: 42 });
  const splitSum = splitCfg.train + splitCfg.val + splitCfg.test;
```

- [ ] **Step 2: Pass the split config through `handleExport`**

In `handleExport`, update the `downloadExport` call to forward the split config when relevant:

```typescript
      await downloadExport(projectId, fmt, {
        signal: controller.signal,
        onProgress: (p) => setExportProgress({ format: fmt, loaded: p.loaded, total: p.total }),
        split: fmt === 'yolo_split' ? splitCfg : undefined,
      });
```

- [ ] **Step 3: Add the radio option**

In the export modal, find the options array. Add `yolo_split` to the pose-only block, after the `yolo` entry:

```typescript
                  ...(isPose
                    ? ([
                        { v: 'yolo', label: 'YOLO-pose (ZIP)', hint: 'Ultralytics, COCO 17 kp' },
                        {
                          v: 'yolo_split',
                          label: 'YOLO-pose split (ZIP)',
                          hint: 'train / valid / test, seeded',
                        },
                        {
                          v: 'bundle',
                          label: 'Full bundle (ZIP)',
                          hint: 'annotations.json + all source images',
                        },
                      ] as const)
                    : []),
```

- [ ] **Step 4: Add the ratio/seed inputs and gate the download button**

Directly **before** the `<button onClick={handleExport} ...>` element in the modal, insert the split config panel (shown only when `yolo_split` is selected):

```tsx
              {exportFormat === 'yolo_split' && (
                <div className="border-t pt-2 mt-1 space-y-2">
                  <div className="grid grid-cols-3 gap-2">
                    {(['train', 'val', 'test'] as const).map((k) => (
                      <label key={k} className="text-xs text-slate-600">
                        <span className="block mb-0.5 capitalize">
                          {k === 'val' ? 'valid' : k} %
                        </span>
                        <input
                          type="number"
                          min={0}
                          max={100}
                          value={splitCfg[k]}
                          onChange={(e) =>
                            setSplitCfg((c) => ({
                              ...c,
                              [k]: Number(e.target.value),
                            }))
                          }
                          className="w-full border rounded px-1.5 py-1 text-sm"
                        />
                      </label>
                    ))}
                  </div>
                  <label className="text-xs text-slate-600 block">
                    <span className="block mb-0.5">Seed</span>
                    <input
                      type="number"
                      value={splitCfg.seed}
                      onChange={(e) =>
                        setSplitCfg((c) => ({ ...c, seed: Number(e.target.value) }))
                      }
                      className="w-full border rounded px-1.5 py-1 text-sm"
                    />
                  </label>
                  <p
                    className={`text-xs ${
                      splitSum === 100 ? 'text-slate-500' : 'text-red-600'
                    }`}
                  >
                    Sum: {splitSum}% {splitSum === 100 ? '' : '(must be 100)'}
                  </p>
                </div>
              )}
```

Then update the download button's `disabled` prop to also block on an invalid sum:

```tsx
              <button
                onClick={handleExport}
                disabled={!!exportProgress || (exportFormat === 'yolo_split' && splitSum !== 100)}
                className="w-full bg-blue-600 text-white text-sm rounded px-3 py-1.5 hover:bg-blue-700 disabled:bg-slate-300"
              >
                {exportProgress ? 'Downloading…' : 'Download'}
              </button>
```

- [ ] **Step 5: Typecheck**

Run: `cd frontend && npx tsc -b --noEmit`
Expected: no errors.

- [ ] **Step 6: Lint**

Run: `cd frontend && npm run lint`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/ProjectDetailPage.tsx
git commit -m "feat(export-ui): YOLO-pose split option with ratio + seed inputs"
```

---

## Task 7: Final verification

**Files:** none (verification only)

- [ ] **Step 1: Full backend suite**

Run: `docker compose exec backend pytest`
Expected: all tests PASS (no regressions across the suite).

- [ ] **Step 2: Frontend build**

Run: `cd frontend && npm run build`
Expected: `tsc -b` clean + `vite build` succeeds into `dist/`.

- [ ] **Step 3: Manual smoke (optional but recommended)**

With the dev stack up (`docker compose up -d`), open a pose project, click Export, choose **YOLO-pose split (ZIP)**, confirm:
- the ratio/seed inputs appear,
- the Download button disables when the percentages don't sum to 100,
- a download named `project_<id>_yolo_split.zip` arrives and unzips to `images/{train,val,test}` + `labels/{train,val,test}` + `data.yaml`.

- [ ] **Step 4: Confirm clean tree**

Run: `git status`
Expected: clean (all changes committed across Tasks 1–6).

---

## Self-review notes

- **Spec coverage:** new format value (T3), ratio+seed params (T3), sum-to-100 422 (T3), Ultralytics layout (T2), seeded reproducible shuffle (T2), `test=0` omits test folders/yaml key (T2), tiny-dataset safety (T2), shared label math via refactor (T1), SPEC update (T4), frontend separate radio + configurable inputs + sum gating (T5/T6). All spec sections map to a task.
- **Type consistency:** `build_yolo_split_export(project_id, train, val, test, seed)` signature is identical across the service, the endpoint call (T3), and tests (T2). `ExportFormat` includes `'yolo_split'` in `download.ts`, `items.ts`, and both unions in `ProjectDetailPage.tsx`. The `split` option shape `{train, val, test, seed}` matches between `DownloadOptions` (T5) and `splitCfg` (T6).
- **Catch-all remainder:** when `test=0`, `val` is the catch-all (`records[n_train:]`) so flooring never drops frames — covered by `test_build_yolo_split_test_zero_omits_test`.
