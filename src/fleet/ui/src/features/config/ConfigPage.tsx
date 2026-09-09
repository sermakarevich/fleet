import { useCoders, useConfig, usePauseSupervisor, usePutConfig, useRestartSupervisor, useResumeSupervisor, useSupervisor } from '../../shared/hooks/useApi';
import { SupervisorPanel } from './SupervisorPanel';
import { ConfigEditor } from './ConfigEditor';
import { useNativeNotifications } from '../../shared/hooks/useNativeNotifications';
import type { RuntimeConfig } from '../../shared/types';
import { formatKiloTokens } from '../../shared/format';
import * as T from '../../shared/styles/tokens';
import { EmptyState } from '../../shared/ui/EmptyState';
import { LoadingState } from '../../shared/ui/LoadingState';
import { PageShell } from '../../shared/ui/PageShell';

export function ConfigPage() {
  const { data: supervisor, isLoading: supervisorLoading } = useSupervisor();
  const { data: config, isLoading: configLoading } = useConfig();
  const { data: codersData, isLoading: codersLoading } = useCoders();
  const pauseSupervisor = usePauseSupervisor();
  const resumeSupervisor = useResumeSupervisor();
  const restartSupervisor = useRestartSupervisor();
  const putConfig = usePutConfig();
  const { permissions, setPermission } = useNativeNotifications();

  const loading = supervisorLoading || configLoading || codersLoading;

  if (loading) return <LoadingState />;

  const coders = codersData?.coders ?? [];

  return (
    <PageShell title="config">
      <div style={styles.grid}>
        <div>
          {supervisor && (
            <SupervisorPanel
              status={supervisor}
              onPause={() => pauseSupervisor.mutate()}
              onResume={() => resumeSupervisor.mutate()}
              onRestart={() => restartSupervisor.mutateAsync().then(() => undefined)}
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
                Inbox questions
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
              <EmptyState message="No coders registered." />
            ) : (
              <ul style={styles.coderList}>
                {coders.map(c => (
                  <li key={c.name} style={styles.coderItem}>
                    <strong>{c.name}</strong>
                    <span style={styles.coderMeta}>
                      {formatKiloTokens(c.context_limit)} ctx — {c.default_model}
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
              onSave={(updates: Partial<RuntimeConfig>) => putConfig.mutateAsync(updates).then(() => undefined)}
            />
          )}
        </div>
      </div>
    </PageShell>
  );
}

const styles = {
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
    borderRadius: '0.25rem',
    color: T.colors.textSecondary,
    fontSize: '0.8125rem',
    fontFamily: 'monospace',
  } as React.CSSProperties,
  coderMeta: {
    color: T.colors.textDim,
    marginLeft: '0.5rem',
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
