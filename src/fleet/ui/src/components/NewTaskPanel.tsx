import { useMemo, useState } from 'react';
import { useCoders, useCreateTask, useTemplates, useTasks } from '../hooks/useApi';
import type { Template } from '../types';

interface Props {
  onClose: () => void;
  onCreated: (id: string) => void;
}

export function NewTaskPanel({ onClose, onCreated }: Props) {
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [cwd, setCwd] = useState('');
  const [coder, setCoder] = useState('');
  const [model, setModel] = useState('');
  const [priority, setPriority] = useState('');
  const [titleError, setTitleError] = useState('');

  const { data: codersData } = useCoders();
  const { data: templatesData } = useTemplates();
  const { data: tasksData } = useTasks();
  const createTask = useCreateTask();

  const coders: string[] = codersData?.coders ?? [];
  const templates: Template[] = templatesData?.templates ?? [];

  const recentCwds = useMemo(() => {
    if (!tasksData) return [];
    const seen = new Set<string>();
    const cwds: string[] = [];
    for (const t of tasksData) {
      if (t.cwd && !seen.has(t.cwd)) {
        seen.add(t.cwd);
        cwds.push(t.cwd);
        if (cwds.length >= 10) break;
      }
    }
    return cwds;
  }, [tasksData]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) {
      setTitleError('Title is required');
      return;
    }
    setTitleError('');
    try {
      const result = await createTask.mutateAsync({
        title: title.trim(),
        description: description || undefined,
        cwd: cwd || undefined,
        coder: coder || undefined,
        model: model || undefined,
        priority: priority ? Number(priority) : undefined,
      });
      onCreated(result.id);
      onClose();
    } catch {
      // error displayed via createTask.error
    }
  };

  const applyTemplate = (t: Template) => {
    const lines = t.content.split('\n');
    const firstLine = lines[0].replace(/^#\s*/, '').trim();
    const rest = lines.slice(1).join('\n').trim();
    if (firstLine) setTitle(firstLine);
    setDescription(rest);
  };

  return (
    <div style={styles.overlay} onClick={onClose}>
      <div style={styles.panel} onClick={e => e.stopPropagation()}>
        <div style={styles.header}>
          <h2 style={styles.heading}>New task</h2>
          <button style={styles.closeBtn} onClick={onClose}>×</button>
        </div>
        <form onSubmit={handleSubmit} style={styles.form}>
          <label style={styles.label}>
            Title *
            <input
              style={{ ...styles.input, ...(titleError ? styles.inputError : {}) }}
              value={title}
              onChange={e => setTitle(e.target.value)}
              placeholder="What should this task do?"
              autoFocus
            />
            {titleError && <span style={styles.errorMsg}>{titleError}</span>}
          </label>

          <label style={styles.label}>
            Description
            <textarea
              style={styles.textarea}
              value={description}
              onChange={e => setDescription(e.target.value)}
              placeholder="Markdown description (optional)"
              rows={4}
            />
          </label>

          <label style={styles.label}>
            Working directory
            <input
              style={styles.input}
              value={cwd}
              onChange={e => setCwd(e.target.value)}
              list="cwd-options"
              placeholder="/path/to/project"
            />
            <datalist id="cwd-options">
              {recentCwds.map(c => <option key={c} value={c} />)}
            </datalist>
          </label>

          <div style={styles.row}>
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

            <label style={{ ...styles.label, width: '6rem' }}>
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

          {templates.length > 0 && (
            <div style={styles.templateSection}>
              <p style={styles.templateLabel}>Templates</p>
              <div style={styles.templateList}>
                {templates.map(t => (
                  <button
                    key={t.name}
                    type="button"
                    style={styles.templateBtn}
                    onClick={() => applyTemplate(t)}
                  >
                    {t.name}
                  </button>
                ))}
              </div>
            </div>
          )}

          <div style={styles.actions}>
            {createTask.error && (
              <span style={styles.errorMsg}>
                {(createTask.error as Error).message}
              </span>
            )}
            <button type="button" style={styles.cancelBtn} onClick={onClose}>
              Cancel
            </button>
            <button type="submit" style={styles.submitBtn} disabled={createTask.isPending}>
              {createTask.isPending ? 'Creating…' : 'Create task'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

const styles = {
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
  panel: {
    background: '#1c1c20',
    border: '1px solid #3f3f46',
    borderRadius: 8,
    width: '100%',
    maxWidth: '36rem',
    maxHeight: 'calc(100vh - 8rem)',
    overflowY: 'auto',
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '1rem 1.25rem 0.75rem',
    borderBottom: '1px solid #27272a',
  } as React.CSSProperties,
  heading: {
    margin: 0,
    fontSize: '0.9375rem',
    fontWeight: 600,
    color: '#e4e4e7',
  } as React.CSSProperties,
  closeBtn: {
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
  row: {
    display: 'flex',
    gap: '0.75rem',
  } as React.CSSProperties,
  templateSection: {
    borderTop: '1px solid #27272a',
    paddingTop: '0.75rem',
  } as React.CSSProperties,
  templateLabel: {
    margin: '0 0 0.5rem',
    fontSize: '0.75rem',
    color: '#71717a',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.05em',
  } as React.CSSProperties,
  templateList: {
    display: 'flex',
    flexWrap: 'wrap' as const,
    gap: '0.375rem',
  } as React.CSSProperties,
  templateBtn: {
    padding: '0.25rem 0.625rem',
    background: '#27272a',
    border: '1px solid #3f3f46',
    borderRadius: 4,
    color: '#a1a1aa',
    cursor: 'pointer',
    fontSize: '0.8125rem',
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  actions: {
    display: 'flex',
    justifyContent: 'flex-end',
    alignItems: 'center',
    gap: '0.75rem',
    paddingTop: '0.5rem',
    borderTop: '1px solid #27272a',
  } as React.CSSProperties,
  errorMsg: {
    color: '#ef4444',
    fontSize: '0.75rem',
    flex: 1,
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
