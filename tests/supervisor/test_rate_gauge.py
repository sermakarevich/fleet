from __future__ import annotations

from datetime import datetime, timezone

import structlog

from fleet.schemas import Event
from fleet.rate_gauge import RateGauge, _RESET_GRACE_SEC, _FALLBACK_DECAY_SEC


def _gauge() -> RateGauge:
    return RateGauge(log=structlog.get_logger())


def _ts() -> datetime:
    return datetime.now(tz=timezone.utc)


def _make_event(kind: str, *, usage_pct: float | None = None, resets_at: int | None = None, status: str | None = None) -> Event:
    rate_info: dict = {}
    if usage_pct is not None:
        rate_info["usage_pct"] = usage_pct
    if resets_at is not None:
        rate_info["resets_at"] = resets_at
    if status is not None:
        rate_info["status"] = status
    return Event(kind=kind, raw={}, ts=_ts(), rate_info=rate_info or None)


# ---------------------------------------------------------------------------
# update populates fields
# ---------------------------------------------------------------------------

def test_update_sets_current_usage_pct() -> None:
    g = _gauge()
    g.update(_make_event("rate_limit_info", usage_pct=78.4, resets_at=9_999_999_999))
    assert g.current_pct() == 78.4


def test_update_sets_resets_at() -> None:
    g = _gauge()
    g.update(_make_event("rate_limit_info", usage_pct=78.4, resets_at=9_999_999_999))
    assert g.resets_at == 9_999_999_999


def test_update_sets_last_updated() -> None:
    g = _gauge()
    assert g.last_updated is None
    g.update(_make_event("rate_limit_info", usage_pct=50.0))
    assert g.last_updated is not None


def test_update_accepts_rate_limit_kind() -> None:
    g = _gauge()
    g.update(_make_event("rate_limit", usage_pct=55.0))
    assert g.current_pct() == 55.0


def test_update_ignores_unrelated_kinds() -> None:
    g = _gauge()
    evt = Event(kind="assistant_text", raw={}, ts=_ts(), rate_info={"usage_pct": 99.0})
    g.update(evt)
    assert g.current_pct() == 0.0


def test_update_ignores_event_with_no_rate_info() -> None:
    g = _gauge()
    evt = Event(kind="rate_limit_info", raw={}, ts=_ts(), rate_info=None)
    g.update(evt)
    assert g.current_pct() == 0.0
    assert g.last_updated is None


# ---------------------------------------------------------------------------
# auto-reset past resets_at + grace
# ---------------------------------------------------------------------------

def test_auto_reset_past_grace_returns_zero() -> None:
    g = _gauge()
    resets_at = 1_000
    g.update(_make_event("rate_limit_info", usage_pct=92.0, resets_at=resets_at))
    past = datetime.fromtimestamp(resets_at + _RESET_GRACE_SEC + 1, tz=timezone.utc)
    assert g.current_pct(now=past) == 0.0


def test_auto_reset_clears_resets_at() -> None:
    g = _gauge()
    resets_at = 1_000
    g.update(_make_event("rate_limit_info", usage_pct=92.0, resets_at=resets_at))
    past = datetime.fromtimestamp(resets_at + _RESET_GRACE_SEC + 1, tz=timezone.utc)
    g.current_pct(now=past)
    assert g.resets_at is None


def test_no_reset_before_grace_expires() -> None:
    g = _gauge()
    resets_at = 1_000
    g.update(_make_event("rate_limit_info", usage_pct=92.0, resets_at=resets_at))
    just_before = datetime.fromtimestamp(resets_at + _RESET_GRACE_SEC - 1, tz=timezone.utc)
    assert g.current_pct(now=just_before) == 92.0


def test_no_reset_at_exact_grace_boundary() -> None:
    # now == resets_at + grace - epsilon: strictly before, so no reset
    g = _gauge()
    resets_at = 1_000
    g.update(_make_event("rate_limit_info", usage_pct=75.0, resets_at=resets_at))
    at_boundary_minus_one = datetime.fromtimestamp(resets_at + _RESET_GRACE_SEC - 0.001, tz=timezone.utc)
    assert g.current_pct(now=at_boundary_minus_one) == 75.0


# ---------------------------------------------------------------------------
# update without usage_pct preserves prior value
# ---------------------------------------------------------------------------

def test_update_no_usage_pct_preserves_prior_value() -> None:
    g = _gauge()
    g.update(_make_event("rate_limit_info", usage_pct=65.0))
    # rejection event: has rate_info but no usage_pct
    rejection = Event(kind="rate_limit", raw={}, ts=_ts(), rate_info={"status": "rejected"})
    g.update(rejection)
    assert g.current_pct() == 65.0


def test_update_no_usage_pct_records_last_updated() -> None:
    g = _gauge()
    rejection = Event(kind="rate_limit", raw={}, ts=_ts(), rate_info={"status": "rejected"})
    g.update(rejection)
    assert g.last_updated is not None


# ---------------------------------------------------------------------------
# snapshot
# ---------------------------------------------------------------------------

def test_snapshot_returns_expected_keys() -> None:
    g = _gauge()
    g.update(_make_event("rate_limit_info", usage_pct=42.0, resets_at=9_000))
    snap = g.snapshot()
    assert "current_usage_pct" in snap
    assert "resets_at" in snap
    assert "last_updated" in snap
    assert snap["current_usage_pct"] == 42.0
    assert snap["resets_at"] == 9_000


# ---------------------------------------------------------------------------
# Fallback decay when resets_at is None (edge case: API omitted resetsAt)
# ---------------------------------------------------------------------------

def test_fallback_decay_when_no_resets_at_and_stale() -> None:
    g = _gauge()
    g.update(_make_event("rate_limit_info", usage_pct=92.0))  # no resets_at
    lu = g.last_updated
    assert lu is not None
    stale = datetime.fromtimestamp(lu.timestamp() + _FALLBACK_DECAY_SEC + 1, tz=timezone.utc)
    assert g.current_pct(now=stale) == 0.0


def test_no_fallback_decay_when_not_yet_stale() -> None:
    g = _gauge()
    g.update(_make_event("rate_limit_info", usage_pct=92.0))
    lu = g.last_updated
    assert lu is not None
    not_stale = datetime.fromtimestamp(lu.timestamp() + _FALLBACK_DECAY_SEC - 1, tz=timezone.utc)
    assert g.current_pct(now=not_stale) == 92.0


def test_fallback_decay_not_triggered_when_resets_at_set() -> None:
    # resets_at is far in the future — normal auto-reset path, not fallback.
    g = _gauge()
    far_future = 9_999_999_999
    g.update(_make_event("rate_limit_info", usage_pct=92.0, resets_at=far_future))
    lu = g.last_updated
    assert lu is not None
    stale = datetime.fromtimestamp(lu.timestamp() + _FALLBACK_DECAY_SEC + 1, tz=timezone.utc)
    assert g.current_pct(now=stale) == 92.0


def test_fallback_decay_not_triggered_without_prior_update() -> None:
    # No update at all — gauge starts at 0.0 and last_updated is None.
    g = _gauge()
    stale = datetime.fromtimestamp(1_000_000 + _FALLBACK_DECAY_SEC + 1, tz=timezone.utc)
    assert g.current_pct(now=stale) == 0.0
