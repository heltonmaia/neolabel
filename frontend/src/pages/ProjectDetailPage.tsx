import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  createLabel,
  deleteLabel,
  deleteProject,
  getProject,
} from '@/api/projects';
import { bulkUpload, listItems } from '@/api/items';
import { uploadVideo } from '@/api/videos';
import { downloadExport } from '@/lib/download';
import { FILES_BASE } from '@/lib/env';

export default function ProjectDetailPage() {
  const { id } = useParams();
  const projectId = Number(id);
  const qc = useQueryClient();
  const navigate = useNavigate();

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

  const videoUpload = useMutation({
    mutationFn: () => uploadVideo(projectId, videoFile!, videoFps),
    onSuccess: () => {
      setVideoFile(null);
      qc.invalidateQueries({ queryKey: ['items', projectId] });
    },
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
        <div className="flex gap-2">
          <button
            onClick={() => downloadExport(projectId, 'json')}
            className="text-sm border rounded px-3 py-1.5 hover:bg-slate-100"
          >
            Export JSON
          </button>
          <button
            onClick={() => downloadExport(projectId, 'jsonl')}
            className="text-sm border rounded px-3 py-1.5 hover:bg-slate-100"
          >
            JSONL
          </button>
          <button
            onClick={() => downloadExport(projectId, 'csv')}
            className="text-sm border rounded px-3 py-1.5 hover:bg-slate-100"
          >
            CSV
          </button>
          <button
            onClick={() => confirm('Delete project?') && removeProject.mutate()}
            className="text-sm text-red-600 border border-red-200 rounded px-3 py-1.5 hover:bg-red-50"
          >
            Delete
          </button>
        </div>
      </header>

      {/* Labels */}
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

      {/* Upload */}
      {isPose ? (
        <section className="bg-white p-4 rounded-lg shadow space-y-3">
          <h2 className="font-semibold">Upload video</h2>
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

          <button
            onClick={() => videoUpload.mutate()}
            disabled={!videoFile || videoUpload.isPending}
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

      {/* Items */}
      <section className="bg-white p-4 rounded-lg shadow space-y-3">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold">
            Items{' '}
            <span className="text-sm text-slate-500 font-normal">
              ({itemsQ.data?.total ?? 0})
            </span>
          </h2>
          {pendingItem && (
            <Link
              to={`/projects/${projectId}/annotate/${pendingItem.id}`}
              className="bg-emerald-600 text-white px-3 py-1.5 rounded text-sm hover:bg-emerald-700"
            >
              Start annotating →
            </Link>
          )}
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
                  className={`text-xs px-2 py-0.5 rounded ${
                    i.status === 'done'
                      ? 'bg-emerald-100 text-emerald-700'
                      : 'bg-slate-100 text-slate-600'
                  }`}
                >
                  {i.status}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
