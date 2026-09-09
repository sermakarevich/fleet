"""Pydantic v2 models for every serve API request and response body.

Called by every module under ``serve/api/`` (each route declares
``response_model=`` with one of these) and by ``serve/openapi_dump.py``
(``app.openapi()`` renders these into the schema that ``just ui-types``
turns into ``ui/src/shared/api-types.gen.ts``). Field names match the JSON
the handlers already return — the UI is the contract — so adding these
changes documentation only, never behaviour: handlers still return
``JSONResponse`` with the same bodies and status codes.

Required-ness mirrors ``ui/src/shared/types.ts``: a field the UI reads as
non-null is required here (handlers always emit the key), a field the UI
reads as nullable is required-but-nullable, and only fields the UI marks
optional get defaults.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class TaskRounds(BaseModel):
    """Trailing-streak retry rounds, from attempts.jsonl."""

    failure: int
    stall: int
    context: int
    partial: int
    noclose: int


class TaskLease(BaseModel):
    """Claim lease from the latest attempt's run.json, null when absent."""

    heartbeat_at: str
    lease_until: str
    alive: bool


class RunStep(BaseModel):
    """One entry of the current attempt's run.json steps."""

    name: str
    started_at: str | None
    ended_at: str | None
    status: Literal["ok", "fail", "outcome"]
    reason: str


class FollowupItem(BaseModel):
    """One observer-declared follow-up bead inside a partial result."""

    title: str = ""
    body: str = ""
    cwd: str | None = None
    depends_on: list[str] = Field(default_factory=list)


class TaskResult(BaseModel):
    """The worker's declared outcome (live RESULT.json or latest snapshot)."""

    model_config = ConfigDict(populate_by_name=True)

    result_schema: int = Field(alias="schema")
    status: Literal["done", "partial", "blocked"]
    summary: str
    commits: list[str]
    tests: dict[str, Any] | None
    open_questions: list[str]
    next_step: str
    blocked_reason: str
    followups: list[FollowupItem] = Field(default_factory=list)


class JobArtifacts(BaseModel):
    """Presence flags for the job worker's RESEARCH/DESIGN/tasks/APPROVED."""

    research: bool
    design: bool
    tasks: bool
    approved: bool


class TaskSummary(BaseModel):
    """One task row for GET /api/tasks (without the attempts timeline)."""

    id: str
    title: str
    description: str | None
    status: str
    cwd: str | None
    coder: str | None
    model: str | None
    priority: int | None
    depends_on: list[str]
    created_at: str | None
    started_at: str | None
    ended_at: str | None
    elapsed_sec: float | None
    idle_sec: float | None
    events: int
    context_tokens: int | None
    context_pct: float | None
    context_limit: int | None
    last_event_kind: str | None
    last_event_detail: str | None
    blocked_reason: str | None
    blocked_at: str | None
    ignore_until: str | None
    ignored: bool
    rounds: TaskRounds
    restarts: int
    context_rounds: int
    compactions: int
    peak_context_pct: float | None
    last_outcome: str | None
    last_outcome_reason: str | None
    last_action: str | None
    result: TaskResult | None
    state_excerpt: str | None
    worker: str | None
    job_phase: str | None
    job_artifacts: JobArtifacts
    steps: list[RunStep]
    lease: TaskLease | None


class TaskAttempt(BaseModel):
    """One row of the attempts timeline."""

    n: int
    kind: str
    mode: str | None
    coder: str | None
    model: str | None
    started_at: str | None
    ended_at: str | None
    duration_sec: float | None
    outcome: str | None
    reason: str | None
    peak_context_pct: float | None
    context_badge: bool
    files_touched: int
    commits: list[str]
    result: TaskResult | None
    has_summary: bool
    has_prompt: bool


class TaskChild(BaseModel):
    """One child bead of an epic."""

    id: str
    title: str | None
    status: str | None
    result_status: str | None
    result_summary: str | None


class TaskChildren(BaseModel):
    """Children panel payload for GET /api/tasks/{id}/children."""

    children: list[TaskChild]
    children_md: str | None


class TaskDetail(TaskSummary):
    """One task with its attempts timeline (GET /api/tasks/{id})."""

    attempts: list[TaskAttempt]


class TaskListResponse(BaseModel):
    """Envelope for GET /api/tasks."""

    tasks: list[TaskDetail]


class TaskAttemptListResponse(BaseModel):
    """Envelope for GET /api/tasks/{id}/attempts."""

    attempts: list[TaskAttempt]


class Bead(BaseModel):
    """One beads-DB row for the BD portal list."""

    id: str
    title: str
    status: str
    priority: int | None
    issue_type: str | None
    assignee: str | None
    created_at: str | None
    updated_at: str | None
    closed_at: str | None
    dependency_count: int | None
    dependent_count: int | None
    comment_count: int | None


class BeadDependency(BaseModel):
    """One dependency edge on a bead detail."""

    id: str | None
    title: str | None
    status: str | None
    dependency_type: str | None


class BeadComment(BaseModel):
    """One comment on a bead detail."""

    id: str | int | None
    author: str | None
    text: str | None
    created_at: str | None


class BeadDetail(BaseModel):
    """One bead with description, notes, dependencies and comments."""

    id: str
    title: str
    status: str
    priority: int | None
    issue_type: str | None
    assignee: str | None
    description: str | None
    notes: str | None
    created_at: str | None
    updated_at: str | None
    closed_at: str | None
    close_reason: str | None
    dependencies: list[BeadDependency]
    comments: list[BeadComment]


class BeadListResponse(BaseModel):
    """Envelope for GET /api/beads."""

    beads: list[Bead]


class StreamEvent(BaseModel):
    """One shaped event row for GET /api/tasks/{id}/events."""

    i: int
    ts: str
    kind: str
    session_id: str | None
    tool_name: str | None
    usage: dict[str, int] | None
    summary: str
    raw: dict[str, Any]


class TaskEventsResponse(BaseModel):
    """Paged envelope for GET /api/tasks/{id}/events."""

    total: int
    offset: int
    events: list[StreamEvent]


class LogLine(BaseModel):
    """One parsed log.jsonl line."""

    ts: str
    level: str
    message: str
    extra: dict[str, Any]


class LogListResponse(BaseModel):
    """Envelope for GET /api/tasks/{id}/logs."""

    lines: list[LogLine]


class FileOp(BaseModel):
    """Per-file read/edit/write counts from the event scan."""

    path: str
    read: int
    edit: int
    write: int


class FileListResponse(BaseModel):
    """Envelope for GET /api/tasks/{id}/files."""

    files: list[FileOp]


class SupervisorResponse(BaseModel):
    """Supervisor liveness, slots, pause flag and code staleness."""

    pid: int | None
    started_at: str | None
    running: bool
    max_concurrent: int
    active_count: int
    free_slots: int
    paused: bool
    version_fingerprint: str | None = None
    stale: bool | None = None


class PauseResponse(BaseModel):
    """Envelope for POST /api/supervisor/pause and /resume."""

    paused: bool


class RestartResponse(BaseModel):
    """New pid facts for POST /api/supervisor/restart."""

    pid: int | None
    alive: bool
    started_at: str | None


class HealthResponse(BaseModel):
    """Liveness payload for GET /healthz."""

    status: str
    fleet_home: str
    version_fingerprint: str | None = None
    current_fingerprint: str | None = None
    stale: bool | None = None


class ConfigView(BaseModel):
    """Full RuntimeConfig as JSON (mirrors core.config.RuntimeConfig)."""

    max_concurrent: int
    model: str
    coder: str
    telegram_chat_id: str
    telegram_allowed_ids: str
    telegram_default_cwd: str
    opencode_ollama_url: str
    ollama_ssh_host: str
    ollama_remote_port: int
    max_concurrent_overrides: str
    context_windows: str
    opencode_default_model: str
    opencode_bedrock_region: str
    opencode_bedrock_profile: str
    stall_warning_minutes: int
    stall_action: str
    max_attempt_minutes: int
    continue_pack_max_bytes: int
    state_max_bytes: int
    compaction_enabled: bool
    compaction_coder: str
    compaction_model: str
    context_checkpoint_pct: int
    context_kill_pct: int
    isolation: str
    isolation_exclude: str
    post_merge_command: str
    triage_interval_minutes: int
    gc_retention_days: int
    gc_archive_days: int
    observer_max_followups: int
    observer_max_rounds: int
    job_gate: bool
    job_child_coder: str
    job_child_model: str
    job_max_children: int
    job_max_phase_attempts: int
    serve_cors_origins: list[str]
    serve_host: str
    serve_port: int


class CoderInfo(BaseModel):
    """One coder entry for the create-task form."""

    name: str
    context_limit: int
    default_model: str


class CoderListResponse(BaseModel):
    """Envelope for GET /api/coders."""

    coders: list[CoderInfo]


class Template(BaseModel):
    """One prompt template stored under the fleet home."""

    name: str
    content: str


class TemplateListResponse(BaseModel):
    """Envelope for GET /api/templates."""

    templates: list[Template]


class AnalyticsKpis(BaseModel):
    """Headline KPIs for the analytics summary."""

    completed: int
    success_rate: float
    active_now: int
    queued: int
    median_run_sec: float | None
    p90_run_sec: float | None
    median_queue_wait_sec: float | None
    total_output_tokens: int | None
    total_input_tokens: int | None = None
    total_cache_read_tokens: int | None = None
    total_cache_creation_tokens: int | None = None
    total_steps: int | None
    avg_segments: float | None
    error_events: int | None
    noclose_count: int | None
    rate_limited_tasks: int | None


class AnalyticsThroughputBucket(BaseModel):
    """Success/failed/blocked counts for one time bucket."""

    bucket: str
    success: int
    failed: int
    blocked: int


class AnalyticsThroughput(BaseModel):
    """Completion throughput with its bucket size."""

    bucket_size: str
    buckets: list[AnalyticsThroughputBucket]


class AnalyticsTokenBucket(BaseModel):
    """Output/input/cache tokens for one time bucket."""

    bucket: str
    output_tokens: int
    input_tokens: int
    cache_tokens: int


class AnalyticsTokenThroughput(BaseModel):
    """Token throughput with its bucket size."""

    bucket_size: str
    buckets: list[AnalyticsTokenBucket]


class AnalyticsByModelRow(BaseModel):
    """One per-(coder, model) breakdown row."""

    coder: str
    model: str
    total: int
    success_rate: float
    median_run_sec: float
    mean_peak_context_tokens: float
    output_tokens: int | None
    avg_segments: float | None
    errors: int
    rate_limited: int


class AnalyticsByProjectRow(BaseModel):
    """One per-cwd breakdown row."""

    cwd: str | None = None
    total: int
    success_rate: float
    median_run_sec: float
    output_tokens: int | None


class AnalyticsToolRow(BaseModel):
    """One tool-usage row."""

    name: str
    count: int


class AnalyticsTools(BaseModel):
    """Tool usage totals with top rows."""

    total: int
    rows: list[AnalyticsToolRow]


class AnalyticsContextHistogram(BaseModel):
    """Peak-context bucket counts keyed by label."""

    buckets: dict[str, int]


class AnalyticsErrorRecent(BaseModel):
    """One task needing attention."""

    id: str
    title: str
    coder: str | None
    model: str | None
    outcome: str | None
    ended_at: str | None


class AnalyticsRateLimit(BaseModel):
    """One raw rate-limit event."""

    task_id: str
    ts: str


class AnalyticsSummary(BaseModel):
    """Aggregated payload for GET /api/analytics/summary."""

    window_days: int
    kpis: AnalyticsKpis
    throughput: AnalyticsThroughput
    token_throughput: AnalyticsTokenThroughput
    by_model: list[AnalyticsByModelRow]
    by_project: list[AnalyticsByProjectRow]
    tools: AnalyticsTools
    context_histogram: AnalyticsContextHistogram
    heatmap: list[list[int]]
    errors_recent: list[AnalyticsErrorRecent]
    rate_limits: list[AnalyticsRateLimit]


class SearchHit(BaseModel):
    """One match: which task, which field, and a snippet around the hit."""

    task_id: str
    task_title: str
    source: str
    match_context: str


class SearchResponse(BaseModel):
    """Envelope for GET /api/search."""

    results: list[SearchHit]


class Question(BaseModel):
    """One ask_human question row for the chat tab."""

    id: str
    agent_id: str | None
    session_id: str | None
    prompt: str
    options: list[str] | None
    multi_select: bool
    priority: int
    status: str
    answer: Any | None
    note: str | None
    default_answer: str | list[str] | None
    timeout_s: float | None
    answered_by: str | None
    created_at: float
    answered_at: float | None
    task_id: str | None
    context: str | None


class QuestionListResponse(BaseModel):
    """Envelope for GET /api/chat/questions."""

    now: float
    pending: list[Question]


class AnswerResponse(BaseModel):
    """Outcome envelope for POST /api/chat/questions/{id}/answer."""

    ok: bool
    status: str


class ArtifactResponse(BaseModel):
    """File content envelope for the artifact routes."""

    content: str
    mtime: float
    path: str


class OutputsResponse(BaseModel):
    """Deliverable names for GET /api/tasks/{id}/artifacts/outputs."""

    files: list[str]


class ContentResponse(BaseModel):
    """Single-text envelope (attempt summary/prompt/log/state, stderr)."""

    content: str


class DiffResponse(BaseModel):
    """git diff envelope for GET /api/tasks/{id}/diff."""

    diff: str


class CreateTaskResponse(BaseModel):
    """New task id for POST /api/tasks."""

    id: str


class OkResponse(BaseModel):
    """Generic mutation acknowledgement ({"ok": true})."""

    ok: bool


class KillResponse(BaseModel):
    """Outcome envelope for POST /api/tasks/{id}/kill."""

    ok: bool
    result: str


class CreateTaskRequest(BaseModel):
    """Body for POST /api/tasks (parsed manually by the handler today)."""

    title: str = ""
    description: str | None = None
    cwd: str | None = None
    coder: str | None = None
    model: str | None = None
    priority: int | None = None
    dependencies: list[str] | None = None
    args: str | None = None


class UnblockRequest(BaseModel):
    """Body for POST /api/tasks/{id}/unblock (parsed manually today)."""

    note: Any | None = None


class SetBeadStatusRequest(BaseModel):
    """Body for POST /api/beads/{id}/status (validated manually today)."""

    status: str = ""


class AnswerRequest(BaseModel):
    """Body for POST /api/chat/questions/{id}/answer (parsed manually today)."""

    answer: str | list[str] = ""


class ConfigUpdateRequest(BaseModel):
    """Partial RuntimeConfig for PUT /api/config (parsed manually today)."""

    max_concurrent: int | None = None
    model: str | None = None
    coder: str | None = None
    max_concurrent_overrides: str | None = None


class ScheduleRequest(BaseModel):
    """Body for POST /api/schedules and PUT /api/schedules/{id} (validated manually)."""

    name: str = ""
    cron: str = ""
    timezone: str = "UTC"
    enabled: bool = True
    title: str = ""
    description: str = ""
    cwd: str | None = None
    coder: str | None = None
    model: str | None = None
    priority: int = 2
    overlap: str = "skip"


class ScheduleRunView(BaseModel):
    """One schedule run plus the task it opened (status/title null when gone)."""

    schedule_id: str
    n: int
    scheduled_for: str
    fired_at: str
    trigger: str
    task_id: str | None
    skipped: bool
    reason: str
    task_status: str | None
    task_title: str | None


class ScheduleView(BaseModel):
    """One schedule with its next firing, run count and latest run."""

    id: str
    name: str
    cron: str
    timezone: str
    enabled: bool
    title: str
    description: str
    cwd: str | None
    coder: str | None
    model: str | None
    priority: int
    overlap: str
    created_at: str
    updated_at: str
    next_fire_at: str | None
    run_count: int
    last_run: ScheduleRunView | None


class ScheduleDetail(ScheduleView):
    """One schedule with upcoming firings and enriched run history."""

    upcoming: list[str]
    runs: list[ScheduleRunView]


class ScheduleListResponse(BaseModel):
    """Envelope for GET /api/schedules."""

    schedules: list[ScheduleView]


class CronPreviewRequest(BaseModel):
    """Body for POST /api/schedules/preview (parsed manually today)."""

    cron: str = ""
    timezone: str = "UTC"
    count: int = 5


class CronPreviewResponse(BaseModel):
    """Cron validity plus upcoming UTC firings (never 4xx for a bad expression)."""

    valid: bool
    error: str | None
    upcoming: list[str]


class ScheduleRunResponse(BaseModel):
    """Envelope for POST /api/schedules/{id}/run."""

    run: ScheduleRunView


class StepRequest(BaseModel):
    """One step template in a workflow create/update body."""

    name: str = ""
    title: str = ""
    description: str = ""
    cwd: str | None = None
    coder: str | None = None
    model: str | None = None
    priority: int | None = None
    needs: list[str] = Field(default_factory=list)


class StageRequest(BaseModel):
    """One stage (parallel group) in a workflow create/update body."""

    name: str = ""
    steps: list[StepRequest] = Field(default_factory=list)


class WorkflowDefaultsModel(BaseModel):
    """Fallback worker settings for steps that leave a field empty."""

    cwd: str | None = None
    coder: str | None = None
    model: str | None = None
    priority: int = 2


class WorkflowRequest(BaseModel):
    """Body for POST /api/workflows and PUT /api/workflows/{id}."""

    name: str = ""
    description: str = ""
    defaults: WorkflowDefaultsModel = Field(default_factory=WorkflowDefaultsModel)
    stages: list[StageRequest] = Field(default_factory=list)


class StepRunView(BaseModel):
    """One step inside one run, with its display state and task title."""

    step_name: str
    stage_index: int
    task_id: str
    task_status: str
    state: str
    task_title: str | None


class WorkflowRunView(BaseModel):
    """One workflow run with its step runs (titles null when tasks are gone)."""

    id: str
    workflow_id: str
    workflow_name: str
    n: int
    trigger: str
    schedule_id: str | None
    status: str
    reason: str
    started_at: str
    finished_at: str | None
    steps: list[StepRunView]


class WorkflowView(BaseModel):
    """One saved workflow with counts and its latest run."""

    id: str
    name: str
    description: str
    defaults: WorkflowDefaultsModel
    stages: list[StageRequest]
    step_count: int
    stage_count: int
    created_at: str
    updated_at: str
    run_count: int
    last_run: WorkflowRunView | None


class WorkflowListResponse(BaseModel):
    """Envelope for GET /api/workflows."""

    workflows: list[WorkflowView]


class WorkflowRunListResponse(BaseModel):
    """Paged envelope for the workflow run list routes."""

    runs: list[WorkflowRunView]
    total: int


class WorkflowValidateResponse(BaseModel):
    """Validation outcome; invalid content is 200 with problems, never 4xx."""

    valid: bool
    problems: list[str]


class WorkflowImportRequest(BaseModel):
    """Body for POST /api/workflows/import (parsed manually today)."""

    yaml: str = ""
    replace_id: str | None = None


class WorkflowExportResponse(BaseModel):
    """Envelope for GET /api/workflows/{id}/export (YAML text)."""

    yaml: str


class StartRunResponse(BaseModel):
    """Envelope for POST /api/workflows/{id}/run."""

    run: WorkflowRunView
