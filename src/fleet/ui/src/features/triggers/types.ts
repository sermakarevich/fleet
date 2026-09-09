// Shared trigger vocabulary for the merged schedules/recurring feature
// (ADR 0009 "Shared schedule feature"). One module parameterised by target
// renders both Scheduled sub-tabs. Rendered by TriggerTable/TriggerForm/
// TriggerDrawer; no page imports the old per-target folders anymore.
import type { components } from '../../shared/api-types.gen';

// Which object a schedule starts: a worker's task or a workflow run.
// Mirrors the `target` column of /api/schedules (backend vocabulary, ADR 0008).
export type TriggerTarget = 'task' | 'workflow';

// Which trigger family a row belongs to: timer-based schedules (cron)
// or signal-based event triggers (ADR 0011). The Workers page renders one
// sub-tab per kind (Runs/Scheduled/Triggered, ADR 0009 decision table).
export type TriggerKind = 'cron' | 'event';

type Schemas = components['schemas'];

// One saved event-trigger definition with firing counts (GET /api/triggers).
export type EventTrigger = Schemas['TriggerView'];

// One trigger firing row, append-only per trigger (GET /api/triggers/{id}).
export type Firing = Schemas['FiringView'];

// One event-source kind with its param help text (GET /api/triggers/sources).
export type TriggerSource = Schemas['SourceKindView'];

// Dry-run payload: current events plus one decision string each.
export type TriggerPreview = Schemas['TriggerPreviewResponse'];

// One trigger with its recent firing history (GET /api/triggers/{id}).
export type TriggerDetail = Schemas['TriggerDetail'];
