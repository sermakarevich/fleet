"""Candidate-tweet fetching for tweet_watch via the ``x`` CLI.

Called by ``worker.find_new_tweets``. Each handle is registered with
``x watch add user:<handle>`` first, then one ``x watch check`` returns
the candidate records, filtered down to handles on the watchlist.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass

CHECK_ARGV: tuple[str, ...] = ("x", "watch", "check", "--format", "json")


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
    if len(tail) > 2000:
        tail = tail[-2000:]
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
            text=True,
            timeout=timeout,
            env=_child_env(),
        )
    except FileNotFoundError as exc:
        raise FetchError("x", f"x: command not found: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise FetchError(
            "check", f"check: timed out after {timeout}s: {' '.join(argv)}"
        ) from exc
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

    try:
        stdout = invoke(CHECK_ARGV)
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

    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise FetchError(
            "check", f"check: invalid JSON from x watch check: {exc}"
        ) from exc
    if not isinstance(data, list):
        raise FetchError(
            "check",
            f"check: expected JSON list from x watch check, "
            f"got {type(data).__name__}",
        )
    for item in data:
        if not isinstance(item, dict):
            raise FetchError(
                "check",
                "check: expected JSON list of objects from x watch check, "
                f"got {type(item).__name__} item",
            )

    canonical = {h.lower(): h for h in wanted}
    tweets: list[Tweet] = []
    for item in data:
        raw_id = item.get("id")
        if raw_id is None or isinstance(raw_id, bool):
            continue
        if isinstance(raw_id, str):
            if not raw_id:
                continue
            tweet_id = raw_id
        elif isinstance(raw_id, (int, float)):
            tweet_id = str(raw_id)
        else:
            continue
        raw_handle = item.get("handle")
        if not isinstance(raw_handle, str) or not raw_handle:
            continue
        owner = canonical.get(raw_handle.lower())
        if owner is None:
            continue
        tweets.append(
            Tweet(
                id=tweet_id,
                handle=owner,
                text=_optional_text(item.get("text", "")),
                url=_optional_text(item.get("url", "")),
                created_at=_optional_text(item.get("created_at", "")),
            )
        )
    return tweets
