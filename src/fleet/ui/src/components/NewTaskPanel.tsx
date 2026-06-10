import { useEffect, useMemo, useState } from 'react';
import { useCoders, useCreateTask, useTemplates, useTasks } from '../hooks/useApi';
import type { CoderInfo, Template } from '../types';
import * as T from '../styles/tokens';

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
  const [args, setArgs] = useState('');
  const [dependencies, setDependencies] = useState<string[]>([]);
  const [titleError, setTitleError] = useState('');

  const { data: codersData } = useCoders();
  const { data: templatesData } = useTemplates();
  const { data: tasksData } = useTasks();
  const createTask = useCreateTask();

  const coders: CoderInfo[] = codersData?.coders ?? [];
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

  const openTasks = useMemo(() => {
    if (!tasksData) return [];
    return tasksData.filter(t => t.status !== 'closed' && t.status !== 'failed');
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
        args: args.trim() || undefined,
        dependencies: dependencies.length > 0 ? dependencies : undefined,
      });
      onCreated(result.id);
      onClose();
    } catch {
      // error displayed via createTask.error
    }
  };

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      handleSubmit(e as unknown as React.FormEvent);
    }
  };

  const handleCoderChange = (name: string) => {
    setCoder(name);
    const info = coders.find(c => c.name === name);
    if (info?.default_model) setModel(info.default_model);
    else if (!name) setModel('');
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
        <form onSubmit={handleSubmit} onKeyDown={handleKeyDown} style={styles.form}>
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
              <select style={styles.select} value={coder} onChange={e => handleCoderChange(e.target.value)}>
                <option value="">— default —</option>
                {coders.map(c => (
                  <option key={c.name} value={c.name}>
                    {c.name} ({Math.round(c.context_limit / 1000)}k) — {c.default_model}
                  </option>
                ))}
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

          {openTasks.length > 0 && (
            <label style={styles.label}>
              Dependencies
              <select
                multiple
                style={styles.multiSelect}
                value={dependencies}
                onChange={e => setDependencies(Array.from(e.target.selectedOptions, o => o.value))}
              >
                {openTasks.map(t => (
                  <option key={t.id} value={t.id}>
                    {t.id} — {t.title}
                  </option>
                ))}
              </select>
              <span style={styles.hint}>Hold Ctrl/⌘ to select multiple</span>
            </label>
          )}

          <label style={styles.label}>
            Extra args
            <input
              style={styles.input}
              value={args}
              onChange={e => setArgs(e.target.value)}
              placeholder="--deps fleet-abc,fleet-xyz --type feature"
            />
          </label>

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
    ...T.panel,
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
    borderBottom: `1px solid ${T.colors.borderSubtle}`,
  } as React.CSSProperties,
  heading: {
    margin: 0,
    fontSize: '0.9375rem',
    fontWeight: 600,
    color: T.colors.textPrimary,
  } as React.CSSProperties,
  closeBtn: {
    background: 'none',
    border: 'none',
    color: T.colors.textDim,
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
    color: T.colors.textSecondary,
  } as React.CSSProperties,
  input: {
    background: T.colors.bgDeep,
    border: `1px solid ${T.colors.border}`,
    borderRadius: 4,
    color: T.colors.textPrimary,
    padding: '0.4rem 0.6rem',
    fontSize: '0.875rem',
    fontFamily: 'system-ui, sans-serif',
    outline: 'none',
  } as React.CSSProperties,
  inputError: {
    borderColor: T.colors.danger,
  } as React.CSSProperties,
  textarea: {
    background: T.colors.bgDeep,
    border: `1px solid ${T.colors.border}`,
    borderRadius: 4,
    color: T.colors.textPrimary,
    padding: '0.4rem 0.6rem',
    fontSize: '0.875rem',
    fontFamily: 'monospace',
    outline: 'none',
    resize: 'vertical' as const,
  } as React.CSSProperties,
  select: {
    background: T.colors.bgDeep,
    border: `1px solid ${T.colors.border}`,
    borderRadius: 4,
    color: T.colors.textPrimary,
    padding: '0.4rem 0.6rem',
    fontSize: '0.875rem',
    fontFamily: 'system-ui, sans-serif',
    outline: 'none',
  } as React.CSSProperties,
  multiSelect: {
    background: T.colors.bgDeep,
    border: `1px solid ${T.colors.border}`,
    borderRadius: 4,
    color: T.colors.textPrimary,
    padding: '0.25rem',
    fontSize: '0.8125rem',
    fontFamily: 'monospace',
    outline: 'none',
    minHeight: '5rem',
    maxHeight: '8rem',
  } as React.CSSProperties,
  hint: {
    fontSize: '0.6875rem',
    color: T.colors.textDim,
  } as React.CSSProperties,
  row: {
    display: 'flex',
    gap: '0.75rem',
  } as React.CSSProperties,
  templateSection: {
    borderTop: `1px solid ${T.colors.borderSubtle}`,
    paddingTop: '0.75rem',
  } as React.CSSProperties,
  templateLabel: {
    margin: '0 0 0.5rem',
    fontSize: '0.75rem',
    color: T.colors.textDim,
    textTransform: 'uppercase' as const,
    letterSpacing: '0.05em',
  } as React.CSSProperties,
  templateList: {
    display: 'flex',
    flexWrap: 'wrap' as const,
    gap: '0.375rem',
  } as React.CSSProperties,
  templateBtn: {
    ...T.btnGhost,
    padding: '0.25rem 0.625rem',
    background: T.colors.borderSubtle,
    fontSize: '0.8125rem',
  } as React.CSSProperties,
  actions: {
    display: 'flex',
    justifyContent: 'flex-end',
    alignItems: 'center',
    gap: '0.75rem',
    paddingTop: '0.5rem',
    borderTop: `1px solid ${T.colors.borderSubtle}`,
  } as React.CSSProperties,
  errorMsg: {
    color: T.colors.danger,
    fontSize: '0.75rem',
    flex: 1,
  } as React.CSSProperties,
  cancelBtn: {
    ...T.btnGhost,
    padding: '0.4rem 0.875rem',
    fontSize: '0.875rem',
  } as React.CSSProperties,
  submitBtn: {
    ...T.btnPrimary,
  } as React.CSSProperties,
};
