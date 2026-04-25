export interface Keypoint {
  id: number;
  name: string;
  label: string;
  side?: 'left' | 'right' | 'center';
}

// COCO 17 keypoints (standard order)
export const COCO_KEYPOINTS: Keypoint[] = [
  { id: 0,  name: 'nose',           label: 'Nose',           side: 'center' },
  { id: 1,  name: 'left_eye',       label: 'Left eye',       side: 'left'   },
  { id: 2,  name: 'right_eye',      label: 'Right eye',      side: 'right'  },
  { id: 3,  name: 'left_ear',       label: 'Left ear',       side: 'left'   },
  { id: 4,  name: 'right_ear',      label: 'Right ear',      side: 'right'  },
  { id: 5,  name: 'left_shoulder',  label: 'Left shoulder',  side: 'left'   },
  { id: 6,  name: 'right_shoulder', label: 'Right shoulder', side: 'right'  },
  { id: 7,  name: 'left_elbow',     label: 'Left elbow',     side: 'left'   },
  { id: 8,  name: 'right_elbow',    label: 'Right elbow',    side: 'right'  },
  { id: 9,  name: 'left_wrist',     label: 'Left wrist',     side: 'left'   },
  { id: 10, name: 'right_wrist',    label: 'Right wrist',    side: 'right'  },
  { id: 11, name: 'left_hip',       label: 'Left hip',       side: 'left'   },
  { id: 12, name: 'right_hip',      label: 'Right hip',      side: 'right'  },
  { id: 13, name: 'left_knee',      label: 'Left knee',      side: 'left'   },
  { id: 14, name: 'right_knee',     label: 'Right knee',     side: 'right'  },
  { id: 15, name: 'left_ankle',     label: 'Left ankle',     side: 'left'   },
  { id: 16, name: 'right_ankle',    label: 'Right ankle',    side: 'right'  },
];

// Reference positions on the avatar canvas (viewBox 200 x 400).
// Baby proportions: large head (~1/4 height), short limbs.
//
// Convention: COCO-17 is anatomical — `left_*` is the SUBJECT's anatomical
// left side. The avatar is drawn frontal (facing the viewer), so the
// subject's anatomical left appears on the VIEWER'S RIGHT side of the
// canvas. Hence left_* keypoints sit at x>100 and right_* at x<100.
//
// Earlier the avatar was drawn mirror-style (left_* on viewer's left),
// which silently disagreed with what the rest of the world means by COCO
// `left_eye`. Saved annotations were already COCO-anatomical (annotators
// followed the text labels in the side panel, not the avatar position),
// so this is a pure visual correction — no data migration needed.
export const AVATAR_POSITIONS: Record<number, [number, number]> = {
  0:  [100, 70],    // nose
  1:  [110, 60],    // left eye      (anatomical left → viewer's right)
  2:  [90,  60],    // right eye
  3:  [125, 72],    // left ear
  4:  [75,  72],    // right ear
  5:  [130, 140],   // left shoulder
  6:  [70,  140],   // right shoulder
  7:  [145, 190],   // left elbow
  8:  [55,  190],   // right elbow
  9:  [155, 235],   // left wrist
  10: [45,  235],   // right wrist
  11: [118, 235],   // left hip
  12: [82,  235],   // right hip
  13: [122, 295],   // left knee
  14: [78,  295],   // right knee
  15: [125, 355],   // left ankle
  16: [75,  355],   // right ankle
};

// Skeleton edges (pairs of keypoint ids)
export const SKELETON: [number, number][] = [
  [0, 1], [0, 2], [1, 3], [2, 4],           // head
  [5, 6], [5, 7], [7, 9], [6, 8], [8, 10],  // arms
  [5, 11], [6, 12], [11, 12],               // torso
  [11, 13], [13, 15], [12, 14], [14, 16],   // legs
];

// Visibility: 0 = not labeled, 1 = labeled but occluded, 2 = labeled and visible
export type KeypointValue = [number, number, 0 | 1 | 2];

// Traversal orderings for guided annotation. Each is a permutation of the 17
// COCO ids — the stored output shape is unchanged, only the "next keypoint"
// pointer walks this list.
//
//   top   — COCO default (nose, eyes, ears, shoulders, …, ankles)
//   left  — head → down the image-left side → across feet → up image-right
//   right — head → down the image-right side → across feet → up image-left
export type OrderMode = 'top' | 'left' | 'right';
export const ORDERINGS: Record<OrderMode, readonly number[]> = {
  top:   [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16],
  left:  [0, 1, 3, 5, 7, 9, 11, 13, 15, 16, 14, 12, 10, 8, 6, 4, 2],
  right: [0, 2, 4, 6, 8, 10, 12, 14, 16, 15, 13, 11, 9, 7, 5, 3, 1],
};

// ─── Rodent schema ────────────────────────────────────────────────────────
// 7 keypoints for top-down rodent tracking (Open Field / Elevated Plus Maze).
// Ids 0..6 → N, LEar, REar, BC, TB, TM, TT.

export const RODENT_KEYPOINTS: Keypoint[] = [
  { id: 0, name: 'nose',        label: 'Nose',        side: 'center' },
  { id: 1, name: 'left_ear',    label: 'Left ear',    side: 'left'   },
  { id: 2, name: 'right_ear',   label: 'Right ear',   side: 'right'  },
  { id: 3, name: 'body_center', label: 'Body center', side: 'center' },
  { id: 4, name: 'tail_base',   label: 'Tail base',   side: 'center' },
  { id: 5, name: 'tail_middle', label: 'Tail middle', side: 'center' },
  { id: 6, name: 'tail_tip',    label: 'Tail tip',    side: 'center' },
];

// Canvas 200x400 (same as COCO avatar). Rodent is viewed top-down with the
// head pointing up; in that orientation the rodent's anatomical left is on
// the viewer's right, matching the COCO convention used by the infant
// schema. So left_ear sits at x>100 and right_ear at x<100.
export const RODENT_AVATAR_POSITIONS: Record<number, [number, number]> = {
  0: [100, 45],    // nose
  1: [120, 72],    // left ear  (anatomical left → viewer's right)
  2: [80,  72],    // right ear
  3: [100, 160],   // body center
  4: [100, 240],   // tail base
  5: [100, 310],   // tail middle
  6: [100, 370],   // tail tip
};

export const RODENT_SKELETON: [number, number][] = [
  [0, 1], [0, 2],         // nose → ears
  [1, 3], [2, 3],         // ears → body center
  [3, 4], [4, 5], [5, 6], // body → tail
];

// Rodent is a linear head→tail walk; there's no meaningful contour variant,
// so left/right map to the same top-down order. Kept as a full OrderMode map
// so the annotate page stays schema-agnostic.
const RODENT_ORDER: readonly number[] = [0, 1, 2, 3, 4, 5, 6];
export const RODENT_ORDERINGS: Record<OrderMode, readonly number[]> = {
  top:   RODENT_ORDER,
  left:  RODENT_ORDER,
  right: RODENT_ORDER,
};

// ─── Schema bundle ────────────────────────────────────────────────────────
// Consumers branch on this instead of importing the raw constants, so every
// schema-aware component sees the same API shape.

export type PoseSchema = 'infant' | 'rodent';

export interface PoseSchemaBundle {
  keypoints: Keypoint[];
  avatarPositions: Record<number, [number, number]>;
  skeleton: [number, number][];
  orderings: Record<OrderMode, readonly number[]>;
  /** True if the schema has a meaningful left/right contour traversal. */
  hasContourModes: boolean;
}

export const INFANT_SCHEMA: PoseSchemaBundle = {
  keypoints: COCO_KEYPOINTS,
  avatarPositions: AVATAR_POSITIONS,
  skeleton: SKELETON,
  orderings: ORDERINGS,
  hasContourModes: true,
};

export const RODENT_SCHEMA: PoseSchemaBundle = {
  keypoints: RODENT_KEYPOINTS,
  avatarPositions: RODENT_AVATAR_POSITIONS,
  skeleton: RODENT_SKELETON,
  orderings: RODENT_ORDERINGS,
  hasContourModes: false,
};

export function getSchemaBundle(schema: PoseSchema): PoseSchemaBundle {
  return schema === 'rodent' ? RODENT_SCHEMA : INFANT_SCHEMA;
}
