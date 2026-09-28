"""R5 (HIGH-only human proposal) shared fixtures and contract helpers.

Unit under test: fleet.tweet_watch.worker.compose_draft (draft half) and
fleet.tweet_watch.worker.propose_tweet (proposal gate). Batch/count
semantics go through worker.run with monkeypatched dependencies.
"""

from __future__ import annotations

import re
from datetime import date

import pytest

from fleet.tweet_watch.x_fetch import Tweet

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

HYPE_WORDS = (
    "game-changer",
    "game changer",
    "revolutionary",
    "insane alpha",
    "mind-blowing",
    "mind blowing",
)

PRAISE_OPENERS = {
    "great",
    "nice",
    "awesome",
    "love",
    "thanks",
    "thank",
    "interesting",
    "fascinating",
    "true",
    "agree",
    "exactly",
    "wow",
    "cool",
}

# All-caps tokens that are plain vocabulary, not abbreviations needing expansion.
PLAIN_CAPS = {"AI", "X", "ML", "LLM", "API", "KV", "STT", "TTS", "CPU", "GPU", "OS"}

ABBREV_RE = re.compile(r"\b([A-Z]{2,})s?\b")
X_POST_LIMIT = 280
TODAY = date(2026, 9, 26)


@pytest.fixture
def interests_text() -> str:
    return INTERESTS_TEXT


def make_tweet(
    id: str = "1968123456789012345",
    handle: str = "omarsar0",
    text: str = (
        "Shipped a fleet of headless coding-agent worker loops draining a "
        "central beads queue with a supervisor retrying failed tasks. "
        "Pipelined speech-to-text cut turn-taking to 120ms on our calls."
    ),
    url: str = "https://x.com/omarsar0/status/1968123456789012345",
    created_at: str = "2026-09-26T10:00:00Z",
) -> Tweet:
    return Tweet(id=id, handle=handle, text=text, url=url, created_at=created_at)


GOOD_DRAFT = (
    "120ms turn-taking is the number to beat: pipelined speech-to-text "
    "(converting speech to text in stages) plus text-to-speech streaming "
    "keeps each stage measurable, so profile speech-to-text, turn-taking, "
    "and text-to-speech separately before switching pipelines."
)


class AskRecorder:
    """Fake `ask` seam: records prompts, replays scripted answers."""

    def __init__(self, answers: list[str] | None = None) -> None:
        self.prompts: list[str] = []
        self._answers = list(answers) if answers else ["skip"]
        self.fail_on: set[int] = set()

    def __call__(self, prompt: str) -> str:
        index = len(self.prompts)
        self.prompts.append(prompt)
        if index in self.fail_on:
            raise RuntimeError("ask_human tool unreachable (simulated)")
        if index < len(self._answers):
            return self._answers[index]
        return self._answers[-1]


def normalize(text: str) -> str:
    folded = text.casefold()
    folded = re.sub(r"\s+", " ", folded).strip()
    return re.sub(r"[^\w ]", "", folded)


def is_praise_only(draft: str) -> bool:
    words = re.findall(r"[A-Za-z']+", draft)
    if not words:
        return True
    if len(words) > 12:
        return False
    content = {w.casefold() for w in words}
    praise = {
        "great",
        "point",
        "points",
        "nice",
        "awesome",
        "love",
        "loved",
        "thanks",
        "thank",
        "true",
        "agree",
        "agreed",
        "exactly",
        "wow",
        "cool",
        "interesting",
        "fascinating",
        "post",
        "take",
        "this",
        "that",
        "it",
        "is",
        "so",
        "very",
        "much",
        "such",
        "a",
        "an",
        "the",
        "well",
        "said",
        "yes",
    }
    return content <= praise


def unexplained_abbreviations(draft: str) -> list[str]:
    """All-caps tokens with no `(expansion)` right after them."""
    bad: list[str] = []
    for match in ABBREV_RE.finditer(draft):
        token = match.group(1)
        if token in PLAIN_CAPS:
            continue
        rest = draft[match.end() :]
        if not re.match(r"\s*\([^)]{3,80}\)", rest):
            bad.append(token)
    return bad


def first_sentence(draft: str) -> str:
    parts = re.split(r"[.!?]+\s+", draft.strip())
    return parts[0] if parts else ""
