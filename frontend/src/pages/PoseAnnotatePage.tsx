import { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { getProject } from '@/api/projects';
import { getItem, listItems, saveAnnotation } from '@/api/items';
import { FILES_BASE } from '@/lib/env';
import BabyAvatar from '@/components/BabyAvatar';
import { COCO_KEYPOINTS, type KeypointValue } from '@/lib/keypoints';

type KeypointsMap = Record<number, KeypointValue | null>;

function emptyKeypoints(): KeypointsMap {
  const m: KeypointsMap = {};
  for (const kp of COCO_KEYPOINTS) m[kp.id] = null;
  return m;
}

export default function PoseAnnotatePage() {
  const { id, itemId } = useParams();
  const projectId = Number(id);
  const currentItemId = Number(itemId);
  const qc = useQueryClient();
  const navigate = useNavigate();

  const projectQ = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => getProject(projectId),
  });
  const itemQ = useQuery({
    queryKey: ['item', currentItemId],
    queryFn: () => getItem(currentItemId),
  });
  const itemsQ = useQuery({
    queryKey: ['items', projectId],
    queryFn: () => listItems(projectId),
  });

  const [currentKp, setCurrentKp] = useState(0);
  const [keypoints, setKeypoints] = useState<KeypointsMap>(emptyKeypoints());
  const historyRef = useRef<KeypointsMap[]>([]);
  const imgRef = useRef<HTMLImageElement>(null);

  // Keyboard cursor position (as 0-1 percent of image)
  const [cursor, setCursor] = useState<{ x: number; y: number }>({ x: 0.5, y: 0.5 });
  const [keyboardMode, setKeyboardMode] = useState(false);

  useEffect(() => {
    const existing = itemQ.data?.annotation?.value as
      | { keypoints?: KeypointValue[] }
      | undefined;
    if (existing?.keypoints && existing.keypoints.length === 17) {
      const m: KeypointsMap = {};
      existing.keypoints.forEach((v, i) => {
        m[i] = v[2] > 0 ? v : null;
      });
      setKeypoints(m);
    } else {
      setKeypoints(emptyKeypoints());
    }
    historyRef.current = [];
    setCurrentKp(0);
  }, [currentItemId, itemQ.data?.id]);

  const items = itemsQ.data?.items ?? [];
  const idx = useMemo(
    () => items.findIndex((i) => i.id === currentItemId),
    [items, currentItemId],
  );
  const prev = idx > 0 ? items[idx - 1] : null;
  const next = idx >= 0 && idx < items.length - 1 ? items[idx + 1] : null;

  const save = useMutation({
    mutationFn: (kps: KeypointsMap) => {
      const arr: KeypointValue[] = COCO_KEYPOINTS.map(
        (kp) => kps[kp.id] ?? ([0, 0, 0] as KeypointValue),
      );
      return saveAnnotation(currentItemId, { keypoints: arr });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['items', projectId] });
      qc.invalidateQueries({ queryKey: ['item', currentItemId] });
    },
  });

  function pushHistory() {
    historyRef.current.push({ ...keypoints });
    if (historyRef.current.length > 50) historyRef.current.shift();
  }

  function advanceAfterPlace(nextMap: KeypointsMap, placed: number) {
    const unset = COCO_KEYPOINTS.find((kp) => kp.id > placed && !nextMap[kp.id]);
    if (unset) setCurrentKp(unset.id);
    else if (placed < 16) setCurrentKp(placed + 1);
  }

  function placeAt(xNat: number, yNat: number) {
    pushHistory();
    const nextMap: KeypointsMap = {
      ...keypoints,
      [currentKp]: [Math.round(xNat), Math.round(yNat), 2],
    };
    setKeypoints(nextMap);
    save.mutate(nextMap);
    advanceAfterPlace(nextMap, currentKp);
  }

  function handleImageClick(e: React.MouseEvent<HTMLImageElement>) {
    const img = e.currentTarget;
    const rect = img.getBoundingClientRect();
    const xPct = (e.clientX - rect.left) / rect.width;
    const yPct = (e.clientY - rect.top) / rect.height;
    setCursor({ x: xPct, y: yPct });
    placeAt(xPct * img.naturalWidth, yPct * img.naturalHeight);
  }

  function placeAtCursor() {
    const img = imgRef.current;
    if (!img) return;
    placeAt(cursor.x * img.naturalWidth, cursor.y * img.naturalHeight);
  }

  function markOccluded() {
    pushHistory();
    const nextMap: KeypointsMap = { ...keypoints, [currentKp]: [0, 0, 1] };
    setKeypoints(nextMap);
    save.mutate(nextMap);
    if (currentKp < 16) setCurrentKp(currentKp + 1);
  }

  function clearCurrent() {
    pushHistory();
    const nextMap: KeypointsMap = { ...keypoints, [currentKp]: null };
    setKeypoints(nextMap);
    save.mutate(nextMap);
  }

  function clearAll() {
    if (!confirm('Clear all keypoints?')) return;
    pushHistory();
    const m = emptyKeypoints();
    setKeypoints(m);
    save.mutate(m);
    setCurrentKp(0);
  }

  function undo() {
    const prev = historyRef.current.pop();
    if (!prev) return;
    setKeypoints(prev);
    save.mutate(prev);
  }

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.target as HTMLElement)?.tagName === 'INPUT') return;

      // Navigate items
      if (e.key === ']' && next) return navigate(`/projects/${projectId}/annotate/${next.id}`);
      if (e.key === '[' && prev) return navigate(`/projects/${projectId}/annotate/${prev.id}`);

      // Switch keypoint
      if (e.key === 'Tab') {
        e.preventDefault();
        setCurrentKp((k) => (e.shiftKey ? (k + 16) % 17 : (k + 1) % 17));
        return;
      }
      if (e.key === 'n' || e.key === 'N') return setCurrentKp((k) => (k + 1) % 17);
      if (e.key === 'p' || e.key === 'P') return setCurrentKp((k) => (k + 16) % 17);

      // Number keys 1-9 jump to keypoint 1-9
      if (e.key >= '1' && e.key <= '9') {
        setCurrentKp(Number(e.key) - 1);
        return;
      }

      // Keyboard cursor movement on image
      const step = e.shiftKey ? 0.05 : 0.01;
      if (e.key === 'ArrowLeft')  { e.preventDefault(); setKeyboardMode(true); setCursor((c) => ({ ...c, x: Math.max(0, c.x - step) })); return; }
      if (e.key === 'ArrowRight') { e.preventDefault(); setKeyboardMode(true); setCursor((c) => ({ ...c, x: Math.min(1, c.x + step) })); return; }
      if (e.key === 'ArrowUp')    { e.preventDefault(); setKeyboardMode(true); setCursor((c) => ({ ...c, y: Math.max(0, c.y - step) })); return; }
      if (e.key === 'ArrowDown')  { e.preventDefault(); setKeyboardMode(true); setCursor((c) => ({ ...c, y: Math.min(1, c.y + step) })); return; }

      // Actions
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); placeAtCursor(); return; }
      if (e.key === 'o' || e.key === 'O') return markOccluded();
      if (e.key === 'u' || e.key === 'U') return undo();
      if (e.key === 'Backspace') return clearCurrent();
      if (e.key === 'c' || e.key === 'C') return clearAll();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentKp, keypoints, prev, next, cursor]);

  if (itemQ.isLoading || projectQ.isLoading) return <p className="p-6">Loading…</p>;
  if (!itemQ.data || !projectQ.data) return <p className="p-6">Not found.</p>;

  const item = itemQ.data;
  const project = projectQ.data;
  const imageUrl = (item.payload as { image_url?: string }).image_url;
  const fullUrl = imageUrl ? `${FILES_BASE}${imageUrl}` : null;
  const doneCount = Object.values(keypoints).filter((v) => v && v[2] > 0).length;

  return (
    <div className="max-w-7xl mx-auto p-4 space-y-4">
      <header className="flex items-center justify-between">
        <Link to={`/projects/${projectId}`} className="text-sm text-blue-600 hover:underline">
          ← {project.name}
        </Link>
        <span className="text-sm text-slate-500">
          {idx >= 0 ? `${idx + 1} / ${items.length}` : ''} · {doneCount}/17 keypoints
        </span>
      </header>

      <div className="grid grid-cols-1 lg:grid-cols-[1fr_340px] gap-4">
        {/* Image */}
        <div
          className="bg-slate-900 rounded-lg overflow-hidden flex items-center justify-center min-h-[400px] relative"
          tabIndex={0}
        >
          {fullUrl ? (
            <>
              <img
                ref={imgRef}
                src={fullUrl}
                onClick={handleImageClick}
                onMouseMove={() => keyboardMode && setKeyboardMode(false)}
                className="max-w-full max-h-[80vh] cursor-crosshair select-none"
                draggable={false}
                alt="frame"
              />
              {/* Render existing keypoints overlay */}
              {imgRef.current && (
                <svg
                  className="absolute pointer-events-none"
                  style={{
                    left: imgRef.current.offsetLeft,
                    top: imgRef.current.offsetTop,
                    width: imgRef.current.clientWidth,
                    height: imgRef.current.clientHeight,
                  }}
                  viewBox={`0 0 ${imgRef.current.naturalWidth} ${imgRef.current.naturalHeight}`}
                  preserveAspectRatio="none"
                >
                  {COCO_KEYPOINTS.map((kp) => {
                    const v = keypoints[kp.id];
                    if (!v || v[2] !== 2) return null;
                    const isCurrent = kp.id === currentKp;
                    return (
                      <g key={kp.id}>
                        <circle
                          cx={v[0]} cy={v[1]}
                          r={Math.max(6, imgRef.current!.naturalWidth / 120)}
                          fill={isCurrent ? '#ef4444' : '#10b981'}
                          stroke="white"
                          strokeWidth={Math.max(2, imgRef.current!.naturalWidth / 400)}
                        />
                        <text
                          x={v[0]} y={v[1] + Math.max(3, imgRef.current!.naturalWidth / 300)}
                          textAnchor="middle"
                          fontSize={Math.max(10, imgRef.current!.naturalWidth / 80)}
                          fontWeight="700"
                          fill="white"
                        >
                          {kp.id + 1}
                        </text>
                      </g>
                    );
                  })}
                </svg>
              )}
              {/* Keyboard cursor crosshair */}
              {keyboardMode && imgRef.current && (
                <div
                  className="absolute pointer-events-none"
                  style={{
                    left: imgRef.current.offsetLeft + cursor.x * imgRef.current.clientWidth - 10,
                    top: imgRef.current.offsetTop + cursor.y * imgRef.current.clientHeight - 10,
                    width: 20, height: 20,
                  }}
                >
                  <div className="w-full h-full border-2 border-yellow-400 rounded-full
                                  shadow-[0_0_0_1px_rgba(0,0,0,0.5)]"/>
                  <div className="absolute inset-0 flex items-center justify-center">
                    <div className="w-1 h-1 bg-yellow-400 rounded-full"/>
                  </div>
                </div>
              )}
            </>
          ) : (
            <p className="text-slate-400">No image for this item.</p>
          )}
        </div>

        {/* Avatar + controls */}
        <aside className="bg-white rounded-lg shadow p-4 space-y-4">
          <div className="flex items-baseline justify-between">
            <div>
              <p className="text-xs text-slate-500 uppercase tracking-wide">Next keypoint</p>
              <p className="text-lg font-semibold">
                <span className="inline-block bg-red-500 text-white rounded px-2 mr-2 text-sm">
                  {currentKp + 1}
                </span>
                {COCO_KEYPOINTS[currentKp].label}
              </p>
            </div>
            <span className="text-sm text-slate-400">{doneCount}/17</span>
          </div>

          <BabyAvatar
            currentId={currentKp}
            keypoints={keypoints}
            onSelect={setCurrentKp}
          />

          <div className="grid grid-cols-2 gap-2 text-sm">
            <button onClick={markOccluded}
              className="border rounded px-2 py-1.5 hover:bg-slate-50">
              Occluded <kbd className="text-xs border rounded px-1 ml-1">O</kbd>
            </button>
            <button onClick={undo}
              className="border rounded px-2 py-1.5 hover:bg-slate-50">
              Undo <kbd className="text-xs border rounded px-1 ml-1">U</kbd>
            </button>
            <button onClick={clearCurrent}
              className="border rounded px-2 py-1.5 hover:bg-slate-50">
              Clear point <kbd className="text-xs border rounded px-1 ml-1">⌫</kbd>
            </button>
            <button onClick={clearAll}
              className="border rounded px-2 py-1.5 text-red-600 hover:bg-red-50">
              Clear all <kbd className="text-xs border rounded px-1 ml-1">C</kbd>
            </button>
          </div>

          <details className="text-xs text-slate-600 bg-slate-50 rounded border">
            <summary className="px-2 py-1.5 font-medium cursor-pointer hover:bg-slate-100">
              Keyboard shortcuts
            </summary>
            <div className="px-2 py-2 space-y-1">
              <p><kbd className="border rounded px-1">←↑↓→</kbd> move cursor on image (Shift = bigger step)</p>
              <p><kbd className="border rounded px-1">Enter</kbd> / <kbd className="border rounded px-1">Space</kbd> place keypoint at cursor</p>
              <p><kbd className="border rounded px-1">Tab</kbd> / <kbd className="border rounded px-1">N</kbd> next keypoint · <kbd className="border rounded px-1">Shift+Tab</kbd> / <kbd className="border rounded px-1">P</kbd> previous</p>
              <p><kbd className="border rounded px-1">1</kbd>…<kbd className="border rounded px-1">9</kbd> jump to keypoint 1–9</p>
              <p><kbd className="border rounded px-1">[</kbd> / <kbd className="border rounded px-1">]</kbd> previous / next item</p>
              <p><kbd className="border rounded px-1">O</kbd> mark occluded · <kbd className="border rounded px-1">U</kbd> undo · <kbd className="border rounded px-1">⌫</kbd> clear current · <kbd className="border rounded px-1">C</kbd> clear all</p>
              <p className="text-slate-500 pt-1 border-t">Click on image with mouse, or use arrows + Enter for keyboard-only.</p>
            </div>
          </details>
        </aside>
      </div>

      <footer className="flex items-center justify-between text-sm">
        <button
          onClick={() => prev && navigate(`/projects/${projectId}/annotate/${prev.id}`)}
          disabled={!prev}
          className="px-3 py-1.5 border rounded disabled:opacity-40"
        >
          ← Previous <kbd className="ml-1 text-xs border rounded px-1">[</kbd>
        </button>
        <button
          onClick={() => next && navigate(`/projects/${projectId}/annotate/${next.id}`)}
          disabled={!next}
          className="px-3 py-1.5 border rounded disabled:opacity-40"
        >
          <kbd className="mr-1 text-xs border rounded px-1">]</kbd> Next →
        </button>
      </footer>
    </div>
  );
}
