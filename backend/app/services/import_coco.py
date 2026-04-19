"""Import a COCO keypoints dataset ZIP (e.g. Roboflow "COCO JSON" export) into
a pose_detection project.

Expected structure — split layout or flat, both handled:

    archive.zip
    ├── train/
    │   ├── _annotations.coco.json
    │   ├── frame_001.jpg
    │   └── ...
    ├── valid/
    │   ├── _annotations.coco.json
    │   └── ...
    └── test/...

Flat alternative:

    archive.zip
    ├── _annotations.coco.json
    ├── frame_001.jpg
    └── ...

Any file whose name matches `*.json` and whose content looks like a COCO
keypoints payload (has `images` + `annotations`) is treated as an index;
images are looked up in the same directory as that JSON. Images referenced
but not found on disk are skipped; labels without a matching image are
skipped.

COCO keypoints convention:
- `keypoints` is a flat list of 3N numbers: [x1, y1, v1, x2, y2, v2, ...].
- `v ∈ {0, 1, 2}`: 0 = not labeled, 1 = labeled but not visible (occluded),
  2 = labeled and visible.
- Coords are in pixel space (not normalized).

Multiple annotations per image → first is kept (schema is 1 pose per frame).
"""
from __future__ import annotations

import json
import re
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO

from app.core import storage
from app.schemas.item import ItemStatus


_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")
_MAX_ZIP_BYTES = 500 * 1024 * 1024    # 500 MiB — same cap as video upload
_CHUNK_BYTES = 1024 * 1024            # 1 MiB
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def _safe_name(name: str) -> str:
    stem = Path(name).stem
    return _SAFE.sub("_", stem) or "import"


def _safe_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    dest = dest.resolve()
    for member in zf.infolist():
        name = member.filename
        if name.endswith("/"):
            continue
        p = Path(name)
        if p.is_absolute() or any(part == ".." for part in p.parts):
            raise ValueError(f"Unsafe path in archive: {name}")
        target = (dest / p).resolve()
        if dest not in target.parents:
            raise ValueError(f"Unsafe path in archive: {name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(member) as src, open(target, "wb") as out:
            shutil.copyfileobj(src, out)


def _find_split(path: Path) -> str | None:
    for ancestor in path.parents:
        if ancestor.name in ("train", "valid", "val", "test"):
            return "valid" if ancestor.name == "val" else ancestor.name
    return None


def _looks_like_coco(data: Any) -> bool:
    return (
        isinstance(data, dict)
        and isinstance(data.get("images"), list)
        and isinstance(data.get("annotations"), list)
    )


def _parse_keypoints(raw: list[Any]) -> list[list[int]] | None:
    """COCO keypoints list → [[x, y, v], ...] with 17 entries.

    Accepts shorter/longer lists by padding/truncating to 17 points.
    Returns None if the list is too short to read.
    """
    if not isinstance(raw, list) or len(raw) < 3:
        return None
    points: list[list[int]] = []
    for i in range(0, len(raw), 3):
        if i + 2 >= len(raw):
            break
        try:
            x = float(raw[i])
            y = float(raw[i + 1])
            v = int(float(raw[i + 2]))
        except (TypeError, ValueError):
            return None
        if v <= 0:
            points.append([0, 0, 0])
        else:
            points.append([round(x), round(y), 2 if v >= 2 else 1])
    # Normalize to exactly 17 keypoints.
    if len(points) > 17:
        points = points[:17]
    while len(points) < 17:
        points.append([0, 0, 0])
    return points


def _is_done(keypoints: list[list[int]]) -> bool:
    return len(keypoints) == 17 and all(k[2] > 0 for k in keypoints)


def _clamp_keypoints(kps: list[list[int]], w: int, h: int) -> list[list[int]]:
    """Clamp visible keypoints into image bounds. 0-visibility entries are
    left as [0, 0, 0] regardless."""
    clamped: list[list[int]] = []
    for x, y, v in kps:
        if v <= 0:
            clamped.append([0, 0, 0])
            continue
        clamped.append([
            max(0, min(w, int(x))),
            max(0, min(h, int(y))),
            v,
        ])
    return clamped


def import_coco_pose(
    project_id: int,
    source: BinaryIO,
    filename: str,
    uploader_id: int,
    assignee_id: int | None = None,
) -> dict:
    """Stream a COCO-keypoints ZIP, walk its JSON indexes, copy referenced
    images into the project's frames dir, and create items + annotations.

    Created annotations are attributed to the assignee when one is provided
    (so they appear on the assignee's view); otherwise they're attributed
    to the uploader (the admin).

    Returns a summary: items_created, annotations_created, skipped_images,
    skipped_labels, source_videos.
    """
    base_name = _safe_name(filename)

    with tempfile.TemporaryDirectory(prefix="neolabel-import-") as td:
        tmp = Path(td)
        archive_path = tmp / "upload.zip"

        # 1. Stream upload to disk with a cap.
        written = 0
        with archive_path.open("wb") as out:
            while chunk := source.read(_CHUNK_BYTES):
                written += len(chunk)
                if written > _MAX_ZIP_BYTES:
                    raise ValueError("Archive larger than 500 MB")
                out.write(chunk)
        if written == 0:
            raise ValueError("Empty file")

        # 2. Extract with path-traversal checks.
        extract_dir = tmp / "extract"
        extract_dir.mkdir()
        try:
            with zipfile.ZipFile(archive_path) as zf:
                _safe_extract(zf, extract_dir)
        except zipfile.BadZipFile as e:
            raise ValueError(f"Not a valid ZIP: {e}")

        # 3. Locate every COCO JSON (Roboflow uses `_annotations.coco.json`,
        # but any *.json that has the expected shape works).
        coco_files: list[tuple[Path, dict]] = []
        for j in sorted(extract_dir.rglob("*.json")):
            try:
                with j.open("r", encoding="utf-8") as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                continue
            if _looks_like_coco(data):
                coco_files.append((j, data))

        if not coco_files:
            raise ValueError(
                "No COCO JSON found. Looking for a file with `images` and "
                "`annotations` arrays (e.g. `_annotations.coco.json` from "
                "a Roboflow COCO export).",
            )

        pdir = storage.project_dir(project_id)
        now = datetime.now(timezone.utc).isoformat()
        counters: dict[str, int] = {}
        items_created = 0
        anns_created = 0
        skipped_images = 0
        skipped_labels = 0
        sources_seen: set[str] = set()

        # 4. Walk each COCO index.
        for json_path, data in coco_files:
            coco_dir = json_path.parent
            split = _find_split(json_path)
            source_name = f"{base_name}-{split}" if split else base_name
            sources_seen.add(source_name)

            # Build image_id → annotation (first per image).
            ann_by_image: dict[int, dict] = {}
            for a in data.get("annotations", []) or []:
                iid = a.get("image_id")
                if iid is None or iid in ann_by_image:
                    continue
                ann_by_image[iid] = a

            for img in data.get("images", []) or []:
                file_name = img.get("file_name")
                if not file_name:
                    skipped_images += 1
                    continue
                src_img = coco_dir / file_name
                if not src_img.exists() or src_img.suffix.lower() not in _IMAGE_SUFFIXES:
                    skipped_images += 1
                    continue

                # Allocate a frame_index contiguous with what's already there.
                if source_name not in counters:
                    existing = (
                        list((pdir / "frames" / source_name).glob("f_*.*"))
                        if (pdir / "frames" / source_name).exists()
                        else []
                    )
                    counters[source_name] = len(existing)
                counters[source_name] += 1
                frame_idx = counters[source_name]

                frames_dir = pdir / "frames" / source_name
                frames_dir.mkdir(parents=True, exist_ok=True)
                suffix = src_img.suffix.lower()
                dest = frames_dir / f"f_{frame_idx:06d}{suffix}"
                shutil.copy2(src_img, dest)
                rel = dest.relative_to(storage._root())

                img_w = int(img.get("width") or 0)
                img_h = int(img.get("height") or 0)

                iid_new = storage.next_id("items")
                payload: dict[str, Any] = {
                    "image_url": f"/files/{rel.as_posix()}",
                    "source_video": source_name,
                    "frame_index": frame_idx,
                }
                if img_w > 0 and img_h > 0:
                    payload["width"] = img_w
                    payload["height"] = img_h
                item = {
                    "id": iid_new,
                    "project_id": project_id,
                    "payload": payload,
                    "status": ItemStatus.pending.value,
                    "created_at": now,
                    "assigned_to": assignee_id,
                }

                # Keypoints (if any).
                keypoints: list[list[int]] | None = None
                coco_ann = ann_by_image.get(img.get("id"))
                if coco_ann:
                    kps_raw = coco_ann.get("keypoints") or []
                    kps = _parse_keypoints(kps_raw)
                    if kps is None:
                        skipped_labels += 1
                    elif img_w > 0 and img_h > 0:
                        keypoints = _clamp_keypoints(kps, img_w, img_h)
                    else:
                        keypoints = kps

                if keypoints:
                    item["status"] = (
                        ItemStatus.done.value if _is_done(keypoints)
                        else ItemStatus.in_progress.value
                    )
                storage.save_item(item)
                items_created += 1

                if keypoints:
                    annotator_id = assignee_id if assignee_id is not None else uploader_id
                    ann_record = {
                        "id": storage.next_id("annotations"),
                        "item_id": iid_new,
                        "annotator_id": annotator_id,
                        "value": {"keypoints": keypoints},
                        "created_at": now,
                        "updated_at": now,
                    }
                    storage.save_annotation(project_id, ann_record)
                    anns_created += 1

        if items_created == 0:
            raise ValueError(
                "COCO JSON parsed, but no image files were found alongside it.",
            )

        return {
            "items_created": items_created,
            "annotations_created": anns_created,
            "skipped_images": skipped_images,
            "skipped_labels": skipped_labels,
            "source_videos": sorted(sources_seen),
        }
