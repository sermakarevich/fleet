// One schedule table for both Scheduled sub-tabs (ADR 0009 "Shared
// schedule feature"). Fetches /api/schedules for its target, renders the
// shared DataList, and owns the drawer (?schedule=) and create form
// (?new=1) through the URL so both host pages render it bare.
// Rendered by WorkersPage (target "task") and WorkflowsPage (target
// "workflow").
import { useSearchParams } from 'react-router-dom';
import { useSchedules, useWorkflows } from '../../shared/hooks/useApi';
import * as T from '../../shared/styles/tokens';
import { DataList } from '../../shared/ui/DataList';
import { LoadingState } from '../../shared/ui/LoadingState';
import { TriggerDrawer } from './TriggerDrawer';
import { TriggerForm } from './TriggerForm';
import { TriggerCard, triggerColumns } from './triggerColumns';
import type { TriggerTarget } from './types';

// Patch the URL params (selection, create form) without touching the tab.
function useParamPatch() {
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedId = searchParams.get('schedule');
  const showCreate = searchParams.get('new') === '1';
  function patch(next: Record<string, string>) {
    const params = new URLSearchParams(searchParams);
    for (const [k, v] of Object.entries(next)) {
      if (v) params.set(k, v);
      else params.delete(k);
    }
    setSearchParams(params, { replace: true });
  }
  return { selectedId, showCreate, patch };
}

// Task- and workflow-target schedule list with drawer and create form.
export function TriggerTable({ target }: { target: TriggerTarget }) {
  const { data: schedules, isLoading, error } = useSchedules(target);
  const { data: workflows } = useWorkflows();
  const { selectedId, showCreate, patch } = useParamPatch();

  const workflowNames: Record<string, string> = Object.fromEntries(
    (target === 'workflow' ? (workflows ?? []) : []).map((w) => [w.id, w.name]),
  );
  const empty =
    target === 'workflow'
      ? 'No recurring workflows. Pick a workflow and a cron to run it on a timer.'
      : 'No scheduled workers yet. Create one to run a worker on a cron.';

  if (error) {
    return <p style={styles.error}>Error: {String(error)}</p>;
  }

  const items = schedules ?? [];

  return (
    <div>
      <div style={styles.actions}>
        <button style={T.btnPrimary} onClick={() => patch({ new: '1' })}>
          {target === 'workflow' ? '+ Schedule a workflow' : '+ New schedule'}
        </button>
      </div>
      {isLoading ? (
        <LoadingState />
      ) : (
        <DataList
          columns={triggerColumns(target, workflowNames)}
          rows={items}
          rowKey={(schedule) => schedule.id}
          onRowClick={(schedule) => patch({ schedule: schedule.id })}
          renderCard={(schedule) => (
            <TriggerCard
              schedule={schedule}
              target={target}
              workflowName={workflowNames[schedule.workflow_id ?? ''] ?? null}
            />
          )}
          selectedKey={selectedId ?? null}
          empty={empty}
        />
      )}
      {selectedId && (
        <TriggerDrawer
          target={target}
          scheduleId={selectedId}
          onClose={() => patch({ schedule: '' })}
        />
      )}
      {showCreate && (
        <TriggerForm
          target={target}
          onClose={() => patch({ new: '' })}
          onSaved={(saved) => patch({ new: '', schedule: saved.id })}
        />
      )}
    </div>
  );
}

const styles = {
  actions: {
    display: 'flex', justifyContent: 'flex-end', marginBottom: '0.75rem',
  } as React.CSSProperties,
  error: {
    padding: '1rem', color: T.colors.danger, fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
};
