/**
 * Slide-over detail view for one recurring workflow schedule: definition,
 * upcoming firings and past workflow runs with links to each run.
 * Called by RecurringPage when a row is selected; the create/edit form is
 * the shared RecurringForm. Mutations come from the schedule hooks in
 * shared/hooks/useApi (same endpoints as the schedules tab).
 */
import { useState } from 'react';
import { Link } from 'react-router-dom';
import {
  useDeleteSchedule,
  useRunSchedule,
  useSchedule,
  useSetScheduleEnabled,
  useWorkflowRun,
  useWorkflows,
} from '../../shared/hooks/useApi';
import { formatShortDateTime as fmtTs } from '../../shared/format';
import * as T from '../../shared/styles/tokens';
import * as R from '../../shared/styles/recipes';
import { Modal } from '../../shared/ui/Modal';
import { RunProgress, RunStatusChip, TriggerChip } from '../workflows/RunRow';
import { RecurringForm } from './RecurringForm';
import type { ScheduleRun } from '../../shared/types';

// Section heading inside the drawer.
function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h3 style={styles.sectionTitle}>{children}</h3>;
}

// One label/value line in the Definition section.
function DefRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={styles.defRow}>
      <span style={styles.defLabel}>{label}</span>
      <span style={styles.defValue}>{children}</span>
    </div>
  );
}

// Done/total progress for one past run, fetched lazily from the run detail.
function RecurringRunProgress({ workflowRunId }: { workflowRunId: string }) {
  const { data: run } = useWorkflowRun(workflowRunId);
  if (!run) return <span style={R.dimStyle()}>…</span>;
  return <RunProgress run={run} />;
}

// One past-run row: number, times, trigger, and either the run link with
// its status chip and step progress or the skip reason.
function PastRunRow({ run }: { run: ScheduleRun }) {
  return (
    <div style={styles.runRow}>
      <span style={styles.runN}>#{run.n}</span>
      <span style={styles.runTs} title={`fired ${run.fired_at}`}>
        {fmtTs(run.scheduled_for)}
      </span>
      <TriggerChip trigger={run.trigger} />
      {run.skipped || !run.workflow_run_id ? (
        <span style={R.dimStyle()}>skipped — {run.reason || 'no reason'}</span>
      ) : (
        <span style={styles.runDetail}>
          <Link to={`/workflow-runs/${run.workflow_run_id}`} style={styles.runLink}>
            <RunStatusChip status={run.workflow_run_status ?? 'unknown'} />
          </Link>
          <RecurringRunProgress workflowRunId={run.workflow_run_id} />
        </span>
      )}
    </div>
  );
}

// Drawer showing the full detail of one recurring workflow schedule.
export function RecurringDrawer({
  scheduleId,
  onClose,
}: {
  scheduleId: string;
  onClose: () => void;
}) {
  const { data: schedule, isLoading, error } = useSchedule(scheduleId);
  const { data: workflows } = useWorkflows();
  const runSchedule = useRunSchedule();
  const setEnabled = useSetScheduleEnabled();
  const deleteSchedule = useDeleteSchedule();
  const [showEdit, setShowEdit] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  function handleDelete() {
    if (!confirmDelete) {
      setConfirmDelete(true);
      return;
    }
    void deleteSchedule.mutateAsync(scheduleId).then(onClose);
  }

  const workflowName = schedule?.workflow_id
    ? (workflows ?? []).find((w) => w.id === schedule.workflow_id)?.name ?? schedule.workflow_id
    : null;

  return (
    <Modal
      labelledBy="recurring-drawer-title"
      onClose={onClose}
      placement="right"
      panelStyle={R.drawerStyle()}
    >
      <div style={styles.header}>
        <span id="recurring-drawer-title" style={styles.id}>
          {scheduleId}
        </span>
        <button style={styles.closeBtn} onClick={onClose} title="Close" aria-label="Close">
          ✕
        </button>
      </div>

      {isLoading && <p style={R.msgStyle()}>Loading…</p>}
      {error && <p style={R.errorMsgStyle()}>Error: {String(error)}</p>}

      {schedule && (
        <div style={styles.body}>
          <h2 style={styles.title}>{schedule.name}</h2>

          <div style={styles.metaRow}>
            <span style={schedule.enabled ? styles.enabledOn : styles.enabledOff}>
              {schedule.enabled ? 'enabled' : 'disabled'}
            </span>
          </div>

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
              onClick={() => setEnabled.mutate({ id: scheduleId, enabled: !schedule.enabled })}
            >
              {schedule.enabled ? 'Disable' : 'Enable'}
            </button>
            <button style={styles.ghostBtn} onClick={() => setShowEdit(true)}>
              Edit
            </button>
            <button
              style={confirmDelete ? styles.deleteConfirmBtn : styles.deleteBtn}
              disabled={deleteSchedule.isPending}
              onClick={handleDelete}
            >
              {confirmDelete ? 'Confirm delete' : 'Delete'}
            </button>
          </div>

          <section style={styles.section}>
            <SectionTitle>Definition</SectionTitle>
            <DefRow label="workflow">
              {schedule.workflow_id ? (
                <Link to={`/workflows/${schedule.workflow_id}`} style={styles.workflowLink}>
                  {workflowName}
                </Link>
              ) : (
                <span style={R.dimStyle()}>—</span>
              )}
            </DefRow>
            <DefRow label="cron">
              <span style={R.monoStyle()} title={schedule.timezone}>
                {schedule.cron}
              </span>
              <span style={R.dimStyle()}> ({schedule.timezone})</span>
            </DefRow>
            <DefRow label="overlap">{schedule.overlap}</DefRow>
            <DefRow label="enabled">{schedule.enabled ? 'yes' : 'no'}</DefRow>
          </section>

          <section style={styles.section}>
            <SectionTitle>Upcoming</SectionTitle>
            {schedule.upcoming.length === 0 ? (
              <p style={R.dimStyle()}>Nothing scheduled{schedule.enabled ? '' : ' (disabled)'}.</p>
            ) : (
              schedule.upcoming
                .slice(0, 5)
                .map((ts) => <div key={ts} style={styles.upcomingRow}>{fmtTs(ts)}</div>)
            )}
          </section>

          <section style={styles.section}>
            <SectionTitle>Past runs ({schedule.runs.length})</SectionTitle>
            {schedule.runs.length === 0 ? (
              <p style={R.dimStyle()}>No runs yet.</p>
            ) : (
              schedule.runs.map((run) => <PastRunRow key={run.n} run={run} />)
            )}
          </section>
        </div>
      )}

      {showEdit && schedule && (
        <RecurringForm
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
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '0.625rem 1rem',
    borderBottom: `1px solid ${T.colors.borderSubtle}`,
    flexShrink: 0,
  } as React.CSSProperties,
  id: {
    fontFamily: 'monospace',
    color: '#60a5fa',
    fontSize: '0.875rem',
    fontWeight: 600,
  } as React.CSSProperties,
  closeBtn: {
    background: 'transparent',
    border: 'none',
    color: T.colors.textSecondary,
    cursor: 'pointer',
    fontSize: '1rem',
    lineHeight: 1,
    padding: '0.25rem',
  } as React.CSSProperties,
  body: {
    padding: '1rem',
    overflowY: 'auto' as const,
    flex: 1,
  } as React.CSSProperties,
  title: {
    margin: '0 0 0.75rem',
    fontSize: '1rem',
    fontWeight: 600,
    color: '#f4f4f5',
    lineHeight: 1.4,
  } as React.CSSProperties,
  metaRow: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
    flexWrap: 'wrap' as const,
    marginBottom: '0.875rem',
  } as React.CSSProperties,
  enabledOn: {
    ...T.badge,
    background: '#14532d',
    color: '#bbf7d0',
  } as React.CSSProperties,
  enabledOff: {
    ...T.badge,
    background: T.colors.borderSubtle,
    color: T.colors.textSecondary,
  } as React.CSSProperties,
  actionsRow: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
    flexWrap: 'wrap' as const,
    marginBottom: '1.25rem',
  } as React.CSSProperties,
  runBtn: {
    ...T.btnPrimary,
    padding: '0.3rem 0.75rem',
    fontSize: '0.8125rem',
  } as React.CSSProperties,
  ghostBtn: {
    ...T.btnGhost,
    padding: '0.3rem 0.75rem',
    fontSize: '0.8125rem',
  } as React.CSSProperties,
  deleteBtn: {
    ...T.btnDanger,
    padding: '0.3rem 0.75rem',
    fontSize: '0.8125rem',
  } as React.CSSProperties,
  deleteConfirmBtn: {
    padding: '0.3rem 0.75rem',
    fontSize: '0.8125rem',
    fontWeight: 600,
    background: T.colors.danger,
    border: `1px solid ${T.colors.danger}`,
    borderRadius: 4,
    color: '#fff',
    cursor: 'pointer',
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  section: {
    marginBottom: '1.25rem',
  } as React.CSSProperties,
  sectionTitle: {
    margin: '0 0 0.5rem',
    fontSize: '0.75rem',
    fontWeight: 600,
    color: T.colors.textDim,
    textTransform: 'uppercase' as const,
    letterSpacing: '0.05em',
  } as React.CSSProperties,
  defRow: {
    display: 'flex',
    gap: '0.5rem',
    padding: '0.25rem 0',
    fontSize: '0.8125rem',
    color: '#d4d4d8',
  } as React.CSSProperties,
  defLabel: {
    width: '6.5rem',
    flexShrink: 0,
    color: T.colors.textDim,
  } as React.CSSProperties,
  defValue: {
    flex: 1,
    minWidth: 0,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  workflowLink: {
    color: '#60a5fa',
    textDecoration: 'none',
  } as React.CSSProperties,
  upcomingRow: {
    padding: '0.25rem 0',
    borderBottom: `1px solid ${T.colors.borderSubtle}`,
    fontSize: '0.8125rem',
    color: T.colors.textSecondary,
  } as React.CSSProperties,
  runRow: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
    padding: '0.375rem 0',
    borderBottom: `1px solid ${T.colors.borderSubtle}`,
    fontSize: '0.8125rem',
    flexWrap: 'wrap' as const,
  } as React.CSSProperties,
  runN: {
    fontFamily: 'monospace',
    color: T.colors.textSecondary,
    width: '2.5rem',
    flexShrink: 0,
  } as React.CSSProperties,
  runTs: {
    color: '#d4d4d8',
    flexShrink: 0,
  } as React.CSSProperties,
  runDetail: {
    display: 'inline-flex',
    alignItems: 'center',
    gap: '0.5rem',
    flex: 1,
    minWidth: '10rem',
  } as React.CSSProperties,
  runLink: {
    display: 'inline-flex',
    textDecoration: 'none',
  } as React.CSSProperties,
};
