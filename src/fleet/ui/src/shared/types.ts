// API response types: generated from the serve OpenAPI schema.
//
// Source of truth is `src/fleet/serve/api/models.py`. Regenerate with
// `just ui-types`; `just check` fails when this file drifts. Do not hand-edit
// the aliases below — only the UI-only view models at the bottom of this file.
import type { components } from './api-types.gen';

type Schemas = components['schemas'];

export type TaskRounds = Schemas['TaskRounds'];
export type TaskLease = Schemas['TaskLease'];
// The backend inlines every summary field into TaskDetail (pydantic flattens
// the subclass), so the list-row type is TaskDetail without the timeline.
export type TaskSummary = Omit<Schemas['TaskDetail'], 'attempts'>;
export type RunStep = Schemas['RunStep'];
export type TaskResult = Schemas['TaskResult'];
export type TaskAttempt = Schemas['TaskAttempt'];
export type TaskChild = Schemas['TaskChild'];
export type TaskChildren = Schemas['TaskChildren'];
export type TaskDetail = Schemas['TaskDetail'];
export type Bead = Schemas['Bead'];
export type BeadDependency = Schemas['BeadDependency'];
export type BeadComment = Schemas['BeadComment'];
export type BeadDetail = Schemas['BeadDetail'];
export type StreamEvent = Schemas['StreamEvent'];
export type SupervisorStatus = Schemas['SupervisorResponse'];
export type HealthzStatus = Schemas['HealthResponse'];
export type RuntimeConfig = Schemas['ConfigView'];
export type CoderInfo = Schemas['CoderInfo'];
export type Template = Schemas['Template'];
export type AnalyticsSummary = Schemas['AnalyticsSummary'];
export type AnalyticsKpis = Schemas['AnalyticsKpis'];
export type AnalyticsThroughputBucket = Schemas['AnalyticsThroughputBucket'];
export type AnalyticsTokenBucket = Schemas['AnalyticsTokenBucket'];
export type AnalyticsByModelRow = Schemas['AnalyticsByModelRow'];
export type AnalyticsByProjectRow = Schemas['AnalyticsByProjectRow'];
export type AnalyticsToolRow = Schemas['AnalyticsToolRow'];
export type AnalyticsErrorRecent = Schemas['AnalyticsErrorRecent'];
export type AnalyticsRateLimit = Schemas['AnalyticsRateLimit'];
export type SearchResult = Schemas['SearchHit'];
export type LogLine = Schemas['LogLine'];
export type FileOp = Schemas['FileOp'];
export type ChatQuestion = Schemas['Question'];
export type Schedule = Schemas['ScheduleView'];
export type ScheduleRun = Schemas['ScheduleRunView'];
export type ScheduleDetail = Schemas['ScheduleDetail'];
export type CronPreview = Schemas['CronPreviewResponse'];
export type Workflow = Schemas['WorkflowView'];
export type WorkflowRun = Schemas['WorkflowRunView'];
export type WorkflowStepRun = Schemas['StepRunView'];
export type WorkflowValidate = Schemas['WorkflowValidateResponse'];

// --- UI-only types (never cross the API boundary) ---

// One event pushed over the websocket: the raw row plus broker metadata.
// (The HTTP /events endpoint returns StreamEvent instead.)
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

export interface ScheduleInput {
  name: string;
  cron: string;
  timezone?: string;
  enabled?: boolean;
  // Required for target "task", omitted for target "workflow".
  title?: string;
  description?: string;
  cwd?: string;
  coder?: string;
  model?: string;
  priority?: number;
  overlap?: string;
  target?: string;
  workflow_id?: string | null;
}

export interface WorkflowStepInput {
  name: string;
  title: string;
  description?: string;
  cwd?: string;
  coder?: string;
  model?: string;
  priority?: number;
  needs?: string[];
}

export interface WorkflowStageInput {
  name: string;
  steps: WorkflowStepInput[];
}

export interface WorkflowInput {
  name: string;
  description?: string;
  defaults?: {
    cwd?: string;
    coder?: string;
    model?: string;
    priority?: number;
  };
  stages: WorkflowStageInput[];
}
