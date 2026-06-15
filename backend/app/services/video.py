from __future__ import annotations

import json
import math
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import BinaryIO

from app.core import storage
from app.schemas.item import ItemStatus
# Import names directly: several functions here use a local `frames` variable,
# so importing the module would shadow it (UnboundLocalError).
from app.services.frames import RESIZE_MODES, TARGET_SIZE, resize_filter


_SAFE = re.compile(r"[^A-Za-z0-9_.-]+")
_MAX_VIDEO_BYTES = 500 * 1024 * 1024    # 500 MiB
_CHUNK_BYTES = 1024 * 1024              # 1 MiB
_TARGET_SIZE = TARGET_SIZE              # shared with the image importer
_RESIZE_MODES = RESIZE_MODES


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


def rotate_keypoints(
    kps: list, w: int, h: int, degrees: int
) -> tuple[list, int, int]:
    """Transform keypoints for an image rotation. `90` is clockwise, `270`
    counter-clockwise (matches the upload `rotation` convention).

    Returns (new_kps, new_w, new_h). Keypoints with visibility 0 (the
    `[0,0,0]` "unset" convention) are passed through unchanged so they
    keep reading as unset. Width/height swap on 90/270.
    """
    out: list = []
    for kp in kps:
        if len(kp) < 3 or kp[2] == 0:
            out.append(list(kp))
            continue
        x, y, v = kp[0], kp[1], kp[2]
        if degrees == 90:
            nx, ny = h - y, x
        elif degrees == 270:
            nx, ny = y, w - x
        else:  # 180
            nx, ny = w - x, h - y
        out.append([nx, ny, v])
    if degrees in (90, 270):
        return out, h, w
    return out, w, h


def rotate_video(project_id: int, source_video: str, degrees: int) -> int:
    """Rotate every extracted frame of `source_video` in place and transform
    the existing keypoint annotations to match. `90` = clockwise.

    Frames are rendered into a sibling temp dir first; the originals are only
    replaced if every frame rendered successfully, so a failed ffmpeg run leaves
    the frames untouched. Item payload and annotation writes happen after the
    frame commit and are not transactional — a failure mid-write could leave
    some items updated and others not (the storage layer has no multi-file
    transaction).

    Returns the number of frames rotated (0 if the video has no frames).
    Raises ValueError on bad `degrees`.
    """
    if degrees not in (90, 180, 270):
        raise ValueError("degrees must be 90, 180, or 270")

    items = [
        i for i in storage.list_items(project_id)
        if (i.get("payload") or {}).get("source_video") == source_video
    ]
    if not items:
        return 0

    pdir = storage.project_dir(project_id)
    frames_dir = pdir / "frames" / source_video
    frames = sorted(frames_dir.glob("f_*.jpg"))
    if not frames:
        return 0

    transpose = _rotation_filter(degrees)  # never None for 90/180/270

    # Phase A — compute new annotation values in memory (cannot fail).
    new_anns: list[dict] = []
    for it in items:
        ann = storage.find_any_annotation_for_item(project_id, it["id"])
        if not ann:
            continue
        value = ann.get("value") or {}
        kps = value.get("keypoints")
        # No keypoints (unannotated / in-progress / non-pose value): the frame
        # is still rotated below, but there's nothing to transform.
        if not kps:
            continue
        p = it.get("payload") or {}
        w = p.get("width") or _TARGET_SIZE
        h = p.get("height") or _TARGET_SIZE
        new_kps, _, _ = rotate_keypoints(kps, w, h, degrees)
        new_anns.append({**ann, "value": {**value, "keypoints": new_kps}})

    # Phase B — render all frames into a temp dir under frames/ (same FS so
    # os.replace is atomic). image2 demuxer reads the f_%06d.jpg sequence.
    with tempfile.TemporaryDirectory(dir=str(frames_dir.parent)) as tmp:
        cmd = [
            "ffmpeg", "-y", "-loglevel", "warning",
            "-start_number", "1",
            "-i", str(frames_dir / "f_%06d.jpg"),
            "-vf", transpose, "-q:v", "2",
            str(Path(tmp) / "f_%06d.jpg"),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"ffmpeg failed: {result.stderr.strip() or result.stdout.strip()}"
            )
        rotated = sorted(Path(tmp).glob("f_*.jpg"))
        if len(rotated) != len(frames):
            raise RuntimeError(
                f"rotation produced {len(rotated)} frames, expected {len(frames)}"
            )
        # Phase C — commit frame files (fast renames).
        for src in rotated:
            os.replace(src, frames_dir / src.name)

    # Phase D — persist payload + annotations.
    swap = degrees in (90, 270)
    for it in items:
        p = it.get("payload") or {}
        if swap:
            w = p.get("width") or _TARGET_SIZE
            h = p.get("height") or _TARGET_SIZE
            p["width"], p["height"] = h, w
        p["frame_rev"] = int(p.get("frame_rev", 0)) + 1
        it["payload"] = p
        storage.save_item(it)
    for ann in new_anns:
        storage.save_annotation(project_id, ann)

    return len(frames)


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
    filters.append(resize_filter(resize_mode))
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
