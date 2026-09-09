// Supervisor group of the settings page: the live status card wired to
// the pause / resume / restart mutations. Rendered by SettingsPage as
// the supervisor section.
import {
  usePauseSupervisor,
  useRestartSupervisor,
  useResumeSupervisor,
  useSupervisor,
} from '../../shared/hooks/useApi';
import * as T from '../../shared/styles/tokens';
import { SupervisorPanel } from './SupervisorPanel';

export function SupervisorSection() {
  const { data: supervisor } = useSupervisor();
  const pauseSupervisor = usePauseSupervisor();
  const resumeSupervisor = useResumeSupervisor();
  const restartSupervisor = useRestartSupervisor();
  const loading =
    pauseSupervisor.isPending || resumeSupervisor.isPending || restartSupervisor.isPending;

  return (
    <section id="settings-supervisor" style={styles.wrap} aria-label="Supervisor">
      {supervisor && (
        <SupervisorPanel
          status={supervisor}
          onPause={() => pauseSupervisor.mutate()}
          onResume={() => resumeSupervisor.mutate()}
          onRestart={() => restartSupervisor.mutateAsync().then(() => undefined)}
          loading={loading}
        />
      )}
    </section>
  );
}

const styles = {
  wrap: {
    scrollMarginTop: '3.5rem',
    color: T.colors.textPrimary,
  } as React.CSSProperties,
};
