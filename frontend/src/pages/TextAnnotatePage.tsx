import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { me } from '@/api/auth';
import { getProject } from '@/api/projects';
import { getItem, listItems, reviewItem, saveAnnotation } from '@/api/items';

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
  const meQ = useQuery({ queryKey: ['me'], queryFn: me });

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

  // Curation: admin or project owner can approve / send back done items.
  const canReview = !!meQ.data && !!projectQ.data && (
    meQ.data.role === 'admin' || meQ.data.id === projectQ.data.owner_id
  );
  const [showSendBack, setShowSendBack] = useState(false);
  const [reviewNoteInput, setReviewNoteInput] = useState('');
  const reviewMut = useMutation({
    mutationFn: (p: { approve: boolean; note?: string }) =>
      reviewItem(currentItemId, p.approve, p.note),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['items', projectId] });
      qc.invalidateQueries({ queryKey: ['item', currentItemId] });
      setShowSendBack(false);
      setReviewNoteInput('');
    },
  });
  useEffect(() => {
    setShowSendBack(false);
    setReviewNoteInput('');
  }, [currentItemId]);

  async function pick(labelName: string) {
    await save.mutateAsync({ label: labelName });
    if (next) navigate(`/projects/${projectId}/annotate/${next.id}`);
  }

  // Keyboard shortcuts
  useEffect(() => {
    const project = projectQ.data;
    if (!project) return;
    function onKey(e: KeyboardEvent) {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA') return;
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
          {idx >= 0 ? `${idx + 1} / ${cohort.length}` : ''}
        </span>
      </header>

      {/* Needs-revision banner: assignee (and admin) sees what to fix. */}
      {item.review_note && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm">
          <p className="font-semibold text-amber-900">Needs revision</p>
          <p className="text-amber-800 mt-0.5">{item.review_note}</p>
        </div>
      )}

      {/* Review panel: admin or project owner can approve / send back. */}
      {canReview && (item.status === 'done' || item.status === 'reviewed') && (
        <div
          className={
            'rounded-lg border p-3 space-y-2 ' +
            (item.status === 'reviewed'
              ? 'border-blue-300 bg-blue-50'
              : 'border-emerald-300 bg-emerald-50')
          }
        >
          <span
            className={
              'text-sm font-semibold ' +
              (item.status === 'reviewed' ? 'text-blue-900' : 'text-emerald-900')
            }
          >
            {item.status === 'reviewed' ? '✓ Reviewed' : 'Ready to review'}
          </span>
          {!showSendBack && (
            <div className="grid grid-cols-2 gap-2">
              <button
                type="button"
                onClick={() => reviewMut.mutate({ approve: true })}
                disabled={reviewMut.isPending || item.status === 'reviewed'}
                className="px-3 py-2 rounded bg-emerald-600 text-white text-sm font-medium hover:bg-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                Approve
              </button>
              <button
                type="button"
                onClick={() => setShowSendBack(true)}
                disabled={reviewMut.isPending}
                className="px-3 py-2 rounded border border-amber-500 text-amber-700 bg-white text-sm font-medium hover:bg-amber-50 disabled:opacity-50"
              >
                Send back
              </button>
            </div>
          )}
          {showSendBack && (
            <div className="space-y-2 pt-2 border-t border-slate-200">
              <textarea
                value={reviewNoteInput}
                onChange={(e) => setReviewNoteInput(e.target.value)}
                placeholder="Optional note for the annotator (what to fix)…"
                rows={2}
                autoFocus
                className="w-full text-sm border rounded px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-amber-300"
              />
              <div className="flex gap-2 justify-end">
                <button
                  type="button"
                  onClick={() => {
                    setShowSendBack(false);
                    setReviewNoteInput('');
                  }}
                  className="text-xs px-3 py-1.5 border rounded text-slate-600 hover:bg-slate-50"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={() =>
                    reviewMut.mutate({
                      approve: false,
                      note: reviewNoteInput.trim() || undefined,
                    })
                  }
                  disabled={reviewMut.isPending}
                  className="text-xs px-3 py-1.5 rounded bg-amber-600 text-white hover:bg-amber-700 disabled:opacity-50"
                >
                  Send back
                </button>
              </div>
            </div>
          )}
        </div>
      )}

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
