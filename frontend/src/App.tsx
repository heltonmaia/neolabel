import { Navigate, Route, Routes } from 'react-router-dom';
import { useAuth } from '@/stores/auth';
import LoginPage from '@/pages/LoginPage';
import ProjectsPage from '@/pages/ProjectsPage';
import ProjectDetailPage from '@/pages/ProjectDetailPage';
import AnnotatePage from '@/pages/AnnotatePage';

function Protected({ children }: { children: React.ReactNode }) {
  const token = useAuth((s) => s.token);
  return token ? <>{children}</> : <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/projects"
        element={
          <Protected>
            <ProjectsPage />
          </Protected>
        }
      />
      <Route
        path="/projects/:id"
        element={
          <Protected>
            <ProjectDetailPage />
          </Protected>
        }
      />
      <Route
        path="/projects/:id/annotate/:itemId"
        element={
          <Protected>
            <AnnotatePage />
          </Protected>
        }
      />
      <Route path="*" element={<Navigate to="/projects" replace />} />
    </Routes>
  );
}
