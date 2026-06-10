import { useQuery } from '@tanstack/react-query';
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter';
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism';
import { api } from '../../api';

interface Props {
  taskId: string;
  status?: string;
}

export function DiffTab({ taskId, status }: Props) {
  const { data, isLoading } = useQuery({
    queryKey: ['task', taskId, 'diff'],
    queryFn: () => api.getDiff(taskId),
    refetchInterval: !status || status === 'in_progress' ? 5000 : false,
  });

  const diff = data?.diff ?? null;

  if (isLoading && !data) return <p style={styles.msg}>Loading…</p>;
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
