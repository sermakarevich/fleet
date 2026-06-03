export interface TaskSummary {
  id: string;
  title: string;
  status: string;
  cwd: string | null;
  coder: string | null;
  model: string | null;
  priority: number | null;
  depends_on: string[];
  started_at: string | null;
  elapsed_sec: number | null;
  idle_sec: number | null;
  events: number;
  context_tokens: number | null;
  context_pct: number | null;
  last_event_kind: string | null;
  last_event_detail: string | null;
}

export interface TaskDetail extends TaskSummary {
  description: string | null;
  priority: number | null;
  retry_count: number;
  outcome: string | null;
  ended_at: string | null;
}

export interface FleetEvent {
  kind: string;
  ts: string;
  session_id: string | null;
  tool_name: string | null;
  usage: Record<string, number> | null;
  rate_info: Record<string, unknown> | null;
  raw: Record<string, unknown>;
  extra: Record<string, unknown>;
}

export interface QuestionSummary {
  id: string;
  task_id: string;
  task_title: string;
  task_cwd: string | null;
  question: string;
  choices: string[] | null;
  asked_at: string;
  elapsed_sec: number;
  status: 'open' | 'answered' | 'timed_out' | 'deferred';
  answer: string | null;
}

export interface SupervisorStatus {
  pid: number | null;
  started_at: string | null;
  max_concurrent: number;
  active_count: number;
  free_slots: number;
  paused: boolean;
}

export interface RuntimeConfig {
  max_concurrent: number;
  model: string;
  coder: string;
  context_pressure_threshold_pct: number;
}

export interface CreateTaskInput {
  title: string;
  description?: string;
  cwd?: string;
  coder?: string;
  model?: string;
  priority?: number;
  dependencies?: string[];
  args?: string;
}

export interface Template {
  name: string;
  content: string;
}

export interface ThroughputBucket {
  hour: string;
  success: number;
  failure: number;
  rate_limit: number;
  context_pressure: number;
  blocked_by_agent: number;
}

export interface LeaderboardRow {
  coder: string;
  model: string;
  success_rate: number;
  mean_elapsed_sec: number;
  mean_tokens: number;
  qa_rate: number;
}

export interface BurnoutRow {
  coder: string;
  model: string;
  count: number;
}

export interface RateLimitEvent {
  ts: string;
  provider: string;
  duration_sec: number | null;
}

export interface PerProjectRow {
  cwd: string;
  task_count: number;
  success_rate: number;
  mean_elapsed_sec: number;
}

export interface SearchResult {
  task_id: string;
  task_title: string;
  source: string;        // "title" | "description" | "qa" | "knowledge" | "plan"
  match_context: string; // ~120 char snippet
}

export interface LogLine {
  ts: string;
  level: string;
  message: string;
  extra: Record<string, unknown>;
}

export interface FileOp {
  path: string;
  read: number;
  edit: number;
  write: number;
}

export interface ChatQuestion {
  id: string;
  agent_id: string | null;
  session_id: string | null;
  prompt: string;
  options: string[] | null;
  multi_select: boolean;
  priority: number;
  created_at: number;
  timeout_s: number | null;
  default_answer: string | string[] | null;
}
