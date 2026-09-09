import { useEffect, useState } from 'react';
import { Command } from 'cmdk';
import { useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { errorMessage } from '../../shared/api';
import { Modal } from '../../shared/ui/Modal';
import { usePauseSupervisor, useResumeSupervisor, useSearch } from '../../shared/hooks/useApi';
import type { TaskSummary } from '../../shared/types';
import * as T from '../../shared/styles/tokens';

interface Props {
  open: boolean;
  setOpen: (v: boolean) => void;
  onCreateWorker: () => void;
}

export function CommandPalette({ open, setOpen, onCreateWorker }: Props) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const pauseSupervisor = usePauseSupervisor();
  const resumeSupervisor = useResumeSupervisor();
  const [inputValue, setInputValue] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');
  // "New schedule" asks for the target first (ADR 0009 shared triggers).
  const [pickTarget, setPickTarget] = useState(false);

  useEffect(() => {
    if (!open) {
      setInputValue('');
      setDebouncedQuery('');
      setPickTarget(false);
    }
  }, [open]);

  useEffect(() => {
    if (inputValue.length < 3) {
      setDebouncedQuery('');
      return;
    }
    const timer = setTimeout(() => setDebouncedQuery(inputValue), 300);
    return () => clearTimeout(timer);
  }, [inputValue]);

  const {
    data: searchResults = [],
    isFetching: searching,
    isError: searchFailed,
    error: searchError,
  } = useSearch(debouncedQuery);

  const cachedTasks = (qc.getQueryData<TaskSummary[]>(['tasks']) ?? []).filter(t =>
    !inputValue ||
    t.title?.toLowerCase().includes(inputValue.toLowerCase()) ||
    t.id.toLowerCase().includes(inputValue.toLowerCase()),
  );

  // Jump to a worker/bead id that is not in the list cache (e.g. a closed
  // bead beyond the Runs history window): the detail page loads any id.
  const trimmedInput = inputValue.trim();
  const exactMatch = cachedTasks.some(t => t.id === trimmedInput);

  const go = (path: string) => {
    navigate(path);
    setOpen(false);
  };

  // New-schedule target picker: worker vs workflow, then straight into
  // the matching Scheduled sub-tab with the create form open.
  const targetActions = [
    { id: 'new-schedule-worker', label: 'Schedule a worker', run: () => go('/workers?tab=scheduled&new=1') },
    { id: 'new-schedule-workflow', label: 'Schedule a workflow', run: () => go('/workflows?tab=scheduled&new=1') },
  ];

  const actions = [
    { id: 'create', label: 'New worker', run: () => { onCreateWorker(); setOpen(false); } },
    { id: 'workers', label: 'Go to workers', run: () => go('/workers') },
    { id: 'scheduled-workers', label: 'Scheduled workers', run: () => go('/workers?tab=scheduled') },
    { id: 'scheduled-workflows', label: 'Scheduled workflows', run: () => go('/workflows?tab=scheduled') },
    { id: 'new-schedule', label: 'New schedule…', run: () => setPickTarget(true) },
    { id: 'workflows', label: 'Go to Workflows', run: () => go('/workflows') },
    { id: 'inbox', label: 'Go to Inbox', run: () => go('/inbox') },
    { id: 'workflow-runs', label: 'Go to workflow runs', run: () => go('/workflows?tab=runs') },
    { id: 'create-workflow', label: 'Create new workflow', run: () => go('/workflows/new') },
    { id: 'analytics', label: 'Go to Analytics', run: () => go('/analytics') },
    { id: 'config', label: 'Go to Config', run: () => go('/config') },
    {
      id: 'pause', label: 'Pause supervisor', run: () => {
        pauseSupervisor.mutate();
        setOpen(false);
      },
    },
    {
      id: 'resume', label: 'Resume supervisor', run: () => {
        resumeSupervisor.mutate();
        setOpen(false);
      },
    },
  ];

  if (!open) return null;

  return (
    <Modal labelledBy="cmd-palette-title" onClose={() => setOpen(false)} panelStyle={s.panel}>
      <h2 id="cmd-palette-title" style={s.srOnly}>Command palette</h2>
      <Command shouldFilter={false} style={s.command}>
          <div style={s.inputWrap}>
            <Command.Input
              value={inputValue}
              onValueChange={setInputValue}
              placeholder="Jump to worker, run action, or search…"
              style={s.input}
            />
          </div>
          <Command.List style={s.list}>
            {cachedTasks.length > 0 && (
              <Command.Group>
                <div style={s.groupHeading}>Jump to worker</div>
                {cachedTasks.slice(0, 8).map(t => (
                  <Command.Item
                    key={t.id}
                    value={t.id}
                    style={s.item}
                    onSelect={() => go(`/workers/${t.id}`)}
                    className="cmd-item"
                  >
                    <span style={s.itemLabel}>{t.title ?? t.id}</span>
                    <span style={s.itemMeta}>{t.id}</span>
                  </Command.Item>
                ))}
              </Command.Group>
            )}
            {trimmedInput && !exactMatch && (
              <Command.Group>
                <div style={s.groupHeading}>Jump to worker by id</div>
                <Command.Item
                  key={`jump-${trimmedInput}`}
                  value={`jump-${trimmedInput}`}
                  style={s.item}
                  onSelect={() => go(`/workers/${trimmedInput}`)}
                  className="cmd-item"
                >
                  <span style={s.itemLabel}>Go to worker {trimmedInput}</span>
                </Command.Item>
              </Command.Group>
            )}
            {pickTarget && (
              <Command.Group>
                <div style={s.groupHeading}>New schedule for…</div>
                {targetActions.map(a => (
                  <Command.Item
                    key={a.id}
                    value={a.id}
                    style={s.item}
                    onSelect={a.run}
                    className="cmd-item"
                  >
                    <span style={s.itemLabel}>{a.label}</span>
                  </Command.Item>
                ))}
              </Command.Group>
            )}
            <Command.Group>
              <div style={s.groupHeading}>Actions</div>
              {actions.map(a => (
                <Command.Item
                  key={a.id}
                  value={a.id}
                  style={s.item}
                  onSelect={a.run}
                  className="cmd-item"
                >
                  <span style={s.itemLabel}>{a.label}</span>
                </Command.Item>
              ))}
            </Command.Group>
            {(searchResults.length > 0 || searching || searchFailed) && (
              <Command.Group>
                <div style={s.groupHeading}>
                  Search{searching ? ' …' : ''}
                </div>
                {searchFailed && (
                  <div style={s.error}>Search failed: {errorMessage(searchError)}</div>
                )}
                {searchResults.map((r, i) => (
                  <Command.Item
                    key={`${r.task_id}-${i}`}
                    value={`search-${i}`}
                    style={s.item}
                    onSelect={() => go(`/workers/${r.task_id}`)}
                    className="cmd-item"
                  >
                    <span style={s.itemLabel}>{r.task_title}</span>
                    <span style={s.itemMeta}>
                      [{r.source}] {r.match_context.slice(0, 60)}
                    </span>
                  </Command.Item>
                ))}
              </Command.Group>
            )}
            {cachedTasks.length === 0 && searchResults.length === 0 && !searching && inputValue && (
              <Command.Empty style={s.empty}>No results found</Command.Empty>
            )}
          </Command.List>
      </Command>
    </Modal>
  );
}

const s = {
  srOnly: {
    position: 'absolute' as const,
    width: 1,
    height: 1,
    padding: 0,
    margin: -1,
    overflow: 'hidden',
    clip: 'rect(0, 0, 0, 0)',
    whiteSpace: 'nowrap' as const,
    borderWidth: 0,
  },
  panel: {
    width: 560,
    maxHeight: '60vh',
    background: T.colors.bgSurface,
    border: `1px solid ${T.colors.border}`,
    borderRadius: '0.5rem',
    boxShadow: '0 24px 64px rgba(0,0,0,0.55)',
    overflow: 'hidden',
    display: 'flex',
    flexDirection: 'column' as const,
  },
  command: {
    display: 'flex',
    flexDirection: 'column' as const,
    overflow: 'hidden',
    fontFamily: 'system-ui, sans-serif',
  },
  inputWrap: {
    borderBottom: `1px solid ${T.colors.borderSubtle}`,
    padding: '0.625rem 1rem',
  },
  input: {
    width: '100%',
    background: 'transparent',
    border: 'none',
    outline: 'none',
    color: T.colors.textPrimary,
    fontSize: '0.9375rem',
    fontFamily: 'system-ui, sans-serif',
  },
  list: {
    overflowY: 'auto' as const,
    maxHeight: '50vh',
    padding: '0.375rem 0',
  },
  groupHeading: {
    padding: '0.25rem 1rem',
    fontSize: '0.6875rem',
    fontWeight: 600,
    color: T.colors.textMuted,
    textTransform: 'uppercase' as const,
    letterSpacing: '0.06em',
    marginTop: '0.25rem',
  },
  item: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '0.45rem 1rem',
    cursor: 'pointer',
    borderRadius: 0,
    fontSize: '0.875rem',
    color: T.colors.textPrimary,
    gap: '0.75rem',
  },
  itemLabel: {
    flex: 1,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
  },
  itemMeta: {
    fontSize: '0.75rem',
    color: T.colors.textMuted,
    flexShrink: 0,
    maxWidth: '200px',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
  },
  empty: {
    padding: '0.75rem 1rem',
    fontSize: '0.875rem',
    color: T.colors.textMuted,
    textAlign: 'center' as const,
  },
  error: {
    padding: '0.5rem 1rem',
    fontSize: '0.8125rem',
    color: T.colors.diffRemoveFg,
  },
};
