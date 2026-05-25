import { useCoders, useConfig, usePauseSupervisor, useResumeSupervisor, useSupervisor, usePutConfig } from '../hooks/useApi';
import { SupervisorPanel } from '../components/Supervisor/SupervisorPanel';
import { ConfigEditor } from '../components/Supervisor/ConfigEditor';
import type { RuntimeConfig } from '../types';

export function Config() {
  const { data: supervisor, isLoading: supervisorLoading } = useSupervisor();
  const { data: config, isLoading: configLoading } = useConfig();
  const { data: codersData, isLoading: codersLoading } = useCoders();
  const pauseSupervisor = usePauseSupervisor();
  const resumeSupervisor = useResumeSupervisor();
  const putConfig = usePutConfig();

  const loading = supervisorLoading || configLoading || codersLoading;

  if (loading) return <p style={styles.msg}>Loading…</p>;

  const coders = codersData?.coders ?? [];

  return (
    <div style={styles.page}>
      <h1 style={styles.heading}>Config</h1>
      <div style={styles.grid}>
        <div>
          {supervisor && (
            <SupervisorPanel
              status={supervisor}
              onPause={() => { void pauseSupervisor.mutateAsync(); }}
              onResume={() => { void resumeSupervisor.mutateAsync(); }}
              loading={pauseSupervisor.isPending || resumeSupervisor.isPending}
            />
          )}
          <div style={styles.panel}>
            <h3 style={styles.panelTitle}>Installed Coders</h3>
            {coders.length === 0 ? (
              <p style={styles.empty}>No coders registered.</p>
            ) : (
              <ul style={styles.coderList}>
                {coders.map(c => (
                  <li key={c} style={styles.coderItem}>{c}</li>
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
                await putConfig.mutateAsync(updates);
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
  heading: {
    margin: '0 0 1.25rem',
    fontSize: '1rem',
    fontWeight: 600,
    color: '#e4e4e7',
  } as React.CSSProperties,
  msg: {
    padding: '1rem',
    color: '#71717a',
  } as React.CSSProperties,
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(18rem, 1fr))',
    gap: '1.5rem',
    alignItems: 'start',
  } as React.CSSProperties,
  panel: {
    background: '#1c1c20',
    border: '1px solid #3f3f46',
    borderRadius: 8,
    padding: '1rem 1.25rem',
  } as React.CSSProperties,
  panelTitle: {
    margin: '0 0 0.75rem',
    fontSize: '0.9375rem',
    fontWeight: 600,
    color: '#e4e4e7',
  } as React.CSSProperties,
  empty: {
    color: '#52525b',
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
    background: '#09090b',
    border: '1px solid #27272a',
    borderRadius: 4,
    color: '#a1a1aa',
    fontSize: '0.8125rem',
    fontFamily: 'monospace',
  } as React.CSSProperties,
};
