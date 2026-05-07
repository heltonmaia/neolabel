import {
  RODENT_AVATAR_POSITIONS,
  RODENT_KEYPOINTS,
  RODENT_SKELETON,
  type KeypointValue,
} from '@/lib/keypoints';

interface Props {
  currentId: number;
  keypoints: Record<number, KeypointValue | null>;
  /** Ids of keypoints the annotator marked as "out of frame". */
  outOfFrame?: ReadonlySet<number>;
  onSelect: (id: number) => void;
}

// Matches BabyAvatar's three-region palette so keypoint colors stay
// consistent across schemas: pink → head, blue → body center, purple → tail.
const REGION_COLOR: Record<number, string> = {
  0: '#ec4899', 1: '#ec4899', 2: '#ec4899', // N, LEar, REar
  3: '#3b82f6',                             // BC
  4: '#a855f7', 5: '#a855f7', 6: '#a855f7', // TB, TM, TT
};

export default function RodentAvatar({ currentId, keypoints, outOfFrame, onSelect }: Props) {
  return (
    <svg viewBox="0 0 200 400" className="w-full max-w-[200px] mx-auto block">
      <defs>
        <linearGradient id="rodent-fur" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#e7e5e4" />
          <stop offset="100%" stopColor="#d6d3d1" />
        </linearGradient>
        <filter id="rodent-soft" x="-20%" y="-20%" width="140%" height="140%">
          <feGaussianBlur in="SourceGraphic" stdDeviation="0.5" />
        </filter>
      </defs>

      {/* Top-down rodent silhouette */}
      <g filter="url(#rodent-soft)" opacity="0.7">
        {/* Ears (behind head) */}
        <ellipse cx="78"  cy="68" rx="10" ry="12" fill="url(#rodent-fur)" stroke="#a8a29e" strokeWidth="1" />
        <ellipse cx="122" cy="68" rx="10" ry="12" fill="url(#rodent-fur)" stroke="#a8a29e" strokeWidth="1" />
        {/* Body */}
        <ellipse cx="100" cy="160" rx="46" ry="76" fill="url(#rodent-fur)" stroke="#a8a29e" strokeWidth="1.2" />
        {/* Head */}
        <ellipse cx="100" cy="75" rx="30" ry="28" fill="url(#rodent-fur)" stroke="#a8a29e" strokeWidth="1.2" />
        {/* Tail */}
        <path
          d="M100,235 Q94,280 103,320 Q110,357 98,380"
          stroke="url(#rodent-fur)" strokeWidth="7" fill="none" strokeLinecap="round"
        />
      </g>

      {/* Skeleton dashed lines */}
      {RODENT_SKELETON.map(([a, b], i) => {
        const pa = RODENT_AVATAR_POSITIONS[a];
        const pb = RODENT_AVATAR_POSITIONS[b];
        return (
          <line
            key={i}
            x1={pa[0]} y1={pa[1]}
            x2={pb[0]} y2={pb[1]}
            stroke="#64748b" strokeWidth="1" strokeDasharray="2 2" opacity="0.6"
          />
        );
      })}

      {/* Keypoints with numbers */}
      {RODENT_KEYPOINTS.map((kp) => {
        const [x, y] = RODENT_AVATAR_POSITIONS[kp.id];
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
                <animate attributeName="r" values="14;18;14" dur="1.2s" repeatCount="indefinite" />
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
