import { useCallback, useState } from 'react';
import type { FleetEvent, TaskSummary } from '../types';

export function useTasksState(initialTasks: TaskSummary[]) {
  const [tasks, setTasks] = useState<TaskSummary[]>(initialTasks);

  const updateFromEvent = useCallback((taskId: string, event: FleetEvent) => {
    setTasks(prev =>
      prev.map(task => {
        if (task.id !== taskId) return task;
        const updates: Partial<TaskSummary> = {
          last_event_kind: event.kind,
          last_event_detail: event.tool_name,
          idle_sec: 0,
        };
        if (event.usage != null) {
          const input = event.usage.input_tokens ?? 0;
          const cacheRead = event.usage.cache_read_input_tokens ?? 0;
          const cacheCreate = event.usage.cache_creation_input_tokens ?? 0;
          updates.context_tokens = input + cacheRead + cacheCreate;
        }
        return { ...task, ...updates };
      }),
    );
  }, []);

  return { tasks, setTasks, updateFromEvent };
}
