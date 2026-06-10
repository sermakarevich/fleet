import type {
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
  SupervisorStatus,
  TaskDetail,
  TaskSummary,
  Template,
} from './types';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, init);
  if (!resp.ok) {
    throw new Error(`${init?.method ?? 'GET'} ${path} → ${resp.status}`);
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

  getAnalytics(endpoint: string): Promise<unknown> {
    return request(`/api/analytics/${endpoint}`);
  },

  async search(q: string): Promise<SearchResult[]> {
    const result = await request<{ results: SearchResult[] }>(`/api/search?q=${encodeURIComponent(q)}`);
    return result.results;
  },

  getArtifactPlan(id: string): Promise<{ content: string; mtime: number; path: string }> {
    return request(`/api/tasks/${id}/artifacts/plan`);
  },

  getArtifactKnowledge(id: string): Promise<{ content: string; mtime: number; path: string }> {
    return request(`/api/tasks/${id}/artifacts/knowledge`);
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

  async getChatQuestions(): Promise<{ now: number; pending: ChatQuestion[] }> {
    return request('/api/chat/questions');
  },

  answerChatQuestion(id: string, answer: string | string[]): Promise<{ ok: boolean; status: string }> {
    return request(`/api/chat/questions/${id}/answer`, json('POST', { answer }));
  },
};
