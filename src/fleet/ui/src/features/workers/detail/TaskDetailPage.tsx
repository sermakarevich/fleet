// Worker detail page (/workers/:id): header plus the four ADR 0017 tabs
// (Activity, Attempts, Result, Bead). Rendered by App's /workers/:id route
// (keyed by task id so state resets between tasks); legacy /tasks/:id URLs
// redirect here.
import { useState } from 'react';
import { useParams, Navigate } from 'react-router-dom';
import { useTask, useBead, useConfig } from '../../../shared/hooks/useApi';
import { ApiError, errorMessage } from '../../../shared/api';
import { useIsMobile } from '../../../shared/hooks/useIsMobile';
import type { BeadDetail, TaskDetail } from '../../../shared/types';
import { TaskDetailHeader } from './TaskDetailHeader';
import { LoadingState } from '../../../shared/ui/LoadingState';
import { Tabs } from '../../../shared/ui/Tabs';
import { ActivityTab } from './tabs/ActivityTab';
import { AttemptsTab } from './tabs/AttemptsTab';
import { ResultTab } from './tabs/ResultTab';
import { BeadTab } from './tabs/BeadTab';
import { ActivityGutter } from './tabs/ActivityGutter';
import { useActivity } from './useActivity';
import { merge } from '../../../shared/styles/recipes';
import * as T from '../../../shared/styles/tokens';

type TabId = 'activity' | 'attempts' | 'artifacts' | 'bead';

const TABS: { id: TabId; label: string }[] = [
  { id: 'activity', label: 'Activity' },
  { id: 'attempts', label: 'Attempts' },
  { id: 'artifacts', label: 'Result' },
  { id: 'bead', label: 'Bead' },
];

export function TaskDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { data: task, isLoading, error } = useTask(id!);
  const { data: bead, isLoading: beadLoading, error: beadError } = useBead(id ?? null);
  const { data: config } = useConfig();

  if (!id) return <Navigate to="/" replace />;

  if (isLoading) {
    return <LoadingState />;
  }

  if (error || !task) {
    if (error && (!(error instanceof ApiError) || error.status !== 404)) {
      return (
        <p style={merge(styles.msg, { color: T.colors.danger })}>
          Could not load task: {errorMessage(error)}
        </p>
      );
    }
    return <p style={merge(styles.msg, { color: T.colors.danger })}>Task not found.</p>;
  }

  return (
    <TaskDetailLoaded task={task} bead={bead} beadLoading={beadLoading} beadError={beadError} config={config} />
  );
}

// Loaded view: owns the activity feed so ActivityTab and ActivityGutter
// share one subscription. Split out so useActivity runs only when the task
// exists (hooks stay unconditional).
function TaskDetailLoaded({
  task,
  bead,
  beadLoading,
  beadError,
  config,
}: {
  task: TaskDetail;
  bead: BeadDetail | undefined;
  beadLoading: boolean;
  beadError: unknown;
  config: ReturnType<typeof useConfig>['data'];
}) {
  const isMobile = useIsMobile();
  const [activeTab, setActiveTab] = useState<TabId>('activity');
  const feed = useActivity(task.id, task.status);

  // The Bead tab shows while its query loads; it hides once the query
  // errored or returned null (flow steps have no bead).
  const showBead = !beadError && (beadLoading || bead != null);
  const tabs = showBead ? TABS : TABS.filter((t) => t.id !== 'bead');
  const effectiveTab = tabs.some((t) => t.id === activeTab) ? activeTab : 'activity';

  function renderTab() {
    switch (effectiveTab) {
      case 'activity':
        return <ActivityTab taskId={task.id} status={task.status} feed={feed} />;
      case 'attempts':
        return <AttemptsTab taskId={task.id} attempts={task.attempts ?? []} />;
      case 'artifacts':
        return <ResultTab taskId={task.id} status={task.status} result={task.result} />;
      case 'bead':
        return bead ? <BeadTab taskId={task.id} bead={bead} /> : <LoadingState />;
    }
  }

  return (
    <div style={styles.page}>
      <TaskDetailHeader task={task} config={config} bead={bead} />
      <div style={styles.body}>
        <div style={styles.main}>
          <Tabs
            tabs={tabs}
            activeTab={effectiveTab}
            onTabChange={(id) => setActiveTab(id as TabId)}
            label="Task views"
            panelStyle={styles.tabContent}
          >
            {renderTab()}
          </Tabs>
        </div>
        {!isMobile && <ActivityGutter task={task} feed={feed} />}
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  page: {
    display: 'flex',
    flexDirection: 'column',
    height: 'calc(100vh - var(--nav-h, 2.5rem))',
    fontFamily: 'system-ui, sans-serif',
    background: T.colors.bgDeep,
    color: T.colors.textPrimary,
  },
  body: {
    display: 'flex',
    flex: 1,
    overflow: 'hidden',
  },
  main: {
    display: 'flex',
    flexDirection: 'column',
    flex: 1,
    overflow: 'hidden',
  },
  tabContent: {
    flex: 1,
    overflow: 'hidden',
    display: 'flex',
    flexDirection: 'column',
  },
  msg: {
    padding: '1rem',
    color: T.colors.textDim,
  },
};
