from __future__ import annotations

import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from app.core import storage
from app.schemas.item import ItemStatus


_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")


def _safe_name(name: str) -> str:
    stem = Path(name).stem
    return _SAFE.sub("_", stem) or "video"


def extract_frames(
    project_id: int,
    video_bytes: bytes,
    filename: str,
    fps: float,
    assignee_id: int | None = None,
) -> dict:
    """Save video, run ffmpeg to extract frames, create items for each frame.

    Each frame-item carries `assigned_to = assignee_id` so only that user sees
    the work. Returns {"video": name, "frames": count}.
    """
    if fps <= 0 or fps > 60:
        raise ValueError("fps must be between 0 and 60")

    pdir = storage.project_dir(project_id)
    name = _safe_name(filename)
    videos_dir = pdir / "_videos"
    videos_dir.mkdir(parents=True, exist_ok=True)
    video_path = videos_dir / f"{name}{Path(filename).suffix.lower()}"
    video_path.write_bytes(video_bytes)

    frames_dir = pdir / "frames" / name
    frames_dir.mkdir(parents=True, exist_ok=True)

    pattern = str(frames_dir / "f_%06d.jpg")
    cmd = [
        "ffmpeg",
        "-y",
        "-loglevel", "error",
        "-i", str(video_path),
        "-vf", f"fps={fps}",
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
