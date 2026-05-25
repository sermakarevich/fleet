import { useEffect, useState } from 'react';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { api } from '../../api';

interface Props {
  taskId: string;
}

export function DiffTab({ taskId }: Props) {
  const [diff, setDiff] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    api.getDiff(taskId)
      .then(data => { setDiff(data.diff); setLoading(false); })
      .catch(() => { setDiff(''); setLoading(false); });
  }, [taskId]);

  if (loading) return <p style={styles.msg}>Loading…</p>;
  if (!diff) return <p style={styles.msg}>No diff available.</p>;

  return (
    <div style={styles.container}>
      <SyntaxHighlighter
        language="diff"
        style={oneDark}
        customStyle={{ margin: 0, borderRadius: 0, flex: 1, fontSize: '0.78rem' }}
        showLineNumbers
        wrapLines
      >
        {diff}
      </SyntaxHighlighter>
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
    overflow: 'auto',
  },
  msg: {
    padding: '1rem',
    color: '#71717a',
    margin: 0,
  },
};
