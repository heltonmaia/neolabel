import { api } from './client';

export async function uploadVideo(projectId: number, file: File, fps: number) {
  const form = new FormData();
  form.append('file', file);
  form.append('fps', String(fps));
  const { data } = await api.post<{ video: string; frames: number }>(
    `/projects/${projectId}/videos`,
    form,
    { headers: { 'Content-Type': 'multipart/form-data' } },
  );
  return data;
}
