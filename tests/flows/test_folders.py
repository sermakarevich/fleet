"""Tests for fleet.flows.folders."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from fleet.core.errors import FlowNotFound
from fleet.flows import folders
from fleet.flows.folders import Catalog


def _flow_data() -> dict[str, Any]:
    """Build a minimal valid flow mapping with one coder step."""
    return {
        "fleet_flow": 2,
        "description": "Test flow.",
        "enabled": True,
        "defaults": {"coder": "opencode", "model": "some-model", "retries": 2},
        "inputs": {"repo": {"required": True, "description": "Repo path."}},
        "steps": {"build": {"prompt": "Build it.", "outputs": ["units"]}},
    }


def _tool_data() -> dict[str, Any]:
    """Build a minimal valid tool mapping."""
    return {
        "fleet_tool": 2,
        "description": "Test tool.",
        "command": ["echo", "{{ args.message }}"],
        "args": {"message": {"required": True, "description": "Text."}},
        "output": "text",
        "timeout": 30,
    }


def _write_yaml(path: Path, data: dict[str, Any]) -> Path:
    """Write ``data`` as YAML to ``path``, creating parent dirs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def _write_flow(folder: Path, name: str, data: dict[str, Any] | None = None) -> Path:
    """Write a flow file ``<folder>/flows/<name>.yaml``."""
    return _write_yaml(folder / "flows" / f"{name}.yaml", data or _flow_data())


def _write_tool(folder: Path, name: str, data: dict[str, Any] | None = None) -> Path:
    """Write a tool file ``<folder>/tools/<name>.yaml``."""
    return _write_yaml(folder / "tools" / f"{name}.yaml", data or _tool_data())


def test_later_folder_replaces_same_name(tmp_path: Path) -> None:
    """A later folder's file with the same name replaces the earlier one."""
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_flow(first, "demo")
    changed = _flow_data()
    changed["description"] = "Second wins."
    second_path = _write_flow(second, "demo", changed)
    catalog = folders.load([str(first), str(second)])
    assert catalog.problems == []
    assert catalog.flow("demo").description == "Second wins."
    assert catalog.flow("demo").source == str(second_path)


def test_override_merges_nested_key_and_keeps_rest(tmp_path: Path) -> None:
    """An override changes one nested key while the rest of the file survives."""
    folder = tmp_path / "only"
    _write_flow(folder, "demo")
    override = {"defaults": {"model": "bigger-model"}, "description": "Tweaked."}
    override_path = _write_yaml(folder / "flows" / "demo.override.yaml", override)
    catalog = folders.load([str(folder)])
    assert catalog.problems == []
    loaded = catalog.flow("demo")
    assert loaded.description == "Tweaked."
    assert loaded.defaults == {"coder": "opencode", "model": "bigger-model", "retries": 2}
    assert loaded.source == str(override_path)


def test_override_none_deletes_key(tmp_path: Path) -> None:
    """An override value of None deletes the key from the merged mapping."""
    folder = tmp_path / "only"
    _write_flow(folder, "demo")
    _write_yaml(folder / "flows" / "demo.override.yaml", {"defaults": {"retries": None}})
    catalog = folders.load([str(folder)])
    assert catalog.problems == []
    assert "retries" not in catalog.flow("demo").defaults
    assert catalog.flow("demo").defaults["coder"] == "opencode"


def test_override_without_base_is_problem(tmp_path: Path) -> None:
    """An override with no base file is a problem and loads nothing."""
    folder = tmp_path / "only"
    orphan = _write_yaml(folder / "flows" / "ghost.override.yaml", {"description": "No base."})
    catalog = folders.load([str(folder)])
    assert catalog.flows == {}
    assert [f"{orphan}: override without a base flow"] == catalog.problems


def test_bad_yaml_and_invalid_flow_are_problems_but_others_load(tmp_path: Path) -> None:
    """One bad YAML file and one invalid flow do not stop other files."""
    folder = tmp_path / "only"
    good_path = _write_flow(folder, "good")
    bad_path = folder / "flows" / "broken.yaml"
    bad_path.parent.mkdir(parents=True, exist_ok=True)
    bad_path.write_text("steps: [unclosed\n  bad indent: : :\n", encoding="utf-8")
    invalid_path = _write_flow(folder, "invalid", {"fleet_flow": 1, "steps": {}})
    catalog = folders.load([str(folder)])
    assert catalog.flow("good").source == str(good_path)
    assert "good" in catalog.flows and "invalid" not in catalog.flows
    assert "broken" not in catalog.flows
    problem_paths = [entry.split(":")[0] for entry in catalog.problems]
    assert str(bad_path) in problem_paths
    assert any(str(invalid_path) in entry for entry in catalog.problems)
    assert len(catalog.problems) == 2


def test_missing_folder_is_problem_not_error(tmp_path: Path) -> None:
    """A folder that does not exist becomes a problem entry, not a raise."""
    missing = tmp_path / "no-such-folder"
    folder = tmp_path / "real"
    _write_flow(folder, "demo")
    catalog = folders.load([str(missing), str(folder)])
    assert catalog.flow("demo").description == "Test flow."
    assert len(catalog.problems) == 1
    assert catalog.problems[0].endswith("missing folder")
    assert str(missing) in catalog.problems[0]


def test_disabled_flow_stays_in_catalog(tmp_path: Path) -> None:
    """Flows with enabled == False stay in the catalog for callers to filter."""
    folder = tmp_path / "only"
    data = _flow_data()
    data["enabled"] = False
    _write_flow(folder, "off", data)
    catalog = folders.load([str(folder)])
    assert catalog.problems == []
    assert catalog.flow("off").enabled is False


def test_tools_load_replace_and_override(tmp_path: Path) -> None:
    """Tools follow the same replace and override-merge rules as flows."""
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_tool(first, "echoer")
    changed = _tool_data()
    changed["timeout"] = 45
    _write_tool(second, "echoer", changed)
    _write_yaml(second / "tools" / "echoer.override.yaml", {"timeout": 60})
    catalog = folders.load([str(first), str(second)])
    assert catalog.problems == []
    assert catalog.tool("echoer").timeout == 60
    assert catalog.tool("echoer").command == ("echo", "{{ args.message }}")
    assert catalog.tool("echoer").source.endswith("echoer.override.yaml")


def test_tool_override_without_base_is_problem(tmp_path: Path) -> None:
    """A tool override with no base tool file is a problem."""
    folder = tmp_path / "only"
    _write_yaml(folder / "tools" / "ghost.override.yaml", {"timeout": 5})
    catalog = folders.load([str(folder)])
    assert catalog.tools == {}
    assert len(catalog.problems) == 1
    assert "override without a base flow" in catalog.problems[0]


def test_invalid_tool_is_problem_and_others_load(tmp_path: Path) -> None:
    """An invalid tool file is a problem while valid tools still load."""
    folder = tmp_path / "only"
    _write_tool(folder, "good")
    _write_tool(folder, "bad", {"fleet_tool": 2})
    catalog = folders.load([str(folder)])
    assert catalog.tool("good").name == "good"
    assert "bad" not in catalog.tools
    assert len(catalog.problems) == 1


def test_missing_flow_and_tool_raise_not_found(tmp_path: Path) -> None:
    """Catalog.flow/tool raise FlowNotFound for names that never loaded."""
    catalog = folders.load([str(tmp_path / "empty-missing")])
    with pytest.raises(FlowNotFound):
        catalog.flow("nope")
    with pytest.raises(FlowNotFound):
        catalog.tool("nope")


def test_empty_catalog_defaults() -> None:
    """A fresh Catalog holds empty maps and an empty problem list."""
    catalog = Catalog()
    assert catalog.flows == {} and catalog.tools == {} and catalog.problems == []


def test_deep_merge_replaces_lists_and_scalars() -> None:
    """Non-mapping override values replace; nested mappings merge deeply."""
    merged = folders.deep_merge(
        {"steps": {"one": {"prompt": "Old"}}, "tags": ["a"], "count": 1},
        {"steps": {"two": {"prompt": "New"}}, "tags": ["b"], "count": 2},
    )
    assert merged == {
        "steps": {"one": {"prompt": "Old"}, "two": {"prompt": "New"}},
        "tags": ["b"],
        "count": 2,
    }


def test_deep_merge_none_deletes_missing_key_safely() -> None:
    """Deleting a key that is not there is a no-op, not an error."""
    assert folders.deep_merge({"kept": True}, {"gone": None}) == {"kept": True}


def test_resolve_folder_builtin_exists_and_is_directory() -> None:
    """resolve_folder('builtin') points at an existing directory."""
    builtin = folders.resolve_folder("builtin")
    assert builtin.exists() and builtin.is_dir()


def test_resolve_folder_expands_user_path() -> None:
    """Other specs become expanded Paths instead of the builtin directory."""
    resolved = folders.resolve_folder("~/some-flows")
    assert str(resolved).endswith("some-flows")
    assert "~" not in str(resolved)
