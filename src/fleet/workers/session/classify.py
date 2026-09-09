"""Pure exit classification for a finished coder session.

Owns the context-overflow error patterns, :func:`error_text_of` /
:func:`is_context_error_text`, and the outcome table :func:`classify_exit`.
No subprocess, no I/O: the caller passes plain values and gets a
:class:`TaskOutcomeRecord`. Callers are ``workers/session/monitors.py``
(the error scanner) and ``workers/llm_session.py`` (final classification).
Tests import the error helpers from here.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass

from fleet.core.task import Event, EventKind, TaskOutcome, TaskOutcomeRecord

# Substrings (case-insensitive) of the CLIs' own "context is full" errors.
# When stderr or an event carries one, the session is over even if usage
# counters never crossed the kill threshold.
_CONTEXT_ERROR_PATTERNS = (
    "prompt is too long",
    "context length",
    "maximum context",
    "context window",
    "token limit",
    "too many tokens",
    "input is too long",
    "context too large",
    "exceeds the context",
    "exceed context",
)


def is_context_error_text(text: str) -> bool:
    """True when *text* looks like a CLI context-overflow error."""
    lowered = text.lower()
    return any(pat in lowered for pat in _CONTEXT_ERROR_PATTERNS)


def error_text_of(event: Event) -> str:
    """The error payload of *event*, or "" when the event carries no error.

    Only ``error`` events and the error fields of a ``session_ended`` event
    count. The model's own prose (``assistant_text``) is never scanned: a
    worker that *talks about* "context windows" is not overflowing one.
    """
    raw = event.raw if isinstance(event.raw, dict) else {}
    if event.kind == EventKind.ERROR:
        candidate = raw
    elif event.kind == EventKind.SESSION_ENDED:
        candidate = {k: raw[k] for k in ("error", "errors", "message") if raw.get(k)}
        if raw.get("is_error") and raw.get("result"):
            candidate["result"] = raw["result"]
    else:
        return ""
    if not candidate:
        return ""
    try:
        return json.dumps(candidate)[:8000]
    except (TypeError, ValueError):
        return ""


@dataclass(frozen=True)
class ExitInputs:
    """Plain values describing how a coder session ended; no handles."""

    exit_code: int | None
    verdict: TaskOutcomeRecord | None
    killed: bool
    kill_reason: str
    cancelled: bool
    stderr_tail: str | None


def _rule_verdict(inputs: ExitInputs) -> TaskOutcomeRecord | None:
    """A monitor already decided while the process was being killed."""
    return inputs.verdict


def _rule_killed(inputs: ExitInputs) -> TaskOutcomeRecord | None:
    """A manual or stall kill recorded by cancel()."""
    if not inputs.killed:
        return None
    return TaskOutcomeRecord(
        outcome=TaskOutcome.KILLED, exit_code=inputs.exit_code, reason=inputs.kill_reason
    )


def _rule_cancelled(inputs: ExitInputs) -> TaskOutcomeRecord | None:
    """A supervisor shutdown, re-queued at once without counting a round."""
    if not inputs.cancelled:
        return None
    return TaskOutcomeRecord(
        outcome=TaskOutcome.FAILURE,
        exit_code=inputs.exit_code,
        reason="supervisor_shutdown",
    )


def _rule_success(inputs: ExitInputs) -> TaskOutcomeRecord | None:
    """A clean exit with no kill and no monitor verdict."""
    if inputs.exit_code != 0:
        return None
    return TaskOutcomeRecord(outcome=TaskOutcome.SUCCESS, exit_code=inputs.exit_code, reason="")


def _rule_context_stderr(inputs: ExitInputs) -> TaskOutcomeRecord | None:
    """A failed exit whose stderr reports a CLI context overflow."""
    if inputs.stderr_tail is not None and is_context_error_text(inputs.stderr_tail):
        return TaskOutcomeRecord(
            outcome=TaskOutcome.CONTEXT_PRESSURE,
            exit_code=inputs.exit_code,
            reason="cli reported context overflow",
            stderr_tail=inputs.stderr_tail,
        )
    return None


def _rule_failure(inputs: ExitInputs) -> TaskOutcomeRecord | None:
    """Any other failed exit; always hits, so the table is total."""
    return TaskOutcomeRecord(
        outcome=TaskOutcome.FAILURE,
        exit_code=inputs.exit_code,
        reason=f"subprocess exited with rc={inputs.exit_code}",
        stderr_tail=inputs.stderr_tail,
    )


# First rule returning non-None wins; _rule_failure always hits.
_EXIT_RULES: tuple[Callable[[ExitInputs], TaskOutcomeRecord | None], ...] = (
    _rule_verdict,
    _rule_killed,
    _rule_cancelled,
    _rule_success,
    _rule_context_stderr,
    _rule_failure,
)


def classify_exit(
    exit_code: int | None,
    *,
    verdict: TaskOutcomeRecord | None = None,
    killed: bool = False,
    kill_reason: str = "manual_kill",
    cancelled: bool = False,
    stderr_tail: str | None = None,
) -> TaskOutcomeRecord:
    """Turn how the session ended into the outcome record for the reap loop."""
    inputs = ExitInputs(
        exit_code=exit_code,
        verdict=verdict,
        killed=killed,
        kill_reason=kill_reason,
        cancelled=cancelled,
        stderr_tail=stderr_tail,
    )
    for rule in _EXIT_RULES:
        record = rule(inputs)
        if record is not None:
            return record
    raise AssertionError("unreachable: _rule_failure always returns a record")
