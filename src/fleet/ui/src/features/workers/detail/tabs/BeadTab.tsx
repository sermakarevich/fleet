// Bead tab of the worker detail page (ADR 0017): dependencies, child
// beads, comments and the raw bead JSON in one scroll. The page only
// renders this tab once the bead query settled on a value, so `bead` is
// always defined here; only the children list fetches on its own (with
// its own error text, so one failure never hides the whole tab).
import { useState } from 'react';
import { Link } from 'react-router-dom';
import { errorMessage } from '../../../../shared/api';
import { useTaskChildren } from '../../../../shared/hooks/useApi';
import type { BeadDetail } from '../../../../shared/types';
import * as T from '../../../../shared/styles/tokens';
import * as R from '../../../../shared/styles/recipes';

interface Props {
  taskId: string;
  bead: BeadDetail;
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h3 style={styles.sectionTitle}>{children}</h3>;
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

function DependenciesSection({ bead }: { bead: BeadDetail }) {
  const incomplete = bead.dependencies.filter((d) => d.status !== 'closed');

  return (
    <section>
      <SectionTitle>Dependencies</SectionTitle>
      {bead.status === 'blocked' && (
        <div style={styles.blockedBlock}>
          <h4 style={styles.subTitle}>Why blocked</h4>
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
        </div>
      )}
      <h4 style={styles.subTitle}>Dependencies ({bead.dependencies.length})</h4>
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
  );
}

// Child beads of an epic plus the observer's CHILDREN.md digest. A fetch
// failure shows its own error text instead of hiding the whole tab.
function ChildrenSection({ taskId }: { taskId: string }) {
  const { data, isLoading, error } = useTaskChildren(taskId);

  return (
    <section>
      <SectionTitle>Children</SectionTitle>
      {isLoading && <p style={R.dimStyle()}>Loading…</p>}
      {!isLoading && error && (
        <p style={R.errorMsgStyle()}>Children failed to load: {errorMessage(error)}</p>
      )}
      {!isLoading && !error && data && data.children.length === 0 && (
        <p style={R.dimStyle()}>No child beads.</p>
      )}
      {!isLoading && !error && data && data.children.length > 0 && (
        <div style={styles.list}>
          {data.children.map((c) => (
            <div key={c.id} style={styles.childRow}>
              <Link to={`/workers/${c.id}`} style={styles.depId}>{c.id}</Link>
              <span style={styles.cell}>{c.status ?? '—'}</span>
              <span style={styles.cell}>{c.result_status ?? '—'}</span>
              <span style={R.merge(styles.cell, styles.summary)} title={c.result_summary ?? c.title ?? undefined}>
                {c.result_summary || c.title || '—'}
              </span>
            </div>
          ))}
        </div>
      )}
      {!isLoading && !error && data?.children_md && (
        <div style={styles.digest}>
          <div style={styles.digestLabel}>CHILDREN.md</div>
          <pre style={styles.pre}>{data.children_md}</pre>
        </div>
      )}
    </section>
  );
}

function CommentsSection({ bead }: { bead: BeadDetail }) {
  return (
    <section>
      <SectionTitle>Comments</SectionTitle>
      <h4 style={styles.subTitle}>Comments ({bead.comments.length})</h4>
      {bead.comments.length === 0 ? (
        <p style={R.dimStyle()}>No comments.</p>
      ) : (
        bead.comments.map((c, i) => (
          <div key={c.id ?? i} style={styles.comment}>
            <div style={styles.meta}>
              <span style={styles.author}>{c.author ?? 'unknown'}</span>
              {c.created_at && <span style={R.dimStyle()}>{c.created_at}</span>}
            </div>
            <div style={styles.text}>{c.text}</div>
          </div>
        ))
      )}
    </section>
  );
}

// Raw payload view: collapsed details with monospace pre plus clipboard
// copy; a clipboard failure surfaces as a short inline message.
function RawSection({ bead }: { bead: BeadDetail }) {
  const [copied, setCopied] = useState(false);
  const [copyError, setCopyError] = useState<string | null>(null);

  async function copy() {
    setCopyError(null);
    try {
      await navigator.clipboard.writeText(JSON.stringify(bead, null, 2));
      setCopied(true);
    } catch (err) {
      setCopied(false);
      setCopyError(`Copy failed: ${errorMessage(err)}`);
    }
  }

  return (
    <section>
      <SectionTitle>Raw</SectionTitle>
      <details>
        <summary style={styles.docSummary}>Bead JSON</summary>
        <div style={styles.rawBar}>
          <button style={styles.copyBtn} onClick={() => void copy()}>
            {copied ? 'Copied' : 'Copy'}
          </button>
          {copyError && <span style={styles.copyError}>{copyError}</span>}
        </div>
        <pre style={styles.pre}>{JSON.stringify(bead, null, 2)}</pre>
      </details>
    </section>
  );
}

export function BeadTab({ taskId, bead }: Props) {
  return (
    <div style={styles.wrap}>
      <DependenciesSection bead={bead} />
      <ChildrenSection taskId={taskId} />
      <CommentsSection bead={bead} />
      <RawSection bead={bead} />
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  wrap: {
    display: 'flex',
    flexDirection: 'column',
    gap: '1.25rem',
    padding: '1rem 1.25rem',
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
  subTitle: {
    margin: '0 0 0.5rem',
    fontSize: '0.75rem',
    fontWeight: 600,
    color: T.colors.textDim,
  },
  blockedBlock: {
    marginBottom: '0.75rem',
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
  childRow: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.6rem',
    padding: '0.4rem 0.5rem',
    borderBottom: `1px solid ${T.colors.bgElevated}`,
    color: T.colors.textPrimary,
    fontSize: '0.8rem',
  },
  cell: {
    whiteSpace: 'nowrap',
    color: T.colors.textSecondary,
  },
  summary: {
    flex: 1,
    minWidth: 0,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
  },
  digest: {
    padding: '0.5rem 0',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.2rem',
  },
  digestLabel: {
    color: T.colors.textDim,
    fontWeight: 600,
    fontSize: '0.75rem',
  },
  comment: {
    padding: '0.5rem 0',
    borderBottom: `1px solid ${T.colors.borderSubtle}`,
  },
  meta: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
    marginBottom: '0.25rem',
    fontSize: '0.75rem',
  },
  author: {
    color: T.colors.textSecondary,
    fontWeight: 600,
  },
  text: {
    color: T.colors.textBody,
    fontSize: '0.8125rem',
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
    lineHeight: 1.5,
  },
  docSummary: {
    cursor: 'pointer',
    fontSize: '0.8125rem',
    color: T.colors.textSecondary,
    fontFamily: 'monospace',
    padding: '0.25rem 0',
  },
  rawBar: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
    margin: '0.25rem 0 0.5rem',
  },
  copyBtn: {
    padding: '0.2rem 0.625rem',
    background: 'transparent',
    border: `1px solid ${T.colors.border}`,
    borderRadius: '0.25rem',
    color: T.colors.textSecondary,
    cursor: 'pointer',
    fontSize: '0.75rem',
    fontFamily: 'system-ui, sans-serif',
  },
  copyError: {
    fontSize: '0.75rem',
    color: T.colors.danger,
  },
  pre: {
    margin: 0,
    padding: '0.625rem 0.75rem',
    background: T.colors.bgElevated,
    border: `1px solid ${T.colors.border}`,
    borderRadius: '0.375rem',
    color: T.colors.textBody,
    fontSize: '0.75rem',
    fontFamily: 'ui-monospace, monospace',
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
    lineHeight: 1.5,
  },
};
