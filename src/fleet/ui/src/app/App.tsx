import { useState } from 'react';
import { QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Link, Navigate, Route, Routes, useParams, useSearchParams } from 'react-router-dom';
import { InboxPage } from '../features/inbox/InboxPage';
import { InboxDetailPage } from '../features/inbox/InboxDetailPage';
import { WorkersPage } from '../features/workers/WorkersPage';
import { WorkflowsPage } from '../features/workflows/WorkflowsPage';
import { WorkflowRunPage } from '../features/workflows/WorkflowRunPage';
import { TaskDetailPage } from '../features/workers/detail/TaskDetailPage';
import { SettingsPage } from '../features/settings/SettingsPage';
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

// Legacy /recurring URLs redirect into the workflows Scheduled sub-tab
// (ADR 0009 shared triggers); an id opens the schedule drawer.
export function RecurringIdRedirect() {
  const { id } = useParams();
  return <Navigate to={`/workflows?tab=scheduled&schedule=${id}`} replace />;
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

// Legacy /analytics URLs redirect to the workers list (ADR 0009 UI 7/7):
// the charts are deleted and the needs-attention strip on WorkersPage
// (reads /api/analytics/summary) is their replacement.
export function AnalyticsRedirect() {
  return <Navigate to="/workers" replace />;
}

// Legacy /config URLs redirect to the renamed settings page (ADR 0009).
export function ConfigRedirect() {
  return <Navigate to="/settings" replace />;
}

// Legacy /chat URLs redirect to the renamed inbox (ADR 0009).
export function ChatRedirect() {
  return <Navigate to="/inbox" replace />;
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
          {/*
            Final route table (ADR 0009). Four live tabs: /workers,
            /workflows, /inbox, /settings. Every legacy route below
            redirects with <Navigate replace> so old links keep working:
            - UI 2: /tasks, /tasks/:id, /schedules, /schedules/:id → workers
            - UI 3: /bd → workers (status mapped in BdRedirect)
            - UI 4: /recurring, /recurring/:id → workflows Scheduled sub-tab
            - UI 5: /chat → inbox
            - UI 6: /config → settings
            - UI 7: /analytics → workers (charts deleted; the
              needs-attention strip replaces them)
          */}
          <Route path="/" element={<Navigate to="/workers" replace />} />
          <Route path="/workers" element={<WorkersPage />} />
          <Route path="/workers/:id" element={<TaskDetailPage />} />
          <Route path="/tasks" element={<Navigate to="/workers" replace />} />
          <Route path="/tasks/:id" element={<TaskIdRedirect />} />
          <Route path="/bd" element={<BdRedirect />} />
          <Route path="/schedules" element={<Navigate to={{ pathname: '/workers', search: '?tab=scheduled' }} replace />} />
          <Route path="/schedules/:id" element={<ScheduleIdRedirect />} />
          <Route path="/workflows" element={<WorkflowsPage />} />
          <Route path="/recurring" element={<Navigate to={{ pathname: '/workflows', search: '?tab=scheduled' }} replace />} />
          <Route path="/recurring/:id" element={<RecurringIdRedirect />} />
          <Route path="/workflows/new" element={<WorkflowsPage />} />
          <Route path="/workflows/:id" element={<WorkflowsPage />} />
          <Route path="/workflows/:id/runs" element={<WorkflowsPage />} />
          <Route path="/workflow-runs/:runId" element={<WorkflowRunPage />} />
          <Route path="/analytics" element={<AnalyticsRedirect />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/config" element={<ConfigRedirect />} />
          <Route path="/inbox" element={<InboxPage />} />
          <Route path="/inbox/:id" element={<InboxDetailPage />} />
          <Route path="/chat" element={<ChatRedirect />} />
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
