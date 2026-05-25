import { useEffect, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { api } from '../../api';

interface Props {
  taskId: string;
}

export function KnowledgeTab({ taskId }: Props) {
  const [content, setContent] = useState<string | null>(null);
  const [filePath, setFilePath] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const mtimeRef = useRef<number | null>(null);

  async function load(checkMtime = false) {
    try {
      const data = await api.getArtifactKnowledge(taskId);
      if (checkMtime && mtimeRef.current === data.mtime) return;
      mtimeRef.current = data.mtime;
      setContent(data.content);
      setFilePath(data.path);
      setError(null);
    } catch {
      if (!checkMtime) setError('Knowledge file not available');
    }
  }

  useEffect(() => {
    load();
    const timer = setInterval(() => load(true), 5000);
    return () => clearInterval(timer);
  }, [taskId]);

  if (error) {
    return <p style={styles.empty}>{error}</p>;
  }

  if (content == null) {
    return <p style={styles.loading}>Loading…</p>;
  }

  return (
    <div style={styles.container}>
      <div style={styles.toolbar}>
        {filePath && (
          <a
            href={`vscode://file/${filePath}`}
            style={styles.editorLink}
            title={filePath}
          >
            Open in editor
          </a>
        )}
      </div>
      <div style={styles.markdown}>
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
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
    justifyContent: 'flex-end',
  },
  editorLink: {
    fontSize: '0.75rem',
    color: '#60a5fa',
    textDecoration: 'none',
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
  loading: {
    padding: '1rem',
    color: '#71717a',
  },
  empty: {
    padding: '1rem',
    color: '#52525b',
  },
};
