import { useEffect, useRef, useState } from 'react';
import { api } from '../../api';

interface Props {
  taskId: string;
}

export function StderrTab({ taskId }: Props) {
  const [content, setContent] = useState<string | null>(null);
  const bottomRef = useRef<HTMLPreElement>(null);

  useEffect(() => {
    api.getStderr(taskId).then(data => setContent(data.content));
  }, [taskId]);

  useEffect(() => {
    if (content != null && bottomRef.current) {
      bottomRef.current.scrollTop = bottomRef.current.scrollHeight;
    }
  }, [content]);

  if (content == null) {
    return <p style={styles.msg}>Loading…</p>;
  }

  if (!content) {
    return <p style={styles.msg}>No stderr output.</p>;
  }

  return (
    <pre ref={bottomRef} style={styles.pre}>
      {content}
    </pre>
  );
}

const styles: Record<string, React.CSSProperties> = {
  pre: {
    margin: 0,
    padding: '0.75rem',
    fontFamily: 'monospace',
    fontSize: '0.78rem',
    color: '#e4e4e7',
    background: '#09090b',
    flex: 1,
    overflow: 'auto',
    whiteSpace: 'pre-wrap',
    wordBreak: 'break-all',
    height: '100%',
    boxSizing: 'border-box',
  },
  msg: {
    padding: '1rem',
    color: '#71717a',
    margin: 0,
  },
};
