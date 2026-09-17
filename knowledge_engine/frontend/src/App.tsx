import { Navigate, Route, Routes } from 'react-router-dom';

import { AppLayout } from './components/AppLayout';
import { AnswerPage } from './pages/AnswerPage';
import { DashboardPage } from './pages/DashboardPage';
import { EvalPage } from './pages/EvalPage';
import { RetrievePage } from './pages/RetrievePage';
import { RewritePage } from './pages/RewritePage';
import { UploadPage } from './pages/UploadPage';

export default function App() {
  return (
    <AppLayout>
      <Routes>
        <Route path="/" element={<DashboardPage />} />
        <Route path="/upload" element={<UploadPage />} />
        <Route path="/retrieve" element={<RetrievePage />} />
        <Route path="/rewrite" element={<RewritePage />} />
        <Route path="/answer" element={<AnswerPage />} />
        <Route path="/eval" element={<EvalPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppLayout>
  );
}
