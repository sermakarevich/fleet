import { useState, useCallback } from 'react';
import { useParams, Navigate } from 'react-router-dom';
import { useTask, useConfig } from '../hooks/useApi';
import { useTaskWebSocket } from '../hooks/useTaskWebSocket';
import { Header } from '../components/TaskDetail/Header';
import { LiveTab } from '../components/TaskDetail/LiveTab';
import { PlanTab } from '../components/TaskDetail/PlanTab';
import { KnowledgeTab } from '../components/TaskDetail/KnowledgeTab';
import { LogTab } from '../components/TaskDetail/LogTab';
import { StderrTab } from '../components/TaskDetail/StderrTab';
import { DiffTab } from '../components/TaskDetail/DiffTab';
import { FilesTab } from '../components/TaskDetail/FilesTab';
import { ActivityGutter } from '../components/TaskDetail/ActivityGutter';
import type { FleetEvent } from '../types';

type TabId = 'live' | 'plan' | 'knowledge' | 'log' | 'stderr' | 'diff' | 'files';

const TABS: { id: TabId; label: string }[] = [
  { id: 'live', label: 'Live' },
  { id: 'plan', label: 'Plan' },
  { id: 'knowledge', label: 'Knowledge' },
  { id: 'log', label: 'Log' },
  { id: 'stderr', label: 'Stderr' },
  { id: 'diff', label: 'Diff' },
  { id: 'files', label: 'Files' },
];

export function TaskDetail() {
  const { id } = useParams<{ id: string }>();
  const [activeTab, setActiveTab] = useState<TabId>('live');
  const [events, setEvents] = useState<FleetEvent[]>([]);
  const { data: task, isLoading, error } = useTask(id!);
  const { data: config } = useConfig();

  const onEvent = useCallback((event: FleetEvent) => {
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
      case 'plan': return <PlanTab taskId={task!.id} />;
      case 'knowledge': return <KnowledgeTab taskId={task!.id} />;
      case 'log': return <LogTab taskId={task!.id} />;
      case 'stderr': return <StderrTab taskId={task!.id} />;
      case 'diff': return <DiffTab taskId={task!.id} />;
      case 'files': return <FilesTab taskId={task!.id} />;
    }
  }

  return (
    <div style={styles.page}>
      <Header task={task} config={config} />
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
        <ActivityGutter task={task} events={events} />
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  page: {
    display: 'flex',
    flexDirection: 'column',
    height: 'calc(100vh - 40px)',
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
