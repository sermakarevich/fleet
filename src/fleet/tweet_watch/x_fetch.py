"""M2 x-fetch: fetch candidate tweets via the ``x`` CLI (scaffold)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Tweet:
    """One candidate tweet record parsed from ``x watch check`` output."""

    id: str
    handle: str
    text: str
    url: str
    created_at: str


class FetchError(Exception):
    """An ``x`` CLI failure for one handle (or the whole check stage).

    Must do: carry the failing handle (or stage) name in ``handle`` and the
    CLI's stderr tail in the message, so R2 can skip that handle without
    advancing its state while siblings continue.
    Serves: M2, needed by R2.
    Depends on: nothing (stdlib only).
    Depended on by: worker.find_new_tweets.
    """

    def __init__(self, handle: str, message: str) -> None:
        """SCAFFOLD (not implemented): store handle and message.

        Must do: set ``self.handle`` and pass ``message`` to ``Exception``.
        Serves: M2, needed by R2.
        Depends on: nothing (stdlib only).
        Depended on by: worker.find_new_tweets.
        """
        raise NotImplementedError


def fetch_tweets(
    handles: Sequence[str],
    run_command: Callable[[tuple[str, ...]], str] | None = None,
    command_timeout: float = 60.0,
) -> list[Tweet]:
    """SCAFFOLD (not implemented): fetch candidate tweets for each handle.

    Must do: run ``x watch add user:<handle>`` once per handle (idempotent),
    then ``x watch check --format json``; parse stdout JSON into ``Tweet``
    records (records missing ``id`` are skipped, records missing only
    optional fields get ``""`` defaults); empty handle list invokes nothing
    and returns ``[]``; non-zero exit or unparseable stdout raises
    ``FetchError`` naming the handle (or the check stage) and never
    fabricates tweets; matching of records to handles is case-insensitive;
    records for unrequested handles are dropped; ``run_command`` is the
    injection seam (argv tuple in, stdout out) defaulting to ``subprocess``;
    every CLI call is killed after ``command_timeout`` seconds.
    Serves: M2, needed by R2.
    Depends on: the ``x`` CLI on PATH.
    Depended on by: worker.find_new_tweets.
    """
    raise NotImplementedError
