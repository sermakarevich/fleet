import { useState } from 'react';
import { QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Link, Navigate, Route, Routes } from 'react-router-dom';
import { ChatPage } from '../features/chat/ChatPage';
import { TasksPage } from '../features/tasks/TasksPage';
import { BeadsPage } from '../features/beads/BeadsPage';
import { SchedulesPage } from '../features/schedules/SchedulesPage';
import { WorkflowsPage } from '../features/workflows/WorkflowsPage';
import { WorkflowRunPage } from '../features/workflows/WorkflowRunPage';
import { TaskDetailPage } from '../features/task-detail/TaskDetailPage';
import { ConfigPage } from '../features/config/ConfigPage';
import { AnalyticsPage } from '../features/analytics/AnalyticsPage';
import { NewTaskPanel } from '../features/tasks/NewTaskPanel';
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
        <Link to="/tasks">← Back to Tasks</Link>
      </p>
    </div>
  );
}

function AppInner() {
  const [showNewTask, setShowNewTask] = useState(false);
  const { open: paletteOpen, setOpen: setPaletteOpen } = useCommandPalette();
  const { addToast } = useToast();

  return (
    <>
      <GlobalEvents />
      <NavBar onNewTask={() => setShowNewTask(true)} />
      <TokenGate />
      <main style={styles.main}>
        <Routes>
          <Route path="/" element={<Navigate to="/tasks" replace />} />
          <Route path="/tasks" element={<TasksPage />} />
          <Route path="/tasks/:id" element={<TaskDetailPage />} />
          <Route path="/bd" element={<BeadsPage />} />
          <Route path="/schedules" element={<SchedulesPage />} />
          <Route path="/schedules/:id" element={<SchedulesPage />} />
          <Route path="/workflows" element={<WorkflowsPage />} />
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
      {showNewTask && (
        <NewTaskPanel
          onClose={() => setShowNewTask(false)}
          onCreated={id => addToast(`Task ${id} created`)}
        />
      )}
      <CommandPalette
        open={paletteOpen}
        setOpen={setPaletteOpen}
        onCreateTask={() => setShowNewTask(true)}
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
