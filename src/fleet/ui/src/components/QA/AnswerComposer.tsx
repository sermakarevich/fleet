import { useState } from 'react';
import * as T from '../../styles/tokens';

interface Props {
  choices?: string[] | null;
  onSubmit: (answer: string) => void;
  disabled?: boolean;
  placeholder?: string;
}

export function AnswerComposer({ choices, onSubmit, disabled, placeholder }: Props) {
  const [text, setText] = useState('');

  const handleSubmit = () => {
    const trimmed = text.trim();
    if (!trimmed) return;
    onSubmit(trimmed);
    setText('');
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  return (
    <div style={styles.container}>
      {choices && choices.length > 0 && (
        <div style={styles.choices}>
          {choices.map(c => (
            <button
              key={c}
              onClick={() => onSubmit(c)}
              disabled={disabled}
              style={styles.choiceBtn}
            >
              {c}
            </button>
          ))}
        </div>
      )}
      <div style={styles.row}>
        <textarea
          value={text}
          onChange={e => setText(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder ?? 'Type your answer… (Enter to send, Shift+Enter for newline)'}
          disabled={disabled}
          rows={2}
          style={styles.textarea}
        />
        <button
          onClick={handleSubmit}
          disabled={disabled || !text.trim()}
          style={styles.sendBtn}
        >
          Send
        </button>
      </div>
    </div>
  );
}

const styles = {
  container: {
    display: 'flex',
    flexDirection: 'column' as const,
    gap: '0.5rem',
  } as React.CSSProperties,
  choices: {
    display: 'flex',
    gap: '0.5rem',
    flexWrap: 'wrap' as const,
  } as React.CSSProperties,
  choiceBtn: {
    padding: '0.25rem 0.75rem',
    background: '#1d4ed8',
    color: '#fff',
    border: 'none',
    borderRadius: 4,
    cursor: 'pointer',
    fontSize: '0.8125rem',
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  row: {
    display: 'flex',
    gap: '0.5rem',
    alignItems: 'flex-end',
  } as React.CSSProperties,
  textarea: {
    flex: 1,
    resize: 'none' as const,
    background: T.colors.borderSubtle,
    border: `1px solid ${T.colors.border}`,
    borderRadius: 4,
    color: T.colors.textPrimary,
    padding: '0.5rem',
    fontSize: '0.875rem',
    fontFamily: 'system-ui, sans-serif',
  } as React.CSSProperties,
  sendBtn: {
    ...T.btnPrimary,
    padding: '0.5rem 1rem',
    border: 'none',
    flexShrink: 0,
  } as React.CSSProperties,
};
