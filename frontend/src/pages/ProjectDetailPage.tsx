import { useState } from 'react';
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
} from '@/api/items';
import { listUsers } from '@/api/users';
import { deleteVideo, listVideos, reassignVideo, uploadVideo } from '@/api/videos';
import { downloadExport } from '@/lib/download';
import { FILES_BASE } from '@/lib/env';

export default function ProjectDetailPage() {
  const { id } = useParams();
  const projectId = Number(id);
  const qc = useQueryClient();
  const navigate = useNavigate();

  const meQ = useQuery({ queryKey: ['me'], queryFn: me });
  const isAdmin = meQ.data?.role === 'admin';

  const projectQ = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => getProject(projectId),
  });
  const itemsQ = useQuery({
    queryKey: ['items', projectId],
    queryFn: () => listItems(projectId),
  });

  const [labelName, setLabelName] = useState('');
  const [labelColor, setLabelColor] = useState('#3b82f6');
  const [labelShortcut, setLabelShortcut] = useState('');
  const [bulkText, setBulkText] = useState('');
  const [videoFile, setVideoFile] = useState<File | null>(null);
  const [videoFps, setVideoFps] = useState(5);
  const [videoAssignee, setVideoAssignee] = useState<number | ''>('');
  const [exportOpen, setExportOpen] = useState(false);
  const [exportFormat, setExportFormat] = useState<'json' | 'jsonl' | 'csv' | 'yolo'>('json');

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
      uploadVideo(projectId, videoFile!, videoFps, videoAssignee as number),
    onSuccess: () => {
      setVideoFile(null);
      qc.invalidateQueries({ queryKey: ['items', projectId] });
      qc.invalidateQueries({ queryKey: ['videos', projectId] });
    },
  });

  const reassign = useMutation({
    mutationFn: (p: { source: string; assigneeId: number }) =>
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

  if (projectQ.isLoading) return <p className="p-6">Loading…</p>;
  if (!projectQ.data) return <p className="p-6">Project not found.</p>;
  const project = projectQ.data;
  const items = itemsQ.data?.items ?? [];
  const pendingItem = items.find((i) => i.status === 'pending');
  const isPose = project.type === 'pose_detection';

  return (
    <div className="max-w-5xl mx-auto p-6 space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <Link to="/projects" className="text-sm text-blue-600 hover:underline">
            ← Projects
          </Link>
          <h1 className="text-2xl font-semibold">{project.name}</h1>
          <p className="text-sm text-slate-500">{project.type}</p>
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
                    ? [{ v: 'yolo', label: 'YOLO-pose (ZIP)', hint: 'Ultralytics, COCO 17 kp' }]
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
                onClick={() => {
                  downloadExport(projectId, exportFormat);
                  setExportOpen(false);
                }}
                className="w-full bg-blue-600 text-white text-sm rounded px-3 py-1.5 hover:bg-blue-700"
              >
                Download
              </button>
            </div>
          )}
          {isAdmin && (
            <button
              onClick={() => confirm('Delete project?') && removeProject.mutate()}
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
        <section className="bg-white p-4 rounded-lg shadow space-y-3">
          <h2 className="font-semibold">Upload video</h2>
          <p className="text-xs text-slate-500">
            Only admins can upload videos. Choose which annotator will receive the
            extracted frames — they become that user's assignment.
          </p>
          <details className="text-sm bg-slate-50 border rounded">
            <summary className="cursor-pointer px-3 py-2 font-medium text-slate-700 hover:bg-slate-100 select-none">
              What is FPS? <span className="text-xs text-slate-500 font-normal">(click to expand)</span>
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
          <input
            type="file"
            accept="video/*"
            onChange={(e) => setVideoFile(e.target.files?.[0] ?? null)}
            className="text-sm block"
          />

          <div className="flex items-center gap-3 text-sm">
            <label className="text-slate-600">FPS</label>
            {/* Log slider: 0 -> 1/60 fps, 1 -> 30 fps */}
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
              className="w-40 accent-blue-600"
            />
            <input
              type="number"
              min={1 / 60}
              max={60}
              step={0.01}
              value={videoFps}
              onChange={(e) => setVideoFps(Number(e.target.value))}
              className="border rounded px-2 py-1 w-24 text-sm"
            />
            <span className="text-xs text-slate-500">
              {videoFps >= 1
                ? `${videoFps.toFixed(videoFps % 1 === 0 ? 0 : 2)} frames/s`
                : 1 / videoFps >= 60
                  ? `1 frame / ${(1 / videoFps / 60).toFixed(1)} min`
                  : `1 frame / ${(1 / videoFps).toFixed(1)} s`}
            </span>
          </div>

          <div className="flex items-center gap-3 text-sm">
            <label className="text-slate-600">Assign to</label>
            <select
              value={videoAssignee}
              onChange={(e) =>
                setVideoAssignee(e.target.value ? Number(e.target.value) : '')
              }
              className="border rounded px-2 py-1 text-sm"
            >
              <option value="">— pick a user —</option>
              {(usersQ.data ?? []).map((u) => (
                <option key={u.id} value={u.id}>
                  {u.username} ({u.role})
                </option>
              ))}
            </select>
          </div>

          <button
            onClick={() => videoUpload.mutate()}
            disabled={!videoFile || !videoAssignee || videoUpload.isPending}
            className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700 disabled:opacity-50"
          >
            {videoUpload.isPending ? 'Extracting…' : 'Upload & extract'}
          </button>
          {videoUpload.isError && (
            <p className="text-sm text-red-600">
              {(videoUpload.error as any)?.response?.data?.detail ?? 'Upload failed'}
            </p>
          )}
          {videoUpload.data && (
            <p className="text-sm text-emerald-700">
              Extracted {videoUpload.data.frames} frames from {videoUpload.data.video}.
            </p>
          )}
        </section>
        ) : null
      ) : (
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
      {isAdmin && isPose && (videosQ.data?.length ?? 0) > 0 && (
        <section className="bg-white p-4 rounded-lg shadow space-y-3">
          <h2 className="font-semibold">Videos</h2>
          <p className="text-xs text-slate-500">
            One row per uploaded video. Reassigning moves every frame of that video
            to the selected user.
          </p>
          <table className="w-full text-sm">
            <thead className="text-left text-slate-500 text-xs uppercase">
              <tr>
                <th className="py-1">Video</th>
                <th className="py-1">Frames</th>
                <th className="py-1">Done</th>
                <th className="py-1">Assigned to</th>
                <th className="py-1 w-8"></th>
              </tr>
            </thead>
            <tbody>
              {videosQ.data!.map((v) => (
                <tr key={v.source_video} className="border-t">
                  <td className="py-2 font-mono">{v.source_video}</td>
                  <td className="py-2">{v.frames}</td>
                  <td className="py-2">{v.done}</td>
                  <td className="py-2">
                    <select
                      value={v.assigned_to ?? ''}
                      onChange={(e) => {
                        const uid = Number(e.target.value);
                        if (uid) reassign.mutate({ source: v.source_video, assigneeId: uid });
                      }}
                      className="border rounded px-2 py-1 text-sm"
                    >
                      <option value="">— mixed / none —</option>
                      {(usersQ.data ?? []).map((u) => (
                        <option key={u.id} value={u.id}>
                          {u.username}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="py-2">
                    <button
                      onClick={() => {
                        if (
                          confirm(
                            `Delete video "${v.source_video}" and all ${v.frames} frames (and annotations)? This cannot be undone.`,
                          )
                        )
                          removeVideo.mutate(v.source_video);
                      }}
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
              ))}
            </tbody>
          </table>
        </section>
      )}

      {/* Items */}
      <section className="bg-white p-4 rounded-lg shadow space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold">
            Items{' '}
            <span className="text-sm text-slate-500 font-normal">
              ({itemsQ.data?.total ?? 0})
            </span>
          </h2>
          <div className="flex items-center gap-2">
            {isAdmin && items.some((i) => i.status === 'done' || i.status === 'reviewed') && (
              <button
                onClick={() => {
                  if (
                    confirm(
                      'Delete ALL annotated items (and their frames)? This cannot be undone.',
                    )
                  )
                    removeAnnotated.mutate();
                }}
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
        {items.length === 0 ? (
          <p className="text-sm text-slate-500">No items yet.</p>
        ) : (
          <ul className="divide-y">
            {items.map((i) => (
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
                    />
                  )}
                  <span className="truncate">
                    {(i.payload as { text?: string; frame_index?: number; source_video?: string }).text ??
                      ((i.payload as any).source_video
                        ? `${(i.payload as any).source_video} · frame ${(i.payload as any).frame_index}`
                        : JSON.stringify(i.payload))}
                  </span>
                </Link>
                <span
                  className={`text-xs px-2 py-0.5 rounded capitalize ${
                    i.status === 'done'
                      ? 'bg-emerald-100 text-emerald-700'
                      : i.status === 'in_progress'
                        ? 'bg-amber-100 text-amber-700'
                        : i.status === 'reviewed'
                          ? 'bg-blue-100 text-blue-700'
                          : 'bg-slate-100 text-slate-600'
                  }`}
                >
                  {i.status.replace('_', ' ')}
                </span>
                {(i.status === 'done' ||
                  i.status === 'in_progress' ||
                  i.status === 'reviewed') && (
                  <button
                    onClick={(e) => {
                      e.preventDefault();
                      if (confirm(`Clear annotation on item ${i.id}?`))
                        clearItemAnnotation.mutate(i.id);
                    }}
                    className="text-slate-400 hover:text-amber-600 p-1"
                    title="Clear annotation (keep item)"
                    aria-label="Clear annotation"
                  >
                    {/* eraser icon */}
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
                <button
                  onClick={(e) => {
                    e.preventDefault();
                    if (confirm(`Delete item ${i.id}?`)) removeItem.mutate(i.id);
                  }}
                  className="text-slate-400 hover:text-red-600 p-1"
                  title="Delete this item"
                  aria-label="Delete item"
                >
                  {/* trash icon */}
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
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
