// Inbox page: pending ask_human questions in a shared DataList, answer
// form in the right pane on desktop. Rendered by App's /inbox route;
// /chat redirects here, /inbox/:id is the mobile full-page answer view.
import { Link, useNavigate } from 'react-router-dom';
import type { ChatQuestion } from '../../shared/types';
import { colors } from '../../shared/styles/tokens';
import { formatRelativeAge } from '../../shared/format';
import { useIsMobile } from '../../shared/hooks/useIsMobile';
import { useNow } from '../../shared/hooks/useNow';
import { DataList, type DataColumn } from '../../shared/ui/DataList';
import { EmptyState } from '../../shared/ui/EmptyState';
import { PageShell } from '../../shared/ui/PageShell';
import { AnswerForm } from './AnswerForm';
import { useInbox } from './hooks/useInbox';
import {
  fromLabel,
  isTriageQuestion,
  promptExcerpt,
  triageChipStyle,
  typeLabel,
  workerPathFor,
} from './questionMeta';

// GET /api/chat/questions exposes pending questions only, so Pending is
// the one sub-tab until an answered endpoint exists.
const TABS = [{ id: 'pending', label: 'Pending' }];

// "From" cell: link to the worker when the asker is a fleet task id.
function FromCell({ question }: { question: ChatQuestion }) {
  const path = workerPathFor(question);
  if (path) {
    return (
      <Link to={path} style={styles.link}>
        {fromLabel(question)}
      </Link>
    );
  }
  return <span>{fromLabel(question)}</span>;
}

// "Kind" cell: text/choice/multi tag plus the triage chip for proposals.
function KindCell({ question }: { question: ChatQuestion }) {
  return (
    <span style={styles.kind}>
      <span style={styles.kindTag}>{typeLabel(question)}</span>
      {isTriageQuestion(question) && <span style={triageChipStyle()}>triage</span>}
    </span>
  );
}

interface ColumnDeps {
  serverOffset: number;
  now: number;
}

function inboxColumns({ serverOffset, now }: ColumnDeps): Array<DataColumn<ChatQuestion>> {
  return [
    {
      key: 'asked',
      header: 'Asked',
      width: '4.5rem',
      render: (q) => <span title={`asked ${formatRelativeAge(q.created_at, serverOffset, now)} ago`}>{formatRelativeAge(q.created_at, serverOffset, now)}</span>,
    },
    {
      key: 'from',
      header: 'From',
      width: '9rem',
      render: (q) => <FromCell question={q} />,
    },
    {
      key: 'kind',
      header: 'Kind',
      width: '7rem',
      render: (q) => <KindCell question={q} />,
    },
    {
      key: 'priority',
      header: 'Priority',
      width: '4.5rem',
      render: (q) => (q.priority > 0 ? <span style={styles.prio}>{q.priority}</span> : <span>—</span>),
    },
    {
      key: 'prompt',
      header: 'Prompt',
      render: (q) => <span style={styles.excerpt}>{promptExcerpt(q.prompt)}</span>,
    },
  ];
}

// Pending list with a right-pane answer form (desktop) or navigation to
// the full-page answer view (mobile).
export function InboxPage() {
  const {
    questions,
    serverOffset,
    isLoading,
    selectedQuestion,
    selectQuestion,
    submitAnswer,
    isSubmitting,
    notify,
  } = useInbox();
  const now = useNow();
  const isMobile = useIsMobile();
  const navigate = useNavigate();

  function handleSelect(id: string) {
    if (isMobile) navigate(`/inbox/${id}`);
    else selectQuestion(id);
  }

  return (
    <PageShell
      title="Inbox"
      count={questions.length}
      tabs={TABS}
      activeTab="pending"
      // Pending is the only tab the API can fill; nothing to switch to.
      onTabChange={() => undefined}
    >
      <div style={styles.layout}>
        <div style={styles.list}>
          <DataList
            columns={inboxColumns({ serverOffset, now })}
            rows={questions}
            rowKey={(q) => q.id}
            onRowClick={(q) => handleSelect(q.id)}
            empty="No pending questions."
            loading={isLoading}
            loadingMessage="Loading questions…"
            selectedKey={selectedQuestion?.id ?? null}
          />
        </div>
        {!isMobile && (
          <div style={styles.detail}>
            {selectedQuestion ? (
              <AnswerForm
                question={selectedQuestion}
                serverOffset={serverOffset}
                now={now}
                isSubmitting={isSubmitting}
                notify={notify}
                onSubmit={submitAnswer}
              />
            ) : (
              <EmptyState
                message={questions.length ? 'Select a question to answer it.' : 'All caught up — no pending questions.'}
              />
            )}
          </div>
        )}
      </div>
    </PageShell>
  );
}

const styles = {
  layout: {
    display: 'flex', gap: '1rem', alignItems: 'flex-start',
  } as React.CSSProperties,
  list: {
    flex: 1, minWidth: 0,
  } as React.CSSProperties,
  detail: {
    flex: 1, minWidth: 0, maxWidth: '40rem',
    padding: '1rem 1.5rem',
    background: colors.bgSurface,
    border: `1px solid ${colors.borderSubtle}`,
    borderRadius: '0.5rem',
  } as React.CSSProperties,
  link: {
    color: colors.link, textDecoration: 'none',
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
    fontSize: '0.8125rem',
  } as React.CSSProperties,
  kind: {
    display: 'inline-flex', alignItems: 'center', gap: '0.375rem',
  } as React.CSSProperties,
  kindTag: {
    fontSize: '0.7rem', fontWeight: 600, letterSpacing: '0.04em',
    textTransform: 'uppercase' as const,
    color: colors.textSecondary,
  } as React.CSSProperties,
  prio: {
    color: colors.amberLight, fontWeight: 600,
  } as React.CSSProperties,
  excerpt: {
    display: 'block', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' as const,
    color: colors.textBody,
  } as React.CSSProperties,
};
