import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { errorMessage, isNotFound } from '../../../shared/api';
import { useArtifactOutputs, useArtifactResult, useArtifactState } from '../../../shared/hooks/useApi';
import type { TaskResult } from '../../../shared/types';
import { merge } from '../../../shared/styles/recipes';
import * as T from '../../../shared/styles/tokens';

interface Props {
  taskId: string;
  result?: TaskResult | null;
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

// Artifacts tab: live STATE.md, latest RESULT.json (live file, else latest
// attempt snapshot), and the outputs/ deliverables listing.
export function StateTab({ taskId, result }: Props) {
  const stateQuery = useArtifactState(taskId);
  const resultQuery = useArtifactResult(taskId);
  const outputsQuery = useArtifactOutputs(taskId);

  if (stateQuery.isLoading) {
    return <p style={styles.loading}>Loading…</p>;
  }
  const state = stateQuery.data?.content ?? null;
  if (state == null) {
    const text = stateQuery.isError
      ? (isNotFound(stateQuery.error) ? 'STATE.md not available' : errorMessage(stateQuery.error))
      : 'Loading…';
    return <p style={stateQuery.isError ? styles.empty : styles.loading}>{text}</p>;
  }

  const statePath = stateQuery.data?.path || null;

  const resultJson = resultQuery.isError ? null : (resultQuery.data?.content ?? null);
  const outputs = outputsQuery.isError ? [] : (outputsQuery.data?.files ?? []);

  return (
    <div style={styles.container}>
      <div style={styles.toolbar}>
        {result && <ResultBadge result={result} />}
        {statePath && (
          <a
            href={`vscode://file/${statePath}`}
            style={styles.editorLink}
            title={statePath}
          >
            Open in editor
          </a>
        )}
      </div>
      <div style={styles.markdown}>
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{state}</ReactMarkdown>
      </div>
      <div style={styles.section}>
        <div style={styles.sectionLabel}>RESULT.json</div>
        <pre style={styles.pre}>{resultJson ?? '(no result declared yet)'}</pre>
      </div>
      <div style={styles.section}>
        <div style={styles.sectionLabel}>outputs/</div>
        <pre style={styles.pre}>
          {outputs.length === 0 ? '(empty)' : outputs.join('\n')}
        </pre>
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
  toolbar: {
    padding: '0.4rem 0.75rem',
    borderBottom: '1px solid #27272a',
    background: T.colors.bgSurface,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: '0.75rem',
  },
  editorLink: {
    fontSize: '0.75rem',
    color: T.colors.link,
    textDecoration: 'none',
  },
  resultBadge: {
    display: 'flex',
    alignItems: 'center',
    gap: '0.5rem',
    fontSize: '0.75rem',
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
  markdown: {
    flex: 1,
    overflowY: 'auto',
    padding: '1rem 1.25rem',
    color: T.colors.textPrimary,
    fontFamily: 'system-ui, sans-serif',
    fontSize: '0.875rem',
    lineHeight: 1.6,
  },
  section: {
    borderTop: '1px solid #27272a',
    padding: '0.5rem 1.25rem',
  },
  sectionLabel: {
    color: T.colors.textDim,
    fontWeight: 600,
    fontSize: '0.75rem',
    marginBottom: '0.25rem',
  },
  pre: {
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
    background: T.colors.bgDeeper,
    border: '1px solid #27272a',
    borderRadius: '4px',
    padding: '0.5rem',
    margin: 0,
    color: T.colors.textBody,
    fontSize: '0.75rem',
    maxHeight: '12rem',
    overflowY: 'auto',
  },
  loading: {
    padding: '1rem',
    color: T.colors.textDim,
  },
  empty: {
    padding: '1rem',
    color: T.colors.textMuted,
  },
};
