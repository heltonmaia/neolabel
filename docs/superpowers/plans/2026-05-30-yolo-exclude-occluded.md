# YOLO export `exclude_occluded` flag — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in `exclude_occluded` flag to the YOLO-pose exports (`yolo` and `yolo_split`) that demotes occluded keypoints (`v=1`) to `v=0`/`[0,0,0]` in the label line — removing them from keypoint training supervision while keeping them in the bounding box.

**Architecture:** The flag is threaded through the shared `_yolo_records` generator in `backend/app/services/item.py`, so both `build_yolo_export` and `build_yolo_split_export` honor it with a single logic change (the per-keypoint string construction). The export endpoint gains a `exclude_occluded: bool` query param passed to both builders. The frontend export modal gains a checkbox shown for the two YOLO formats; `download.ts` sends the param.

**Tech Stack:** Python 3.12 / FastAPI / Pydantic v2 (backend), pytest + httpx TestClient (tests), React 18 + TypeScript + Tailwind (frontend).

**Reference spec:** `docs/superpowers/specs/2026-05-30-yolo-exclude-occluded-design.md`

**Branch:** all work happens on `feat/yolo-exclude-occluded` (the controller creates it before Task 1; do not commit to `main`).

---

## Background the engineer needs

- Visibility flags on stored keypoints: `2` = visible, `1` = occluded (real coords, "covered"), `0` = not labeled / out-of-frame (`[0,0,0]`). See SPEC §2.
- `_yolo_records(project_id, num_kpts)` is the single place that turns an annotated item into a `(src_path, stem, label_line)` record. Both YOLO builders consume it. The label line is `0 cx cy w h  x1 y1 v1 ... xN yN vN` (all normalized; `cx cy w h` is the bbox).
- The bbox is computed from `visible_pts = [(x, y) for x, y, v in kps if v > 0]` — occluded points are **included** in the box. This plan does **not** change that.
- Backend tests run **inside the container as a module**: `docker compose exec -T backend python -m pytest tests/<file>::<test> -v` (always `-T`, always `python -m pytest`). The dev stack is up and pytest/ruff are installed in the container.
- Lint must be **scoped to changed files**: `ruff check <files>` / `ruff format <files>` — never `ruff format backend` (it churns unrelated files). A pre-existing `E741` at `backend/app/services/item.py:286` is unrelated — ignore it.
- Frontend has **no test suite**; verify with `cd frontend && npx tsc -b --noEmit` (must be clean; if `.js` files appear under `src/`, delete them — they are gitignored). `npm run lint` is broken in this checkout (no eslint config) — do not use it as a gate.
- Commits in this repo omit the `Co-Authored-By` trailer. Never `git add` CLAUDE.md (gitignored).

---

## File structure

**Modified:**
- `backend/app/services/item.py` — `_yolo_records` gains `exclude_occluded` kwarg; both builders thread it through + a README note.
- `backend/app/api/v1/items.py` — `export_project` gains `exclude_occluded: bool` query param, passed to both builders.
- `backend/tests/test_items_api.py` — new tests.
- `frontend/src/lib/download.ts` — `DownloadOptions.excludeOccluded`; send param for `yolo`/`yolo_split`.
- `frontend/src/pages/ProjectDetailPage.tsx` — checkbox + `handleExport` plumbing.

No new files.

---

## Task 1: Backend — thread `exclude_occluded` through the record generator and both builders

**Files:**
- Modify: `backend/app/services/item.py`
- Test: `backend/tests/test_items_api.py`

- [ ] **Step 1: Write the failing service test**

Append to `backend/tests/test_items_api.py`. It seeds ONE pose item with 16 visible keypoints plus 1 occluded keypoint placed at an extreme corner (so the bbox demonstrably depends on it), then exports `yolo` with and without the flag.

```python
def _seed_one_mixed_pose_item(client, auth_headers, project, tmp_path):
    """One annotated item: 16 visible (v=2) kps + 1 occluded (v=1) at a
    far corner so the bbox provably depends on the occluded point.
    Returns the parsed-out occluded keypoint index (16)."""
    rel = f"projects/{project['id']}/frames/vid/f_000000.jpg"
    img_path = tmp_path / rel
    img_path.parent.mkdir(parents=True, exist_ok=True)
    img_path.write_bytes(_tiny_jpeg(640, 480))
    client.post(
        f"/api/v1/projects/{project['id']}/items/bulk",
        json={"items": [{"payload": {"image_url": f"/files/{rel}"}}]},
        headers=auth_headers,
    )
    iid = client.get(
        f"/api/v1/projects/{project['id']}/items", headers=auth_headers
    ).json()["items"][0]["id"]
    kps = [[50 + i * 5, 60 + i * 5, 2] for i in range(16)] + [[600, 470, 1]]
    client.put(
        f"/api/v1/items/{iid}/annotation",
        json={"value": {"keypoints": kps}},
        headers=auth_headers,
    )
    return 16  # the occluded keypoint's index in the 17-kp array


def _yolo_label_fields(stream):
    """Read the single labels/train/*.txt from a built YOLO zip → list[str]."""
    import io
    import zipfile

    try:
        zf = zipfile.ZipFile(io.BytesIO(stream.read()))
    finally:
        stream.close()
    name = next(n for n in zf.namelist() if n.startswith("labels/train/"))
    return zf.read(name).decode().strip().split()


def test_yolo_export_demotes_occluded_keeps_bbox(client, auth_headers, project, tmp_path):
    from app.services import item as item_service

    occ = _seed_one_mixed_pose_item(client, auth_headers, project, tmp_path)

    plain, _ = item_service.build_yolo_export(project["id"])
    plain_fields = _yolo_label_fields(plain)

    excl_stream, _ = item_service.build_yolo_export(project["id"], exclude_occluded=True)
    excl_fields = _yolo_label_fields(excl_stream)

    # Field layout: [class, cx, cy, w, h, then 17 triplets x,y,v].
    assert len(plain_fields) == 1 + 4 + 17 * 3
    base = 5 + occ * 3  # start of the occluded keypoint's triplet

    # Without the flag: occluded kp has its real coords and visibility 1.
    assert plain_fields[base + 2] == "1"
    assert plain_fields[base] != "0.000000"

    # With the flag: occluded kp is zeroed and visibility 0.
    assert excl_fields[base] == "0.000000"
    assert excl_fields[base + 1] == "0.000000"
    assert excl_fields[base + 2] == "0"

    # Bbox (fields 1..4) is IDENTICAL — occluded point still drives the box.
    assert plain_fields[1:5] == excl_fields[1:5]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `docker compose exec -T backend python -m pytest tests/test_items_api.py::test_yolo_export_demotes_occluded_keeps_bbox -v`
Expected: FAIL — `build_yolo_export()` got an unexpected keyword argument `exclude_occluded`.

- [ ] **Step 3: Add the `exclude_occluded` param to `_yolo_records`**

In `backend/app/services/item.py`, change the signature of `_yolo_records` and the `kp_str` construction. Current signature:

```python
def _yolo_records(project_id: int, num_kpts: int) -> Iterator[tuple[Path, str, str]]:
```

becomes:

```python
def _yolo_records(
    project_id: int, num_kpts: int, exclude_occluded: bool = False
) -> Iterator[tuple[Path, str, str]]:
```

Update the docstring's first paragraph by appending one sentence:

```
    When `exclude_occluded` is set, occluded keypoints (v=1) are written as
    `0 0 0` (demoted to v=0) so they carry no keypoint supervision; the bbox
    still uses them.
```

Then replace the `kp_str = ...` line. Current:

```python
        kp_str = " ".join(f"{x / w:.6f} {y / h:.6f} {int(v)}" for x, y, v in kps)
```

becomes:

```python
        kp_str = " ".join(
            "0.000000 0.000000 0"
            if (exclude_occluded and v == 1)
            else f"{x / w:.6f} {y / h:.6f} {int(v)}"
            for x, y, v in kps
        )
```

(The `visible_pts`/bbox math above it is untouched.)

- [ ] **Step 4: Thread the param through `build_yolo_export`**

Change its signature and the `_yolo_records` call, and add a README note. Current signature:

```python
def build_yolo_export(project_id: int) -> tuple[BinaryIO, int]:
```

becomes:

```python
def build_yolo_export(
    project_id: int, exclude_occluded: bool = False
) -> tuple[BinaryIO, int]:
```

Change the records loop call. Current:

```python
        for src, stem, label_line in _yolo_records(project_id, num_kpts):
```

becomes:

```python
        for src, stem, label_line in _yolo_records(
            project_id, num_kpts, exclude_occluded
        ):
```

Add the README note. Current README writestr:

```python
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
```

becomes (insert the conditional `occ_note` and reference it):

```python
        occ_note = (
            "Occluded keypoints (v=1): excluded from training\n"
            if exclude_occluded
            else ""
        )
        zf.writestr(
            "README.txt",
            f"NeoLabel YOLO-pose export\n"
            f"Project: {project_id}\n"
            f"Exported: {exported} annotated frames\n"
            f"Format: Ultralytics YOLO-pose, {schema_label}\n"
            f"{occ_note}"
            f"Train with e.g.:\n"
            f"  yolo pose train data=data.yaml model=yolo11n-pose.pt epochs=100\n"
            f"(same yaml works for YOLOv8/v11/v12/v26 pose.)\n",
        )
```

- [ ] **Step 5: Run the service test to verify it passes**

Run: `docker compose exec -T backend python -m pytest tests/test_items_api.py::test_yolo_export_demotes_occluded_keeps_bbox -v`
Expected: PASS.

- [ ] **Step 6: Thread the param through `build_yolo_split_export`**

Change its signature, the `_yolo_records` call, and add the same README note. Current signature:

```python
def build_yolo_split_export(
    project_id: int, train: int, val: int, test: int, seed: int
) -> tuple[BinaryIO, int]:
```

becomes:

```python
def build_yolo_split_export(
    project_id: int, train: int, val: int, test: int, seed: int,
    exclude_occluded: bool = False,
) -> tuple[BinaryIO, int]:
```

Change the records call. Current:

```python
    records = list(_yolo_records(project_id, num_kpts))
```

becomes:

```python
    records = list(_yolo_records(project_id, num_kpts, exclude_occluded))
```

Add the README note. Current README writestr:

```python
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
```

becomes:

```python
        occ_note = (
            "Occluded keypoints (v=1): excluded from training\n"
            if exclude_occluded
            else ""
        )
        zf.writestr(
            "README.txt",
            f"NeoLabel YOLO-pose split export\n"
            f"Project: {project_id}\n"
            f"Format: Ultralytics YOLO-pose, {schema_label}\n"
            f"Split: train={train}% val={val}% test={test}% (seed={seed})\n"
            f"Frames per split: {count_str}\n"
            f"{occ_note}"
            f"Train with e.g.:\n"
            f"  yolo pose train data=data.yaml model=yolo11n-pose.pt epochs=100\n"
            f"(same yaml works for YOLOv8/v11/v12/v26 pose.)\n",
        )
```

- [ ] **Step 7: Add the split + default-unchanged tests**

Append to `backend/tests/test_items_api.py`:

```python
def test_yolo_split_export_honors_exclude_occluded(client, auth_headers, project, tmp_path):
    import io
    import zipfile

    from app.services import item as item_service

    _seed_one_mixed_pose_item(client, auth_headers, project, tmp_path)

    stream, _ = item_service.build_yolo_split_export(
        project["id"], train=100, val=0, test=0, seed=42, exclude_occluded=True
    )
    try:
        zf = zipfile.ZipFile(io.BytesIO(stream.read()))
    finally:
        stream.close()
    label_name = next(n for n in zf.namelist() if n.startswith("labels/"))
    fields = zf.read(label_name).decode().strip().split()
    # No keypoint triplet may carry visibility "1" once occluded are excluded.
    visibilities = fields[7::3]  # every 3rd field starting at the first v
    assert "1" not in visibilities


def test_yolo_export_default_keeps_occluded(client, auth_headers, project, tmp_path):
    from app.services import item as item_service

    occ = _seed_one_mixed_pose_item(client, auth_headers, project, tmp_path)
    fields = _yolo_label_fields(item_service.build_yolo_export(project["id"])[0])
    # Default (no flag) still emits the occluded keypoint with visibility 1.
    assert fields[5 + occ * 3 + 2] == "1"
```

- [ ] **Step 8: Run all the new service tests**

Run: `docker compose exec -T backend python -m pytest tests/test_items_api.py -k "occluded" -v`
Expected: 3 passed.

- [ ] **Step 9: Run the full export group (regression)**

Run: `docker compose exec -T backend python -m pytest tests/test_items_api.py -k export -v`
Expected: all PASS (flat YOLO, split, bundle, text formats unaffected).

- [ ] **Step 10: Lint (scoped)**

Run: `ruff check backend/app/services/item.py backend/tests/test_items_api.py && ruff format backend/app/services/item.py backend/tests/test_items_api.py`
(Ignore the pre-existing E741 at item.py:286.)

- [ ] **Step 11: Commit**

```bash
git add backend/app/services/item.py backend/tests/test_items_api.py
git commit -m "feat(yolo-export): exclude_occluded option demotes v=1 keypoints"
```

---

## Task 2: Backend — wire `exclude_occluded` into the export endpoint

**Files:**
- Modify: `backend/app/api/v1/items.py`
- Test: `backend/tests/test_items_api.py`

- [ ] **Step 1: Write the failing endpoint test**

Append to `backend/tests/test_items_api.py`:

```python
def test_export_yolo_exclude_occluded_endpoint(client, auth_headers, project, tmp_path):
    import io
    import zipfile

    _seed_one_mixed_pose_item(client, auth_headers, project, tmp_path)

    r = client.get(
        f"/api/v1/projects/{project['id']}/export?format=yolo&exclude_occluded=true",
        headers=auth_headers,
    )
    assert r.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    label_name = next(n for n in zf.namelist() if n.startswith("labels/train/"))
    fields = zf.read(label_name).decode().strip().split()
    assert "1" not in fields[7::3]  # no occluded keypoint survives in labels
```

- [ ] **Step 2: Run it, expect failure**

Run: `docker compose exec -T backend python -m pytest tests/test_items_api.py::test_export_yolo_exclude_occluded_endpoint -v`
Expected: FAIL — without the param the occluded keypoint stays `v=1`, so `"1" in fields[7::3]` and the assertion fails.

- [ ] **Step 3: Add the query param and pass it to both builders**

In `backend/app/api/v1/items.py`, `export_project`. Add the param to the signature (after `seed`):

```python
    seed: int = Query(42),
    exclude_occluded: bool = Query(False),
) -> Response:
```

Update the two YOLO branches to pass it. Current:

```python
    if format == "yolo":
        stream, size = item_service.build_yolo_export(project_id)
        return _stream_zip(stream, size, f"project_{project_id}_yolo.zip")

    if format == "yolo_split":
        if train + val + test != 100:
            raise HTTPException(
                status_code=422,
                detail="train + val + test must sum to 100",
            )
        stream, size = item_service.build_yolo_split_export(project_id, train, val, test, seed)
        return _stream_zip(stream, size, f"project_{project_id}_yolo_split.zip")
```

becomes:

```python
    if format == "yolo":
        stream, size = item_service.build_yolo_export(project_id, exclude_occluded)
        return _stream_zip(stream, size, f"project_{project_id}_yolo.zip")

    if format == "yolo_split":
        if train + val + test != 100:
            raise HTTPException(
                status_code=422,
                detail="train + val + test must sum to 100",
            )
        stream, size = item_service.build_yolo_split_export(
            project_id, train, val, test, seed, exclude_occluded
        )
        return _stream_zip(stream, size, f"project_{project_id}_yolo_split.zip")
```

- [ ] **Step 4: Run the endpoint test, expect PASS**

Run: `docker compose exec -T backend python -m pytest tests/test_items_api.py::test_export_yolo_exclude_occluded_endpoint -v`
Expected: PASS.

- [ ] **Step 5: Run the full export group**

Run: `docker compose exec -T backend python -m pytest tests/test_items_api.py -k export -v`
Expected: all PASS.

- [ ] **Step 6: Lint (scoped)**

Run: `ruff check backend/app/api/v1/items.py backend/tests/test_items_api.py && ruff format backend/app/api/v1/items.py backend/tests/test_items_api.py`

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/v1/items.py backend/tests/test_items_api.py
git commit -m "feat(export): exclude_occluded query param for yolo + yolo_split"
```

---

## Task 3: Frontend — send `exclude_occluded` from `download.ts`

**Files:**
- Modify: `frontend/src/lib/download.ts`

- [ ] **Step 1: Add the option and send it for the YOLO formats**

In `frontend/src/lib/download.ts`, add `excludeOccluded?: boolean` to `DownloadOptions`. Current interface:

```typescript
export interface DownloadOptions {
  onProgress?: (p: DownloadProgress) => void;
  signal?: AbortSignal;
  split?: { train: number; val: number; test: number; seed: number };
}
```

becomes:

```typescript
export interface DownloadOptions {
  onProgress?: (p: DownloadProgress) => void;
  signal?: AbortSignal;
  split?: { train: number; val: number; test: number; seed: number };
  excludeOccluded?: boolean;
}
```

Then replace the params construction so it composes split params (yolo_split only) and the exclude flag (yolo or yolo_split). Current:

```typescript
  const params: Record<string, string | number> =
    format === 'yolo_split' && opts?.split
      ? { format, ...opts.split }
      : { format };
```

becomes:

```typescript
  const params: Record<string, string | number | boolean> = { format };
  if (format === 'yolo_split' && opts?.split) {
    Object.assign(params, opts.split);
  }
  if ((format === 'yolo' || format === 'yolo_split') && opts?.excludeOccluded) {
    params.exclude_occluded = true;
  }
```

(Leave the `onDownloadProgress`, blob handling, and the `a.download` filename ternary untouched.)

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npx tsc -b --noEmit`
Expected: no errors. If any `.js` appears under `frontend/src/`, delete it (do not stage it).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/lib/download.ts
git commit -m "feat(export-ui): download.ts sends exclude_occluded for YOLO formats"
```

---

## Task 4: Frontend — checkbox in the export modal

**Files:**
- Modify: `frontend/src/pages/ProjectDetailPage.tsx`

- [ ] **Step 1: Add state**

Find (just after the `splitSum` derived const, ~line 108):

```typescript
  const [splitCfg, setSplitCfg] = useState({ train: 70, val: 20, test: 10, seed: 42 });
  const splitSum = splitCfg.train + splitCfg.val + splitCfg.test;
```

Add a line right after:

```typescript
  const [excludeOccluded, setExcludeOccluded] = useState(false);
```

- [ ] **Step 2: Forward it through `handleExport`**

In `handleExport`, the `downloadExport(projectId, fmt, { ... })` call currently passes `signal`, `onProgress`, `split`. Add `excludeOccluded`:

```typescript
      await downloadExport(projectId, fmt, {
        signal: controller.signal,
        onProgress: (p) => setExportProgress({ format: fmt, loaded: p.loaded, total: p.total }),
        split: fmt === 'yolo_split' ? splitCfg : undefined,
        excludeOccluded:
          fmt === 'yolo' || fmt === 'yolo_split' ? excludeOccluded : undefined,
      });
```

- [ ] **Step 3: Add the checkbox to the modal**

In the export modal, the split panel block `{exportFormat === 'yolo_split' && ( ... )}` ends just before the `<button onClick={handleExport} ...>`. Insert this checkbox block BETWEEN the end of the split panel `)}` and the `<button>` (so it shows for both YOLO formats):

```tsx
              {(exportFormat === 'yolo' || exportFormat === 'yolo_split') && (
                <label className="flex items-start gap-2 text-xs text-slate-600 border-t pt-2 mt-1 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={excludeOccluded}
                    onChange={(e) => setExcludeOccluded(e.target.checked)}
                    className="mt-0.5"
                  />
                  <span>
                    Excluir keypoints ocluídos (v=1) do treino
                    <span className="block text-slate-400">
                      vira 0 0 0; segue contando para a bounding box
                    </span>
                  </span>
                </label>
              )}
```

(Do not change the Download button's `disabled` logic — the checkbox never blocks the button.)

- [ ] **Step 4: Typecheck**

Run: `cd frontend && npx tsc -b --noEmit`
Expected: no errors (delete any stray `.js` under `src/`, do not stage).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/ProjectDetailPage.tsx
git commit -m "feat(export-ui): exclude-occluded checkbox for YOLO exports"
```

---

## Task 5: SPEC.md + final verification

**Files:**
- Modify: `SPEC.md`

- [ ] **Step 1: Document the param in SPEC.md**

In `SPEC.md`, find the export endpoint line (the one listing `format=json|jsonl|csv|yolo|bundle|yolo_split`). Add a bullet describing the new param next to the existing `yolo_split` description:

```markdown
- `exclude_occluded` (bool, default `false`; applies to `yolo` and
  `yolo_split`, ignored otherwise) — when `true`, occluded keypoints
  (`v=1`) are written as `0 0 0` (demoted to `v=0`) so they carry no
  keypoint training supervision. The bounding box is unchanged: occluded
  points still count toward it. Lets you A/B a dataset that trains on
  occluded joints against one that doesn't.
```

- [ ] **Step 2: Commit SPEC**

```bash
git add SPEC.md
git commit -m "docs(spec): document exclude_occluded export param"
```

- [ ] **Step 3: Full backend suite**

Run: `docker compose exec -T backend python -m pytest -q`
Expected: all tests PASS (no regressions).

- [ ] **Step 4: Frontend build**

Run: `cd frontend && npm run build`
Expected: `tsc -b` clean + `vite build` succeeds. (Afterward, delete any `.js` emitted under `src/`.)

- [ ] **Step 5: Manual smoke (optional)**

With the dev stack up, open a pose project → Export → choose **YOLO-pose (ZIP)** or **YOLO-pose split (ZIP)** → confirm the checkbox "Excluir keypoints ocluídos (v=1) do treino" appears, and a download with it checked produces labels where occluded keypoints are `0 0 0`.

- [ ] **Step 6: Confirm clean tree**

Run: `git status` — expected clean (all changes committed; no stray `.js`).

---

## Self-review notes

- **Spec coverage:** flag demotes v=1→`0 0 0` (T1, `_yolo_records`); bbox unchanged + test proves identical bbox (T1); applies to both builders (T1 threads through both); endpoint param (T2); ignored for non-YOLO formats (param simply unused by other branches); frontend send (T3) + checkbox shown only for yolo/yolo_split (T4); default off / standard behavior preserved (T1 default-keeps test); SPEC documented (T5); edge case (all-occluded frame still boxed) is inherent to the unchanged bbox path. All spec sections map to a task.
- **Type/signature consistency:** `build_yolo_export(project_id, exclude_occluded=False)`, `build_yolo_split_export(project_id, train, val, test, seed, exclude_occluded=False)`, and `_yolo_records(project_id, num_kpts, exclude_occluded=False)` are used identically in the endpoint (T2) and tests (T1). Frontend `excludeOccluded` option shape matches between `DownloadOptions` (T3) and `handleExport` (T4); wire param name is `exclude_occluded` in both `download.ts` (T3) and the endpoint (T2).
- **Field-index arithmetic:** label fields are `[class, cx, cy, w, h]` + 17 triplets; keypoint `i`'s visibility is field `5 + i*3 + 2`. The "no v=1" checks use `fields[7::3]` (every visibility field: first is index 7 = `5 + 0*3 + 2`). Consistent across T1/T2 tests.
