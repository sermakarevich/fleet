# ADR 0017: Task detail page — four tabs, one activity feed

## Status

Accepted

## Date

2026-09-29

## Context

The worker detail page (`/workers/:id`) grew to fifteen tabs: Live, Attempts,
Children, Artifacts, Research, Design, Shortlist, Log, Events, Stderr, Diff,
Files, Dependencies, Comments, Bead. An inventory on 2026-09-28 found:

- Four tabs show the coder's output from four angles (Live over a per-task
  websocket with no history, Events from `events.jsonl`, Log from fleet's own
  `log.jsonl`, Stderr from `log.stderr`). The websocket has no backfill and no
  heartbeat, so an open page can look "connected" while nothing arrives; and
  `usePoll` switches every timer off whenever *any* socket is up, so the other
  tabs only refresh on mount or focus. In practice the page hangs.
- Six tabs are artifacts (Artifacts, Research, Design, Shortlist, Diff, Files).
  Most are empty for most tasks: Research and Design only exist for the old
  research workflow, Shortlist for research workers, Diff ignores worktrees so
  committed work shows as empty, and several tabs show "Loading…" forever on
  an error.
- Four tabs are beads-only (Children, Dependencies, Comments, Bead). Fleet 2
  flow steps already appear as bead-less tasks (`~/.fleet/tasks/<run>.<step>/`),
  and beads stop being mandatory as flows take over (ADR for Fleet 2,
  `docs/27_sep_upgrade/DESIGN.md`).
- Page state (events, active tab) leaks between tasks because the route has
  no `key`.

## Decision

Replace the fifteen tabs with four, each backed by one request:

| Tab | Shows | Backend |
|---|---|---|
| **Activity** | One time-ordered feed across all attempts: coder events (`events.jsonl`), fleet log lines of level warning and above (`log.jsonl`), plus a collapsible stderr tail of the latest attempt. Attempt boundaries are dividers. | `GET /api/tasks/{id}/activity?after=&before=&limit=&min_level=` — merged, cached, cursor-paged |
| **Attempts** | Existing attempt list with per-attempt summary and prompt; errors shown, never "Loading…" forever. | existing routes |
| **Result** | Everything the task produced: RESULT.json, STATE.md, `outputs/`, every document under `artifacts/` (`*.md`, `*.json`), files touched, and a diff on demand that understands worktrees (`worktree_path`, `base_ref`). Missing parts are omitted, not errors. | `GET /api/tasks/{id}/artifacts` (one bundle) and `GET /api/tasks/{id}/diff` (fixed) |
| **Bead** | Dependencies, comments, child beads and the raw bead JSON. Only shown when the task has a bead (`GET /api/beads/{id}` succeeds). | existing bead routes |

Rules:

- **Polling, not a per-task websocket.** The Activity tab keeps its own
  interval (about 2 s while the task is in progress, none once finished) and
  fetches only items after its cursor. It does not use `usePoll`, so the global
  `/ws/events` socket cannot switch it off. The `/ws/tasks/{id}/events`
  endpoint becomes unused and is removed; the file watcher stays because the
  global `/ws/events` socket (runs list) still uses it.
- **Every fetch error is visible.** A tab shows the error text and a retry, never
  an empty state or a spinner, when the request fails.
- **The page is keyed by task id**, so navigating between tasks resets state.
- **Sidebar (ActivityGutter)** reads tokens, idle time and last event from the
  activity feed, not from a socket. Kill result messages match the server's
  actual outcomes (`killing`, `closed`, `no-op`).
- **Flow steps.** Step dirs share the task-dir layout, so the same four tabs
  serve Fleet 2 flow steps without a Bead tab. A flow-run page that links to
  them is a separate, later decision.

## Consequences

- Deleted UI: LiveTab, EventsTab, LogTab, StderrTab, StateTab, JobDocTab,
  ShortlistTab, DiffTab, FilesTab, ChildrenTab, DependenciesTab, CommentsTab,
  BeadJsonTab and their hooks. Deleted backend: `/logs`, `/stderr`, `/events`,
  `/files`, `/artifacts/{state,result,outputs,research,design,candidates,children_runs}`,
  `/ws/tasks/{id}/events`.
- CLI commands (`fleet task <id> log`, and so on) read files directly and are
  unaffected.
- The Shortlist ranking of `candidates.json` is dropped; the file is shown as a
  plain document. The research workflow that produced it is being replaced by
  the research flow.
- Implemented by beads U1 (backend), U2 (Activity tab and page shell), U3
  (Result and Bead tabs), U4 (backend and UI deletions), in that order.
