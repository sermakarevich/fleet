import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { api } from '../../../shared/api';
import { useChatQuestions } from '../../../shared/hooks/useApi';
import { useToast } from '../../../shared/contexts/ToastContext';

export function useChat() {
  const { data } = useChatQuestions();
  const questions = useMemo(() => data?.pending ?? [], [data]);
  const serverOffset = data ? data.now - Date.now() / 1000 : 0;
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const { addToast } = useToast();
  const qc = useQueryClient();

  useEffect(() => {
    setSelectedId(prev => {
      if (prev && questions.some(q => q.id === prev)) return prev;
      return questions.length > 0 ? questions[0].id : null;
    });
  }, [questions]);

  const answerMutation = useMutation({
    mutationFn: ({ id, value }: { id: string; value: string | string[] }) =>
      api.answerChatQuestion(id, value),
    onSuccess: res => {
      addToast(res.ok ? 'Answer sent' : `Already ${res.status} — refreshing`);
      setSelectedId(null);
      void qc.invalidateQueries({ queryKey: ['chat-questions'] });
    },
    onError: () => addToast('Network error — try again.'),
  });

  const selectedQuestion = questions.find(q => q.id === selectedId) ?? null;

  return {
    questions,
    serverOffset,
    selectedQuestion,
    selectQuestion: setSelectedId,
    submitAnswer: (id: string, value: string | string[]) => answerMutation.mutate({ id, value }),
    isSubmitting: answerMutation.isPending,
    notify: addToast,
  };
}
