from __future__ import annotations

from enum import Enum

import structlog

from fleet.rate_gauge import RateGauge


class SpawnDecision(Enum):
    SPAWN = "spawn"
    PAUSED_FULL = "paused_full"
    PAUSED_RATE_LIMIT = "paused_rate_limit"


class SpawnController:
    def __init__(self, *, log: structlog.BoundLogger) -> None:
        self._log = log
        self._was_rate_paused: bool = False

    def decide(
        self,
        *,
        in_flight: int,
        max_concurrent: int,
        threshold_pct: float,
        gauge: RateGauge,
    ) -> SpawnDecision:
        if in_flight >= max_concurrent:
            return SpawnDecision.PAUSED_FULL

        current_pct = gauge.current_pct()

        if current_pct > threshold_pct:
            if not self._was_rate_paused:
                self._log.warning(
                    "rate_limit_pause",
                    current_usage_pct=current_pct,
                    rate_limit_threshold_pct=threshold_pct,
                )
                self._was_rate_paused = True
            return SpawnDecision.PAUSED_RATE_LIMIT

        if self._was_rate_paused:
            self._log.info(
                "rate_limit_resume",
                current_usage_pct=current_pct,
                rate_limit_threshold_pct=threshold_pct,
            )
            self._was_rate_paused = False

        return SpawnDecision.SPAWN
