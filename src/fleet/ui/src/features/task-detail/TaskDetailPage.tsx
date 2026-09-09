import { useState, useCallback, useRef } from 'react';
import { useParams, Navigate } from 'react-router-dom';
import { useTask, useConfig } from '../../shared/hooks/useApi';
import { useEventSocket } from '../../shared/hooks/useEventSocket';
import { useIsMobile } from '../../shared/hooks/useIsMobile';
import { TaskDetailHeader } from './TaskDetailHeader';
import { Tabs } from '../../shared/ui/Tabs';
import { LiveTab } from './tabs/LiveTab';
import { AttemptsTab } from './tabs/AttemptsTab';
import { ChildrenTab } from './tabs/ChildrenTab';
import { StateTab } from './tabs/StateTab';
import { JobDocTab } from './tabs/JobDocTab';
import { LogTab } from './tabs/LogTab';
import { StderrTab } from './tabs/StderrTab';
import { DiffTab } from './tabs/DiffTab';
import { FilesTab } from './tabs/FilesTab';
import { EventsTab } from './tabs/EventsTab';
import { ActivityGutter } from './tabs/ActivityGutter';
import type { FleetEvent } from '../../shared/types';
import { merge, when } from '../../shared/styles/recipes';

type TabId = 'live' | 'attempts' | 'children' | 'artifacts' | 'research' | 'design' | 'log' | 'events' | 'stderr' | 'diff' | 'files';

const TABS: { id: TabId; label: string }[] = [
  { id: 'live', label: 'Live' },
  { id: 'attempts', label: 'Attempts' },
  { id: 'children', label: 'Children' },
  { id: 'artifacts', label: 'Artifacts' },
  { id: 'research', label: 'Research' },
  { id: 'design', label: 'Design' },
  { id: 'log', label: 'Log' },
  { id: 'events', label: 'Events' },
  { id: 'stderr', label: 'Stderr' },
  { id: 'diff', label: 'Diff' },
  { id: 'files', label: 'Files' },
];

export function TaskDetailPage() {
  const { id } = useParams<{ id: string }>();
  const isMobile = useIsMobile();
  const [activeTab, setActiveTab] = useState<TabId>('live');
  const [events, setEvents] = useState<FleetEvent[]>([]);
  const { data: task, isLoading, error } = useTask(id!);
  const { data: config } = useConfig();

  // GET /api/tasks/{id} already returns the beads-reconciled status, so no
  // client-side overlay is needed here.
  const taskWithStatus = task;

  const seenKeys = useRef(new Set<string>());

  const onEvent = useCallback((event: FleetEvent) => {
    const key = `${event.ts}|${event.kind}`;
    if (seenKeys.current.has(key)) return;
    seenKeys.current.add(key);
    setEvents(prev => [...prev, event]);
  }, []);

  useEventSocket<{ event: FleetEvent }>(`/ws/tasks/${id}/events`, ({ event }) => {
    onEvent(event);
  }, { noReconnectCodes: [4004] });

  if (!id) return <Navigate to="/" replace />;

  if (isLoading) {
    return <p style={styles.msg}>Loading…</p>;
  }

  if (error || !task) {
    return <p style={merge(styles.msg, { color: '#ef4444' })}>Task not found.</p>;
  }

  function renderTab() {
    switch (activeTab) {
      case 'live': return <LiveTab events={events} />;
      case 'attempts': return <AttemptsTab taskId={task!.id} attempts={task?.attempts ?? []} />;
      case 'children': return <ChildrenTab taskId={task!.id} />;
      case 'artifacts': return <StateTab taskId={task!.id} result={task!.result} />;
      case 'research': return <JobDocTab taskId={task!.id} kind="research" />;
      case 'design': return <JobDocTab taskId={task!.id} kind="design" />;
      case 'log': return <LogTab taskId={task!.id} status={(taskWithStatus ?? task)!.status} />;
      case 'events': return <EventsTab taskId={task!.id} status={(taskWithStatus ?? task)!.status} />;
      case 'stderr': return <StderrTab taskId={task!.id} status={(taskWithStatus ?? task)!.status} />;
      case 'diff': return <DiffTab taskId={task!.id} status={(taskWithStatus ?? task)!.status} />;
      case 'files': return <FilesTab taskId={task!.id} status={(taskWithStatus ?? task)!.status} />;
    }
  }

  return (
    <div style={styles.page}>
      <TaskDetailHeader task={taskWithStatus ?? task} config={config} />
      <div style={styles.body}>
        <div style={styles.main}>
          <Tabs
            tabs={TABS}
            activeTab={activeTab}
            onTabChange={(id) => setActiveTab(id as TabId)}
            label="Task views"
            barStyle={styles.tabBar}
            tabStyle={(active) => merge(styles.tabBtn, when(active, styles.tabBtnActive), {  })}
            panelStyle={styles.tabContent}
          >
            {renderTab()}
          </Tabs>
        </div>
        {!isMobile && <ActivityGutter task={taskWithStatus ?? task} events={events} />}
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  page: {
    display: 'flex',
    flexDirection: 'column',
    height: 'calc(100vh - var(--nav-h, 40px))',
    fontFamily: 'system-ui, sans-serif',
    background: '#09090b',
    color: '#e4e4e7',
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
  tabBar: {
    display: 'flex',
    gap: 0,
    borderBottom: '1px solid #27272a',
    background: '#18181b',
    overflowX: 'auto',
    flexShrink: 0,
  },
  tabBtn: {
    padding: '0.4rem 0.9rem',
    background: 'transparent',
    border: 'none',
    borderBottom: '2px solid transparent',
    color: '#71717a',
    cursor: 'pointer',
    fontSize: '0.8rem',
    fontWeight: 500,
    whiteSpace: 'nowrap',
  },
  tabBtnActive: {
    color: '#e4e4e7',
    borderBottomColor: '#3b82f6',
    fontWeight: 600,
  },
  tabContent: {
    flex: 1,
    overflow: 'hidden',
    display: 'flex',
    flexDirection: 'column',
  },
  msg: {
    padding: '1rem',
    color: '#71717a',
  },
};
