// Result tab of the worker detail page (ADR 0017): everything the task
// produced in one scroll — RESULT.json, outputs/, documents under
// artifacts/, STATE.md, files touched, and an on-demand worktree-aware
// diff. Backed by GET /api/tasks/{id}/artifacts (one bundle) plus
// GET /api/tasks/{id}/diff on demand. Missing parts are omitted, never
// errors; a bundle fetch failure shows the error with a Retry.
import { useState } from 'react';
import { errorMessage } from '../../../../shared/api';
import { useArtifactBundle, useTaskDiff } from '../../../../shared/hooks/useApi';
import type { ArtifactBundle, ArtifactDoc, FileOp, TaskDetail, TaskResult } from '../../../../shared/types';
import { merge } from '../../../../shared/styles/recipes';
import * as T from '../../../../shared/styles/tokens';
import { EmptyState } from '../../../../shared/ui/EmptyState';
import { Markdown } from '../../../../shared/ui/Markdown';

interface Props {
  taskId: string;
  status: string;
  result: TaskDetail['result'];
}

const RESULT_BADGE_COLOR: Record<TaskResult['status'], string> = {
  done: T.colors.success,
  partial: T.colors.yellow,
  blocked: T.colors.danger,
};

function ResultBadge({ result }: { result: TaskResult }) {
  return (
    <div style={styles.resultBadge}>
      <span style={merge(styles.resultDot, { background: RESULT_BADGE_COLOR[result.status] })} />
      <span style={styles.resultStatus}>{result.status}</span>
      {result.summary && <span style={styles.resultSummary}>{result.summary}</span>}
    </div>
  );
}

/** "1.2 KiB" / "3.4 MiB" / "42 B" for the outputs listing. */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ['KiB', 'MiB', 'GiB', 'TiB'];
  let value = bytes / 1024;
  let unit = units[0];
  for (const next of units.slice(1)) {
    if (value < 1024) break;
    value /= 1024;
    unit = next;
  }
  return `${value.toFixed(1)} ${unit}`;
}

// RESULT.json content, pretty-printed: known fields (status, summary,
// next_steps/followups) as text when present, else the raw JSON.
function ResultContent({ content }: { content: string }) {
  let parsed: unknown = null;
  try {
    parsed = JSON.parse(content);
  } catch {
    return <pre style={styles.pre}>{content}</pre>;
  }
  if (typeof parsed !== 'object' || parsed === null) {
    return <pre style={styles.pre}>{content}</pre>;
  }
  const rec = parsed as Record<string, unknown>;
  const status = typeof rec.status === 'string' ? rec.status : null;
  const summary = typeof rec.summary === 'string' ? rec.summary : null;
  const nextSteps = rec.next_steps ?? rec.next_step ?? null;
  const followups = rec.followups ?? null;
  if (status == null && summary == null && nextSteps == null && followups == null) {
    return <pre style={styles.pre}>{content}</pre>;
  }
  return (
    <div style={styles.resultBody}>
      {status && (
        <div style={styles.resultLine}>
          <span style={styles.resultField}>status</span> {status}
        </div>
      )}
      {summary && (
        <div style={styles.resultLine}>
          <span style={styles.resultField}>summary</span> {summary}
        </div>
      )}
      {nextSteps != null && nextSteps !== '' && (
        <div style={styles.resultLine}>
          <span style={styles.resultField}>next steps</span> {formatSteps(nextSteps)}
        </div>
      )}
      {followups != null && followups !== '' && (
        <div style={styles.resultLine}>
          <span style={styles.resultField}>followups</span> {formatSteps(followups)}
        </div>
      )}
    </div>
  );
}

function formatSteps(value: unknown): string {
  if (typeof value === 'string') return value;
  if (Array.isArray(value)) {
    return value
      .map((item) => {
        if (typeof item === 'string') return item;
        if (typeof item === 'object' && item !== null) {
          const rec = item as Record<string, unknown>;
          const title = typeof rec.title === 'string' ? rec.title : '';
          const body = typeof rec.body === 'string' ? rec.body : '';
          return [title, body].filter(Boolean).join(': ');
        }
        return String(item);
      })
      .join('\n');
  }
  return String(value);
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h3 style={styles.sectionTitle}>{children}</h3>;
}

function FilesTable({ files }: { files: FileOp[] }) {
  return (
    <table style={styles.table}>
      <thead>
        <tr>
          <th style={styles.thPath}>Path</th>
          <th style={styles.thCount}>Read</th>
          <th style={styles.thCount}>Edit</th>
          <th style={styles.thCount}>Write</th>
        </tr>
      </thead>
      <tbody>
        {files.map((f) => (
          <tr key={f.path} style={styles.row}>
            <td style={styles.tdPath}>{f.path}</td>
            <td style={styles.tdCount}>{f.read > 0 ? f.read : <span style={styles.zero}>—</span>}</td>
            <td style={styles.tdCount}>{f.edit > 0 ? f.edit : <span style={styles.zero}>—</span>}</td>
            <td style={styles.tdCount}>{f.write > 0 ? f.write : <span style={styles.zero}>—</span>}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function DiffSection({ taskId, worktree }: { taskId: string; worktree: ArtifactBundle['worktree'] }) {
  const [requested, setRequested] = useState(false);
  const diffQuery = useTaskDiff(taskId, requested);

  const worktreeGone = worktree != null && !worktree.exists;
  const worktreeLabel = worktree?.worktree_path
    ? worktree.base_ref
      ? `branch vs ${worktree.base_ref} in ${worktree.worktree_path}`
      : `in ${worktree.worktree_path}`
    : null;

  const diff = diffQuery.data?.diff ?? '';
  const note = diffQuery.data?.note ?? '';

  return (
    <section>
      <SectionTitle>Diff</SectionTitle>
      <div style={styles.diffBar}>
        <button
          style={styles.loadBtn}
          disabled={requested || worktreeGone}
          onClick={() => setRequested(true)}
        >
          Load diff
        </button>
        {worktreeLabel && !worktreeGone && <span style={styles.diffMeta}>{worktreeLabel}</span>}
        {worktreeGone && <span style={styles.diffMeta}>worktree removed</span>}
      </div>
      {requested && diffQuery.isLoading && <p style={styles.msg}>Loading…</p>}
      {requested && diffQuery.isError && (
        <p style={styles.error}>Could not load diff: {errorMessage(diffQuery.error)}</p>
      )}
      {requested && diffQuery.data && diff !== '' && <pre style={styles.pre}>{diff}</pre>}
      {requested && diffQuery.data && diff === '' && note !== '' && <p style={styles.msg}>{note}</p>}
      {requested && diffQuery.data && diff === '' && note === '' && <p style={styles.msg}>No changes.</p>}
    </section>
  );
}

export function ResultTab({ taskId, status, result }: Props) {
  const bundleQuery = useArtifactBundle(taskId, status);
  const { data: bundle, dataUpdatedAt, error, refetch } = bundleQuery;

  if (bundleQuery.isLoading && !bundle) {
    return <p style={styles.msg}>Loading…</p>;
  }

  if (error && !bundle) {
    return (
      <div style={styles.errorWrap}>
        <p style={styles.error}>Could not load result: {errorMessage(error)}</p>
        <button style={styles.loadBtn} onClick={() => void refetch()}>
          Retry
        </button>
      </div>
    );
  }

  if (!bundle) {
    return <p style={styles.msg}>Loading…</p>;
  }

  const showResult = result != null || bundle.result != null;
  const showOutputs = bundle.outputs.length > 0;
  const showDocs = bundle.docs.length > 0;
  const showState = bundle.state != null;
  const showFiles = bundle.files.length > 0;
  const hasContent = showResult || showOutputs || showDocs || showState || showFiles;

  return (
    <div style={styles.container}>
      <div style={styles.header}>
        <span style={styles.updated}>
          updated {new Date(dataUpdatedAt).toTimeString().slice(0, 8)}
        </span>
      </div>
      <div style={styles.body}>
        {!hasContent && (
          <EmptyState message={status === 'in_progress' ? 'Nothing produced yet.' : 'Nothing produced.'} />
        )}
        {showResult && (
          <section>
            <SectionTitle>Result</SectionTitle>
            {result && <ResultBadge result={result} />}
            {bundle.result && <ResultContent content={bundle.result.content} />}
          </section>
        )}
        {showOutputs && (
          <section>
            <SectionTitle>Outputs</SectionTitle>
            <div style={styles.list}>
              {bundle.outputs.map((o) => (
                <div key={o.path} style={styles.outputRow}>
                  <span style={styles.outputName}>{o.name}</span>
                  <span style={styles.outputSize}>{formatBytes(o.size)}</span>
                  <a href={`vscode://file/${o.path}`} style={styles.editorLink} title={o.path}>
                    Open in editor
                  </a>
                </div>
              ))}
            </div>
          </section>
        )}
        {showDocs && (
          <section>
            <SectionTitle>Documents</SectionTitle>
            <div style={styles.list}>
              {bundle.docs.map((doc: ArtifactDoc, i: number) => (
                <details key={doc.name} open={i === 0}>
                  <summary style={styles.docSummary}>
                    {doc.name}
                    {doc.truncated && <span style={styles.truncated}> (truncated)</span>}
                  </summary>
                  {doc.name.endsWith('.md') ? (
                    <div style={styles.markdown}>
                      <Markdown source={doc.content} />
                    </div>
                  ) : (
                    <pre style={styles.pre}>{doc.content}</pre>
                  )}
                </details>
              ))}
            </div>
          </section>
        )}
        {showState && bundle.state && (
          <section>
            <SectionTitle>State</SectionTitle>
            <details>
              <summary style={styles.docSummary}>Progress notes (STATE.md)</summary>
              <div style={styles.markdown}>
                <Markdown source={bundle.state.content} />
              </div>
            </details>
          </section>
        )}
        {showFiles && (
          <section>
            <SectionTitle>Files touched</SectionTitle>
            <FilesTable files={bundle.files} />
          </section>
        )}
        <DiffSection taskId={taskId} worktree={bundle.worktree} />
      </div>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
  },
  header: {
    padding: '0.4rem 0.75rem',
    borderBottom: `1px solid ${T.colors.borderSubtle}`,
    background: T.colors.bgSurface,
    display: 'flex',
    justifyContent: 'flex-end',
  },
  updated: {
    fontSize: '0.75rem',
    color: T.colors.textDim,
    fontFamily: 'monospace',
  },
  body: {
    flex: 1,
    overflowY: 'auto',
    padding: '1rem 1.25rem',
    display: 'flex',
    flexDirection: 'column',
    gap: '1.25rem',
  },
  sectionTitle: {
    margin: '0 0 0.5rem',
    fontSize: '0.75rem',
    fontWeight: 600,
    color: T.colors.textDim,
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
  },
  resultBadge: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
    fontSize: '0.75rem',
    marginBottom: '0.5rem',
  },
  resultDot: {
    width: '0.6rem',
    height: '0.6rem',
    borderRadius: '50%',
  },
  resultStatus: {
    fontWeight: 600,
    color: T.colors.textPrimary,
  },
  resultSummary: {
    color: T.colors.textSecondary,
  },
  resultBody: {
    display: 'flex',
    flexDirection: 'column',
    gap: '0.25rem',
    fontSize: '0.8125rem',
    color: T.colors.textBody,
    whiteSpace: 'pre-wrap',
  },
  resultLine: {
    lineHeight: 1.5,
  },
  resultField: {
    color: T.colors.textDim,
    fontWeight: 600,
    marginRight: '0.5rem',
  },
  list: {
    display: 'flex',
    flexDirection: 'column',
    gap: '0.375rem',
  },
  outputRow: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.75rem',
    fontSize: '0.8125rem',
    padding: '0.25rem 0',
    borderBottom: `1px solid ${T.colors.bgElevated}`,
  },
  outputName: {
    flex: 1,
    minWidth: 0,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    color: T.colors.textPrimary,
    fontFamily: 'monospace',
  },
  outputSize: {
    color: T.colors.textDim,
    fontSize: '0.75rem',
    fontFamily: 'monospace',
    flexShrink: 0,
  },
  editorLink: {
    fontSize: '0.75rem',
    color: T.colors.link,
    textDecoration: 'none',
    flexShrink: 0,
  },
  docSummary: {
    cursor: 'pointer',
    fontSize: '0.8125rem',
    color: T.colors.textSecondary,
    fontFamily: 'monospace',
    padding: '0.25rem 0',
  },
  truncated: {
    color: T.colors.textMuted,
    fontSize: '0.75rem',
  },
  markdown: {
    color: T.colors.textPrimary,
    fontSize: '0.875rem',
    lineHeight: 1.6,
    padding: '0.5rem 0',
  },
  table: {
    width: '100%',
    borderCollapse: 'collapse',
    fontFamily: 'monospace',
    fontSize: '0.78rem',
  },
  thPath: {
    textAlign: 'left',
    padding: '0.4rem 0.5rem',
    color: T.colors.textDim,
    fontWeight: 600,
    fontSize: '0.7rem',
    borderBottom: `1px solid ${T.colors.borderSubtle}`,
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
  },
  thCount: {
    textAlign: 'right',
    padding: '0.4rem 0.75rem',
    color: T.colors.textDim,
    fontWeight: 600,
    fontSize: '0.7rem',
    borderBottom: `1px solid ${T.colors.borderSubtle}`,
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
  },
  row: {
    borderBottom: `1px solid ${T.colors.bgElevated}`,
  },
  tdPath: {
    padding: '0.35rem 0.5rem',
    color: T.colors.textSecondary,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
    maxWidth: 400,
  },
  tdCount: {
    padding: '0.35rem 0.75rem',
    textAlign: 'right',
    color: T.colors.textPrimary,
    fontWeight: 600,
  },
  zero: {
    color: T.colors.border,
  },
  diffBar: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.75rem',
    marginBottom: '0.5rem',
  },
  loadBtn: {
    padding: '0.2rem 0.625rem',
    background: 'transparent',
    border: `1px solid ${T.colors.border}`,
    borderRadius: '0.25rem',
    color: T.colors.textSecondary,
    cursor: 'pointer',
    fontSize: '0.75rem',
    fontFamily: 'system-ui, sans-serif',
  },
  diffMeta: {
    fontSize: '0.75rem',
    color: T.colors.textDim,
    fontFamily: 'monospace',
  },
  pre: {
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
    background: T.colors.bgDeeper,
    border: `1px solid ${T.colors.borderSubtle}`,
    borderRadius: '4px',
    padding: '0.5rem',
    margin: 0,
    color: T.colors.textBody,
    fontSize: '0.75rem',
    maxHeight: '24rem',
    overflowY: 'auto',
  },
  msg: {
    padding: '0.5rem 0',
    color: T.colors.textDim,
    margin: 0,
    fontSize: '0.8125rem',
  },
  error: {
    padding: '0.5rem 0',
    color: T.colors.danger,
    margin: 0,
    fontSize: '0.8125rem',
  },
  errorWrap: {
    padding: '1rem',
    display: 'flex',
    flexDirection: 'column',
    gap: '0.5rem',
    alignItems: 'flex-start',
  },
};
