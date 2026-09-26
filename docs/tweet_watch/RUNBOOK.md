# tweet_watch runbook

This file is `docs/tweet_watch/RUNBOOK.md`. It documents the recurring
tweet-watch worker: schedule identity, KB paths, `x` CLI commands, adding
and removing watched handles, verifying a run, and recovering from a
missed run or a corrupt state file.

If the numbered requirements in `docs/tweet_watch/REQUIREMENTS.md` (R1-R6)
disagree with this runbook, the requirements win. Report the mismatch
naming both sources instead of following a stale copy into a wrong write.

KB files live only under `/Users/sergii/.ai/knowledge/media/x/` with the
absolute prefix; never fall back to a likely path, never invent a path,
and never commit KB files to the repo — they are written directly to the
knowledge base, never committed. Never run `git add` on the watchlist,
state, or replies: KB files are written directly, never committed.

## Schedule identity

- Schedule name: `tweet-watch`.
- Cadence: every 30 minutes, cron `*/30 * * * *`.
- Overlap policy: `--overlap skip`.
- Coder: `opencode`.
- Install exactly as:

  ```
  fleet schedule create --name tweet-watch --cron '*/30 * * * *' --overlap skip
  ```

  with coder `opencode`, run from the fleet repo checkout.
- Verify with:

  ```
  fleet schedule list
  ```

  which must show the `tweet-watch` entry, plus one manual
  `fleet schedule run` to confirm a full R1-R6 pass.
- Do not create a duplicate entry under a variant name as a backup or a
  second schedule with a different name: if `fleet schedule list` shows
  two `tweet-watch`-like entries, delete the wrong one and reinstall
  exactly as documented above. A variant name is a mismatch.

## KB paths owned by the worker

- Watchlist: `/Users/sergii/.ai/knowledge/media/x/watchlist.md`
- State: `/Users/sergii/.ai/knowledge/media/x/watch_state.json`
- Interests: `/Users/sergii/.ai/knowledge/media/INTERESTS.md`
- Replies dir: `/Users/sergii/.ai/knowledge/media/x/replies`

If the KB parent dir itself is absent (`media/x/` missing, not just the
files), route through the R1 ensure path: run
`mkdir -p /Users/sergii/.ai/knowledge/media/x/` (this creates the parent
for the watchlist at `/Users/sergii/.ai/knowledge/media/x/watchlist.md`),
then let the run create the watchlist with the 5 seed handles. Never
create directories under unlisted paths.

## `x` CLI commands

Run exactly these documented invocations, in order, once per run:

```
x watch add user:<handle>
x watch check --format json
```

- `x watch add user:<handle>` once per handle (idempotent; keep the
  `user:` prefix).
- `x watch check --format json` (the `--format json` flag is required).
- Parse stdout as JSON into candidate tweets. Output piped through ad-hoc
  text-munging instead of JSON parsing is not an acceptable substitute:
  always use JSON parsing of the `--format json` output.
- On non-zero exit or unparseable output, fail loud with the handle named
  and leave state untouched for the failed scope; the next run retries.
  Never fabricate or invent tweets and never continue with cached tweets:
  the worker never fabricates tweets.

## How to add a watched handle

1. Open `/Users/sergii/.ai/knowledge/media/x/watchlist.md` in an editor.
2. Add one handle per line, e.g. `cloneisjun` on its own line. Format
   rules: one handle per line; blank lines are ignored; `#` starts a
   comment line that is ignored; a leading "@" is stripped, so write
   `cloneisjun`, not `@cloneisjun`, and never a comma-separated list
   such as `@cloneisjun, goodhartproof` on one line (M1 parses lines,
   not commas).
3. Save once. A new handle needs no state edit: a missing state entry
   means all candidates are new (R2), which is the correct first-run
   behavior — hand-inserting a guessed newest id silently skips real
   tweets, so do not touch `watch_state.json`.
4. Serial edits only: concurrent edits to `watchlist.md` are
   last-writer-wins with no merge step, so re-read the file before
   editing, make the single-line change, and save once.

## How to remove a watched handle

1. Re-read `/Users/sergii/.ai/knowledge/media/x/watchlist.md`, delete the
   handle's line, save once (serial edits, as above).
2. Leave state alone: delete the line from `watchlist.md` and leave the
   handle's key in `watch_state.json` untouched. Stale state keys are
   harmless (R2 ignores handles not in the watchlist). Hand-editing state
   risks corrupting the JSON, so hand-editing or hand-merging state files
   is forbidden here.

## Empty watchlist

Zero handles (all lines deleted or commented out) is a valid quiet
configuration: the run fetches nothing, proposes nothing, exits success
(zero proposals, zero new files), and leaves state unchanged. A watchlist
containing only blanks and `#` comments parses to an empty handle list
with the same quiet result — this is the documented effect of the ignore
rules, not corruption. Never fix an empty watchlist by re-seeding the 5
seed handles: an existing file is never overwritten, and re-seeding is
forbidden.

## How to verify a run

1. Run `fleet schedule list` and confirm the `tweet-watch` entry is
   present.
2. Trigger one manual `fleet schedule run` and watch the output.
3. Quiet run success signals: quiet run, zero proposals and zero new
   files in `/Users/sergii/.ai/knowledge/media/x/replies/`.
4. HIGH run success signals: one `ask_human` call per HIGH tweet, each
   proposal containing the tweet link plus the drafted reply draft. One
   call per HIGH tweet: N new HIGH tweets produce N proposals, each with
   link + draft; zero HIGH tweets produce zero calls.
5. Length rule: a draft at or over the X post limit is rewritten or
   trimmed to the limit at a word boundary before proposing — never
   auto-truncate mid-word. Truncate is forbidden; rewrite/trim first.

## Recovery: corrupt state file

A corrupt state file (`/Users/sergii/.ai/knowledge/media/x/watch_state.json`
with invalid JSON, or valid JSON with the wrong shape such as a list
instead of a handle-to-id map, or numeric instead of string ids) aborts
the run before fetch with an error naming
`/Users/sergii/.ai/knowledge/media/x/watch_state.json`. Abort-before-fetch
is mandatory.

1. Abort runs (do not start new ones).
2. Back up the corrupt file first — never reset it, never delete it:
   `cp watch_state.json watch_state.json.bak-<date>` (back up before any
   repair). Deleting state re-emits the full history as new (missing entry
   means all candidates new) and spams duplicate proposals.
3. Hand-repair the JSON or restore from backup, then validate with
   `python3 -c "import json; json.load(open('/Users/sergii/.ai/knowledge/media/x/watch_state.json'))"`.
   The `json.load` check must pass before resuming.
4. Resume runs. Never silently reset state to `{}`: a silent reset
   re-emits everything ever seen as duplicate proposals.

## Recovery: missed run

The next tick self-heals: state persists newest seen ids, so one manual
run picks up everything since the last success. Trigger exactly one
manual `fleet schedule run` — never one run per missed tick, never replay
missed ticks to catch up. Replaying one run per missed tick (catch up by
replay) is forbidden.

## Backlog behavior

After missed runs, dozens of new tweets may surface on the next tick
(backlog of new tweets across handles). Bounded behavior: all new tweets
are emitted exactly once, each HIGH tweet gets its own proposal — no
batching, no sampling to keep it short. An operator overwhelmed by N
proposals triages per-proposal (confirm or decline each proposal) and
never edits state to skip the backlog.

## Troubleshooting

- `x` CLI missing or failing (`command not found`, non-zero exit,
  unparseable stdout): the run fails loud with the handle named; state
  stays untouched for the failed scope and the next run retries. Never
  continue with cached tweets or hand-invented candidates.
- `/Users/sergii/.ai/knowledge/media/INTERESTS.md` missing or unreadable:
  abort proposals for the run (R5); never score by gut feel. Tweets stay
  new via persisted state and are re-driven next run.
- `fleet schedule list` not showing `tweet-watch`: reinstall exactly with
  `fleet schedule create --name tweet-watch --cron '*/30 * * * *'
  --overlap skip` (coder `opencode`), then re-verify with
  `fleet schedule list` plus one manual `fleet schedule run`. Never create
  a second entry under a variant name as a backup.
- Permission errors (`permission denied` on the watchlist, state, or
  `replies/`): fix ownership/permissions (`ls -l`, then `chmod`/`chown`
  as appropriate) and re-run. Never `sudo`-run the worker and never move
  the KB files to a writable path: running as another user splits state
  across homes and forks the newest-id tracking.
- Clock skew or a long scheduler outage (no runs for days; reply files
  older than 3 days): the next run still emits everything since the last
  persisted id (no tweets lost), but the R4 3-day window no longer blocks
  repeats of recently proposed angles whose files aged out. Triage
  proposals with extra care after an outage instead of assuming dedupe
  still covers the gap.
- Source tweet deleted between fetch and proposal (link 404s during
  verification): propose once with the cached text plus a dead-link note
  (R5); never silently drop an emitted tweet and never propose without
  the link.
- Confirmation recorded without a reply id ("posted" with no id or link
  in the `ask_human` answer): store nothing and log pending-confirmation
  with the source id (R5/R6); never invent an id to complete the
  `<date>-<id>.md` filename. The reply file is written on the next
  confirmed answer carrying the id.
- Operator already replied from outside the worker (a manual reply on X
  with no file in `replies/`): the worker still proposes (R5); the linked
  thread is the backstop. Never invent an extra liveness check step.

## Concurrency

- Overlapping runs (a manual `fleet schedule run` colliding with the
  30-minute tick; the installed schedule uses `--overlap skip` so this is
  manual-only) use no-locking semantics: both runs may propose
  independently (R5) and double confirmation converges via idempotent
  same-path R6 writes. Do not use lockfiles, do not merge state files,
  and do not de-duplicate the other run's proposals — the operator seeing
  a duplicate proposal is the accepted backstop, and R4 blocks repeats
  once one reply is persisted. Overlap colliding runs therefore need no
  lock: no lockfiles, no state-file merges.
- Two operators editing `watchlist.md` at once: serial edits only —
  re-read before editing (see above). There is no merge step.
- State read-modify-write racing a concurrent run (both runs read the
  same state, both persist newest ids): last-writer-wins on the JSON map
  is acceptable — ids only move forward per handle, so the newer write
  dominates and the next tick heals any missed key. Forbid hand-merging
  two state copies: hand-merging risks reintroducing stale ids and
  re-emitting tweets.

## Runbook drift

If INTERESTS.md gains a core topic, the reply format gains a field, the
`x` CLI changes output shape, or schedule flags change while this
runbook still documents the old shape, the numbered requirements R1-R6
win over the runbook copy. Report the mismatch naming both sources (the
R1-R6 requirement text and this stale runbook section) instead of
following the stale copy into a wrong write.
