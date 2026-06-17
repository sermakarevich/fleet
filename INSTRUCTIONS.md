# Fleet Task Creation — Cheat Sheet

How to create and chain fleet tasks (beads queue). Verified 2026-06-11.

## Create a task

```bash
DESC=$(cat <<'EOF'
Context: one line + pointer to spec/design doc the coder should read.
Build: concrete, self-contained spec (paths, interfaces, constraints).
DoD: verifiable done-criteria (tests green, file X exists, command Y works).
EOF
)
ID=$(fleet bd create --title "project P0.1: short title" \
  -d "$DESC" -p 1 -l "project,phase0" \
  --cwd /abs/path/to/repo --silent | grep -oE 'fleet-[a-z0-9]+' | head -1)
echo "$ID"   # e.g. fleet-2xr6
```

- `--cwd`, `--coder`, `--model` are intercepted by fleet and stored as per-task
  overrides (everything else is forwarded to `bd create`).
- Descriptions must be **self-contained**: headless coders see only title + description
  + the repo at `--cwd`. Reference design docs by repo-relative path.
- **ID capture**: even with `--silent`, output may include the title — parse with
  `grep -oE 'fleet-[a-z0-9]+' | head -1` (first match = new task ID). Do NOT use a
  loose pattern like `[A-Za-z]+-[A-Za-z0-9]+` (matches hyphenated title words).

## Dependencies (DAG)

Semantics: **child depends on parent** = child stays out of the ready queue until parent closes.

```bash
# at create time (only with REAL existing IDs):
fleet bd create --title "child" -d "$DESC" --deps "$T1,$T2" --silent ...

# after the fact:  bd dep add <blocked/child> <blocker/parent>
fleet bd dep add fleet-aaaa fleet-bbbb                    # aaaa depends on bbbb
fleet bd dep add fleet-aaaa fleet-cccc --no-cycle-check   # bulk wiring: skip per-add check...
fleet bd dep cycles                                       # ...then verify once at the end
```

**Gotcha (learned the hard way):** invalid IDs passed to `--deps` are dropped
**silently** — the task is created with no dependencies at all. Always verify after wiring:

```bash
fleet bd dep list fleet-aaaa            # show this task's dependencies
fleet bd dep tree fleet-aaaa --direction both
fleet bd ready                          # what is claimable RIGHT NOW (should match intent)
```

## Live supervisor gotcha

If `fleet run` is active, **dep-less tasks are claimed within seconds of creation**.
So either wire deps at create time (`--deps` with verified IDs), or create the whole
DAG before starting the supervisor. Recovery if something starts prematurely:

```bash
fleet kill fleet-xxxx                        # supervisor interrupts the session
fleet bd update fleet-xxxx --status open     # re-queue; deps now gate it correctly
```

## Inspect / manage

```bash
fleet bd list                    # all tasks + status (○ open ◐ in_progress ✓ closed)
fleet bd show fleet-xxxx         # full description, assignee, status
fleet bd ready                   # unblocked open tasks (the claim queue)
fleet bd update fleet-xxxx --status open|closed ...
ps aux | grep 'fleet run'        # is a supervisor running?
```

## Conventions that worked

- Title: `<project> <phase.step>: <imperative summary>` (e.g. `invest-analyst P0.2: EDGAR collector`).
- Priority: `-p 1` for critical-path tasks, `-p 2` default for the rest.
- Labels: `-l "<project>,<phase|spike>"` for filtering.
- Create in topological order, capture each ID, pass them to `--deps` of children;
  finish with `fleet bd dep cycles` + `fleet bd ready` sanity check.
