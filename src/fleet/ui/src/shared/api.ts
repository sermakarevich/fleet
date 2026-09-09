import type {
  AnalyticsSummary,
  Bead,
  BeadDetail,
  ChatQuestion,
  CoderInfo,
  CreateTaskInput,
  CronPreview,
  FileOp,
  HealthzStatus,
  LogLine,
  RuntimeConfig,
  Schedule,
  ScheduleDetail,
  ScheduleInput,
  ScheduleRun,
  SearchResult,
  StreamEvent,
  SupervisorStatus,
  TaskChildren,
  TaskDetail,
  TaskSummary,
  Template,
  Workflow,
  WorkflowInput,
  WorkflowRun,
  WorkflowValidate,
} from './types';

export const FLEET_TOKEN_KEY = 'fleet_token';

export function getFleetToken(): string | null {
  try {
    return localStorage.getItem(FLEET_TOKEN_KEY);
  } catch {
    return null;
  }
}

/** Persist the API token (used by TokenGate after the user types it in). */
export function setFleetToken(token: string): void {
  try {
    localStorage.setItem(FLEET_TOKEN_KEY, token);
  } catch {
    // storage unavailable (private mode); the token still applies to this page
  }
}

/** HTTP failure with the status code and the server's error message. */
export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

/** True for a 404 ApiError (missing artifact → "not available" copy). */
export function isNotFound(err: unknown): boolean {
  return err instanceof ApiError && err.status === 404;
}

/** Human message for anything a query or mutation can throw. */
export function errorMessage(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

/** Query string from defined params (?a=1&b=x), '' when all are empty. */
export function qs(params: Record<string, string | number | boolean | undefined | null>): string {
  const parts: string[] = [];
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === '') continue;
    parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`);
  }
  return parts.length > 0 ? `?${parts.join('&')}` : '';
}

type AuthRequiredListener = () => void;

const authRequiredListeners = new Set<AuthRequiredListener>();

/**
 * Subscribe for 401 notifications (TokenGate shows the token field).
 * Returns an unsubscribe function.
 */
export function onAuthRequired(listener: AuthRequiredListener): () => void {
  authRequiredListeners.add(listener);
  return () => {
    authRequiredListeners.delete(listener);
  };
}

function notifyAuthRequired(): void {
  authRequiredListeners.forEach((listener) => listener());
}

function withAuth(init: RequestInit | undefined, token: string | null): RequestInit | undefined {
  if (!token) return init;
  return {
    ...init,
    headers: {
      ...((init?.headers as Record<string, string> | undefined) ?? {}),
      Authorization: `Bearer ${token}`,
    },
  };
}

/** Server error body ({error} or {detail}) or a "METHOD path → status" fallback. */
async function readErrorMessage(resp: Response, path: string, init?: RequestInit): Promise<string> {
  const fallback = `${init?.method ?? 'GET'} ${path} → ${resp.status}`;
  try {
    const body = JSON.parse(await resp.text()) as { error?: unknown; detail?: unknown; message?: unknown };
    for (const field of [body.error, body.detail, body.message]) {
      if (typeof field === 'string' && field) return field;
    }
  } catch {
    // non-JSON body; fall through to the status fallback
  }
  return fallback;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, withAuth(init, getFleetToken()));
  if (resp.status === 401) {
    // TokenGate collects the token via a field; never block the request on a prompt.
    notifyAuthRequired();
    throw new ApiError(401, 'Unauthorized — enter the Fleet API token');
  }
  if (!resp.ok) {
    throw new ApiError(resp.status, await readErrorMessage(resp, path, init));
  }
  if (resp.status === 204) return undefined as T;
  return resp.json() as Promise<T>;
}

function json(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  };
}

export const api = {
  async getTasks(): Promise<TaskSummary[]> {
    const result = await request<{ tasks: TaskSummary[] }>('/api/tasks');
    return result.tasks;
  },

  getTask(id: string): Promise<TaskDetail> {
    return request(`/api/tasks/${id}`);
  },

  getTaskChildren(id: string): Promise<TaskChildren> {
    return request(`/api/tasks/${id}/children`);
  },

  killTask(id: string): Promise<{ ok: boolean; result: string }> {
    return request(`/api/tasks/${id}/kill`, { method: 'POST' });
  },

  requeueTask(id: string): Promise<void> {
    return request(`/api/tasks/${id}/requeue`, { method: 'POST' });
  },

  unblockTask(id: string, note?: string): Promise<void> {
    return request(`/api/tasks/${id}/unblock`, json('POST', { note: note ?? '' }));
  },

  unignoreTask(id: string): Promise<void> {
    return request(`/api/tasks/${id}/unignore`, { method: 'POST' });
  },

  closeTask(id: string): Promise<void> {
    return request(`/api/tasks/${id}/close`, { method: 'POST' });
  },

  deleteTask(id: string): Promise<void> {
    return request(`/api/tasks/${id}`, { method: 'DELETE' });
  },

  removeAssignee(id: string): Promise<void> {
    return request(`/api/tasks/${id}/remove-assignee`, { method: 'POST' });
  },

  createTask(payload: CreateTaskInput): Promise<{ id: string }> {
    return request('/api/tasks', json('POST', payload));
  },

  // --- Beads portal (BD tab) ---------------------------------------------
  async getBeads(): Promise<Bead[]> {
    const result = await request<{ beads: Bead[] }>('/api/beads');
    return result.beads;
  },

  getBead(id: string): Promise<BeadDetail> {
    return request(`/api/beads/${id}`);
  },

  setBeadStatus(id: string, status: string): Promise<{ ok: boolean }> {
    return request(`/api/beads/${id}/status`, json('POST', { status }));
  },

  unblockBead(id: string): Promise<{ ok: boolean }> {
    return request(`/api/beads/${id}/unblock`, { method: 'POST' });
  },

  removeBeadAssignee(id: string): Promise<{ ok: boolean }> {
    return request(`/api/beads/${id}/remove-assignee`, { method: 'POST' });
  },

  getSupervisor(): Promise<SupervisorStatus> {
    return request('/api/supervisor');
  },

  getHealthz(): Promise<HealthzStatus> {
    return request('/healthz');
  },

  pauseSupervisor(): Promise<void> {
    return request('/api/supervisor/pause', { method: 'POST' });
  },

  resumeSupervisor(): Promise<void> {
    return request('/api/supervisor/resume', { method: 'POST' });
  },

  restartSupervisor(): Promise<{ pid: number; alive: boolean; started_at: string | null }> {
    return request('/api/supervisor/restart', { method: 'POST' });
  },

  getConfig(): Promise<RuntimeConfig> {
    return request('/api/config');
  },

  putConfig(updates: Partial<RuntimeConfig>): Promise<RuntimeConfig> {
    return request('/api/config', json('PUT', updates));
  },

  getCoders(): Promise<{ coders: CoderInfo[] }> {
    return request('/api/coders');
  },

  getTemplates(): Promise<{ templates: Template[] }> {
    return request('/api/templates');
  },

  async getAnalyticsSummary(days: number): Promise<AnalyticsSummary> {
    return request(`/api/analytics/summary${qs({ days })}`);
  },

  async search(query: string): Promise<SearchResult[]> {
    const result = await request<{ results: SearchResult[] }>(
      `/api/search${qs({ query })}`
    );
    return result.results;
  },

  getArtifactState(id: string): Promise<{ content: string; mtime: number; path: string }> {
    return request(`/api/tasks/${id}/artifacts/state`);
  },

  getArtifactResult(id: string): Promise<{ content: string; mtime: number; path: string }> {
    return request(`/api/tasks/${id}/artifacts/result`);
  },

  getArtifactOutputs(id: string): Promise<{ files: string[] }> {
    return request(`/api/tasks/${id}/artifacts/outputs`);
  },

  getArtifactResearch(id: string): Promise<{ content: string; mtime: number; path: string }> {
    return request(`/api/tasks/${id}/artifacts/research`);
  },

  getArtifactDesign(id: string): Promise<{ content: string; mtime: number; path: string }> {
    return request(`/api/tasks/${id}/artifacts/design`);
  },

  getLogs(id: string, level?: string): Promise<{ lines: LogLine[] }> {
    return request(`/api/tasks/${id}/logs${qs({ level })}`);
  },

  getStderr(id: string): Promise<{ content: string }> {
    return request(`/api/tasks/${id}/stderr`);
  },

  // --- Attempts timeline ---------------------------------------------------

  getAttemptSummary(id: string, n: number): Promise<{ content: string }> {
    return request(`/api/tasks/${id}/attempts/${n}/summary`);
  },

  getAttemptPrompt(id: string, n: number): Promise<{ content: string }> {
    return request(`/api/tasks/${id}/attempts/${n}/prompt`);
  },

  getAttemptLog(id: string, n: number): Promise<{ content: string }> {
    return request(`/api/tasks/${id}/attempts/${n}/log`);
  },

  getDiff(id: string): Promise<{ diff: string }> {
    return request(`/api/tasks/${id}/diff`);
  },

  getFiles(id: string): Promise<{ files: FileOp[] }> {
    return request(`/api/tasks/${id}/files`);
  },

  getTaskEvents(
    id: string,
    opts?: { offset?: number; limit?: number; kind?: string },
  ): Promise<{ total: number; offset: number; events: StreamEvent[] }> {
    return request(`/api/tasks/${id}/events${qs({ offset: opts?.offset, limit: opts?.limit, kind: opts?.kind })}`);
  },

  async getChatQuestions(): Promise<{ now: number; pending: ChatQuestion[] }> {
    return request('/api/chat/questions');
  },

  answerChatQuestion(id: string, answer: string | string[]): Promise<{ ok: boolean; status: string }> {
    return request(`/api/chat/questions/${id}/answer`, json('POST', { answer }));
  },

  // --- Schedules (recurring workers) ---------------------------------------

  async getSchedules(target?: 'task' | 'workflow'): Promise<Schedule[]> {
    const result = await request<{ schedules: Schedule[] }>(
      `/api/schedules${qs({ target })}`,
    );
    return result.schedules;
  },

  getSchedule(id: string): Promise<ScheduleDetail> {
    return request(`/api/schedules/${id}`);
  },

  createSchedule(payload: ScheduleInput): Promise<Schedule> {
    return request('/api/schedules', json('POST', payload));
  },

  updateSchedule(id: string, payload: ScheduleInput): Promise<Schedule> {
    return request(`/api/schedules/${id}`, json('PUT', payload));
  },

  deleteSchedule(id: string): Promise<{ ok: boolean }> {
    return request(`/api/schedules/${id}`, { method: 'DELETE' });
  },

  runSchedule(id: string): Promise<{ run: ScheduleRun }> {
    return request(`/api/schedules/${id}/run`, { method: 'POST' });
  },

  setScheduleEnabled(id: string, enabled: boolean): Promise<{ ok: boolean }> {
    return request(`/api/schedules/${id}/${enabled ? 'enable' : 'disable'}`, {
      method: 'POST',
    });
  },

  previewCron(cron: string, timezone = 'UTC', count = 5): Promise<CronPreview> {
    return request('/api/schedules/preview', json('POST', { cron, timezone, count }));
  },

  // --- Workflows (ordered stages of workers) -------------------------------

  async listWorkflows(): Promise<Workflow[]> {
    const result = await request<{ workflows: Workflow[] }>('/api/workflows');
    return result.workflows;
  },

  getWorkflow(id: string): Promise<Workflow> {
    return request(`/api/workflows/${id}`);
  },

  createWorkflow(payload: WorkflowInput): Promise<Workflow> {
    return request('/api/workflows', json('POST', payload));
  },

  updateWorkflow(id: string, payload: WorkflowInput): Promise<Workflow> {
    return request(`/api/workflows/${id}`, json('PUT', payload));
  },

  deleteWorkflow(id: string): Promise<{ ok: boolean }> {
    return request(`/api/workflows/${id}`, { method: 'DELETE' });
  },

  validateWorkflow(payload: WorkflowInput): Promise<WorkflowValidate> {
    return request('/api/workflows/validate', json('POST', payload));
  },

  importWorkflow(yaml: string, replace_id?: string): Promise<Workflow> {
    return request('/api/workflows/import', json('POST', { yaml, replace_id: replace_id ?? null }));
  },

  exportWorkflow(id: string): Promise<{ yaml: string }> {
    return request(`/api/workflows/${id}/export`);
  },

  runWorkflow(id: string): Promise<{ run: WorkflowRun }> {
    return request(`/api/workflows/${id}/run`, { method: 'POST' });
  },

  async listWorkflowRuns(
    id: string,
    opts?: { limit?: number; offset?: number },
  ): Promise<{ runs: WorkflowRun[]; total: number }> {
    return request(`/api/workflows/${id}/runs${qs({ limit: opts?.limit, offset: opts?.offset })}`);
  },

  async listAllWorkflowRuns(opts?: {
    status?: string;
    limit?: number;
    offset?: number;
  }): Promise<{ runs: WorkflowRun[]; total: number }> {
    return request(
      `/api/workflow-runs${qs({ status: opts?.status, limit: opts?.limit, offset: opts?.offset })}`,
    );
  },

  getWorkflowRun(runId: string): Promise<WorkflowRun> {
    return request(`/api/workflow-runs/${runId}`);
  },

  cancelWorkflowRun(runId: string): Promise<WorkflowRun> {
    return request(`/api/workflow-runs/${runId}/cancel`, { method: 'POST' });
  },
};
