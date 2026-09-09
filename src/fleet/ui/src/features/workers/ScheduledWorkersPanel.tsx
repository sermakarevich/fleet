// Scheduled workers sub-tab: task-target schedules rendered inside the
// workers page. Reuses the schedules feature's table, drawer and form
// (UI 4/7 merges them into features/triggers); selection and the create
// form live in the URL so both are shareable. Rendered by WorkersPage.
import { useSearchParams } from 'react-router-dom';
import { useSchedules } from '../../shared/hooks/useApi';
import * as T from '../../shared/styles/tokens';
import { DataList } from '../../shared/ui/DataList';
import { LoadingState } from '../../shared/ui/LoadingState';
import { ScheduleCard, scheduleColumns } from '../schedules/scheduleColumns';
import { ScheduleDrawer } from '../schedules/ScheduleDrawer';
import { ScheduleForm } from '../schedules/ScheduleForm';

// Task-schedule list with detail drawer and create form.
export function ScheduledWorkersPanel() {
  const { data: schedules, isLoading, error } = useSchedules('task');
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedId = searchParams.get('schedule');
  const showCreate = searchParams.get('new') === '1';

  function updateParams(patch: Record<string, string>) {
    const next = new URLSearchParams(searchParams);
    for (const [k, v] of Object.entries(patch)) {
      if (v) next.set(k, v);
      else next.delete(k);
    }
    setSearchParams(next, { replace: true });
  }

  if (error) {
    return <p style={styles.error}>Error: {String(error)}</p>;
  }

  const items = schedules ?? [];

  return (
    <div>
      <div style={styles.actions}>
        <button style={T.btnPrimary} onClick={() => updateParams({ new: '1' })}>
          + New schedule
        </button>
      </div>
      {isLoading ? (
        <LoadingState />
      ) : (
        <DataList
          columns={scheduleColumns()}
          rows={items}
          rowKey={(schedule) => schedule.id}
          onRowClick={(schedule) => updateParams({ schedule: schedule.id })}
          renderCard={(schedule) => <ScheduleCard schedule={schedule} />}
          selectedKey={selectedId ?? null}
          empty="No scheduled workers yet. Create one to run a worker on a cron."
        />
      )}
      {selectedId && (
        <ScheduleDrawer scheduleId={selectedId} onClose={() => updateParams({ schedule: '' })} />
      )}
      {showCreate && (
        <ScheduleForm
          onClose={() => updateParams({ new: '' })}
          onSaved={(saved) => updateParams({ new: '', schedule: saved.id })}
        />
      )}
    </div>
  );
}

const styles = {
  actions: {
    display: 'flex',
    justifyContent: 'flex-end',
    marginBottom: '0.75rem',
  } as React.CSSProperties,
  error: {
    padding: '1rem', color: T.colors.danger, fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
};
