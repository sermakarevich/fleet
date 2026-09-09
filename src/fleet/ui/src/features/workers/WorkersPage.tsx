// Workers page: the renamed tasks page (ADR 0009). Sub-tabs Runs (today's
// worker list), Scheduled (task-target schedules) and Triggered
// (event triggers, ADR 0011); the active sub-tab lives in the URL
// (?tab=scheduled, ?tab=triggered) so all are shareable. Rendered by
// App's /workers route; /tasks redirects here.
import { useSearchParams } from 'react-router-dom';
import { useTasks } from '../../shared/hooks/useApi';
import { PageShell } from '../../shared/ui/PageShell';
import { EventTriggerTable } from '../triggers/EventTriggerTable';
import { TriggerTable } from '../triggers/TriggerTable';
import { RunsTab } from './RunsTab';

const TABS = [
  { id: 'runs', label: 'Runs' },
  { id: 'scheduled', label: 'Scheduled' },
  { id: 'triggered', label: 'Triggered' },
];

type WorkersTab = 'runs' | 'scheduled' | 'triggered';

// Sub-tab shell: Runs shows the worker count, Scheduled/Triggered own lists.
export function WorkersPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const rawTab = searchParams.get('tab');
  const tab: WorkersTab =
    rawTab === 'scheduled' ? 'scheduled' : rawTab === 'triggered' ? 'triggered' : 'runs';
  const { data: polledTasks } = useTasks();

  function handleTabChange(next: string) {
    const params = new URLSearchParams(searchParams);
    if (next === 'scheduled' || next === 'triggered') params.set('tab', next);
    else params.delete('tab');
    setSearchParams(params, { replace: true });
  }

  return (
    <PageShell
      title="workers"
      count={tab === 'runs' ? (polledTasks?.length ?? undefined) : undefined}
      tabs={TABS}
      activeTab={tab}
      onTabChange={handleTabChange}
    >
      {tab === 'runs' ? (
        <RunsTab />
      ) : tab === 'scheduled' ? (
        <TriggerTable target="task" />
      ) : (
        <EventTriggerTable />
      )}
    </PageShell>
  );
}
