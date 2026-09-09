// Event-trigger table for the Triggered sub-tab (ADR 0011): every saved
// trigger with its source, enabled toggle, policy, firing counts and row
// actions. Owns the drawer (?trigger=) and create form (?new=1) through
// the URL, mirroring TriggerTable (?schedule=). Rendered by WorkersPage.
import { useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useDeleteTrigger, useSetTriggerEnabled, useTriggers } from '../../shared/hooks/useApi';
import { formatShortDateTime as fmtTs } from '../../shared/format';
import * as T from '../../shared/styles/tokens';
import * as R from '../../shared/styles/recipes';
import { Confirm } from '../../shared/ui/Confirm';
import { DataList, type DataColumn } from '../../shared/ui/DataList';
import { LoadingState } from '../../shared/ui/LoadingState';
import type { EventTrigger } from './types';
import { EnabledDot } from './triggerColumns';
import { EventTriggerDrawer } from './EventTriggerDrawer';
import { EventTriggerForm } from './EventTriggerForm';

// Patch the URL params (selection, create form) without touching the tab.
function useParamPatch() {
  const [searchParams, setSearchParams] = useSearchParams();
  const selectedId = searchParams.get('trigger');
  const showCreate = searchParams.get('new') === '1';
  function patch(next: Record<string, string>) {
    const params = new URLSearchParams(searchParams);
    for (const [k, v] of Object.entries(next)) {
      if (v) params.set(k, v);
      else params.delete(k);
    }
    setSearchParams(params, { replace: true });
  }
  return { selectedId, showCreate, patch };
}

// Clicking a button inside a row must not select the row.
function stop(e: React.MouseEvent) {
  e.stopPropagation();
}

// Row actions: enable/disable toggle, preview (opens the drawer) and
// delete with an inline confirm. Each button stops row-click selection.
function RowActions({ trigger, onPreview }: { trigger: EventTrigger; onPreview: () => void }) {
  const setEnabled = useSetTriggerEnabled();
  const deleteTrigger = useDeleteTrigger();
  const [confirmDelete, setConfirmDelete] = useState(false);

  function handleDelete() {
    void deleteTrigger.mutateAsync(trigger.id);
  }

  return (
    <span style={styles.actions}>
      <button
        style={styles.ghostBtn}
        disabled={setEnabled.isPending}
        onClick={(e) => { stop(e); setEnabled.mutate({ id: trigger.id, enabled: !trigger.enabled }); }}
        title={trigger.enabled ? 'Disable' : 'Enable'}
      >
        {trigger.enabled ? 'Disable' : 'Enable'}
      </button>
      <button style={styles.ghostBtn} onClick={(e) => { stop(e); onPreview(); }} title="Preview">
        Preview
      </button>
      {confirmDelete ? (
        <Confirm
          verb="Delete"
          onConfirm={handleDelete}
          onCancel={() => setConfirmDelete(false)}
        />
      ) : (
        <button
          style={styles.deleteBtn}
          disabled={deleteTrigger.isPending}
          onClick={(e) => { stop(e); setConfirmDelete(true); }}
          title="Delete"
        >
          Delete
        </button>
      )}
    </span>
  );
}

// Desktop columns plus the shared mobile card body for one event trigger.
export function eventTriggerColumns(onPreview: (trigger: EventTrigger) => void): Array<DataColumn<EventTrigger>> {
  return [
    {
      key: 'enabled', header: 'Enabled', width: '4rem',
      render: (trigger) => (
        <span style={styles.enabledCell}>
          <EnabledDot enabled={trigger.enabled} />
          {trigger.enabled ? 'on' : 'off'}
        </span>
      ),
    },
    {
      key: 'name', header: 'Name',
      render: (trigger) => <span style={R.titleCellStyle()} title={trigger.name}>{trigger.name}</span>,
    },
    {
      key: 'source', header: 'Source', width: '9rem',
      render: (trigger) => (
        <span style={R.merge(R.monoStyle(), styles.cell)} title={trigger.source}>
          {trigger.source}
        </span>
      ),
    },
    {
      key: 'max_open', header: 'Max open', width: '5rem',
      render: (trigger) => <span style={styles.runsCell}>{trigger.max_open}</span>,
    },
    {
      key: 'firings', header: 'Firings', width: '4rem',
      render: (trigger) => <span style={styles.runsCell}>{trigger.firing_count}</span>,
    },
    {
      key: 'last', header: 'Last fired', width: '9rem',
      render: (trigger) => (
        <span style={styles.cell}>
          {trigger.last_fired_at ? fmtTs(trigger.last_fired_at) : <span style={R.dimStyle()}>never</span>}
        </span>
      ),
    },
    {
      key: 'actions', header: 'Actions', width: 'auto',
      render: (trigger) => <RowActions trigger={trigger} onPreview={() => onPreview(trigger)} />,
    },
  ];
}

// Mobile card body for one event trigger (DataList wraps it in the shell).
export function EventTriggerCard({ trigger }: { trigger: EventTrigger }) {
  return (
    <>
      <div style={R.cardHeadStyle()}>
        <EnabledDot enabled={trigger.enabled} />
        <span style={R.cardTitleStyle()} title={trigger.name}>{trigger.name}</span>
        <span style={R.cardMetaTextStyle()}>{trigger.firing_count} firing{trigger.firing_count === 1 ? '' : 's'}</span>
      </div>
      <div style={R.cardMetaStyle()}>
        <span style={R.merge(R.monoStyle(), R.cardMetaTextStyle())}>{trigger.source}</span>
        <span style={R.cardMetaTextStyle()}>max open {trigger.max_open}</span>
      </div>
      <div style={R.cardMetaStyle()}>
        <span style={R.cardMetaTextStyle()}>
          Last fired: {trigger.last_fired_at ? fmtTs(trigger.last_fired_at) : 'never'}
        </span>
      </div>
    </>
  );
}

// Event-trigger list with drawer and create form, owned by the URL.
export function EventTriggerTable() {
  const { data: triggers, isLoading, error } = useTriggers();
  const { selectedId, showCreate, patch } = useParamPatch();

  if (error) {
    return <p style={styles.error}>Error: {String(error)}</p>;
  }

  const items = triggers ?? [];
  const columns = eventTriggerColumns((trigger) => patch({ trigger: trigger.id }));

  return (
    <div>
      <div style={styles.actionsBar}>
        <button style={T.btnPrimary} onClick={() => patch({ new: '1' })}>
          + New trigger
        </button>
      </div>
      {isLoading ? (
        <LoadingState />
      ) : (
        <DataList
          columns={columns}
          rows={items}
          rowKey={(trigger) => trigger.id}
          onRowClick={(trigger) => patch({ trigger: trigger.id })}
          renderCard={(trigger) => <EventTriggerCard trigger={trigger} />}
          selectedKey={selectedId ?? null}
          empty="No event triggers yet. Create one to start a worker on a signal."
        />
      )}
      {selectedId && (
        <EventTriggerDrawer
          triggerId={selectedId}
          onClose={() => patch({ trigger: '' })}
        />
      )}
      {showCreate && (
        <EventTriggerForm
          onClose={() => patch({ new: '' })}
          onSaved={(saved) => patch({ new: '', trigger: saved.id })}
        />
      )}
    </div>
  );
}

const styles = {
  actionsBar: {
    display: 'flex', justifyContent: 'flex-end', marginBottom: '0.75rem',
  } as React.CSSProperties,
  error: {
    padding: '1rem', color: T.colors.danger, fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  enabledCell: {
    display: 'inline-flex', alignItems: 'center', gap: '0.375rem',
    fontSize: '0.8125rem', color: T.colors.textSecondary,
  } as React.CSSProperties,
  cell: {
    fontSize: '0.8125rem', color: T.colors.textSecondary,
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  runsCell: {
    fontSize: '0.8125rem', color: T.colors.textSecondary, textAlign: 'right' as const,
  } as React.CSSProperties,
  actions: {
    display: 'inline-flex', alignItems: 'center', gap: '0.375rem',
  } as React.CSSProperties,
  ghostBtn: {
    ...T.btnGhost, padding: '0.2rem 0.5rem', fontSize: '0.75rem',
  } as React.CSSProperties,
  deleteBtn: {
    ...T.btnDanger, padding: '0.2rem 0.5rem', fontSize: '0.75rem',
  } as React.CSSProperties,
};
