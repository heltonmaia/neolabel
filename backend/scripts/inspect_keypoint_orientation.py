"""Read-only audit: are saved keypoints in COCO anatomical convention or
mirror/visual convention?

COCO-17 stores `left_*` as the subject's anatomical left side. For a person
facing the camera (e.g. infants supine), anatomical left appears on the
viewer's right — so on the image we expect:

    left_shoulder.x > right_shoulder.x   (COCO-correct)
    left_shoulder.x < right_shoulder.x   (mirror / visual)

This script walks every annotation under DATA_DIR and tallies the two
patterns across the six L/R pairs (shoulder, elbow, wrist, hip, knee,
ankle). Eyes/ears are too close to the centerline to be reliable — we
skip them.

Run on the host (no Docker needed; pure stdlib):

    DATA_DIR=./data-prod python backend/scripts/inspect_keypoint_orientation.py
    DATA_DIR=/root/work/neo-label-data python backend/scripts/inspect_keypoint_orientation.py

It only reads from disk. Nothing is written. It's safe to run on prod.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# COCO-17 keypoint indices for paired points. Eyes/ears excluded — they sit
# too close to the centerline to give reliable orientation evidence on small
# heads (and infants often have one occluded).
PAIRS = [
    ("shoulder", 5, 6),
    ("elbow",    7, 8),
    ("wrist",    9, 10),
    ("hip",      11, 12),
    ("knee",     13, 14),
    ("ankle",    15, 16),
]


def is_visible(kp: list) -> bool:
    """Visibility flag: 0 = not labeled, 1 = occluded, 2 = visible.
    For orientation we accept both 1 and 2 — the position is recorded."""
    return isinstance(kp, list) and len(kp) >= 3 and kp[2] in (1, 2)


def classify_pair(left_kp: list, right_kp: list) -> str | None:
    """Returns 'coco' if left.x > right.x (COCO/anatomical convention),
    'mirror' if left.x < right.x, None if inconclusive (same x or invalid)."""
    if not is_visible(left_kp) or not is_visible(right_kp):
        return None
    lx, _ = left_kp[0], left_kp[1]
    rx, _ = right_kp[0], right_kp[1]
    if lx == rx:
        return None
    return "coco" if lx > rx else "mirror"


def inspect_annotation(value: dict) -> dict:
    """Tally pairs in a single annotation."""
    kps = value.get("keypoints") or []
    if len(kps) < 17:
        return {}
    counts = {"coco": 0, "mirror": 0, "inconclusive": 0}
    per_pair: dict[str, str | None] = {}
    for name, left_id, right_id in PAIRS:
        verdict = classify_pair(kps[left_id], kps[right_id])
        per_pair[name] = verdict
        if verdict is None:
            counts["inconclusive"] += 1
        else:
            counts[verdict] += 1
    return {"counts": counts, "per_pair": per_pair}


def main() -> int:
    data_dir = Path(os.environ.get("DATA_DIR", "./data-prod")).expanduser().resolve()
    if not data_dir.exists():
        print(f"DATA_DIR not found: {data_dir}", file=sys.stderr)
        return 1

    print(f"Auditing keypoint orientation in: {data_dir}")
    print("=" * 70)

    project_totals: dict[int, dict] = {}

    for proj_dir in sorted((data_dir / "projects").glob("*")):
        if not proj_dir.is_dir():
            continue
        try:
            pid = int(proj_dir.name)
        except ValueError:
            continue
        ann_dir = proj_dir / "annotations"
        if not ann_dir.exists():
            continue

        per_proj = {
            "pair_coco": 0,
            "pair_mirror": 0,
            "pair_inconclusive": 0,
            "frames_total": 0,
            "frames_coco_majority": 0,
            "frames_mirror_majority": 0,
            "frames_no_pairs": 0,
            "samples_coco": [],
            "samples_mirror": [],
        }

        for ann_file in sorted(ann_dir.glob("*.json")):
            try:
                data = json.loads(ann_file.read_text())
            except Exception:
                continue
            value = data.get("value") or {}
            res = inspect_annotation(value)
            if not res:
                continue
            per_proj["frames_total"] += 1
            c = res["counts"]
            per_proj["pair_coco"] += c["coco"]
            per_proj["pair_mirror"] += c["mirror"]
            per_proj["pair_inconclusive"] += c["inconclusive"]
            decisive = c["coco"] + c["mirror"]
            if decisive == 0:
                per_proj["frames_no_pairs"] += 1
                continue
            if c["coco"] > c["mirror"]:
                per_proj["frames_coco_majority"] += 1
                if len(per_proj["samples_coco"]) < 3:
                    per_proj["samples_coco"].append((ann_file.name, res["per_pair"]))
            else:
                per_proj["frames_mirror_majority"] += 1
                if len(per_proj["samples_mirror"]) < 3:
                    per_proj["samples_mirror"].append((ann_file.name, res["per_pair"]))

        project_totals[pid] = per_proj

    if not project_totals:
        print("No annotated projects found.")
        return 0

    for pid, t in project_totals.items():
        print(f"\nProject {pid}")
        print("-" * 70)
        print(f"  Annotations inspected:        {t['frames_total']}")
        if t["frames_total"] == 0:
            continue
        decisive_frames = t["frames_coco_majority"] + t["frames_mirror_majority"]
        print(f"  Frames with no L/R pair data: {t['frames_no_pairs']}")
        print(f"  Frame-level majority verdict:")
        if decisive_frames > 0:
            print(f"    COCO   (anatomical, left.x > right.x): "
                  f"{t['frames_coco_majority']:>5}  ({100 * t['frames_coco_majority'] / decisive_frames:5.1f}%)")
            print(f"    Mirror (visual,     left.x < right.x): "
                  f"{t['frames_mirror_majority']:>5}  ({100 * t['frames_mirror_majority'] / decisive_frames:5.1f}%)")
        decisive_pairs = t["pair_coco"] + t["pair_mirror"]
        print(f"  Pair-level totals (across all frames, {len(PAIRS)} pairs each):")
        if decisive_pairs > 0:
            print(f"    COCO:    {t['pair_coco']:>5}  ({100 * t['pair_coco'] / decisive_pairs:5.1f}%)")
            print(f"    Mirror:  {t['pair_mirror']:>5}  ({100 * t['pair_mirror'] / decisive_pairs:5.1f}%)")
        print(f"    Inconclusive (one side missing/equal x): {t['pair_inconclusive']}")

        if t["samples_coco"]:
            print(f"\n  Sample frames classified COCO:")
            for name, pp in t["samples_coco"]:
                print(f"    {name}: {pp}")
        if t["samples_mirror"]:
            print(f"\n  Sample frames classified Mirror:")
            for name, pp in t["samples_mirror"]:
                print(f"    {name}: {pp}")

    print("\n" + "=" * 70)
    grand_coco = sum(t["pair_coco"] for t in project_totals.values())
    grand_mirror = sum(t["pair_mirror"] for t in project_totals.values())
    grand_decisive = grand_coco + grand_mirror
    if grand_decisive > 0:
        print(f"Overall pair-level verdict across {len(project_totals)} project(s):")
        print(f"  COCO-compatible:   {grand_coco:>5}  ({100 * grand_coco / grand_decisive:5.1f}%)")
        print(f"  Mirror convention: {grand_mirror:>5}  ({100 * grand_mirror / grand_decisive:5.1f}%)")
        if grand_coco > 0.9 * grand_decisive:
            print("\n→ Existing data is COCO-compliant. Only the avatar visual needs fixing.")
        elif grand_mirror > 0.9 * grand_decisive:
            print("\n→ Existing data follows the MIRROR convention. To make it COCO-compatible "
                  "(needed for fine-tuning on COCO-pretrained models), swap left↔right pairs "
                  "in every annotation. A migration script is required.")
        else:
            print("\n→ Mixed signal — annotations don't strongly agree on a convention. "
                  "Spot-check individual frames before any migration.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
