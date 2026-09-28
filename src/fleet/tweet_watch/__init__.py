"""Recurring X/Twitter watch worker: watchlist, fetch, score, propose, persist.

Called by the ``tweet-watch`` schedule every 30 minutes. Every run reads
the watchlist, fetches new tweets via the ``x`` CLI, scores them against
INTERESTS.md, proposes HIGH-only drafts through ``ask_human``, and persists
confirmed replies. See ``docs/tweet_watch/REQUIREMENTS.md``.
"""

from __future__ import annotations

from fleet.tweet_watch.kb_files import SEED_HANDLES, load_state, read_watchlist, save_state
from fleet.tweet_watch.reply_files import list_recent, read_reply_text, write_reply
from fleet.tweet_watch.worker import (
    INTERESTS_PATH,
    REPLIES_DIR,
    STATE_PATH,
    WATCHLIST_PATH,
    compose_draft,
    ensure_watchlist,
    find_new_tweets,
    is_duplicate,
    parse_confirmation,
    persist_reply,
    propose_tweet,
    run,
    score_tweet,
)
from fleet.tweet_watch.x_fetch import FetchError, Tweet, fetch_tweets

__all__ = [
    "FetchError",
    "INTERESTS_PATH",
    "REPLIES_DIR",
    "SEED_HANDLES",
    "STATE_PATH",
    "WATCHLIST_PATH",
    "Tweet",
    "compose_draft",
    "ensure_watchlist",
    "fetch_tweets",
    "find_new_tweets",
    "is_duplicate",
    "list_recent",
    "load_state",
    "parse_confirmation",
    "persist_reply",
    "propose_tweet",
    "read_reply_text",
    "read_watchlist",
    "run",
    "save_state",
    "score_tweet",
    "write_reply",
]
