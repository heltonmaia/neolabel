import { api } from './client';

export interface VideoSummary {
  source_video: string;
  frames: number;
  done: number;
  assigned_to: number | null;
}

export async function uploadVideo(
  projectId: number,
  file: File,
  fps: number,
  assigneeId: number | null,
  rotation: 0 | 90 | 180 | 270 = 0,
) {
  const form = new FormData();
  form.append('file', file);
  form.append('fps', String(fps));
  if (assigneeId !== null) form.append('assignee_id', String(assigneeId));
  form.append('rotation', String(rotation));
  const { data } = await api.post<{ video: string; frames: number }>(
    `/projects/${projectId}/videos`,
    form,
    { headers: { 'Content-Type': 'multipart/form-data' } },
  );
  return data;
}

export async function listVideos(projectId: number) {
  const { data } = await api.get<VideoSummary[]>(`/projects/${projectId}/videos`);
  return data;
}

export async function reassignVideo(
  projectId: number,
  sourceVideo: string,
  assigneeId: number | null,
) {
  const { data } = await api.patch<{ reassigned: number; assignee_id: number | null }>(
    `/projects/${projectId}/videos/${encodeURIComponent(sourceVideo)}/assign`,
    { assignee_id: assigneeId },
  );
  return data;
}

export async function deleteVideo(projectId: number, sourceVideo: string) {
  const { data } = await api.delete<{ deleted: number }>(
    `/projects/${projectId}/videos/${encodeURIComponent(sourceVideo)}`,
  );
  return data;
}
