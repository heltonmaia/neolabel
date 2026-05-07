import {
  AVATAR_POSITIONS,
  COCO_KEYPOINTS,
  SKELETON,
  type KeypointValue,
} from '@/lib/keypoints';

interface Props {
  currentId: number;
  keypoints: Record<number, KeypointValue | null>;
  /** Ids of keypoints the annotator marked as "out of frame". */
  outOfFrame?: ReadonlySet<number>;
  onSelect: (id: number) => void;
}

// Color palette by body region
const REGION_COLOR: Record<number, string> = {
  0: '#ec4899', 1: '#ec4899', 2: '#ec4899', 3: '#ec4899', 4: '#ec4899', // head – pink
  5: '#3b82f6', 6: '#3b82f6',                                           // shoulders – blue
  7: '#3b82f6', 8: '#3b82f6', 9: '#3b82f6', 10: '#3b82f6',              // arms
  11: '#a855f7', 12: '#a855f7',                                         // hips – purple
  13: '#a855f7', 14: '#a855f7', 15: '#a855f7', 16: '#a855f7',           // legs
};

export default function BabyAvatar({ currentId, keypoints, outOfFrame, onSelect }: Props) {
  return (
    <svg viewBox="0 0 220 420" className="w-full max-w-[240px] mx-auto block">
      <defs>
        <radialGradient id="skin" cx="50%" cy="40%" r="60%">
          <stop offset="0%" stopColor="#fef3c7" />
          <stop offset="100%" stopColor="#fcd34d" />
        </radialGradient>
        <linearGradient id="body" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#fde68a" />
          <stop offset="100%" stopColor="#fbbf24" />
        </linearGradient>
        <filter id="soft" x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur in="SourceGraphic" stdDeviation="0.5" />
        </filter>
      </defs>

      {/* Body with a cute pose */}
      <g filter="url(#soft)">
        {/* Legs outline */}
        <path
          d="M85,250 Q80,320 80,370 L95,370 Q100,320 105,255 Z"
          fill="url(#body)" stroke="#b45309" strokeWidth="1.2"
        />
        <path
          d="M125,250 Q140,320 140,370 L125,370 Q118,320 115,255 Z"
          fill="url(#body)" stroke="#b45309" strokeWidth="1.2"
        />
        {/* Torso / onesie */}
        <path
          d="M70,150 Q62,200 75,255 L145,255 Q158,200 150,150 Q110,130 70,150 Z"
          fill="#bae6fd" stroke="#0284c7" strokeWidth="1.3"
        />
        {/* Arms */}
        <path d="M72,150 Q52,195 50,240 L60,245 Q68,200 82,160 Z"
              fill="url(#body)" stroke="#b45309" strokeWidth="1.2" />
        <path d="M148,150 Q168,195 170,240 L160,245 Q152,200 138,160 Z"
              fill="url(#body)" stroke="#b45309" strokeWidth="1.2" />
        {/* Feet */}
        <ellipse cx="87" cy="375" rx="12" ry="6" fill="#f97316" stroke="#9a3412" strokeWidth="1"/>
        <ellipse cx="133" cy="375" rx="12" ry="6" fill="#f97316" stroke="#9a3412" strokeWidth="1"/>
        {/* Head */}
        <circle cx="110" cy="75" r="45" fill="url(#skin)" stroke="#b45309" strokeWidth="1.4"/>
        {/* Hair tuft */}
        <path d="M100,38 Q105,28 110,36 Q115,28 120,38"
              fill="none" stroke="#78350f" strokeWidth="3" strokeLinecap="round"/>
        {/* Eyes (closed cute) */}
        <path d="M95,72 Q100,68 105,72" stroke="#1e293b" strokeWidth="1.8" fill="none" strokeLinecap="round"/>
        <path d="M115,72 Q120,68 125,72" stroke="#1e293b" strokeWidth="1.8" fill="none" strokeLinecap="round"/>
        {/* Cheeks */}
        <circle cx="90" cy="85" r="6" fill="#fca5a5" opacity="0.65"/>
        <circle cx="130" cy="85" r="6" fill="#fca5a5" opacity="0.65"/>
        {/* Smile */}
        <path d="M102,95 Q110,102 118,95" stroke="#be123c" strokeWidth="1.5" fill="none" strokeLinecap="round"/>
        {/* Neck shadow */}
        <ellipse cx="110" cy="125" rx="14" ry="5" fill="#fbbf24" opacity="0.5"/>
      </g>

      {/* Skeleton dashed lines */}
      {SKELETON.map(([a, b], i) => {
        const pa = AVATAR_POSITIONS[a];
        const pb = AVATAR_POSITIONS[b];
        return (
          <line key={i}
            x1={pa[0] + 10} y1={pa[1] + 10}
            x2={pb[0] + 10} y2={pb[1] + 10}
            stroke="#64748b" strokeWidth="1" strokeDasharray="2 2" opacity="0.6"/>
        );
      })}

      {/* Keypoints with numbers */}
      {COCO_KEYPOINTS.map((kp) => {
        const [rawX, rawY] = AVATAR_POSITIONS[kp.id];
        const x = rawX + 10, y = rawY + 10;  // shifted to keep positions centered on new bigger avatar
        const value = keypoints[kp.id];
        const isCurrent = kp.id === currentId;
        const isOOF = !!outOfFrame?.has(kp.id);
        const isDone = !!value && value[2] > 0;
        const isOccluded = !!value && value[2] === 1;
        const baseColor = REGION_COLOR[kp.id] ?? '#64748b';
        const fill = isCurrent
          ? '#ef4444'
          : isOOF
            ? '#94a3b8'
            : isDone
              ? baseColor
              : '#e2e8f0';
        const stroke = isCurrent ? '#991b1b' : isOOF ? '#475569' : isDone ? '#1e293b' : '#94a3b8';
        const r = isCurrent ? 11 : 9;

        return (
          <g key={kp.id} onClick={() => onSelect(kp.id)} className="cursor-pointer group">
            {isCurrent && (
              <circle cx={x} cy={y} r="16" fill="none" stroke="#ef4444"
                      strokeWidth="2" opacity="0.4">
                <animate attributeName="r" values="14;18;14" dur="1.2s" repeatCount="indefinite"/>
              </circle>
            )}
            <circle
              cx={x} cy={y}
              r={r}
              fill={fill}
              stroke={stroke}
              strokeWidth="1.5"
              className="transition-all group-hover:stroke-slate-900"
              strokeDasharray={isOccluded ? '2 2' : undefined}
            />
            {isOOF && (
              <line
                x1={x - r * 0.7} y1={y - r * 0.7}
                x2={x + r * 0.7} y2={y + r * 0.7}
                stroke="#1e293b" strokeWidth="1.5" strokeLinecap="round"
                pointerEvents="none"
              />
            )}
            <text
              x={x} y={y + 3.5}
              textAnchor="middle"
              fontSize="9.5"
              fontWeight="700"
              fill={isCurrent || isDone || isOOF ? 'white' : '#475569'}
              className="pointer-events-none select-none"
            >
              {kp.id + 1}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
