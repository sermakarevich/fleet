"""Shared fixtures for R9 schedule-install-and-verify tests.

Unit under test: the installed ``tweet-watch`` schedule firing one R1-R6
pass (``fleet.tweet_watch.worker.run``) every 30 minutes. Real objects
only: ``worker.run``, the KB path constants, ``SEED_HANDLES``, ``Tweet``,
and the real fleet schedule machinery (``Schedule``, ``OverlapPolicy``,
``ScheduleStore``, ``cron.parse``). The M2 fetch dependency is canned via
monkeypatch (a different unit, not the unit under test); the R9 unit
itself is never stubbed.

Contract the implementation must honor (used by every run-based test):
``run()`` reads KB locations from the module-level ``WATCHLIST_PATH``,
``STATE_PATH``, ``INTERESTS_PATH`` and ``REPLIES_DIR`` constants, reaches
M2 through ``x_fetch.fetch_tweets``, and uses the documented seams
(``ask``/``today``/``interests_text``/``recent_texts``).
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any

import pytest

from fleet.schedules.model import OverlapPolicy, Schedule
from fleet.schedules.store import ScheduleStore
from fleet.tweet_watch import worker
from fleet.tweet_watch import x_fetch as x_fetch_module
from fleet.tweet_watch.x_fetch import Tweet

SCHEDULE_NAME = "tweet-watch"
SCHEDULE_CRON = "*/30 * * * *"
SCHEDULE_OVERLAP = OverlapPolicy.skip
SCHEDULE_CODER = "opencode"
REPO_ROOT = "/Users/sergii/git/fleet"
EXPECTED_CREATE = (
    "fleet schedule create --name tweet-watch --cron '*/30 * * * *' --overlap skip --coder opencode"
)

TODAY = date(2026, 9, 26)

INTERESTS_CORE = (
    "# Interests\n\nCore topics: agent harnesses, coding agents, "
    "verifier models, voice agents, cost engineering.\n\n"
    "Voice: plain language, no hype words, one concrete observation "
    "or number first, teaching tone, abbreviations explained on first use.\n"
)

HIGH_TEXT = (
    "We cut eval cost 10x with a verifier model gating releases: "
    "a separate checker model reviews the coding agent output."
)
LOW_TEXT = "Price talk: this token is going to the moon, giveaway below, meme."


def make_tweet(
    tweet_id: str = "300",
    handle: str = "typesafeai",
    text: str = HIGH_TEXT,
) -> Tweet:
    """One canned candidate tweet record."""
    return Tweet(
        id=tweet_id,
        handle=handle,
        text=text,
        url=f"https://x.com/{handle}/status/{tweet_id}",
        created_at="2026-09-26T10:00:00Z",
    )


class AskLog:
    """Recording ``ask_human`` stand-in: records, then answers or raises."""

    def __init__(
        self,
        answers: list[str] | tuple[str, ...] = (),
        error: BaseException | None = None,
    ) -> None:
        self.messages: list[str] = []
        self._answers = list(answers)
        self._error = error

    def __call__(self, message: str) -> str:
        self.messages.append(message)
        if self._error is not None:
            raise self._error
        if self._answers:
            return self._answers.pop(0)
        return "skip"


@pytest.fixture
def fleet_home(tmp_path):
    home = tmp_path / "fleet-home"
    home.mkdir()
    return home


@pytest.fixture
def store(fleet_home) -> ScheduleStore:
    return ScheduleStore(fleet_home)


@pytest.fixture
def make_schedule():
    def _make(schedule_id: str = "sch-test-1", **overrides: Any) -> Schedule:
        fields: dict[str, Any] = {
            "id": schedule_id,
            "name": SCHEDULE_NAME,
            "cron": SCHEDULE_CRON,
            "title": "tweet watch",
            "description": "R1-R6 pass",
            "cwd": REPO_ROOT,
            "coder": SCHEDULE_CODER,
            "overlap": SCHEDULE_OVERLAP,
        }
        fields.update(overrides)
        return Schedule(**fields)

    return _make


@pytest.fixture
def kb(tmp_path, monkeypatch) -> SimpleNamespace:
    """Redirect the worker's KB constants at a throwaway tree."""
    media = tmp_path / "kb" / "media"
    x_dir = media / "x"
    x_dir.mkdir(parents=True)
    watchlist = x_dir / "watchlist.md"
    state = x_dir / "watch_state.json"
    replies = x_dir / "replies"
    replies.mkdir()
    interests = media / "INTERESTS.md"
    monkeypatch.setattr(worker, "WATCHLIST_PATH", watchlist)
    monkeypatch.setattr(worker, "STATE_PATH", state)
    monkeypatch.setattr(worker, "INTERESTS_PATH", interests)
    monkeypatch.setattr(worker, "REPLIES_DIR", replies)
    return SimpleNamespace(
        root=x_dir,
        watchlist=watchlist,
        state=state,
        replies=replies,
        interests=interests,
    )


def write_watchlist(kb: SimpleNamespace, handles: list[str]) -> None:
    kb.watchlist.write_text("".join(h + "\n" for h in handles), encoding="utf-8")


def write_interests(kb: SimpleNamespace, text: str = INTERESTS_CORE) -> None:
    kb.interests.write_text(text, encoding="utf-8")


def canned_fetch(monkeypatch, tweets=None, exc=None, seen=None) -> None:
    """Route the M2 dependency through canned data (not the R9 unit)."""

    def _fetch(*args: Any, **kwargs: Any) -> list[Tweet]:
        if seen is not None:
            seen.append((args, kwargs))
        if exc is not None:
            raise exc
        return list(tweets or [])

    monkeypatch.setattr(x_fetch_module, "fetch_tweets", _fetch)
    if hasattr(worker, "fetch_tweets"):
        monkeypatch.setattr(worker, "fetch_tweets", _fetch)


def run_or_fail_scaffold(**kwargs: Any) -> Any:
    """Call ``worker.run``; a scaffold NotImplementedError fails the test.

    Use when the run may legitimately return without raising: on the
    scaffold the test goes red, once implemented the caller asserts the
    real behavior below.
    """
    try:
        return worker.run(**kwargs)
    except NotImplementedError:
        pytest.fail("scaffold: worker.run not implemented")
