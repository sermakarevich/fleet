"""Flow and tool folders: ordered folder loading with replace and override.

Reads flow and tool YAML files from an ordered list of folders
(``docs/27_sep_upgrade/DESIGN.md`` §3.3). A later folder with the same file
name **replaces** the earlier file; a later ``<name>.override.yaml`` with
only some keys **merges** over it via :func:`deep_merge`. Every file that
fails becomes one ``"<path>: <message>"`` entry in :attr:`Catalog.problems`
instead of raising. This module imports ``core`` only.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

import fleet
from fleet.core.config import RuntimeConfig, expand_folders
from fleet.core.errors import FlowInvalid, FlowNotFound
from fleet.flows.model import Flow, flow_from_dict
from fleet.flows.tools import Tool, tool_from_dict

BUILTIN_SPEC = "builtin"
"""Folder spec string that means the ``builtin/`` directory shipped with fleet."""

_FLOW_DIR = "flows"
_TOOL_DIR = "tools"
_KINDS: tuple[str, str] = (_FLOW_DIR, _TOOL_DIR)
_OVERRIDE_SUFFIX = ".override.yaml"
_YAML_SUFFIX = ".yaml"


@dataclass(frozen=True)
class Catalog:
    """Every flow and tool loaded from an ordered list of folders."""

    flows: dict[str, Flow] = field(default_factory=dict)
    tools: dict[str, Tool] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)

    def flow(self, name: str) -> Flow:
        """Return the flow with this name, raising FlowNotFound when missing."""
        try:
            return self.flows[name]
        except KeyError as exc:
            raise FlowNotFound(name) from exc

    def tool(self, name: str) -> Tool:
        """Return the tool with this name, raising FlowNotFound when missing."""
        try:
            return self.tools[name]
        except KeyError as exc:
            raise FlowNotFound(name) from exc


def resolve_folder(spec: str) -> Path:
    """Map a folder spec to a directory: ``"builtin"`` ships with fleet."""
    if spec == BUILTIN_SPEC:
        package_dir = Path(fleet.__file__).parent
        return package_dir / BUILTIN_SPEC
    return Path(spec).expanduser()


def deep_merge(base: Mapping[str, Any], over: Mapping[str, Any]) -> dict[str, Any]:
    """Merge ``over`` onto ``base``: nested mappings recurse, else replace.

    Any other value in ``over`` replaces the base value, and keys in
    ``over`` with value None delete the key from the result.
    """
    merged: dict[str, Any] = dict(base)
    for merge_key, over_value in over.items():
        if over_value is None:
            merged.pop(merge_key, None)
        elif isinstance(over_value, Mapping) and isinstance(merged.get(merge_key), Mapping):
            merged[merge_key] = deep_merge(merged[merge_key], over_value)
        else:
            merged[merge_key] = over_value
    return merged


def load(folders: Sequence[str]) -> Catalog:
    """Load flows and tools from ``folders`` in order into one Catalog.

    For each folder in order, for kind in ("flows", "tools"): every
    ``*.yaml`` that is not ``*.override.yaml`` replaces the stored raw
    mapping for its stem name, then every ``*.override.yaml`` merges over
    the stored mapping (an override with no base is a problem). After all
    folders, raw mappings are built into Flow/Tool objects; a FlowInvalid
    or YAML error becomes one problems entry and the name is left out. A
    missing folder is a problem, not an error. Flows with
    ``enabled == False`` stay in the catalog; ``source`` is the last file
    path that wrote the entry.
    """
    raw: dict[str, dict[str, Any]] = {kind: {} for kind in _KINDS}
    sources: dict[str, dict[str, str]] = {kind: {} for kind in _KINDS}
    problems: list[str] = []
    for spec in folders:
        folder = resolve_folder(spec)
        if not folder.is_dir():
            problems.append(f"{folder}: missing folder")
            continue
        for kind in _KINDS:
            _read_base_files(folder / kind, raw[kind], sources[kind], problems)
            _read_override_files(folder / kind, raw[kind], sources[kind], problems)
    flows = _build_flows(raw[_FLOW_DIR], sources[_FLOW_DIR], problems)
    tools = _build_tools(raw[_TOOL_DIR], sources[_TOOL_DIR], problems)
    return Catalog(flows=flows, tools=tools, problems=problems)


def load_catalog(config: RuntimeConfig) -> Catalog:
    """Load the flow/tool catalog from the folders listed in ``config``."""
    return load(expand_folders(config.flows_folders))


def _read_base_files(
    kind_dir: Path,
    raw: dict[str, Any],
    sources: dict[str, str],
    problems: list[str],
) -> None:
    """Read every plain ``*.yaml`` in ``kind_dir``, replacing stored entries."""
    if not kind_dir.is_dir():
        return
    for path in sorted(kind_dir.glob("*.yaml")):
        if path.name.endswith(_OVERRIDE_SUFFIX):
            continue
        data = _read_yaml_mapping(path, problems)
        if data is None:
            continue
        raw[path.stem] = data
        sources[path.stem] = str(path)


def _read_override_files(
    kind_dir: Path,
    raw: dict[str, Any],
    sources: dict[str, str],
    problems: list[str],
) -> None:
    """Merge every ``*.override.yaml`` in ``kind_dir`` over stored entries."""
    if not kind_dir.is_dir():
        return
    for path in sorted(kind_dir.glob(f"*{_OVERRIDE_SUFFIX}")):
        data = _read_yaml_mapping(path, problems)
        if data is None:
            continue
        override_name = path.name[: -len(_OVERRIDE_SUFFIX)]
        if override_name not in raw:
            problems.append(f"{path}: override without a base flow")
            continue
        raw[override_name] = deep_merge(raw[override_name], data)
        sources[override_name] = str(path)


def _read_yaml_mapping(path: Path, problems: list[str]) -> dict[str, Any] | None:
    """Read ``path`` as a YAML mapping; on failure record a problem."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        problems.append(f"{path}: {exc.strerror or exc}")
        return None
    except yaml.YAMLError as exc:
        problems.append(f"{path}: {exc}")
        return None
    if data is None:
        return {}
    if not isinstance(data, Mapping):
        problems.append(f"{path}: top level must be a mapping")
        return None
    return dict(data)


def _build_flows(
    raw: dict[str, Any], sources: dict[str, str], problems: list[str]
) -> dict[str, Flow]:
    """Build Flow objects; failures become problems and the name is left out."""
    flows: dict[str, Flow] = {}
    for flow_name in sorted(raw):
        try:
            flows[flow_name] = flow_from_dict(raw[flow_name], flow_name, sources[flow_name])
        except FlowInvalid as exc:
            problems.append(f"{sources[flow_name]}: {exc}")
    return flows


def _build_tools(
    raw: dict[str, Any], sources: dict[str, str], problems: list[str]
) -> dict[str, Tool]:
    """Build Tool objects; failures become problems and the name is left out."""
    tools: dict[str, Tool] = {}
    for tool_name in sorted(raw):
        try:
            tools[tool_name] = tool_from_dict(raw[tool_name], tool_name, sources[tool_name])
        except FlowInvalid as exc:
            problems.append(f"{sources[tool_name]}: {exc}")
    return tools
