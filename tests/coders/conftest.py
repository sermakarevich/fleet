"""Shared fixtures and helpers for coder tests."""

from __future__ import annotations

from fleet.coders.claude import ClaudeCoder
from fleet.coders.pi import PiCoder
from fleet.coders.settings import BedrockSettings, PiSettings
from fleet.core.task import Task
from fleet.state.paths import fleet_home

# ---------------------------------------------------------------------------
# Shared by test_coder_claude.py splits (Clean 29/30: moved, not rewritten).
# ---------------------------------------------------------------------------


def _coder() -> ClaudeCoder:
    return ClaudeCoder(fleet_home=fleet_home())


# ---------------------------------------------------------------------------
# Shared by test_coder_pi.py splits (Clean 29/30: moved, not rewritten).
# ---------------------------------------------------------------------------


def _bedrock_coder(model: str, **kwargs) -> PiCoder:
    """PiCoder routed to Bedrock with a dev profile/region by default."""
    bedrock = BedrockSettings(
        profile=kwargs.pop("bedrock_profile", "dev"),
        region=kwargs.pop("bedrock_region", "us-east-1"),
        context_limit=kwargs.pop("bedrock_context_limit", None),
    )
    agent_dir = kwargs.pop("agent_dir", None)
    if agent_dir is not None:
        kwargs["settings"] = PiSettings(agent_dir=agent_dir, bedrock=bedrock)
    else:
        kwargs.setdefault("settings", PiSettings(bedrock=bedrock))
    kwargs.setdefault("fleet_home", fleet_home())
    return PiCoder(model=model, **kwargs)


def _task(task_id: str = "test-001", cwd: str | None = None) -> Task:
    return Task(
        id=task_id,
        title="Test task",
        description="Do the thing.",
        status="in_progress",
        cwd=cwd,
    )
