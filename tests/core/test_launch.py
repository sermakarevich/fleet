"""Tests for `core.launch.plan_launch`: fresh vs. continue, pack assembly,
and the deterministic truncation fallback when needs_compaction is true.

Pure unit tests: no I/O, no task directory — `ArtifactSnapshot` is built
by hand for each case.
"""

from __future__ import annotations

from fleet.core.launch import ArtifactSnapshot, LaunchLimits, LaunchPlan, plan_launch


def _stub_snapshot(**overrides) -> ArtifactSnapshot:
    defaults = dict(
        handoff_text="",
        handoff_is_stub=True,
        knowledge_text="",
        knowledge_is_stub=True,
        plan_text="",
        plan_is_stub=True,
        latest_summary_text=None,
        latest_result=None,
        latest_result_is_missing=False,
    )
    defaults.update(overrides)
    return ArtifactSnapshot(**defaults)


def test_no_prior_attempts_and_stub_artifacts_is_fresh() -> None:
    plan = plan_launch([], _stub_snapshot(), LaunchLimits())
    assert plan.mode == "fresh"
    assert plan.pack == ""
    assert plan.pack_bytes == 0
    assert plan.needs_compaction is False


def test_prior_attempts_forces_continue_even_if_stub() -> None:
    attempts = [{"n": 1, "outcome": "failure", "reason": "crash"}]
    plan = plan_launch(attempts, _stub_snapshot(), LaunchLimits())
    assert plan.mode == "continue"


def test_non_stub_artifacts_forces_continue_even_without_attempts() -> None:
    snap = _stub_snapshot(handoff_text="Done: wrote X", handoff_is_stub=False)
    plan = plan_launch([], snap, LaunchLimits())
    assert plan.mode == "continue"


def test_continue_pack_includes_labelled_sections() -> None:
    attempts = [{"n": 1, "outcome": "partial", "reason": "next_step: keep going"}]
    snap = _stub_snapshot(
        handoff_text="Done: A\nNext: B",
        handoff_is_stub=False,
        knowledge_text="Some durable fact.",
        knowledge_is_stub=False,
        latest_summary_text="# Attempt 1 summary\n...",
        latest_result={
            "next_step": "keep going",
            "open_questions": ["is X safe?"],
        },
        latest_result_is_missing=False,
    )
    plan = plan_launch(attempts, snap, LaunchLimits())
    assert plan.mode == "continue"
    assert "Attempt 2 of this task" in plan.pack
    assert "partial: next_step: keep going" in plan.pack
    assert "Previous HANDOFF.md" in plan.pack
    assert "Done: A" in plan.pack
    assert "next_step: keep going" in plan.pack
    assert "is X safe?" in plan.pack
    assert "Latest attempt summary" in plan.pack
    assert "Attempt 1 summary" in plan.pack
    assert "KNOWLEDGE.md" in plan.pack
    assert "Some durable fact." in plan.pack
    assert plan.pack_bytes == len(plan.pack.encode("utf-8"))


def test_needs_compaction_when_pack_too_big() -> None:
    attempts = [{"n": 1, "outcome": "partial", "reason": "r"}]
    snap = _stub_snapshot(
        handoff_text="x" * 1000,
        handoff_is_stub=False,
        knowledge_text="y" * 1000,
        knowledge_is_stub=False,
        latest_result={"next_step": "n"},
        latest_result_is_missing=False,
    )
    limits = LaunchLimits(
        continue_pack_max_bytes=100, handoff_max_bytes=2048, knowledge_max_bytes=4096
    )
    plan = plan_launch(attempts, snap, limits)
    assert plan.needs_compaction is True
    # Deterministic truncation fallback: sections are capped, not dropped.
    assert plan.pack_bytes > 0


def test_needs_compaction_when_knowledge_too_big() -> None:
    attempts = [{"n": 1, "outcome": "partial", "reason": "r"}]
    snap = _stub_snapshot(
        handoff_text="handoff",
        handoff_is_stub=False,
        knowledge_text="k" * 5000,
        knowledge_is_stub=False,
        latest_result={"next_step": "n"},
        latest_result_is_missing=False,
    )
    limits = LaunchLimits(
        continue_pack_max_bytes=1_000_000, handoff_max_bytes=2048, knowledge_max_bytes=4096
    )
    plan = plan_launch(attempts, snap, limits)
    assert plan.needs_compaction is True


def test_handoff_and_knowledge_truncated_to_limits() -> None:
    attempts = [{"n": 1, "outcome": "partial", "reason": "r"}]
    snap = _stub_snapshot(
        handoff_text="h" * 5000,
        handoff_is_stub=False,
        knowledge_text="k" * 5000,
        knowledge_is_stub=False,
        latest_result={"next_step": "n"},
        latest_result_is_missing=False,
    )
    limits = LaunchLimits(
        continue_pack_max_bytes=1_000_000, handoff_max_bytes=50, knowledge_max_bytes=60
    )
    plan = plan_launch(attempts, snap, limits)
    # Each section is truncated to its own cap regardless of the overall pack limit.
    handoff_section = plan.pack.split("## Previous HANDOFF.md\n", 1)[1].split("\n\n##", 1)[0]
    assert len(handoff_section.encode("utf-8")) <= 50
    knowledge_section = plan.pack.split("## KNOWLEDGE.md\n", 1)[1]
    assert len(knowledge_section.encode("utf-8")) <= 60


def test_needs_compaction_when_previous_result_missing() -> None:
    attempts = [{"n": 1, "outcome": "failure", "reason": "crash"}]
    snap = _stub_snapshot(
        handoff_text="handoff",
        handoff_is_stub=False,
        latest_result=None,
        latest_result_is_missing=True,
    )
    plan = plan_launch(attempts, snap, LaunchLimits())
    assert plan.needs_compaction is True


def test_needs_compaction_when_previous_handoff_still_stub() -> None:
    """The previous attempt died without handing off: HANDOFF.md is still the stub."""
    attempts = [{"n": 1, "outcome": "failure", "reason": "crash"}]
    snap = _stub_snapshot(handoff_is_stub=True, latest_result={"next_step": ""})
    plan = plan_launch(attempts, snap, LaunchLimits())
    assert plan.needs_compaction is True


def test_no_needs_compaction_for_healthy_continue() -> None:
    attempts = [{"n": 1, "outcome": "partial", "reason": "next_step: go"}]
    snap = _stub_snapshot(
        handoff_text="Done: A",
        handoff_is_stub=False,
        knowledge_text="fact",
        knowledge_is_stub=False,
        latest_result={"next_step": "go"},
        latest_result_is_missing=False,
    )
    plan = plan_launch(attempts, snap, LaunchLimits())
    assert plan.needs_compaction is False


def test_launch_plan_is_a_dataclass_with_expected_fields() -> None:
    plan = LaunchPlan(mode="fresh", pack="", pack_bytes=0, needs_compaction=False)
    assert plan.mode == "fresh"
    assert plan.pack == ""
    assert plan.pack_bytes == 0
    assert plan.needs_compaction is False
