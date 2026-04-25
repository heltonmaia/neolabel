import { useEffect, useMemo, useRef, useState } from 'react';
import axios from 'axios';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { me } from '@/api/auth';
import {
  createLabel,
  deleteLabel,
  deleteProject,
  getProject,
} from '@/api/projects';
import {
  bulkUpload,
  clearAnnotation,
  deleteAnnotatedItems,
  deleteItem,
  listItems,
  type ItemStatus,
} from '@/api/items';
import { listUsers } from '@/api/users';
import { deleteVideo, importCocoPose, listVideos, reassignVideo, uploadVideo } from '@/api/videos';
import type { CocoImportResult, ResizeMode } from '@/api/videos';
import { downloadExport } from '@/lib/download';
import { FILES_BASE } from '@/lib/env';
import { useConfirm } from '@/components/ui/ConfirmDialog';

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`;
  return `${(n / 1024 ** 3).toFixed(2)} GB`;
}

function formatDuration(s: number): string {
  if (!isFinite(s) || s < 0) return '—';
  const m = Math.floor(s / 60);
  const r = Math.floor(s % 60);
  return `${m}:${r.toString().padStart(2, '0')}`;
}

export default function ProjectDetailPage() {
  const { id } = useParams();
  const projectId = Number(id);
  const qc = useQueryClient();
  const navigate = useNavigate();
  const confirmDialog = useConfirm();

  const meQ = useQuery({ queryKey: ['me'], queryFn: me });
  const isAdmin = meQ.data?.role === 'admin';

  const projectQ = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => getProject(projectId),
  });
  const itemsQ = useQuery({
    queryKey: ['items', projectId],
    queryFn: () => listItems(projectId, 500, 0),
  });

  const [labelName, setLabelName] = useState('');
  const [labelColor, setLabelColor] = useState('#3b82f6');
  const [labelShortcut, setLabelShortcut] = useState('');
  const [bulkText, setBulkText] = useState('');
  const [videoFile, setVideoFile] = useState<File | null>(null);
  const [videoFps, setVideoFps] = useState(5);
  const [videoAssignee, setVideoAssignee] = useState<number | ''>('');
  const [videoDuration, setVideoDuration] = useState<number | null>(null);
  const [videoRotation, setVideoRotation] = useState<0 | 90 | 180 | 270>(0);
  const [videoResizeMode, setVideoResizeMode] = useState<ResizeMode>('pad');
  const [isDragging, setIsDragging] = useState(false);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importAssignee, setImportAssignee] = useState<number | ''>('');
  const [importResult, setImportResult] = useState<CocoImportResult | null>(null);
  const videoPreviewUrl = useMemo(
    () => (videoFile ? URL.createObjectURL(videoFile) : null),
    [videoFile],
  );
  useEffect(() => {
    setVideoDuration(null);
    return () => {
      if (videoPreviewUrl) URL.revokeObjectURL(videoPreviewUrl);
    };
  }, [videoPreviewUrl]);
  const [exportOpen, setExportOpen] = useState(false);
  const [exportFormat, setExportFormat] = useState<
    'json' | 'jsonl' | 'csv' | 'yolo' | 'bundle'
  >('json');
  const [exportProgress, setExportProgress] = useState<
    | null
    | {
        format: 'json' | 'jsonl' | 'csv' | 'yolo' | 'bundle';
        loaded: number;
        total: number | null;
      }
  >(null);
  const exportAbortRef = useRef<AbortController | null>(null);

  async function handleExport() {
    const fmt = exportFormat;
    const controller = new AbortController();
    exportAbortRef.current = controller;
    setExportProgress({ format: fmt, loaded: 0, total: null });
    setExportOpen(false);
    try {
      await downloadExport(projectId, fmt, {
        signal: controller.signal,
        onProgress: (p) => setExportProgress({ format: fmt, loaded: p.loaded, total: p.total }),
      });
    } catch (err) {
      if (!axios.isCancel(err)) {
        console.error('export failed', err);
        alert('Export failed — check the backend logs.');
      }
    } finally {
      exportAbortRef.current = null;
      setExportProgress(null);
    }
  }

  // Videos table filters (admin)
  const [videoQuery, setVideoQuery] = useState('');
  const [videoAssigneeFilter, setVideoAssigneeFilter] = useState<number | ''>('');

  // Items filters / view
  const [statusFilter, setStatusFilter] = useState<'all' | ItemStatus>('all');
  const [sourceFilter, setSourceFilter] = useState<string>('');
  // '' = all, number = a specific user id, 'unassigned' = items with no assignee.
  // Admin-only (the user list endpoint is admin-only too).
  const [assigneeFilter, setAssigneeFilter] = useState<'' | number | 'unassigned'>('');
  const [itemView, setItemView] = useState<'list' | 'grid'>('list');
  const [itemsVisible, setItemsVisible] = useState(50);

  const addLabel = useMutation({
    mutationFn: () =>
      createLabel(projectId, {
        name: labelName,
        color: labelColor,
        shortcut: labelShortcut || null,
      }),
    onSuccess: () => {
      setLabelName('');
      setLabelShortcut('');
      qc.invalidateQueries({ queryKey: ['project', projectId] });
    },
  });

  const removeLabel = useMutation({
    mutationFn: (labelId: number) => deleteLabel(labelId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['project', projectId] }),
  });

  const upload = useMutation({
    mutationFn: () => {
      const lines = bulkText.split('\n').map((l) => l.trim()).filter(Boolean);
      const items = lines.map((text) => ({ payload: { text } }));
      return bulkUpload(projectId, items);
    },
    onSuccess: () => {
      setBulkText('');
      qc.invalidateQueries({ queryKey: ['items', projectId] });
    },
  });

  const usersQ = useQuery({
    queryKey: ['users'],
    queryFn: listUsers,
    enabled: isAdmin,
  });
  const videosQ = useQuery({
    queryKey: ['videos', projectId],
    queryFn: () => listVideos(projectId),
    enabled: isAdmin,
  });

  const videoUpload = useMutation({
    mutationFn: () =>
      uploadVideo(
        projectId,
        videoFile!,
        videoFps,
        videoAssignee === '' ? null : videoAssignee,
        videoRotation,
        videoResizeMode,
      ),
    onSuccess: () => {
      setVideoFile(null);
      setVideoRotation(0);
      qc.invalidateQueries({ queryKey: ['items', projectId] });
      qc.invalidateQueries({ queryKey: ['videos', projectId] });
    },
  });

  const cocoImport = useMutation({
    mutationFn: () =>
      importCocoPose(
        projectId,
        importFile!,
        importAssignee === '' ? null : importAssignee,
      ),
    onSuccess: (data) => {
      setImportResult(data);
      setImportFile(null);
      qc.invalidateQueries({ queryKey: ['items', projectId] });
      qc.invalidateQueries({ queryKey: ['videos', projectId] });
    },
  });

  const reassign = useMutation({
    mutationFn: (p: { source: string; assigneeId: number | null }) =>
      reassignVideo(projectId, p.source, p.assigneeId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['items', projectId] });
      qc.invalidateQueries({ queryKey: ['videos', projectId] });
    },
  });

  const removeVideo = useMutation({
    mutationFn: (source: string) => deleteVideo(projectId, source),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['items', projectId] });
      qc.invalidateQueries({ queryKey: ['videos', projectId] });
    },
  });

  const removeItem = useMutation({
    mutationFn: (itemId: number) => deleteItem(itemId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['items', projectId] }),
  });

  const clearItemAnnotation = useMutation({
    mutationFn: (itemId: number) => clearAnnotation(itemId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['items', projectId] }),
  });

  const removeAnnotated = useMutation({
    mutationFn: () => deleteAnnotatedItems(projectId),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['items', projectId] }),
  });

  const removeProject = useMutation({
    mutationFn: () => deleteProject(projectId),
    onSuccess: () => navigate('/projects'),
  });

  const items = itemsQ.data?.items ?? [];
  const isPose = projectQ.data?.type === 'pose_detection';

  const statusCounts = useMemo(() => {
    const c: Record<ItemStatus | 'all', number> = {
      all: items.length,
      pending: 0,
      in_progress: 0,
      done: 0,
      reviewed: 0,
    };
    for (const i of items) c[i.status]++;
    return c;
  }, [items]);

  // Source-video dropdown is constrained by the current assignee filter:
  // when an annotator is selected we only offer videos that contain at
  // least one of their items, so the dropdown can't lead to an empty list.
  const sourceVideos = useMemo(() => {
    if (!isPose) return [] as string[];
    const s = new Set<string>();
    for (const i of items) {
      if (assigneeFilter !== '') {
        if (assigneeFilter === 'unassigned') {
          if (i.assigned_to != null) continue;
        } else if (i.assigned_to !== assigneeFilter) {
          continue;
        }
      }
      const sv = (i.payload as { source_video?: string }).source_video;
      if (sv) s.add(sv);
    }
    return Array.from(s).sort();
  }, [items, isPose, assigneeFilter]);

  // If the selected source video disappears from the narrowed list (e.g. the
  // user switched annotators and the previously chosen video has none of the
  // new annotator's items), drop the stale selection so the list isn't empty.
  useEffect(() => {
    if (sourceFilter && !sourceVideos.includes(sourceFilter)) {
      setSourceFilter('');
    }
  }, [sourceVideos, sourceFilter]);

  // Distinct assignees actually present on this project's items, used to
  // populate the annotator filter and to hide it when there's only one group.
  const itemAnnotators = useMemo(() => {
    const ids = new Set<number>();
    let hasUnassigned = false;
    for (const i of items) {
      if (i.assigned_to == null) hasUnassigned = true;
      else ids.add(i.assigned_to);
    }
    return { ids: Array.from(ids).sort((a, b) => a - b), hasUnassigned };
  }, [items]);

  const filteredItems = useMemo(() => {
    return items.filter((i) => {
      if (statusFilter !== 'all' && i.status !== statusFilter) return false;
      if (sourceFilter) {
        const sv = (i.payload as { source_video?: string }).source_video;
        if (sv !== sourceFilter) return false;
      }
      if (assigneeFilter !== '') {
        if (assigneeFilter === 'unassigned') {
          if (i.assigned_to != null) return false;
        } else if (i.assigned_to !== assigneeFilter) {
          return false;
        }
      }
      return true;
    });
  }, [items, statusFilter, sourceFilter, assigneeFilter]);

  const userNameById = useMemo(() => {
    const m = new Map<number, string>();
    for (const u of usersQ.data ?? []) m.set(u.id, u.username);
    return m;
  }, [usersQ.data]);

  function annotatorLabel(uid: number | null | undefined): string | null {
    if (uid == null) return null;
    return userNameById.get(uid) ?? `user #${uid}`;
  }

  if (projectQ.isLoading) return <p className="p-6">Loading…</p>;
  if (!projectQ.data) return <p className="p-6">Project not found.</p>;
  const project = projectQ.data;

  const pendingItem = filteredItems.find((i) => i.status === 'pending')
    ?? items.find((i) => i.status === 'pending');

  return (
    <div className="max-w-5xl mx-auto p-6 space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <Link to="/projects" className="text-sm text-blue-600 hover:underline">
            ← Projects
          </Link>
          <h1 className="text-2xl font-semibold">{project.name}</h1>
          <p className="text-sm text-slate-500 flex items-center gap-2">
            <span>{project.type}</span>
            <span
              className={
                'inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium ring-1 ' +
                (project.keypoint_schema === 'rodent'
                  ? 'bg-amber-50 text-amber-800 ring-amber-200'
                  : 'bg-sky-50 text-sky-800 ring-sky-200')
              }
              title={
                project.keypoint_schema === 'rodent'
                  ? 'Rodent pose — 7 keypoints (immutable)'
                  : 'Infant pose — 17 COCO keypoints (immutable)'
              }
            >
              {project.keypoint_schema === 'rodent' ? 'rodent · 7 pts' : 'infant · 17 pts'}
            </span>
          </p>
        </div>
        <div className="flex gap-2 relative">
          <button
            onClick={() => setExportOpen((v) => !v)}
            className="text-sm border rounded px-3 py-1.5 hover:bg-slate-100"
          >
            Export ▾
          </button>
          {exportOpen && (
            <div
              className="absolute right-0 top-full mt-1 z-10 bg-white border rounded-lg shadow-lg p-3 w-64 space-y-2"
              onMouseLeave={() => setExportOpen(false)}
            >
              <p className="text-xs font-medium text-slate-500 uppercase tracking-wide">
                Format
              </p>
              {(
                [
                  { v: 'json', label: 'JSON', hint: 'single array' },
                  { v: 'jsonl', label: 'JSONL', hint: 'one item per line' },
                  { v: 'csv', label: 'CSV', hint: 'spreadsheet-friendly' },
                  ...(isPose
                    ? ([
                        { v: 'yolo', label: 'YOLO-pose (ZIP)', hint: 'Ultralytics, COCO 17 kp' },
                        {
                          v: 'bundle',
                          label: 'Full bundle (ZIP)',
                          hint: 'annotations.json + all source images',
                        },
                      ] as const)
                    : []),
                ] as const
              ).map((opt) => (
                <label
                  key={opt.v}
                  className={`flex items-start gap-2 p-2 rounded cursor-pointer text-sm ${
                    exportFormat === opt.v ? 'bg-blue-50 ring-1 ring-blue-300' : 'hover:bg-slate-50'
                  }`}
                >
                  <input
                    type="radio"
                    name="export-format"
                    value={opt.v}
                    checked={exportFormat === opt.v}
                    onChange={() => setExportFormat(opt.v)}
                    className="mt-0.5"
                  />
                  <span>
                    <span className="font-medium">{opt.label}</span>
                    <span className="block text-xs text-slate-500">{opt.hint}</span>
                  </span>
                </label>
              ))}
              <button
                onClick={handleExport}
                disabled={!!exportProgress}
                className="w-full bg-blue-600 text-white text-sm rounded px-3 py-1.5 hover:bg-blue-700 disabled:bg-slate-300"
              >
                {exportProgress ? 'Downloading…' : 'Download'}
              </button>
            </div>
          )}
          {isAdmin && (
            <button
              onClick={() =>
                confirmDialog.ask({
                  title: 'Delete project?',
                  message: 'This removes the project and every item, annotation, video and frame it contains. This cannot be undone.',
                  confirmLabel: 'Delete project',
                  tone: 'danger',
                  onConfirm: () => removeProject.mutate(),
                })
              }
              className="text-sm text-red-600 border border-red-200 rounded px-3 py-1.5 hover:bg-red-50"
              title="Admin only"
            >
              Delete
            </button>
          )}
        </div>
      </header>

      {/* Labels — hidden for pose (keypoint schema is fixed, no user labels needed) */}
      {!isPose && (
      <section className="bg-white p-4 rounded-lg shadow space-y-3">
        <h2 className="font-semibold">Labels</h2>
        <div className="flex flex-wrap gap-2">
          {project.labels.map((l) => (
            <span
              key={l.id}
              className="inline-flex items-center gap-2 px-2 py-1 rounded text-sm text-white"
              style={{ backgroundColor: l.color }}
            >
              {l.name}
              {l.shortcut && (
                <kbd className="bg-black/30 rounded px-1 text-xs">{l.shortcut}</kbd>
              )}
              <button
                onClick={() => removeLabel.mutate(l.id)}
                className="text-white/80 hover:text-white"
              >
                ×
              </button>
            </span>
          ))}
          {project.labels.length === 0 && (
            <span className="text-sm text-slate-500">No labels yet.</span>
          )}
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (labelName.trim()) addLabel.mutate();
          }}
          className="flex gap-2 items-center"
        >
          <input
            value={labelName}
            onChange={(e) => setLabelName(e.target.value)}
            placeholder="label name"
            className="border rounded px-2 py-1 flex-1"
          />
          <input
            type="color"
            value={labelColor}
            onChange={(e) => setLabelColor(e.target.value)}
            className="h-9 w-12 border rounded"
          />
          <input
            value={labelShortcut}
            onChange={(e) => setLabelShortcut(e.target.value.slice(0, 1))}
            placeholder="key"
            className="border rounded px-2 py-1 w-16 text-center"
          />
          <button className="bg-blue-600 text-white px-3 py-1.5 rounded hover:bg-blue-700">
            Add
          </button>
        </form>
      </section>
      )}

      {/* Upload */}
      {isPose ? (
        isAdmin ? (
        <section className="bg-white rounded-lg shadow">
          <details className="group">
            <summary className="flex items-center justify-between gap-3 cursor-pointer px-4 py-3 select-none hover:bg-slate-50 rounded-lg">
              <div className="min-w-0">
                <h2 className="font-semibold">Upload video</h2>
                <p className="text-xs text-slate-500">
                  Pick a video and an FPS. Assigning to an annotator is optional —
                  leave unassigned to keep frames in the admin pool.
                </p>
              </div>
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="shrink-0 text-slate-400 transition-transform group-open:rotate-180"
              >
                <polyline points="6 9 12 15 18 9" />
              </svg>
            </summary>
            <div className="px-4 pb-4 pt-3 border-t space-y-4">

          {/* Drop zone / preview */}
          {!videoFile ? (
            <label
              onDragOver={(e) => {
                e.preventDefault();
                if (!isDragging) setIsDragging(true);
              }}
              onDragLeave={() => setIsDragging(false)}
              onDrop={(e) => {
                e.preventDefault();
                setIsDragging(false);
                const f = e.dataTransfer.files?.[0];
                if (f && f.type.startsWith('video/')) setVideoFile(f);
              }}
              className={`flex flex-col items-center justify-center gap-2 px-6 py-10 border-2 border-dashed rounded-lg cursor-pointer transition-colors ${
                isDragging
                  ? 'border-blue-500 bg-blue-50'
                  : 'border-slate-200 bg-slate-50 hover:bg-slate-100 hover:border-slate-300'
              }`}
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="32"
                height="32"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="text-slate-400"
              >
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="17 8 12 3 7 8" />
                <line x1="12" y1="3" x2="12" y2="15" />
              </svg>
              <span className="text-sm font-medium text-slate-700">
                Click to choose or drag a video here
              </span>
              <span className="text-xs text-slate-500">
                MP4, MOV, WebM — any format FFmpeg can read
              </span>
              <input
                type="file"
                accept="video/*"
                onChange={(e) => setVideoFile(e.target.files?.[0] ?? null)}
                className="hidden"
              />
            </label>
          ) : (
            <div className="flex flex-col sm:flex-row gap-4 p-3 border rounded-lg bg-slate-50">
              <div className="w-full sm:w-56 h-32 bg-black rounded overflow-hidden flex items-center justify-center">
                <video
                  src={videoPreviewUrl ?? undefined}
                  controls
                  onLoadedMetadata={(e) =>
                    setVideoDuration((e.target as HTMLVideoElement).duration)
                  }
                  style={{
                    transform: `rotate(${videoRotation}deg)`,
                    maxWidth: videoRotation % 180 === 0 ? '100%' : '8rem',
                    maxHeight: videoRotation % 180 === 0 ? '100%' : '14rem',
                  }}
                  className="object-contain"
                />
              </div>
              <div className="flex-1 min-w-0 flex flex-col gap-1">
                <div className="font-medium truncate" title={videoFile.name}>
                  {videoFile.name}
                </div>
                <div className="text-xs text-slate-500 flex gap-3 flex-wrap">
                  <span>{formatBytes(videoFile.size)}</span>
                  {videoDuration !== null && <span>{formatDuration(videoDuration)}</span>}
                  {videoFile.type && <span className="font-mono">{videoFile.type}</span>}
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs text-slate-600 font-medium">Rotation:</span>
                  <div className="inline-flex rounded border overflow-hidden text-xs">
                    <button
                      type="button"
                      onClick={() =>
                        setVideoRotation((r) => (((r - 90 + 360) % 360) as 0 | 90 | 180 | 270))
                      }
                      className="px-2 py-1 hover:bg-white border-r"
                      title="Rotate left 90°"
                    >
                      ↺
                    </button>
                    <button
                      type="button"
                      onClick={() =>
                        setVideoRotation((r) => (((r + 90) % 360) as 0 | 90 | 180 | 270))
                      }
                      className="px-2 py-1 hover:bg-white border-r"
                      title="Rotate right 90°"
                    >
                      ↻
                    </button>
                    <button
                      type="button"
                      onClick={() => setVideoRotation(0)}
                      disabled={videoRotation === 0}
                      className="px-2 py-1 hover:bg-white disabled:opacity-40"
                      title="Reset"
                    >
                      Reset
                    </button>
                  </div>
                  <span className="text-xs text-slate-500 tabular-nums">{videoRotation}°</span>
                </div>
                <div className="mt-auto flex gap-2">
                  <label className="text-xs border rounded px-2 py-1 hover:bg-white cursor-pointer">
                    Change
                    <input
                      type="file"
                      accept="video/*"
                      onChange={(e) => {
                        setVideoFile(e.target.files?.[0] ?? null);
                        setVideoRotation(0);
                      }}
                      className="hidden"
                    />
                  </label>
                  <button
                    onClick={() => {
                      setVideoFile(null);
                      setVideoRotation(0);
                    }}
                    className="text-xs border rounded px-2 py-1 text-red-600 hover:bg-red-50"
                  >
                    Remove
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Settings: FPS + Assign to side by side */}
          <div className="grid sm:grid-cols-2 gap-4">
            <div className="space-y-1">
              <label className="text-xs font-medium text-slate-600 uppercase tracking-wide">
                FPS
              </label>
              <div className="flex items-center gap-2">
                <input
                  type="range"
                  min={0}
                  max={1}
                  step={0.01}
                  value={
                    (Math.log(videoFps) - Math.log(1 / 60)) /
                    (Math.log(30) - Math.log(1 / 60))
                  }
                  onChange={(e) => {
                    const t = Number(e.target.value);
                    const fps = Math.exp(
                      Math.log(1 / 60) + t * (Math.log(30) - Math.log(1 / 60)),
                    );
                    setVideoFps(Math.round(fps * 1000) / 1000);
                  }}
                  className="flex-1 accent-blue-600"
                />
                <input
                  type="number"
                  min={1 / 60}
                  max={60}
                  step={0.01}
                  value={videoFps}
                  onChange={(e) => setVideoFps(Number(e.target.value))}
                  className="border rounded px-2 py-1 w-20 text-sm text-right"
                />
              </div>
              <div className="text-xs text-slate-500">
                {videoFps >= 1
                  ? `${videoFps.toFixed(videoFps % 1 === 0 ? 0 : 2)} frames/s`
                  : 1 / videoFps >= 60
                    ? `1 frame / ${(1 / videoFps / 60).toFixed(1)} min`
                    : `1 frame / ${(1 / videoFps).toFixed(1)} s`}
              </div>
            </div>

            <div className="space-y-1">
              <label className="text-xs font-medium text-slate-600 uppercase tracking-wide">
                Assign to
              </label>
              <select
                value={videoAssignee}
                onChange={(e) =>
                  setVideoAssignee(e.target.value ? Number(e.target.value) : '')
                }
                className="border rounded px-2 py-1.5 text-sm w-full"
              >
                <option value="">— leave unassigned —</option>
                {(usersQ.data ?? []).map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.username} ({u.role})
                  </option>
                ))}
              </select>
              <div className="text-xs text-slate-500">
                Optional — assign later from the videos table if you prefer.
              </div>
            </div>
          </div>

          <div className="space-y-1">
            <label className="text-xs font-medium text-slate-600 uppercase tracking-wide">
              Resize to 640 × 640
            </label>
            <div className="grid sm:grid-cols-2 gap-2">
              <label
                className={`flex items-start gap-2 border rounded px-3 py-2 cursor-pointer text-sm ${
                  videoResizeMode === 'pad'
                    ? 'border-blue-500 bg-blue-50'
                    : 'border-slate-200 hover:bg-slate-50'
                }`}
              >
                <input
                  type="radio"
                  name="resize-mode"
                  value="pad"
                  checked={videoResizeMode === 'pad'}
                  onChange={() => setVideoResizeMode('pad')}
                  className="mt-0.5"
                />
                <span>
                  <span className="font-medium">Keep aspect ratio</span>{' '}
                  <span className="text-xs text-emerald-700">(recommended)</span>
                  <span className="block text-xs text-slate-500">
                    Letterbox with black bars — no distortion.
                  </span>
                </span>
              </label>
              <label
                className={`flex items-start gap-2 border rounded px-3 py-2 cursor-pointer text-sm ${
                  videoResizeMode === 'stretch'
                    ? 'border-blue-500 bg-blue-50'
                    : 'border-slate-200 hover:bg-slate-50'
                }`}
              >
                <input
                  type="radio"
                  name="resize-mode"
                  value="stretch"
                  checked={videoResizeMode === 'stretch'}
                  onChange={() => setVideoResizeMode('stretch')}
                  className="mt-0.5"
                />
                <span>
                  <span className="font-medium">Stretch</span>
                  <span className="block text-xs text-slate-500">
                    Fill the frame — distorts non-square sources.
                  </span>
                </span>
              </label>
            </div>
          </div>

          <details className="text-sm bg-slate-50 border rounded">
            <summary className="cursor-pointer px-3 py-2 font-medium text-slate-700 hover:bg-slate-100 select-none">
              What is FPS?{' '}
              <span className="text-xs text-slate-500 font-normal">(click to expand)</span>
            </summary>
            <div className="px-3 pb-3 space-y-1 text-slate-600">
              <p>
                <b>FPS (frames per second)</b> controls how many frames are extracted
                from the video and added as items to annotate.
              </p>
              <ul className="list-disc ml-5 text-slate-500">
                <li><b>FPS = 1</b> → 1 frame every second (60 frames from a 1-minute clip).</li>
                <li><b>FPS = 5</b> → 5 frames per second (smoother motion, more work).</li>
                <li><b>FPS = 0.2</b> → 1 frame every 5 seconds (<code>1 / 5 = 0.2</code>).</li>
                <li><b>FPS = 0.1</b> → 1 frame every 10 seconds.</li>
              </ul>
              <p className="text-slate-500">
                Rule of thumb: <code>FPS = 1 / interval_in_seconds</code>. Lower FPS =
                fewer frames = less work.
              </p>
            </div>
          </details>

          <div className="flex items-center justify-between gap-3 flex-wrap pt-2 border-t">
            <div className="text-xs text-slate-600">
              {videoFile && videoDuration !== null && videoFps > 0 ? (
                <>
                  Will extract ~
                  <b>{Math.max(1, Math.floor(videoDuration * videoFps))}</b> frames
                </>
              ) : (
                <span className="text-slate-400">
                  Pick a video to enable upload.
                </span>
              )}
            </div>
            <button
              onClick={() => videoUpload.mutate()}
              disabled={!videoFile || videoUpload.isPending}
              className="inline-flex items-center gap-2 bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 disabled:opacity-50 text-sm font-medium"
            >
              {videoUpload.isPending ? (
                <>
                  <svg
                    className="animate-spin"
                    width="16"
                    height="16"
                    viewBox="0 0 24 24"
                    fill="none"
                  >
                    <circle cx="12" cy="12" r="10" stroke="currentColor" strokeOpacity="0.25" strokeWidth="4" />
                    <path d="M12 2a10 10 0 0 1 10 10" stroke="currentColor" strokeWidth="4" strokeLinecap="round" />
                  </svg>
                  Extracting…
                </>
              ) : (
                <>
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    width="16"
                    height="16"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                    <polyline points="17 8 12 3 7 8" />
                    <line x1="12" y1="3" x2="12" y2="15" />
                  </svg>
                  Upload &amp; extract
                </>
              )}
            </button>
          </div>
          {videoUpload.isError && (
            <p className="text-sm text-red-600">
              {(videoUpload.error as any)?.response?.data?.detail ?? 'Upload failed'}
            </p>
          )}
          {videoUpload.data && (() => {
            const d = videoUpload.data;
            const dur = d.duration_s;
            const exp = d.expected_frames;
            const off =
              exp !== null && exp > 0
                ? Math.abs(d.frames - exp) / exp
                : 0;
            const mismatch = exp !== null && off > 0.1 && Math.abs(d.frames - exp) > 1;
            return (
              <div className="text-sm space-y-0.5">
                <p className={mismatch ? 'text-amber-700' : 'text-emerald-700'}>
                  Extracted <b>{d.frames}</b> frames from {d.video}
                  {dur ? ` (${dur.toFixed(1)}s)` : ''}
                  {exp !== null ? ` — expected ~${exp}` : ''}.
                </p>
                {mismatch && (
                  <p className="text-xs text-amber-600">
                    Actual count differs from expected — the source video may have
                    variable framerate or unusual timestamps.
                  </p>
                )}
              </div>
            );
          })()}
            </div>
          </details>
        </section>
        ) : null
      ) : null}

      {/* Import COCO-pose (admin, pose projects) */}
      {isPose && isAdmin && (
        <section className="bg-white rounded-lg shadow">
          <details className="group">
            <summary className="flex items-center justify-between gap-3 cursor-pointer px-4 py-3 select-none hover:bg-slate-50 rounded-lg">
              <div className="min-w-0">
                <h2 className="font-semibold">Import COCO keypoints dataset</h2>
                <p className="text-xs text-slate-500">
                  Drop a COCO JSON keypoints ZIP (e.g. Roboflow "COCO JSON" export).
                  The importer walks for <code>_annotations.coco.json</code> files
                  and creates one item per image; images referenced by a COCO
                  annotation are imported as already-annotated (17 keypoints).
                </p>
              </div>
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="shrink-0 text-slate-400 transition-transform group-open:rotate-180"
              >
                <polyline points="6 9 12 15 18 9" />
              </svg>
            </summary>
            <div className="px-4 pb-4 pt-3 border-t space-y-4">

          {!importFile ? (
            <label
              className="flex flex-col items-center justify-center gap-2 px-6 py-8 border-2 border-dashed border-slate-200 bg-slate-50 rounded-lg cursor-pointer hover:bg-slate-100 hover:border-slate-300 transition-colors"
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="28"
                height="28"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="1.6"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="text-slate-400"
              >
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
                <polyline points="17 8 12 3 7 8" />
                <line x1="12" y1="3" x2="12" y2="15" />
              </svg>
              <span className="text-sm font-medium text-slate-700">
                Click to choose a COCO keypoints ZIP
              </span>
              <span className="text-xs text-slate-500">
                Roboflow "COCO JSON" pose export works directly
              </span>
              <input
                type="file"
                accept=".zip,application/zip"
                onChange={(e) => {
                  setImportFile(e.target.files?.[0] ?? null);
                  setImportResult(null);
                }}
                className="hidden"
              />
            </label>
          ) : (
            <div className="flex items-center gap-3 p-3 border rounded-lg bg-slate-50">
              <div className="flex-1 min-w-0">
                <div className="font-medium truncate" title={importFile.name}>
                  {importFile.name}
                </div>
                <div className="text-xs text-slate-500">
                  {formatBytes(importFile.size)}
                </div>
              </div>
              <button
                onClick={() => setImportFile(null)}
                className="text-xs border rounded px-2 py-1 text-red-600 hover:bg-red-50"
              >
                Remove
              </button>
            </div>
          )}

          <div className="space-y-1">
            <label className="text-xs font-medium text-slate-600 uppercase tracking-wide">
              Assign to
            </label>
            <select
              value={importAssignee}
              onChange={(e) =>
                setImportAssignee(e.target.value ? Number(e.target.value) : '')
              }
              className="border rounded px-2 py-1.5 text-sm w-full sm:w-64"
            >
              <option value="">— leave unassigned —</option>
              {(usersQ.data ?? []).map((u) => (
                <option key={u.id} value={u.id}>
                  {u.username} ({u.role})
                </option>
              ))}
            </select>
            <div className="text-xs text-slate-500">
              Annotations without an assignee are attributed to you, so you can
              review them as admin.
            </div>
          </div>

          <div className="flex items-center justify-end pt-2 border-t">
            <button
              onClick={() => cocoImport.mutate()}
              disabled={!importFile || cocoImport.isPending}
              className="inline-flex items-center gap-2 bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 disabled:opacity-50 text-sm font-medium"
            >
              {cocoImport.isPending ? 'Importing…' : 'Import dataset'}
            </button>
          </div>

          {cocoImport.isError && (
            <p className="text-sm text-red-600">
              {(cocoImport.error as { response?: { data?: { detail?: string } } })
                ?.response?.data?.detail ?? 'Import failed'}
            </p>
          )}
          {importResult && (
            <div className="text-sm text-emerald-700 space-y-0.5">
              <p>
                Imported <b>{importResult.items_created}</b> frames
                {' · '}<b>{importResult.annotations_created}</b> with labels
                {importResult.skipped_images > 0 && (
                  <>{' · '}<b>{importResult.skipped_images}</b> missing images</>
                )}
                {importResult.skipped_labels > 0 && (
                  <>{' · '}<b>{importResult.skipped_labels}</b> skipped (bad labels)</>
                )}
              </p>
              {importResult.source_videos.length > 0 && (
                <p className="text-xs text-slate-500">
                  Grouped under: {importResult.source_videos.join(', ')}
                </p>
              )}
            </div>
          )}
            </div>
          </details>
        </section>
      )}

      {isPose ? null : (
        <section className="bg-white p-4 rounded-lg shadow space-y-3">
          <h2 className="font-semibold">Upload items</h2>
          <p className="text-sm text-slate-500">One text per line.</p>
          <textarea
            value={bulkText}
            onChange={(e) => setBulkText(e.target.value)}
            rows={5}
            className="w-full border rounded px-2 py-1 font-mono text-sm"
            placeholder={'first sentence\nsecond sentence\n...'}
          />
          <button
            onClick={() => upload.mutate()}
            disabled={!bulkText.trim() || upload.isPending}
            className="bg-blue-600 text-white px-3 py-1.5 rounded hover:bg-blue-700 disabled:opacity-50"
          >
            {upload.isPending ? 'Uploading…' : 'Upload'}
          </button>
        </section>
      )}

      {/* Videos (admin oversight of per-video assignments) */}
      {isAdmin && isPose && (videosQ.data?.length ?? 0) > 0 && (() => {
        const all = videosQ.data!;
        const q = videoQuery.trim().toLowerCase();
        const filtered = all.filter((v) => {
          if (q && !v.source_video.toLowerCase().includes(q)) return false;
          if (videoAssigneeFilter !== '' && v.assigned_to !== videoAssigneeFilter) return false;
          return true;
        });
        const totals = filtered.reduce(
          (acc, v) => ({
            frames: acc.frames + v.frames,
            done: acc.done + v.done,
          }),
          { frames: 0, done: 0 },
        );
        return (
        <section className="bg-white rounded-lg shadow">
          <details open className="group">
            <summary className="flex items-center justify-between gap-3 cursor-pointer px-4 py-3 select-none hover:bg-slate-50 rounded-lg">
              <div className="min-w-0">
                <h2 className="font-semibold">
                  Videos{' '}
                  <span className="text-sm text-slate-500 font-normal">
                    ({filtered.length}
                    {filtered.length !== all.length && ` of ${all.length}`})
                  </span>
                </h2>
                <p className="text-xs text-slate-500">
                  Reassigning moves every frame of a video to the selected user.
                </p>
              </div>
              <svg
                xmlns="http://www.w3.org/2000/svg"
                width="18"
                height="18"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
                className="shrink-0 text-slate-400 transition-transform group-open:rotate-180"
              >
                <polyline points="6 9 12 15 18 9" />
              </svg>
            </summary>
            <div className="px-4 pb-4 pt-3 border-t space-y-3">
              <div className="flex items-center gap-2 flex-wrap justify-end">
                <input
                  type="search"
                  value={videoQuery}
                  onChange={(e) => setVideoQuery(e.target.value)}
                  placeholder="Search video…"
                  className="border rounded px-2 py-1 text-sm"
                />
                <select
                  value={videoAssigneeFilter}
                  onChange={(e) =>
                    setVideoAssigneeFilter(e.target.value ? Number(e.target.value) : '')
                  }
                  className="border rounded px-2 py-1 text-sm"
                >
                  <option value="">All annotators</option>
                  {(usersQ.data ?? []).map((u) => (
                    <option key={u.id} value={u.id}>
                      {u.username}
                    </option>
                  ))}
                </select>
              </div>
          {filtered.length === 0 ? (
            <p className="text-sm text-slate-500 py-2">No videos match.</p>
          ) : (
          <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-slate-500 text-xs uppercase">
              <tr>
                <th className="py-1">Video</th>
                <th className="py-1 w-24">Frames</th>
                <th className="py-1 w-56">Progress</th>
                <th className="py-1">Assigned to</th>
                <th className="py-1 w-8"></th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((v) => {
                const pct = v.frames > 0 ? (v.done / v.frames) * 100 : 0;
                return (
                <tr key={v.source_video} className="border-t">
                  <td className="py-2 font-mono truncate max-w-xs">{v.source_video}</td>
                  <td className="py-2">{v.frames}</td>
                  <td className="py-2">
                    <div className="flex items-center gap-2">
                      <div className="flex-1 h-2 bg-slate-100 rounded overflow-hidden">
                        <div
                          className="h-full bg-emerald-500"
                          style={{ width: `${pct}%` }}
                        />
                      </div>
                      <span className="text-xs text-slate-500 tabular-nums whitespace-nowrap">
                        {v.done}/{v.frames}
                      </span>
                    </div>
                  </td>
                  <td className="py-2">
                    <select
                      value={v.assigned_to ?? ''}
                      onChange={(e) => {
                        const raw = e.target.value;
                        const assigneeId = raw === '' ? null : Number(raw);
                        reassign.mutate({ source: v.source_video, assigneeId });
                      }}
                      className="border rounded px-2 py-1 text-sm"
                    >
                      <option value="">— unassigned —</option>
                      {(usersQ.data ?? []).map((u) => (
                        <option key={u.id} value={u.id}>
                          {u.username}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="py-2">
                    <button
                      onClick={() =>
                        confirmDialog.ask({
                          title: 'Delete video?',
                          message: `"${v.source_video}" and all ${v.frames} extracted frames (plus their annotations) will be removed. This cannot be undone.`,
                          confirmLabel: 'Delete video',
                          tone: 'danger',
                          onConfirm: () => removeVideo.mutate(v.source_video),
                        })
                      }
                      disabled={removeVideo.isPending}
                      className="text-slate-400 hover:text-red-600 p-1 disabled:opacity-40"
                      title="Delete video and all its frames"
                      aria-label="Delete video"
                    >
                      <svg
                        xmlns="http://www.w3.org/2000/svg"
                        width="16"
                        height="16"
                        viewBox="0 0 24 24"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="2"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      >
                        <path d="M3 6h18" />
                        <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                        <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
                        <path d="M10 11v6" />
                        <path d="M14 11v6" />
                      </svg>
                    </button>
                  </td>
                </tr>
                );
              })}
            </tbody>
            <tfoot>
              <tr className="border-t text-xs text-slate-500">
                <td className="py-2 font-medium">
                  {filtered.length} video{filtered.length === 1 ? '' : 's'}
                </td>
                <td className="py-2 tabular-nums">{totals.frames}</td>
                <td className="py-2 tabular-nums">
                  {totals.done}/{totals.frames}
                  {totals.frames > 0 &&
                    ` · ${Math.round((totals.done / totals.frames) * 100)}%`}
                </td>
                <td colSpan={2} />
              </tr>
            </tfoot>
          </table>
          </div>
          )}
            </div>
          </details>
        </section>
        );
      })()}

      {/* Items */}
      <section className="bg-white p-4 rounded-lg shadow space-y-3">
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <h2 className="font-semibold">
            Items{' '}
            <span className="text-sm text-slate-500 font-normal">
              ({filteredItems.length}
              {filteredItems.length !== items.length && ` of ${items.length}`})
            </span>
          </h2>
          <div className="flex items-center gap-2 flex-wrap">
            {isAdmin && items.some((i) => i.status === 'done' || i.status === 'reviewed') && (
              <button
                onClick={() =>
                  confirmDialog.ask({
                    title: 'Delete all annotated items?',
                    message: 'Every item with an annotation (status done or reviewed) will be deleted along with its frame. This cannot be undone.',
                    confirmLabel: 'Delete annotated',
                    tone: 'danger',
                    onConfirm: () => removeAnnotated.mutate(),
                  })
                }
                disabled={removeAnnotated.isPending}
                className="text-sm text-red-600 border border-red-200 rounded px-3 py-1.5 hover:bg-red-50 disabled:opacity-50"
                title="Remove every item that has an annotation"
              >
                {removeAnnotated.isPending ? 'Deleting…' : 'Delete annotated'}
              </button>
            )}
            {pendingItem && (
              <Link
                to={`/projects/${projectId}/annotate/${pendingItem.id}`}
                className="bg-emerald-600 text-white px-3 py-1.5 rounded text-sm hover:bg-emerald-700"
              >
                Start annotating →
              </Link>
            )}
          </div>
        </div>

        {items.length > 0 && (
        <div className="flex items-center gap-2 flex-wrap border-b pb-3">
          {(
            [
              ['all', 'All'],
              ['pending', 'Pending'],
              ['in_progress', 'In progress'],
              ['done', 'Done'],
              ['reviewed', 'Reviewed'],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              onClick={() => {
                setStatusFilter(key);
                setItemsVisible(50);
              }}
              className={`text-xs px-2.5 py-1 rounded-full border ${
                statusFilter === key
                  ? 'bg-blue-600 text-white border-blue-600'
                  : 'bg-white text-slate-600 border-slate-200 hover:bg-slate-50'
              }`}
            >
              {label}{' '}
              <span className={statusFilter === key ? 'opacity-80' : 'text-slate-400'}>
                {statusCounts[key]}
              </span>
            </button>
          ))}
          <div className="flex items-center gap-2 flex-wrap ml-auto">
            {isAdmin &&
              itemAnnotators.ids.length + (itemAnnotators.hasUnassigned ? 1 : 0) > 1 && (
                <select
                  value={assigneeFilter === '' ? '' : String(assigneeFilter)}
                  onChange={(e) => {
                    const v = e.target.value;
                    setAssigneeFilter(
                      v === ''
                        ? ''
                        : v === 'unassigned'
                          ? 'unassigned'
                          : Number(v),
                    );
                    setItemsVisible(50);
                  }}
                  className="border rounded px-2 py-1 text-xs"
                  title="Filter by annotator"
                >
                  <option value="">All annotators</option>
                  {itemAnnotators.ids.map((uid) => (
                    <option key={uid} value={uid}>
                      {userNameById.get(uid) ?? `user #${uid}`}
                    </option>
                  ))}
                  {itemAnnotators.hasUnassigned && (
                    <option value="unassigned">— unassigned —</option>
                  )}
                </select>
              )}
            {isPose && sourceVideos.length > 0 && (
              <select
                value={sourceFilter}
                onChange={(e) => {
                  setSourceFilter(e.target.value);
                  setItemsVisible(50);
                }}
                className="border rounded px-2 py-1 text-xs"
              >
                <option value="">All videos</option>
                {sourceVideos.map((sv) => (
                  <option key={sv} value={sv}>
                    {sv}
                  </option>
                ))}
              </select>
            )}
            <div className="inline-flex border rounded overflow-hidden text-xs">
              <button
                onClick={() => setItemView('list')}
                className={`px-2 py-1 ${
                  itemView === 'list' ? 'bg-slate-800 text-white' : 'bg-white text-slate-600'
                }`}
                title="List view"
              >
                List
              </button>
              <button
                onClick={() => setItemView('grid')}
                className={`px-2 py-1 border-l ${
                  itemView === 'grid' ? 'bg-slate-800 text-white' : 'bg-white text-slate-600'
                }`}
                title="Grid view"
              >
                Grid
              </button>
            </div>
          </div>
        </div>
        )}

        {items.length === 0 ? (
          <p className="text-sm text-slate-500">No items yet.</p>
        ) : filteredItems.length === 0 ? (
          <p className="text-sm text-slate-500 py-2">No items match the filter.</p>
        ) : itemView === 'grid' ? (
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-3">
            {filteredItems.slice(0, itemsVisible).map((i) => {
              const imgUrl = (i.payload as { image_url?: string }).image_url;
              const sv = (i.payload as { source_video?: string }).source_video;
              const fi = (i.payload as { frame_index?: number }).frame_index;
              const w = (i.payload as { width?: number }).width;
              const h = (i.payload as { height?: number }).height;
              const size = typeof w === 'number' && typeof h === 'number' ? `${w}×${h}` : null;
              const label = sv ? `${sv} · ${fi}` : `#${i.id}`;
              return (
                <Link
                  key={i.id}
                  to={`/projects/${projectId}/annotate/${i.id}`}
                  className="group block relative border rounded overflow-hidden hover:border-blue-400"
                >
                  {imgUrl ? (
                    <img
                      src={`${FILES_BASE}${imgUrl}`}
                      className="w-full aspect-square object-cover bg-slate-100"
                      alt=""
                      loading="lazy"
                    />
                  ) : (
                    <div className="w-full aspect-square bg-slate-100 flex items-center justify-center text-xs text-slate-400">
                      no preview
                    </div>
                  )}
                  <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/70 to-transparent text-white text-xs px-2 py-1 space-y-0.5">
                    <div className="truncate">{label}</div>
                    {size && (
                      <div className="text-[10px] text-white/70 tabular-nums">{size}</div>
                    )}
                    {(() => {
                      const name = annotatorLabel(i.assigned_to);
                      return (
                        <div
                          className={
                            'truncate text-[10px] ' +
                            (name ? 'text-white/80' : 'text-white/50 italic')
                          }
                        >
                          {name ?? 'unassigned'}
                        </div>
                      );
                    })()}
                  </div>
                  {(() => {
                    const needsRevision =
                      i.status === 'in_progress' && !!i.review_note;
                    return (
                      <span
                        className={`absolute top-1 right-1 text-[10px] px-1.5 py-0.5 rounded ${
                          needsRevision
                            ? 'bg-amber-600 text-white font-semibold ring-1 ring-amber-300'
                            : i.status === 'done'
                              ? 'bg-emerald-500 text-white'
                              : i.status === 'in_progress'
                                ? 'bg-amber-500 text-white'
                                : i.status === 'reviewed'
                                  ? 'bg-blue-500 text-white'
                                  : 'bg-white/90 text-slate-600'
                        }`}
                        title={needsRevision ? `Needs revision: ${i.review_note}` : undefined}
                      >
                        {needsRevision ? 'needs revision' : i.status.replace('_', ' ')}
                      </span>
                    );
                  })()}
                </Link>
              );
            })}
          </div>
        ) : (
          <ul className="divide-y">
            {filteredItems.slice(0, itemsVisible).map((i) => (
              <li key={i.id} className="py-2 flex items-center justify-between gap-4">
                <Link
                  to={`/projects/${projectId}/annotate/${i.id}`}
                  className="flex items-center gap-3 flex-1 min-w-0 hover:underline"
                >
                  {(i.payload as { image_url?: string }).image_url && (
                    <img
                      src={`${FILES_BASE}${(i.payload as { image_url: string }).image_url}`}
                      className="w-12 h-12 object-cover rounded border"
                      alt=""
                      loading="lazy"
                    />
                  )}
                  <span className="truncate">
                    {(i.payload as { text?: string; frame_index?: number; source_video?: string }).text ??
                      ((i.payload as any).source_video
                        ? `${(i.payload as any).source_video} · frame ${(i.payload as any).frame_index}`
                        : JSON.stringify(i.payload))}
                  </span>
                  {(() => {
                    const w = (i.payload as { width?: number }).width;
                    const h = (i.payload as { height?: number }).height;
                    if (typeof w !== 'number' || typeof h !== 'number') return null;
                    return (
                      <span className="text-xs text-slate-500 tabular-nums whitespace-nowrap">
                        {w}×{h}
                      </span>
                    );
                  })()}
                </Link>
                {(() => {
                  const name = annotatorLabel(i.assigned_to);
                  return (
                    <span
                      className={
                        'text-xs px-2 py-0.5 rounded border whitespace-nowrap ' +
                        (name
                          ? 'bg-slate-50 text-slate-700 border-slate-200'
                          : 'bg-transparent text-slate-400 border-dashed border-slate-300 italic')
                      }
                      title={name ? `Assigned to ${name}` : 'No annotator assigned'}
                    >
                      {name ?? 'unassigned'}
                    </span>
                  );
                })()}
                {(() => {
                  const needsRevision =
                    i.status === 'in_progress' && !!i.review_note;
                  return (
                    <span
                      className={`text-xs px-2 py-0.5 rounded capitalize ${
                        needsRevision
                          ? 'bg-amber-100 text-amber-800 font-semibold ring-1 ring-amber-300'
                          : i.status === 'done'
                            ? 'bg-emerald-100 text-emerald-700'
                            : i.status === 'in_progress'
                              ? 'bg-amber-100 text-amber-700'
                              : i.status === 'reviewed'
                                ? 'bg-blue-100 text-blue-700'
                                : 'bg-slate-100 text-slate-600'
                      }`}
                      title={needsRevision ? `Needs revision: ${i.review_note}` : undefined}
                    >
                      {needsRevision ? 'needs revision' : i.status.replace('_', ' ')}
                    </span>
                  );
                })()}
                {(i.status === 'done' ||
                  i.status === 'in_progress' ||
                  i.status === 'reviewed') && (
                  <button
                    onClick={(e) => {
                      e.preventDefault();
                      confirmDialog.ask({
                        title: 'Clear annotation?',
                        message: `The annotation on item ${i.id} will be removed, but the item itself is kept so it can be re-annotated.`,
                        confirmLabel: 'Clear annotation',
                        tone: 'danger',
                        onConfirm: () => clearItemAnnotation.mutate(i.id),
                      });
                    }}
                    className="text-slate-400 hover:text-amber-600 p-1"
                    title="Clear annotation (keep item)"
                    aria-label="Clear annotation"
                  >
                    <svg
                      xmlns="http://www.w3.org/2000/svg"
                      width="16"
                      height="16"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="2"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    >
                      <path d="M20 20H9L3 14a2 2 0 0 1 0-2.8l8.5-8.5a2 2 0 0 1 2.8 0l6 6a2 2 0 0 1 0 2.8L13 20" />
                      <path d="M18 13 9 22" />
                    </svg>
                  </button>
                )}
                {isAdmin && (
                <button
                  onClick={(e) => {
                    e.preventDefault();
                    confirmDialog.ask({
                      title: 'Delete item?',
                      message: `Item ${i.id} and any annotation on it will be permanently removed. This cannot be undone.`,
                      confirmLabel: 'Delete item',
                      tone: 'danger',
                      onConfirm: () => removeItem.mutate(i.id),
                    });
                  }}
                  className="text-slate-400 hover:text-red-600 p-1"
                  title="Delete this item"
                  aria-label="Delete item"
                >
                  <svg
                    xmlns="http://www.w3.org/2000/svg"
                    width="16"
                    height="16"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="M3 6h18" />
                    <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6" />
                    <path d="M10 11v6" />
                    <path d="M14 11v6" />
                  </svg>
                </button>
                )}
              </li>
            ))}
          </ul>
        )}

        {filteredItems.length > itemsVisible && (
          <div className="flex justify-center pt-2">
            <button
              onClick={() => setItemsVisible((v) => v + 50)}
              className="text-sm border rounded px-4 py-1.5 hover:bg-slate-100"
            >
              Load more ({filteredItems.length - itemsVisible} remaining)
            </button>
          </div>
        )}
      </section>

      {exportProgress && (
        <div
          role="status"
          aria-live="polite"
          className="fixed bottom-4 right-4 z-50 bg-white border rounded-lg shadow-lg p-4 w-80 space-y-2"
        >
          <div className="flex items-center justify-between">
            <span className="text-sm font-medium">
              Exporting {exportProgress.format.toUpperCase()}…
            </span>
            <button
              onClick={() => exportAbortRef.current?.abort()}
              className="text-xs text-slate-500 hover:text-red-600"
              title="Cancel"
            >
              Cancel
            </button>
          </div>
          <div className="h-2 rounded bg-slate-200 overflow-hidden">
            {exportProgress.total ? (
              <div
                className="h-full bg-blue-600 transition-[width] duration-150"
                style={{
                  width: `${Math.min(100, (exportProgress.loaded / exportProgress.total) * 100)}%`,
                }}
              />
            ) : (
              // Indeterminate: server sent no Content-Length (chunked text stream).
              <div className="h-full w-1/3 bg-blue-600 animate-pulse" />
            )}
          </div>
          <div className="text-xs text-slate-500">
            {exportProgress.total
              ? `${formatBytes(exportProgress.loaded)} of ${formatBytes(exportProgress.total)} · ${Math.round(
                  (exportProgress.loaded / exportProgress.total) * 100,
                )}%`
              : `${formatBytes(exportProgress.loaded)} transferred`}
          </div>
        </div>
      )}
      {confirmDialog.dialog}
    </div>
  );
}
