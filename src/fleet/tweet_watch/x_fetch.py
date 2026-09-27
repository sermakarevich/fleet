"""Candidate-tweet fetching for tweet_watch via the ``x`` CLI.

Called by ``worker.find_new_tweets``. Each handle is registered with
``x watch add user:<handle>`` first, then one ``x watch check`` returns
the candidate records, filtered down to handles on the watchlist.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass

logger = logging.getLogger(__name__)

CHECK_ARGV: tuple[str, ...] = ("x", "watch", "check", "--format", "json")

# Bytes of stderr kept on the failure detail line.
_STDERR_TAIL_LIMIT = 2000


@dataclass(frozen=True, slots=True)
class Tweet:
    """One candidate tweet record parsed from ``x watch check`` output."""

    id: str
    handle: str
    text: str
    url: str
    created_at: str


class FetchError(Exception):
    """An ``x`` CLI failure for one handle (or the whole check stage)."""

    def __init__(self, handle: str, message: str) -> None:
        self.handle = handle
        super().__init__(message)


def _stderr_tail(exc: subprocess.CalledProcessError) -> str:
    stderr = exc.stderr
    if isinstance(stderr, bytes):
        stderr = stderr.decode("utf-8", "replace")
    if stderr is None:
        return ""
    tail = str(stderr).strip()
    if len(tail) > _STDERR_TAIL_LIMIT:
        tail = tail[-_STDERR_TAIL_LIMIT:]
    return tail


def _child_env() -> dict[str, str]:
    env = dict(os.environ)
    parts = env.get("PATH", "").split(os.pathsep)
    for default in os.defpath.split(os.pathsep):
        if default and default not in parts:
            parts.append(default)
    env["PATH"] = os.pathsep.join(parts)
    return env


def _default_runner(argv: tuple[str, ...], timeout: float) -> str:
    try:
        proc = subprocess.run(
            list(argv),
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout,
            env=_child_env(),
        )
    except FileNotFoundError as exc:
        raise FetchError("x", f"x: command not found: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise FetchError("check", f"check: timed out after {timeout}s: {' '.join(argv)}") from exc
    except OSError as exc:
        raise FetchError("x", f"x: cannot run {' '.join(argv)}: {exc}") from exc
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(
            proc.returncode, list(argv), output=proc.stdout, stderr=proc.stderr
        )
    return proc.stdout


def _optional_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def fetch_tweets(
    handles: Sequence[str],
    run_command: Callable[[tuple[str, ...]], str] | None = None,
    command_timeout: float = 60.0,
) -> list[Tweet]:
    """Fetch candidate tweets for the handles via the x CLI, watchlist order kept."""
    wanted = list(handles)
    if not wanted:
        return []

    def invoke(argv: tuple[str, ...]) -> str:
        if run_command is not None:
            return run_command(tuple(argv))
        return _default_runner(tuple(argv), command_timeout)

    _register_handles(wanted, invoke, command_timeout)
    stdout = _run_check(invoke, command_timeout)
    data = _parse_check_output(stdout)
    return _select_wanted(data, wanted)


def _register_handles(
    wanted: Sequence[str],
    invoke: Callable[[tuple[str, ...]], str],
    command_timeout: float,
) -> None:
    """Register each handle with ``x watch add``; a per-handle failure names it."""
    for handle in wanted:
        argv = ("x", "watch", "add", f"user:{handle}")
        try:
            invoke(argv)
        except FetchError:
            raise
        except FileNotFoundError as exc:
            raise FetchError("x", f"x: command not found: {exc}") from exc
        except subprocess.TimeoutExpired as exc:
            raise FetchError(
                handle, f"{handle}: x watch add timed out after {command_timeout}s"
            ) from exc
        except subprocess.CalledProcessError as exc:
            tail = _stderr_tail(exc)
            detail = f": {tail}" if tail else f" (exit {exc.returncode})"
            raise FetchError(handle, f"{handle}: x watch add failed{detail}") from exc
        except OSError as exc:
            raise FetchError("x", f"x: cannot run x watch add for {handle}: {exc}") from exc


def _run_check(invoke: Callable[[tuple[str, ...]], str], command_timeout: float) -> str:
    """Run the single ``x watch check`` stage and return its stdout."""
    try:
        return invoke(CHECK_ARGV)
    except FetchError:
        raise
    except FileNotFoundError as exc:
        raise FetchError("x", f"x: command not found: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise FetchError(
            "check", f"check: timed out after {command_timeout}s: x watch check"
        ) from exc
    except subprocess.CalledProcessError as exc:
        tail = _stderr_tail(exc)
        detail = f": {tail}" if tail else f" (exit {exc.returncode})"
        raise FetchError("check", f"check: x watch check failed{detail}") from exc
    except OSError as exc:
        raise FetchError("check", f"check: cannot run x watch check: {exc}") from exc


def _parse_check_output(stdout: str) -> list[dict[str, object]]:
    """Parse check stdout as a JSON list of objects, or raise FetchError."""
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise FetchError("check", f"check: invalid JSON from x watch check: {exc}") from exc
    if not isinstance(data, list):
        raise FetchError(
            "check",
            f"check: expected JSON list from x watch check, got {type(data).__name__}",
        )
    for item in data:
        if not isinstance(item, dict):
            raise FetchError(
                "check",
                "check: expected JSON list of objects from x watch check, "
                f"got {type(item).__name__} item",
            )
    return data


def _select_wanted(data: Sequence[dict[str, object]], wanted: Sequence[str]) -> list[Tweet]:
    """Keep records owned by the watchlist, in check order, skipping id-less rows."""
    canonical = {h.lower(): h for h in wanted}
    tweets: list[Tweet] = []
    for item in data:
        tweet = _parse_record(item, canonical)
        if tweet is not None:
            tweets.append(tweet)
    return tweets


def _parse_record(item: dict[str, object], canonical: dict[str, str]) -> Tweet | None:
    raw_id = item.get("id")
    if raw_id is None or isinstance(raw_id, bool):
        logger.warning("x watch check: record missing id, skipping: %r", item)
        return None
    if isinstance(raw_id, str):
        if not raw_id:
            return None
        tweet_id = raw_id
    elif isinstance(raw_id, (int, float)):
        tweet_id = str(raw_id)
    else:
        return None
    raw_handle = item.get("handle")
    if not isinstance(raw_handle, str) or not raw_handle:
        return None
    owner = canonical.get(raw_handle.lower())
    if owner is None:
        return None
    return Tweet(
        id=tweet_id,
        handle=owner,
        text=_optional_text(item.get("text", "")),
        url=_optional_text(item.get("url", "")),
        created_at=_optional_text(item.get("created_at", "")),
    )
