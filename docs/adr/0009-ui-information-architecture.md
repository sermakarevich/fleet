# ADR 0009: UI information architecture — workers and workflows, four tabs

Date: 2026-09-09
Status: Accepted
Builds on: ADR 0007 (recurring workers / schedules), ADR 0008 (workflows),
ADR 0006 (clean-code rules, applied to the UI as well).

## Problem

The web UI grew one tab per feature: `tasks`, `bd`, `schedules`, `workflows`,
`recurring`, `analytics`, `config`, `chat`. The navigation reflects the order
things were built, not how an operator thinks about fleet.

Observed on 2026-09-09:

- `schedules` and `recurring` are one backend store (`/api/schedules`) split by
  `target`. Two UI folders duplicate table, form and drawer code. The schedules
  header links to the recurring tab to explain the split.
- `tasks` and `bd` overlap almost completely. `bd` adds only: closed beads beyond
  the recent window, priority, dependency list, comments, close/reopen, remove
  assignee. All of these are properties of a worker's task, not a separate
  concept.
- `analytics` fans one endpoint (`/api/analytics/summary`) into eleven widgets
  with no drill-down. The useful parts ("needs attention", rate-limit events)
  belong next to the running workers.
- `config` exposes 4 of 43 `RuntimeConfig` fields although `PUT /api/config`
  accepts all of them and 40 hot-reload within `CONFIG_POLL_INTERVAL_SEC`.
  Coder and model are free text; `serve_host`/`serve_port` save silently but
  need a restart; ~35 code-level tunables (`core/limits.py`, retry and triage
  constants) are invisible.
- Three idioms for "look at one thing": right drawer (beads, schedules,
  recurring), full page with tabs (task detail, workflow run), inline two-pane
  (chat). Filter bars, confirmations, empty states and units differ per page.
  Several files hardcode hex colours and pixel sizes beside `shared/styles`.
- The supervisor panel shows "Active / Free slots 2117 / 0": `_count_active`
  counts every task.json with `status == in_progress`, including stale ones.

## Decision

The UI is organised around **two objects** and **how they are started**.

| Object   | Started once          | Started on a timer      | Started on a signal (later) |
|----------|-----------------------|-------------------------|-----------------------------|
| Worker   | a task (today)        | a task schedule (today) | a listener                  |
| Workflow | a workflow run (today)| a workflow schedule     | a listener                  |

Navigation has **four tabs**: `Workers`, `Workflows`, `Inbox`, `Settings`.

### Workers (`/workers`)

The renamed tasks page. Sub-tabs:

- **Runs** — today's task list. Filters: running, queued, blocked, done, failed,
  plus free-text search. Filter state is in the URL.
- **Scheduled** — schedules with `target=task`. Same table shape as the
  Workflows → Scheduled sub-tab.

A **needs-attention strip** above the list shows counts for blocked, failed in
the last 24 h, rate-limited in the last 24 h and pending inbox questions. It
reads `/api/analytics/summary` and replaces the analytics tab.

The worker detail page (`/workers/:id`, today's task detail) absorbs the
bead-only features: priority and issue type, dependency list with types,
comments, close / reopen, remove assignee. A `Bead` tab shows the raw bead JSON
for debugging. The `bd` tab and route are removed; `/bd` redirects to
`/workers?status=…`. The `/api/beads` routes stay (CLI, tests, other clients).

`+ New worker` replaces `+ New task`. The button opens the existing task form;
the form gains a "Run: now / on a schedule" switch so a schedule can be created
from the same place. API paths (`/api/tasks`) do not change; "worker" is UI
vocabulary only. Backend vocabulary from ADR 0008 (task = the bead a step
opens) is unchanged.

### Workflows (`/workflows`)

Sub-tabs: **Definitions**, **Runs**, **Scheduled** (schedules with
`target=workflow`, today's `recurring`). `/recurring` redirects here. The
editor and run page stay full pages.

### Shared schedule feature

`features/schedules` and `features/recurring` collapse into one
`features/triggers` module parameterised by target. One form, one row, one
drawer. Listeners, when they exist, are a second trigger kind in the same
module and a third sub-tab on both pages; no new top-level tab.

### Inbox (`/inbox`)

Today's chat page renamed. It is the place a human answers questions from
workers and triage proposals. The pending count is shown in the tab label.

### Settings (`/settings`)

Every `RuntimeConfig` field, grouped:

Supervisor (status, pause / resume / restart) · Concurrency · Coders and models
(dropdowns from `/api/coders`, per-model context windows) · Worker limits
(stall, max attempt minutes, context checkpoint / kill %) · Isolation and merge
· Triage · Jobs · Compaction · Housekeeping (gc) · Integrations (telegram,
ollama, opencode) · Server (host, port, CORS; marked **restart required**) ·
Browser notifications.

A read-only **Constants** section lists the code-level tunables with the text
from `TUNABLE_DOCS` (served by a new `GET /api/config/constants`) so they are
discoverable even though they are not editable.

### One rule set for every page

1. One list component: table on desktop, card on mobile, shared by workers,
   workflows, runs, schedules and inbox.
2. Filters live in the URL (`useSearchParams`) on every list.
3. Anything that has runs or tabs is a full page. A drawer (`Modal
   placement="right"`) is used only for quick edit forms.
4. One `Confirm` component; no `window.confirm`.
5. One empty state and one loading state component.
6. Colours and sizes come from `shared/styles/tokens.ts` and `recipes.ts` only;
   rem units; an eslint rule rejects hex literals outside `tokens.ts`.
7. Every API hook has a UI caller or is deleted.

### Out of scope

- Listeners themselves (only the slot in the structure is reserved).
- Any backend behaviour change other than `GET /api/config/constants` and the
  supervisor active-count fix.

## Consequences

- Eight tabs become four. Two duplicate feature folders become one.
- Workers and Workflows pages have the same three-part shape, so a new operator
  learns one layout.
- Analytics charts are deleted from the UI. The API stays and the charts can
  return as a report page later if wanted.
- The `bd` tab disappears; a raw bead is still one click away on the worker
  detail page.
- API paths are unchanged, so the CLI, Telegram integration and tests are
  untouched.

## Implementation

Seven serial beads (`UI n/7`, ADR 0009), each leaving `just check`, `npx tsc
--noEmit`, `npm run lint`, `npm test -- --run` and `npm run build` green:

1. Shared primitives and rules (list, filter bar, confirm, empty/loading,
   detail shell, eslint hex rule; migrate existing pages onto them).
2. Workers page: rename, routes and redirects, sub-tabs, URL filters,
   needs-attention strip, wire requeue / close.
3. Worker detail absorbs bead features; remove `bd` tab and `features/beads`.
4. `features/triggers`: merge schedules + recurring; Scheduled sub-tabs on both
   pages; remove `features/schedules`, `features/recurring`.
5. Inbox rename and layout on shared primitives; nav badge.
6. Settings page: all groups, dropdowns, restart-required marker, constants
   endpoint and section; supervisor active-count fix.
7. Remove analytics tab and charts, four-tab nav, command palette, docs and
   screenshots; `just ui-build`.
