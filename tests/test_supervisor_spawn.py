from __future__ import annotations

import structlog
import structlog.testing

from fleet.rate_gauge import RateGauge
from fleet.supervisor_spawn import SpawnController, SpawnDecision


def _gauge(pct: float = 0.0) -> RateGauge:
    g = RateGauge(log=structlog.get_logger())
    g.current_usage_pct = pct
    return g


def _controller() -> SpawnController:
    return SpawnController(log=structlog.get_logger())


# ---------------------------------------------------------------------------
# Spawn decisions
# ---------------------------------------------------------------------------

def test_spawn_when_below_cap_and_below_threshold() -> None:
    d = _controller().decide(in_flight=0, max_concurrent=3, threshold_pct=90.0, gauge=_gauge(80.0))
    assert d == SpawnDecision.SPAWN


def test_spawn_when_in_flight_below_cap_and_gauge_zero() -> None:
    d = _controller().decide(in_flight=2, max_concurrent=3, threshold_pct=90.0, gauge=_gauge(0.0))
    assert d == SpawnDecision.SPAWN


def test_paused_full_when_in_flight_equals_cap() -> None:
    d = _controller().decide(in_flight=3, max_concurrent=3, threshold_pct=90.0, gauge=_gauge(0.0))
    assert d == SpawnDecision.PAUSED_FULL


def test_paused_full_when_in_flight_exceeds_cap() -> None:
    d = _controller().decide(in_flight=5, max_concurrent=3, threshold_pct=90.0, gauge=_gauge(0.0))
    assert d == SpawnDecision.PAUSED_FULL


def test_paused_rate_limit_when_gauge_above_threshold() -> None:
    d = _controller().decide(in_flight=1, max_concurrent=3, threshold_pct=90.0, gauge=_gauge(92.0))
    assert d == SpawnDecision.PAUSED_RATE_LIMIT


def test_strict_inequality_at_threshold_gives_spawn() -> None:
    # gauge == threshold → NOT paused (strict >)
    d = _controller().decide(in_flight=0, max_concurrent=3, threshold_pct=90.0, gauge=_gauge(90.0))
    assert d == SpawnDecision.SPAWN


def test_just_above_threshold_gives_paused_rate_limit() -> None:
    d = _controller().decide(in_flight=0, max_concurrent=3, threshold_pct=90.0, gauge=_gauge(90.001))
    assert d == SpawnDecision.PAUSED_RATE_LIMIT


def test_paused_full_takes_priority_over_rate_limit() -> None:
    # Both in_flight == cap AND gauge > threshold: PAUSED_FULL wins (checked first)
    d = _controller().decide(in_flight=3, max_concurrent=3, threshold_pct=90.0, gauge=_gauge(95.0))
    assert d == SpawnDecision.PAUSED_FULL


# ---------------------------------------------------------------------------
# Pause / resume log transitions
# ---------------------------------------------------------------------------

def test_rate_limit_pause_emitted_on_first_paused_decision() -> None:
    with structlog.testing.capture_logs() as logs:
        ctrl = SpawnController(log=structlog.get_logger())
        ctrl.decide(in_flight=0, max_concurrent=3, threshold_pct=90.0, gauge=_gauge(92.0))

    pause_logs = [l for l in logs if l.get("event") == "rate_limit_pause"]
    assert len(pause_logs) == 1
    assert pause_logs[0]["current_usage_pct"] == 92.0
    assert pause_logs[0]["rate_limit_threshold_pct"] == 90.0
    assert pause_logs[0]["log_level"] == "warning"


def test_rate_limit_pause_emitted_only_once_while_sustained() -> None:
    with structlog.testing.capture_logs() as logs:
        ctrl = SpawnController(log=structlog.get_logger())
        for _ in range(5):
            ctrl.decide(in_flight=0, max_concurrent=3, threshold_pct=90.0, gauge=_gauge(92.0))

    pause_logs = [l for l in logs if l.get("event") == "rate_limit_pause"]
    assert len(pause_logs) == 1


def test_rate_limit_resume_emitted_on_leaving_paused_state() -> None:
    with structlog.testing.capture_logs() as logs:
        ctrl = SpawnController(log=structlog.get_logger())
        ctrl.decide(in_flight=0, max_concurrent=3, threshold_pct=90.0, gauge=_gauge(92.0))  # pause
        ctrl.decide(in_flight=0, max_concurrent=3, threshold_pct=90.0, gauge=_gauge(85.0))  # resume

    resume_logs = [l for l in logs if l.get("event") == "rate_limit_resume"]
    assert len(resume_logs) == 1
    assert resume_logs[0]["current_usage_pct"] == 85.0
    assert resume_logs[0]["rate_limit_threshold_pct"] == 90.0
    assert resume_logs[0]["log_level"] == "info"


def test_rate_limit_resume_emitted_only_once_per_transition() -> None:
    with structlog.testing.capture_logs() as logs:
        ctrl = SpawnController(log=structlog.get_logger())
        ctrl.decide(in_flight=0, max_concurrent=3, threshold_pct=90.0, gauge=_gauge(92.0))  # pause
        ctrl.decide(in_flight=0, max_concurrent=3, threshold_pct=90.0, gauge=_gauge(80.0))  # resume
        ctrl.decide(in_flight=0, max_concurrent=3, threshold_pct=90.0, gauge=_gauge(75.0))  # spawn again
        ctrl.decide(in_flight=0, max_concurrent=3, threshold_pct=90.0, gauge=_gauge(70.0))  # spawn again

    resume_logs = [l for l in logs if l.get("event") == "rate_limit_resume"]
    assert len(resume_logs) == 1


def test_no_resume_log_without_prior_pause() -> None:
    with structlog.testing.capture_logs() as logs:
        ctrl = SpawnController(log=structlog.get_logger())
        ctrl.decide(in_flight=0, max_concurrent=3, threshold_pct=90.0, gauge=_gauge(50.0))
        ctrl.decide(in_flight=0, max_concurrent=3, threshold_pct=90.0, gauge=_gauge(40.0))

    resume_logs = [l for l in logs if l.get("event") == "rate_limit_resume"]
    assert len(resume_logs) == 0


def test_multiple_pause_resume_cycles_each_logged_once() -> None:
    with structlog.testing.capture_logs() as logs:
        ctrl = SpawnController(log=structlog.get_logger())
        ctrl.decide(in_flight=0, max_concurrent=3, threshold_pct=90.0, gauge=_gauge(92.0))  # pause 1
        ctrl.decide(in_flight=0, max_concurrent=3, threshold_pct=90.0, gauge=_gauge(80.0))  # resume 1
        ctrl.decide(in_flight=0, max_concurrent=3, threshold_pct=90.0, gauge=_gauge(95.0))  # pause 2
        ctrl.decide(in_flight=0, max_concurrent=3, threshold_pct=90.0, gauge=_gauge(70.0))  # resume 2

    pause_logs = [l for l in logs if l.get("event") == "rate_limit_pause"]
    resume_logs = [l for l in logs if l.get("event") == "rate_limit_resume"]
    assert len(pause_logs) == 2
    assert len(resume_logs) == 2


# ---------------------------------------------------------------------------
# Lowered threshold does not kill in-flight runners (FR-27)
# ---------------------------------------------------------------------------

def test_lowered_threshold_returns_paused_rate_limit_for_new_spawns() -> None:
    # Simulates: 3 in-flight, threshold lowered from 90 to 80, gauge at 85
    ctrl = _controller()
    d = ctrl.decide(in_flight=3, max_concurrent=5, threshold_pct=80.0, gauge=_gauge(85.0))
    # 85 > 80 and 3 < 5, so PAUSED_RATE_LIMIT
    assert d == SpawnDecision.PAUSED_RATE_LIMIT


def test_controller_has_no_cancel_or_kill_surface() -> None:
    # Structural: the controller has no cancel/kill method, so it cannot
    # touch in-flight runners regardless of threshold changes.
    ctrl = _controller()
    assert not hasattr(ctrl, "cancel")
    assert not hasattr(ctrl, "kill")
    assert not hasattr(ctrl, "terminate")
