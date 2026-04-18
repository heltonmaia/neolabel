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

// Reference positions on the avatar canvas (viewBox 200 x 400)
// Baby proportions: large head (~1/4 height), short limbs
export const AVATAR_POSITIONS: Record<number, [number, number]> = {
  0:  [100, 70],    // nose
  1:  [90,  60],    // left eye
  2:  [110, 60],    // right eye
  3:  [75,  72],    // left ear
  4:  [125, 72],    // right ear
  5:  [70,  140],   // left shoulder
  6:  [130, 140],   // right shoulder
  7:  [55,  190],   // left elbow
  8:  [145, 190],   // right elbow
  9:  [45,  235],   // left wrist
  10: [155, 235],   // right wrist
  11: [82,  235],   // left hip
  12: [118, 235],   // right hip
  13: [78,  295],   // left knee
  14: [122, 295],   // right knee
  15: [75,  355],   // left ankle
  16: [125, 355],   // right ankle
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
