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
// 'all' = every item (pending rows carry annotation: null);
// 'annotated' = only rows with an annotation record. Ignored server-side for YOLO.
export type ExportScope = 'all' | 'annotated';

export async function downloadExport(
  projectId: number,
  format: ExportFormat,
  scope: ExportScope = 'all',
  opts?: DownloadOptions,
) {
  const res = await api.get(`/projects/${projectId}/export`, {
    params: { format, scope },
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
  const tag = scope === 'annotated' && format !== 'yolo' ? '_annotated' : '';
  a.download =
    format === 'yolo'
      ? `project_${projectId}_yolo.zip`
      : format === 'bundle'
        ? `project_${projectId}_bundle${tag}.zip`
        : `project_${projectId}${tag}.${format}`;
  a.click();
  URL.revokeObjectURL(url);
}
