import { useRef, useState } from 'react';
import { useCoders, useConfig, usePauseSupervisor, usePutConfig, useRestartSupervisor, useResumeSupervisor, useSupervisor } from '../hooks/useApi';
import { SupervisorPanel } from '../components/Supervisor/SupervisorPanel';
import { ConfigEditor } from '../components/Supervisor/ConfigEditor';
import { useNativeNotifications } from '../hooks/useNativeNotifications';
import type { RuntimeConfig } from '../types';
import * as T from '../styles/tokens';

interface SaveResult { ok: boolean; text: string }

export function Config() {
  const { data: supervisor, isLoading: supervisorLoading } = useSupervisor();
  const { data: config, isLoading: configLoading } = useConfig();
  const { data: codersData, isLoading: codersLoading } = useCoders();
  const pauseSupervisor = usePauseSupervisor();
  const resumeSupervisor = useResumeSupervisor();
  const restartSupervisor = useRestartSupervisor();
  const putConfig = usePutConfig();
  const { permissions, setPermission } = useNativeNotifications();

  const [saveResult, setSaveResult] = useState<SaveResult | null>(null);
  const dismissTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const loading = supervisorLoading || configLoading || codersLoading;

  if (loading) return <p style={styles.msg}>Loading…</p>;

  const coders = codersData?.coders ?? [];

  const showSaveResult = (result: SaveResult) => {
    if (dismissTimer.current !== null) clearTimeout(dismissTimer.current);
    setSaveResult(result);
    dismissTimer.current = setTimeout(() => setSaveResult(null), 4000);
  };

  return (
    <div style={styles.page}>
      <div style={styles.pageHeader}>
        <h1 style={styles.heading}>config</h1>
        {saveResult && (
          <span style={{ ...styles.saveBanner, ...(saveResult.ok ? styles.saveBannerOk : styles.saveBannerErr) }}>
            {saveResult.text}
          </span>
        )}
      </div>
      <div style={styles.grid}>
        <div>
          {supervisor && (
            <SupervisorPanel
              status={supervisor}
              onPause={async () => {
                try { await pauseSupervisor.mutateAsync(); }
                catch (err) { showSaveResult({ ok: false, text: err instanceof Error ? err.message : String(err) }); }
              }}
              onResume={async () => {
                try { await resumeSupervisor.mutateAsync(); }
                catch (err) { showSaveResult({ ok: false, text: err instanceof Error ? err.message : String(err) }); }
              }}
              onRestart={async () => {
                try {
                  const result = await restartSupervisor.mutateAsync();
                  const text = result.alive
                    ? `Supervisor restarted — PID ${result.pid}`
                    : 'Restart failed (process exited immediately)';
                  showSaveResult({ ok: result.alive, text });
                } catch (err) {
                  showSaveResult({ ok: false, text: err instanceof Error ? err.message : String(err) });
                }
              }}
              loading={pauseSupervisor.isPending || resumeSupervisor.isPending || restartSupervisor.isPending}
            />
          )}
          <div style={styles.panel}>
            <h3 style={styles.panelTitle}>Notifications</h3>
            <p style={styles.notifNote}>Browser notifications (requires permission)</p>
            <div style={styles.toggleRow}>
              <label style={styles.toggleLabel}>
                <input
                  type="checkbox"
                  checked={permissions.ask_human}
                  onChange={e => setPermission('ask_human', e.target.checked)}
                  style={styles.checkbox}
                />
                Q&amp;A questions
              </label>
            </div>
            <div style={styles.toggleRow}>
              <label style={styles.toggleLabel}>
                <input
                  type="checkbox"
                  checked={permissions.completed}
                  onChange={e => setPermission('completed', e.target.checked)}
                  style={styles.checkbox}
                />
                Task completions
              </label>
            </div>
          </div>
          <div style={styles.panel}>
            <h3 style={styles.panelTitle}>Installed Coders</h3>
            {coders.length === 0 ? (
              <p style={styles.empty}>No coders registered.</p>
            ) : (
              <ul style={styles.coderList}>
                {coders.map(c => (
                  <li key={c.name} style={styles.coderItem}>
                    <strong>{c.name}</strong>
                    <span style={{ color: T.colors.textDim, marginLeft: '0.5rem' }}>
                      {Math.round(c.context_limit / 1000)}k ctx — {c.default_model}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
        <div>
          {config && (
            <ConfigEditor
              config={config}
              onSave={async (updates: Partial<RuntimeConfig>) => {
                try {
                  await putConfig.mutateAsync(updates);
                  showSaveResult({ ok: true, text: 'Config saved' });
                } catch (err) {
                  showSaveResult({ ok: false, text: err instanceof Error ? err.message : String(err) });
                  throw err;
                }
              }}
            />
          )}
        </div>
      </div>
    </div>
  );
}

const styles = {
  page: {
    padding: '1rem 1.5rem',
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  pageHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: '1rem',
    marginBottom: '1.25rem',
    flexWrap: 'wrap' as const,
  } as React.CSSProperties,
  heading: {
    margin: 0,
    fontSize: '0.9375rem',
    fontWeight: 600,
    color: T.colors.textPrimary,
  } as React.CSSProperties,
  saveBanner: {
    display: 'inline-flex',
    alignItems: 'center',
    padding: '0.2rem 0.75rem',
    borderRadius: 4,
    fontSize: '0.8125rem',
    fontWeight: 500,
  } as React.CSSProperties,
  saveBannerOk: {
    background: 'rgba(22,163,74,0.15)',
    border: '1px solid #16a34a',
    color: '#22c55e',
  } as React.CSSProperties,
  saveBannerErr: {
    background: 'rgba(239,68,68,0.12)',
    border: '1px solid #dc2626',
    color: T.colors.danger,
  } as React.CSSProperties,
  msg: {
    padding: '1rem',
    color: T.colors.textDim,
  } as React.CSSProperties,
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(18rem, 1fr))',
    gap: '1.5rem',
    alignItems: 'start',
  } as React.CSSProperties,
  panel: {
    ...T.panel,
    padding: '1rem 1.25rem',
    marginTop: '1rem',
  } as React.CSSProperties,
  panelTitle: {
    margin: '0 0 0.75rem',
    fontSize: '0.9375rem',
    fontWeight: 600,
    color: T.colors.textPrimary,
  } as React.CSSProperties,
  empty: {
    color: T.colors.textMuted,
    fontSize: '0.875rem',
    margin: 0,
  } as React.CSSProperties,
  coderList: {
    margin: 0,
    padding: 0,
    listStyle: 'none',
    display: 'flex',
    flexDirection: 'column' as const,
    gap: '0.375rem',
  } as React.CSSProperties,
  coderItem: {
    padding: '0.3rem 0.6rem',
    background: T.colors.bgDeep,
    border: `1px solid ${T.colors.borderSubtle}`,
    borderRadius: 4,
    color: T.colors.textSecondary,
    fontSize: '0.8125rem',
    fontFamily: 'monospace',
  } as React.CSSProperties,
  notifNote: {
    color: T.colors.textMuted,
    fontSize: '0.8125rem',
    margin: '0 0 0.625rem',
  } as React.CSSProperties,
  toggleRow: {
    marginBottom: '0.5rem',
  } as React.CSSProperties,
  toggleLabel: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
    color: T.colors.textSecondary,
    fontSize: '0.875rem',
    cursor: 'pointer',
  } as React.CSSProperties,
  checkbox: {
    accentColor: T.colors.accent,
    cursor: 'pointer',
  } as React.CSSProperties,
};
