/**
 * Recurring workflows browser: workflow schedules on a cron, the schedule
 * form and a detail drawer with upcoming firings and past runs.
 * Composes DataList on the shared PageShell; the selected id and the
 * create form live in the URL so both are shareable. The schedules
 * tab (single-task schedules) stays separate via the target filter.
 * Called by App's /recurring and /recurring/:id routes.
 */
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useSchedules, useWorkflows } from '../../shared/hooks/useApi';
import * as T from '../../shared/styles/tokens';
import { DataList } from '../../shared/ui/DataList';
import { LoadingState } from '../../shared/ui/LoadingState';
import { PageShell } from '../../shared/ui/PageShell';
import { RecurringCard, recurringColumns } from './recurringColumns';
import { RecurringDrawer } from './RecurringDrawer';
import { RecurringForm } from './RecurringForm';

// Recurring page: heading, list, create form and detail drawer.
export function RecurringPage() {
  const { data: schedules, isLoading, error } = useSchedules('workflow');
  const { data: workflows } = useWorkflows();
  const navigate = useNavigate();
  const { id: selectedId } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const showCreate = searchParams.get('new') === '1';

  if (error) {
    return <p style={styles.error}>Error: {String(error)}</p>;
  }

  const items = schedules ?? [];
  const workflowNames: Record<string, string> = Object.fromEntries(
    (workflows ?? []).map((w) => [w.id, w.name]),
  );

  return (
    <PageShell
      title="Recurring workflows"
      count={items.length}
      actions={
        <button style={T.btnPrimary} onClick={() => setSearchParams({ new: '1' })}>
          + Schedule a workflow
        </button>
      }
    >
      {isLoading ? (
        <LoadingState />
      ) : (
        <DataList
          columns={recurringColumns(workflowNames)}
          rows={items}
          rowKey={(schedule) => schedule.id}
          onRowClick={(schedule) => navigate(`/recurring/${schedule.id}`)}
          renderCard={(schedule) => (
            <RecurringCard
              schedule={schedule}
              workflowName={workflowNames[schedule.workflow_id ?? ''] ?? null}
            />
          )}
          selectedKey={selectedId ?? null}
          empty="No recurring workflows. Pick a workflow and a cron to run it on a timer."
        />
      )}
      {selectedId && <RecurringDrawer scheduleId={selectedId} onClose={() => navigate('/recurring')} />}
      {showCreate && (
        <RecurringForm
          onClose={() => navigate(selectedId ? `/recurring/${selectedId}` : '/recurring')}
          onSaved={(saved) => navigate(`/recurring/${saved.id}`)}
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
