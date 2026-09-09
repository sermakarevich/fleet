"""Deterministic launch-mode policy: fresh vs. continue, and the continue pack.

No LLM call, no I/O — this module only decides, from attempt history and an
`ArtifactSnapshot` already read by the caller, whether an attempt starts
fresh or continues, and (when continuing) builds the bounded text "pack"
handed to the coder as its only continuation context. A later compaction
job acts on ``LaunchPlan.needs_compaction``; this module only records it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class LaunchLimits:
    continue_pack_max_bytes: int = 8192
    state_max_bytes: int = 6144


@dataclass(frozen=True, slots=True)
class ArtifactSnapshot:
    state_text: str
    state_is_stub: bool
    latest_result: dict | None  # parsed previous attempt RESULT.json, or None
    latest_result_is_missing: bool  # True if the previous attempt has no RESULT.json at all


@dataclass(frozen=True, slots=True)
class LaunchPlan:
    mode: Literal["fresh", "continue", "validate"]
    pack: str
    pack_bytes: int
    needs_compaction: bool


def _truncate(text: str, max_bytes: int) -> str:
    """Keep the first *max_bytes* bytes of *text*, decoded leniently.

    Deterministic and byte-safe: slicing raw utf-8 bytes can land mid
    character, so trailing partial bytes are dropped via errors="ignore".
    """
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    return encoded[:max_bytes].decode("utf-8", errors="ignore")


def _result_lines(result: dict) -> list[str]:
    """The Previous-RESULT.json lines the pack carries: summary, next steps, questions, tests."""
    lines = [f"summary: {result.get('summary') or ''}"]
    lines.append(f"next_step: {result.get('next_step') or ''}")
    open_questions = result.get("open_questions") or []
    if open_questions:
        lines.append("open_questions:")
        lines.extend(f"- {q}" for q in open_questions)
    tests = result.get("tests")
    if tests is not None:
        lines.append(f"tests: {tests}")
    return lines


def plan_launch(
    attempts: list[dict], artifacts: ArtifactSnapshot, limits: LaunchLimits
) -> LaunchPlan:
    """Decide fresh vs. continue for the next attempt, and build the pack.

    *attempts* is this task's attempt history strictly before the attempt
    being planned (oldest first). Fresh only when there is no history AND
    STATE.md is still its seeded stub; otherwise continue. The pack is
    STATE.md plus the previous RESULT.json (summary, next_step,
    open_questions, tests).
    """
    if not attempts and artifacts.state_is_stub:
        return LaunchPlan(mode="fresh", pack="", pack_bytes=0, needs_compaction=False)

    if attempts:
        prev = attempts[-1]
        prev_outcome = prev.get("outcome") or "unknown"
        prev_reason = prev.get("reason") or "unknown"
    else:
        prev_outcome = "unknown"
        prev_reason = "unknown"

    sections: list[str] = [
        f"Attempt {len(attempts) + 1} of this task. "
        f"Previous attempt ended: {prev_outcome}: {prev_reason}."
    ]

    state = _truncate(artifacts.state_text, limits.state_max_bytes)
    sections.append("## STATE.md\n" + state)

    if artifacts.latest_result is not None:
        sections.append(
            "## Previous RESULT.json\n" + "\n".join(_result_lines(artifacts.latest_result))
        )

    pack = "\n\n".join(sections)
    pack_bytes = len(pack.encode("utf-8"))

    needs_compaction = (
        pack_bytes > limits.continue_pack_max_bytes
        or len(artifacts.state_text.encode("utf-8")) > limits.state_max_bytes
    )

    return LaunchPlan(
        mode="continue",
        pack=pack,
        pack_bytes=pack_bytes,
        needs_compaction=needs_compaction,
    )
