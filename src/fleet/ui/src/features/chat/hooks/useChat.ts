import { useEffect, useMemo, useState } from 'react';
import { api } from '../../../shared/api';
import { useChatQuestions } from '../../../shared/hooks/useApi';
import { useTaskMutation } from '../../../shared/hooks/useTaskMutation';
import { useToast } from '../../../shared/contexts/ToastContext';

export function useChat() {
  const { data } = useChatQuestions();
  const questions = useMemo(() => data?.pending ?? [], [data]);
  const serverOffset = data ? data.now - Date.now() / 1000 : 0;
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const { addToast } = useToast();

  useEffect(() => {
    setSelectedId(prev => {
      if (prev && questions.some(q => q.id === prev)) return prev;
      return questions.length > 0 ? questions[0].id : null;
    });
  }, [questions]);

  const answerMutation = useTaskMutation(
    'Answer question',
    ({ id, value }: { id: string; value: string | string[] }) => api.answerChatQuestion(id, value),
    {
      invalidate: [['chat-questions']],
      success: (res) => (res.ok ? 'Answer sent' : `Already ${res.status} — refreshing`),
      failure: 'Network error — try again.',
    },
  );

  const selectedQuestion = questions.find(q => q.id === selectedId) ?? null;

  return {
    questions,
    serverOffset,
    selectedQuestion,
    selectQuestion: setSelectedId,
    submitAnswer: (id: string, value: string | string[]) =>
      answerMutation.mutate({ id, value }, { onSuccess: () => setSelectedId(null) }),
    isSubmitting: answerMutation.isPending,
    notify: addToast,
  };
}
