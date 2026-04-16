import { api } from './client';

export type ProjectType = 'pose_detection' | 'image_segmentation';

export interface Label {
  id: number;
  project_id: number;
  name: string;
  color: string;
  shortcut: string | null;
}

export interface Project {
  id: number;
  name: string;
  description: string | null;
  type: ProjectType;
  owner_id: number;
  created_at: string;
  labels: Label[];
}

export async function listProjects(ownerId?: number | null) {
  const params = ownerId != null ? { owner_id: ownerId } : undefined;
  const { data } = await api.get<Project[]>('/projects', { params });
  return data;
}

export async function createProject(input: {
  name: string;
  description?: string;
  type: ProjectType;
}) {
  const { data } = await api.post<Project>('/projects', input);
  return data;
}

export async function deleteProject(id: number) {
  await api.delete(`/projects/${id}`);
}

export async function getProject(id: number) {
  const { data } = await api.get<Project>(`/projects/${id}`);
  return data;
}

export async function createLabel(
  projectId: number,
  input: { name: string; color?: string; shortcut?: string | null },
) {
  const { data } = await api.post<Label>(`/projects/${projectId}/labels`, input);
  return data;
}

export async function deleteLabel(labelId: number) {
  await api.delete(`/labels/${labelId}`);
}
