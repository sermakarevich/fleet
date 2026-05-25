import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api } from '../api';
import type { CreateTaskInput, RuntimeConfig } from '../types';

export function useTasks() {
  return useQuery({ queryKey: ['tasks'], queryFn: api.getTasks, refetchInterval: 5000 });
}

export function useTask(id: string) {
  return useQuery({ queryKey: ['task', id], queryFn: () => api.getTask(id), refetchInterval: 3000 });
}

export function useQA(status?: string) {
  return useQuery({
    queryKey: ['qa', status],
    queryFn: () => api.getQA(status),
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

export function useConfig() {
  return useQuery({ queryKey: ['config'], queryFn: api.getConfig });
}

export function useKillTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.killTask(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['tasks'] }),
  });
}

export function useRequeueTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.requeueTask(id),
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
