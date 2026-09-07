import { useEffect, useRef } from 'react';
import { Link, NavLink } from 'react-router-dom';
import type { CSSProperties } from 'react';
import { useIsMobile } from '../shared/hooks/useIsMobile';
import { useChatQuestions, useSupervisor, useHealthz } from '../shared/hooks/useApi';
import { colors } from '../shared/styles/tokens';

// Always-visible circle next to the Chat tab: green when there are unanswered
// (pending) ask_human questions, dim gray when the queue is empty.
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

export function NavBar({ connected, onNewTask }: { connected: boolean; onNewTask: () => void }) {
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
      <NavLink style={navLinkStyle} to="/tasks">tasks</NavLink>
      <NavLink style={navLinkStyle} to="/bd">bd</NavLink>
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
          <Link style={styles.brand} to="/tasks">
            fleet
          </Link>
          <StalenessChip />
          <span style={{ ...styles.dot, marginLeft: 'auto', fontSize: '0.7rem', color: connected ? colors.success : colors.danger }}>
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
      <Link style={styles.brand} to="/tasks">
        fleet
      </Link>
      {navLinks}
      <button style={styles.newTaskBtn} onClick={onNewTask}>+ New task</button>
      <StalenessChip />
      <span style={{ ...styles.dot, color: connected ? colors.success : colors.danger }}>
        {connected ? '● connected' : '○ disconnected'}
      </span>
    </nav>
  );
}

const navLinkStyle = ({ isActive }: { isActive: boolean }): CSSProperties => ({
  padding: '0.25rem 0.75rem',
  textDecoration: 'none',
  color: isActive ? '#fff' : colors.textSecondary,
  fontWeight: isActive ? 600 : 400,
  borderBottom: isActive ? `2px solid ${colors.accent}` : '2px solid transparent',
});

const styles = {
  nav: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.25rem',
    padding: '0 1rem',
    height: '40px',
    background: colors.bgSurface,
    borderBottom: `1px solid ${colors.borderSubtle}`,
    fontFamily: 'system-ui, sans-serif',
    fontSize: '0.875rem',
  } as CSSProperties,
  navMobile: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: '0.125rem',
    padding: '0.375rem 0.75rem',
    background: colors.bgSurface,
    borderBottom: `1px solid ${colors.borderSubtle}`,
    fontFamily: 'system-ui, sans-serif',
    fontSize: '0.875rem',
  } as CSSProperties,
  navMobileTop: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
  } as CSSProperties,
  navMobileLinks: {
    display: 'flex',
    alignItems: 'center',
    overflowX: 'auto' as const,
  } as CSSProperties,
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
  } as CSSProperties,
  chatLink: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '0.375rem',
  } as CSSProperties,
  chatDot: {
    display: 'inline-block',
    width: '0.5rem',
    height: '0.5rem',
    borderRadius: '9999px',
    flexShrink: 0,
    transition: 'background-color 0.2s, box-shadow 0.2s',
  } as CSSProperties,
  chatDotActive: {
    background: colors.success,
    boxShadow: '0 0 0 3px rgba(34,197,94,0.18)',
  } as CSSProperties,
  chatDotIdle: {
    background: colors.border,
    boxShadow: 'none',
  } as CSSProperties,
  newTaskBtn: {
    marginLeft: 'auto',
    padding: '0.2rem 0.625rem',
    background: colors.accent,
    border: `1px solid ${colors.accent}`,
    borderRadius: 4,
    color: '#fff',
    cursor: 'pointer',
    fontSize: '0.8125rem',
    fontWeight: 500,
    fontFamily: 'system-ui, sans-serif',
    lineHeight: '1.4',
  } as CSSProperties,
  dot: {
    fontSize: '0.75rem',
    color: colors.textSecondary,
  } as CSSProperties,
  staleChip: {
    display: 'inline-flex',
    alignItems: 'center',
    padding: '0.1rem 0.5rem',
    borderRadius: '9999px',
    background: colors.warningBg,
    color: colors.warningFg,
    fontSize: '0.75rem',
    fontWeight: 600,
    cursor: 'default',
    whiteSpace: 'nowrap' as const,
  } as CSSProperties,
};
