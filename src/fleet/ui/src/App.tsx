import { useEffect, useRef, useState } from 'react';
import { useIsMobile } from './hooks/useIsMobile';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Link, NavLink, Route, Routes, useMatch } from 'react-router-dom';
import { Chat } from './pages/Chat';
import { Dashboard } from './pages/Dashboard';
import { Tasks } from './pages/Tasks';
import { BD } from './pages/BD';
import { TaskDetail } from './pages/TaskDetail';
import { Config } from './pages/Config';
import { QAInbox } from './pages/QAInbox';
import { Analytics } from './pages/Analytics';
import { NewTaskPanel } from './components/NewTaskPanel';
import { CommandPalette } from './components/CommandPalette/CommandPalette';
import { useQA, useChatQuestions, useSupervisor, useHealthz } from './hooks/useApi';
import { useWebSocket } from './hooks/useWebSocket';
import { useCommandPalette } from './hooks/useCommandPalette';
import { useNativeNotifications } from './hooks/useNativeNotifications';
import { ToastProvider, useToast } from './contexts/ToastContext';

function NotFound() {
  return (
    <div style={{ padding: '2rem', textAlign: 'center' }}>
      <h2>404 — Page not found</h2>
      <p>
        <Link to="/tasks">← Back to Tasks</Link>
      </p>
    </div>
  );
}

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1 } },
});

function useDocumentTitle() {
  const { data } = useChatQuestions();
  const pendingCount = data?.pending.length ?? 0;
  const taskMatch = useMatch('/tasks/:id');
  const taskId = taskMatch?.params.id;
  useEffect(() => {
    const prefix = pendingCount > 0 ? `(${pendingCount}) ` : '';
    const suffix = taskId ? ` - ${taskId}` : '';
    document.title = `${prefix}fleet${suffix}`;
  }, [pendingCount, taskId]);
}

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

function StalenessChip() {
  const { data: supervisor } = useSupervisor();
  const { data: healthz } = useHealthz();
  const supervisorStale = supervisor?.stale === true;
  const serveStale = healthz?.stale === true;
  if (!supervisorStale && !serveStale) return null;
  const parts: string[] = [];
  if (supervisorStale) parts.push('supervisor (fleet run restart)');
  if (serveStale) parts.push('serve (fleet serve restart)');
  const hint = `Stale daemon${parts.length > 1 ? 's' : ''}: ${parts.join(', ')}`;
  return (
    <span title={hint} style={styles.staleChip}>
      ⚠ stale
    </span>
  );
}

function NavBar({ connected, onNewTask }: { connected: boolean; onNewTask: () => void }) {
  const isMobile = useIsMobile();
  const navRef = useRef<HTMLElement>(null);

  useEffect(() => {
    const el = navRef.current;
    if (!el) return;
    document.documentElement.style.setProperty('--nav-h', `${el.offsetHeight}px`);
    const obs = new ResizeObserver(() => {
      document.documentElement.style.setProperty('--nav-h', `${el.offsetHeight}px`);
    });
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  const navLinks = (
    <>
      <NavLink style={navLinkStyle} to="/" end>dash</NavLink>
      <NavLink style={navLinkStyle} to="/tasks">tasks</NavLink>
      <NavLink style={navLinkStyle} to="/bd">bd</NavLink>
      <NavLink style={navLinkStyle} to="/qa">qa</NavLink>
      <NavLink style={navLinkStyle} to="/analytics">analytics</NavLink>
      <NavLink style={navLinkStyle} to="/config">config</NavLink>
      <NavLink style={navLinkStyle} to="/chat">
        <span style={styles.chatLink}>
          chat
          <ChatIndicator />
        </span>
      </NavLink>
    </>
  );

  if (isMobile) {
    return (
      <nav ref={navRef} style={styles.navMobile}>
        <div style={styles.navMobileTop}>
          <Link style={styles.brand} to="/">
            fleet
            <QAIndicator />
          </Link>
          <StalenessChip />
          <span style={{ ...styles.dot, marginLeft: 'auto', fontSize: '0.7rem', color: connected ? '#22c55e' : '#ef4444' }}>
            {connected ? '●' : '○'}
          </span>
          <button style={styles.newTaskBtn} onClick={onNewTask}>+ New</button>
        </div>
        <div style={styles.navMobileLinks} className="nav-scroll">
          {navLinks}
        </div>
      </nav>
    );
  }

  return (
    <nav ref={navRef} style={styles.nav}>
      <Link style={styles.brand} to="/">
        fleet
        <QAIndicator />
      </Link>
      {navLinks}
      <button style={styles.newTaskBtn} onClick={onNewTask}>+ New task</button>
      <StalenessChip />
      <span style={{ ...styles.dot, color: connected ? '#22c55e' : '#ef4444' }}>
        {connected ? '● connected' : '○ disconnected'}
      </span>
    </nav>
  );
}

function AppInner() {
  useDocumentTitle();
  const [showNewTask, setShowNewTask] = useState(false);
  const { open: paletteOpen, setOpen: setPaletteOpen } = useCommandPalette();
  const { notify } = useNativeNotifications();
  const { addToast } = useToast();
  const seenAskHumanIds = useRef<Set<string>>(new Set());

  const { connected } = useWebSocket((taskId, event) => {
    if (event.kind === 'ask_human') {
      const questionId = event.extra?.question_id as string | undefined;
      if (questionId && seenAskHumanIds.current.has(questionId)) return;
      if (questionId) seenAskHumanIds.current.add(questionId);
      const question = (event.extra?.question as string | undefined) ?? 'New question';
      addToast(`Q&A: ${question.slice(0, 80)}`);
      const title = (event.extra?.task_title as string | undefined) ?? taskId;
      notify('ask_human', 'Fleet Q&A', `${title}: ${question.slice(0, 100)}`);
      void queryClient.invalidateQueries({ queryKey: ['qa'] });
      void queryClient.invalidateQueries({ queryKey: ['chat-questions'] });
    }
    if (event.kind === 'session_ended') {
      const result = (event.extra?.result as string | undefined) ?? '';
      if (result === 'success') {
        const durationSec = event.extra?.duration_sec as number | undefined;
        const filesTouched = event.extra?.files_touched as number | undefined;
        let summary = '';
        if (durationSec != null) {
          const mins = Math.round(durationSec / 60);
          summary += ` in ${mins > 0 ? `${mins}m` : '<1m'}`;
        }
        if (filesTouched != null && filesTouched > 0) {
          summary += ` - ${filesTouched} file${filesTouched === 1 ? '' : 's'}`;
        }
        const msg = `${taskId} done${summary}`;
        addToast(msg);
        notify('completed', 'Fleet', msg);
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
          <Route path="/" element={<Dashboard />} />
          <Route path="/tasks" element={<Tasks />} />
          <Route path="/tasks/:id" element={<TaskDetail />} />
          <Route path="/bd" element={<BD />} />
          <Route path="/qa" element={<QAInbox />} />
          <Route path="/analytics" element={<Analytics />} />
          <Route path="/config" element={<Config />} />
          <Route path="/chat" element={<Chat />} />
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
  navMobile: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: '0.125rem',
    padding: '0.375rem 0.75rem',
    background: '#18181b',
    borderBottom: '1px solid #27272a',
    fontFamily: 'system-ui, sans-serif',
    fontSize: '0.875rem',
  } as React.CSSProperties,
  navMobileTop: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
  } as React.CSSProperties,
  navMobileLinks: {
    display: 'flex',
    alignItems: 'center',
    overflowX: 'auto' as const,
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
  staleChip: {
    display: 'inline-flex',
    alignItems: 'center',
    padding: '0.1rem 0.5rem',
    borderRadius: '9999px',
    background: '#854d0e',
    color: '#fef08a',
    fontSize: '0.75rem',
    fontWeight: 600,
    cursor: 'default',
    whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  main: {
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
};
