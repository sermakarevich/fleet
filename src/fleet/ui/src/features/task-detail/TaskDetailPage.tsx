import { useState, useCallback, useRef } from 'react';
import { useParams, Navigate } from 'react-router-dom';
import { useTask, useTasks, useConfig } from '../../shared/hooks/useApi';
import { useTaskWebSocket } from '../../shared/hooks/useTaskWebSocket';
import { useIsMobile } from '../../shared/hooks/useIsMobile';
import { Header } from './Header';
import { LiveTab } from './tabs/LiveTab';
import { RunsTab } from './tabs/RunsTab';
import { PlanTab } from './tabs/PlanTab';
import { KnowledgeTab } from './tabs/KnowledgeTab';
import { LogTab } from './tabs/LogTab';
import { StderrTab } from './tabs/StderrTab';
import { DiffTab } from './tabs/DiffTab';
import { FilesTab } from './tabs/FilesTab';
import { EventsTab } from './tabs/EventsTab';
import { ActivityGutter } from './tabs/ActivityGutter';
import type { FleetEvent } from '../../shared/types';

type TabId = 'live' | 'runs' | 'plan' | 'knowledge' | 'log' | 'events' | 'stderr' | 'diff' | 'files';

const TABS: { id: TabId; label: string }[] = [
  { id: 'live', label: 'Live' },
  { id: 'runs', label: 'Runs' },
  { id: 'plan', label: 'Plan' },
  { id: 'knowledge', label: 'Knowledge' },
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
  const { data: tasksList } = useTasks();
  const { data: config } = useConfig();

  // /api/tasks/{id} reads stale task.json; overlay correct status from the
  // beads-reconciled list (which polls /api/tasks every 5s).
  const taskWithStatus = task
    ? { ...task, status: tasksList?.find(t => t.id === id)?.status ?? task.status }
    : undefined;

  const seenKeys = useRef(new Set<string>());

  const onEvent = useCallback((event: FleetEvent) => {
    const key = `${event.ts}|${event.kind}`;
    if (seenKeys.current.has(key)) return;
    seenKeys.current.add(key);
    setEvents(prev => [...prev, event]);
  }, []);

  useTaskWebSocket(id!, onEvent);

  if (!id) return <Navigate to="/" replace />;

  if (isLoading) {
    return <p style={styles.msg}>Loading…</p>;
  }

  if (error || !task) {
    return <p style={{ ...styles.msg, color: '#ef4444' }}>Task not found.</p>;
  }

  function renderTab() {
    switch (activeTab) {
      case 'live': return <LiveTab events={events} />;
      case 'runs': return <RunsTab attempts={task?.attempts ?? []} />;
      case 'plan': return <PlanTab taskId={task!.id} />;
      case 'knowledge': return <KnowledgeTab taskId={task!.id} />;
      case 'log': return <LogTab taskId={task!.id} status={(taskWithStatus ?? task)!.status} />;
      case 'events': return <EventsTab taskId={task!.id} status={(taskWithStatus ?? task)!.status} />;
      case 'stderr': return <StderrTab taskId={task!.id} status={(taskWithStatus ?? task)!.status} />;
      case 'diff': return <DiffTab taskId={task!.id} status={(taskWithStatus ?? task)!.status} />;
      case 'files': return <FilesTab taskId={task!.id} status={(taskWithStatus ?? task)!.status} />;
    }
  }

  return (
    <div style={styles.page}>
      <Header task={taskWithStatus ?? task} config={config} />
      <div style={styles.body}>
        <div style={styles.main}>
          <div style={styles.tabBar}>
            {TABS.map(tab => (
              <button
                key={tab.id}
                style={{
                  ...styles.tabBtn,
                  ...(activeTab === tab.id ? styles.tabBtnActive : {}),
                }}
                onClick={() => setActiveTab(tab.id)}
              >
                {tab.label}
              </button>
            ))}
          </div>
          <div style={styles.tabContent}>
            {renderTab()}
          </div>
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
