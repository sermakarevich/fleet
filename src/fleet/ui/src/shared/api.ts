import type {
  AnalyticsSummary,
  Bead,
  BeadDetail,
  ChatQuestion,
  CoderInfo,
  CreateTaskInput,
  FileOp,
  HealthzStatus,
  LogLine,
  RuntimeConfig,
  SearchResult,
  StreamEvent,
  SupervisorStatus,
  TaskDetail,
  TaskSummary,
  Template,
} from './types';

export function getFleetToken(): string | null {
  try {
    return localStorage.getItem('fleet_token');
  } catch {
    return null;
  }
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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let resp = await fetch(path, withAuth(init, getFleetToken()));
  if (resp.status === 401) {
    const entered = window.prompt('Fleet API token');
    if (entered) {
      try {
        localStorage.setItem('fleet_token', entered);
      } catch {
        // ignore storage errors; still retry with the entered token
      }
      resp = await fetch(path, withAuth(init, entered));
    }
  }
  if (!resp.ok) {
    throw new Error(`${init?.method ?? 'GET'} ${path} \u2192 ${resp.status}`);
  }
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

  killTask(id: string): Promise<{ ok: boolean; result: string }> {
    return request(`/api/tasks/${id}/kill`, { method: 'POST' });
  },

  requeueTask(id: string): Promise<void> {
    return request(`/api/tasks/${id}/requeue`, { method: 'POST' });
  },

  unblockTask(id: string, note?: string): Promise<void> {
    return request(`/api/tasks/${id}/unblock`, json('POST', { note: note ?? '' }));
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
    return request(`/api/analytics/summary?days=${days}`);
  },

  async search(q: string): Promise<SearchResult[]> {
    const result = await request<{ results: SearchResult[] }>(`/api/search?q=${encodeURIComponent(q)}`);
    return result.results;
  },

  getArtifactPlan(id: string): Promise<{ content: string; mtime: number; path: string }> {
    return request(`/api/tasks/${id}/artifacts/plan`);
  },

  getArtifactHandoff(id: string): Promise<{ content: string; mtime: number; path: string }> {
    return request(`/api/tasks/${id}/artifacts/handoff`);
  },

  getArtifactKnowledge(id: string): Promise<{ content: string; mtime: number; path: string }> {
    return request(`/api/tasks/${id}/artifacts/knowledge`);
  },

  getArtifactResult(id: string): Promise<{ content: string; mtime: number; path: string }> {
    return request(`/api/tasks/${id}/artifacts/result`);
  },

  getLogs(id: string, level?: string): Promise<{ lines: LogLine[] }> {
    const qs = level ? `?level=${encodeURIComponent(level)}` : '';
    return request(`/api/tasks/${id}/logs${qs}`);
  },

  getStderr(id: string): Promise<{ content: string }> {
    return request(`/api/tasks/${id}/stderr`);
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
    const parts: string[] = [];
    if (opts?.offset !== undefined) parts.push(`offset=${opts.offset}`);
    if (opts?.limit !== undefined) parts.push(`limit=${opts.limit}`);
    if (opts?.kind) parts.push(`kind=${encodeURIComponent(opts.kind)}`);
    const qs = parts.length ? "?" + parts.join("&") : "";
    return request(`/api/tasks/${id}/events${qs}`);
  },

  async getChatQuestions(): Promise<{ now: number; pending: ChatQuestion[] }> {
    return request('/api/chat/questions');
  },

  answerChatQuestion(id: string, answer: string | string[]): Promise<{ ok: boolean; status: string }> {
    return request(`/api/chat/questions/${id}/answer`, json('POST', { answer }));
  },
};
