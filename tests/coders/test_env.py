"""Coder env overlays: the FLEET_* pair and the Bedrock AWS overlay."""

from pathlib import Path

from fleet.coders.env import bedrock_env, fleet_env
from fleet.coders.settings import BedrockSettings
from fleet.core.task import Task


def _task() -> Task:
    return Task(id="t-42", title="T", description=None, status="open")


def test_fleet_env_has_task_id_and_dir(tmp_path: Path):
    assert fleet_env(_task(), tmp_path) == {
        "FLEET_TASK_ID": "t-42",
        "FLEET_TASK_DIR": str(tmp_path),
    }


def test_bedrock_env_none_is_empty():
    assert bedrock_env(None) == {}


def test_bedrock_env_blank_fields_are_empty():
    assert bedrock_env(BedrockSettings()) == {}


def test_bedrock_env_sets_profile_and_region():
    env = bedrock_env(BedrockSettings(profile="dev", region="us-east-1"))
    assert env == {"AWS_PROFILE": "dev", "AWS_REGION": "us-east-1"}
