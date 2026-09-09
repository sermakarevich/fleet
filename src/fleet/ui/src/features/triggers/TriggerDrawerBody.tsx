// Body sections of the trigger drawer: target-specific definition,
// upcoming firings and past runs. Rendered by TriggerDrawer once the
// schedule has loaded; the edit form lives in the drawer shell.
import { Link } from 'react-router-dom';
import { formatShortDateTime as fmtTs } from '../../shared/format';
import * as T from '../../shared/styles/tokens';
import * as R from '../../shared/styles/recipes';
import type { ScheduleDetail } from '../../shared/types';
import type { TriggerTarget } from './types';
import { TriggerRuns } from './TriggerRuns';

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

// Definition for a task schedule: worker template plus cron/coder fields.
function TaskDefinition({ schedule }: { schedule: ScheduleDetail }) {
  return (
    <>
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
    </>
  );
}

// Definition for a workflow schedule: linked workflow plus cron/overlap.
function WorkflowDefinition({
  schedule, workflowName,
}: {
  schedule: ScheduleDetail; workflowName: string | null;
}) {
  return (
    <>
      <DefRow label="workflow">
        {schedule.workflow_id ? (
          <Link to={`/workflows/${schedule.workflow_id}`} style={styles.workflowLink}>
            {workflowName ?? schedule.workflow_id}
          </Link>
        ) : (
          <span style={R.dimStyle()}>—</span>
        )}
      </DefRow>
      <DefRow label="cron">
        <span style={R.monoStyle()} title={schedule.timezone}>{schedule.cron}</span>
        <span style={R.dimStyle()}> ({schedule.timezone})</span>
      </DefRow>
      <DefRow label="overlap">{schedule.overlap}</DefRow>
      <DefRow label="enabled">{schedule.enabled ? 'yes' : 'no'}</DefRow>
    </>
  );
}

// Definition, upcoming firings and past runs for one schedule.
export function TriggerDrawerBody({
  schedule, target, workflowName,
}: {
  schedule: ScheduleDetail; target: TriggerTarget; workflowName: string | null;
}) {
  return (
    <>
      <h2 style={styles.title}>{schedule.name}</h2>
      <div style={styles.metaRow}>
        <span style={schedule.enabled ? styles.enabledOn : styles.enabledOff}>
          {schedule.enabled ? 'enabled' : 'disabled'}
        </span>
      </div>
      <section style={styles.section}>
        <SectionTitle>Definition</SectionTitle>
        {target === 'workflow'
          ? <WorkflowDefinition schedule={schedule} workflowName={workflowName} />
          : <TaskDefinition schedule={schedule} />}
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
        <SectionTitle>
          {target === 'workflow' ? `Past runs (${schedule.runs.length})` : `Runs (${schedule.runs.length})`}
        </SectionTitle>
        <TriggerRuns runs={schedule.runs} />
      </section>
    </>
  );
}

const styles = {
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
  section: { marginBottom: '1.25rem' } as React.CSSProperties,
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
  workflowLink: { color: T.colors.link, textDecoration: 'none' } as React.CSSProperties,
  upcomingRow: {
    padding: '0.25rem 0', borderBottom: `1px solid ${T.colors.borderSubtle}`,
    fontSize: '0.8125rem', color: T.colors.textSecondary,
  } as React.CSSProperties,
};
