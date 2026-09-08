"""Tests for `core.launch.plan_launch`: fresh vs. continue, pack assembly,
and the deterministic truncation fallback when needs_compaction is true.

Pure unit tests: no I/O, no task directory — `ArtifactSnapshot` is built
by hand for each case.
"""

from __future__ import annotations

from fleet.core.launch import ArtifactSnapshot, LaunchLimits, LaunchPlan, plan_launch


def _stub_snapshot(**overrides) -> ArtifactSnapshot:
    defaults = {
        "state_text": "",
        "state_is_stub": True,
        "latest_result": None,
        "latest_result_is_missing": False,
    }
    defaults.update(overrides)
    return ArtifactSnapshot(**defaults)


def test_no_prior_attempts_and_stub_state_is_fresh() -> None:
    plan = plan_launch([], _stub_snapshot(), LaunchLimits())
    assert plan.mode == "fresh"
    assert plan.pack == ""
    assert plan.pack_bytes == 0
    assert plan.needs_compaction is False


def test_prior_attempts_forces_continue_even_if_stub() -> None:
    attempts = [{"n": 1, "outcome": "failure", "reason": "crash"}]
    plan = plan_launch(attempts, _stub_snapshot(), LaunchLimits())
    assert plan.mode == "continue"


def test_non_stub_state_forces_continue_even_without_attempts() -> None:
    snap = _stub_snapshot(state_text="## Done\n- wrote X", state_is_stub=False)
    plan = plan_launch([], snap, LaunchLimits())
    assert plan.mode == "continue"


def test_continue_pack_includes_state_and_result() -> None:
    attempts = [{"n": 1, "outcome": "partial", "reason": "next_step: keep going"}]
    snap = _stub_snapshot(
        state_text="## Done\n- A\n\n## Next\n- B",
        state_is_stub=False,
        latest_result={
            "summary": "did some",
            "next_step": "keep going",
            "open_questions": ["is X safe?"],
            "tests": {"command": "pytest", "passed": True},
        },
        latest_result_is_missing=False,
    )
    plan = plan_launch(attempts, snap, LaunchLimits())
    assert plan.mode == "continue"
    assert "Attempt 2 of this task" in plan.pack
    assert "partial: next_step: keep going" in plan.pack
    assert "## STATE.md" in plan.pack
    assert "- A" in plan.pack
    assert "## Previous RESULT.json" in plan.pack
    assert "summary: did some" in plan.pack
    assert "next_step: keep going" in plan.pack
    assert "is X safe?" in plan.pack
    assert "pytest" in plan.pack
    assert plan.pack_bytes == len(plan.pack.encode("utf-8"))


def test_needs_compaction_when_pack_too_big() -> None:
    attempts = [{"n": 1, "outcome": "partial", "reason": "r"}]
    snap = _stub_snapshot(
        state_text="x" * 1000,
        state_is_stub=False,
        latest_result={"next_step": "n"},
        latest_result_is_missing=False,
    )
    limits = LaunchLimits(continue_pack_max_bytes=100, state_max_bytes=6144)
    plan = plan_launch(attempts, snap, limits)
    assert plan.needs_compaction is True
    # Deterministic truncation fallback: sections are capped, not dropped.
    assert plan.pack_bytes > 0


def test_needs_compaction_when_state_too_big() -> None:
    attempts = [{"n": 1, "outcome": "partial", "reason": "r"}]
    snap = _stub_snapshot(
        state_text="s" * 5000,
        state_is_stub=False,
        latest_result={"next_step": "n"},
        latest_result_is_missing=False,
    )
    limits = LaunchLimits(continue_pack_max_bytes=1_000_000, state_max_bytes=4096)
    plan = plan_launch(attempts, snap, limits)
    assert plan.needs_compaction is True


def test_state_truncated_to_limit() -> None:
    attempts = [{"n": 1, "outcome": "partial", "reason": "r"}]
    snap = _stub_snapshot(
        state_text="s" * 5000,
        state_is_stub=False,
        latest_result={"next_step": "n"},
        latest_result_is_missing=False,
    )
    limits = LaunchLimits(continue_pack_max_bytes=1_000_000, state_max_bytes=50)
    plan = plan_launch(attempts, snap, limits)
    state_section = plan.pack.split("## STATE.md\n", 1)[1].split("\n\n##", 1)[0]
    assert len(state_section.encode("utf-8")) <= 50


def test_no_needs_compaction_for_healthy_continue() -> None:
    attempts = [{"n": 1, "outcome": "partial", "reason": "next_step: go"}]
    snap = _stub_snapshot(
        state_text="## Done\n- A",
        state_is_stub=False,
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
