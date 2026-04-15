import { api } from '@/api/client';

export async function downloadExport(projectId: number, format: 'json' | 'jsonl' | 'csv') {
  const res = await api.get(`/projects/${projectId}/export`, {
    params: { format },
    responseType: 'blob',
  });
  const url = URL.createObjectURL(res.data);
  const a = document.createElement('a');
  a.href = url;
  a.download = `project_${projectId}.${format}`;
  a.click();
  URL.revokeObjectURL(url);
}
