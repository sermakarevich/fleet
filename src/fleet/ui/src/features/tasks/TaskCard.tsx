import { useUnblockTask } from '../../shared/hooks/useApi';
import { fmtTs } from '../../shared/format';
import { chipFor } from './statusChip';
import { styles, cardStyles } from './itemStyles';
import type { TaskRowProps } from './TaskRow';

export function TaskCard({ task, confirmingId, stoppingIds, onKillClick, onKillConfirm, onKillCancel, onRowClick }: TaskRowProps) {
  const isStopping = stoppingIds.has(task.id) && task.status === 'in_progress';
  const chip = chipFor(task.status, isStopping);
  const cwdShort = task.cwd ? (task.cwd.split('/').pop() ?? task.cwd) : '—';
  const isConfirming = confirmingId === task.id;
  const killEligible = new Set(['in_progress', 'blocked', 'open', 'ready']).has(task.status);
  const coderModelStr = [task.coder, task.model].filter(Boolean).join(' · ');
  const isBlocked = task.status === 'blocked';
  const unblockTask = useUnblockTask();

  return (
    <div
      style={cardStyles.card}
      className="row-interactive"
      tabIndex={0}
      onClick={() => onRowClick(task.id)}
    >
      <div style={cardStyles.cardHead}>
        <span style={{ ...styles.chip, ...cardStyles.chipInCard, background: chip.bg, color: chip.fg }}>
          {chip.label}
        </span>
        <span style={cardStyles.cardId}>{task.id}</span>
        <span style={cardStyles.cardActions} onClick={e => e.stopPropagation()}>
          {isBlocked && (
            <button style={styles.unblockBtn} onClick={() => unblockTask.mutate({ id: task.id })}>Unblock</button>
          )}
          {killEligible && !isConfirming && !isStopping && (
            <button style={styles.killBtn} onClick={() => onKillClick(task.id)}>Kill</button>
          )}
          {isStopping && <span style={styles.stoppingLabel}>stopping…</span>}
          {isConfirming && (
            <span style={styles.confirm}>
              <button style={styles.yesBtn} onClick={() => onKillConfirm(task.id)}>Yes</button>
              <button style={styles.cancelBtn} onClick={onKillCancel}>No</button>
            </span>
          )}
        </span>
      </div>
      <div style={cardStyles.cardTitle}>{task.title}</div>
      {task.description && <div style={cardStyles.cardDesc}>{task.description}</div>}
      {isBlocked && (
        <div style={styles.blockedReason} title={task.blocked_reason ?? 'No recorded reason'}>
          {task.blocked_reason ?? 'No recorded reason'}
        </div>
      )}
      <div style={cardStyles.cardMeta}>
        <span style={cardStyles.cardMetaText}>{coderModelStr || '(default)'}</span>
        <span style={cardStyles.cardMetaText}>{fmtTs(task.started_at)}</span>
        <span style={cardStyles.cardMetaText} title={task.cwd ?? undefined}>{cwdShort}</span>
      </div>
      {task.restarts > 0 && (
        <div style={cardStyles.cardMetaText} title={`Last: ${task.last_outcome ?? '—'} → ${task.last_action ?? '—'}: ${task.last_outcome_reason ?? '—'}`}>
          Runs: {task.restarts + 1} · last: {task.last_outcome ?? '—'} → {task.last_action ?? '—'}: {task.last_outcome_reason ?? '—'}
        </div>
      )}
    </div>
  );
}
