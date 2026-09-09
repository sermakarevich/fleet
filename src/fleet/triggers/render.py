"""Task-template rendering for event triggers (ADR 0011 templates).

`render()` fills `{{event.<key>}}` from an event payload plus
`{{trigger.name}}` and `{{n}}`. Unknown placeholders stay as written (the
same rule as ADR 0010). Called by `firing.py::open_task`; pure, no I/O.
"""

from __future__ import annotations

import re

from fleet.triggers.model import Trigger, TriggerEvent

#: One compiled pattern for the three known placeholders (ADR 0011).
_PLACEHOLDER_RE = re.compile(r"\{\{\s*(event\.([a-z0-9_]+)|trigger\.name|n)\s*\}\}")


def render(template: str, *, trigger: Trigger, event: TriggerEvent, firing_n: int) -> str:
    """Fill event/trigger/n placeholders; unknown ones stay as written."""
    if not template:
        return ""

    def _replace(match: re.Match[str]) -> str:
        """Swap one placeholder for its value, or leave it untouched."""
        inner = match.group(1)
        if inner == "trigger.name":
            return trigger.name
        if inner == "n":
            return str(firing_n)
        key = match.group(2)
        if key is not None:
            return event.payload.get(key, match.group(0))
        return match.group(0)

    return _PLACEHOLDER_RE.sub(_replace, template)
