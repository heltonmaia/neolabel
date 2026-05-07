import { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { me } from '@/api/auth';
import { getProject } from '@/api/projects';
import { getItem, listAllItems, reviewItem, saveAnnotation } from '@/api/items';
import { FILES_BASE } from '@/lib/env';
import BabyAvatar from '@/components/BabyAvatar';
import RodentAvatar from '@/components/RodentAvatar';
import { useConfirm } from '@/components/ui/ConfirmDialog';
import {
  ORDERINGS,
  getSchemaBundle,
  type Keypoint,
  type KeypointValue,
  type OrderMode,
  type PoseSchema,
} from '@/lib/keypoints';

const ORDER_STORAGE_KEY = 'pose.orderMode';
const REVIEW_MODE_STORAGE_KEY = 'pose.reviewMode';
const ORDER_LABEL: Record<OrderMode, string> = {
  top: 'Top → bottom',
  left: 'Left contour',
  right: 'Right contour',
};

type KeypointsMap = Record<number, KeypointValue | null>;

// Captured from <img> onLoad. We can't derive these from imgRef.current
// during render: setting a ref doesn't trigger a re-render, and naturalW/H
// are 0 until the image actually loads — which would collapse the SVG
// viewBox and hide all keypoints (the bug this state fixes).
type ImgDims = {
  naturalW: number;
  naturalH: number;
  offsetL: number;
  offsetT: number;
  clientW: number;
  clientH: number;
};

type DragState =
  | { mode: 'single'; id: number; moved: boolean }
  | {
      mode: 'group';
      id: number;
      moved: boolean;
      startClientX: number;
      startClientY: number;
      snapshot: KeypointsMap;
      imgW: number;
      imgH: number;
      rectW: number;
      rectH: number;
    };

function emptyKeypoints(schemaKps: Keypoint[]): KeypointsMap {
  const m: KeypointsMap = {};
  for (const kp of schemaKps) m[kp.id] = null;
  return m;
}

function translateAll(
  snapshot: KeypointsMap,
  dx: number,
  dy: number,
  schemaKps: Keypoint[],
): KeypointsMap {
  const next: KeypointsMap = {};
  for (const kp of schemaKps) {
    const v = snapshot[kp.id];
    next[kp.id] = v ? [Math.round(v[0] + dx), Math.round(v[1] + dy), v[2]] : null;
  }
  return next;
}

// Clamp a translation so the bounding box of all placed keypoints stays
// fully inside the image — the whole pose shifts together instead of
// individual points being clipped, which would distort the skeleton.
function clampGroupDelta(
  snapshot: KeypointsMap,
  dx: number,
  dy: number,
  imgW: number,
  imgH: number,
): { dx: number; dy: number } {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  for (const v of Object.values(snapshot)) {
    if (!v) continue;
    if (v[0] < minX) minX = v[0];
    if (v[0] > maxX) maxX = v[0];
    if (v[1] < minY) minY = v[1];
    if (v[1] > maxY) maxY = v[1];
  }
  if (minX === Infinity) return { dx: 0, dy: 0 };
  return {
    dx: Math.max(-minX, Math.min(imgW - maxX, dx)),
    dy: Math.max(-minY, Math.min(imgH - maxY, dy)),
  };
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
    queryFn: () => listAllItems(projectId),
  });
  const meQ = useQuery({ queryKey: ['me'], queryFn: me });

  const schema: PoseSchema = (projectQ.data?.keypoint_schema ?? 'infant') as PoseSchema;
  const bundle = useMemo(() => getSchemaBundle(schema), [schema]);
  const schemaKps = bundle.keypoints;
  const N = schemaKps.length;

  const [currentKp, setCurrentKp] = useState(0);
  const [keypoints, setKeypoints] = useState<KeypointsMap>(() => emptyKeypoints(schemaKps));
  const [orderMode, setOrderMode] = useState<OrderMode>(() => {
    const saved = typeof window !== 'undefined' ? localStorage.getItem(ORDER_STORAGE_KEY) : null;
    return saved && saved in ORDERINGS ? (saved as OrderMode) : 'top';
  });
  const sequence = bundle.orderings[orderMode];

  useEffect(() => {
    localStorage.setItem(ORDER_STORAGE_KEY, orderMode);
  }, [orderMode]);

  // Don't reset imgDims when the item changes — the <img> onLoad will
  // overwrite it once the new image is decoded. An earlier version reset
  // here, which raced with onLoad: for cached images the load event fires
  // very fast (possibly before this effect would run), so setImgDims(null)
  // would clobber the dims set by onLoad and the SVG stayed hidden. All
  // frames in a pose project are 640x640, so leaving the previous dims in
  // place for a frame is invisible.
  const [imgDims, setImgDims] = useState<ImgDims | null>(null);
  const historyRef = useRef<KeypointsMap[]>([]);
  const imgRef = useRef<HTMLImageElement>(null);
  const draggingRef = useRef<DragState | null>(null);
  const nudgeTimerRef = useRef<number | null>(null);
  const saveDebounceRef = useRef<number | null>(null);
  // Guards against rapid-fire clicks / keyboard repeat on Prev/Next: we
  // skip a nav if one was fired within the last ~120ms. Keeps the view
  // from queueing up a backlog of URL changes that can render out of order.
  const navLockRef = useRef(0);
  const goTo = (targetId: number) => {
    const now = Date.now();
    if (now - navLockRef.current < 120) return;
    navLockRef.current = now;
    navigate(`/projects/${projectId}/annotate/${targetId}`);
  };

  // Keyboard cursor position (as 0-1 percent of image)
  const [cursor, setCursor] = useState<{ x: number; y: number }>({ x: 0.5, y: 0.5 });
  const [keyboardMode, setKeyboardMode] = useState(false);

  const confirm = useConfirm();

  // Review-queue mode: when on, the cohort below is also restricted to
  // status='done' items, so admin/owner walks only items pending approval.
  // After approve/send-back the item leaves this set, so we auto-advance to
  // the next one — see handleApprove / handleSendBack below.
  const [reviewMode, setReviewMode] = useState<boolean>(() => {
    return typeof window !== 'undefined'
      && localStorage.getItem(REVIEW_MODE_STORAGE_KEY) === '1';
  });
  useEffect(() => {
    localStorage.setItem(REVIEW_MODE_STORAGE_KEY, reviewMode ? '1' : '0');
  }, [reviewMode]);

  const items = itemsQ.data?.items ?? [];
  // Cohort: items sharing the current item's assignee. Prev/Next walks only
  // within this cohort so navigating an annotator's queue never silently
  // crosses into another annotator's items (or admin sees what the assignee
  // would see). Treat null/undefined as "unassigned" — same group.
  const cohortAssignee = itemQ.data?.assigned_to ?? null;
  const cohort = useMemo(
    () => items.filter((i) => {
      if ((i.assigned_to ?? null) !== cohortAssignee) return false;
      if (reviewMode && i.status !== 'done') return false;
      return true;
    }),
    [items, cohortAssignee, reviewMode],
  );
  const idx = useMemo(
    () => cohort.findIndex((i) => i.id === currentItemId),
    [cohort, currentItemId],
  );
  const prev = idx > 0 ? cohort[idx - 1] : null;
  const next = idx >= 0 && idx < cohort.length - 1 ? cohort[idx + 1] : null;

  // Kept warm so the "Copy previous pose" button can act instantly.
  // Reuses the same cache key as itemQ, so backtracking is free.
  const prevItemQ = useQuery({
    queryKey: ['item', prev?.id],
    queryFn: () => getItem(prev!.id),
    enabled: !!prev,
  });

  const save = useMutation({
    mutationFn: (kps: KeypointsMap) => {
      const arr: KeypointValue[] = schemaKps.map(
        (kp) => kps[kp.id] ?? ([0, 0, 0] as KeypointValue),
      );
      return saveAnnotation(currentItemId, { keypoints: arr });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['items', projectId] });
      qc.invalidateQueries({ queryKey: ['item', currentItemId] });
    },
  });

  // Curation: admin or project owner can approve / send back. Only meaningful
  // when the item is at least 'done' — partial work isn't reviewable.
  const canReview = !!meQ.data && !!projectQ.data && (
    meQ.data.role === 'admin' || meQ.data.id === projectQ.data.owner_id
  );
  const [showSendBack, setShowSendBack] = useState(false);
  const [reviewNoteInput, setReviewNoteInput] = useState('');
  const reviewMut = useMutation({
    mutationFn: (p: { action: 'approve' | 'unapprove' | 'send_back'; note?: string }) =>
      reviewItem(currentItemId, p.action, p.note),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['items', projectId] });
      qc.invalidateQueries({ queryKey: ['item', currentItemId] });
      setShowSendBack(false);
      setReviewNoteInput('');
    },
  });
  // Reset the send-back form when navigating items.
  useEffect(() => {
    setShowSendBack(false);
    setReviewNoteInput('');
  }, [currentItemId]);

  // The Approve button toggles: 'done' -> 'reviewed' -> 'done' -> ...
  // Auto-advance only fires for forward-progress actions (approve, send-back),
  // never for unapprove — that's a correction, the user wants to stay on
  // the item to verify or re-review.
  function handleApprove() {
    const isUnapprove = itemQ.data?.status === 'reviewed';
    const action: 'approve' | 'unapprove' = isUnapprove ? 'unapprove' : 'approve';
    let nextTargetId: number | null = null;
    if (!isUnapprove) {
      const ix = cohort.findIndex((i) => i.id === currentItemId);
      if (ix >= 0 && ix < cohort.length - 1) nextTargetId = cohort[ix + 1].id;
    }
    reviewMut.mutate(
      { action },
      {
        onSuccess: () => {
          if (reviewMode && nextTargetId !== null) {
            navigate(`/projects/${projectId}/annotate/${nextTargetId}`);
          }
        },
      },
    );
  }
  function handleSendBack(note?: string) {
    const ix = cohort.findIndex((i) => i.id === currentItemId);
    const nextTargetId =
      ix >= 0 && ix < cohort.length - 1 ? cohort[ix + 1].id : null;
    reviewMut.mutate(
      { action: 'send_back', note },
      {
        onSuccess: () => {
          if (reviewMode && nextTargetId !== null) {
            navigate(`/projects/${projectId}/annotate/${nextTargetId}`);
          }
        },
      },
    );
  }

  // Load saved annotation (if any) or reset to empty when the item changes.
  // Template reuse is now manual — see copyPreviousPose below.
  useEffect(() => {
    if (itemQ.data?.id !== currentItemId) return;

    if (itemQ.data.annotation) {
      const existing = itemQ.data.annotation.value as
        | { keypoints?: KeypointValue[] }
        | undefined;
      const m = emptyKeypoints(schemaKps);
      if (existing?.keypoints && existing.keypoints.length === N) {
        existing.keypoints.forEach((v, i) => {
          m[i] = v[2] > 0 ? v : null;
        });
      }
      setKeypoints(m);
      historyRef.current = [];
      setCurrentKp(sequence[0]);
      return;
    }

    setKeypoints(emptyKeypoints(schemaKps));
    historyRef.current = [];
    setCurrentKp(sequence[0]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentItemId, itemQ.data?.id, schema]);

  function pushHistory() {
    historyRef.current.push({ ...keypoints });
    if (historyRef.current.length > 50) historyRef.current.shift();
  }

  function advanceAfterPlace(nextMap: KeypointsMap, placed: number) {
    const placedIdx = sequence.indexOf(placed);
    // Walk the chosen sequence forward looking for the next empty slot.
    for (let i = 1; i < N; i++) {
      const cand = sequence[(placedIdx + i) % N];
      if (!nextMap[cand]) {
        setCurrentKp(cand);
        return;
      }
    }
    // Everything labeled — advance to the next position in sequence (or stay).
    if (placedIdx >= 0 && placedIdx < N - 1) setCurrentKp(sequence[placedIdx + 1]);
  }

  function stepCurrent(delta: 1 | -1) {
    setCurrentKp((k) => {
      const idx = sequence.indexOf(k);
      const newIdx = ((idx === -1 ? 0 : idx) + delta + N) % N;
      return sequence[newIdx];
    });
  }

  function placeAt(xNat: number, yNat: number, visibility: 1 | 2 = 2) {
    pushHistory();
    const nextMap: KeypointsMap = {
      ...keypoints,
      [currentKp]: [Math.round(xNat), Math.round(yNat), visibility],
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
    const visibility = e.button === 2 || e.ctrlKey ? 1 : 2;
    placeAt(xPct * img.naturalWidth, yPct * img.naturalHeight, visibility);
  }

  function handleContextMenu(e: React.MouseEvent<HTMLImageElement>) {
    e.preventDefault();
    const img = e.currentTarget;
    const rect = img.getBoundingClientRect();
    const xPct = (e.clientX - rect.left) / rect.width;
    const yPct = (e.clientY - rect.top) / rect.height;
    setCursor({ x: xPct, y: yPct });
    placeAt(xPct * img.naturalWidth, yPct * img.naturalHeight, 1);
  }

  function placeAtCursor(visibility: 1 | 2 = 2) {
    const img = imgRef.current;
    if (!img) return;
    placeAt(cursor.x * img.naturalWidth, cursor.y * img.naturalHeight, visibility);
  }

  function markOccluded() {
    placeAtCursor(1);
  }

  function clearCurrent() {
    pushHistory();
    const nextMap: KeypointsMap = { ...keypoints, [currentKp]: null };
    setKeypoints(nextMap);
    save.mutate(nextMap);
  }

  function clearAll() {
    confirm.ask({
      title: 'Clear all keypoints?',
      message: 'This removes every placed keypoint on the current frame. You can undo this with U.',
      confirmLabel: 'Clear all',
      tone: 'danger',
      onConfirm: () => {
        pushHistory();
        const m = emptyKeypoints(schemaKps);
        setKeypoints(m);
        save.mutate(m);
        setCurrentKp(0);
      },
    });
  }

  const prevPoseKps = (prevItemQ.data?.annotation?.value as
    | { keypoints?: KeypointValue[] }
    | undefined)?.keypoints;
  const hasPrevPose =
    !!prevPoseKps && prevPoseKps.length === N && prevPoseKps.some((v) => v[2] > 0);

  function copyPreviousPose() {
    if (!prevPoseKps) return;
    const apply = () => {
      pushHistory();
      const m = emptyKeypoints(schemaKps);
      prevPoseKps.forEach((v, i) => {
        m[i] = v[2] > 0 ? v : null;
      });
      setKeypoints(m);
      save.mutate(m);
      setCurrentKp(sequence[0]);
    };
    const hasPlaced = Object.values(keypoints).some((v) => v && v[2] > 0);
    if (!hasPlaced) {
      apply();
      return;
    }
    confirm.ask({
      title: 'Overwrite current keypoints?',
      message: 'The previous frame\u2019s pose will replace every point you\u2019ve placed here. Use Undo (U) if you change your mind.',
      confirmLabel: 'Copy pose',
      onConfirm: apply,
    });
  }

  function undo() {
    const prev = historyRef.current.pop();
    if (!prev) return;
    setKeypoints(prev);
    save.mutate(prev);
  }

  // Rapid Shift+Arrow presses coalesce into one undo step and one save:
  // history is pushed on the first nudge of a run and reset after 500ms
  // of idleness; save is debounced 400ms behind the last nudge.
  function nudgeAll(dx: number, dy: number) {
    const img = imgRef.current;
    if (!img) return;
    if (nudgeTimerRef.current === null) pushHistory();
    else clearTimeout(nudgeTimerRef.current);
    nudgeTimerRef.current = window.setTimeout(() => {
      nudgeTimerRef.current = null;
    }, 500);

    setKeypoints((prev) => {
      const clamped = clampGroupDelta(prev, dx, dy, img.naturalWidth, img.naturalHeight);
      if (clamped.dx === 0 && clamped.dy === 0) return prev;
      return translateAll(prev, clamped.dx, clamped.dy, schemaKps);
    });

    if (saveDebounceRef.current !== null) clearTimeout(saveDebounceRef.current);
    saveDebounceRef.current = window.setTimeout(() => {
      setKeypoints((latest) => {
        save.mutate(latest);
        return latest;
      });
      saveDebounceRef.current = null;
    }, 400);
  }

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA') return;

      // Suspend shortcuts while the confirm dialog is open (hook handles Esc).
      if (confirm.isOpen) return;

      // Navigate items
      if (e.key === ']' && next) return goTo(next.id);
      if (e.key === '[' && prev) return goTo(prev.id);

      // Switch keypoint (walks the current ordering)
      if (e.key === 'Tab') {
        e.preventDefault();
        stepCurrent(e.shiftKey ? -1 : 1);
        return;
      }
      if (e.key === 'n' || e.key === 'N') return stepCurrent(1);
      if (e.key === 'p' || e.key === 'P') return stepCurrent(-1);

      // Number keys 1-9 jump to keypoint 1..min(9, N); ignored past the schema count
      if (e.key >= '1' && e.key <= '9') {
        const target = Number(e.key) - 1;
        if (target < N) setCurrentKp(target);
        return;
      }

      // Arrow keys: Shift = nudge the whole group (2px natural), plain =
      // move the keyboard cursor overlay (for placing with Enter/Space).
      if (e.key === 'ArrowLeft' || e.key === 'ArrowRight' || e.key === 'ArrowUp' || e.key === 'ArrowDown') {
        e.preventDefault();
        if (e.shiftKey) {
          const delta = 2;
          const dx = e.key === 'ArrowLeft' ? -delta : e.key === 'ArrowRight' ? delta : 0;
          const dy = e.key === 'ArrowUp' ? -delta : e.key === 'ArrowDown' ? delta : 0;
          nudgeAll(dx, dy);
          return;
        }
        setKeyboardMode(true);
        const step = 0.01;
        if (e.key === 'ArrowLeft')  setCursor((c) => ({ ...c, x: Math.max(0, c.x - step) }));
        if (e.key === 'ArrowRight') setCursor((c) => ({ ...c, x: Math.min(1, c.x + step) }));
        if (e.key === 'ArrowUp')    setCursor((c) => ({ ...c, y: Math.max(0, c.y - step) }));
        if (e.key === 'ArrowDown')  setCursor((c) => ({ ...c, y: Math.min(1, c.y + step) }));
        return;
      }

      // Actions
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); placeAtCursor(); return; }
      if (e.key === 'o' || e.key === 'O') return markOccluded();
      if (e.key === 'u' || e.key === 'U') return undo();
      if (e.key === 'Backspace') return clearCurrent();
      if (e.key === 'c' || e.key === 'C') return clearAll();

      // Curation (admin/owner only, only meaningful for done/reviewed items).
      if (canReview && itemQ.data && (itemQ.data.status === 'done' || itemQ.data.status === 'reviewed')) {
        // A toggles approve/unapprove based on current status.
        if (e.key === 'a' || e.key === 'A') {
          handleApprove();
          return;
        }
        if (e.key === 'r' || e.key === 'R') {
          setShowSendBack(true);
          return;
        }
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentKp, keypoints, prev, next, cursor, confirm.isOpen, canReview, itemQ.data?.status]);

  if (itemQ.isLoading || projectQ.isLoading) return <p className="p-6">Loading…</p>;
  if (!itemQ.data || !projectQ.data) return <p className="p-6">Not found.</p>;
  // Belt-and-suspenders: if the cached data is for a different frame (can
  // happen in the tick between URL change and query refetch settling),
  // show Loading rather than painting the wrong image with the new header.
  if (itemQ.data.id !== currentItemId) return <p className="p-6">Loading…</p>;

  const item = itemQ.data;
  const project = projectQ.data;
  const payload = item.payload as {
    image_url?: string;
    source_video?: string;
    frame_index?: number;
  };
  const imageUrl = payload.image_url;
  const fullUrl = imageUrl ? `${FILES_BASE}${imageUrl}` : null;
  const doneCount = Object.values(keypoints).filter((v) => v && v[2] > 0).length;
  const isComplete = doneCount === N;

  return (
    <div className="max-w-7xl mx-auto p-4 space-y-4">
      <header className="flex items-center justify-between">
        <div>
          <Link to={`/projects/${projectId}`} className="text-sm text-blue-600 hover:underline">
            ← {project.name}
          </Link>
          <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-500">
            <span className="inline-flex items-center gap-1 font-mono bg-slate-100 text-slate-700 rounded px-1.5 py-0.5">
              #{item.id}
            </span>
            {payload.source_video && (
              <span className="truncate max-w-[260px]" title={payload.source_video}>
                {payload.source_video}
              </span>
            )}
            {typeof payload.frame_index === 'number' && (
              <span className="tabular-nums">frame {payload.frame_index}</span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-3 text-sm text-slate-500">
          {canReview && (
            <button
              type="button"
              onClick={() => setReviewMode((v) => !v)}
              className={
                'inline-flex items-center gap-1.5 px-2 py-1 rounded-full text-xs font-medium border transition-colors ' +
                (reviewMode
                  ? 'bg-amber-500 text-white border-amber-600 hover:bg-amber-600'
                  : 'bg-white text-slate-600 border-slate-300 hover:bg-slate-50')
              }
              title={
                reviewMode
                  ? 'Walking only items pending approval. Click to widen back to the assignee’s full queue.'
                  : 'Walk only items pending approval (status=done). Approve/Send back auto-advances.'
              }
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
                {reviewMode ? <polyline points="20 6 9 17 4 12" /> : <circle cx="12" cy="12" r="9" />}
              </svg>
              Review queue {reviewMode ? 'on' : 'off'}
            </button>
          )}
          <span className="flex items-center gap-2">
            {idx >= 0 ? `${idx + 1} / ${cohort.length}` : ''} ·
            <span
              className={
                'px-2 py-0.5 rounded-full font-semibold ' +
                (isComplete
                  ? 'bg-emerald-100 text-emerald-700'
                  : 'text-slate-500')
              }
            >
              {doneCount}/{N} keypoints {isComplete && '✓'}
            </span>
          </span>
        </div>
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
                key={item.id}
                src={fullUrl}
                onClick={handleImageClick}
                onContextMenu={handleContextMenu}
                onMouseMove={() => keyboardMode && setKeyboardMode(false)}
                onLoad={(e) => {
                  const i = e.currentTarget;
                  setImgDims({
                    naturalW: i.naturalWidth,
                    naturalH: i.naturalHeight,
                    offsetL: i.offsetLeft,
                    offsetT: i.offsetTop,
                    clientW: i.clientWidth,
                    clientH: i.clientHeight,
                  });
                }}
                className="max-w-full max-h-[80vh] cursor-crosshair select-none"
                draggable={false}
                alt="frame"
              />
              {/* Render skeleton + keypoints overlay */}
              {imgDims && (
                <svg
                  className="absolute"
                  style={{
                    left: imgDims.offsetL,
                    top: imgDims.offsetT,
                    width: imgDims.clientW,
                    height: imgDims.clientH,
                    pointerEvents: 'none',
                  }}
                  viewBox={`0 0 ${imgDims.naturalW} ${imgDims.naturalH}`}
                  preserveAspectRatio="none"
                >
                  {/* Skeleton lines (only between placed endpoints) */}
                  {bundle.skeleton.map(([a, b], i) => {
                    const va = keypoints[a];
                    const vb = keypoints[b];
                    if (!va || !vb || va[2] === 0 || vb[2] === 0) return null;
                    const dashed = va[2] === 1 || vb[2] === 1;
                    const sw = Math.max(2, imgDims.naturalW / 400);
                    return (
                      <line
                        key={i}
                        x1={va[0]} y1={va[1]} x2={vb[0]} y2={vb[1]}
                        stroke="#22d3ee"
                        strokeWidth={sw}
                        strokeOpacity={0.85}
                        strokeDasharray={dashed ? `${sw * 2} ${sw * 1.5}` : undefined}
                      />
                    );
                  })}
                  {schemaKps.map((kp) => {
                    const v = keypoints[kp.id];
                    if (!v || v[2] === 0) return null;
                    const isCurrent = kp.id === currentKp;
                    const isOccluded = v[2] === 1;
                    const r = Math.max(6, imgDims.naturalW / 120);
                    const sw = Math.max(2, imgDims.naturalW / 400);

                    function onDown(e: React.PointerEvent<SVGGElement>) {
                      if (e.button !== 0) return;
                      e.stopPropagation();
                      (e.target as Element).setPointerCapture(e.pointerId);
                      pushHistory();
                      if (e.shiftKey && imgRef.current) {
                        const img = imgRef.current;
                        const rect = img.getBoundingClientRect();
                        draggingRef.current = {
                          mode: 'group',
                          id: kp.id,
                          moved: false,
                          startClientX: e.clientX,
                          startClientY: e.clientY,
                          snapshot: keypoints,
                          imgW: img.naturalWidth,
                          imgH: img.naturalHeight,
                          rectW: rect.width,
                          rectH: rect.height,
                        };
                      } else {
                        draggingRef.current = { mode: 'single', id: kp.id, moved: false };
                        setCurrentKp(kp.id);
                      }
                    }
                    function onMove(e: React.PointerEvent<SVGGElement>) {
                      const drag = draggingRef.current;
                      const img = imgRef.current;
                      if (!drag || drag.id !== kp.id || !img) return;
                      if (drag.mode === 'group') {
                        const dx = ((e.clientX - drag.startClientX) / drag.rectW) * drag.imgW;
                        const dy = ((e.clientY - drag.startClientY) / drag.rectH) * drag.imgH;
                        const clamped = clampGroupDelta(drag.snapshot, dx, dy, drag.imgW, drag.imgH);
                        drag.moved = true;
                        setKeypoints(translateAll(drag.snapshot, clamped.dx, clamped.dy, schemaKps));
                        return;
                      }
                      if (!v) return;
                      const rect = img.getBoundingClientRect();
                      const xNat = ((e.clientX - rect.left) / rect.width) * img.naturalWidth;
                      const yNat = ((e.clientY - rect.top) / rect.height) * img.naturalHeight;
                      const clamped: KeypointValue = [
                        Math.round(Math.max(0, Math.min(img.naturalWidth, xNat))),
                        Math.round(Math.max(0, Math.min(img.naturalHeight, yNat))),
                        v[2] as 1 | 2,
                      ];
                      drag.moved = true;
                      setKeypoints((prev) => ({ ...prev, [kp.id]: clamped }));
                    }
                    function onUp(e: React.PointerEvent<SVGGElement>) {
                      const drag = draggingRef.current;
                      (e.target as Element).releasePointerCapture?.(e.pointerId);
                      draggingRef.current = null;
                      if (drag?.moved) {
                        // read latest state via functional setter, then persist
                        setKeypoints((latest) => {
                          save.mutate(latest);
                          return latest;
                        });
                      } else {
                        historyRef.current.pop(); // no move → drop the pre-push
                      }
                    }

                    return (
                      <g
                        key={kp.id}
                        style={{ pointerEvents: 'auto', cursor: 'grab' }}
                        onPointerDown={onDown}
                        onPointerMove={onMove}
                        onPointerUp={onUp}
                        onPointerCancel={onUp}
                      >
                        <circle
                          cx={v[0]} cy={v[1]}
                          r={r}
                          fill={isCurrent ? '#ef4444' : isOccluded ? '#f59e0b' : '#10b981'}
                          fillOpacity={isOccluded ? 0.55 : 1}
                          stroke="white"
                          strokeWidth={sw}
                          strokeDasharray={isOccluded ? `${sw * 2} ${sw * 1.5}` : undefined}
                        />
                        <text
                          x={v[0]} y={v[1] + Math.max(3, imgDims.naturalW / 300)}
                          textAnchor="middle"
                          fontSize={Math.max(10, imgDims.naturalW / 80)}
                          fontWeight="700"
                          fill="white"
                          style={{ pointerEvents: 'none', userSelect: 'none' }}
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
        <aside
          className={
            'bg-white rounded-lg shadow p-4 space-y-4 transition-colors '
            + (isComplete ? 'ring-2 ring-emerald-400' : '')
          }
        >
          {/* Needs-revision banner: assignee (and admin) sees what to fix. */}
          {item.review_note && (
            <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm">
              <p className="font-semibold text-amber-900">Needs revision</p>
              <p className="text-amber-800 mt-0.5">{item.review_note}</p>
            </div>
          )}

          {/* Review panel: admin or project owner can approve / send back. */}
          {canReview && (item.status === 'done' || item.status === 'reviewed') && (
            <div
              className={
                'rounded-lg border p-3 space-y-2 ' +
                (item.status === 'reviewed'
                  ? 'border-blue-300 bg-blue-50'
                  : 'border-emerald-300 bg-emerald-50')
              }
            >
              <div className="flex items-center justify-between gap-2">
                <span
                  className={
                    'text-sm font-semibold ' +
                    (item.status === 'reviewed' ? 'text-blue-900' : 'text-emerald-900')
                  }
                >
                  {item.status === 'reviewed' ? '✓ Reviewed' : 'Ready to review'}
                </span>
                <span className="text-[10px] text-slate-500 uppercase tracking-wide">
                  <kbd className="border rounded px-1 bg-white">A</kbd> approve ·{' '}
                  <kbd className="border rounded px-1 bg-white">R</kbd> send back
                </span>
              </div>
              {!showSendBack && (
                <div className="grid grid-cols-2 gap-2">
                  <button
                    type="button"
                    onClick={handleApprove}
                    disabled={reviewMut.isPending}
                    className={
                      'px-3 py-2 rounded text-sm font-medium disabled:opacity-50 disabled:cursor-not-allowed ' +
                      (item.status === 'reviewed'
                        ? 'bg-white border border-slate-300 text-slate-700 hover:bg-slate-50'
                        : 'bg-emerald-600 text-white hover:bg-emerald-700')
                    }
                    title={
                      item.status === 'reviewed'
                        ? 'Move this item back to "awaiting review" (not a rejection — use Send back to return it to the annotator)'
                        : 'Approve this item — marks it reviewed'
                    }
                  >
                    {item.status === 'reviewed' ? 'Undo approval' : 'Approve'}
                  </button>
                  <button
                    type="button"
                    onClick={() => setShowSendBack(true)}
                    disabled={reviewMut.isPending}
                    className="px-3 py-2 rounded border border-amber-500 text-amber-700 bg-white text-sm font-medium hover:bg-amber-50 disabled:opacity-50"
                  >
                    Send back
                  </button>
                </div>
              )}
              {showSendBack && (
                <div className="space-y-2 pt-2 border-t border-slate-200">
                  <textarea
                    value={reviewNoteInput}
                    onChange={(e) => setReviewNoteInput(e.target.value)}
                    placeholder="Optional note for the annotator (what to fix)…"
                    rows={2}
                    autoFocus
                    className="w-full text-sm border rounded px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-amber-300"
                  />
                  <div className="flex gap-2 justify-end">
                    <button
                      type="button"
                      onClick={() => {
                        setShowSendBack(false);
                        setReviewNoteInput('');
                      }}
                      className="text-xs px-3 py-1.5 border rounded text-slate-600 hover:bg-slate-50"
                    >
                      Cancel
                    </button>
                    <button
                      type="button"
                      onClick={() => handleSendBack(reviewNoteInput.trim() || undefined)}
                      disabled={reviewMut.isPending}
                      className="text-xs px-3 py-1.5 rounded bg-amber-600 text-white hover:bg-amber-700 disabled:opacity-50"
                    >
                      Send back
                    </button>
                  </div>
                </div>
              )}
            </div>
          )}

          {isComplete ? (
            <div className="flex items-center gap-3 bg-emerald-50 border border-emerald-200 rounded px-3 py-2">
              <span className="flex-none w-8 h-8 rounded-full bg-emerald-500 text-white flex items-center justify-center text-lg font-bold">
                ✓
              </span>
              <div className="flex-1">
                <p className="text-sm font-semibold text-emerald-800">
                  All {N} keypoints placed
                </p>
                <p className="text-xs text-emerald-700">
                  Drag any point to adjust, or press{' '}
                  <kbd className="border border-emerald-300 rounded px-1 bg-white">
                    ]
                  </kbd>{' '}
                  for the next frame.
                </p>
              </div>
            </div>
          ) : (
            <div className="flex items-baseline justify-between">
              <div>
                <p className="text-xs text-slate-500 uppercase tracking-wide">Next keypoint</p>
                <p className="text-lg font-semibold">
                  <span className="inline-block bg-red-500 text-white rounded px-2 mr-2 text-sm">
                    {currentKp + 1}
                  </span>
                  {schemaKps[currentKp]?.label ?? ''}
                </p>
              </div>
              <span className="text-sm text-slate-400">{doneCount}/{N}</span>
            </div>
          )}

          {bundle.hasContourModes && (
            <div className="space-y-1">
              <p className="text-xs text-slate-500 uppercase tracking-wide">Traversal order</p>
              <div className="grid grid-cols-3 text-xs rounded border overflow-hidden">
                {(['left', 'top', 'right'] as OrderMode[]).map((m) => (
                  <button
                    key={m}
                    type="button"
                    onClick={() => setOrderMode(m)}
                    className={
                      'px-2 py-1.5 font-medium transition-colors ' +
                      (orderMode === m
                        ? 'bg-red-500 text-white'
                        : 'bg-white text-slate-600 hover:bg-slate-50')
                    }
                  >
                    {ORDER_LABEL[m]}
                  </button>
                ))}
              </div>
              <p className="text-xs text-slate-500">
                Controls the "next keypoint" pointer. You can always click a
                point on the image or the avatar to override it.
              </p>
            </div>
          )}

          {schema === 'rodent' ? (
            <RodentAvatar
              currentId={currentKp}
              keypoints={keypoints}
              onSelect={setCurrentKp}
            />
          ) : (
            <BabyAvatar
              currentId={currentKp}
              keypoints={keypoints}
              onSelect={setCurrentKp}
            />
          )}

          <button
            type="button"
            onClick={copyPreviousPose}
            disabled={!hasPrevPose}
            title={
              hasPrevPose
                ? 'Copy the previous frame\u2019s keypoints into this frame'
                : 'No previous pose available'
            }
            className="w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg border border-slate-200 bg-white text-sm font-medium text-slate-700 transition hover:bg-slate-50 hover:border-slate-300 active:translate-y-px disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-white disabled:hover:border-slate-200"
          >
            <svg viewBox="0 0 16 16" className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
              <path d="M10 2H4a1 1 0 0 0-1 1v8" />
              <rect x="6" y="5" width="8" height="9" rx="1" />
            </svg>
            Copy previous pose
          </button>

          <div className="grid grid-cols-2 gap-2 text-sm">
            <button
              onClick={() => prev && goTo(prev.id)}
              disabled={!prev}
              title="Previous frame ([)"
              className="inline-flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg bg-slate-900 text-white font-medium shadow-sm hover:bg-slate-800 hover:shadow active:translate-y-px disabled:bg-slate-100 disabled:text-slate-400 disabled:shadow-none disabled:cursor-not-allowed transition"
            >
              <span aria-hidden className="text-base leading-none">←</span>
              Previous
            </button>
            <button
              onClick={() => next && goTo(next.id)}
              disabled={!next}
              title="Next frame (])"
              className="inline-flex items-center justify-center gap-2 px-3 py-2.5 rounded-lg bg-slate-900 text-white font-medium shadow-sm hover:bg-slate-800 hover:shadow active:translate-y-px disabled:bg-slate-100 disabled:text-slate-400 disabled:shadow-none disabled:cursor-not-allowed transition"
            >
              Next
              <span aria-hidden className="text-base leading-none">→</span>
            </button>
          </div>

          <div className="grid grid-cols-2 gap-2 text-sm">
            <button
              onClick={markOccluded}
              title="Mark occluded (right-click)"
              className="px-3 py-2 rounded-lg border border-slate-200 bg-white text-slate-700 font-medium hover:bg-slate-50 hover:border-slate-300 active:translate-y-px transition"
            >
              Occluded
            </button>
            <button
              onClick={undo}
              title="Undo (U)"
              className="px-3 py-2 rounded-lg border border-slate-200 bg-white text-slate-700 font-medium hover:bg-slate-50 hover:border-slate-300 active:translate-y-px transition"
            >
              Undo
            </button>
            <button
              onClick={clearCurrent}
              title="Clear current keypoint (Backspace)"
              className="px-3 py-2 rounded-lg border border-slate-200 bg-white text-slate-700 font-medium hover:bg-slate-50 hover:border-slate-300 active:translate-y-px transition"
            >
              Clear point
            </button>
            <button
              onClick={clearAll}
              title="Clear all keypoints (C)"
              className="px-3 py-2 rounded-lg border border-red-200 bg-white text-red-600 font-medium hover:bg-red-50 hover:border-red-300 active:translate-y-px transition"
            >
              Clear all
            </button>
          </div>

          <details className="text-xs text-slate-600 bg-slate-50 rounded border">
            <summary className="px-2 py-1.5 font-medium cursor-pointer hover:bg-slate-100">
              Keyboard shortcuts
            </summary>
            <div className="px-2 py-2 space-y-1">
              <p><kbd className="border rounded px-1">←↑↓→</kbd> move cursor on image</p>
              <p><kbd className="border rounded px-1">Shift</kbd> + drag a point = move all points · <kbd className="border rounded px-1">Shift+←↑↓→</kbd> nudge all by 2&nbsp;px</p>
              <p><kbd className="border rounded px-1">Enter</kbd> / <kbd className="border rounded px-1">Space</kbd> place keypoint at cursor</p>
              <p><kbd className="border rounded px-1">Tab</kbd> / <kbd className="border rounded px-1">N</kbd> next keypoint · <kbd className="border rounded px-1">Shift+Tab</kbd> / <kbd className="border rounded px-1">P</kbd> previous (walks the chosen order)</p>
              <p><kbd className="border rounded px-1">1</kbd>…<kbd className="border rounded px-1">9</kbd> jump to keypoint 1–9</p>
              <p><kbd className="border rounded px-1">[</kbd> / <kbd className="border rounded px-1">]</kbd> previous / next item</p>
              <p><b>Left click</b> / <kbd className="border rounded px-1">Enter</kbd> = visible · <b>Right click</b> / <kbd className="border rounded px-1">O</kbd> = occluded (position still required)</p>
              <p><kbd className="border rounded px-1">U</kbd> undo · <kbd className="border rounded px-1">⌫</kbd> clear current · <kbd className="border rounded px-1">C</kbd> clear all</p>
              <p className="text-slate-500 pt-1 border-t">Occluded points appear as dashed orange circles. Use when the keypoint is covered but you can estimate its position.</p>
            </div>
          </details>
        </aside>
      </div>
      {confirm.dialog}
    </div>
  );
}
