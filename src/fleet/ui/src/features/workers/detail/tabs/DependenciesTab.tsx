// Dependencies tab of the worker detail page: the bead's dependency
// edges with type and live status, each linking to its worker page.
// Reuses the "Why blocked" section from the old bead drawer. Rendered
// by TaskDetailPage when the Dependencies tab is active.
import { Link } from 'react-router-dom';
import type { BeadDetail } from '../../../../shared/types';
import * as T from '../../../../shared/styles/tokens';
import * as R from '../../../../shared/styles/recipes';
import { LoadingState } from '../../../../shared/ui/LoadingState';

interface Props {
  bead: BeadDetail | undefined;
  isLoading: boolean;
  error: unknown;
}

// One dependency row: id links to the worker, type and status aside;
// incomplete deps carry a "waiting" flag.
function DepRow({ dep, waiting }: { dep: BeadDetail['dependencies'][number]; waiting: boolean }) {
  return (
    <div style={styles.depItem}>
      {dep.id ? (
        <Link to={`/workers/${dep.id}`} style={styles.depId}>{dep.id}</Link>
      ) : (
        <span style={styles.depId}>?</span>
      )}
      <span style={styles.depTitle} title={dep.title ?? undefined}>{dep.title ?? ''}</span>
      <span style={R.miniChipStyle(dep.status ?? '')}>{dep.status ?? '?'}</span>
      {dep.dependency_type && <span style={styles.depType}>{dep.dependency_type}</span>}
      {waiting && <span style={styles.waiting}>waiting</span>}
    </div>
  );
}

// Full dependency list plus, for blocked beads, the recorded reason.
export function DependenciesTab({ bead, isLoading, error }: Props) {
  if (isLoading) return <LoadingState />;
  if (error) return <p style={R.errorMsgStyle()}>Bead detail failed to load.</p>;
  if (!bead) return <p style={R.dimStyle()}>No bead detail.</p>;

  const incomplete = bead.dependencies.filter((d) => d.status !== 'closed');

  return (
    <div style={styles.wrap}>
      {bead.status === 'blocked' && (
        <section>
          <h3 style={styles.sectionTitle}>Why blocked</h3>
          {bead.notes && <pre style={styles.notes}>{bead.notes}</pre>}
          {incomplete.length > 0 && (
            <div style={styles.list}>
              <span style={R.dimStyle()}>
                Waiting on {incomplete.length} open dependenc{incomplete.length === 1 ? 'y' : 'ies'}:
              </span>
              {incomplete.map((d, i) => (
                <DepRow key={d.id ?? i} dep={d} waiting={false} />
              ))}
            </div>
          )}
          {!bead.notes && incomplete.length === 0 && (
            <p style={R.dimStyle()}>No recorded reason — blocked manually. Use Unblock to reopen.</p>
          )}
        </section>
      )}
      <section>
        <h3 style={styles.sectionTitle}>Dependencies ({bead.dependencies.length})</h3>
        {bead.dependencies.length === 0 ? (
          <p style={R.dimStyle()}>None.</p>
        ) : (
          <div style={styles.list}>
            {bead.dependencies.map((d, i) => (
              <DepRow key={d.id ?? i} dep={d} waiting={d.status !== 'closed'} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  wrap: {
    display: 'flex',
    flexDirection: 'column',
    gap: '1rem',
    padding: '1rem',
    overflowY: 'auto',
  },
  sectionTitle: {
    margin: '0 0 0.5rem',
    fontSize: '0.75rem',
    fontWeight: 600,
    color: T.colors.textDim,
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
  },
  list: {
    display: 'flex',
    flexDirection: 'column',
    gap: '0.375rem',
  },
  notes: {
    margin: '0 0 0.5rem',
    padding: '0.625rem 0.75rem',
    background: T.colors.noteBg,
    border: `1px solid ${T.colors.noteBorder}`,
    borderRadius: '0.375rem',
    color: T.colors.noteFg,
    fontSize: '0.8125rem',
    fontFamily: 'ui-monospace, monospace',
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
  },
  depItem: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
    padding: '0.375rem 0.5rem',
    borderBottom: `1px solid ${T.colors.borderSubtle}`,
    fontSize: '0.8125rem',
  },
  depId: {
    fontFamily: 'monospace',
    color: T.colors.link,
    flexShrink: 0,
    textDecoration: 'none',
  },
  depTitle: {
    flex: 1,
    minWidth: 0,
    color: T.colors.textBody,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  depType: {
    flexShrink: 0,
    color: T.colors.textMuted,
    fontSize: '0.7rem',
    fontFamily: 'monospace',
  },
  waiting: {
    flexShrink: 0,
    padding: '0.1rem 0.45rem',
    borderRadius: '10rem',
    background: T.colors.warningBg,
    color: T.colors.warningFg,
    fontSize: '0.7rem',
    fontWeight: 600,
  },
};
