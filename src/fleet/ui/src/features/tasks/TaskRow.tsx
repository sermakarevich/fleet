import { useUnblockTask, useUnignoreTask } from '../../shared/hooks/useApi';
import type { TaskSummary } from '../../shared/types';
import { fmtTs, fmtTokens, fmtContextTitle } from '../../shared/format';
import * as R from '../../shared/styles/recipes';
import { StatusChip } from '../../shared/ui/StatusChip';
import { styles } from './itemStyles';

const KILL_ELIGIBLE = new Set(['in_progress', 'blocked', 'open', 'ready']);

function runsTitle(task: TaskSummary): string {
  return `Last: ${task.last_outcome ?? '—'} → ${task.last_action ?? '—'}: ${task.last_outcome_reason ?? '—'}`;
}

export interface TaskRowProps {
  task: TaskSummary;
  confirmingId: string | null;
  stoppingIds: Set<string>;
  onKillClick: (id: string) => void;
  onKillConfirm: (id: string) => void;
  onKillCancel: () => void;
  onRowClick: (id: string) => void;
}

export function TaskRow({ task, confirmingId, stoppingIds, onKillClick, onKillConfirm, onKillCancel, onRowClick }: TaskRowProps) {
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

  return (
    <div style={R.rowStyle(false)} className="row-interactive" tabIndex={0} onClick={() => onRowClick(task.id)}>
      <StatusChip status={task.status} stopping={isStopping} />
      <span style={R.idCellStyle()}>{task.id}</span>
      <span style={styles.titleCol}>
        <span style={styles.titleText} title={task.title}>{task.title}</span>
        {task.description && (
          <span style={styles.descText} title={task.description}>{task.description}</span>
        )}
        {isBlocked && (
          <span style={styles.blockedReason} title={task.blocked_reason ?? 'No recorded reason'}>
            {task.blocked_reason ?? 'No recorded reason'}
          </span>
        )}
        {staleLease && (
          <span style={styles.staleLeaseBadge} title={`Last heartbeat ${task.lease?.heartbeat_at ?? '—'}; lease until ${task.lease?.lease_until ?? '—'}`}>
            stale lease
          </span>
        )}
        {task.ignored && (
          <span style={styles.ignoredBadge} title={`Triage ignored until ${task.ignore_until ?? '—'}`}>
            ignored
          </span>
        )}
      </span>
      <span style={styles.coderCell}>
        {coderModelStr
          ? coderModelStr
          : <span style={R.dimStyle()}>(default)</span>}
      </span>
      <span style={styles.contextCell} title={fmtContextTitle(task.context_tokens, task.context_limit)}>{fmtTokens(task.context_tokens, task.context_pct)}</span>
      <span style={styles.runsCell}>
        {task.restarts > 0 ? (
          <span style={styles.runsChip} title={runsTitle(task)}>{task.restarts + 1}</span>
        ) : (
          task.restarts + 1
        )}
      </span>
      <span style={styles.tsCell}>{fmtTs(task.started_at)}</span>
      <span style={styles.tsCell}>{fmtTs(task.ended_at)}</span>
      <span style={styles.cwdCell} title={task.cwd ?? undefined}>{cwdShort}</span>
      <span style={styles.actionCell} onClick={e => e.stopPropagation()}>
        {isBlocked && (
          <button style={styles.unblockBtn} onClick={() => unblockTask.mutate({ id: task.id })}>
            Unblock
          </button>
        )}
        {isBlocked && task.ignored && (
          <button style={styles.unblockBtn} onClick={() => unignoreTask.mutate(task.id)}>
            Unignore
          </button>
        )}
        {killEligible && !isConfirming && !isStopping && (
          <button style={styles.killBtn} onClick={() => onKillClick(task.id)}>
            Kill
          </button>
        )}
        {isStopping && (
          <span style={styles.stoppingLabel}>stopping…</span>
        )}
        {isConfirming && (
          <span style={styles.confirm}>
            <span style={styles.confirmLabel}>Confirm kill?</span>
            <button style={styles.yesBtn} onClick={() => onKillConfirm(task.id)}>Yes</button>
            <button style={styles.cancelBtn} onClick={onKillCancel}>Cancel</button>
          </span>
        )}
      </span>
    </div>
  );
}
