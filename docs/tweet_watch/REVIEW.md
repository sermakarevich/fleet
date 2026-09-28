# tweet_watch — fresh-eyes review (spec vs code, reviewed state 075b4ff)

Read: REQUIREMENTS.md, WORKER.md, RUNBOOK.md, failures M1-M3/R1-R9,
`src/fleet/tweet_watch/{kb_files,x_fetch,reply_files,worker}.py`, all
`tests/tweet_watch/` (490 passed before fixes). KB convention checked
against live files in `/Users/sergii/.ai/knowledge/media/x/replies/`.

Format per finding: severity | unit / failure case | file:line | fix | status.

## Findings

### F1 MEDIUM — R6/M3: `> reply to:` records the reply's own id, not the source tweet id
- Unit: reply persistence (R6-F9 format). Files: `src/fleet/tweet_watch/reply_files.py:140`, `src/fleet/tweet_watch/worker.py:721` (`persist_reply`), call site `worker.py:813`.
- Evidence: live KB files all show filename id == `> source:` id (the reply's own post) and `> reply to:` == a *different* id (the watched source tweet, e.g. `2026-09-19-2101144918706073932.md` replies to `2101074795643494546`). Code writes `> reply to: {reply_id}` (self-reference), because `persist_reply` never receives the source tweet id and `write_reply` has no parameter for it. Provenance of every worker-stored reply is wrong.
- Fix: `write_reply` gains keyword-only `source_id` (falls back to `reply_id` when absent, so M3 direct callers are unaffected); `persist_reply` extracts the source tweet id from `source_url` via the existing status-URL pattern and passes it through. `persist_reply`'s signature is unchanged.
- Status: fixed.

### F2 MEDIUM — R6: one failed reply-file write aborts the run and silently drops later HIGH tweets forever
- Unit: batch persistence (R6-F15). File: `src/fleet/tweet_watch/worker.py:813` (`run()` loop).
- Evidence: `persist_reply` exceptions propagate out of `run()` immediately. State was already advanced by R2, so tweets after the failed one are never proposed this run AND never re-emitted next run — lost forever. Proposal failures in the same loop are recorded and continued (`failures` list); persist failures must behave the same per R6-F15 ("reported as unpersisted", operator retries — retry is only possible if the run continues and exits loud).
- Fix: catch per-tweet persist exceptions into `failures`, continue the batch, re-raise at end (same shape as the proposal path).
- Status: fixed.

### F3 LOW — R6: confirmation containing the word "on" (no ISO date) is rejected even with a valid reply id
- Unit: confirmation parsing (R6-F3/F5 boundary). File: `src/fleet/tweet_watch/worker.py:652` (`_ON_WORD_RE`), applied at `worker.py:708`.
- Evidence: `_ON_WORD_RE = re.compile(r"\bon\b")` vetoes ANY answer containing "on" when no ISO date is present, e.g. "posted 2103871751771898112 on my main account" → `None` → valid confirmation lost, nothing stored, no loud error. The dedicated regexes already catch every real non-ISO date shape (`_SLASH_DATE_RE`, `_NON_ISO_DAY_RE`, `_MONTH_DAY_RE`); the blanket word ban adds only false negatives. All pinned tests (`on 26/09/2026`, `yesterday`, `on Sept 26`) stay rejected via those regexes.
- Fix: remove the `_ON_WORD_RE` clause and constant.
- Status: fixed.

### F4 LOW — R6: bare reply id picks the first number in the answer, not the id
- Unit: confirmation parsing (R6-F4). File: `src/fleet/tweet_watch/worker.py:714`.
- Evidence: `_BARE_ID_RE.search(scrubbed)` returns the first digit run, so "posted with 2 tries, id 2103871751771898112" persists `2` as the reply id, producing a wrong `<date>-2.md` filename. Reply ids are long snowflakes; the longest digit run is the id.
- Fix: pick the longest digit run (first wins ties).
- Status: fixed.

### F5 LOW — R5: prompt room budget computed from a placeholder head, over-trimming the source snippet
- Unit: proposal prompt (R5-F11 cardinality/content). File: `src/fleet/tweet_watch/worker.py:494` (`_PROMPT_HEAD = "Reply proposal for :\n"`), used at `worker.py:632`, while the real prompt built at `worker.py:641` starts with `f"Reply proposal for {tweet_url}:\n"`.
- Evidence: the budget subtracts the 21-char placeholder instead of the real head (placeholder + ~50-char URL), so the cached source snippet is trimmed ~50 chars shorter than the cap allows. Prompt content contract (link + draft) unaffected, but context is needlessly cut.
- Fix: compute `room` from the actual head string; drop the stale constant.
- Status: fixed.

### F6 LOW — R4: duplicate/empty drafts skipped with no log line naming the tweet
- Unit: dedupe observability (R4-F1/F2: "logged with the tweet id"). File: `src/fleet/tweet_watch/worker.py:796`.
- Evidence: `is_duplicate(...) → continue` is silent; an operator cannot tell a blocked draft from a quiet run. Same for content-free drafts.
- Fix: `logger.info` naming tweet id and reason before `continue`.
- Status: fixed.

### F7 LOW — M2: records skipped for missing id are not reported
- Unit: record parsing (M2-F5: "skip that record and report an error naming the handle"). File: `src/fleet/tweet_watch/x_fetch.py:167`.
- Evidence: id-less records `continue` silently; the pinned test only asserts skip/no-synthesis, but the failure doc also requires a report naming the handle.
- Fix: `logger.warning` with the offending handle (or record summary when handle absent).
- Status: fixed.

### F8 LOW — M1: float state ids stringify to `1e+18` form
- Unit: state load (M1-F9/F16). File: `src/fleet/tweet_watch/kb_files.py:73`.
- Evidence: `str(value)` on a float id (e.g. hand-edited `1e18`) yields `'1e+18'`, exactly the formatting M1-F9 forbids; the stored "newest id" then corrupts R2 comparison. Pinned tests cover int coercion only.
- Fix: int → `str()`; integral float → `str(int(v))`; non-integral float → `ValueError` (wrong-type, names handle).
- Status: fixed.

### F9 INFO — R3: scoring runs on hardcoded unit lists gated on INTERESTS.md, not parsed from it
- Unit: interest scoring (R3-F3: "never fall back to a hardcoded topic list"). File: `src/fleet/tweet_watch/worker.py:199`.
- Evidence: `_CORE_UNITS`/`_ADJACENT_UNITS` are static phrase tables; INTERESTS.md only gates them (`gate in interests_norm`) plus a generic token-overlap fallback. If INTERESTS.md gains a genuinely new core topic with none of the hardcoded phrases, tweets on it score MEDIUM/LOW until the table is edited — the observable "given a fixed tweet and the INTERESTS.md file, the label is reproducible" holds, and all r3 contract tests pin current labels, so this is a design limitation, not a behavior bug today.
- Fix: would need a real topic parser + test changes (tests read-only).
- Status: deferred (needs test change; raise via ask_human in a non-auto step).

### F10 INFO — R3/R5: missing INTERESTS.md exits the run 0/quiet instead of erroring
- Unit: run abort contract (R3-F3, R5-F8: "abort ... with an error"). File: `src/fleet/tweet_watch/worker.py:772`.
- Evidence: `logger.warning` + `return` yields exit success with zero proposals. Observable outcome is correct (nothing proposed, state untouched so next tick re-drives), but a scheduler sees success, not failure. The quiet-abort is explicitly pinned by `tests/tweet_watch/r5/test_propose_batch.py::test_missing_interests_aborts_proposals_with_error` ("aborts the run's proposals quietly (no raise)").
- Fix: raise instead of return — requires test change first.
- Status: deferred (pinned by test; needs ask_human before touching).

## Notes (not code findings)

- N1: `fleet schedule list` in this environment shows "No schedules" — the R9 live-schedule deliverable is not installed here. R9 unit tests construct the `Schedule` object in memory and pass; install/verify is an ops action outside this review's code-fix scope, so it is not counted above. Reinstall per RUNBOOK (`fleet schedule create --name tweet-watch --cron '*/30 * * * *' --overlap skip`, coder `opencode`) + `schedule list` + one manual run before closing the feature.
- N2: reviewed and found correct (no change): R1 seed exactness/atomicity, R2 byte-identical state on quiet runs, numeric id comparison, reload-before-save merge, M3 3-day inclusive window with future-date exclusion, R5 HIGH-only gate/one-call-per-tweet, R6 decline/ambiguous/no-id → store nothing, write atomicity, R7/R8 template and runbook content (spot-checked against failure docs; R8 `EXPECTED_CREATE` in r9 conftest matches RUNBOOK).
