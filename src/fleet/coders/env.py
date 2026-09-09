"""Shared env overlays every coder composes into its spawn env.

:func:`fleet_env` owns the ``FLEET_*`` pair (moved from ``base.base_env``);
:func:`bedrock_env` owns the AWS overlay for Bedrock-routed models (moved
from ``ollama.ollama_env``). Coders build their ``env()`` as
``{**fleet_env(task, task_dir), **...}``. Called by the five coder modules.
"""

from __future__ import annotations

from pathlib import Path

from fleet.coders.settings import BedrockSettings
from fleet.core.task import Task


def fleet_env(task: Task, task_dir: Path) -> dict[str, str]:
    """The ``FLEET_*`` variables every coder sets (attempt vars layered later)."""
    return {
        "FLEET_TASK_ID": task.id,
        "FLEET_TASK_DIR": str(task_dir),
    }


def bedrock_env(settings: BedrockSettings | None) -> dict[str, str]:
    """AWS env overlay for Bedrock-routed models; empty when not Bedrock.

    *settings* is None (or has blank fields) for Ollama routing: Ollama needs
    no env since its URL travels in coder config.
    """
    if settings is None:
        return {}
    env: dict[str, str] = {}
    if settings.profile:
        env["AWS_PROFILE"] = settings.profile
    if settings.region:
        env["AWS_REGION"] = settings.region
    return env
