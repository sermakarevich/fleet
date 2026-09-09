/**
 * Chat tab: pending questions on the left, answer form on the right.
 * Composes QuestionList and AnswerForm; polling lives in useChat and
 * the one-second relative-time ticker in useNow. Called by App's
 * /chat route.
 */
import { colors } from '../../shared/styles/tokens';
import { useChat } from './hooks/useChat';
import { useNow } from '../../shared/hooks/useNow';
import { QuestionList } from './QuestionList';
import { AnswerForm } from './AnswerForm';

// Two-pane chat layout with empty states.
export function ChatPage() {
  const {
    questions,
    serverOffset,
    selectedQuestion: selectedQ,
    selectQuestion,
    submitAnswer,
    isSubmitting,
    notify,
  } = useChat();
  const now = useNow();

  return (
    <div style={styles.root}>
      <QuestionList
        questions={questions}
        selectedId={selectedQ?.id ?? null}
        onSelect={selectQuestion}
        serverOffset={serverOffset}
        now={now}
      />
      <main style={styles.mainPane}>
        {!selectedQ ? (
          <div style={styles.emptyMain}>
            <div style={styles.emptyIcon}>✓</div>
            <div>
              {questions.length
                ? 'Select a question from the left.'
                : 'All caught up — no pending questions.'}
            </div>
          </div>
        ) : (
          <AnswerForm
            question={selectedQ}
            serverOffset={serverOffset}
            now={now}
            isSubmitting={isSubmitting}
            notify={notify}
            onSubmit={submitAnswer}
          />
        )}
      </main>
    </div>
  );
}

const styles = {
  root: {
    display: 'flex', height: 'calc(100vh - 2.5rem)', background: colors.bgDeep,
    color: colors.textPrimary, fontFamily: 'system-ui, sans-serif',
    fontSize: '0.875rem', lineHeight: 1.55, overflow: 'hidden',
  } as React.CSSProperties,
  mainPane: {
    flex: 1, height: '100%', overflowY: 'auto', padding: '2.5rem 3rem',
  } as React.CSSProperties,
  emptyMain: {
    height: '100%', display: 'flex', flexDirection: 'column' as const,
    alignItems: 'center', justifyContent: 'center', gap: '0.75rem', color: colors.textSecondary,
  } as React.CSSProperties,
  emptyIcon: {
    width: '2.875rem', height: '2.875rem', borderRadius: '50%', background: colors.bgElevated,
    display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '1.25rem',
  } as React.CSSProperties,
};
