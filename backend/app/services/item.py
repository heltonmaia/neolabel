import csv
import io
import json
import tempfile
import zipfile
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

from app.core import storage
from app.core.config import settings
from app.schemas.item import (
    AnnotationRead,
    AnnotationUpsert,
    ItemCreate,
    ItemRead,
    ItemStatus,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def bulk_create(
    project_id: int, items: list[ItemCreate], assigned_to: int | None = None
) -> int:
    count = 0
    for i in items:
        iid = storage.next_id("items")
        record = {
            "id": iid,
            "project_id": project_id,
            "payload": i.payload,
            "status": ItemStatus.pending.value,
            "created_at": _now(),
            "assigned_to": assigned_to,
        }
        storage.save_item(record)
        count += 1
    return count


def list_for_project(
    project_id: int,
    limit: int = 100,
    offset: int = 0,
    assigned_to: int | None = None,
) -> tuple[list[ItemRead], int]:
    all_items = storage.list_items(project_id)
    if assigned_to is not None:
        all_items = [i for i in all_items if i.get("assigned_to") == assigned_to]
    total = len(all_items)
    page = all_items[offset : offset + limit]
    return [ItemRead.model_validate(i) for i in page], total


def videos_in_project(project_id: int) -> list[dict]:
    """Group items by source_video to give an admin overview of distribution."""
    groups: dict[str, dict] = {}
    for item in storage.list_items(project_id):
        name = (item.get("payload") or {}).get("source_video")
        if not name:
            continue
        g = groups.setdefault(
            name,
            {
                "source_video": name,
                "frames": 0,
                "done": 0,
                "reviewed": 0,
                "assigned_to": item.get("assigned_to"),
            },
        )
        g["frames"] += 1
        # `done` is "annotated" (counts both done and reviewed) — kept as-is
        # for the existing progress bar UI. `reviewed` is the strict subset
        # that's been signed off by admin/owner, so the UI can compute
        # "approve-able" = done - reviewed.
        if item.get("status") in (ItemStatus.done.value, ItemStatus.reviewed.value):
            g["done"] += 1
        if item.get("status") == ItemStatus.reviewed.value:
            g["reviewed"] += 1
        # If frames disagree on assignee (manual edits), expose None so admin resolves.
        if g["assigned_to"] != item.get("assigned_to"):
            g["assigned_to"] = None
    return sorted(groups.values(), key=lambda g: g["source_video"])


def reassign_video(project_id: int, source_video: str, assignee_id: int | None) -> int:
    """Reassign every frame of `source_video` to `assignee_id` (None = unassign).

    Returns count updated.
    """
    count = 0
    for item in storage.list_items(project_id):
        if (item.get("payload") or {}).get("source_video") != source_video:
            continue
        item["assigned_to"] = assignee_id
        storage.save_item(item)
        count += 1
    return count


def delete_video(project_id: int, source_video: str) -> int:
    """Delete every frame of `source_video` (items + annotations + frame JPGs),
    plus the original video file and the now-empty frames directory.

    Returns how many items were removed.
    """
    import shutil

    count = 0
    for item in storage.list_items(project_id):
        if (item.get("payload") or {}).get("source_video") != source_video:
            continue
        if storage.delete_item(project_id, item["id"]):
            count += 1

    pdir = storage.project_dir(project_id)
    # Remove the frames folder (may still exist if empty)
    frames_dir = pdir / "frames" / source_video
    if frames_dir.exists():
        shutil.rmtree(frames_dir, ignore_errors=True)
    # Remove the source video file (any extension)
    videos_dir = pdir / "_videos"
    if videos_dir.exists():
        for f in videos_dir.glob(f"{source_video}.*"):
            try:
                f.unlink()
            except OSError:
                pass
    return count


def user_has_assignment_in_project(project_id: int, user_id: int) -> bool:
    for item in storage.list_items(project_id):
        if item.get("assigned_to") == user_id:
            return True
    return False


def project_ids_assigned_to_user(user_id: int) -> set[int]:
    """Scan all projects for items assigned to user_id — small-scale OK."""
    out: set[int] = set()
    for p in storage.list_projects():
        if user_has_assignment_in_project(p["id"], user_id):
            out.add(p["id"])
    return out


def get(item_id: int) -> dict | None:
    return storage.find_item(item_id)


def get_annotation(project_id: int, item_id: int, annotator_id: int) -> AnnotationRead | None:
    # Fast path: the requested annotator's file. Falls back to scanning the
    # item's annotation directory so admin/owner viewers (and reassigned
    # items where the annotation lives under the previous assignee's id)
    # still surface the existing work.
    d = storage.load_annotation(project_id, item_id, annotator_id)
    if d is None:
        d = storage.find_any_annotation_for_item(project_id, item_id)
    return AnnotationRead.model_validate(d) if d else None


def delete(item_id: int) -> bool:
    item = storage.find_item(item_id)
    if not item:
        return False
    return storage.delete_item(item["project_id"], item["id"])


def clear_annotation(item_id: int) -> bool:
    item = storage.find_item(item_id)
    if not item:
        return False
    storage.delete_annotations_for_item(item["project_id"], item["id"])
    item["status"] = ItemStatus.pending.value
    storage.save_item(item)
    return True


def delete_annotated(project_id: int) -> int:
    count = 0
    for item in storage.list_items(project_id):
        if item.get("status") in (ItemStatus.done.value, ItemStatus.reviewed.value):
            if storage.delete_item(project_id, item["id"]):
                count += 1
    return count


# Pairs of (label, left_id, right_id) used by the L/R-swap heuristic. Eyes
# and ears are intentionally excluded — they sit too close to the centerline
# on small heads to be reliable orientation evidence (and one is often
# occluded). Pose schemas without these ids will simply skip them.
_LR_PAIRS: list[tuple[str, int, int]] = [
    ("shoulder", 5, 6),
    ("elbow", 7, 8),
    ("wrist", 9, 10),
    ("hip", 11, 12),
    ("knee", 13, 14),
    ("ankle", 15, 16),
]


def _classify_pair(left_kp: list, right_kp: list) -> str | None:
    """COCO convention puts left_*.x > right_*.x for a frontal subject (left
    is anatomically the subject's left, which is the viewer's right). Returns
    'mirror' if the saved pair disagrees, 'coco' if it matches, None if a
    side is missing/unlabeled or both share the same x."""
    def vis(kp: list) -> bool:
        return isinstance(kp, list) and len(kp) >= 3 and kp[2] in (1, 2)
    if not vis(left_kp) or not vis(right_kp):
        return None
    if left_kp[0] == right_kp[0]:
        return None
    return "coco" if left_kp[0] > right_kp[0] else "mirror"


def _vis(kp: list) -> bool:
    return isinstance(kp, list) and len(kp) >= 3 and kp[2] in (1, 2)


def _check_lr_swap(kps: list, mirror_threshold: int = 3) -> dict | None:
    mirror_pairs: list[str] = []
    coco_pairs: list[str] = []
    for name, lid, rid in _LR_PAIRS:
        verdict = _classify_pair(kps[lid], kps[rid])
        if verdict == "mirror":
            mirror_pairs.append(name)
        elif verdict == "coco":
            coco_pairs.append(name)
    if len(mirror_pairs) < mirror_threshold:
        return None
    return {
        "kind": "lr_swap",
        "summary": (
            f"{len(mirror_pairs)}/{len(_LR_PAIRS)} paired keypoints look mirrored "
            f"({', '.join(mirror_pairs)}). Likely a left/right swap — but a "
            "non-supine pose can also trigger this."
        ),
        "details": {
            "mirror_pairs": mirror_pairs,
            "coco_pairs": coco_pairs,
            "score": f"{len(mirror_pairs)}/{len(_LR_PAIRS)}",
        },
    }


def _check_out_of_image(kps: list, payload: dict) -> dict | None:
    """Flag visible keypoints that fall outside the frame's bounds. Skipped
    silently if width/height aren't in the payload (some legacy / external
    imports don't set them)."""
    w = payload.get("width")
    h = payload.get("height")
    if not isinstance(w, int) or not isinstance(h, int) or w <= 0 or h <= 0:
        return None
    bad: list[dict] = []
    for kp_def in COCO_KP_NAMES:
        idx, name = kp_def
        if idx >= len(kps):
            continue
        kp = kps[idx]
        if not _vis(kp):
            continue
        x, y = kp[0], kp[1]
        if x < 0 or x > w or y < 0 or y > h:
            bad.append({"name": name, "x": x, "y": y})
    if not bad:
        return None
    parts = ", ".join(b["name"] for b in bad)
    return {
        "kind": "out_of_image",
        "summary": (
            f"{len(bad)} keypoint{'s' if len(bad) != 1 else ''} land outside "
            f"the {w}×{h} frame ({parts})."
        ),
        "details": {"bad_keypoints": bad, "frame": {"width": w, "height": h}},
    }


def _midpoint(kps: list, lid: int, rid: int) -> tuple[float, float] | None:
    l, r = kps[lid], kps[rid]
    if not (_vis(l) and _vis(r)):
        return None
    return ((l[0] + r[0]) / 2.0, (l[1] + r[1]) / 2.0)


def _check_impossible_anatomy(kps: list) -> dict | None:
    """Project the head→ankles axis and verify shoulder/hip/knee fall in
    the expected order along it. Works for any orientation (head-up,
    head-down, sideways) because the axis is derived from the data, not
    assumed. Needs nose + at least one ankle pair to anchor the axis."""
    nose = kps[0] if len(kps) > 0 else None
    mid_an = _midpoint(kps, 15, 16)
    if not (nose and _vis(nose) and mid_an):
        return None
    ax = mid_an[0] - nose[0]
    ay = mid_an[1] - nose[1]
    axis_sq = ax * ax + ay * ay
    if axis_sq < 1:  # nose and ankles essentially overlap — meaningless axis
        return None

    def proj(p: tuple[float, float]) -> float:
        return ((p[0] - nose[0]) * ax + (p[1] - nose[1]) * ay) / axis_sq

    landmarks: list[tuple[str, float]] = [("nose", 0.0)]
    for label, lid, rid in (
        ("shoulder", 5, 6),
        ("hip", 11, 12),
        ("knee", 13, 14),
    ):
        m = _midpoint(kps, lid, rid)
        if m is not None:
            landmarks.append((label, proj(m)))
    landmarks.append(("ankle", 1.0))
    if len(landmarks) < 3:
        return None
    # Walk pairwise; record any out-of-order pair. Tolerance avoids tiny
    # numerical wobbles flagging healthy poses (e.g. shoulder slightly above
    # the nose-ankle line counts as in-order, not a violation).
    EPS = 0.02
    violations: list[str] = []
    for i in range(len(landmarks) - 1):
        a_name, a_t = landmarks[i]
        b_name, b_t = landmarks[i + 1]
        if a_t > b_t + EPS:
            violations.append(f"{b_name} ahead of {a_name} along the body axis")
    if not violations:
        return None
    return {
        "kind": "impossible_anatomy",
        "summary": (
            "Body landmarks are out of head→ankle order: "
            + "; ".join(violations) + ". Could be a swap, or a curled/folded pose."
        ),
        "details": {"violations": violations},
    }


# COCO-17 keypoint names paired with their id, used by the out_of_image
# detail formatter. (Order is the canonical COCO order.)
COCO_KP_NAMES: list[tuple[int, str]] = [
    (0, "nose"),
    (1, "left_eye"), (2, "right_eye"),
    (3, "left_ear"), (4, "right_ear"),
    (5, "left_shoulder"), (6, "right_shoulder"),
    (7, "left_elbow"), (8, "right_elbow"),
    (9, "left_wrist"), (10, "right_wrist"),
    (11, "left_hip"), (12, "right_hip"),
    (13, "left_knee"), (14, "right_knee"),
    (15, "left_ankle"), (16, "right_ankle"),
]


def find_outliers(project_id: int) -> list[dict]:
    """Run all heuristics over every annotated item; return one entry per
    item that has at least one issue. Soft signal — this never modifies
    anything; the caller (admin/owner UI) picks each one to review.
    """
    out: list[dict] = []
    for item in storage.list_items(project_id):
        if item.get("status") not in (ItemStatus.done.value, ItemStatus.reviewed.value):
            continue
        ann = storage.find_any_annotation_for_item(project_id, item["id"])
        if not ann:
            continue
        kps = (ann.get("value") or {}).get("keypoints") or []
        if len(kps) < 17:
            continue
        payload = item.get("payload") or {}
        outliers = [
            check for check in (
                _check_lr_swap(kps),
                _check_out_of_image(kps, payload),
                _check_impossible_anatomy(kps),
            )
            if check is not None
        ]
        if not outliers:
            continue
        out.append({
            "id": item["id"],
            "project_id": item["project_id"],
            "payload": payload,
            "status": item["status"],
            "assigned_to": item.get("assigned_to"),
            "review_note": item.get("review_note"),
            "outliers": outliers,
        })
    return out


def approve_all_done(project_id: int, source_video: str | None = None) -> int:
    """Mark every 'done' item as 'reviewed' (optionally restricted to one
    source video). Items already 'reviewed' are skipped silently. Returns
    the count of items touched."""
    count = 0
    for item in storage.list_items(project_id):
        if item.get("status") != ItemStatus.done.value:
            continue
        if source_video is not None:
            sv = (item.get("payload") or {}).get("source_video")
            if sv != source_video:
                continue
        item["status"] = ItemStatus.reviewed.value
        item.pop("review_note", None)
        storage.save_item(item)
        count += 1
    return count


def _expected_kpts(project: dict | None) -> int:
    """Keypoint count expected for a pose project's schema (tolerant read)."""
    schema = (project or {}).get("keypoint_schema") or "infant"
    return 7 if schema == "rodent" else 17


def _status_for(project: dict | None, value: dict) -> str:
    """For pose projects, 'done' requires every keypoint to be addressed —
    either labeled (v>0) or explicitly marked out-of-frame via the parallel
    `out_of_frame` boolean array. Non-pose projects are 'done' on any save.

    The `out_of_frame` field is a NeoLabel addition; legacy annotations omit
    it and fall back to the v>0 check, so historical data is unaffected.
    Externally, an OOF keypoint stays as [0,0,0]/v=0 in the COCO array — the
    same encoding standard COCO datasets use for "not in image".
    """
    if not project or project.get("type") != "pose_detection":
        return ItemStatus.done.value
    expected = _expected_kpts(project)
    kps = value.get("keypoints") or []
    if len(kps) != expected:
        return ItemStatus.in_progress.value
    oof = value.get("out_of_frame") or []
    for i, k in enumerate(kps):
        labeled = isinstance(k, list) and len(k) >= 3 and k[2] > 0
        out_of_frame = i < len(oof) and bool(oof[i])
        if not (labeled or out_of_frame):
            return ItemStatus.in_progress.value
    return ItemStatus.done.value


def upsert_annotation(item: dict, annotator_id: int, data: AnnotationUpsert) -> AnnotationRead:
    pid = item["project_id"]
    existing = storage.load_annotation(pid, item["id"], annotator_id)
    now = _now()
    if existing:
        existing["value"] = data.value
        existing["updated_at"] = now
        record = existing
    else:
        record = {
            "id": storage.next_id("annotations"),
            "item_id": item["id"],
            "annotator_id": annotator_id,
            "value": data.value,
            "created_at": now,
            "updated_at": now,
        }
    storage.save_annotation(pid, record)
    project = storage.load_project(pid)
    item["status"] = _status_for(project, data.value)
    # Once the annotator brings the item back to 'done', clear any prior
    # review_note: they've responded to the feedback. Partial saves
    # (in_progress) keep the note so the prompt doesn't disappear mid-fix.
    if item["status"] == ItemStatus.done.value:
        item.pop("review_note", None)
    storage.save_item(item)
    return AnnotationRead.model_validate(record)


def review_item(item: dict, action: str, note: str | None) -> dict:
    """Curation action by admin/owner. See ItemReviewIn for the enum."""
    if action == "approve":
        item["status"] = ItemStatus.reviewed.value
        item.pop("review_note", None)
    elif action == "unapprove":
        # Revert a prior approval. Annotation is untouched; admin/owner can
        # then re-approve, send back, or leave it 'done' for someone else.
        item["status"] = ItemStatus.done.value
        item.pop("review_note", None)
    elif action == "send_back":
        item["status"] = ItemStatus.in_progress.value
        if note and note.strip():
            item["review_note"] = note.strip()
        else:
            item.pop("review_note", None)
    else:
        raise ValueError(f"unknown review action: {action!r}")
    storage.save_item(item)
    return item


def _jpeg_size(path: Path) -> tuple[int, int] | None:
    """Read JPEG width/height from SOF marker — avoids a Pillow dependency."""
    try:
        with open(path, "rb") as f:
            if f.read(2) != b"\xff\xd8":
                return None
            while True:
                b = f.read(1)
                while b and b != b"\xff":
                    b = f.read(1)
                marker = f.read(1)
                while marker == b"\xff":
                    marker = f.read(1)
                if not marker:
                    return None
                if marker[0] in (0xC0, 0xC1, 0xC2, 0xC3):
                    f.read(3)  # length(2) + precision(1)
                    h = int.from_bytes(f.read(2), "big")
                    w = int.from_bytes(f.read(2), "big")
                    return w, h
                size = int.from_bytes(f.read(2), "big")
                f.seek(size - 2, 1)
    except OSError:
        return None


def build_yolo_export(project_id: int) -> tuple[BinaryIO, int]:
    """Build a YOLO-pose dataset ZIP (Ultralytics format).

    Keypoint layout is chosen by the project's `keypoint_schema`:
    - `infant` → 17 COCO keypoints (default for projects created before the
      field existed)
    - `rodent` → 7 keypoints (N, LEar, REar, BC, TB, TM, TT) for OF / EPM

    Spills to disk past 64 MiB so large projects don't pin the container's
    RAM. Returns a file-like positioned at 0 plus its total byte size so the
    caller can set `Content-Length` and stream it out. Caller must `close()`
    the handle when done.

    Structure:
        data.yaml
        images/train/<stem>.jpg
        labels/train/<stem>.txt   — `0 cx cy w h  x1 y1 v1 ... xN yN vN` (normalized)
    """
    project = storage.load_project(project_id) or {}
    schema = project.get("keypoint_schema") or "infant"
    if schema == "rodent":
        num_kpts = 7
        # Top-down horizontal flip: LEar (1) and REar (2) swap; rest self-map.
        flip_idx = [0, 2, 1, 3, 4, 5, 6]
        class_name = "rodent"
        schema_label = "rodent (7 keypoints: N, LEar, REar, BC, TB, TM, TT)"
    else:
        num_kpts = 17
        # COCO horizontal-flip index: swaps left<->right joints.
        flip_idx = [0, 2, 1, 4, 3, 6, 5, 8, 7, 10, 9, 12, 11, 14, 13, 16, 15]
        class_name = "person"
        schema_label = "COCO 17 keypoints"

    items = storage.list_items(project_id)
    anns = {a["item_id"]: a for a in storage.list_annotations_for_project(project_id)}
    data_root = Path(settings.DATA_DIR)

    spooled = tempfile.SpooledTemporaryFile(max_size=64 * 1024 * 1024, mode="w+b")
    with zipfile.ZipFile(spooled, "w", zipfile.ZIP_DEFLATED) as zf:
        # NOTE: intentionally no `path:` key. Ultralytics resolves relative
        # train/val against `path`; when `path` is missing it falls back to
        # the yaml file's own parent (see ultralytics/data/utils.py
        # `check_det_dataset`). With `path: .` it resolves against CWD
        # instead, which breaks any training run started from a directory
        # that isn't the extracted dataset root.
        yaml = (
            f"# YOLO-pose dataset ({schema_label})\n"
            "train: images/train\n"
            "val: images/train\n"
            f"kpt_shape: [{num_kpts}, 3]\n"
            f"flip_idx: {flip_idx}\n"
            f"names:\n  0: {class_name}\n"
        )
        zf.writestr("data.yaml", yaml)

        exported = 0
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


def build_bundle_export(project_id: int) -> tuple[BinaryIO, int]:
    """Build a self-contained ZIP with annotations.json + source images.

    Structure:
        README.txt
        annotations.json        — JSON array of rows, image_url rewritten
                                  to the archive-relative path
        images/<stem>.<ext>     — source frames referenced by items

    Items whose `payload.image_url` points at a non-existent file on disk
    (shouldn't happen, but safe) keep their original URL untouched and
    no image is bundled for them — the row still makes it into the json.
    """
    items = storage.list_items(project_id)
    anns = {a["item_id"]: a for a in storage.list_annotations_for_project(project_id)}
    data_root = Path(settings.DATA_DIR)

    spooled = tempfile.SpooledTemporaryFile(max_size=64 * 1024 * 1024, mode="w+b")
    rows: list[dict] = []
    included_images = 0
    seen: set[str] = set()

    with zipfile.ZipFile(spooled, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in items:
            ann_value = anns.get(item["id"], {}).get("value") if item["id"] in anns else None
            payload = dict(item.get("payload") or {})
            image_url = payload.get("image_url")
            if isinstance(image_url, str) and image_url.startswith("/files/"):
                src = data_root / image_url[len("/files/"):]
                if src.exists():
                    stem = f"{item['id']:06d}_{src.stem}"
                    arc = f"images/{stem}{src.suffix}"
                    if arc not in seen:
                        zf.write(src, arc)
                        seen.add(arc)
                        included_images += 1
                    payload["image_url"] = arc
            rows.append(
                {
                    "id": item["id"],
                    "payload": payload,
                    "status": item["status"],
                    "annotation": ann_value,
                }
            )

        zf.writestr(
            "annotations.json",
            json.dumps(rows, default=str, ensure_ascii=False, indent=2),
        )
        zf.writestr(
            "README.txt",
            f"NeoLabel full bundle\n"
            f"Project: {project_id}\n"
            f"Items: {len(rows)}\n"
            f"Images included: {included_images}\n"
            f"\nannotations.json is a JSON array, one record per item.\n"
            f"Each payload.image_url is a path relative to this archive\n"
            f"(images/<stem>.<ext>), so the bundle can be unzipped and\n"
            f"consumed as-is on any machine.\n",
        )

    size = spooled.tell()
    spooled.seek(0)
    return spooled, size


def _iter_export_rows(project_id: int) -> Iterator[dict]:
    """Shared row source for JSON/JSONL/CSV — yields one row at a time so the
    caller can stream without materializing the whole list. Pending items
    are emitted with `annotation: null`; filtering is downstream."""
    items = storage.list_items(project_id)
    anns = {a["item_id"]: a for a in storage.list_annotations_for_project(project_id)}
    for i in items:
        yield {
            "id": i["id"],
            "payload": i["payload"],
            "status": i["status"],
            "annotation": anns.get(i["id"], {}).get("value") if i["id"] in anns else None,
        }


def iter_export_json(project_id: int) -> Iterator[bytes]:
    """Stream a JSON array one element at a time — no backend buffering."""
    yield b"["
    first = True
    for row in _iter_export_rows(project_id):
        prefix = b"" if first else b","
        first = False
        yield prefix + json.dumps(row, default=str, ensure_ascii=False).encode("utf-8")
    yield b"]"


def iter_export_jsonl(project_id: int) -> Iterator[bytes]:
    for row in _iter_export_rows(project_id):
        yield (json.dumps(row, default=str, ensure_ascii=False) + "\n").encode("utf-8")


def iter_export_csv(project_id: int) -> Iterator[bytes]:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "payload", "status", "annotation"])
    yield buf.getvalue().encode("utf-8")
    buf.seek(0)
    buf.truncate()
    for r in _iter_export_rows(project_id):
        writer.writerow(
            [
                r["id"],
                json.dumps(r["payload"], ensure_ascii=False),
                r["status"],
                json.dumps(r["annotation"], ensure_ascii=False) if r["annotation"] else "",
            ]
        )
        yield buf.getvalue().encode("utf-8")
        buf.seek(0)
        buf.truncate()
