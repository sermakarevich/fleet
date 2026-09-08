export interface TaskSummary {
  id: string;
  title: string;
  description: string | null;
  status: string;
  cwd: string | null;
  coder: string | null;
  model: string | null;
  priority: number | null;
  depends_on: string[];
  created_at: string | null;
  started_at: string | null;
  ended_at: string | null;
  elapsed_sec: number | null;
  idle_sec: number | null;
  events: number;
  context_tokens: number | null;
  context_pct: number | null;
  last_event_kind: string | null;
  last_event_detail: string | null;
  blocked_reason: string | null;
  blocked_at: string | null;
  failures: number;
  noclose: number;
  stalls: number;
  restarts: number;
  last_outcome: string | null;
  last_outcome_reason: string | null;
  last_action: string | null;
  result: TaskResult | null;
  handoff_excerpt: string | null;
  worker: string | null;
  steps: RunStep[];
}

// One entry from the current attempt's run.json["steps"].
export interface RunStep {
  name: string;
  started_at: string | null;
  ended_at: string | null;
  status: 'ok' | 'fail' | 'outcome';
  reason: string;
}

// The worker's declared outcome, parsed from artifacts/RESULT.json.
export interface TaskResult {
  schema: number;
  status: 'done' | 'partial' | 'blocked';
  summary: string;
  commits: string[];
  tests: Record<string, unknown> | null;
  open_questions: string[];
  next_step: string;
  blocked_reason: string;
}

// One row of the attempts timeline: state/task_summary.py::_build_attempts_summary.
export interface TaskAttempt {
  n: number;
  kind: string; // "work" today; compaction jobs add their own kind later.
  mode: 'fresh' | 'continue' | null;
  coder: string | null;
  model: string | null;
  started_at: string | null;
  ended_at: string | null;
  duration_sec: number | null;
  outcome: string | null;
  reason: string | null;
  peak_context_pct: number | null;
  files_touched: number;
  commits: string[];
  result: TaskResult | null;
  has_summary: boolean;
  has_handoff: boolean;
}

export interface TaskDetail extends TaskSummary {
  attempts: TaskAttempt[];
}

// A row from the beads DB, as surfaced by the BD (beads) portal.
export interface Bead {
  id: string;
  title: string;
  status: string;
  priority: number | null;
  issue_type: string | null;
  assignee: string | null;
  created_at: string | null;
  updated_at: string | null;
  closed_at: string | null;
  dependency_count: number | null;
  dependent_count: number | null;
  comment_count: number | null;
}

export interface BeadDependency {
  id: string;
  title: string | null;
  status: string | null;
  dependency_type: string | null;
}

export interface BeadComment {
  id: string | number | null;
  author: string | null;
  text: string | null;
  created_at: string | null;
}

export interface BeadDetail {
  id: string;
  title: string;
  status: string;
  priority: number | null;
  issue_type: string | null;
  assignee: string | null;
  description: string | null;
  notes: string | null;
  created_at: string | null;
  updated_at: string | null;
  closed_at: string | null;
  close_reason: string | null;
  dependencies: BeadDependency[];
  comments: BeadComment[];
}

export interface FleetEvent {
  kind: string;
  ts: string;
  session_id: string | null;
  tool_name: string | null;
  usage: Record<string, number> | null;
  rate_info: Record<string, unknown> | null;
  raw: Record<string, unknown>;
  extra?: Record<string, unknown>;
}

export interface SupervisorStatus {
  pid: number | null;
  started_at: string | null;
  running: boolean;
  max_concurrent: number;
  active_count: number;
  free_slots: number;
  paused: boolean;
  version_fingerprint?: string | null;
  stale?: boolean;
}

export interface HealthzStatus {
  status: string;
  fleet_home: string;
  version_fingerprint?: string | null;
  current_fingerprint?: string;
  stale?: boolean;
}

export interface RuntimeConfig {
  max_concurrent: number;
  max_concurrent_overrides: string;
  model: string;
  coder: string;
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

export interface CoderInfo {
  name: string;
  context_limit: number;
  default_model: string;
}

// --- Analytics Summary ---

export interface AnalyticsSummary {
  window_days: number;
  kpis: AnalyticsKpis;
  throughput: { bucket_size: string; buckets: AnalyticsThroughputBucket[] };
  token_throughput?: { bucket_size: string; buckets: AnalyticsTokenBucket[] };
  by_model: AnalyticsByModelProject[];
  by_project: AnalyticsByModelProject[];
  tools: { total: number; rows: AnalyticsToolRow[] };
  context_histogram: { buckets: number[] | Record<string, number> };
  heatmap: number[][];
  errors_recent: AnalyticsErrorRecent[];
  rate_limits: AnalyticsRateLimit[];
}

export interface AnalyticsKpis {
  completed: number;
  success_rate: number;
  active_now: number;
  queued: number;
  median_run_sec: number | null;
  p90_run_sec: number | null;
  median_queue_wait_sec: number | null;
  total_output_tokens: number | null;
  total_input_tokens?: number | null;
  total_cache_read_tokens?: number | null;
  total_cache_creation_tokens?: number | null;
  total_steps: number | null;
  avg_segments: number | null;
  error_events: number | null;
  noclose_count: number | null;
  rate_limited_tasks: number | null;
}

export interface AnalyticsThroughputBucket {
  bucket: string;
  success: number;
  failed: number;
  blocked: number;
}

export interface AnalyticsTokenBucket {
  bucket: string;
  output_tokens: number;
  input_tokens: number;
  cache_tokens: number;
}

export interface AnalyticsByModelProject {
  coder: string;
  model: string;
  cwd?: string | null;
  total: number;
  success_rate: number;
  median_run_sec: number;
  mean_peak_context_tokens: number;
  output_tokens: number | null;
  avg_segments: number | null;
  errors: number;
  rate_limited: number;
}

export interface AnalyticsToolRow {
  name: string;
  count: number;
}

export interface AnalyticsErrorRecent {
  id: string;
  title: string;
  coder: string | null;
  model: string | null;
  outcome: string | null;
  ended_at: string | null;
}

export interface AnalyticsRateLimit {
  task_id: string;
  ts: string;
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

export interface StreamEvent {
  i: number;
  ts: string;
  kind: string;
  session_id: string | null;
  tool_name: string | null;
  usage: Record<string, number> | null;
  summary: string;
  raw: Record<string, unknown>;
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
