import { useEffect, useState } from 'react';
import { Command } from 'cmdk';
import { useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { api } from '../../api';
import { usePauseSupervisor, useResumeSupervisor } from '../../hooks/useApi';
import type { SearchResult, TaskSummary } from '../../types';

interface Props {
  open: boolean;
  setOpen: (v: boolean) => void;
  onCreateTask: () => void;
}

export function CommandPalette({ open, setOpen, onCreateTask }: Props) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const pauseSupervisor = usePauseSupervisor();
  const resumeSupervisor = useResumeSupervisor();
  const [inputValue, setInputValue] = useState('');
  const [debouncedQuery, setDebouncedQuery] = useState('');
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  const [searching, setSearching] = useState(false);

  useEffect(() => {
    if (!open) {
      setInputValue('');
      setDebouncedQuery('');
      setSearchResults([]);
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

  useEffect(() => {
    if (!debouncedQuery) {
      setSearchResults([]);
      return;
    }
    setSearching(true);
    api.search(debouncedQuery)
      .then(results => setSearchResults(results))
      .catch(() => setSearchResults([]))
      .finally(() => setSearching(false));
  }, [debouncedQuery]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, setOpen]);

  const cachedTasks = (qc.getQueryData<TaskSummary[]>(['tasks']) ?? []).filter(t =>
    !inputValue ||
    t.title?.toLowerCase().includes(inputValue.toLowerCase()) ||
    t.id.toLowerCase().includes(inputValue.toLowerCase()),
  );

  const go = (path: string) => {
    navigate(path);
    setOpen(false);
  };

  const actions = [
    { id: 'create', label: 'Create new task', run: () => { onCreateTask(); setOpen(false); } },
    { id: 'analytics', label: 'Go to Analytics', run: () => go('/analytics') },
    { id: 'config', label: 'Go to Config', run: () => go('/config') },
    {
      id: 'pause', label: 'Pause supervisor', run: () => {
        void pauseSupervisor.mutateAsync().catch(() => null);
        setOpen(false);
      },
    },
    {
      id: 'resume', label: 'Resume supervisor', run: () => {
        void resumeSupervisor.mutateAsync().catch(() => null);
        setOpen(false);
      },
    },
  ];

  if (!open) return null;

  return (
    <div style={s.backdrop} onClick={() => setOpen(false)}>
      <div style={s.panel} onClick={e => e.stopPropagation()}>
        <Command shouldFilter={false} style={s.command}>
          <div style={s.inputWrap}>
            <Command.Input
              autoFocus
              value={inputValue}
              onValueChange={setInputValue}
              placeholder="Jump to task, run action, or search…"
              style={s.input}
            />
          </div>
          <Command.List style={s.list}>
            {cachedTasks.length > 0 && (
              <Command.Group>
                <div style={s.groupHeading}>Jump to task</div>
                {cachedTasks.slice(0, 8).map(t => (
                  <Command.Item
                    key={t.id}
                    value={t.id}
                    style={s.item}
                    onSelect={() => go(`/tasks/${t.id}`)}
                    className="cmd-item"
                  >
                    <span style={s.itemLabel}>{t.title ?? t.id}</span>
                    <span style={s.itemMeta}>{t.id}</span>
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
            {(searchResults.length > 0 || searching) && (
              <Command.Group>
                <div style={s.groupHeading}>
                  Search{searching ? ' …' : ''}
                </div>
                {searchResults.map((r, i) => (
                  <Command.Item
                    key={`${r.task_id}-${i}`}
                    value={`search-${i}`}
                    style={s.item}
                    onSelect={() => go(`/tasks/${r.task_id}`)}
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
      </div>
    </div>
  );
}

const s = {
  backdrop: {
    position: 'fixed' as const,
    inset: 0,
    background: 'rgba(0,0,0,0.55)',
    zIndex: 2000,
    display: 'flex',
    alignItems: 'flex-start',
    justifyContent: 'center',
    paddingTop: '18vh',
  },
  panel: {
    width: 560,
    maxHeight: '60vh',
    background: '#18181b',
    border: '1px solid #3f3f46',
    borderRadius: 8,
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
    borderBottom: '1px solid #27272a',
    padding: '0.625rem 1rem',
  },
  input: {
    width: '100%',
    background: 'transparent',
    border: 'none',
    outline: 'none',
    color: '#e4e4e7',
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
    color: '#52525b',
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
    color: '#e4e4e7',
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
    color: '#52525b',
    flexShrink: 0,
    maxWidth: '200px',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
  },
  empty: {
    padding: '0.75rem 1rem',
    fontSize: '0.875rem',
    color: '#52525b',
    textAlign: 'center' as const,
  },
};
