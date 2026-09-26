"""Main-path end-to-end test for tweet_watch (R1 -> R6 happy path).

Drives the real flow through ``fleet.tweet_watch.worker.run`` with real KB
files on disk (watchlist, state, INTERESTS.md, replies dir) and real
modules. Only external services are faked:

- the ``x`` CLI: a fake ``x`` executable shim on PATH serving one canned
  ``watch check`` payload (no handles are pre-registered anywhere else);
- the ``ask_human`` tool: the ``ask`` callable seam, scripted to confirm
  the reply was posted with a bare numeric reply id.

Final observable result: one proposal carrying the tweet link, exactly one
new reply file at the expected ``<date>-<id>.md`` path in the existing
per-tweet format, and the state file advanced to the new tweet id.
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

import fleet.tweet_watch.worker as worker_mod
from fleet.tweet_watch.worker import run

TODAY = date(2026, 9, 26)
HANDLE = "omarsar0"
TWEET_ID = "1968123456789012345"
TWEET_URL = f"https://x.com/{HANDLE}/status/{TWEET_ID}"
TWEET_TEXT = (
    "Shipped a fleet of headless coding-agent worker loops draining a "
    "central beads queue with a supervisor retrying failed tasks. "
    "A verifier model gates releases and cut bad deploys in half."
)
REPLY_ID = "2103871751771898112"

INTERESTS_TEXT = """# INTERESTS.md

## Core (score HIGH)

1. **AI agent harnesses and orchestration** — building/running fleets of
   autonomous coding agents: central task queues (beads), headless worker
   loops, supervisors, multi-harness setups.
2. **Coding agents and AI-assisted coding patterns** — opencode, Claude Code,
   model picks (Muse Spark, Claude Fable for design).
3. **Agent evaluation and verifier models** — TypeSafe Jev (typed answers with
   calibrated probabilities), post-interruption recovery (IHBench), eval
   harnesses, verifier models, release pipelines.
4. **Voice agents** — real-time voice pipelines: speech-to-text/text-to-speech
   and turn-taking, latency engineering, pipelined vs speech-to-speech.
5. **Agentic cost engineering** — token economics of agent fleets at scale:
   tasks-per-dollar, cheap local models vs frontier models.

## Voice notes for proposed replies

- Plain language, no hype words.
- Lead with one concrete observation or number, not praise.
- Teaching tone.
- Explain abbreviations on first use.
"""


class AskRecorder:
    """Fake ask_human: records prompts, replays scripted answers."""

    def __init__(self, answers: list[str]) -> None:
        self.prompts: list[str] = []
        self._answers = list(answers)

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self._answers[min(len(self.prompts) - 1, len(self._answers) - 1)]


def _install_fake_x_cli(monkeypatch, tmp_path: Path) -> None:
    """Put a fake ``x`` executable first on PATH.

    ``x watch add user:<handle>`` exits 0 (idempotent register);
    ``x watch check --format json`` prints one canned HIGH-topic tweet.
    """
    check_payload = json.dumps(
        [
            {
                "id": TWEET_ID,
                "handle": HANDLE,
                "text": TWEET_TEXT,
                "url": TWEET_URL,
                "created_at": "2026-09-26T10:00:00Z",
            }
        ]
    )
    payload_file = tmp_path / "check.json"
    payload_file.write_text(check_payload, encoding="utf-8")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    shim = bindir / "x"
    shim.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = "watch" ] && [ "$2" = "add" ]; then exit 0; fi\n'
        'if [ "$1" = "watch" ] && [ "$2" = "check" ]; then '
        f'cat "{payload_file}"; exit 0; fi\n'
        'echo "unexpected x argv: $@" >&2; exit 1\n',
        encoding="utf-8",
    )
    shim.chmod(0o755)
    monkeypatch.setenv("PATH", str(bindir) + os.pathsep + os.environ.get("PATH", ""))


def test_main_path_one_high_tweet_proposed_confirmed_and_stored(
    monkeypatch, tmp_path: Path
) -> None:
    kb = tmp_path / "kb"
    watchlist = kb / "x" / "watchlist.md"
    state = kb / "x" / "watch_state.json"
    interests = kb / "INTERESTS.md"
    replies = kb / "x" / "replies"
    watchlist.parent.mkdir(parents=True)
    replies.mkdir(parents=True)
    watchlist.write_text(f"{HANDLE}\n", encoding="utf-8")
    interests.write_text(INTERESTS_TEXT, encoding="utf-8")

    monkeypatch.setattr(worker_mod, "WATCHLIST_PATH", watchlist)
    monkeypatch.setattr(worker_mod, "STATE_PATH", state)
    monkeypatch.setattr(worker_mod, "INTERESTS_PATH", interests)
    monkeypatch.setattr(worker_mod, "REPLIES_DIR", replies)
    _install_fake_x_cli(monkeypatch, tmp_path)

    ask = AskRecorder(answers=[f"posted {REPLY_ID}"])
    run(ask=ask, today=TODAY, interests_text=None, recent_texts=None)

    assert len(ask.prompts) == 1
    assert TWEET_URL in ask.prompts[0]

    expected = replies / f"2026-09-26-{REPLY_ID}.md"
    assert expected.is_file()
    assert [p.name for p in replies.iterdir()] == [expected.name]
    body = expected.read_text(encoding="utf-8")
    assert TWEET_URL in body

    saved = json.loads(state.read_text(encoding="utf-8"))
    assert saved[HANDLE] == TWEET_ID
