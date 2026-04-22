import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { useNavigate } from 'react-router-dom';
import { login } from '@/api/auth';
import { useAuth } from '@/stores/auth';

interface Form { username: string; password: string }

export default function LoginPage() {
  const { register, handleSubmit } = useForm<Form>({
    defaultValues: { username: '', password: '' },
  });
  const setToken = useAuth((s) => s.setToken);
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(values: Form) {
    setError(null);
    setLoading(true);
    try {
      const { access_token } = await login(values.username, values.password);
      setToken(access_token);
      navigate('/projects');
    } catch {
      setError('Invalid credentials');
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-full grid lg:grid-cols-2">
      <aside className="relative hidden lg:flex flex-col justify-between p-10 overflow-hidden bg-gradient-to-br from-sky-50 via-amber-50 to-rose-50">
        <div className="absolute inset-0 -z-10 opacity-60">
          <div className="absolute top-10 -left-20 h-72 w-72 rounded-full bg-sky-200 blur-3xl" />
          <div className="absolute bottom-0 right-0 h-80 w-80 rounded-full bg-amber-200 blur-3xl" />
          <div className="absolute top-1/3 right-1/3 h-56 w-56 rounded-full bg-rose-200 blur-3xl" />
        </div>

        <div>
          <div className="flex items-center gap-2 text-sky-900">
            <LogoMark />
            <span className="text-lg font-semibold tracking-tight">NeoLabel</span>
          </div>
        </div>

        <div className="flex items-end justify-center gap-6 -my-4">
          <figure className="flex flex-col items-center w-[200px]">
            <PoseHero />
            <figcaption className="mt-1 text-xs font-medium text-slate-600">
              Infant · 17 keypoints
            </figcaption>
          </figure>
          <figure className="flex flex-col items-center w-[150px]">
            <RodentHero />
            <figcaption className="mt-1 text-xs font-medium text-slate-600">
              Rodent · 7 keypoints
            </figcaption>
          </figure>
        </div>

        <div className="max-w-md">
          <h2 className="text-2xl font-semibold text-slate-900 leading-snug">
            Video-based pose annotation, built for research.
          </h2>
          <p className="mt-3 text-slate-700">
            Label video frames, assign work to annotators, and export
            ready-to-train datasets. Two keypoint schemas ship by default:
            17-point infant pose (COCO) and 7-point rodent pose for
            behavioral assays such as Open Field and Elevated Plus Maze.
          </p>
          <div className="mt-6 flex flex-wrap gap-2 text-xs">
            <Chip>Infant · 17-pt COCO</Chip>
            <Chip>Rodent · 7-pt (OF / EPM)</Chip>
            <Chip>FFmpeg frame extraction</Chip>
            <Chip>YOLO-pose export</Chip>
          </div>
        </div>
      </aside>

      <main className="flex items-center justify-center p-6 lg:p-10">
        <form
          onSubmit={handleSubmit(onSubmit)}
          className="w-full max-w-sm bg-white p-8 rounded-xl shadow-sm ring-1 ring-slate-200 space-y-5"
        >
          <div className="flex items-center gap-2 lg:hidden">
            <LogoMark />
            <span className="text-lg font-semibold tracking-tight text-sky-900">NeoLabel</span>
          </div>
          <div>
            <h1 className="text-2xl font-semibold text-slate-900">Sign in</h1>
            <p className="mt-1 text-sm text-slate-500">Access your annotation workspace.</p>
          </div>

          <label className="block space-y-1">
            <span className="text-xs font-medium text-slate-600 uppercase tracking-wide">Username</span>
            <input
              {...register('username', { required: true })}
              autoComplete="username"
              placeholder="annotator"
              className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm
                         focus:outline-none focus:ring-2 focus:ring-sky-500 focus:border-sky-500"
            />
          </label>

          <label className="block space-y-1">
            <span className="text-xs font-medium text-slate-600 uppercase tracking-wide">Password</span>
            <input
              {...register('password', { required: true })}
              type="password"
              autoComplete="current-password"
              placeholder="••••••••"
              className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm
                         focus:outline-none focus:ring-2 focus:ring-sky-500 focus:border-sky-500"
            />
          </label>

          {error && <p className="text-red-600 text-sm">{error}</p>}

          <button
            disabled={loading}
            className="w-full py-2.5 rounded-md text-white font-medium
                       bg-gradient-to-r from-sky-600 to-sky-700 hover:from-sky-700 hover:to-sky-800
                       disabled:opacity-60 disabled:cursor-not-allowed transition"
          >
            {loading ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      </main>
    </div>
  );
}

function Chip({ children }: { children: React.ReactNode }) {
  return (
    <span className="px-2.5 py-1 rounded-full bg-white/70 backdrop-blur text-slate-700 ring-1 ring-slate-200">
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
