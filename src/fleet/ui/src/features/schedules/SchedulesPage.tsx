/**
 * Schedules browser: list of recurring workers, create/edit form and a
 * detail drawer with upcoming firings and run history.
 * Composes DataList on the shared PageShell; the selected id and the
 * create form live in the URL so both are shareable. Called by App's
 * /schedules and /schedules/:id routes.
 */
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useSchedules } from '../../shared/hooks/useApi';
import * as T from '../../shared/styles/tokens';
import { DataList } from '../../shared/ui/DataList';
import { LoadingState } from '../../shared/ui/LoadingState';
import { PageShell } from '../../shared/ui/PageShell';
import { ScheduleCard, scheduleColumns } from './scheduleColumns';
import { ScheduleDrawer } from './ScheduleDrawer';
import { ScheduleForm } from './ScheduleForm';

// Schedules page: heading, list, create form and detail drawer.
export function SchedulesPage() {
  const { data: schedules, isLoading, error } = useSchedules('task');
  const navigate = useNavigate();
  const { id: selectedId } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const showCreate = searchParams.get('new') === '1';

  if (error) {
    return <p style={styles.error}>Error: {String(error)}</p>;
  }

  const items = schedules ?? [];

  return (
    <PageShell
      title="Schedules"
      count={items.length}
      subtitle={<>single-task schedules · recurring workflows have their own <Link to="/recurring">tab</Link></>}
      actions={
        <button style={T.btnPrimary} onClick={() => setSearchParams({ new: '1' })}>
          + New schedule
        </button>
      }
    >
      {isLoading ? (
        <LoadingState />
      ) : (
        <DataList
          columns={scheduleColumns()}
          rows={items}
          rowKey={(schedule) => schedule.id}
          onRowClick={(schedule) => navigate(`/schedules/${schedule.id}`)}
          renderCard={(schedule) => <ScheduleCard schedule={schedule} />}
          selectedKey={selectedId ?? null}
          empty="No schedules yet. Create one to run a worker on a cron."
        />
      )}
      {selectedId && <ScheduleDrawer scheduleId={selectedId} onClose={() => navigate('/schedules')} />}
      {showCreate && (
        <ScheduleForm
          onClose={() => navigate(selectedId ? `/schedules/${selectedId}` : '/schedules')}
          onSaved={(saved) => navigate(`/schedules/${saved.id}`)}
        />
      )}
    </PageShell>
  );
}

const styles = {
  error: {
    padding: '1rem', color: T.colors.danger, fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
};
