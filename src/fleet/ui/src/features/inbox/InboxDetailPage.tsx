// Full-page answer view for one inbox question: the mobile path opened
// from the inbox list (desktop answers in the right pane instead).
// Rendered by App's /inbox/:id route.
import { Link, useParams } from 'react-router-dom';
import { colors } from '../../shared/styles/tokens';
import { useNow } from '../../shared/hooks/useNow';
import { EmptyState } from '../../shared/ui/EmptyState';
import { LoadingState } from '../../shared/ui/LoadingState';
import { PageShell } from '../../shared/ui/PageShell';
import { AnswerForm } from './AnswerForm';
import { useInboxBase } from './hooks/useInbox';

// One question with the answer form, a back link and sent/empty states.
export function InboxDetailPage() {
  const { id } = useParams();
  const { questions, serverOffset, isLoading, submitAnswer, isSubmitting, notify } = useInboxBase();
  const now = useNow();
  const question = questions.find((q) => q.id === id) ?? null;

  return (
    <PageShell title="Inbox">
      <div style={styles.wrap}>
        <Link to="/inbox" style={styles.back}>
          ← Back to inbox
        </Link>
        {isLoading && questions.length === 0 ? (
          <LoadingState message="Loading question…" />
        ) : !question ? (
          <EmptyState message="That question is already answered or gone." />
        ) : (
          <AnswerForm
            question={question}
            serverOffset={serverOffset}
            now={now}
            isSubmitting={isSubmitting}
            notify={notify}
            onSubmit={submitAnswer}
          />
        )}
      </div>
    </PageShell>
  );
}

const styles = {
  wrap: {
    maxWidth: '44rem',
  } as React.CSSProperties,
  back: {
    display: 'inline-block', marginBottom: '1rem',
    color: colors.link, textDecoration: 'none', fontSize: '0.875rem',
  } as React.CSSProperties,
};
