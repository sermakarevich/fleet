/**
 * Slide-over detail view for one trigger (a schedule): definition,
 * upcoming firings and run history, with Run now / enable-disable / edit
 * / delete actions. Called by TriggerTable when a row is selected.
 */
import { useState } from 'react';
import {
  useDeleteSchedule,
  useRunSchedule,
  useSchedule,
  useSetScheduleEnabled,
  useWorkflows,
} from '../../shared/hooks/useApi';
import * as T from '../../shared/styles/tokens';
import * as R from '../../shared/styles/recipes';
import { Modal } from '../../shared/ui/Modal';
import { Confirm } from '../../shared/ui/Confirm';
import { LoadingState } from '../../shared/ui/LoadingState';
import type { TriggerTarget } from './types';
import { TriggerDrawerBody } from './TriggerDrawerBody';
import { TriggerForm } from './TriggerForm';

// Row of action buttons under the title: run, enable, edit, delete.
function DrawerActions({
  scheduleId, enabled, onEdit, onDeleted,
}: {
  scheduleId: string; enabled: boolean; onEdit: () => void; onDeleted: () => void;
}) {
  const runSchedule = useRunSchedule();
  const setEnabled = useSetScheduleEnabled();
  const deleteSchedule = useDeleteSchedule();
  const [confirmDelete, setConfirmDelete] = useState(false);

  function handleDelete() {
    void deleteSchedule.mutateAsync(scheduleId).then(onDeleted);
  }

  return (
    <div style={styles.actionsRow}>
      <button
        style={styles.runBtn}
        disabled={runSchedule.isPending}
        onClick={() => runSchedule.mutate(scheduleId)}
      >
        {runSchedule.isPending ? 'Starting…' : 'Run now'}
      </button>
      <button
        style={styles.ghostBtn}
        disabled={setEnabled.isPending}
        onClick={() => setEnabled.mutate({ id: scheduleId, enabled: !enabled })}
      >
        {enabled ? 'Disable' : 'Enable'}
      </button>
      <button style={styles.ghostBtn} onClick={onEdit}>
        Edit
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
          disabled={deleteSchedule.isPending}
          onClick={() => setConfirmDelete(true)}
        >
          Delete
        </button>
      )}
    </div>
  );
}

// Drawer shell: header, actions, body sections and the edit form.
export function TriggerDrawer({
  target, scheduleId, onClose,
}: {
  target: TriggerTarget; scheduleId: string; onClose: () => void;
}) {
  const { data: schedule, isLoading, error } = useSchedule(scheduleId);
  const { data: workflows } = useWorkflows();
  const [showEdit, setShowEdit] = useState(false);

  const workflowName = schedule?.workflow_id
    ? (workflows ?? []).find((w) => w.id === schedule.workflow_id)?.name ?? schedule.workflow_id
    : null;

  return (
    <Modal labelledBy="trigger-drawer-title" onClose={onClose} placement="right" panelStyle={R.drawerStyle()}>
      <div style={styles.header}>
        <span id="trigger-drawer-title" style={styles.id}>{scheduleId}</span>
        <button style={styles.closeBtn} onClick={onClose} title="Close" aria-label="Close">✕</button>
      </div>
      <div style={styles.body}>
        {isLoading && <LoadingState />}
        {error && <p style={R.errorMsgStyle()}>Error: {String(error)}</p>}
        {schedule && (
          <>
            <DrawerActions
              scheduleId={scheduleId}
              enabled={schedule.enabled}
              onEdit={() => setShowEdit(true)}
              onDeleted={onClose}
            />
            <TriggerDrawerBody schedule={schedule} target={target} workflowName={workflowName} />
          </>
        )}
      </div>
      {showEdit && schedule && (
        <TriggerForm
          target={target}
          initial={schedule}
          onClose={() => setShowEdit(false)}
          onSaved={() => undefined}
        />
      )}
    </Modal>
  );
}

const styles = {
  header: {
    display: 'flex', alignItems: 'center', justifyContent: 'space-between',
    padding: '0.625rem 1rem', borderBottom: `1px solid ${T.colors.borderSubtle}`, flexShrink: 0,
  } as React.CSSProperties,
  id: {
    fontFamily: 'monospace', color: T.colors.link, fontSize: '0.875rem', fontWeight: 600,
  } as React.CSSProperties,
  closeBtn: {
    background: 'transparent', border: 'none', color: T.colors.textSecondary,
    cursor: 'pointer', fontSize: '1rem', lineHeight: 1, padding: '0.25rem',
  } as React.CSSProperties,
  body: {
    padding: '1rem', overflowY: 'auto' as const, flex: 1,
  } as React.CSSProperties,
  actionsRow: {
    display: 'flex', alignItems: 'center', gap: '0.5rem',
    flexWrap: 'wrap' as const, marginBottom: '1.25rem',
  } as React.CSSProperties,
  runBtn: {
    ...T.btnPrimary, padding: '0.3rem 0.75rem', fontSize: '0.8125rem',
  } as React.CSSProperties,
  ghostBtn: {
    ...T.btnGhost, padding: '0.3rem 0.75rem', fontSize: '0.8125rem',
  } as React.CSSProperties,
  deleteBtn: {
    ...T.btnDanger, padding: '0.3rem 0.75rem', fontSize: '0.8125rem',
  } as React.CSSProperties,
};
