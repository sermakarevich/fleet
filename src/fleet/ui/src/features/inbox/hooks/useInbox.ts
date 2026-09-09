// Inbox data hook: pending questions, single selection and the answer
// mutation. Called by InboxPage (desktop two-pane) and InboxDetailPage
// (mobile full page); polling lives in useChatQuestions and the
// relative-time ticker in useNow.
import { useEffect, useMemo, useState } from 'react';
import { api } from '../../../shared/api';
import { useChatQuestions } from '../../../shared/hooks/useApi';
import { useTaskMutation } from '../../../shared/hooks/useTaskMutation';
import { useToast } from '../../../shared/contexts/ToastContext';

// Shared questions + answer mutation without any selection state.
export function useInboxBase() {
  const { data, isLoading } = useChatQuestions();
  const questions = useMemo(() => data?.pending ?? [], [data]);
  const serverOffset = data ? data.now - Date.now() / 1000 : 0;
  const { addToast } = useToast();

  const answerMutation = useTaskMutation(
    'Answer question',
    ({ id, value }: { id: string; value: string | string[] }) => api.answerChatQuestion(id, value),
    {
      invalidate: [['chat-questions']],
      success: (res) => (res.ok ? 'Answer sent' : `Already ${res.status} — refreshing`),
      failure: 'Network error — try again.',
    },
  );

  return {
    questions,
    serverOffset,
    isLoading,
    submitAnswer: (id: string, value: string | string[]) => answerMutation.mutate({ id, value }),
    isSubmitting: answerMutation.isPending,
    notify: addToast,
  };
}

// Desktop inbox: questions plus the selected row id (auto-selects the
// first pending question, keeps the selection while it stays pending,
// clears it once that question is answered).
export function useInbox() {
  const base = useInboxBase();
  const [selectedId, setSelectedId] = useState<string | null>(null);

  useEffect(() => {
    setSelectedId((prev) => {
      if (prev && base.questions.some((q) => q.id === prev)) return prev;
      return base.questions.length > 0 ? base.questions[0].id : null;
    });
  }, [base.questions]);

  return {
    ...base,
    selectedQuestion: base.questions.find((q) => q.id === selectedId) ?? null,
    selectQuestion: setSelectedId,
    submitAnswer: (id: string, value: string | string[]) =>
      base.submitAnswer(id, value),
  };
}
