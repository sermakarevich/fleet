"""Config hot-reload: poll runtime.toml and emit on_config_reloaded on change.

Called by ``orchestrator/`` ``default_services`` (wiring). The last-seen
mtime lives in the tick closure built by ``make_config_reload``, so each
supervisor gets its own reload state without a class.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from fleet.core.limits import CONFIG_POLL_INTERVAL_SEC
from fleet.orchestrator.service import PeriodicService, ServiceOrder, emit
from fleet.state.config_file import reload_if_changed

if TYPE_CHECKING:
    from fleet.orchestrator.state import SupervisorState


def make_config_reload(interval_sec: float = CONFIG_POLL_INTERVAL_SEC) -> PeriodicService:
    """Build the config-reload periodic service with its own mtime cell."""
    seen: dict[str, float | None] = {"mtime": None}

    async def config_reload_tick(st: SupervisorState) -> None:
        """Reload config when runtime.toml changed and notify services."""
        try:
            result = reload_if_changed(st.runtime_toml_path, seen["mtime"])
        except OSError:
            return
        if result is None:
            return
        new_config, new_mtime = result
        old_config = st.config
        st.config = new_config
        seen["mtime"] = new_mtime
        st.log.info("config_reloaded", path=str(st.runtime_toml_path))
        await emit(st.services, "on_config_reloaded", st, old_config, new_config)

    return PeriodicService(
        name="config_reload",
        order=ServiceOrder.Config,
        interval_sec=interval_sec,
        tick=config_reload_tick,
    )
