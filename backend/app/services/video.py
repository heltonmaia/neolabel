from __future__ import annotations

import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

from app.core import storage
from app.schemas.item import ItemStatus


_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")
_MAX_VIDEO_BYTES = 500 * 1024 * 1024    # 500 MiB
_CHUNK_BYTES = 1024 * 1024              # 1 MiB


def _safe_name(name: str) -> str:
    stem = Path(name).stem
    return _SAFE.sub("_", stem) or "video"


def _rotation_filter(rotation: int) -> str | None:
    return {
        0: None,
        90: "transpose=1",
        180: "transpose=1,transpose=1",
        270: "transpose=2",
    }[rotation]


def extract_frames(
    project_id: int,
    source: BinaryIO,
    filename: str,
    fps: float,
    rotation: int = 0,
    assignee_id: int | None = None,
) -> dict:
    """Stream `source` to disk, run ffmpeg, create a frame-item per extracted JPG.

    Raises ValueError on bad params, empty file, or file larger than 500 MB.
    Each frame-item carries `assigned_to = assignee_id`.
    """
    if fps <= 0 or fps > 60:
        raise ValueError("fps must be between 0 and 60")
    if rotation not in (0, 90, 180, 270):
        raise ValueError("rotation must be 0, 90, 180, or 270")

    pdir = storage.project_dir(project_id)
    name = _safe_name(filename)
    videos_dir = pdir / "_videos"
    videos_dir.mkdir(parents=True, exist_ok=True)
    video_path = videos_dir / f"{name}{Path(filename).suffix.lower()}"

    written = 0
    with video_path.open("wb") as out:
        while chunk := source.read(_CHUNK_BYTES):
            written += len(chunk)
            if written > _MAX_VIDEO_BYTES:
                out.close()
                video_path.unlink(missing_ok=True)
                raise ValueError("Video larger than 500 MB")
            out.write(chunk)
    if written == 0:
        video_path.unlink(missing_ok=True)
        raise ValueError("Empty file")

    filters = []
    rot = _rotation_filter(rotation)
    if rot:
        filters.append(rot)
    filters.append(f"fps={fps}")
    vf = ",".join(filters)

    frames_dir = pdir / "frames" / name
    frames_dir.mkdir(parents=True, exist_ok=True)

    pattern = str(frames_dir / "f_%06d.jpg")
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel", "error",
        "-i", str(video_path),
        "-vf", vf,
        "-q:v", "2",
        pattern,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr.strip() or result.stdout.strip()}")

    frames = sorted(frames_dir.glob("f_*.jpg"))
    created_at = datetime.now(timezone.utc).isoformat()
    for i, frame in enumerate(frames, 1):
        rel = frame.relative_to(storage._root())
        iid = storage.next_id("items")
        item = {
            "id": iid,
            "project_id": project_id,
            "payload": {
                "image_url": f"/files/{rel.as_posix()}",
                "source_video": name,
                "frame_index": i,
            },
            "status": ItemStatus.pending.value,
            "created_at": created_at,
            "assigned_to": assignee_id,
        }
        storage.save_item(item)

    return {"video": name, "frames": len(frames)}
