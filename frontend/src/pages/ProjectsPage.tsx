import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { createProject, deleteProject, listProjects, ProjectType } from '@/api/projects';
import { useAuth } from '@/stores/auth';

const TYPES: { value: ProjectType; label: string }[] = [
  { value: 'pose_detection', label: 'Pose detection' },
  { value: 'image_segmentation', label: 'Image segmentation' },
];

export default function ProjectsPage() {
  const qc = useQueryClient();
  const logout = useAuth((s) => s.logout);
  const { data: projects = [], isLoading } = useQuery({
    queryKey: ['projects'],
    queryFn: listProjects,
  });

  const [name, setName] = useState('');
  const [type, setType] = useState<ProjectType>('pose_detection');

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
        <h1 className="text-2xl font-semibold">Projects</h1>
        <button onClick={logout} className="text-sm text-slate-600 hover:underline">
          Sign out
        </button>
      </header>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (name.trim()) createMut.mutate({ name, type });
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
          value={type}
          onChange={(e) => setType(e.target.value as ProjectType)}
          className="border rounded px-3 py-2"
        >
          {TYPES.map((t) => (
            <option key={t.value} value={t.value}>{t.label}</option>
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
          {projects.map((p) => (
            <li key={p.id} className="bg-white p-4 rounded-lg shadow flex justify-between items-center">
              <Link to={`/projects/${p.id}`} className="flex-1 hover:underline">
                <p className="font-medium">{p.name}</p>
                <p className="text-sm text-slate-500">{p.type}</p>
              </Link>
              <button
                onClick={() => deleteMut.mutate(p.id)}
                className="text-sm text-red-600 hover:underline ml-4"
              >
                Delete
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
