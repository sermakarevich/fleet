import { useCallback, useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { api } from '../../../shared/api';
import type { TaskResult } from '../../../shared/types';
import { merge } from '../../../shared/styles/recipes';

interface Props {
  taskId: string;
  result?: TaskResult | null;
}

const RESULT_BADGE_COLOR: Record<TaskResult['status'], string> = {
  done: '#22c55e',
  partial: '#eab308',
  blocked: '#ef4444',
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
  const [state, setState] = useState<string | null>(null);
  const [statePath, setStatePath] = useState<string | null>(null);
  const [stateError, setStateError] = useState<string | null>(null);
  const [resultJson, setResultJson] = useState<string | null>(null);
  const [outputs, setOutputs] = useState<string[]>([]);
  const mtimeRef = useRef<number | null>(null);

  const load = useCallback(async (checkMtime = false) => {
    try {
      const data = await api.getArtifactState(taskId);
      if (checkMtime && mtimeRef.current === data.mtime) return;
      mtimeRef.current = data.mtime;
      setState(data.content);
      setStatePath(data.path || null);
      setStateError(null);
    } catch {
      if (!checkMtime) setStateError('STATE.md not available');
    }
    try {
      const data = await api.getArtifactResult(taskId);
      setResultJson(data.content);
    } catch {
      if (!checkMtime) setResultJson(null);
    }
    try {
      const data = await api.getArtifactOutputs(taskId);
      setOutputs(data.files);
    } catch {
      if (!checkMtime) setOutputs([]);
    }
  }, [taskId]);

  useEffect(() => {
    load();
    const timer = setInterval(() => load(true), 5000);
    return () => clearInterval(timer);
  }, [load]);

  if (stateError) {
    return <p style={styles.empty}>{stateError}</p>;
  }

  if (state == null) {
    return <p style={styles.loading}>Loading…</p>;
  }

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
    background: '#18181b',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    gap: '0.75rem',
  },
  editorLink: {
    fontSize: '0.75rem',
    color: '#60a5fa',
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
    color: '#e4e4e7',
  },
  resultSummary: {
    color: '#a1a1aa',
  },
  markdown: {
    flex: 1,
    overflowY: 'auto',
    padding: '1rem 1.25rem',
    color: '#e4e4e7',
    fontFamily: 'system-ui, sans-serif',
    fontSize: '0.875rem',
    lineHeight: 1.6,
  },
  section: {
    borderTop: '1px solid #27272a',
    padding: '0.5rem 1.25rem',
  },
  sectionLabel: {
    color: '#71717a',
    fontWeight: 600,
    fontSize: '0.75rem',
    marginBottom: '0.25rem',
  },
  pre: {
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-word',
    background: '#0f0f12',
    border: '1px solid #27272a',
    borderRadius: '4px',
    padding: '0.5rem',
    margin: 0,
    color: '#d4d4d8',
    fontSize: '0.75rem',
    maxHeight: '12rem',
    overflowY: 'auto',
  },
  loading: {
    padding: '1rem',
    color: '#71717a',
  },
  empty: {
    padding: '1rem',
    color: '#52525b',
  },
};
