"""Workflow-test fixtures."""

from __future__ import annotations

import pytest

from fleet.workflows.builders import sources


@pytest.fixture(autouse=True)
def _instant_http_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep _http_get's retry loop, drop its real-time pauses."""
    monkeypatch.setattr(sources, "HTTP_RETRY_DELAYS_S", (0.0, 0.0))
