import json
import tempfile
import zipfile
from pathlib import Path
from typing import BinaryIO

from app.services.item import eligible_pose_items, partition_records

# COCO export is infant-only (the endpoint rejects rodent), so the keypoint
# count is always the COCO-17 person layout.
_NUM_KPTS = 17

# Fixed COCO Keypoints `categories` entry (1-indexed skeleton, COCO convention).
_COCO_CATEGORIES = [
    {
        "id": 1,
        "name": "person",
        "supercategory": "person",
        "keypoints": [
            "nose",
            "left_eye",
            "right_eye",
            "left_ear",
            "right_ear",
            "left_shoulder",
            "right_shoulder",
            "left_elbow",
            "right_elbow",
            "left_wrist",
            "right_wrist",
            "left_hip",
            "right_hip",
            "left_knee",
            "right_knee",
            "left_ankle",
            "right_ankle",
        ],
        "skeleton": [
            [16, 14],
            [14, 12],
            [17, 15],
            [15, 13],
            [12, 13],
            [6, 12],
            [7, 13],
            [6, 7],
            [6, 8],
            [7, 9],
            [8, 10],
            [9, 11],
            [2, 3],
            [1, 2],
            [1, 3],
            [2, 4],
            [3, 5],
            [4, 6],
            [5, 7],
        ],
    }
]

# Annotation ids are offset from image ids so an annotation's id never equals
# its image_id (COCO requires both, and they must be distinguishable).
_ANN_ID_OFFSET = 1_000_000


def _image_and_annotation(
    image_id: int, item: dict, src: Path, w: int, h: int, kps: list
) -> tuple[dict, dict]:
    """Build the COCO images[] and annotations[] entries for one frame.

    Keypoints are absolute pixels in COCO-17 order with native 0/1/2
    visibility. The bbox is derived from the visible (v>0) keypoints, padded
    12% per side and clamped to the image — NeoLabel stores no person box.
    """
    file_name = f"{item['id']:06d}_{src.stem}{src.suffix}"
    image = {"id": image_id, "file_name": file_name, "width": w, "height": h}

    keypoints: list = []
    num_keypoints = 0
    for x, y, v in kps:
        keypoints.extend([x, y, v])
        if v > 0:
            num_keypoints += 1

    vis = [(x, y) for x, y, v in kps if v > 0]
    xs = [p[0] for p in vis]
    ys = [p[1] for p in vis]
    x0, x1 = min(xs), max(xs)
    y0, y1 = min(ys), max(ys)
    # 12% pad per side (intentionally wider than the YOLO exporter's 10% —
    # the COCO person box is a touch looser by request). `or 5` gives a 5px
    # fallback when every visible keypoint coincides (zero-span).
    pad_x = (x1 - x0) * 0.12 or 5
    pad_y = (y1 - y0) * 0.12 or 5
    bx0 = max(0, x0 - pad_x)
    by0 = max(0, y0 - pad_y)
    bx1 = min(w, x1 + pad_x)
    by1 = min(h, y1 + pad_y)
    bw = bx1 - bx0
    bh = by1 - by0

    annotation = {
        "id": image_id + _ANN_ID_OFFSET,
        "image_id": image_id,
        "category_id": 1,
        "keypoints": keypoints,
        "num_keypoints": num_keypoints,
        "bbox": [bx0, by0, bw, bh],
        "area": bw * bh,
        "iscrowd": 0,
    }
    return image, annotation


def _coco_doc(eligible: list) -> dict:
    """Build a COCO dict from an ordered list of (item, src, w, h, kps)."""
    images = []
    annotations = []
    for i, (item, src, w, h, kps) in enumerate(eligible, start=1):
        image, ann = _image_and_annotation(i, item, src, w, h, kps)
        images.append(image)
        annotations.append(ann)
    return {"images": images, "annotations": annotations, "categories": _COCO_CATEGORIES}


def build_coco_export(project_id: int) -> bytes:
    """Single COCO Keypoints annotations.json over every annotated frame."""
    eligible = list(eligible_pose_items(project_id, _NUM_KPTS))
    return json.dumps(_coco_doc(eligible)).encode("utf-8")


def video_index_pairs(project_id: int) -> list[tuple[str, str]]:
    """(source_video, frame_stem) for every frame in the flat COCO export — the
    SAME eligible stream `build_coco_export` consumes, so the manifest matches
    the doc's images[] exactly."""
    return [
        ((item.get("payload") or {}).get("source_video") or "", src.stem)
        for item, src, _w, _h, _kps in eligible_pose_items(project_id, _NUM_KPTS)
    ]


def build_coco_split_export(
    project_id: int, train: int, val: int, test: int, seed: int
) -> tuple[BinaryIO, int]:
    """ZIP with train.json/val.json/test.json. Uses the SAME ordered eligible
    items and the SAME seeded partition as the YOLO split, so the per-frame
    assignment is identical for matching params. test.json is omitted when
    test == 0 (val is the catch-all). Spills to disk past 64 MiB.
    """
    eligible = list(eligible_pose_items(project_id, _NUM_KPTS))
    splits = partition_records(eligible, train, val, test, seed)

    spooled = tempfile.SpooledTemporaryFile(max_size=64 * 1024 * 1024, mode="w+b")
    with zipfile.ZipFile(spooled, "w", zipfile.ZIP_DEFLATED) as zf:
        for split_name, split_items in splits:
            zf.writestr(f"{split_name}.json", json.dumps(_coco_doc(split_items)))

    size = spooled.tell()
    spooled.seek(0)
    return spooled, size
