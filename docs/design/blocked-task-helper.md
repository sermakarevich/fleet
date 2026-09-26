# Design: blocked-task helper

Replaces the periodic triage question (`orchestrator/triage.py`,
`core/triage_policy.py` rules) with a priority-0 LLM "helper" bead per
automatic block event. Full requirements:
`.sddw/blocked-tasks-help-worker/requirements.md`.

## Where it lives

New service `orchestrator/helper.py` (`HelperSpawn`, `ServiceOrder.Helper`,
same slot `Triage` had), registered in `orchestrator/__init__.py` in place
of `Triage`. It ticks every `STATUS_LOG_INTERVAL_SEC` like `StallWatch`
(no interval config needed — only on/off matters per FR-07).

Unlike the old triage, the helper does its Q&A **inside the worker run**,
not in the orchestrator: every fleet worker already has the blocking
`mcp__ask_human__ask_human_question` tool (`templates/INSTRUCTION_COMMON.md`
"ask_human protocol"). The orchestrator's only job is to *create* the
right helper bead with the right description; the coder LLM investigates,
asks, and implements.

## Creating the helper bead (pattern: `_apply_repair` in old triage.py)

Each tick: `queue.list_blocked()` → for each bead with `blocked_reason` set
(auto-blocked) and no active `ignore_until` (reuse `ignore_active`), check
dedup, then `queue.create_task(...)` with:
- title: `Helper: unblock <target-id> ("<title>")`
- description: `templates/HELPER_INVESTIGATE.md` rendered with block info,
  prior-chain investigations, and the task dir/repo paths (same fields the
  old investigator trigger used: `task_id`, `title`, `blocked_reason`,
  `blocked_at`, `cwd`, `task_dir`, `rounds`, `stderr_tail`).
- labels: `["helper", f"helps:{target_id}", f"chain:{root_id}"]`
- priority via `extra_args="-p 0"` (bd create flag) plus metadata
  `{"fleet_isolation": "none"}` isolation opt-out is NOT set — helper may
  need to edit repo code, so it keeps normal isolation.
- coder/model: `config.helper_coder` / `config.helper_model` (new config,
  default `claude`/`opus`), not the general per-task default.
- After create: `TaskMeta.update(task_dir_of_target, helper_task_id=helper.id,
  helper_blocked_at=blocked_at)` on the **target** bead (T or a helper),
  and `TaskMeta.update(task_dir_of_helper, helper_for=target_id,
  chain_root=root_id, chain_seq=n)` on the new helper bead.

## Dedup (FR-01/02)

Skip a candidate when its `helper_task_id` in task.json is set, still not
closed (`_repair_live`-style check via `queue.get(...).status`). The
check ignores `blocked_at`: a task that is retried and re-blocks while its
helper still runs (the helper may be retrying it) must not get a second
helper. Once that helper is closed, the next tick spawns a fresh one for
the current block.

## Chain linkage (FR-19/21/22)

`root_id` = the original task's own id, carried forward as `chain_root`
on every helper in the chain (a helper's target may itself be a helper,
but `chain_root` always points at the first blocked task). When a helper
blocks, it is scanned exactly like any blocked bead — the label
`helps:<target>` + `chain:<root>` on it means its own helper (H_{n+1}):
target = the blocked helper H_n, root = unchanged. `HELPER_INVESTIGATE.md`
is rendered with every earlier `HELPER_REPORT.md` in the chain (read via
`chain_root`'s `helper_task_id` history — walk labels `chain:<root>`
across `queue.list_by_label` or similar) so H_{n+1} sees H_1..H_n's
reports (FR-22).

## Progress check (FR-23/24)

The helper itself writes `artifacts/HELPER_REPORT.md` with a `Same as
previous root cause: yes/no` field (told explicitly, in its prompt, what
the earlier root causes in the chain were). Before creating H_{n+1}, the
spawn service reads H_n's `HELPER_REPORT.md`
(`state/helper_report.py::read_report`, mirrors old
`state/investigation.py`); if `same_as_previous` is `yes`, no further
helper is created — instead `store.ask(...)` (existing non-blocking
`QuestionStore`, same call triage used for its digest) posts one free-text
summary question built from every report in the chain, and a
`chain_stopped` flag is set on the root task's meta so the chain is never
retried.

## Removing old triage

Delete `orchestrator/triage.py`, `triggers/lookup.py`, `core/investigation.py`,
`state/investigation.py`, `docs/triggers/blocked-task-investigator.json`,
the `Triage` service wiring, and the triage-only parts of
`core/triage_policy.py` (`Proposal`, `TriageRule`, all `_is_*/_proposal`
rule functions, `RETRY_*`/`CLOSE`/`IGNORE_*`/`DIGEST_*` option constants,
`MergeConflictInfo`, `propose`, `digest_text`). Keep `ignore_active` and
`ignore_until_24h` — used by `beads/task_store.py`,
`state/task_summary.py`, `triggers/sources/blocked_task.py` — by moving
them to `core/ignore_policy.py` and updating those three importers plus
the new `helper.py`. Remove `triage_interval_minutes`,
`triage_wait_for_investigation`, `triage_investigation_wait_minutes` from
`core/config.py`, and the `core/triage_policy.py` entries in
`serve/api/config.py`'s `_EXTRA_MODULES`/`_EXTRA_CONSTANTS`.
