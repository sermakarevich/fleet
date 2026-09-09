// Close / Reopen / remove-assignee controls for one worker, driven by
// the bead payload. Rendered in the worker detail header; every action
// confirms through the shared Confirm (no window.confirm).
import { useState } from 'react';
import type { BeadDetail } from '../../../shared/types';
import * as T from '../../../shared/styles/tokens';
import { useCloseTask, useRemoveAssignee, useSetBeadStatus } from '../../../shared/hooks/useApi';
import { Confirm } from '../../../shared/ui/Confirm';

interface Props {
  taskId: string;
  bead: BeadDetail | undefined;
}

type Confirming = 'close' | 'reopen' | 'unassign' | null;

// Two-step buttons: first click arms the Confirm, Confirm fires the hook.
export function WorkerStatusControls({ taskId, bead }: Props) {
  const closeTask = useCloseTask();
  const setBeadStatus = useSetBeadStatus();
  const removeAssignee = useRemoveAssignee();
  const [confirming, setConfirming] = useState<Confirming>(null);
  const busy = closeTask.isPending || setBeadStatus.isPending || removeAssignee.isPending;
  const isClosed = (bead?.status ?? '') === 'closed';

  function confirmButton(verb: Exclude<Confirming, null>, run: () => void, danger: boolean) {
    return (
      <Confirm
        verb={verb === 'unassign' ? 'Remove assignee' : verb === 'close' ? 'Close' : 'Reopen'}
        onConfirm={() => { setConfirming(null); run(); }}
        onCancel={() => setConfirming(null)}
        danger={danger}
      />
    );
  }

  return (
    <div style={styles.controls}>
      {!isClosed && confirming !== 'close' && (
        <button style={styles.closeBtn} disabled={busy} onClick={() => setConfirming('close')}>
          Close
        </button>
      )}
      {!isClosed && confirming === 'close' &&
        confirmButton('close', () => closeTask.mutate(taskId), true)}
      {isClosed && confirming !== 'reopen' && (
        <button style={styles.reopenBtn} disabled={busy} onClick={() => setConfirming('reopen')}>
          Reopen
        </button>
      )}
      {isClosed && confirming === 'reopen' &&
        confirmButton('reopen', () => setBeadStatus.mutate({ id: taskId, status: 'open' }), false)}
      {bead?.assignee && confirming !== 'unassign' && (
        <button style={styles.unassignBtn} disabled={busy} onClick={() => setConfirming('unassign')}>
          Remove assignee
        </button>
      )}
      {bead?.assignee && confirming === 'unassign' &&
        confirmButton('unassign', () => removeAssignee.mutate(taskId), false)}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  controls: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
    flexWrap: 'wrap',
    marginTop: '0.5rem',
  },
  closeBtn: {
    padding: '0.2rem 0.625rem',
    background: 'transparent',
    border: `1px solid ${T.colors.danger}`,
    borderRadius: '0.25rem',
    color: T.colors.danger,
    cursor: 'pointer',
    fontSize: '0.75rem',
    fontWeight: 600,
    fontFamily: 'system-ui, sans-serif',
  },
  reopenBtn: {
    padding: '0.2rem 0.625rem',
    background: 'transparent',
    border: `1px solid ${T.colors.info}`,
    borderRadius: '0.25rem',
    color: T.colors.link,
    cursor: 'pointer',
    fontSize: '0.75rem',
    fontWeight: 600,
    fontFamily: 'system-ui, sans-serif',
  },
  unassignBtn: {
    padding: '0.2rem 0.625rem',
    background: 'transparent',
    border: `1px solid ${T.colors.stoneWarm}`,
    borderRadius: '0.25rem',
    color: T.colors.stone,
    cursor: 'pointer',
    fontSize: '0.75rem',
    fontFamily: 'system-ui, sans-serif',
  },
};
