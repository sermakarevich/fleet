/**
 * Recurring workflows browser: workflow schedules on a cron, the schedule
 * form and a detail drawer with upcoming firings and past runs.
 * Called by App's /recurring and /recurring/:id routes; the selected id
 * and the create form live in the URL so both are shareable. The schedules
 * tab (single-task schedules) stays separate via the target filter.
 */
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useSchedules, useWorkflows } from '../../shared/hooks/useApi';
import { useIsMobile } from '../../shared/hooks/useIsMobile';
import * as T from '../../shared/styles/tokens';
import * as R from '../../shared/styles/recipes';
import { RecurringTable } from './RecurringTable';
import { RecurringDrawer } from './RecurringDrawer';
import { RecurringForm } from './RecurringForm';

// Recurring page: heading, table, create form and detail drawer.
export function RecurringPage() {
  const { data: schedules, isLoading, error } = useSchedules('workflow');
  const { data: workflows } = useWorkflows();
  const isMobile = useIsMobile();
  const navigate = useNavigate();
  const { id: selectedId } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const showCreate = searchParams.get('new') === '1';

  if (isLoading) {
    return <p style={R.msgStyle()}>Loading…</p>;
  }
  if (error) {
    return <p style={R.errorMsgStyle()}>Error: {String(error)}</p>;
  }

  const items = schedules ?? [];
  const workflowNames: Record<string, string> = Object.fromEntries(
    (workflows ?? []).map((w) => [w.id, w.name]),
  );

  return (
    <div style={R.pageStyle(isMobile)}>
      <div style={R.topBarStyle()}>
        <h2 style={R.headingStyle()}>
          Recurring workflows <span style={R.countStyle()}>({items.length})</span>
        </h2>
        <button
          style={R.merge(T.btnPrimary, { marginLeft: 'auto' })}
          onClick={() => setSearchParams({ new: '1' })}
        >
          + Schedule a workflow
        </button>
      </div>
      <RecurringTable
        items={items}
        workflowNames={workflowNames}
        selectedId={selectedId ?? null}
        onSelect={(id) => navigate(`/recurring/${id}`)}
        isMobile={isMobile}
      />
      {selectedId && <RecurringDrawer scheduleId={selectedId} onClose={() => navigate('/recurring')} />}
      {showCreate && (
        <RecurringForm
          onClose={() => navigate(selectedId ? `/recurring/${selectedId}` : '/recurring')}
          onSaved={(saved) => navigate(`/recurring/${saved.id}`)}
        />
      )}
    </div>
  );
}
