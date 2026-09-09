/**
 * One react-query hook per backend endpoint (queries) plus every action
 * (mutations via useTaskMutation, so each failure toasts). Polling uses
 * POLL cadences and pauses while the events socket streams. Called by
 * every page, tab and palette in the UI.
 */
import { useMutation, useQuery } from '@tanstack/react-query';
import { api, errorMessage } from '../api';
import { usePoll } from '../poll';
import type { CreateTaskInput, RuntimeConfig, ScheduleInput, WorkflowInput } from '../types';
import { useTaskMutation } from './useTaskMutation';
import { useDebounced } from './useDebounced';

export function useTasks() {
  return useQuery({ queryKey: ['tasks'], queryFn: api.getTasks, refetchInterval: usePoll('normal') });
}

export function useTask(id: string) {
  // GET /api/tasks/{id} already returns the beads-reconciled status, so no
  // client-side overlay from the list cache is needed here.
  return useQuery({
    queryKey: ['task', id],
    queryFn: () => api.getTask(id),
    refetchInterval: usePoll('fast'),
  });
}

export function useTaskChildren(id: string) {
  return useQuery({
    queryKey: ['task-children', id],
    queryFn: () => api.getTaskChildren(id),
    refetchInterval: usePoll('normal'),
  });
}

// Fetched lazily when an attempt row in the Attempts timeline is expanded.
export function useAttemptSummary(taskId: string, n: number, enabled: boolean) {
  return useQuery({
    queryKey: ['attempt-summary', taskId, n],
    queryFn: () => api.getAttemptSummary(taskId, n),
    enabled,
  });
}

export function useAttemptPrompt(taskId: string, n: number, enabled: boolean) {
  return useQuery({
    queryKey: ['attempt-prompt', taskId, n],
    queryFn: () => api.getAttemptPrompt(taskId, n),
    enabled,
  });
}

export function useBeads() {
  return useQuery({ queryKey: ['beads'], queryFn: api.getBeads, refetchInterval: usePoll('normal') });
}

export function useBead(id: string | null) {
  return useQuery({
    queryKey: ['bead', id],
    queryFn: () => api.getBead(id as string),
    enabled: !!id,
    refetchInterval: usePoll('fast'),
  });
}

export function useSetBeadStatus() {
  return useTaskMutation('Set bead status', ({ id, status }: { id: string; status: string }) =>
    api.setBeadStatus(id, status),
  {
    invalidate: (_data, vars) => [['beads'], ['bead', vars.id]],
    success: 'Saved',
    failure: (_vars, err) => `Save failed: ${errorMessage(err)}`,
  });
}

export function useUnblockBead() {
  return useTaskMutation('Unblock bead', (id: string) => api.unblockBead(id), {
    invalidate: (_data, id) => [['beads'], ['bead', id]],
    success: 'Bead unblocked',
  });
}

export function useRemoveBeadAssignee() {
  return useTaskMutation('Remove bead assignee', (id: string) => api.removeBeadAssignee(id), {
    invalidate: (_data, id) => [['beads'], ['bead', id]],
    success: 'Assignee removed',
  });
}

export function useChatQuestions() {
  return useQuery({
    queryKey: ['chat-questions'],
    queryFn: api.getChatQuestions,
    refetchInterval: usePoll('fast'),
  });
}

export function useSupervisor() {
  return useQuery({
    queryKey: ['supervisor'],
    queryFn: api.getSupervisor,
    refetchInterval: usePoll('normal'),
  });
}

export function useHealthz() {
  return useQuery({
    queryKey: ['healthz'],
    queryFn: api.getHealthz,
    refetchInterval: usePoll('slow'),
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
  return useTaskMutation('Kill task', (id: string) => api.killTask(id), {
    invalidate: (_data, id) => [['tasks'], ['task', id]],
    success: (data) => KILL_MESSAGES[data.result] ?? `Kill result: ${data.result}`,
    failure: (_vars, err) => `Kill failed: ${errorMessage(err)}`,
  });
}

export function useRequeueTask() {
  return useTaskMutation('Re-queue task', (id: string) => api.requeueTask(id), {
    invalidate: [['tasks']],
    success: 'Task re-queued.',
    failure: (_vars, err) => `Re-queue failed: ${errorMessage(err)}`,
  });
}

export function useUnblockTask() {
  return useTaskMutation(
    'Unblock task',
    ({ id, note }: { id: string; note?: string }) => api.unblockTask(id, note),
    {
      invalidate: (_data, vars) => [['tasks'], ['task', vars.id]],
      success: 'Task unblocked.',
      failure: (_vars, err) => `Unblock failed: ${errorMessage(err)}`,
    },
  );
}

export function useUnignoreTask() {
  return useTaskMutation('Lift triage ignore', (id: string) => api.unignoreTask(id), {
    invalidate: (_data, id) => [['tasks'], ['task', id]],
    success: 'Triage ignore lifted.',
    failure: (_vars, err) => `Unignore failed: ${errorMessage(err)}`,
  });
}

export function useCloseTask() {
  return useTaskMutation('Close task', (id: string) => api.closeTask(id), {
    invalidate: [['tasks']],
    success: 'Task closed.',
  });
}

export function useDeleteTask() {
  return useTaskMutation('Delete task', (id: string) => api.deleteTask(id), {
    invalidate: [['tasks']],
    success: 'Task deleted.',
  });
}

export function useRemoveAssignee() {
  return useTaskMutation('Remove assignee', (id: string) => api.removeAssignee(id), {
    invalidate: [['tasks']],
    success: 'Assignee removed.',
  });
}

export function useCreateTask() {
  // No success toast: NewTaskPanel already toasts the created id via onCreated.
  return useTaskMutation('Create task', (payload: CreateTaskInput) => api.createTask(payload), {
    invalidate: [['tasks']],
  });
}

export function usePutConfig() {
  return useTaskMutation('Save config', (updates: Partial<RuntimeConfig>) => api.putConfig(updates), {
    invalidate: [['config']],
    success: 'Config saved',
  });
}

export function useCoders() {
  return useQuery({ queryKey: ['coders'], queryFn: api.getCoders });
}

export function useTemplates() {
  return useQuery({ queryKey: ['templates'], queryFn: api.getTemplates });
}

export function usePauseSupervisor() {
  return useTaskMutation('Pause supervisor', () => api.pauseSupervisor(), {
    invalidate: [['supervisor']],
    success: 'Supervisor paused.',
  });
}

export function useResumeSupervisor() {
  return useTaskMutation('Resume supervisor', () => api.resumeSupervisor(), {
    invalidate: [['supervisor']],
    success: 'Supervisor resumed.',
  });
}

export function useRestartSupervisor() {
  return useTaskMutation('Restart supervisor', () => api.restartSupervisor(), {
    invalidate: [['supervisor']],
    success: (result) => result.alive
      ? `Supervisor restarted — PID ${result.pid}`
      : 'Restart failed (process exited immediately)',
  });
}

export function useAnalyticsSummary(days: number) {
  return useQuery({
    queryKey: ['analytics', 'summary', days],
    queryFn: () => api.getAnalyticsSummary(days),
    refetchInterval: usePoll('slow'),
  });
}

// Artifact documents (STATE.md, RESULT.json, outputs/, RESEARCH.md,
// DESIGN.md): polled while the socket is down so open tabs stay fresh.
export function useArtifactState(taskId: string) {
  return useQuery({
    queryKey: ['task', taskId, 'artifacts', 'state'],
    queryFn: () => api.getArtifactState(taskId),
    refetchInterval: usePoll('normal'),
  });
}

export function useArtifactResult(taskId: string) {
  return useQuery({
    queryKey: ['task', taskId, 'artifacts', 'result'],
    queryFn: () => api.getArtifactResult(taskId),
    refetchInterval: usePoll('normal'),
  });
}

export function useArtifactOutputs(taskId: string) {
  return useQuery({
    queryKey: ['task', taskId, 'artifacts', 'outputs'],
    queryFn: () => api.getArtifactOutputs(taskId),
    refetchInterval: usePoll('normal'),
  });
}

export function useArtifactDoc(taskId: string, kind: 'research' | 'design') {
  return useQuery({
    queryKey: ['task', taskId, 'artifacts', kind],
    queryFn: () => kind === 'research' ? api.getArtifactResearch(taskId) : api.getArtifactDesign(taskId),
    refetchInterval: usePoll('normal'),
  });
}

// Full-text search for the command palette; disabled for short input.
export function useSearch(query: string) {
  return useQuery({
    queryKey: ['search', query],
    queryFn: () => api.search(query),
    enabled: query.length >= 3,
  });
}

// --- Schedules (recurring workers, ADR 0007) -------------------------------

export function useSchedules(target?: 'task' | 'workflow') {
  return useQuery({
    queryKey: ['schedules', target ?? 'all'],
    queryFn: () => api.getSchedules(target),
    refetchInterval: 10000,
  });
}

export function useSchedule(id: string | null) {
  return useQuery({
    queryKey: ['schedule', id],
    queryFn: () => api.getSchedule(id as string),
    enabled: !!id,
    refetchInterval: 5000,
  });
}

export function useCreateSchedule() {
  return useTaskMutation('Create schedule', (payload: ScheduleInput) => api.createSchedule(payload), {
    invalidate: (data) => [['schedules'], ['schedule', data.id]],
    success: (data) => `Schedule created: ${data.name}`,
    failure: (_vars, err) => `Create failed: ${errorMessage(err)}`,
  });
}

export function useUpdateSchedule() {
  return useTaskMutation(
    'Update schedule',
    ({ id, payload }: { id: string; payload: ScheduleInput }) => api.updateSchedule(id, payload),
    {
      invalidate: (_data, vars) => [['schedules'], ['schedule', vars.id]],
      success: 'Schedule updated',
      failure: (_vars, err) => `Update failed: ${errorMessage(err)}`,
    },
  );
}

export function useDeleteSchedule() {
  return useTaskMutation('Delete schedule', (id: string) => api.deleteSchedule(id), {
    invalidate: (_data, id) => [['schedules'], ['schedule', id]],
    success: 'Schedule deleted',
    failure: (_vars, err) => `Delete failed: ${errorMessage(err)}`,
  });
}

export function useRunSchedule() {
  return useTaskMutation('Run schedule', (id: string) => api.runSchedule(id), {
    invalidate: (_data, id) => [['schedules'], ['schedule', id]],
    success: (data) => (data.run.task_id ? `Run started: ${data.run.task_id}` : 'Run recorded (skipped)'),
    failure: (_vars, err) => `Run failed: ${errorMessage(err)}`,
  });
}

export function useSetScheduleEnabled() {
  return useTaskMutation(
    'Set schedule enabled',
    ({ id, enabled }: { id: string; enabled: boolean }) => api.setScheduleEnabled(id, enabled),
    {
      invalidate: (_data, vars) => [['schedules'], ['schedule', vars.id]],
      success: (_data, vars) => (vars.enabled ? 'Schedule enabled' : 'Schedule disabled'),
      failure: (_vars, err) => `Save failed: ${errorMessage(err)}`,
    },
  );
}

// Cron validity plus next firings; debounced so typing fetches at most
// once per pause. Disabled (no fetch) while the expression is blank.
export function useCronPreview(cron: string, timezone: string) {
  const debouncedCron = useDebounced(cron);
  const debouncedZone = useDebounced(timezone);
  return useQuery({
    queryKey: ['cron-preview', debouncedCron, debouncedZone],
    queryFn: () => api.previewCron(debouncedCron, debouncedZone || 'UTC'),
    enabled: debouncedCron.trim().length > 0,
  });
}

// --- Workflows (ordered stages of workers, ADR 0008) -----------------------

export function useWorkflows() {
  return useQuery({ queryKey: ['workflows'], queryFn: api.listWorkflows, refetchInterval: 10000 });
}

export function useWorkflow(id: string | null) {
  return useQuery({
    queryKey: ['workflow', id],
    queryFn: () => api.getWorkflow(id as string),
    enabled: !!id,
  });
}

export function useCreateWorkflow() {
  return useTaskMutation('Create workflow', (payload: WorkflowInput) => api.createWorkflow(payload), {
    invalidate: [['workflows']],
    success: 'Workflow saved',
    failure: (_vars, err) => `Save failed: ${errorMessage(err)}`,
  });
}

export function useUpdateWorkflow() {
  return useTaskMutation(
    'Update workflow',
    ({ id, payload }: { id: string; payload: WorkflowInput }) => api.updateWorkflow(id, payload),
    {
      invalidate: (_data, vars) => [['workflows'], ['workflow', vars.id]],
      success: 'Workflow saved',
      failure: (_vars, err) => `Save failed: ${errorMessage(err)}`,
    },
  );
}

export function useDeleteWorkflow() {
  return useTaskMutation('Delete workflow', (id: string) => api.deleteWorkflow(id), {
    invalidate: (_data, id) => [['workflows'], ['workflow', id]],
    success: 'Workflow deleted',
    failure: (_vars, err) => `Delete failed: ${errorMessage(err)}`,
  });
}

export function useRunWorkflow() {
  return useTaskMutation('Run workflow', (id: string) => api.runWorkflow(id), {
    invalidate: (_data, id) => [['workflows'], ['workflow', id], ['workflow-runs']],
    success: 'Run started',
    failure: (_vars, err) => `Run failed: ${errorMessage(err)}`,
  });
}

export function useImportWorkflow() {
  return useTaskMutation(
    'Import workflow',
    ({ yaml, replace_id }: { yaml: string; replace_id?: string }) =>
      api.importWorkflow(yaml, replace_id),
    {
      invalidate: [['workflows']],
      success: (data) => `Imported ${data.name}`,
      failure: (_vars, err) => `Import failed: ${errorMessage(err)}`,
    },
  );
}

// Server-side draft validation for the editor; a plain mutation (no toast:
// problems are normal while editing, the editor lists them inline).
export function useValidateWorkflow() {
  return useMutation({
    mutationFn: (payload: WorkflowInput) => api.validateWorkflow(payload),
  });
}

// --- Workflow runs (run monitor, ADR 0008) -------------------------------

export function useWorkflowRuns(
  workflowId: string | null,
  opts?: { limit?: number; offset?: number },
) {
  return useQuery({
    queryKey: ['workflow-runs', workflowId, opts?.limit, opts?.offset],
    queryFn: () => api.listWorkflowRuns(workflowId as string, opts),
    enabled: !!workflowId,
    refetchInterval: 5000,
  });
}

export function useAllWorkflowRuns(
  status?: string,
  opts?: { limit?: number; offset?: number },
) {
  return useQuery({
    queryKey: ['workflow-runs', 'all', status ?? 'all', opts?.limit, opts?.offset],
    queryFn: () => api.listAllWorkflowRuns({ status, ...opts }),
    refetchInterval: 5000,
  });
}

export function useWorkflowRun(runId: string | null) {
  return useQuery({
    queryKey: ['workflow-run', runId],
    queryFn: () => api.getWorkflowRun(runId as string),
    enabled: !!runId,
    refetchInterval: (query) =>
      query.state.data?.status === 'running' ? 3000 : false,
  });
}

export function useCancelWorkflowRun() {
  return useTaskMutation('Cancel run', (runId: string) => api.cancelWorkflowRun(runId), {
    invalidate: (_data, runId) => [['workflow-run', runId], ['workflow-runs'], ['workflows']],
    success: 'Run cancelled',
    failure: (_vars, err) => `Cancel failed: ${errorMessage(err)}`,
  });
}
