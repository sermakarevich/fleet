"""Config hot-reload: poll runtime.toml and emit on_config_reloaded on change."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fleet.core.config import reload_if_changed
from fleet.core.limits import CONFIG_POLL_INTERVAL_SEC
from fleet.orchestrator.service import PeriodicService, ServiceOrder, emit

if TYPE_CHECKING:
    from fleet.orchestrator.state import SupervisorState


class ConfigReload(PeriodicService):
    """Poll runtime.toml and swap live config when the file changes."""

    order = ServiceOrder.Config
    name = "config_reload"

    def __init__(self, interval_sec: float = CONFIG_POLL_INTERVAL_SEC) -> None:
        super().__init__(interval_sec)
        self._mtime: float | None = None

    async def tick(self, st: SupervisorState) -> None:
        """Reload config when runtime.toml changed and notify services."""
        try:
            result = reload_if_changed(st.runtime_toml_path, self._mtime)
        except OSError:
            return
        if result is None:
            return
        new_config, new_mtime = result
        old_config = st.config
        st.config = new_config
        self._mtime = new_mtime
        st.log.info("config_reloaded", path=str(st.runtime_toml_path))
        await emit(st.services, "on_config_reloaded", st, old_config, new_config)
