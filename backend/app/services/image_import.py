"""Import a ZIP of raw images into a pose_detection project as pending frames.

Mirrors `import_coco`'s ZIP plumbing (stream-to-disk cap, path-safe extract) but
there is no annotation index: every image becomes one unannotated `pending`
item, resized to the shared TARGET_SIZE exactly like a video frame, so imported
image frames and extracted video frames are interchangeable downstream.

All images in the archive flatten into a single source group named after the
ZIP file (subfolders are walked recursively but ignored for grouping).
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

from app.core import storage
from app.schemas.item import ItemStatus
from app.services import frames


_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")
_MAX_ZIP_BYTES = 500 * 1024 * 1024    # 500 MiB — same cap as video / COCO import
_CHUNK_BYTES = 1024 * 1024            # 1 MiB
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def _safe_name(name: str) -> str:
    stem = Path(name).stem
    return _SAFE.sub("_", stem) or "images"


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


def import_images(
    project_id: int,
    source: BinaryIO,
    filename: str,
    assignee_id: int | None = None,
    resize_mode: str = "pad",
) -> dict:
    """Stream an image ZIP, resize every image to TARGET_SIZE, and create one
    pending item per image under a single group named after the ZIP.

    `frame_index` continues contiguously past any existing frames in the group,
    so re-uploading under the same name extends it instead of colliding.

    Returns {items_created, skipped_files, source_video, resize_mode}.
    Raises ValueError on bad params / empty file / not-a-zip / no images, and
    RuntimeError if ffmpeg fails on an image.
    """
    if resize_mode not in frames.RESIZE_MODES:
        raise ValueError(f"resize_mode must be one of: {', '.join(frames.RESIZE_MODES)}")

    source_name = _safe_name(filename)
    vf = frames.resize_filter(resize_mode)

    with tempfile.TemporaryDirectory(prefix="neolabel-images-") as td:
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

        # 3. Collect image files (recursively, flattened); count other files.
        images: list[Path] = []
        skipped_files = 0
        for p in sorted(extract_dir.rglob("*")):
            if not p.is_file():
                continue
            if p.suffix.lower() in _IMAGE_SUFFIXES:
                images.append(p)
            else:
                skipped_files += 1
        if not images:
            raise ValueError("No images found in archive")

        pdir = storage.project_dir(project_id)
        frames_dir = pdir / "frames" / source_name
        frames_dir.mkdir(parents=True, exist_ok=True)

        # Continue numbering past any frames already in this group.
        start = len(list(frames_dir.glob("f_*.*")))

        now = datetime.now(timezone.utc).isoformat()
        items_created = 0
        for offset, src_img in enumerate(images, 1):
            frame_idx = start + offset
            dest = frames_dir / f"f_{frame_idx:06d}.jpg"
            cmd = [
                "ffmpeg", "-y", "-loglevel", "warning",
                "-i", str(src_img), "-vf", vf, "-q:v", "2", str(dest),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                raise RuntimeError(
                    f"ffmpeg failed: {result.stderr.strip() or result.stdout.strip()}"
                )
            rel = dest.relative_to(storage._root())
            iid = storage.next_id("items")
            storage.save_item({
                "id": iid,
                "project_id": project_id,
                "payload": {
                    "image_url": f"/files/{rel.as_posix()}",
                    "source_video": source_name,
                    "frame_index": frame_idx,
                    "width": frames.TARGET_SIZE,
                    "height": frames.TARGET_SIZE,
                },
                "status": ItemStatus.pending.value,
                "created_at": now,
                "assigned_to": assignee_id,
            })
            items_created += 1

    return {
        "items_created": items_created,
        "skipped_files": skipped_files,
        "source_video": source_name,
        "resize_mode": resize_mode,
    }
