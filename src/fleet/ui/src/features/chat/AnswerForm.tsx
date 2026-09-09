/**
 * Selected question detail plus the answer form.
 * Called by ChatPage; parses the form into a string|string[] answer
 * and hands it to the chat hook's submit.
 */
import { useEffect, useRef } from 'react';
import type { ChatQuestion } from '../../shared/types';
import { colors } from '../../shared/styles/tokens';
import { formatRelativeAge } from '../../shared/format';

interface Props {
  question: ChatQuestion;
  serverOffset: number;
  now: number;
  isSubmitting: boolean;
  notify: (msg: string) => void;
  onSubmit: (id: string, answer: string | string[]) => void;
}

// Read the answer out of the submitted form.
function readAnswer(form: HTMLFormElement, q: ChatQuestion): string | string[] | null {
  if (q.options) {
    const checked = Array.from(form.querySelectorAll<HTMLInputElement>('input[name="answer"]:checked'));
    if (!checked.length) return null;
    const vals = checked.map((c) => c.value);
    return q.multi_select ? vals : vals[0];
  }
  const v = form.querySelector<HTMLTextAreaElement>('textarea')?.value.trim() ?? '';
  return v || null;
}

// Detail header, prompt and answer form for one question.
export function AnswerForm({ question: q, serverOffset, now, isSubmitting, notify, onSubmit }: Props) {
  const answerRef = useRef<HTMLTextAreaElement>(null);

  // Focus the answer box when a new question is selected (the autoFocus
  // prop is banned by jsx-a11y, so focus imperatively on question change).
  useEffect(() => {
    answerRef.current?.focus();
  }, [q.id]);

  function handleSubmit(ev: React.FormEvent<HTMLFormElement>) {
    ev.preventDefault();
    const answer = readAnswer(ev.currentTarget, q);
    if (answer == null) {
      notify(q.options ? 'Pick an option first.' : 'Type an answer first.');
      return;
    }
    onSubmit(q.id, answer);
  }

  return (
    <div>
      <div style={styles.detailHead}>
        <div style={styles.detailAgent}>{q.agent_id || 'unknown'}</div>
        <div style={styles.detailMeta}>
          <span style={styles.mono}>#{q.id.slice(0, 8)}</span>
          {q.session_id && <span>session {q.session_id}</span>}
          <span>asked {formatRelativeAge(q.created_at, serverOffset, now)} ago</span>
          {q.timeout_s != null && <span>timeout {Math.round(q.timeout_s)}s</span>}
          {q.priority > 0 && <span style={styles.prioText}>priority {q.priority}</span>}
        </div>
      </div>

      <div style={styles.detailPrompt}>{q.prompt}</div>

      <form key={q.id} style={styles.answerForm} onSubmit={handleSubmit}>
        {q.options ? (
          <div style={styles.options}>
            {q.options.map((opt, i) => (
              <label key={i} style={styles.opt}>
                <input
                  type={q.multi_select ? 'checkbox' : 'radio'}
                  name="answer"
                  value={opt}
                  style={styles.optInput}
                />
                <span style={styles.optText}>{opt}</span>
              </label>
            ))}
          </div>
        ) : (
          <textarea
            name="answer"
            ref={answerRef}
            style={styles.textarea}
            placeholder="Type your answer…"
            onKeyDown={(e) => {
              if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
                (e.currentTarget.form as HTMLFormElement).requestSubmit();
              }
            }}
          />
        )}
        <div style={styles.actions}>
          <button type="submit" style={styles.submitBtn} disabled={isSubmitting}>
            {isSubmitting ? 'Sending…' : q.options ? 'Submit answer' : 'Send'}
          </button>
          {!q.options && <span style={styles.hint}>⌘/Ctrl + Enter</span>}
          {q.default_answer != null && (
            <span style={styles.hint}>
              default on timeout:{' '}
              {Array.isArray(q.default_answer) ? q.default_answer.join(', ') : q.default_answer}
            </span>
          )}
        </div>
      </form>
    </div>
  );
}

const styles = {
  detailHead: {
    marginBottom: 6,
  } as React.CSSProperties,
  detailAgent: {
    fontSize: 22, fontWeight: 700, color: colors.textPrimary,
  } as React.CSSProperties,
  detailMeta: {
    display: 'flex', flexWrap: 'wrap' as const, gap: '6px 14px',
    marginTop: 8, color: colors.textSecondary, fontSize: 12.5,
  } as React.CSSProperties,
  mono: {
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
    color: colors.textSecondary,
  } as React.CSSProperties,
  prioText: {
    color: colors.amberLight, fontWeight: 600,
  } as React.CSSProperties,
  detailPrompt: {
    fontSize: 18, fontWeight: 500, lineHeight: 1.5,
    margin: '18px 0 26px', whiteSpace: 'pre-wrap' as const, color: colors.textPrimary,
  } as React.CSSProperties,
  answerForm: {
    maxWidth: 620,
  } as React.CSSProperties,
  options: {
    display: 'flex', flexDirection: 'column' as const, gap: 8,
  } as React.CSSProperties,
  opt: {
    display: 'flex', alignItems: 'center', gap: 11, padding: '13px 15px',
    cursor: 'pointer', border: `1px solid ${colors.borderSubtle}`,
    borderRadius: 11, background: colors.bgSurface,
  } as React.CSSProperties,
  optInput: {
    width: 17, height: 17, margin: 0, accentColor: colors.periwinkle, flexShrink: 0,
  } as React.CSSProperties,
  optText: {
    fontSize: 14.5, color: colors.textPrimary,
  } as React.CSSProperties,
  textarea: {
    width: '100%', minHeight: 84, padding: '13px 15px', font: 'inherit',
    resize: 'vertical' as const, color: colors.textPrimary,
    background: colors.bgSurface, border: `1px solid ${colors.borderSubtle}`,
    borderRadius: 11, boxSizing: 'border-box' as const,
  } as React.CSSProperties,
  actions: {
    display: 'flex', alignItems: 'center', gap: 14, marginTop: 18,
  } as React.CSSProperties,
  submitBtn: {
    padding: '11px 20px', border: 0, borderRadius: 10, background: colors.periwinkle,
    color: colors.white, fontSize: 14, fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit',
  } as React.CSSProperties,
  hint: {
    color: colors.textSecondary, fontSize: 12.5,
  } as React.CSSProperties,
};
