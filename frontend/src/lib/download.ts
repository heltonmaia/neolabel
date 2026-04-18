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
}

export type ExportFormat = 'json' | 'jsonl' | 'csv' | 'yolo' | 'bundle';

export async function downloadExport(
  projectId: number,
  format: ExportFormat,
  opts?: DownloadOptions,
) {
  const res = await api.get(`/projects/${projectId}/export`, {
    params: { format },
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
  a.download =
    format === 'yolo'
      ? `project_${projectId}_yolo.zip`
      : format === 'bundle'
        ? `project_${projectId}_bundle.zip`
        : `project_${projectId}.${format}`;
  a.click();
  URL.revokeObjectURL(url);
}
