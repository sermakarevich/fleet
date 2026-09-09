import { useUnblockTask, useUnignoreTask } from '../../shared/hooks/useApi';
import type { TaskSummary } from '../../shared/types';
import type { TaskItemProps } from './types';
import { formatTimestamp, formatTokens, formatContextTitle } from '../../shared/format';
import * as R from '../../shared/styles/recipes';
import { useClickableProps } from '../../shared/ui/Clickable';
import { StatusChip } from '../../shared/ui/StatusChip';
import { rowStyles } from './itemStyles';

const KILL_ELIGIBLE = new Set(['in_progress', 'blocked', 'open', 'ready']);

function runsTitle(task: TaskSummary): string {
  return `Last: ${task.last_outcome ?? '—'} → ${task.last_action ?? '—'}: ${task.last_outcome_reason ?? '—'}`;
}

export function TaskRow({ task, confirmingId, stoppingIds, onKillClick, onKillConfirm, onKillCancel, onRowClick }: TaskItemProps) {
  const isStopping = stoppingIds.has(task.id) && task.status === 'in_progress';
  const cwdShort = task.cwd ? (task.cwd.split('/').pop() ?? task.cwd) : '—';
  const isConfirming = confirmingId === task.id;
  const killEligible = KILL_ELIGIBLE.has(task.status);
  const coderModelStr = [task.coder, task.model].filter(Boolean).join(' · ');
  const isBlocked = task.status === 'blocked';
  const unblockTask = useUnblockTask();
  const unignoreTask = useUnignoreTask();
  // A lease whose lease_until already passed while the task still shows as
  // running: the heartbeat stopped (crashed runner, slept host). The
  // supervisor reclaims it once the pid is provably dead; until then flag it.
  const staleLease = task.status === 'in_progress'
    && task.lease != null
    && Number(new Date(task.lease.lease_until)) < Date.now();
  const rowClick = useClickableProps(() => onRowClick(task.id));

  return (
    <div style={R.rowStyle(false)} className="row-interactive" {...rowClick}>
      <StatusChip status={task.status} stopping={isStopping} />
      <span style={R.idCellStyle()}>{task.id}</span>
      <span style={rowStyles.titleCol}>
        <span style={rowStyles.titleText} title={task.title}>{task.title}</span>
        {task.description && (
          <span style={rowStyles.descText} title={task.description}>{task.description}</span>
        )}
        {isBlocked && (
          <span style={rowStyles.blockedReason} title={task.blocked_reason ?? 'No recorded reason'}>
            {task.blocked_reason ?? 'No recorded reason'}
          </span>
        )}
        {staleLease && (
          <span style={rowStyles.staleLeaseBadge} title={`Last heartbeat ${task.lease?.heartbeat_at ?? '—'}; lease until ${task.lease?.lease_until ?? '—'}`}>
            stale lease
          </span>
        )}
        {task.ignored && (
          <span style={rowStyles.ignoredBadge} title={`Triage ignored until ${task.ignore_until ?? '—'}`}>
            ignored
          </span>
        )}
      </span>
      <span style={rowStyles.coderCell}>
        {coderModelStr
          ? coderModelStr
          : <span style={R.dimStyle()}>(default)</span>}
      </span>
      <span style={rowStyles.contextCell} title={formatContextTitle(task.context_tokens, task.context_limit)}>{formatTokens(task.context_tokens, task.context_pct)}</span>
      <span style={rowStyles.runsCell}>
        {task.restarts > 0 ? (
          <span style={rowStyles.runsChip} title={runsTitle(task)}>{task.restarts + 1}</span>
        ) : (
          task.restarts + 1
        )}
      </span>
      <span style={rowStyles.tsCell}>{formatTimestamp(task.started_at)}</span>
      <span style={rowStyles.tsCell}>{formatTimestamp(task.ended_at)}</span>
      <span style={rowStyles.cwdCell} title={task.cwd ?? undefined}>{cwdShort}</span>
      <span style={rowStyles.actionCell}>
        {isBlocked && (
          <button style={rowStyles.unblockBtn} onClick={(e) => { e.stopPropagation(); unblockTask.mutate({ id: task.id }); }}>
            Unblock
          </button>
        )}
        {isBlocked && task.ignored && (
          <button style={rowStyles.unblockBtn} onClick={(e) => { e.stopPropagation(); unignoreTask.mutate(task.id); }}>
            Unignore
          </button>
        )}
        {killEligible && !isConfirming && !isStopping && (
          <button style={rowStyles.killBtn} onClick={(e) => { e.stopPropagation(); onKillClick(task.id); }}>
            Kill
          </button>
        )}
        {isStopping && (
          <span style={rowStyles.stoppingLabel}>stopping…</span>
        )}
        {isConfirming && (
          <span style={rowStyles.confirm}>
            <span style={rowStyles.confirmLabel}>Confirm kill?</span>
            <button style={rowStyles.yesBtn} onClick={(e) => { e.stopPropagation(); onKillConfirm(task.id); }}>Yes</button>
            <button style={rowStyles.cancelBtn} onClick={(e) => { e.stopPropagation(); onKillCancel(); }}>Cancel</button>
          </span>
        )}
      </span>
    </div>
  );
}
