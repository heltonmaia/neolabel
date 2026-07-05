import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { GoogleLogin } from '@react-oauth/google';
import { loginWithGoogle } from '@/api/auth';
import { useAuth } from '@/stores/auth';

export default function LoginPage() {
  const setToken = useAuth((s) => s.setToken);
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);

  async function onGoogle(credential: string | undefined) {
    setError(null);
    if (!credential) {
      setError('Google sign-in failed. Please try again.');
      return;
    }
    try {
      const { access_token } = await loginWithGoogle(credential);
      setToken(access_token);
      navigate('/projects');
    } catch (err) {
      const status = (err as { response?: { status?: number } })?.response?.status;
      setError(
        status === 403
          ? 'This Google account is not authorized.'
          : 'Sign-in failed. Please try again.',
      );
    }
  }

  return (
    <div className="min-h-full grid lg:grid-cols-[1.05fr_1fr]">
      <aside className="relative isolate hidden lg:flex flex-col justify-between overflow-hidden border-r border-slate-200/70 bg-slate-50 p-12">
        <div
          aria-hidden="true"
          className="dot-grid absolute inset-0 -z-10"
        />
        <div
          aria-hidden="true"
          className="absolute inset-0 -z-10 bg-gradient-to-b from-white/30 via-transparent to-white/85"
        />

        <div className="flex items-center gap-2.5 text-slate-900">
          <LogoMark />
          <span className="text-lg font-semibold tracking-tight">NeoLabel</span>
        </div>

        <div className="flex items-end justify-center gap-10">
          <figure className="flex w-[190px] flex-col items-center">
            <PoseHero />
            <figcaption className="mt-3 text-[11px] font-medium uppercase tracking-[0.12em] text-slate-500">
              Infant · 17 pts
            </figcaption>
          </figure>
          <figure className="flex w-[140px] flex-col items-center">
            <RodentHero />
            <figcaption className="mt-3 text-[11px] font-medium uppercase tracking-[0.12em] text-slate-500">
              Rodent · 7 pts
            </figcaption>
          </figure>
        </div>

        <div className="max-w-md">
          <h2 className="text-[27px] font-semibold leading-[1.15] tracking-tight text-slate-900">
            Video-based pose annotation, built for research.
          </h2>
          <p className="mt-4 text-sm leading-relaxed text-slate-600">
            Label frames, assign work to annotators, and export ready-to-train
            datasets — 17-point infant pose (COCO) and 7-point rodent pose for
            assays like Open Field and Elevated Plus Maze.
          </p>
          <div className="mt-6 flex flex-wrap gap-2 text-[11px]">
            <Chip>Infant · 17-pt COCO</Chip>
            <Chip>Rodent · 7-pt (OF / EPM)</Chip>
            <Chip>FFmpeg frames</Chip>
            <Chip>YOLO-pose export</Chip>
          </div>
        </div>
      </aside>

      <main className="flex items-center justify-center bg-white px-6 py-10">
        <div className="w-full max-w-[340px]">
          <div className="flex items-center gap-2.5 text-slate-900 lg:hidden">
            <LogoMark />
            <span className="text-lg font-semibold tracking-tight">NeoLabel</span>
          </div>

          <div className="mt-10 lg:mt-0">
            <h1 className="text-xl font-semibold tracking-tight text-slate-900">
              Sign in to your workspace
            </h1>
            <p className="mt-2 text-sm text-slate-500">
              Continue with your authorized Google account.
            </p>
          </div>

          <div className="mt-7 flex">
            <GoogleLogin
              onSuccess={(cred) => onGoogle(cred.credential)}
              onError={() => setError('Google sign-in failed. Please try again.')}
            />
          </div>

          {error && (
            <p className="mt-4 text-sm text-red-600" role="alert">
              {error}
            </p>
          )}
        </div>
      </main>
    </div>
  );
}

function Chip({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded-full bg-white px-3 py-1 text-slate-600 ring-1 ring-slate-200/80">
      {children}
    </span>
  );
}

function LogoMark() {
  return (
    <svg width="28" height="28" viewBox="0 0 40 40" aria-hidden="true">
      <defs>
        <linearGradient id="lg" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#38bdf8" />
          <stop offset="100%" stopColor="#a855f7" />
        </linearGradient>
      </defs>
      <circle cx="20" cy="20" r="18" fill="url(#lg)" opacity="0.15" />
      <circle cx="20" cy="12" r="3" fill="#ec4899" />
      <circle cx="14" cy="20" r="2.5" fill="#3b82f6" />
      <circle cx="26" cy="20" r="2.5" fill="#3b82f6" />
      <circle cx="17" cy="30" r="2.5" fill="#a855f7" />
      <circle cx="23" cy="30" r="2.5" fill="#a855f7" />
      <path d="M20,12 L14,20 M20,12 L26,20 M14,20 L17,30 M26,20 L23,30"
            stroke="#64748b" strokeWidth="1" strokeDasharray="2 2" fill="none" />
    </svg>
  );
}

// Decorative pose illustration — synthetic silhouette with COCO-style keypoints.
// No real imagery; purely illustrative.
function PoseHero() {
  const dots = [
    { x: 140, y: 60, c: '#ec4899' },   // nose
    { x: 128, y: 52, c: '#ec4899' },   // eye L
    { x: 152, y: 52, c: '#ec4899' },   // eye R
    { x: 118, y: 58, c: '#ec4899' },   // ear L
    { x: 162, y: 58, c: '#ec4899' },   // ear R
    { x: 108, y: 110, c: '#3b82f6' },  // shoulder L
    { x: 172, y: 110, c: '#3b82f6' },  // shoulder R
    { x: 88,  y: 150, c: '#3b82f6' },  // elbow L
    { x: 192, y: 150, c: '#3b82f6' },  // elbow R
    { x: 72,  y: 190, c: '#3b82f6' },  // wrist L
    { x: 208, y: 190, c: '#3b82f6' },  // wrist R
    { x: 118, y: 200, c: '#a855f7' },  // hip L
    { x: 162, y: 200, c: '#a855f7' },  // hip R
    { x: 112, y: 260, c: '#a855f7' },  // knee L
    { x: 168, y: 260, c: '#a855f7' },  // knee R
    { x: 108, y: 320, c: '#a855f7' },  // ankle L
    { x: 172, y: 320, c: '#a855f7' },  // ankle R
  ];
  const edges: [number, number][] = [
    [0, 1], [0, 2], [1, 3], [2, 4],
    [5, 6], [5, 7], [7, 9], [6, 8], [8, 10],
    [5, 11], [6, 12], [11, 12],
    [11, 13], [13, 15], [12, 14], [14, 16],
  ];

  return (
    <svg viewBox="0 0 280 380" className="w-full max-w-[340px] drop-shadow-sm">
      <defs>
        <radialGradient id="halo" cx="50%" cy="45%" r="55%">
          <stop offset="0%" stopColor="#ffffff" stopOpacity="0.9" />
          <stop offset="100%" stopColor="#ffffff" stopOpacity="0" />
        </radialGradient>
        <linearGradient id="silhouette" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#bae6fd" />
          <stop offset="100%" stopColor="#e0e7ff" />
        </linearGradient>
      </defs>

      <circle cx="140" cy="170" r="160" fill="url(#halo)" />

      <g opacity="0.55">
        <circle cx="140" cy="60" r="38" fill="url(#silhouette)" />
        <path
          d="M95,110 Q80,180 98,210 L182,210 Q200,180 185,110 Q140,92 95,110 Z"
          fill="url(#silhouette)"
        />
        <path d="M95,115 Q68,160 70,200 L82,205 Q90,165 105,120 Z" fill="url(#silhouette)" />
        <path d="M185,115 Q212,160 210,200 L198,205 Q190,165 175,120 Z" fill="url(#silhouette)" />
        <path d="M110,210 Q100,275 108,325 L122,325 Q128,275 130,215 Z" fill="url(#silhouette)" />
        <path d="M170,210 Q180,275 172,325 L158,325 Q152,275 150,215 Z" fill="url(#silhouette)" />
      </g>

      {edges.map(([a, b], i) => (
        <line
          key={i}
          x1={dots[a].x} y1={dots[a].y}
          x2={dots[b].x} y2={dots[b].y}
          stroke="#64748b" strokeWidth="1.2" strokeDasharray="3 3" opacity="0.65"
        />
      ))}

      {dots.map((d, i) => (
        <g key={i}>
          <circle cx={d.x} cy={d.y} r="10" fill={d.c} opacity="0.25" />
          <circle cx={d.x} cy={d.y} r="6" fill={d.c} stroke="white" strokeWidth="1.5" />
        </g>
      ))}
    </svg>
  );
}

// Decorative rodent (top-down) — 7 keypoints: nose, L/R ears, body center,
// tail base/middle/tip. Behavioral-assay view (Open Field / EPM).
function RodentHero() {
  const dots = [
    { x: 110, y: 30,  c: '#ec4899' },  // N
    { x: 82,  y: 52,  c: '#ec4899' },  // LEar
    { x: 138, y: 52,  c: '#ec4899' },  // REar
    { x: 110, y: 140, c: '#3b82f6' },  // BC
    { x: 110, y: 215, c: '#a855f7' },  // TB
    { x: 110, y: 290, c: '#a855f7' },  // TM
    { x: 110, y: 360, c: '#a855f7' },  // TT
  ];
  const edges: [number, number][] = [
    [0, 1], [0, 2],
    [1, 3], [2, 3],
    [3, 4], [4, 5], [5, 6],
  ];

  return (
    <svg viewBox="0 0 220 380" className="w-full drop-shadow-sm">
      <defs>
        <radialGradient id="halo-r" cx="50%" cy="45%" r="55%">
          <stop offset="0%" stopColor="#ffffff" stopOpacity="0.9" />
          <stop offset="100%" stopColor="#ffffff" stopOpacity="0" />
        </radialGradient>
        <linearGradient id="rodent-body" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#e7e5e4" />
          <stop offset="100%" stopColor="#d6d3d1" />
        </linearGradient>
      </defs>

      <circle cx="110" cy="170" r="160" fill="url(#halo-r)" />

      <g opacity="0.6">
        <ellipse cx="86"  cy="50" rx="9"  ry="11" fill="url(#rodent-body)" />
        <ellipse cx="134" cy="50" rx="9"  ry="11" fill="url(#rodent-body)" />
        <ellipse cx="110" cy="140" rx="42" ry="68" fill="url(#rodent-body)" />
        <ellipse cx="110" cy="62"  rx="28" ry="26" fill="url(#rodent-body)" />
        <path
          d="M110,210 Q104,252 113,294 Q120,332 108,362"
          stroke="url(#rodent-body)" strokeWidth="6" fill="none" strokeLinecap="round"
        />
      </g>

      {edges.map(([a, b], i) => (
        <line
          key={i}
          x1={dots[a].x} y1={dots[a].y}
          x2={dots[b].x} y2={dots[b].y}
          stroke="#64748b" strokeWidth="1.2" strokeDasharray="3 3" opacity="0.65"
        />
      ))}

      {dots.map((d, i) => (
        <g key={i}>
          <circle cx={d.x} cy={d.y} r="10" fill={d.c} opacity="0.25" />
          <circle cx={d.x} cy={d.y} r="6" fill={d.c} stroke="white" strokeWidth="1.5" />
        </g>
      ))}
    </svg>
  );
}
