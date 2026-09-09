import { useState } from 'react';
import { QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Link, Navigate, Route, Routes, useParams, useSearchParams } from 'react-router-dom';
import { ChatPage } from '../features/chat/ChatPage';
import { WorkersPage } from '../features/workers/WorkersPage';
import { RecurringPage } from '../features/recurring/RecurringPage';
import { WorkflowsPage } from '../features/workflows/WorkflowsPage';
import { WorkflowRunPage } from '../features/workflows/WorkflowRunPage';
import { TaskDetailPage } from '../features/workers/detail/TaskDetailPage';
import { ConfigPage } from '../features/config/ConfigPage';
import { AnalyticsPage } from '../features/analytics/AnalyticsPage';
import { NewWorkerPanel } from '../features/workers/NewWorkerPanel';
import { CommandPalette } from '../features/command-palette/CommandPalette';
import { useCommandPalette } from '../shared/hooks/useCommandPalette';
import { ToastProvider, useToast } from '../shared/contexts/ToastContext';
import { TokenGate } from '../shared/ui/TokenGate';
import { queryClient } from './queryClient';
import { NavBar } from './NavBar';
import { GlobalEvents } from './GlobalEvents';

function NotFound() {
  return (
    <div style={styles.notFound}>
      <h2>404 — Page not found</h2>
      <p>
        <Link to="/workers">← Back to Workers</Link>
      </p>
    </div>
  );
}

// Legacy /tasks/:id URLs redirect to the renamed worker detail page.
export function TaskIdRedirect() {
  const { id } = useParams();
  return <Navigate to={`/workers/${id}`} replace />;
}

// Legacy /schedules/:id URLs redirect into the workers Scheduled sub-tab.
export function ScheduleIdRedirect() {
  const { id } = useParams();
  return <Navigate to={`/workers?tab=scheduled&schedule=${id}`} replace />;
}

// Legacy /bd URLs redirect to the workers list. The bd tab filtered by
// bead status; map each value onto the workers filter vocabulary
// (open→queued, in_progress→running, blocked→blocked, closed→done;
// anything else lands on the default filter).
const BD_STATUS_MAP: Record<string, string> = {
  open: 'queued',
  in_progress: 'running',
  blocked: 'blocked',
  closed: 'done',
};

export function BdRedirect() {
  const [params] = useSearchParams();
  const mapped = BD_STATUS_MAP[params.get('status') ?? ''] ?? '';
  return <Navigate to={{ pathname: '/workers', search: mapped ? `?status=${mapped}` : '' }} replace />;
}

function AppInner() {
  const [showNewWorker, setShowNewWorker] = useState(false);
  const { open: paletteOpen, setOpen: setPaletteOpen } = useCommandPalette();
  const { addToast } = useToast();

  return (
    <>
      <GlobalEvents />
      <NavBar onNewWorker={() => setShowNewWorker(true)} />
      <TokenGate />
      <main style={styles.main}>
        <Routes>
          <Route path="/" element={<Navigate to="/workers" replace />} />
          <Route path="/workers" element={<WorkersPage />} />
          <Route path="/workers/:id" element={<TaskDetailPage />} />
          <Route path="/tasks" element={<Navigate to="/workers" replace />} />
          <Route path="/tasks/:id" element={<TaskIdRedirect />} />
          <Route path="/bd" element={<BdRedirect />} />
          <Route path="/schedules" element={<Navigate to={{ pathname: '/workers', search: '?tab=scheduled' }} replace />} />
          <Route path="/schedules/:id" element={<ScheduleIdRedirect />} />
          <Route path="/workflows" element={<WorkflowsPage />} />
          <Route path="/recurring" element={<RecurringPage />} />
          <Route path="/recurring/:id" element={<RecurringPage />} />
          <Route path="/workflows/new" element={<WorkflowsPage />} />
          <Route path="/workflows/:id" element={<WorkflowsPage />} />
          <Route path="/workflows/:id/runs" element={<WorkflowsPage />} />
          <Route path="/workflow-runs/:runId" element={<WorkflowRunPage />} />
          <Route path="/analytics" element={<AnalyticsPage />} />
          <Route path="/config" element={<ConfigPage />} />
          <Route path="/chat" element={<ChatPage />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
      {showNewWorker && (
        <NewWorkerPanel
          onClose={() => setShowNewWorker(false)}
          onCreated={id => addToast(`Worker ${id} created`)}
        />
      )}
      <CommandPalette
        open={paletteOpen}
        setOpen={setPaletteOpen}
        onCreateWorker={() => setShowNewWorker(true)}
      />
    </>
  );
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <ToastProvider>
          <AppInner />
        </ToastProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
}

const styles = {
  notFound: {
    padding: '2rem', textAlign: 'center' as const,
  } as React.CSSProperties,
  main: {
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
};
