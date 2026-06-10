import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';
import type { CreateTaskInput, RuntimeConfig, TaskSummary } from '../types';
import { useToast } from '../contexts/ToastContext';

export function useTasks() {
  return useQuery({ queryKey: ['tasks'], queryFn: api.getTasks, refetchInterval: 5000 });
}

export function useTask(id: string) {
  const qc = useQueryClient();
  return useQuery({
    queryKey: ['task', id],
    queryFn: async () => {
      const task = await api.getTask(id);
      // /api/tasks/{id} reads task.json directly (stale). Overlay with the
      // beads-reconciled status from the list cache when available.
      const list = qc.getQueryData<TaskSummary[]>(['tasks']);
      const listed = list?.find(t => t.id === id);
      if (listed) task.status = listed.status;
      return task;
    },
    refetchInterval: 3000,
  });
}

export function useBeads() {
  return useQuery({ queryKey: ['beads'], queryFn: api.getBeads, refetchInterval: 5000 });
}

export function useBead(id: string | null) {
  return useQuery({
    queryKey: ['bead', id],
    queryFn: () => api.getBead(id as string),
    enabled: !!id,
    refetchInterval: 3000,
  });
}

export function useSetBeadStatus() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) => api.setBeadStatus(id, status),
    onSuccess: (_data, vars) => {
      void qc.invalidateQueries({ queryKey: ['beads'] });
      void qc.invalidateQueries({ queryKey: ['bead', vars.id] });
    },
  });
}

export function useUnblockBead() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.unblockBead(id),
    onSuccess: (_data, id) => {
      void qc.invalidateQueries({ queryKey: ['beads'] });
      void qc.invalidateQueries({ queryKey: ['bead', id] });
    },
  });
}

export function useRemoveBeadAssignee() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.removeBeadAssignee(id),
    onSuccess: (_data, id) => {
      void qc.invalidateQueries({ queryKey: ['beads'] });
      void qc.invalidateQueries({ queryKey: ['bead', id] });
    },
  });
}

export function useQA(status?: string) {
  return useQuery({
    queryKey: ['qa', status],
    queryFn: () => api.getQA(status),
    refetchInterval: 3000,
  });
}

export function useChatQuestions() {
  return useQuery({
    queryKey: ['chat-questions'],
    queryFn: api.getChatQuestions,
    refetchInterval: 3000,
  });
}

export function useSupervisor() {
  return useQuery({
    queryKey: ['supervisor'],
    queryFn: api.getSupervisor,
    refetchInterval: 5000,
  });
}

export function useHealthz() {
  return useQuery({
    queryKey: ['healthz'],
    queryFn: api.getHealthz,
    refetchInterval: 30000,
  });
}

export function useConfig() {
  return useQuery({ queryKey: ['config'], queryFn: api.getConfig });
}

const KILL_MESSAGES: Record<string, string> = {
  killing: 'Kill signal sent — task will stop shortly.',
  'supervisor-not-running': 'Kill signal written, but the supervisor is not running.',
  'task-not-running': 'Task is not currently running — nothing to kill.',
};

export function useKillTask() {
  const qc = useQueryClient();
  const { addToast } = useToast();
  return useMutation({
    mutationFn: (id: string) => api.killTask(id),
    onSuccess: (data, id) => {
      void qc.invalidateQueries({ queryKey: ['tasks'] });
      void qc.invalidateQueries({ queryKey: ['task', id] });
      addToast(KILL_MESSAGES[data.result] ?? `Kill result: ${data.result}`);
    },
    onError: (err: unknown) => {
      addToast(`Kill failed: ${err instanceof Error ? err.message : String(err)}`);
    },
  });
}

export function useRequeueTask() {
  const qc = useQueryClient();
  const { addToast } = useToast();
  return useMutation({
    mutationFn: (id: string) => api.requeueTask(id),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['tasks'] });
      addToast('Task re-queued.');
    },
    onError: (err: unknown) => {
      addToast(`Re-queue failed: ${err instanceof Error ? err.message : String(err)}`);
    },
  });
}

export function useCloseTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.closeTask(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['tasks'] }),
  });
}

export function useDeleteTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteTask(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['tasks'] }),
  });
}

export function useRemoveAssignee() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.removeAssignee(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['tasks'] }),
  });
}

export function useCreateTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: CreateTaskInput) => api.createTask(payload),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['tasks'] }),
  });
}

export function useAnswerQuestion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, answer }: { id: string; answer: string }) =>
      api.answerQuestion(id, answer),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['qa'] }),
  });
}

export function useDeferQuestion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deferQuestion(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['qa'] }),
  });
}

export function usePutConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (updates: Partial<RuntimeConfig>) => api.putConfig(updates),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['config'] }),
  });
}

export function useCoders() {
  return useQuery({ queryKey: ['coders'], queryFn: api.getCoders });
}

export function useTemplates() {
  return useQuery({ queryKey: ['templates'], queryFn: api.getTemplates });
}

export function usePauseSupervisor() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.pauseSupervisor(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['supervisor'] }),
  });
}

export function useResumeSupervisor() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.resumeSupervisor(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['supervisor'] }),
  });
}

export function useRestartSupervisor() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.restartSupervisor(),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['supervisor'] }),
  });
}

export function useAnalytics() {
  const throughput = useQuery({ queryKey: ['analytics', 'throughput'], queryFn: () => api.getAnalytics('throughput') });
  const leaderboard = useQuery({ queryKey: ['analytics', 'leaderboard'], queryFn: () => api.getAnalytics('leaderboard') });
  const burnouts = useQuery({ queryKey: ['analytics', 'burnouts'], queryFn: () => api.getAnalytics('burnouts') });
  const rateLimits = useQuery({ queryKey: ['analytics', 'rate-limits'], queryFn: () => api.getAnalytics('rate-limits') });
  const perProject = useQuery({ queryKey: ['analytics', 'per-project'], queryFn: () => api.getAnalytics('per-project') });

  const loading =
    throughput.isLoading ||
    leaderboard.isLoading ||
    burnouts.isLoading ||
    rateLimits.isLoading ||
    perProject.isLoading;

  return {
    throughput: throughput.data,
    leaderboard: leaderboard.data,
    burnouts: burnouts.data,
    rateLimits: rateLimits.data,
    perProject: perProject.data,
    loading,
  };
}
