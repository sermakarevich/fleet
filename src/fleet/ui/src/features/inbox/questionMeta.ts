// Question metadata helpers for the inbox: triage detection, kind label,
// "from" label, worker link target and prompt excerpt. Rendered by
// InboxPage (DataList columns) and AnswerForm (header chips).
import type { CSSProperties } from 'react';
import type { ChatQuestion } from '../../shared/types';
import { colors } from '../../shared/styles/tokens';

// Triage proposals are asked by the supervisor loop (agent_id 'triage');
// older rows may carry a "[triage]" prompt prefix instead.
export function isTriageQuestion(q: ChatQuestion): boolean {
  return q.agent_id === 'triage' || q.prompt.startsWith('[triage]');
}

// Short kind tag: text, choice or multi.
export function typeLabel(q: ChatQuestion): string {
  if (!q.options) return 'text';
  return q.multi_select ? 'multi' : 'choice';
}

// Who asked: the fleet task id when there is one, else the agent id.
export function fromLabel(q: ChatQuestion): string {
  return q.task_id ?? q.agent_id ?? 'unknown';
}

// Worker detail path for the asker, or null when it is not a fleet task.
export function workerPathFor(q: ChatQuestion): string | null {
  return q.task_id ? `/workers/${q.task_id}` : null;
}

// First maxLen characters of the prompt, cut at a word boundary.
export function promptExcerpt(prompt: string, maxLen = 120): string {
  const flat = prompt.replace(/\s+/g, ' ').trim();
  if (flat.length <= maxLen) return flat;
  const cut = flat.lastIndexOf(' ', maxLen);
  return `${flat.slice(0, cut === -1 ? maxLen : cut)}…`;
}

// Violet "triage" chip used by the kind column and the answer header.
export function triageChipStyle(): CSSProperties {
  return {
    display: 'inline-flex',
    alignItems: 'center',
    padding: '0.05rem 0.4rem',
    borderRadius: '0.25rem',
    fontSize: '0.7rem',
    fontWeight: 600,
    background: colors.violet,
    color: colors.white,
  };
}
