import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useCoders, useCreateTask, useKillTask, useRequeueTask, useTasks } from '../hooks/useApi';
import type { CreateTaskInput, TaskSummary } from '../types';

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

interface ChipStyle { label: string; color: string; bg: string }

function statusChip(status: string): ChipStyle {
  switch (status) {
    case 'in_progress': return { label: 'Running', color: '#fff', bg: '#16a34a' };
    case 'blocked':     return { label: 'Blocked', color: '#fff', bg: '#d97706' };
    case 'open':
    case 'ready':       return { label: 'Pending', color: '#fff', bg: '#2563eb' };
    case 'closed':      return { label: 'Done',    color: '#71717a', bg: '#27272a' };
    case 'failed':      return { label: 'Failed',  color: '#fff', bg: '#dc2626' };
    default:            return { label: status,    color: '#a1a1aa', bg: '#3f3f46' };
  }
}

const STATUS_ORDER: Record<string, number> = {
  open: 0, ready: 0,
  in_progress: 1,
  blocked: 2,
  closed: 3, failed: 3,
};

function taskOrder(t: TaskSummary): number {
  return STATUS_ORDER[t.status] ?? 9;
}

// ---------------------------------------------------------------------------
// BD task row
// ---------------------------------------------------------------------------

interface RowProps {
  task: TaskSummary;
  onClose: (id: string) => void;
  onRequeue: (id: string) => void;
  onView: (id: string) => void;
}

function BDRow({ task, onClose, onRequeue, onView }: RowProps) {
  const chip = statusChip(task.status);
  const isCloseable = task.status === 'closed' || task.status === 'failed';
  const isBlockedStatus = task.status === 'blocked';

  return (
    <div style={styles.row} onClick={() => onView(task.id)}>
      <span style={{ ...styles.chip, background: chip.bg, color: chip.color }}>
        {chip.label}
      </span>
      <span style={styles.idCell}>{task.id}</span>
      <span style={styles.titleCell} title={task.title}>{task.title}</span>
      <span style={styles.prioCell}>
        {task.priority != null ? task.priority : <span style={styles.dim}>—</span>}
      </span>
      <span style={styles.coderCell}>
        {task.coder ?? <span style={styles.dim}>(default)</span>}
      </span>
      <span style={styles.depsCell} onClick={e => e.stopPropagation()}>
        {task.depends_on.length > 0
          ? task.depends_on.map(dep => (
              <span key={dep} style={styles.depBadge}>{dep}</span>
            ))
          : <span style={styles.dim}>—</span>}
      </span>
      <span style={styles.actionCell} onClick={e => e.stopPropagation()}>
        <button style={styles.viewBtn} onClick={() => onView(task.id)}>View</button>
        {isBlockedStatus && (
          <button style={styles.requeueBtn} onClick={() => onRequeue(task.id)}>Re-queue</button>
        )}
        {isCloseable && (
          <button style={styles.closeRowBtn} onClick={() => onClose(task.id)}>Close</button>
        )}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Create task form (modal panel)
// ---------------------------------------------------------------------------

interface FormProps {
  recentCwds: string[];
  coders: string[];
  onClose: () => void;
  onCreated: (id: string) => void;
}

function CreateTaskForm({ recentCwds, coders, onClose, onCreated }: FormProps) {
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [cwd, setCwd] = useState('');
  const [coder, setCoder] = useState('');
  const [model, setModel] = useState('');
  const [priority, setPriority] = useState('');
  const [titleErr, setTitleErr] = useState('');
  const [cwdErr, setCwdErr] = useState('');
  const createTask = useCreateTask();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    let hasErr = false;
    if (!title.trim()) { setTitleErr('Title is required'); hasErr = true; } else setTitleErr('');
    if (!cwd.trim())   { setCwdErr('Working directory is required'); hasErr = true; } else setCwdErr('');
    if (hasErr) return;
    try {
      const payload: CreateTaskInput = {
        title: title.trim(),
        description: description || undefined,
        cwd: cwd.trim(),
        coder: coder || undefined,
        model: model || undefined,
        priority: priority ? Number(priority) : undefined,
      };
      const result = await createTask.mutateAsync(payload);
      onCreated(result.id);
      onClose();
    } catch {
      // error shown via createTask.error
    }
  };

  return (
    <div style={styles.overlay} onClick={onClose}>
      <div style={styles.formPanel} onClick={e => e.stopPropagation()}>
        <div style={styles.formHeader}>
          <h2 style={styles.formHeading}>Create Task</h2>
          <button style={styles.closeX} onClick={onClose}>×</button>
        </div>
        <form onSubmit={handleSubmit} style={styles.form}>
          <label style={styles.label}>
            Title *
            <input
              style={{ ...styles.input, ...(titleErr ? styles.inputError : {}) }}
              value={title}
              onChange={e => setTitle(e.target.value)}
              placeholder="What should this task do?"
              autoFocus
            />
            {titleErr && <span style={styles.fieldErr}>{titleErr}</span>}
          </label>

          <label style={styles.label}>
            Description
            <textarea
              style={styles.textarea}
              value={description}
              onChange={e => setDescription(e.target.value)}
              placeholder="Optional markdown description"
              rows={3}
            />
          </label>

          <label style={styles.label}>
            Working directory *
            <input
              style={{ ...styles.input, ...(cwdErr ? styles.inputError : {}) }}
              value={cwd}
              onChange={e => setCwd(e.target.value)}
              list="bd-cwd-options"
              placeholder="/path/to/project"
            />
            <datalist id="bd-cwd-options">
              {recentCwds.map(c => <option key={c} value={c} />)}
            </datalist>
            {cwdErr && <span style={styles.fieldErr}>{cwdErr}</span>}
          </label>

          <div style={styles.row2}>
            <label style={{ ...styles.label, flex: 1 }}>
              Coder
              <select style={styles.select} value={coder} onChange={e => setCoder(e.target.value)}>
                <option value="">— default —</option>
                {coders.map(c => <option key={c} value={c}>{c}</option>)}
              </select>
            </label>
            <label style={{ ...styles.label, flex: 1 }}>
              Model
              <input
                style={styles.input}
                value={model}
                onChange={e => setModel(e.target.value)}
                placeholder="default"
              />
            </label>
            <label style={{ ...styles.label, width: '5.5rem' }}>
              Priority
              <input
                style={styles.input}
                type="number"
                value={priority}
                onChange={e => setPriority(e.target.value)}
                placeholder="0"
                min={0}
              />
            </label>
          </div>

          <div style={styles.formFooter}>
            {createTask.error && (
              <span style={{ ...styles.fieldErr, flex: 1 }}>{(createTask.error as Error).message}</span>
            )}
            <button type="button" style={styles.cancelBtn} onClick={onClose}>Cancel</button>
            <button type="submit" style={styles.submitBtn} disabled={createTask.isPending}>
              {createTask.isPending ? 'Creating…' : 'Create task'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// BD page
// ---------------------------------------------------------------------------

export function BD() {
  const navigate = useNavigate();
  const { data: tasksData, isLoading, error } = useTasks();
  const { data: codersData } = useCoders();
  const killTask = useKillTask();
  const requeueTask = useRequeueTask();
  const [showCreate, setShowCreate] = useState(false);
  const [lastCreated, setLastCreated] = useState<string | null>(null);

  const coders = codersData?.coders ?? [];

  const sorted = useMemo(() => {
    if (!tasksData) return [];
    return [...tasksData].sort((a, b) => taskOrder(a) - taskOrder(b));
  }, [tasksData]);

  const recentCwds = useMemo(() => {
    if (!tasksData) return [];
    const seen = new Set<string>();
    const result: string[] = [];
    for (const t of tasksData) {
      if (t.cwd && !seen.has(t.cwd)) {
        seen.add(t.cwd);
        result.push(t.cwd);
        if (result.length >= 10) break;
      }
    }
    return result;
  }, [tasksData]);

  if (isLoading) {
    return <p style={styles.msg}>Loading…</p>;
  }
  if (error) {
    return <p style={{ ...styles.msg, color: '#ef4444' }}>Error: {String(error)}</p>;
  }

  return (
    <div style={styles.page}>
      <div style={styles.topBar}>
        <h1 style={styles.heading}>
          BD Queue <span style={styles.count}>({sorted.length})</span>
        </h1>
        {lastCreated && (
          <span style={styles.createdBanner}>
            Task <span style={styles.createdId}>{lastCreated}</span> created
          </span>
        )}
        <button style={styles.createBtn} onClick={() => setShowCreate(true)}>
          + Create task
        </button>
      </div>

      <div style={styles.panel}>
        <div style={styles.colHeader}>
          <span style={styles.cStatus}>Status</span>
          <span style={styles.cId}>ID</span>
          <span style={styles.cTitle}>Title</span>
          <span style={styles.cPrio}>Pri</span>
          <span style={styles.cCoder}>Coder</span>
          <span style={styles.cDeps}>Depends on</span>
          <span style={styles.cAction} />
        </div>
        {sorted.length === 0 ? (
          <p style={styles.empty}>No tasks in queue.</p>
        ) : (
          sorted.map(task => (
            <BDRow
              key={task.id}
              task={task}
              onClose={id => { void killTask.mutateAsync(id); }}
              onRequeue={id => { void requeueTask.mutateAsync(id); }}
              onView={id => navigate(`/tasks/${id}`)}
            />
          ))
        )}
      </div>

      {showCreate && (
        <CreateTaskForm
          recentCwds={recentCwds}
          coders={coders}
          onClose={() => setShowCreate(false)}
          onCreated={id => {
            setLastCreated(id);
            setTimeout(() => setLastCreated(null), 5000);
          }}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Styles
// ---------------------------------------------------------------------------

const styles = {
  page: {
    padding: '1rem 1.5rem',
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  msg: {
    padding: '1rem',
    color: '#71717a',
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  topBar: {
    display: 'flex',
    alignItems: 'center',
    gap: '1rem',
    marginBottom: '0.875rem',
    flexWrap: 'wrap' as const,
  } as React.CSSProperties,
  heading: {
    margin: 0,
    fontSize: '0.9375rem',
    fontWeight: 600,
    color: '#e4e4e7',
  } as React.CSSProperties,
  count: {
    fontWeight: 400,
    color: '#71717a',
    fontSize: '0.875rem',
  } as React.CSSProperties,
  createdBanner: {
    padding: '0.2rem 0.625rem',
    background: 'rgba(22,163,74,0.12)',
    border: '1px solid #16a34a',
    borderRadius: 4,
    color: '#22c55e',
    fontSize: '0.8125rem',
  } as React.CSSProperties,
  createdId: {
    fontFamily: 'monospace',
    fontWeight: 600,
  } as React.CSSProperties,
  createBtn: {
    marginLeft: 'auto',
    padding: '0.2rem 0.625rem',
    background: '#3b82f6',
    border: '1px solid #3b82f6',
    borderRadius: 4,
    color: '#fff',
    cursor: 'pointer',
    fontSize: '0.8125rem',
    fontWeight: 500,
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  panel: {
    background: '#1c1c20',
    border: '1px solid #3f3f46',
    borderRadius: 8,
    overflow: 'hidden',
  } as React.CSSProperties,
  colHeader: {
    display: 'flex',
    alignItems: 'center',
    padding: '0.4rem 1rem',
    borderBottom: '1px solid #27272a',
    fontSize: '0.75rem',
    fontWeight: 600,
    color: '#71717a',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.05em',
    gap: '0.75rem',
  } as React.CSSProperties,
  cStatus: { width: '5rem', flexShrink: 0 } as React.CSSProperties,
  cId:     { width: '6rem', flexShrink: 0 } as React.CSSProperties,
  cTitle:  { flex: 1, minWidth: 0 } as React.CSSProperties,
  cPrio:   { width: '3rem', flexShrink: 0 } as React.CSSProperties,
  cCoder:  { width: '6rem', flexShrink: 0 } as React.CSSProperties,
  cDeps:   { width: '10rem', flexShrink: 0 } as React.CSSProperties,
  cAction: { width: '9rem', flexShrink: 0 } as React.CSSProperties,
  row: {
    display: 'flex',
    alignItems: 'center',
    padding: '0.5rem 1rem',
    gap: '0.75rem',
    borderBottom: '1px solid #27272a',
    cursor: 'pointer',
    fontSize: '0.875rem',
    color: '#d4d4d8',
  } as React.CSSProperties,
  chip: {
    display: 'inline-flex',
    alignItems: 'center',
    justifyContent: 'center',
    width: '5rem',
    flexShrink: 0,
    padding: '0.15rem 0.5rem',
    borderRadius: 4,
    fontSize: '0.75rem',
    fontWeight: 600,
  } as React.CSSProperties,
  idCell: {
    width: '6rem',
    flexShrink: 0,
    fontFamily: 'monospace',
    color: '#60a5fa',
    fontSize: '0.8125rem',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  titleCell: {
    flex: 1,
    minWidth: 0,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  prioCell: {
    width: '3rem',
    flexShrink: 0,
    fontSize: '0.8125rem',
    color: '#a1a1aa',
    textAlign: 'center' as const,
  } as React.CSSProperties,
  coderCell: {
    width: '6rem',
    flexShrink: 0,
    fontSize: '0.8125rem',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  depsCell: {
    width: '10rem',
    flexShrink: 0,
    display: 'flex',
    flexWrap: 'wrap' as const,
    gap: '0.25rem',
    alignItems: 'center',
  } as React.CSSProperties,
  depBadge: {
    display: 'inline-block',
    padding: '0.1rem 0.4rem',
    background: '#27272a',
    border: '1px solid #3f3f46',
    borderRadius: 4,
    color: '#a1a1aa',
    fontSize: '0.7rem',
    fontFamily: 'monospace',
    whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  actionCell: {
    width: '9rem',
    flexShrink: 0,
    display: 'flex',
    gap: '0.375rem',
    alignItems: 'center',
  } as React.CSSProperties,
  viewBtn: {
    padding: '0.15rem 0.5rem',
    background: 'transparent',
    border: '1px solid #3f3f46',
    borderRadius: 4,
    color: '#71717a',
    cursor: 'pointer',
    fontSize: '0.75rem',
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  requeueBtn: {
    padding: '0.15rem 0.5rem',
    background: 'transparent',
    border: '1px solid #2563eb',
    borderRadius: 4,
    color: '#60a5fa',
    cursor: 'pointer',
    fontSize: '0.75rem',
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  closeRowBtn: {
    padding: '0.15rem 0.5rem',
    background: 'transparent',
    border: '1px solid #3f3f46',
    borderRadius: 4,
    color: '#71717a',
    cursor: 'pointer',
    fontSize: '0.75rem',
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  empty: {
    padding: '1.5rem 1rem',
    color: '#52525b',
    fontSize: '0.875rem',
    margin: 0,
    textAlign: 'center' as const,
  } as React.CSSProperties,
  dim: {
    color: '#52525b',
  } as React.CSSProperties,
  // Modal form styles
  overlay: {
    position: 'fixed',
    inset: 0,
    background: 'rgba(0,0,0,0.6)',
    display: 'flex',
    alignItems: 'flex-start',
    justifyContent: 'center',
    paddingTop: '5rem',
    zIndex: 500,
  } as React.CSSProperties,
  formPanel: {
    background: '#1c1c20',
    border: '1px solid #3f3f46',
    borderRadius: 8,
    width: '100%',
    maxWidth: '36rem',
    maxHeight: 'calc(100vh - 8rem)',
    overflowY: 'auto',
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  formHeader: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '1rem 1.25rem 0.75rem',
    borderBottom: '1px solid #27272a',
  } as React.CSSProperties,
  formHeading: {
    margin: 0,
    fontSize: '0.9375rem',
    fontWeight: 600,
    color: '#e4e4e7',
  } as React.CSSProperties,
  closeX: {
    background: 'none',
    border: 'none',
    color: '#71717a',
    cursor: 'pointer',
    fontSize: '1.25rem',
    lineHeight: 1,
    padding: '0 0.25rem',
  } as React.CSSProperties,
  form: {
    padding: '1rem 1.25rem',
    display: 'flex',
    flexDirection: 'column' as const,
    gap: '0.875rem',
  } as React.CSSProperties,
  label: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: '0.3rem',
    fontSize: '0.8125rem',
    color: '#a1a1aa',
  } as React.CSSProperties,
  input: {
    background: '#09090b',
    border: '1px solid #3f3f46',
    borderRadius: 4,
    color: '#e4e4e7',
    padding: '0.4rem 0.6rem',
    fontSize: '0.875rem',
    fontFamily: 'system-ui, sans-serif',
    outline: 'none',
  } as React.CSSProperties,
  inputError: {
    borderColor: '#ef4444',
  } as React.CSSProperties,
  textarea: {
    background: '#09090b',
    border: '1px solid #3f3f46',
    borderRadius: 4,
    color: '#e4e4e7',
    padding: '0.4rem 0.6rem',
    fontSize: '0.875rem',
    fontFamily: 'monospace',
    outline: 'none',
    resize: 'vertical' as const,
  } as React.CSSProperties,
  select: {
    background: '#09090b',
    border: '1px solid #3f3f46',
    borderRadius: 4,
    color: '#e4e4e7',
    padding: '0.4rem 0.6rem',
    fontSize: '0.875rem',
    fontFamily: 'system-ui, sans-serif',
    outline: 'none',
  } as React.CSSProperties,
  row2: {
    display: 'flex',
    gap: '0.625rem',
  } as React.CSSProperties,
  fieldErr: {
    color: '#ef4444',
    fontSize: '0.75rem',
  } as React.CSSProperties,
  formFooter: {
    display: 'flex',
    justifyContent: 'flex-end',
    alignItems: 'center',
    gap: '0.75rem',
    paddingTop: '0.375rem',
    borderTop: '1px solid #27272a',
  } as React.CSSProperties,
  cancelBtn: {
    padding: '0.4rem 0.875rem',
    background: 'transparent',
    border: '1px solid #3f3f46',
    borderRadius: 4,
    color: '#a1a1aa',
    cursor: 'pointer',
    fontSize: '0.875rem',
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  submitBtn: {
    padding: '0.4rem 0.875rem',
    background: '#3b82f6',
    border: '1px solid #3b82f6',
    borderRadius: 4,
    color: '#fff',
    cursor: 'pointer',
    fontSize: '0.875rem',
    fontWeight: 500,
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
};
