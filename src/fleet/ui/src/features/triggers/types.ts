// Shared trigger vocabulary for the merged schedules/recurring feature
// (ADR 0009 "Shared schedule feature"). One module parameterised by target
// renders both Scheduled sub-tabs. Rendered by TriggerTable/TriggerForm/
// TriggerDrawer; no page imports the old per-target folders anymore.

// Which object a schedule starts: a worker's task or a workflow run.
// Mirrors the `target` column of /api/schedules (backend vocabulary, ADR 0008).
export type TriggerTarget = 'task' | 'workflow';

// Timer-based triggers are the only kind today. Listeners (start on a
// signal, ADR 0009 decision table) will become a second TriggerKind in
// this same module with a third sub-tab on both pages; no listener UI yet.
export type TriggerKind = 'cron';
