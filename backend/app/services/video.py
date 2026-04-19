from __future__ import annotations

import json
import math
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
_TARGET_SIZE = 640
_PAD_COLOR = "black"
_RESIZE_MODES = ("stretch", "pad")


def _probe_duration_s(path: Path) -> float | None:
    """Best-effort duration of `path` in seconds (None on any ffprobe failure)."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "json",
        str(path),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        return None
    try:
        return float(json.loads(r.stdout)["format"]["duration"])
    except (KeyError, ValueError, json.JSONDecodeError):
        return None


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


def _resize_filter(mode: str) -> str:
    if mode == "stretch":
        return f"scale={_TARGET_SIZE}:{_TARGET_SIZE}"
    # "pad" — scale the longer edge to 640 then pad the shorter edge with
    # solid color. Matches Ultralytics' letterbox convention.
    return (
        f"scale={_TARGET_SIZE}:{_TARGET_SIZE}:force_original_aspect_ratio=decrease,"
        f"pad={_TARGET_SIZE}:{_TARGET_SIZE}:(ow-iw)/2:(oh-ih)/2:color={_PAD_COLOR}"
    )


def extract_frames(
    project_id: int,
    source: BinaryIO,
    filename: str,
    fps: float,
    rotation: int = 0,
    assignee_id: int | None = None,
    resize_mode: str = "pad",
) -> dict:
    """Stream `source` to disk, run ffmpeg, create a frame-item per extracted JPG.

    Frames are always output at 640x640. `resize_mode` controls how the source
    is fit: "pad" letterboxes with a solid border to preserve aspect ratio
    (recommended), "stretch" scales freely and distorts.

    Raises ValueError on bad params, empty file, or file larger than 500 MB.
    Each frame-item carries `assigned_to = assignee_id`.
    """
    if fps <= 0 or fps > 60:
        raise ValueError("fps must be between 0 and 60")
    if rotation not in (0, 90, 180, 270):
        raise ValueError("rotation must be 0, 90, 180, or 270")
    if resize_mode not in _RESIZE_MODES:
        raise ValueError(f"resize_mode must be one of: {', '.join(_RESIZE_MODES)}")

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
    # `round=up` ensures the last boundary frame is kept instead of dropped,
    # which otherwise undercounts short clips by one.
    filters.append(f"fps=fps={fps}:round=up")
    filters.append(_resize_filter(resize_mode))
    vf = ",".join(filters)

    frames_dir = pdir / "frames" / name
    frames_dir.mkdir(parents=True, exist_ok=True)
    # Clear any leftovers from a prior upload under the same name so stale
    # frames don't get picked up and turned into duplicate items.
    for old in frames_dir.glob("f_*.jpg"):
        old.unlink(missing_ok=True)
    for old in frames_dir.glob("f_*.png"):
        old.unlink(missing_ok=True)

    duration_s = _probe_duration_s(video_path)
    expected_frames = (
        max(1, math.ceil(duration_s * fps)) if duration_s and duration_s > 0 else None
    )

    pattern = str(frames_dir / "f_%06d.jpg")
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel", "warning",
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
                "width": _TARGET_SIZE,
                "height": _TARGET_SIZE,
            },
            "status": ItemStatus.pending.value,
            "created_at": created_at,
            "assigned_to": assignee_id,
        }
        storage.save_item(item)

    return {
        "video": name,
        "frames": len(frames),
        "duration_s": duration_s,
        "expected_frames": expected_frames,
    }
