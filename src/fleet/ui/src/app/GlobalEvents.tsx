import { useEffect, useRef } from 'react';
import { useMatch } from 'react-router-dom';
import { useChatQuestions } from '../shared/hooks/useApi';
import { useEventSocket } from '../shared/hooks/useEventSocket';
import { useNativeNotifications } from '../shared/hooks/useNativeNotifications';
import { useToast } from '../shared/contexts/ToastContext';
import { formatDuration } from '../shared/format';
import type { FleetEvent } from '../shared/types';
import { queryClient } from './queryClient';

interface TaskSocketMessage {
  task_id: string;
  event: FleetEvent;
}

function useDocumentTitle() {
  const { data } = useChatQuestions();
  const pendingCount = data?.pending.length ?? 0;
  const taskMatch = useMatch('/workers/:id');
  const taskId = taskMatch?.params.id;
  useEffect(() => {
    const prefix = pendingCount > 0 ? `(${pendingCount}) ` : '';
    const suffix = taskId ? ` - ${taskId}` : '';
    document.title = `${prefix}fleet${suffix}`;
  }, [pendingCount, taskId]);
}

// Wires the task websocket to toasts and native notifications, and keeps
// the document title in sync. Renders nothing; NavBar reads the shared
// socket status itself via useSocketStatus.
export function GlobalEvents() {
  useDocumentTitle();
  const { notify } = useNativeNotifications();
  const { addToast } = useToast();
  const seenAskHumanIds = useRef<Set<string>>(new Set());

  useEventSocket<TaskSocketMessage>('/ws/events', ({ task_id: taskId, event }) => {
    if (event.kind === 'ask_human') {
      const questionId = event.extra?.question_id as string | undefined;
      if (questionId && seenAskHumanIds.current.has(questionId)) return;
      if (questionId) seenAskHumanIds.current.add(questionId);
      const question = (event.extra?.question as string | undefined) ?? 'New question';
      addToast(`inbox: ${question.slice(0, 80)}`);
      const title = (event.extra?.task_title as string | undefined) ?? taskId;
      notify('ask_human', 'Fleet inbox', `${title}: ${question.slice(0, 100)}`);
      void queryClient.invalidateQueries({ queryKey: ['chat-questions'] });
    }
    if (event.kind === 'session_ended') {
      const result = (event.extra?.result as string | undefined) ?? '';
      if (result === 'success') {
        const durationSec = event.extra?.duration_sec as number | undefined;
        const filesTouched = event.extra?.files_touched as number | undefined;
        let summary = '';
        if (durationSec != null) {
          summary += ` in ${formatDuration(durationSec)}`;
        }
        if (filesTouched != null && filesTouched > 0) {
          summary += ` - ${filesTouched} file${filesTouched === 1 ? '' : 's'}`;
        }
        const msg = `${taskId} done${summary}`;
        addToast(msg);
        notify('completed', 'Fleet', msg);
      }
    }
  });

  return null;
}
