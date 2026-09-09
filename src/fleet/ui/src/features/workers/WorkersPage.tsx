// Workers page: the renamed tasks page (ADR 0009). Sub-tabs Runs (today's
// worker list) and Scheduled (task-target schedules); the active sub-tab
// lives in the URL (?tab=scheduled) so both are shareable. Rendered by
// App's /workers route; /tasks redirects here.
import { useSearchParams } from 'react-router-dom';
import { useTasks } from '../../shared/hooks/useApi';
import { PageShell } from '../../shared/ui/PageShell';
import { TriggerTable } from '../triggers/TriggerTable';
import { RunsTab } from './RunsTab';

const TABS = [
  { id: 'runs', label: 'Runs' },
  { id: 'scheduled', label: 'Scheduled' },
];

// Sub-tab shell: Runs shows the worker count, Scheduled owns its list.
export function WorkersPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = searchParams.get('tab') === 'scheduled' ? 'scheduled' : 'runs';
  const { data: polledTasks } = useTasks();

  function handleTabChange(next: string) {
    const params = new URLSearchParams(searchParams);
    if (next === 'scheduled') params.set('tab', 'scheduled');
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
      {tab === 'runs' ? <RunsTab /> : <TriggerTable target="task" />}
    </PageShell>
  );
}
