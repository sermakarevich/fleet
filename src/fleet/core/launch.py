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


@dataclass
class LaunchLimits:
    continue_pack_max_bytes: int = 8192
    handoff_max_bytes: int = 2048
    knowledge_max_bytes: int = 4096


@dataclass
class ArtifactSnapshot:
    handoff_text: str
    handoff_is_stub: bool
    knowledge_text: str
    knowledge_is_stub: bool
    plan_text: str
    plan_is_stub: bool
    latest_summary_text: str | None  # latest attempt SUMMARY.md, or None
    latest_result: dict | None  # parsed latest attempt RESULT.json, or None
    latest_result_is_missing: bool  # True if the previous attempt has no RESULT.json at all


@dataclass
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


def plan_launch(
    attempts: list[dict], artifacts: ArtifactSnapshot, limits: LaunchLimits
) -> LaunchPlan:
    """Decide fresh vs. continue for the next attempt, and build the pack.

    *attempts* is this task's attempt history strictly before the attempt
    being planned (oldest first). Fresh only when there is no history AND
    every artifact is still its seeded stub; otherwise continue.
    """
    all_stubs = (
        artifacts.handoff_is_stub and artifacts.knowledge_is_stub and artifacts.plan_is_stub
    )
    if not attempts and all_stubs:
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

    handoff = _truncate(artifacts.handoff_text, limits.handoff_max_bytes)
    sections.append("## Previous HANDOFF.md\n" + handoff)

    if artifacts.latest_result is not None:
        next_step = artifacts.latest_result.get("next_step") or ""
        open_questions = artifacts.latest_result.get("open_questions") or []
        lines = [f"next_step: {next_step}"]
        if open_questions:
            lines.append("open_questions:")
            lines.extend(f"- {q}" for q in open_questions)
        sections.append("## Previous next_step / open_questions\n" + "\n".join(lines))

    if artifacts.latest_summary_text is not None:
        sections.append(
            "## Latest attempt summary (SUMMARY.md)\n" + artifacts.latest_summary_text
        )

    knowledge = _truncate(artifacts.knowledge_text, limits.knowledge_max_bytes)
    sections.append("## KNOWLEDGE.md\n" + knowledge)

    pack = "\n\n".join(sections)
    pack_bytes = len(pack.encode("utf-8"))

    needs_compaction = (
        pack_bytes > limits.continue_pack_max_bytes
        or len(artifacts.knowledge_text.encode("utf-8")) > limits.knowledge_max_bytes
        or artifacts.latest_result_is_missing
        or (bool(attempts) and artifacts.handoff_is_stub)
    )

    return LaunchPlan(
        mode="continue",
        pack=pack,
        pack_bytes=pack_bytes,
        needs_compaction=needs_compaction,
    )
