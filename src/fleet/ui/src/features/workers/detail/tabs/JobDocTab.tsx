import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { errorMessage, isNotFound } from '../../../../shared/api';
import { useArtifactDoc } from '../../../../shared/hooks/useApi';
import * as T from '../../../../shared/styles/tokens';

interface Props {
  taskId: string;
  kind: 'research' | 'design';
}

const MISSING_COPY: Record<Props['kind'], string> = {
  research: 'RESEARCH.md not available',
  design: 'DESIGN.md not available',
};

// Job worker document tab: RESEARCH.md / DESIGN.md (see workers/job.py).
// Hidden unless the artifact exists; polling lives in useArtifactDoc.
export function JobDocTab({ taskId, kind }: Props) {
  const { data, isLoading, isError, error } = useArtifactDoc(taskId, kind);

  if (isLoading || data == null) {
    if (isError && data == null) {
      const text = !isNotFound(error) ? errorMessage(error) : MISSING_COPY[kind];
      return <p style={styles.empty}>{text}</p>;
    }
    return <p style={styles.loading}>Loading…</p>;
  }

  return (
    <div style={styles.container}>
      <div style={styles.toolbar}>
        {data.path && (
          <a
            href={`vscode://file/${data.path}`}
            style={styles.editorLink}
            title={data.path}
          >
            Open in editor
          </a>
        )}
      </div>
      <div style={styles.markdown}>
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{data.content}</ReactMarkdown>
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
    borderBottom: `1px solid ${T.colors.borderSubtle}`,
    background: T.colors.bgSurface,
    display: 'flex',
    justifyContent: 'flex-end',
  },
  editorLink: {
    fontSize: '0.75rem',
    color: T.colors.link,
    textDecoration: 'none',
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
  loading: {
    padding: '1rem',
    color: T.colors.textDim,
  },
  empty: {
    padding: '1rem',
    color: T.colors.textMuted,
  },
};
