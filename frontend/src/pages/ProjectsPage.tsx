import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { createProject, deleteProject, listProjects, KeypointSchema } from '@/api/projects';
import { listUsers } from '@/api/users';
import { me } from '@/api/auth';
import { useAuth } from '@/stores/auth';
import { useConfirm } from '@/components/ui/ConfirmDialog';

const SCHEMAS: { value: KeypointSchema; label: string; hint: string }[] = [
  { value: 'infant', label: 'Infant pose', hint: '17 COCO keypoints' },
  { value: 'rodent', label: 'Rodent pose', hint: '7 pts — OF / EPM'  },
];

function SchemaBadge({ schema }: { schema: KeypointSchema }) {
  const isRodent = schema === 'rodent';
  return (
    <span
      className={
        'inline-flex items-center px-1.5 py-0.5 rounded text-xs font-medium ring-1 ' +
        (isRodent
          ? 'bg-amber-50 text-amber-800 ring-amber-200'
          : 'bg-sky-50 text-sky-800 ring-sky-200')
      }
      title={isRodent ? 'Rodent pose — 7 keypoints' : 'Infant pose — 17 COCO keypoints'}
    >
      {isRodent ? 'rodent · 7 pts' : 'infant · 17 pts'}
    </span>
  );
}

export default function ProjectsPage() {
  const qc = useQueryClient();
  const logout = useAuth((s) => s.logout);

  const meQ = useQuery({ queryKey: ['me'], queryFn: me });
  const isAdmin = meQ.data?.role === 'admin';
  const confirmDialog = useConfirm();

  const [ownerFilter, setOwnerFilter] = useState<number | 'all'>('all');

  const usersQ = useQuery({
    queryKey: ['users'],
    queryFn: listUsers,
    enabled: isAdmin,
  });

  const effectiveOwner: number | null = !isAdmin
    ? null
    : ownerFilter === 'all'
      ? null
      : ownerFilter;

  const { data: projects = [], isLoading } = useQuery({
    queryKey: ['projects', isAdmin ? effectiveOwner ?? 'all' : 'self'],
    queryFn: () => listProjects(effectiveOwner ?? undefined),
  });

  const usersById = new Map((usersQ.data ?? []).map((u) => [u.id, u]));

  const [name, setName] = useState('');
  const [schema, setSchema] = useState<KeypointSchema>('infant');

  const createMut = useMutation({
    mutationFn: createProject,
    onSuccess: () => {
      setName('');
      qc.invalidateQueries({ queryKey: ['projects'] });
    },
  });
  const deleteMut = useMutation({
    mutationFn: deleteProject,
    onSuccess: () => qc.invalidateQueries({ queryKey: ['projects'] }),
  });

  return (
    <div className="max-w-4xl mx-auto p-6 space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">Projects</h1>
          {meQ.data && (
            <p className="text-sm text-slate-500">
              Signed in as <span className="font-medium">{meQ.data.username}</span>
              {isAdmin && <span className="ml-1 px-1.5 py-0.5 rounded bg-amber-100 text-amber-800 text-xs">admin</span>}
            </p>
          )}
        </div>
        <button onClick={logout} className="text-sm text-slate-600 hover:underline">
          Sign out
        </button>
      </header>

      {isAdmin && (
        <div className="bg-white p-3 rounded-lg shadow flex items-center gap-2">
          <label className="text-sm text-slate-600">View projects of:</label>
          <select
            value={ownerFilter === 'all' ? 'all' : String(ownerFilter)}
            onChange={(e) =>
              setOwnerFilter(e.target.value === 'all' ? 'all' : Number(e.target.value))
            }
            className="border rounded px-3 py-1.5 text-sm"
          >
            <option value="all">All users</option>
            {(usersQ.data ?? []).map((u) => (
              <option key={u.id} value={u.id}>
                {u.username} ({u.role})
              </option>
            ))}
          </select>
        </div>
      )}

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim()) {
            createMut.mutate({ name, type: 'pose_detection', keypoint_schema: schema });
          }
        }}
        className="bg-white p-4 rounded-lg shadow flex gap-2"
      >
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="New project name"
          className="flex-1 border rounded px-3 py-2"
        />
        <select
          value={schema}
          onChange={(e) => setSchema(e.target.value as KeypointSchema)}
          title="Keypoint schema (immutable after creation)"
          className="border rounded px-3 py-2"
        >
          {SCHEMAS.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label} — {s.hint}
            </option>
          ))}
        </select>
        <button className="bg-blue-600 text-white px-4 py-2 rounded hover:bg-blue-700">
          Create
        </button>
      </form>

      {isLoading ? (
        <p className="text-slate-500">Loading…</p>
      ) : projects.length === 0 ? (
        <p className="text-slate-500">No projects yet.</p>
      ) : (
        <ul className="space-y-2">
          {projects.map((p) => {
            const owner = usersById.get(p.owner_id);
            return (
              <li key={p.id} className="bg-white p-4 rounded-lg shadow flex justify-between items-center">
                <Link to={`/projects/${p.id}`} className="flex-1 hover:underline">
                  <p className="font-medium">{p.name}</p>
                  <p className="text-sm text-slate-500 flex items-center gap-2">
                    <span>{p.type}</span>
                    <SchemaBadge schema={p.keypoint_schema} />
                    {isAdmin && (
                      <span className="text-xs text-slate-400">
                        · owner: {owner ? owner.username : `#${p.owner_id}`}
                      </span>
                    )}
                  </p>
                </Link>
                {(isAdmin || p.owner_id === meQ.data?.id) && (
                  <button
                    onClick={() =>
                      confirmDialog.ask({
                        title: 'Delete project?',
                        message: `"${p.name}" — this removes the project and every item, annotation, video and frame it contains. This cannot be undone.`,
                        confirmLabel: 'Delete project',
                        tone: 'danger',
                        requireTypedConfirmation: p.name,
                        onConfirm: () => deleteMut.mutate(p.id),
                      })
                    }
                    className="text-sm text-red-600 hover:underline ml-4"
                  >
                    Delete
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      )}
      {confirmDialog.dialog}
    </div>
  );
}
