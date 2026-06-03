import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../api';
import type { ChatQuestion } from '../types';

function typeLabel(q: ChatQuestion): string {
  if (!q.options) return 'text';
  return q.multi_select ? 'multi' : 'choice';
}

function relTime(ts: number, serverOffset: number): string {
  const s = Math.max(0, Math.floor(Date.now() / 1000 + serverOffset - ts));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

export function Chat() {
  const [questions, setQuestions] = useState<ChatQuestion[]>([]);
  const [serverOffset, setServerOffset] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const [toast, setToast] = useState<string | null>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  function showToast(msg: string) {
    setToast(msg);
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 2600);
  }

  const load = useCallback(async () => {
    try {
      const data = await api.getChatQuestions();
      setServerOffset(data.now - Date.now() / 1000);
      setQuestions(data.pending);
      setSelectedId(prev => {
        if (prev && data.pending.find(q => q.id === prev)) return prev;
        if (data.pending.length > 0) return data.pending[0].id;
        return null;
      });
    } catch {
      // ignore network errors between polls
    }
  }, []);

  useEffect(() => {
    load();
    const pollId = setInterval(load, 3000);
    return () => clearInterval(pollId);
  }, [load]);

  // Tick every second for relative-time display
  useEffect(() => {
    const id = setInterval(() => setTick(t => t + 1), 1000);
    return () => clearInterval(id);
  }, []);

  async function handleSubmit(ev: React.FormEvent<HTMLFormElement>) {
    ev.preventDefault();
    const q = questions.find(x => x.id === selectedId);
    if (!q) return;
    const form = ev.currentTarget;

    let answer: string | string[];
    if (q.options) {
      const checked = Array.from(
        form.querySelectorAll<HTMLInputElement>('input[name="answer"]:checked'),
      );
      if (!checked.length) { showToast('Pick an option first.'); return; }
      const vals = checked.map(c => c.value);
      answer = q.multi_select ? vals : vals[0];
    } else {
      const ta = form.querySelector<HTMLTextAreaElement>('textarea');
      const v = ta?.value.trim() ?? '';
      if (!v) { showToast('Type an answer first.'); return; }
      answer = v;
    }

    const btn = form.querySelector('button[type="submit"]') as HTMLButtonElement | null;
    if (btn) { btn.disabled = true; btn.textContent = 'Sending…'; }

    try {
      const res = await api.answerChatQuestion(q.id, answer);
      showToast(res.ok ? 'Answer sent' : `Already ${res.status} — refreshing`);
      setSelectedId(null);
      await load();
    } catch {
      if (btn) { btn.disabled = false; btn.textContent = q.options ? 'Submit answer' : 'Send'; }
      showToast('Network error — try again.');
    }
  }

  // suppress unused var warning for tick
  void tick;

  const rt = (ts: number) => relTime(ts, serverOffset);
  const selectedQ = questions.find(q => q.id === selectedId) ?? null;

  return (
    <div style={s.root}>
      {toast && <div style={s.toast}>{toast}</div>}

      <aside style={s.sidebar}>
        <div style={s.sideHead}>
          <div style={s.brand}>
            <span style={s.dot} />
            ask_human
          </div>
          <div style={s.count}>{questions.length} pending</div>
        </div>
        <div style={s.list}>
          {questions.length === 0 ? (
            <div style={s.emptyList}>No pending questions.</div>
          ) : questions.map(q => (
            <div
              key={q.id}
              style={{ ...s.item, ...(q.id === selectedId ? s.itemSel : {}) }}
              onClick={() => setSelectedId(q.id)}
            >
              <div style={s.itemTop}>
                <span style={s.agent}>{q.agent_id || 'unknown'}</span>
                <span style={s.age}>{rt(q.created_at)}</span>
              </div>
              <div style={s.preview}>{q.prompt}</div>
              <div style={s.tags}>
                <span style={s.tag}>{typeLabel(q)}</span>
                {q.priority > 0 && (
                  <span style={{ ...s.tag, ...s.tagPrio }}>prio {q.priority}</span>
                )}
                <span style={s.tagId}>{q.id.slice(0, 8)}</span>
              </div>
            </div>
          ))}
        </div>
      </aside>

      <main style={s.mainPane}>
        {!selectedQ ? (
          <div style={s.emptyMain}>
            <div style={s.emptyIcon}>✓</div>
            <div>
              {questions.length
                ? 'Select a question from the left.'
                : 'All caught up — no pending questions.'}
            </div>
          </div>
        ) : (
          <div>
            <div style={s.detailHead}>
              <div style={s.detailAgent}>{selectedQ.agent_id || 'unknown'}</div>
              <div style={s.detailMeta}>
                <span style={s.mono}>#{selectedQ.id.slice(0, 8)}</span>
                {selectedQ.session_id && <span>session {selectedQ.session_id}</span>}
                <span>asked {rt(selectedQ.created_at)} ago</span>
                {selectedQ.timeout_s != null && (
                  <span>timeout {Math.round(selectedQ.timeout_s)}s</span>
                )}
                {selectedQ.priority > 0 && (
                  <span style={s.prioText}>priority {selectedQ.priority}</span>
                )}
              </div>
            </div>

            <div style={s.detailPrompt}>{selectedQ.prompt}</div>

            <form key={selectedQ.id} style={s.answerForm} onSubmit={handleSubmit}>
              {selectedQ.options ? (
                <div style={s.options}>
                  {selectedQ.options.map((opt, i) => (
                    <label key={i} style={s.opt}>
                      <input
                        type={selectedQ.multi_select ? 'checkbox' : 'radio'}
                        name="answer"
                        value={opt}
                        style={s.optInput}
                      />
                      <span style={s.optText}>{opt}</span>
                    </label>
                  ))}
                </div>
              ) : (
                <textarea
                  name="answer"
                  style={s.textarea}
                  placeholder="Type your answer…"
                  autoFocus
                  onKeyDown={e => {
                    if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
                      (e.currentTarget.form as HTMLFormElement).requestSubmit();
                    }
                  }}
                />
              )}
              <div style={s.actions}>
                <button type="submit" style={s.submitBtn}>
                  {selectedQ.options ? 'Submit answer' : 'Send'}
                </button>
                {!selectedQ.options && <span style={s.hint}>⌘/Ctrl + Enter</span>}
                {selectedQ.default_answer != null && (
                  <span style={s.hint}>
                    default on timeout:{' '}
                    {Array.isArray(selectedQ.default_answer)
                      ? selectedQ.default_answer.join(', ')
                      : selectedQ.default_answer}
                  </span>
                )}
              </div>
            </form>
          </div>
        )}
      </main>
    </div>
  );
}

const s: Record<string, React.CSSProperties> = {
  root: {
    display: 'flex',
    height: 'calc(100vh - 40px)',
    background: '#0d0f14',
    color: '#e7e9ee',
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif',
    fontSize: 14,
    lineHeight: 1.55,
    overflow: 'hidden',
  },

  // Sidebar
  sidebar: {
    width: 340,
    minWidth: 300,
    height: '100%',
    background: '#15181f',
    borderRight: '1px solid #272c37',
    display: 'flex',
    flexDirection: 'column',
    flexShrink: 0,
  },
  sideHead: {
    padding: '16px 18px',
    borderBottom: '1px solid #272c37',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  brand: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    fontWeight: 700,
    fontSize: 15,
    color: '#e7e9ee',
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: '50%',
    background: '#22c55e',
    boxShadow: '0 0 0 3px rgba(34,197,94,.18)',
    display: 'inline-block',
    flexShrink: 0,
  },
  count: {
    color: '#98a2b3',
    fontSize: 12.5,
    fontWeight: 500,
    fontVariantNumeric: 'tabular-nums',
  },
  list: {
    flex: 1,
    overflowY: 'auto',
    padding: 8,
  },
  emptyList: {
    padding: '40px 12px',
    textAlign: 'center',
    color: '#98a2b3',
    fontSize: 13,
  },

  // Sidebar item
  item: {
    padding: '11px 12px',
    marginBottom: 4,
    border: '1px solid transparent',
    borderRadius: 10,
    cursor: 'pointer',
  },
  itemSel: {
    background: '#1e2233',
    borderColor: '#818cf8',
  },
  itemTop: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'baseline',
    gap: 8,
  },
  agent: {
    fontWeight: 600,
    fontSize: 13,
    whiteSpace: 'nowrap',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    color: '#e7e9ee',
  },
  age: {
    color: '#98a2b3',
    fontSize: 11.5,
    whiteSpace: 'nowrap',
    fontVariantNumeric: 'tabular-nums',
  },
  preview: {
    color: '#98a2b3',
    fontSize: 12.5,
    marginTop: 3,
    overflow: 'hidden',
    display: '-webkit-box',
    WebkitLineClamp: 2,
    WebkitBoxOrient: 'vertical',
  },
  tags: {
    display: 'flex',
    gap: 6,
    alignItems: 'center',
    marginTop: 8,
    flexWrap: 'wrap',
  },
  tag: {
    fontSize: 10.5,
    fontWeight: 600,
    letterSpacing: '0.4px',
    textTransform: 'uppercase',
    padding: '1px 7px',
    borderRadius: 9999,
    background: '#1b1f28',
    color: '#98a2b3',
  },
  tagPrio: {
    background: '#2a2310',
    color: '#fbbf24',
  },
  tagId: {
    marginLeft: 'auto',
    color: '#98a2b3',
    fontSize: 11,
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
  },

  // Main pane
  mainPane: {
    flex: 1,
    height: '100%',
    overflowY: 'auto',
    padding: '40px 48px',
  },
  emptyMain: {
    height: '100%',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 12,
    color: '#98a2b3',
  },
  emptyIcon: {
    width: 46,
    height: 46,
    borderRadius: '50%',
    background: '#1b1f28',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: 20,
  },

  // Detail
  detailHead: {
    marginBottom: 6,
  },
  detailAgent: {
    fontSize: 22,
    fontWeight: 700,
    color: '#e7e9ee',
  },
  detailMeta: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: '6px 14px',
    marginTop: 8,
    color: '#98a2b3',
    fontSize: 12.5,
  },
  mono: {
    fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
    color: '#98a2b3',
  },
  prioText: {
    color: '#fbbf24',
    fontWeight: 600,
  },
  detailPrompt: {
    fontSize: 18,
    fontWeight: 500,
    lineHeight: 1.5,
    margin: '18px 0 26px',
    whiteSpace: 'pre-wrap',
    color: '#e7e9ee',
  },

  // Answer form
  answerForm: {
    maxWidth: 620,
  },
  options: {
    display: 'flex',
    flexDirection: 'column',
    gap: 8,
  },
  opt: {
    display: 'flex',
    alignItems: 'center',
    gap: 11,
    padding: '13px 15px',
    cursor: 'pointer',
    border: '1px solid #272c37',
    borderRadius: 11,
    background: '#15181f',
  },
  optInput: {
    width: 17,
    height: 17,
    margin: 0,
    accentColor: '#818cf8',
    flexShrink: 0,
  },
  optText: {
    fontSize: 14.5,
    color: '#e7e9ee',
  },
  textarea: {
    width: '100%',
    minHeight: 84,
    padding: '13px 15px',
    font: 'inherit',
    resize: 'vertical',
    color: '#e7e9ee',
    background: '#15181f',
    border: '1px solid #272c37',
    borderRadius: 11,
    boxSizing: 'border-box',
  },
  actions: {
    display: 'flex',
    alignItems: 'center',
    gap: 14,
    marginTop: 18,
  },
  submitBtn: {
    padding: '11px 20px',
    border: 0,
    borderRadius: 10,
    background: '#818cf8',
    color: '#fff',
    fontSize: 14,
    fontWeight: 600,
    cursor: 'pointer',
    fontFamily: 'inherit',
  },
  hint: {
    color: '#98a2b3',
    fontSize: 12.5,
  },

  // Toast
  toast: {
    position: 'fixed',
    bottom: 22,
    left: '50%',
    transform: 'translateX(-50%)',
    background: '#2a2f3a',
    color: '#fff',
    padding: '10px 18px',
    borderRadius: 10,
    fontSize: 13,
    boxShadow: '0 8px 24px rgba(0,0,0,.2)',
    zIndex: 1000,
    pointerEvents: 'none',
  },
};
