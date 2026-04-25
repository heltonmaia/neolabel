import { useEffect, useMemo } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { getProject } from '@/api/projects';
import { getItem, listItems, saveAnnotation } from '@/api/items';

export default function TextAnnotatePage() {
  const { id, itemId } = useParams();
  const projectId = Number(id);
  const currentItemId = Number(itemId);
  const qc = useQueryClient();
  const navigate = useNavigate();

  const projectQ = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => getProject(projectId),
  });
  const itemQ = useQuery({
    queryKey: ['item', currentItemId],
    queryFn: () => getItem(currentItemId),
  });
  const itemsQ = useQuery({
    queryKey: ['items', projectId],
    queryFn: () => listItems(projectId),
  });

  const items = itemsQ.data?.items ?? [];
  // Cohort: items sharing the current item's assignee. Prev/Next stays
  // within one annotator's queue (matches what the assignee filter on the
  // project page would show).
  const cohortAssignee = itemQ.data?.assigned_to ?? null;
  const cohort = useMemo(
    () => items.filter((i) => (i.assigned_to ?? null) === cohortAssignee),
    [items, cohortAssignee],
  );
  const idx = useMemo(() => cohort.findIndex((i) => i.id === currentItemId), [cohort, currentItemId]);
  const prev = idx > 0 ? cohort[idx - 1] : null;
  const next = idx >= 0 && idx < cohort.length - 1 ? cohort[idx + 1] : null;

  const save = useMutation({
    mutationFn: (value: Record<string, unknown>) => saveAnnotation(currentItemId, value),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['item', currentItemId] });
      qc.invalidateQueries({ queryKey: ['items', projectId] });
    },
  });

  async function pick(labelName: string) {
    await save.mutateAsync({ label: labelName });
    if (next) navigate(`/projects/${projectId}/annotate/${next.id}`);
  }

  // Keyboard shortcuts
  useEffect(() => {
    const project = projectQ.data;
    if (!project) return;
    function onKey(e: KeyboardEvent) {
      if ((e.target as HTMLElement)?.tagName === 'INPUT') return;
      if (e.key === 'ArrowLeft' && prev) {
        navigate(`/projects/${projectId}/annotate/${prev.id}`);
        return;
      }
      if (e.key === 'ArrowRight' && next) {
        navigate(`/projects/${projectId}/annotate/${next.id}`);
        return;
      }
      const label = project!.labels.find((l) => l.shortcut === e.key);
      if (label) {
        e.preventDefault();
        pick(label.name);
      }
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projectQ.data, prev, next, currentItemId]);

  if (itemQ.isLoading || projectQ.isLoading) return <p className="p-6">Loading…</p>;
  if (!itemQ.data || !projectQ.data) return <p className="p-6">Not found.</p>;

  const item = itemQ.data;
  const project = projectQ.data;
  const currentLabel = (item.annotation?.value as { label?: string } | undefined)?.label;
  const text = (item.payload as { text?: string }).text ?? JSON.stringify(item.payload);

  return (
    <div className="max-w-3xl mx-auto p-6 space-y-6">
      <header className="flex items-center justify-between">
        <Link to={`/projects/${projectId}`} className="text-sm text-blue-600 hover:underline">
          ← {project.name}
        </Link>
        <span className="text-sm text-slate-500">
          {idx >= 0 ? `${idx + 1} / ${items.length}` : ''}
        </span>
      </header>

      <div className="bg-white p-6 rounded-lg shadow min-h-[160px] text-lg whitespace-pre-wrap">
        {text}
      </div>

      <div className="flex flex-wrap gap-2">
        {project.labels.length === 0 ? (
          <p className="text-sm text-slate-500">
            No labels defined. <Link to={`/projects/${projectId}`} className="text-blue-600">Add labels</Link>.
          </p>
        ) : (
          project.labels.map((l) => {
            const selected = currentLabel === l.name;
            return (
              <button
                key={l.id}
                onClick={() => pick(l.name)}
                className={`px-3 py-2 rounded text-white text-sm flex items-center gap-2 ${
                  selected ? 'ring-2 ring-offset-2 ring-slate-900' : ''
                }`}
                style={{ backgroundColor: l.color }}
              >
                {l.name}
                {l.shortcut && (
                  <kbd className="bg-black/30 rounded px-1 text-xs">{l.shortcut}</kbd>
                )}
              </button>
            );
          })
        )}
      </div>

      <footer className="flex items-center justify-between text-sm">
        <button
          onClick={() => prev && navigate(`/projects/${projectId}/annotate/${prev.id}`)}
          disabled={!prev}
          className="px-3 py-1.5 border rounded disabled:opacity-40"
        >
          ← Previous
        </button>
        <span className="text-slate-500">
          <kbd className="border rounded px-1">←</kbd>/<kbd className="border rounded px-1">→</kbd> nav
          {' · '}
          shortcut keys apply labels
        </span>
        <button
          onClick={() => next && navigate(`/projects/${projectId}/annotate/${next.id}`)}
          disabled={!next}
          className="px-3 py-1.5 border rounded disabled:opacity-40"
        >
          Next →
        </button>
      </footer>
    </div>
  );
}
