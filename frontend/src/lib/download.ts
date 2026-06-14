import { api } from '@/api/client';

export interface DownloadProgress {
  loaded: number;
  // null when the server doesn't send Content-Length (chunked transfer,
  // e.g. streaming JSON/JSONL/CSV). Render an indeterminate bar in that case.
  total: number | null;
}

export interface DownloadOptions {
  onProgress?: (p: DownloadProgress) => void;
  signal?: AbortSignal;
  split?: { train: number; val: number; test: number; seed: number };
  excludeOccluded?: boolean;
  videoIndex?: boolean;
}

export type ExportFormat =
  | 'json'
  | 'jsonl'
  | 'csv'
  | 'yolo'
  | 'bundle'
  | 'yolo_split'
  | 'coco'
  | 'coco_split';

export async function downloadExport(
  projectId: number,
  format: ExportFormat,
  opts?: DownloadOptions,
) {
  const params: Record<string, string | number | boolean> = { format };
  if ((format === 'yolo_split' || format === 'coco_split') && opts?.split) {
    Object.assign(params, opts.split);
  }
  if ((format === 'yolo' || format === 'yolo_split') && opts?.excludeOccluded) {
    params.exclude_occluded = true;
  }
  if (opts?.videoIndex) {
    params.video_index = true;
  }
  const res = await api.get(`/projects/${projectId}/export`, {
    params,
    responseType: 'blob',
    signal: opts?.signal,
    onDownloadProgress: (e) => {
      if (!opts?.onProgress) return;
      const total = typeof e.total === 'number' && e.total > 0 ? e.total : null;
      opts.onProgress({ loaded: e.loaded ?? 0, total });
    },
  });
  const url = URL.createObjectURL(res.data);
  const a = document.createElement('a');
  a.href = url;
  // Archive/JSON formats get an explicit name; text formats fall back to the
  // bare extension (e.g. project_1.json / .jsonl / .csv).
  const archiveNames: Partial<Record<ExportFormat, string>> = {
    yolo: `project_${projectId}_yolo.zip`,
    yolo_split: `project_${projectId}_yolo_split.zip`,
    coco: `project_${projectId}_coco.json`,
    coco_split: `project_${projectId}_coco_split.zip`,
    bundle: `project_${projectId}_bundle.zip`,
  };
  let name = archiveNames[format] ?? `project_${projectId}.${format}`;
  if (
    opts?.videoIndex &&
    (format === 'coco' || format === 'json' || format === 'jsonl' || format === 'csv')
  ) {
    // backend wraps these in a zip when video_index is set
    name = `project_${projectId}_${format}.zip`;
  }
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}
