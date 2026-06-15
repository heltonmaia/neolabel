"""Shared frame geometry for the video uploader and the image importer.

Both ingest paths normalize every frame to one fixed square so video frames and
imported image frames are byte-consistent and export geometry is uniform.
"""
from __future__ import annotations

TARGET_SIZE = 640
PAD_COLOR = "black"
RESIZE_MODES = ("stretch", "pad")


def resize_filter(mode: str) -> str:
    """ffmpeg `-vf` value that fits a source into TARGET_SIZE x TARGET_SIZE.

    "stretch" scales freely (distorts non-square sources); "pad" scales the
    longer edge to TARGET_SIZE then pads the shorter edge with a solid border
    to preserve aspect ratio (Ultralytics' letterbox convention).
    """
    if mode == "stretch":
        return f"scale={TARGET_SIZE}:{TARGET_SIZE}"
    return (
        f"scale={TARGET_SIZE}:{TARGET_SIZE}:force_original_aspect_ratio=decrease,"
        f"pad={TARGET_SIZE}:{TARGET_SIZE}:(ow-iw)/2:(oh-ih)/2:color={PAD_COLOR}"
    )
