"""Shared shape for one analytics metric section.

Called by ``serve/analytics/metrics/*`` (each metric family defines its
``SECTION`` from this type) and ``serve/analytics/summary.py`` (the
``SUMMARY_SECTIONS`` registry). This module owns the type only; it imports
no metric module, so there is no import cycle.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fleet.serve.analytics.records import AttemptRecord
from fleet.serve.analytics.window import Window


@dataclass(frozen=True)
class Section:
    """One named metric: key in the summary dict plus its compute function."""

    key: str
    title: str
    compute: Callable[[list[AttemptRecord], Window], Any]
