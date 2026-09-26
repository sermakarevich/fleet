# tweet_watch — Requirements

## Shared modules

## M1 kb-files
Needed by R1, R2, R6. Read/parse the user-editable watchlist at
`/Users/sergii/.ai/knowledge/media/x/watchlist.md` (one X handle per line,
ignore blank lines and `#` comments, strip leading `@`) and load/save
`/Users/sergii/.ai/knowledge/media/x/watch_state.json`
(map handle -> newest seen tweet id, string). Missing state file reads as `{}`.

## M2 x-fetch
Needed by R2. Run `x watch add user:<handle>` once per handle (idempotent)
then `x watch check --format json`, parse stdout JSON into a list of
`{id, handle, text, url, created_at}` records. Non-zero exit or unparseable
stdout surfaces as an error naming the handle; never fabricates tweets.

## M3 reply-files
Needed by R4, R5, R6. Read files in
`/Users/sergii/.ai/knowledge/media/x/replies/` (`<date>-<id>.md`,
existing per-tweet format: header, `> source:`, `> reply to:`, quoted body,
stats line) and write new ones in the same format. Lists files from the last
3 days by filename date prefix.

## Requirements

## R1 watchlist ensure and read
On every run, ensure `/Users/sergii/.ai/knowledge/media/x/watchlist.md`
exists; if missing, create it with exactly these 5 seed handles, one per
line: `omarsar0`, `typesafeai`, `cloneisjun`, `goodhartproof`,
`SakanaAILabs`. Then return the ordered handle list via M1
(blank lines/`#` comments ignored). Observable: missing file ->
created with 5 seeds; existing file is never overwritten.

## R2 new-tweet detection and state update
For each handle from R1, fetch candidate tweets via M2 and emit only those
with ids newer than the handle's entry in `watch_state.json` (missing entry
-> all candidates are new). After the check, persist the newest seen id per
handle back to `watch_state.json` via M1. Observable: second run with no new
tweets emits nothing and leaves state unchanged; new tweets appear exactly
once across consecutive runs.

## R3 interest scoring
Score each new tweet from R2 as HIGH, MEDIUM, or LOW against
`/Users/sergii/.ai/knowledge/media/INTERESTS.md` (Core topics -> HIGH,
Adjacent -> MEDIUM, otherwise LOW). Observable: given a fixed tweet and the
INTERESTS.md file, the label is reproducible; core-topic tweets (agent
harnesses, coding agents, verifier models, voice agents, cost engineering)
score HIGH, price-talk/memes/giveaways score LOW.

## R4 recency dedupe
Before proposing any draft, read reply files from the last 3 days via M3 and
drop (or flag for rewrite) any draft near-identical in wording or point to
an existing reply. Observable: a draft copying a reply from the last 3 days
is rejected; a draft on a new angle passes; replies older than 3 days do not
block.

## R5 HIGH-only human proposal
For each HIGH tweet that passes R4, call the `ask_human` tool once with the
tweet link plus a drafted reply post. The draft adds something new to the
original tweet's content (not praise-only, not a restatement) and follows the
voice notes in INTERESTS.md (plain language, no hype words, one concrete
observation or number first, teaching tone, abbreviations explained on first
use). MEDIUM/LOW tweets never trigger a proposal. Observable: N new HIGH
tweets -> N proposals, each containing link + draft; zero HIGH tweets -> zero
calls.

## R6 reply persistence
When the operator confirms a reply was posted (via the ask_human answer),
store it as `/Users/sergii/.ai/knowledge/media/x/replies/<date>-<id>.md`
(`date` = posting date `YYYY-MM-DD`, `id` = posted reply tweet id) in the
existing per-tweet format via M3. Unconfirmed drafts store nothing.
Observable: confirmed reply -> exactly one new file at the expected path in
the existing format; unconfirmed -> no new file.

## R7 worker bead body template
Repo file (e.g. `docs/tweet_watch/WORKER.md` or a fleet template) containing
the copy-paste bead body for the recurring run: the ordered steps R1->R6
with exact KB paths, the `x` CLI invocations, and the HIGH-only proposal
rule. Observable: the file exists in the repo and a worker following it
verbatim performs steps R1-R6.

## R8 runbook
Repo file `docs/tweet_watch/RUNBOOK.md` documenting: schedule name/cadence,
KB paths owned by the worker, the `x` CLI commands, how to add/remove a
watched handle, how to verify a run, and how to recover from a missed run or
corrupt state file. Observable: the file exists and each listed procedure
works as written.

## R9 schedule install and verify
Installed recurring schedule: `fleet schedule create --name tweet-watch
--cron '*/30 * * * *' --overlap skip` with coder `opencode`, verified by
`fleet schedule list` showing `tweet-watch` and one manual
`fleet schedule run` completing. Observable: `schedule list` contains the
entry; the manual run executes R1-R6 once.
