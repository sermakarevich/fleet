# tweet_watch worker — recurring run bead body

Copy-paste body for one scheduled run. Perform exactly one pass through the
numbered steps R1, R2, R3, R4, R5, R6 in order, then exit. Do exactly one
pass per run: never loop on a timer and never reinstall the schedule from
inside the run.

If the numbered requirements in `docs/tweet_watch/REQUIREMENTS.md` disagree
with this copy, the requirement wins. Report the mismatch naming both
sources instead of following a stale or drifted copy.

A missing template is a hard stop: never reconstruct the procedure from
memory. KB files live only under `/Users/sergii/.ai/knowledge/media/x/`
with the absolute prefix; never fall back to a likely path, never invent a
path, and never commit KB files to the repo — write them directly to the
knowledge base.

## R1 ensure and read the watchlist

1. If missing, create `/Users/sergii/.ai/knowledge/media/x/watchlist.md`
   with exactly these 5 seed lines in order, one per line:
   `omarsar0`, `typesafeai`, `cloneisjun`, `goodhartproof`, `SakanaAILabs`.
   Never invent seeds. An existing file is never overwritten.
2. If the parent dir `/Users/sergii/.ai/knowledge/media/x/` itself is absent,
   run `mkdir -p /Users/sergii/.ai/knowledge/media/x/` via this ensure path,
   then create the file as above.
3. Read the ordered handle list from the file (ignore blank lines and `#`
   comments, strip a leading `@`). A worker that finds no watchlist file and
   no instruction here stops with an error naming the watchlist path.
4. Take the R1 snapshot of the handle list and work that snapshot for the
   whole run. If the watchlist is edited mid-run, the next run picks it up;
   do not re-read mid-batch.

## R2 fetch new tweets and persist state

1. Run `x watch add user:<handle>` once per handle (idempotent), then
   `x watch check --format json`. Run exactly these documented invocations;
   `check` without `--format json` or any undocumented flag is a template
   bug to fix, not to paper over.
2. Parse stdout JSON into candidate tweets. On non-zero exit or unparseable
   output, fail loud with the handle named and leave state untouched for the
   failed scope so the next run retries. Never fabricate or invent tweets
   and never continue with cached candidates.
3. Emit only tweets with ids newer than the handle's entry in
   `/Users/sergii/.ai/knowledge/media/x/watch_state.json` (a missing entry
   means all candidates for that handle are new).
4. Persist the newest seen id per handle back to
   `/Users/sergii/.ai/knowledge/media/x/watch_state.json`. Without this
   write-back every run re-emits the same tweets. A run that reaches end of
   run with new tweets but no persist instruction reports it instead of
   exiting successfully.
5. If the state file is corrupt (invalid JSON or wrong shape), abort before
   fetch with an error naming the state path. Never silently reset it to an
   empty map: a helpful reset re-emits everything ever seen.

## R3 score each new tweet HIGH, MEDIUM, or LOW

Read `/Users/sergii/.ai/knowledge/media/INTERESTS.md` fresh once per run.
Core topics score HIGH, adjacent topics score MEDIUM, everything else scores
LOW. If INTERESTS.md is missing or unreadable, abort proposals for the run
with an error or stop: never score by gut feel. Tweets stay new via the
persisted state and are re-driven next run.

## R4 recency dedupe over the last 3 days

1. Read reply files from the last 3 days in
   `/Users/sergii/.ai/knowledge/media/x/replies/` and compare each draft
   against them before proposing. Drop (or flag for rewrite) any draft that
   is near-identical or a duplicate in wording or point to an existing reply.
   A draft on a new angle passes; replies older than 3 days do not block.
2. Fail closed: no proposal goes out without the dedupe verdict. If the
   recent-reply read is impossible, stop the proposal phase with an error
   naming the missing check rather than proposing unchecked drafts.
3. Intra-batch drafts count too: compare each new draft against drafts
   already proposed in this run.

## R5 HIGH-only proposal via ask_human

1. The HIGH-only gate binds: propose HIGH tweets only. MEDIUM and LOW tweets
   never trigger a proposal. A template reading of interesting without the
   HIGH, MEDIUM, LOW labels does not authorize extra proposals.
2. For each surviving HIGH tweet call the `ask_human` tool once with the
   tweet link plus the drafted reply. One tweet gets exactly one call: never
   batch N HIGH tweets into one call and never fan one tweet out into two
   calls.
3. The draft adds something new to the original tweet (not praise-only, not a
   restatement) and follows the voice notes in
   `/Users/sergii/.ai/knowledge/media/INTERESTS.md`: plain language, no hype
   words, one concrete observation or number first, teaching tone,
   abbreviations explained on first use. Drafts that cannot be voice-checked
   are not proposed.
4. Check the draft length before proposing: rewrite or trim to the 280
   character post limit at a word boundary first. Never auto-truncate
   mid-word into an unpostable proposal.
5. If a source tweet was deleted between fetch and proposal (link 404s),
   propose once with the cached text plus a dead-link note. Never silently
   drop an emitted tweet and never propose without the link.
6. If the operator already replied manually from outside the worker (an
   outside or already replied thread with no file in `replies/`), still
   propose: the linked thread is the backstop. Never invent an extra
   liveness check step.
7. Quiet exit: zero new HIGH tweets means zero `ask_human` calls, zero new
   files, successful run. Never send a nothing-to-report proposal and never
   raise a spurious error on a quiet run.
8. If the `ask_human` tool fails mid-batch (tool error, timeout, unreachable
   console), record that tweet as unproposed, continue with the remaining
   HIGH tweets, and exit loud (non-zero) at the end. Never treat the failure
   as a decline and never treat it as a confirmation.

## R6 store confirmed replies only

1. Store a reply file only when the operator confirms the reply was posted
   and supplies the posted reply id. Unconfirmed drafts store nothing.
2. Write `/Users/sergii/.ai/knowledge/media/x/replies/<date>-<id>.md` where
   the date is the posting date `YYYY-MM-DD` and the id is the posted reply
   tweet id. A confirmation without a reply id stores nothing: log it as
   pending-confirmation with the source id and never invent an id to
   complete the filename.
3. Overwrites of an existing same-path file are idempotent: last confirmed
   text wins, no `-2` duplicates. Writes use one file per reply with an
   atomic rename per write; never append to a shared index file with a
   read-modify-write cycle.

## Overlapping runs

Overlapping or concurrent runs (for example a manual run colliding with the
30-minute tick) may each call `ask_human` independently; never try to
de-duplicate the other run's proposals. Do not use lockfiles and do not
merge state files. Double confirmation converges via the idempotent
same-path reply writes above: the atomic rename means a concurrent listing
sees a complete file or misses it, never a half-written body. The operator
seeing a duplicate proposal is the accepted backstop, and the R4 check
blocks repeats once one reply is persisted.
