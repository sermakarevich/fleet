"""load_catalog: config folder list drives folder loading."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from fleet.core.config import RuntimeConfig
from fleet.flows import folders


def _flow_data() -> dict[str, Any]:
    return {
        "fleet_flow": 2,
        "description": "Tmp flow.",
        "enabled": True,
        "defaults": {"coder": "opencode", "model": "some-model", "retries": 2},
        "inputs": {"repo": {"required": True, "description": "Repo path."}},
        "steps": {"build": {"prompt": "Build it.", "outputs": ["units"]}},
    }


def test_load_catalog_includes_tmp_folder_flow(tmp_path: Path) -> None:
    folder = tmp_path / "extra"
    flows_dir = folder / "flows"
    flows_dir.mkdir(parents=True)
    (flows_dir / "local.yaml").write_text(yaml.safe_dump(_flow_data()), encoding="utf-8")
    config = RuntimeConfig(flows_folders=["builtin", str(folder)])
    catalog = folders.load_catalog(config)
    assert catalog.flow("local").description == "Tmp flow."
