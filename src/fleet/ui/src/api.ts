import type {
  CreateTaskInput,
  QuestionSummary,
  RuntimeConfig,
  SearchResult,
  SupervisorStatus,
  TaskDetail,
  TaskSummary,
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
  getTasks(): Promise<TaskSummary[]> {
    return request('/api/tasks');
  },

  getTask(id: string): Promise<TaskDetail> {
    return request(`/api/tasks/${id}`);
  },

  killTask(id: string): Promise<void> {
    return request(`/api/tasks/${id}/kill`, { method: 'POST' });
  },

  requeueTask(id: string): Promise<void> {
    return request(`/api/tasks/${id}/requeue`, { method: 'POST' });
  },

  createTask(payload: CreateTaskInput): Promise<{ id: string }> {
    return request('/api/tasks', json('POST', payload));
  },

  getQA(status?: string): Promise<QuestionSummary[]> {
    const qs = status ? `?status=${encodeURIComponent(status)}` : '';
    return request(`/api/qa${qs}`);
  },

  answerQuestion(id: string, answer: string): Promise<void> {
    return request(`/api/qa/${id}/answer`, json('POST', { answer }));
  },

  deferQuestion(id: string): Promise<void> {
    return request(`/api/qa/${id}/defer`, { method: 'POST' });
  },

  getSupervisor(): Promise<SupervisorStatus> {
    return request('/api/supervisor');
  },

  pauseSupervisor(): Promise<void> {
    return request('/api/supervisor/pause', { method: 'POST' });
  },

  resumeSupervisor(): Promise<void> {
    return request('/api/supervisor/resume', { method: 'POST' });
  },

  getConfig(): Promise<RuntimeConfig> {
    return request('/api/config');
  },

  putConfig(updates: Partial<RuntimeConfig>): Promise<RuntimeConfig> {
    return request('/api/config', json('PUT', updates));
  },

  getAnalytics(endpoint: string): Promise<unknown> {
    return request(`/api/analytics/${endpoint}`);
  },

  search(q: string): Promise<SearchResult[]> {
    return request(`/api/search?q=${encodeURIComponent(q)}`);
  },
};
