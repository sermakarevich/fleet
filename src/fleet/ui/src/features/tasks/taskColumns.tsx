// Per-task cell renderers for the shared DataList: desktop column
// definitions plus the mobile card. Rendered by TasksPage; the kill
// flow lives in TaskActions (shared Confirm). Cell styles stay in
// itemStyles; page/row/chip recipes come from shared/styles.
import { useUnblockTask, useUnignoreTask } from '../../shared/hooks/useApi';
import type { TaskSummary } from '../../shared/types';
import { formatTimestamp, formatTokens, formatContextTitle } from '../../shared/format';
import * as R from '../../shared/styles/recipes';
import { Confirm } from '../../shared/ui/Confirm';
import { StatusChip } from '../../shared/ui/StatusChip';
import type { DataColumn } from '../../shared/ui/DataList';
import { rowStyles, cardStyles } from './itemStyles';

export interface TaskListCallbacks {
  confirmingId: string | null;
  stoppingIds: Set<string>;
  onKillClick: (id: string) => void;
  onKillConfirm: (id: string) => void;
  onKillCancel: () => void;
}

function runsTitle(task: TaskSummary): string {
  return `Last: ${task.last_outcome ?? '—'} → ${task.last_action ?? '—'}: ${task.last_outcome_reason ?? '—'}`;
}

// A lease whose lease_until already passed while the task still shows as
// running: the heartbeat stopped (crashed runner, slept host). The
// supervisor reclaims it once the pid is provably dead; until then flag it.
function isStaleLease(task: TaskSummary): boolean {
  return task.status === 'in_progress'
    && task.lease != null
    && Number(new Date(task.lease.lease_until)) < Date.now();
}

// Title cell: title plus description, blocked reason and lease badges.
export function TaskTitleCell({ task }: { task: TaskSummary }) {
  const isBlocked = task.status === 'blocked';
  return (
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
      {isStaleLease(task) && (
        <span
          style={rowStyles.staleLeaseBadge}
          title={`Last heartbeat ${task.lease?.heartbeat_at ?? '—'}; lease until ${task.lease?.lease_until ?? '—'}`}
        >
          stale lease
        </span>
      )}
      {task.ignored && (
        <span style={rowStyles.ignoredBadge} title={`Triage ignored until ${task.ignore_until ?? '—'}`}>
          ignored
        </span>
      )}
    </span>
  );
}

// Kill / unblock / unignore buttons for one task row or card.
function TaskActionsCell({ task, cb }: { task: TaskSummary; cb: TaskListCallbacks }) {
  const unblockTask = useUnblockTask();
  const unignoreTask = useUnignoreTask();
  const isBlocked = task.status === 'blocked';
  const killEligible = new Set(['in_progress', 'blocked', 'open', 'ready']).has(task.status);
  const isConfirming = cb.confirmingId === task.id;
  const isStopping = cb.stoppingIds.has(task.id) && task.status === 'in_progress';

  function stop(e: React.MouseEvent) {
    e.stopPropagation();
  }

  return (
    <span style={rowStyles.actionCell}>
      {isBlocked && (
        <button style={rowStyles.unblockBtn} onClick={(e) => { stop(e); unblockTask.mutate({ id: task.id }); }}>
          Unblock
        </button>
      )}
      {isBlocked && task.ignored && (
        <button style={rowStyles.unblockBtn} onClick={(e) => { stop(e); unignoreTask.mutate(task.id); }}>
          Unignore
        </button>
      )}
      {killEligible && !isConfirming && !isStopping && (
        <button style={rowStyles.killBtn} onClick={(e) => { stop(e); cb.onKillClick(task.id); }}>
          Kill
        </button>
      )}
      {isStopping && <span style={rowStyles.stoppingLabel}>stopping…</span>}
      {isConfirming && (
        <Confirm verb="Kill" onConfirm={() => cb.onKillConfirm(task.id)} onCancel={cb.onKillCancel} />
      )}
    </span>
  );
}

// Desktop columns for the tasks DataList.
export function taskColumns(cb: TaskListCallbacks): Array<DataColumn<TaskSummary>> {
  return [
    {
      key: 'status', header: 'Status', width: '5rem',
      render: (task) => (
        <StatusChip status={task.status} stopping={cb.stoppingIds.has(task.id) && task.status === 'in_progress'} />
      ),
    },
    { key: 'id', header: 'ID', width: '6rem', render: (task) => <span style={R.idCellStyle()}>{task.id}</span> },
    { key: 'title', header: 'Title', render: (task) => <TaskTitleCell task={task} /> },
    {
      key: 'coder', header: 'Coder / Model', width: '9rem',
      render: (task) => {
        const coderModelStr = [task.coder, task.model].filter(Boolean).join(' · ');
        return (
          <span style={rowStyles.coderCell}>
            {coderModelStr ? coderModelStr : <span style={R.dimStyle()}>(default)</span>}
          </span>
        );
      },
    },
    {
      key: 'context', header: 'Context', width: '5rem',
      render: (task) => (
        <span style={rowStyles.contextCell} title={formatContextTitle(task.context_tokens, task.context_limit)}>
          {formatTokens(task.context_tokens, task.context_pct)}
        </span>
      ),
    },
    {
      key: 'runs', header: 'Runs', width: '4rem',
      render: (task) => (
        <span style={rowStyles.runsCell}>
          {task.restarts > 0 ? (
            <span style={rowStyles.runsChip} title={runsTitle(task)}>{task.restarts + 1}</span>
          ) : (
            task.restarts + 1
          )}
        </span>
      ),
    },
    {
      key: 'started', header: 'Started', width: '8.5rem',
      render: (task) => <span style={rowStyles.tsCell}>{formatTimestamp(task.started_at)}</span>,
    },
    {
      key: 'completed', header: 'Completed', width: '8.5rem',
      render: (task) => <span style={rowStyles.tsCell}>{formatTimestamp(task.ended_at)}</span>,
    },
    {
      key: 'cwd', header: 'Cwd', width: '7rem',
      render: (task) => {
        const cwdShort = task.cwd ? (task.cwd.split('/').pop() ?? task.cwd) : '—';
        return <span style={rowStyles.cwdCell} title={task.cwd ?? undefined}>{cwdShort}</span>;
      },
    },
    {
      key: 'actions', header: '', width: '10rem',
      render: (task) => <TaskActionsCell task={task} cb={cb} />,
    },
  ];
}

// Mobile card for one task, with the same kill flow as the desktop row.
export function TaskCard({ task, cb }: { task: TaskSummary; cb: TaskListCallbacks }) {
  const isStopping = cb.stoppingIds.has(task.id) && task.status === 'in_progress';
  const cwdShort = task.cwd ? (task.cwd.split('/').pop() ?? task.cwd) : '—';
  const coderModelStr = [task.coder, task.model].filter(Boolean).join(' · ');
  const isBlocked = task.status === 'blocked';

  return (
    <>
      <div style={cardStyles.cardHead}>
        <StatusChip status={task.status} stopping={isStopping} width="auto" />
        <span style={cardStyles.cardId}>{task.id}</span>
        <span style={cardStyles.cardActions}>
          <TaskActionsCell task={task} cb={cb} />
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
        <div style={cardStyles.cardMetaText} title={runsTitle(task)}>
          Runs: {task.restarts + 1} · last: {task.last_outcome ?? '—'} → {task.last_action ?? '—'}: {task.last_outcome_reason ?? '—'}
        </div>
      )}
    </>
  );
}
