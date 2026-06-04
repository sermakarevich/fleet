import { useEffect, useState } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Link, Navigate, NavLink, Route, Routes } from 'react-router-dom';
import { Chat } from './pages/Chat';
import { Tasks } from './pages/Tasks';
import { BD } from './pages/BD';
import { TaskDetail } from './pages/TaskDetail';
import { Config } from './pages/Config';
import { NewTaskPanel } from './components/NewTaskPanel';
import { CommandPalette } from './components/CommandPalette/CommandPalette';
import { useQA, useChatQuestions } from './hooks/useApi';
import { useWebSocket } from './hooks/useWebSocket';
import { useCommandPalette } from './hooks/useCommandPalette';
import { useNativeNotifications } from './hooks/useNativeNotifications';

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1 } },
});

function QAIndicator() {
  const { data } = useQA('open');
  const count = data?.length ?? 0;
  if (count === 0) return null;
  return <span style={styles.qaBadge}>{count}</span>;
}

// Always-visible circle next to the Chat tab: green when there are unanswered
// (pending) ask_human questions, dim gray when the queue is empty. Unlike
// QAIndicator it must render in both states so the color *change* is the signal.
function ChatIndicator() {
  const { data } = useChatQuestions();
  const count = data?.pending.length ?? 0;
  const active = count > 0;
  return (
    <span
      title={
        active
          ? `${count} unanswered question${count === 1 ? '' : 's'}`
          : 'No pending questions'
      }
      style={{ ...styles.chatDot, ...(active ? styles.chatDotActive : styles.chatDotIdle) }}
    />
  );
}

function NavBar({ connected, onNewTask }: { connected: boolean; onNewTask: () => void }) {
  return (
    <nav style={styles.nav}>
      <Link style={styles.brand} to="/tasks">
        fleet
        <QAIndicator />
      </Link>
      <NavLink style={navLinkStyle} to="/tasks">tasks</NavLink>
      <NavLink style={navLinkStyle} to="/bd">bd</NavLink>
      <NavLink style={navLinkStyle} to="/config">config</NavLink>
      <NavLink style={navLinkStyle} to="/chat">
        <span style={styles.chatLink}>
          chat
          <ChatIndicator />
        </span>
      </NavLink>
      <button style={styles.newTaskBtn} onClick={onNewTask}>+ New task</button>
      <span style={{ ...styles.dot, color: connected ? '#22c55e' : '#ef4444' }}>
        {connected ? '● connected' : '○ disconnected'}
      </span>
    </nav>
  );
}

function AppInner() {
  const [toasts, setToasts] = useState<Array<{ id: string; message: string }>>([]);
  const [showNewTask, setShowNewTask] = useState(false);
  const { open: paletteOpen, setOpen: setPaletteOpen } = useCommandPalette();
  const { notify } = useNativeNotifications();

  const addToast = (message: string) => {
    const id = String(Date.now());
    setToasts(prev => [...prev, { id, message }]);
    setTimeout(() => setToasts(prev => prev.filter(t => t.id !== id)), 6000);
  };

  const { connected } = useWebSocket((taskId, event) => {
    if (event.kind === 'ask_human') {
      const question = (event.extra.question as string | undefined) ?? 'New question';
      addToast(`Q&A: ${question.slice(0, 80)}`);
      const title = (event.extra.task_title as string | undefined) ?? taskId;
      notify('ask_human', 'Fleet Q&A', `${title}: ${question.slice(0, 100)}`);
    }
    if (event.kind === 'session_ended') {
      const result = (event.extra.result as string | undefined) ?? '';
      if (result === 'success') {
        const title = (event.extra.task_title as string | undefined) ?? taskId;
        notify('completed', 'Fleet', `${title} completed`);
      }
    }
  });

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setPaletteOpen(true);
      }
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [setPaletteOpen]);

  return (
    <>
      <NavBar connected={connected} onNewTask={() => setShowNewTask(true)} />
      <main style={styles.main}>
        <Routes>
          <Route path="/" element={<Navigate to="/tasks" replace />} />
          <Route path="/tasks" element={<Tasks />} />
          <Route path="/tasks/:id" element={<TaskDetail />} />
          <Route path="/bd" element={<BD />} />
          <Route path="/config" element={<Config />} />
          <Route path="/chat" element={<Chat />} />
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
      {toasts.length > 0 && (
        <div style={styles.toastContainer}>
          {toasts.map(t => (
            <div key={t.id} style={styles.toast}>
              <span style={styles.toastText}>{t.message}</span>
              <button
                style={styles.toastClose}
                onClick={() => setToasts(prev => prev.filter(x => x.id !== t.id))}
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}
    </>
  );
}

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppInner />
      </BrowserRouter>
    </QueryClientProvider>
  );
}

const navLinkStyle = ({ isActive }: { isActive: boolean }): React.CSSProperties => ({
  padding: '0.25rem 0.75rem',
  textDecoration: 'none',
  color: isActive ? '#fff' : '#aaa',
  fontWeight: isActive ? 600 : 400,
  borderBottom: isActive ? '2px solid #60a5fa' : '2px solid transparent',
});

const styles = {
  nav: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.25rem',
    padding: '0 1rem',
    height: '40px',
    background: '#18181b',
    borderBottom: '1px solid #27272a',
    fontFamily: 'system-ui, sans-serif',
    fontSize: '0.875rem',
  } as React.CSSProperties,
  brand: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.375rem',
    fontWeight: 700,
    color: '#fff',
    marginRight: '0.75rem',
    letterSpacing: '-0.02em',
    textDecoration: 'none',
    cursor: 'pointer',
  } as React.CSSProperties,
  qaBadge: {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    minWidth: '1.1rem',
    height: '1.1rem',
    borderRadius: '9999px',
    background: '#3b82f6',
    color: '#fff',
    fontSize: '0.7rem',
    fontWeight: 700,
    padding: '0 0.25rem',
  } as React.CSSProperties,
  chatLink: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '0.375rem',
  } as React.CSSProperties,
  chatDot: {
    display: 'inline-block',
    width: '0.5rem',
    height: '0.5rem',
    borderRadius: '9999px',
    flexShrink: 0,
    transition: 'background-color 0.2s, box-shadow 0.2s',
  } as React.CSSProperties,
  chatDotActive: {
    background: '#22c55e',
    boxShadow: '0 0 0 3px rgba(34,197,94,0.18)',
  } as React.CSSProperties,
  chatDotIdle: {
    background: '#3f3f46',
    boxShadow: 'none',
  } as React.CSSProperties,
  newTaskBtn: {
    marginLeft: 'auto',
    padding: '0.2rem 0.625rem',
    background: '#3b82f6',
    border: '1px solid #3b82f6',
    borderRadius: 4,
    color: '#fff',
    cursor: 'pointer',
    fontSize: '0.8125rem',
    fontWeight: 500,
    fontFamily: 'system-ui, sans-serif',
    lineHeight: '1.4',
  } as React.CSSProperties,
  dot: {
    fontSize: '0.75rem',
    color: '#aaa',
  } as React.CSSProperties,
  main: {
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  toastContainer: {
    position: 'fixed',
    bottom: '1.5rem',
    right: '1.5rem',
    display: 'flex',
    flexDirection: 'column' as const,
    gap: '0.5rem',
    zIndex: 1000,
  } as React.CSSProperties,
  toast: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.75rem',
    background: '#1d4ed8',
    color: '#fff',
    padding: '0.75rem 1rem',
    borderRadius: 6,
    boxShadow: '0 4px 12px rgba(0,0,0,0.4)',
    maxWidth: '20rem',
    fontSize: '0.875rem',
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  toastText: {
    flex: 1,
  } as React.CSSProperties,
  toastClose: {
    background: 'none',
    border: 'none',
    color: '#93c5fd',
    cursor: 'pointer',
    fontSize: '1.125rem',
    lineHeight: 1,
    padding: 0,
    flexShrink: 0,
  } as React.CSSProperties,
};
