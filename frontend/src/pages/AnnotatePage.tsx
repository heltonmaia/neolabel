import { useQuery } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';
import { getProject } from '@/api/projects';
import PoseAnnotatePage from './PoseAnnotatePage';
import TextAnnotatePage from './TextAnnotatePage';

export default function AnnotatePage() {
  const { id } = useParams();
  const projectId = Number(id);
  const { data: project, isLoading } = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => getProject(projectId),
  });

  if (isLoading) return <p className="p-6">Loading…</p>;
  if (!project) return <p className="p-6">Project not found.</p>;

  if (project.type === 'pose_detection') return <PoseAnnotatePage />;
  // image_segmentation: not yet implemented — placeholder
  if (project.type === 'image_segmentation')
    return (
      <div className="p-6 max-w-xl mx-auto">
        <p className="text-slate-500">
          Image segmentation annotator not yet implemented.
        </p>
      </div>
    );
  return <TextAnnotatePage />;
}
