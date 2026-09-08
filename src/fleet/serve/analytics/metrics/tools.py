"""Tool-use metrics: merged tool call counts over in-window records.

Called by ``serve/analytics/summary.py`` (``SECTION`` joins
``SUMMARY_SECTIONS``).
"""

from __future__ import annotations

from fleet.serve.analytics.metrics import Section
from fleet.serve.analytics.records import AttemptRecord
from fleet.serve.analytics.window import Window, in_window

_TOP_ROWS = 20


def compute(records: list[AttemptRecord], window: Window) -> dict:
    """Total tool calls plus the top tool names over in-window records."""
    counts: dict[str, int] = {}
    for record in records:
        if not in_window(record, window):
            continue
        for name, total in record.tool_counts.items():
            counts[name] = counts.get(name, 0) + total
    top = sorted(counts.items(), key=lambda pair: pair[1], reverse=True)[:_TOP_ROWS]
    rows = [{"name": name, "count": total} for name, total in top]
    return {"total": sum(counts.values()), "rows": rows}


SECTION = Section("tools", "Tool usage", compute)
