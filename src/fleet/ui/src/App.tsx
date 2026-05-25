import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, NavLink, Route, Routes } from 'react-router-dom';
import { Dashboard } from './pages/Dashboard';
import { TaskDetail } from './pages/TaskDetail';
import { useQA } from './hooks/useApi';
import { useWebSocket } from './hooks/useWebSocket';

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1 } },
});

function QABadge() {
  const { data } = useQA('open');
  const count = data?.length ?? 0;
  return count > 0 ? <span style={styles.badge}>{count}</span> : null;
}

function NavBar({ connected }: { connected: boolean }) {
  return (
    <nav style={styles.nav}>
      <span style={styles.brand}>fleet</span>
      <NavLink style={navLinkStyle} to="/">Dashboard</NavLink>
      <NavLink style={navLinkStyle} to="/qa">
        Q&amp;A <QABadge />
      </NavLink>
      <NavLink style={navLinkStyle} to="/analytics">Analytics</NavLink>
      <NavLink style={navLinkStyle} to="/config">Config</NavLink>
      <span style={{ ...styles.dot, color: connected ? '#22c55e' : '#ef4444' }}>
        {connected ? '● connected' : '○ disconnected'}
      </span>
    </nav>
  );
}

function AppInner() {
  const { connected } = useWebSocket(() => {
    // Dashboard handles its own WebSocket-driven state; no-op here
  });

  return (
    <>
      <NavBar connected={connected} />
      <main style={styles.main}>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/tasks/:id" element={<TaskDetail />} />
          <Route path="/qa" element={<Placeholder title="Q&A inbox" />} />
          <Route path="/analytics" element={<Placeholder title="Analytics" />} />
          <Route path="/config" element={<Placeholder title="Config" />} />
        </Routes>
      </main>
    </>
  );
}

function Placeholder({ title }: { title: string }) {
  return <p style={{ padding: '1rem', color: '#888' }}>{title} — coming soon</p>;
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
    fontWeight: 700,
    color: '#fff',
    marginRight: '1rem',
    letterSpacing: '-0.02em',
  } as React.CSSProperties,
  badge: {
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
    marginLeft: '0.25rem',
  } as React.CSSProperties,
  dot: {
    marginLeft: 'auto',
    fontSize: '0.75rem',
    color: '#aaa',
  } as React.CSSProperties,
  main: {
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
};
