import { useUnblockTask, useUnignoreTask } from '../../shared/hooks/useApi';
import { formatTimestamp } from '../../shared/format';
import { useClickableProps } from '../../shared/ui/Clickable';
import { StatusChip } from '../../shared/ui/StatusChip';
import { rowStyles, cardStyles } from './itemStyles';
import type { TaskItemProps } from './types';

export function TaskCard({ task, confirmingId, stoppingIds, onKillClick, onKillConfirm, onKillCancel, onRowClick }: TaskItemProps) {
  const isStopping = stoppingIds.has(task.id) && task.status === 'in_progress';
  const cwdShort = task.cwd ? (task.cwd.split('/').pop() ?? task.cwd) : '—';
  const isConfirming = confirmingId === task.id;
  const killEligible = new Set(['in_progress', 'blocked', 'open', 'ready']).has(task.status);
  const coderModelStr = [task.coder, task.model].filter(Boolean).join(' · ');
  const isBlocked = task.status === 'blocked';
  const unblockTask = useUnblockTask();
  const unignoreTask = useUnignoreTask();
  const cardClick = useClickableProps(() => onRowClick(task.id));

  return (
    <div
      style={cardStyles.card}
      className="row-interactive"
      {...cardClick}
    >
      <div style={cardStyles.cardHead}>
        <StatusChip status={task.status} stopping={isStopping} width="auto" />
        <span style={cardStyles.cardId}>{task.id}</span>
        <span style={cardStyles.cardActions}>
          {isBlocked && (
            <button style={rowStyles.unblockBtn} onClick={(e) => { e.stopPropagation(); unblockTask.mutate({ id: task.id }); }}>Unblock</button>
          )}
          {isBlocked && task.ignored && (
            <button style={rowStyles.unblockBtn} onClick={(e) => { e.stopPropagation(); unignoreTask.mutate(task.id); }}>Unignore</button>
          )}
          {killEligible && !isConfirming && !isStopping && (
            <button style={rowStyles.killBtn} onClick={(e) => { e.stopPropagation(); onKillClick(task.id); }}>Kill</button>
          )}
          {isStopping && <span style={rowStyles.stoppingLabel}>stopping…</span>}
          {isConfirming && (
            <span style={rowStyles.confirm}>
              <button style={rowStyles.yesBtn} onClick={(e) => { e.stopPropagation(); onKillConfirm(task.id); }}>Yes</button>
              <button style={rowStyles.cancelBtn} onClick={(e) => { e.stopPropagation(); onKillCancel(); }}>No</button>
            </span>
          )}
        </span>
      </div>
      <div style={cardStyles.cardTitle}>{task.title}</div>
      {task.description && <div style={cardStyles.cardDesc}>{task.description}</div>}
      {isBlocked && (
        <div style={rowStyles.blockedReason} title={task.blocked_reason ?? 'No recorded reason'}>
          {task.blocked_reason ?? 'No recorded reason'}
        </div>
      )}
      {task.ignored && (
        <div style={rowStyles.ignoredBadge} title={`Triage ignored until ${task.ignore_until ?? '—'}`}>
          ignored until {task.ignore_until ?? '—'}
        </div>
      )}
      <div style={cardStyles.cardMeta}>
        <span style={cardStyles.cardMetaText}>{coderModelStr || '(default)'}</span>
        <span style={cardStyles.cardMetaText}>{formatTimestamp(task.started_at)}</span>
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
