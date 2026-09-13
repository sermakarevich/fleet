# ADR 0012: Never serve stale task.json statuses silently when beads is unavailable

## Status

Accepted

Implemented by fleet-mq57m (2026-09).

## Date

2026-09-13

## Context

Beads (`bd`) is the source of truth for task status; `GET /api/tasks`
reconciles each task.json row against the beads map
(`fleet/beads/status_cache.py`). When `bd` failed, the map was `None`
and the handler fell back to raw task.json statuses with no signal.
Stale task.json rows (claims whose leases long expired) surfaced
2282 already-closed tasks as `in_progress` — 92 UI pages of phantom
"running" workers — plus wrong open/blocked counts. The cache's own
comment promised "keep serving the last-known map" on `BdError`, but
the code overwrote the entry with `None`.

## Decision

- `beads/status_cache.py` gains `get_beads_snapshot()`: on `BdError`
  the previous non-None map keeps being served (marked `stale`,
  `available=False`); only a beads that never succeeded yields
  `map=None`. The failure is logged at most once per TTL window, and
  the TTL expiry is stamped after the subprocess call so a slow `bd`
  does not birth an already-expired entry.
- `GET /api/tasks`, `GET /api/analytics/summary` and `GET /api/supervisor`
  return `beads_available: bool` plus `beads_error: str | null`
  (optional response-model fields, default available).
- With no usable map, `GET /api/tasks` reports locally-`closed` rows as
  `closed` and every other row as `"unknown"` — raw task.json statuses
  are never served as-is, so nothing renders as running/queued/blocked.
- The workers Runs tab shows a red `role="alert"` banner
  ("beads unavailable: \<error> — statuses may be stale") while
  `beads_available` is false, suppresses the filter alert counts and
  the footer's blocked count, and labels `unknown` rows "Unknown".

## Consequences

- Response-schema change (additive, backward compatible): `TaskListResponse`,
  `AnalyticsSummary`, `SupervisorResponse` each gain `beads_available`
  (default true) and `beads_error` (default null); UI types regenerated
  via `just ui-types`, and `api.getTasks` now returns the envelope.
- While beads is down, the Runs tab shows its rows under no status
  filter (unknown matches none) plus the banner — honest, but operators
  cannot filter by real status until `bd` recovers.
