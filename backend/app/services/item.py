import io
import zipfile
from datetime import datetime, timezone
from pathlib import Path

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
                "assigned_to": item.get("assigned_to"),
            },
        )
        g["frames"] += 1
        if item.get("status") in (ItemStatus.done.value, ItemStatus.reviewed.value):
            g["done"] += 1
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
    d = storage.load_annotation(project_id, item_id, annotator_id)
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


def _status_for(project_type: str | None, value: dict) -> str:
    """For pose projects, 'done' requires all 17 keypoints labeled (v>0)."""
    if project_type == "pose_detection":
        kps = value.get("keypoints") or []
        if len(kps) == 17 and all(isinstance(k, list) and len(k) >= 3 and k[2] > 0 for k in kps):
            return ItemStatus.done.value
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
    item["status"] = _status_for(project.get("type") if project else None, data.value)
    storage.save_item(item)
    return AnnotationRead.model_validate(record)


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


def export_yolo(project_id: int) -> bytes:
    """Build a YOLO-pose dataset ZIP (COCO 17-keypoints, Ultralytics format).

    Structure:
        data.yaml
        images/train/<stem>.jpg
        labels/train/<stem>.txt   — `0 cx cy w h  x1 y1 v1 ... x17 y17 v17` (normalized)
    """
    items = storage.list_items(project_id)
    anns = {a["item_id"]: a for a in storage.list_annotations_for_project(project_id)}
    data_root = Path(settings.DATA_DIR)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # NOTE: intentionally no `path:` key. Ultralytics resolves relative
        # train/val against `path`; when `path` is missing it falls back to
        # the yaml file's own parent (see ultralytics/data/utils.py
        # `check_det_dataset`). With `path: .` it resolves against CWD
        # instead, which breaks any training run started from a directory
        # that isn't the extracted dataset root.
        yaml = (
            "# YOLO-pose dataset (COCO 17 keypoints)\n"
            "train: images/train\n"
            "val: images/train\n"
            "kpt_shape: [17, 3]\n"
            # COCO horizontal-flip index: swaps left<->right joints
            "flip_idx: [0, 2, 1, 4, 3, 6, 5, 8, 7, 10, 9, 12, 11, 14, 13, 16, 15]\n"
            "names:\n  0: person\n"
        )
        zf.writestr("data.yaml", yaml)

        exported = 0
        for item in items:
            ann = anns.get(item["id"])
            if not ann:
                continue
            kps = (ann.get("value") or {}).get("keypoints") or []
            if len(kps) != 17:
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
            f"Neo-Label YOLO-pose export\n"
            f"Project: {project_id}\n"
            f"Exported: {exported} annotated frames\n"
            f"Format: Ultralytics YOLO-pose, COCO 17 keypoints\n"
            f"Train with e.g.:\n"
            f"  yolo pose train data=data.yaml model=yolo11n-pose.pt epochs=100\n"
            f"(same yaml works for YOLOv8/v11/v12/v26 pose.)\n",
        )

    return buf.getvalue()


def export_project(project_id: int) -> list[dict]:
    items = storage.list_items(project_id)
    anns = {a["item_id"]: a for a in storage.list_annotations_for_project(project_id)}
    return [
        {
            "id": i["id"],
            "payload": i["payload"],
            "status": i["status"],
            "annotation": anns.get(i["id"], {}).get("value") if i["id"] in anns else None,
        }
        for i in items
    ]
