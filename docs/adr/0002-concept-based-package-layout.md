# ADR 0002: Organize the Code by Concept, Not by Process

## Status

Accepted

## Date

2026-09-07

## Context

Fleet has three processes: the supervisor, the web server, and the CLI.
The source tree is organized around them (`supervisor.py`, `serve/`,
`cli.py`). Concepts that all three need were re-implemented inside each
one instead of being shared.

An architecture review on 2026-09-07 found, with file references:

- The task-directory path is built by hand in about 18 places.
- Six modules parse `events.jsonl` independently.
- Five modules shell out to `bd`, with the JSON envelope unwrap copied
  four times, and two different rules for reconciling bead status with
  `task.json`.
- `supervisor.py` mixes thirteen concerns; its outcome handler alone is
  182 lines and cannot be tested apart from the queue.
- The supervisor and CLI import the fleet-home resolver from the web
  layer (`serve/stats.py`), so the core depends on the web layer.
- About 1000 of the 1628 lines in `cli.py` are logic, not command
  plumbing. Two route files hold most of the API's domain code.
- Dead code with live tests: `SpawnController` (can only return SPAWN),
  `supervisor_worktree.py`, the UI `Dashboard` page and its three
  components, and five analytics endpoints marked deprecated.
- Names that hide content: `logging.py`, `schemas.py`, `failures.py`,
  `stats.py`, `gc.py`, `BD.tsx`, `analytics_core.py`.
- Two clients for the ask_human database that have diverged: the web
  answer path drops the operator note.

Agents editing the code cannot find "the" definition of a concept, so
they add another copy. The duplication grows with every feature.

## Decision

Reorganize `src/fleet` and `src/fleet/ui/src` by concept, as described
in `docs/ARCHITECTURE.md`. Six rules govern the tree: one concept has
one home; lower layers never import higher ones; entry points are thin;
names say what is inside; dead code is deleted; pure policy is a pure
function.

The move is done as a chain of small, mechanical steps, each leaving
tests green, in this order:

1. `state/paths.py` and `beads/client.py`; replace every hand-built path
   and every `bd` call.
2. `state/events.py` as the single events reader; the two reconciliation
   rules become one in `beads/reconcile.py`.
3. `core/outcome_policy.py` extracted as a pure function; the supervisor
   split into `orchestrator/`.
4. Delete dead code.
5. Move logic out of `cli.py` and the routes; split `cli.py` by group.
6. Merge the two ask_human clients and fix the dropped note.
7. UI: shared formatters and status helpers, features folders, one
   styling approach.
8. `tests/` mirrors the source tree.

## Consequences

Positive: one grep finds one definition. Policy can be unit-tested
without subprocesses. New coders, integrations, or routes have an
obvious home. `docs/ARCHITECTURE.md` becomes the first thing an agent
reads.

Negative: a burst of import churn across the tree; every open branch
will need a rebase. Git blame history moves with the files (use
`git log --follow`). Some tests are rewritten rather than moved when the
module they tested is deleted.

Relation to ADR 0001: the store-first design lands naturally inside
`state/` and `beads/` once those packages exist. This ADR does not
decide the storage question; it creates the place where that decision
will be implemented.
