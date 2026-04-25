import { api } from './client';

export type ItemStatus = 'pending' | 'in_progress' | 'done' | 'reviewed';

export interface Item {
  id: number;
  project_id: number;
  payload: Record<string, unknown>;
  status: ItemStatus;
  created_at: string;
  assigned_to: number | null;
  review_note?: string | null;
}

export interface Annotation {
  id: number;
  item_id: number;
  annotator_id: number;
  value: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ItemDetail extends Item {
  annotation: Annotation | null;
}

export async function bulkUpload(projectId: number, items: { payload: Record<string, unknown> }[]) {
  const { data } = await api.post<{ created: number }>(
    `/projects/${projectId}/items/bulk`,
    { items },
  );
  return data;
}

// Default limit matches the backend's max (Query(..., le=500)) so the
// annotator's Prev/Next navigator covers every item in the project. If a
// project ever needs >500 items, this needs paged-navigation logic, not
// just a higher cap.
export async function listItems(projectId: number, limit = 500, offset = 0) {
  const { data } = await api.get<{ total: number; items: Item[] }>(
    `/projects/${projectId}/items`,
    { params: { limit, offset } },
  );
  return data;
}

export async function getItem(id: number) {
  const { data } = await api.get<ItemDetail>(`/items/${id}`);
  return data;
}

export async function saveAnnotation(itemId: number, value: Record<string, unknown>) {
  const { data } = await api.put<Annotation>(`/items/${itemId}/annotation`, { value });
  return data;
}

export async function deleteItem(itemId: number) {
  await api.delete(`/items/${itemId}`);
}

export async function clearAnnotation(itemId: number) {
  await api.delete(`/items/${itemId}/annotation`);
}

export type ReviewAction = 'approve' | 'unapprove' | 'send_back';

export async function reviewItem(
  itemId: number,
  action: ReviewAction,
  note?: string,
) {
  const { data } = await api.post<Item>(`/items/${itemId}/review`, {
    action,
    note: note ?? null,
  });
  return data;
}

export async function approveAllDone(projectId: number, sourceVideo?: string) {
  const { data } = await api.post<{ approved: number }>(
    `/projects/${projectId}/items/approve-all-done`,
    null,
    { params: sourceVideo ? { source_video: sourceVideo } : undefined },
  );
  return data;
}

export interface OutlierItem extends Item {
  outlier: {
    kind: 'lr_swap';
    mirror_pairs: string[];
    coco_pairs: string[];
    score: string;          // e.g. "4/6"
  };
}

export async function findOutliers(projectId: number) {
  const { data } = await api.get<{ items: OutlierItem[]; checks_run: string[] }>(
    `/projects/${projectId}/items/outliers`,
  );
  return data;
}

export async function deleteAnnotatedItems(projectId: number) {
  const { data } = await api.post<{ deleted: number }>(
    `/projects/${projectId}/items/delete-annotated`,
  );
  return data;
}

export function exportUrl(projectId: number, format: 'json' | 'jsonl' | 'csv') {
  return `/projects/${projectId}/export?format=${format}`;
}
