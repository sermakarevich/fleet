/**
 * Slide-over detail view for one schedule: definition, upcoming firings
 * and run history with links to the tasks each run opened.
 * Called by SchedulesPage when a row is selected.
 */
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useDeleteSchedule, useRunSchedule, useSchedule, useSetScheduleEnabled } from '../../shared/hooks/useApi';
import { formatShortDateTime as fmtTs } from '../../shared/format';
import * as T from '../../shared/styles/tokens';
import * as R from '../../shared/styles/recipes';
import { Modal } from '../../shared/ui/Modal';
import { Confirm } from '../../shared/ui/Confirm';
import { LoadingState } from '../../shared/ui/LoadingState';
import { StatusChip } from '../../shared/ui/StatusChip';
import { ScheduleForm } from './ScheduleForm';

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

// Drawer showing the full detail of one schedule.
export function ScheduleDrawer({ scheduleId, onClose }: { scheduleId: string; onClose: () => void }) {
  const { data: schedule, isLoading, error } = useSchedule(scheduleId);
  const runSchedule = useRunSchedule();
  const setEnabled = useSetScheduleEnabled();
  const deleteSchedule = useDeleteSchedule();
  const [showEdit, setShowEdit] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);

  function handleDelete() {
    void deleteSchedule.mutateAsync(scheduleId).then(onClose);
  }

  return (
    <Modal labelledBy="schedule-drawer-title" onClose={onClose} placement="right" panelStyle={R.drawerStyle()}>
      <div style={styles.header}>
        <span id="schedule-drawer-title" style={styles.id}>{scheduleId}</span>
        <button style={styles.closeBtn} onClick={onClose} title="Close" aria-label="Close">✕</button>
      </div>

      {isLoading && <LoadingState />}
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

          <section style={styles.section}>
            <SectionTitle>Definition</SectionTitle>
            <DefRow label="cron">
              <span style={R.monoStyle()}>{schedule.cron}</span>
              <span style={R.dimStyle()}> ({schedule.timezone})</span>
            </DefRow>
            <DefRow label="cwd">{schedule.cwd ?? <span style={R.dimStyle()}>—</span>}</DefRow>
            <DefRow label="coder/model">
              {schedule.coder ?? <span style={R.dimStyle()}>default</span>}
              {schedule.model ? ` / ${schedule.model}` : ''}
            </DefRow>
            <DefRow label="priority">{schedule.priority}</DefRow>
            <DefRow label="overlap">{schedule.overlap}</DefRow>
            <SectionTitle>Title template</SectionTitle>
            <pre style={styles.pre}>{schedule.title}</pre>
            {schedule.description && <pre style={styles.pre}>{schedule.description}</pre>}
          </section>

          <section style={styles.section}>
            <SectionTitle>Upcoming</SectionTitle>
            {schedule.upcoming.length === 0 ? (
              <p style={R.dimStyle()}>Nothing scheduled{schedule.enabled ? '' : ' (disabled)'}.</p>
            ) : (
              schedule.upcoming.slice(0, 5).map((ts) => (
                <div key={ts} style={styles.upcomingRow}>{fmtTs(ts)}</div>
              ))
            )}
          </section>

          <section style={styles.section}>
            <SectionTitle>Runs ({schedule.runs.length})</SectionTitle>
            {schedule.runs.length === 0 ? (
              <p style={R.dimStyle()}>No runs yet.</p>
            ) : (
              schedule.runs.map((run) => (
                <div key={run.n} style={styles.runRow}>
                  <span style={styles.runN}>#{run.n}</span>
                  <span style={styles.runTs} title={`fired ${run.fired_at}`}>{fmtTs(run.scheduled_for)}</span>
                  <span style={R.miniChipStyle(run.trigger)}>{run.trigger}</span>
                  {run.skipped || !run.task_id ? (
                    <span style={R.dimStyle()}>skipped — {run.reason || 'no reason'}</span>
                  ) : (
                    <Link to={`/tasks/${run.task_id}`} style={styles.taskLink}>
                      <span style={R.monoStyle()}>{run.task_id}</span>
                      <StatusChip status={run.task_status ?? 'unknown'} width="5rem" />
                    </Link>
                  )}
                </div>
              ))
            )}
          </section>
        </div>
      )}

      {showEdit && schedule && (
        <ScheduleForm
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
  title: {
    margin: '0 0 0.75rem', fontSize: '1rem', fontWeight: 600, color: T.colors.textBright, lineHeight: 1.4,
  } as React.CSSProperties,
  metaRow: {
    display: 'flex', alignItems: 'center', gap: '0.5rem',
    flexWrap: 'wrap' as const, marginBottom: '0.875rem',
  } as React.CSSProperties,
  enabledOn: {
    ...T.badge, background: T.colors.greenDark, color: T.colors.mintPale,
  } as React.CSSProperties,
  enabledOff: {
    ...T.badge, background: T.colors.borderSubtle, color: T.colors.textSecondary,
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
  section: {
    marginBottom: '1.25rem',
  } as React.CSSProperties,
  sectionTitle: {
    margin: '0 0 0.5rem', fontSize: '0.75rem', fontWeight: 600, color: T.colors.textDim,
    textTransform: 'uppercase' as const, letterSpacing: '0.05em',
  } as React.CSSProperties,
  defRow: {
    display: 'flex', gap: '0.5rem', padding: '0.25rem 0',
    fontSize: '0.8125rem', color: T.colors.textBody,
  } as React.CSSProperties,
  defLabel: {
    width: '6.5rem', flexShrink: 0, color: T.colors.textDim,
  } as React.CSSProperties,
  defValue: {
    flex: 1, minWidth: 0, overflow: 'hidden',
    textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const,
  } as React.CSSProperties,
  pre: {
    margin: '0 0 0.5rem', padding: '0.625rem 0.75rem', background: T.colors.bgElevated,
    border: `1px solid ${T.colors.border}`, borderRadius: '0.375rem', color: T.colors.textBody,
    fontSize: '0.8125rem', fontFamily: 'ui-monospace, monospace',
    whiteSpace: 'pre-wrap' as const, wordBreak: 'break-word' as const, lineHeight: 1.5,
  } as React.CSSProperties,
  upcomingRow: {
    padding: '0.25rem 0', borderBottom: `1px solid ${T.colors.borderSubtle}`,
    fontSize: '0.8125rem', color: T.colors.textSecondary,
  } as React.CSSProperties,
  runRow: {
    display: 'flex', alignItems: 'center', gap: '0.5rem', padding: '0.375rem 0',
    borderBottom: `1px solid ${T.colors.borderSubtle}`, fontSize: '0.8125rem',
    flexWrap: 'wrap' as const,
  } as React.CSSProperties,
  runN: {
    fontFamily: 'monospace', color: T.colors.textSecondary,
    width: '2.5rem', flexShrink: 0,
  } as React.CSSProperties,
  runTs: {
    color: T.colors.textBody, flexShrink: 0,
  } as React.CSSProperties,
  taskLink: {
    display: 'inline-flex', alignItems: 'center', gap: '0.5rem',
    color: T.colors.link, textDecoration: 'none', fontSize: '0.8125rem',
  } as React.CSSProperties,
};
