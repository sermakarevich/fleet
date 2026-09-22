"""Render child-bead bodies for research runs (ADR 0015 §4, §6).

Each child body lives in ``templates/research/<kind>.md`` with
``{{placeholder}}`` tokens; the design phase fills them (one filled body per
child bead) so every research run's children carry identical, tested text.
Line 1 of each template is an HTML comment listing its placeholders.
"""

from __future__ import annotations

import re
from pathlib import Path

KINDS = (
    "copy",
    "topic_digest",
    "agg_digest",
    "agg_overview",
    "agg_disagreements",
    "agg_open_questions",
    "lens",
    "agg_index",
)

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates" / "research"

_PLACEHOLDER_RE = re.compile(r"\{\{([A-Za-z0-9_]+)\}\}")


def render_body(kind: str, **fields: str) -> str:
    """Fill ``templates/research/<kind>.md`` with *fields*.

    Every ``{{name}}`` token is replaced by ``fields["name"]``. Raises
    :class:`KeyError` naming the first unfilled placeholder (in file order)
    when a field is missing.
    """
    text = (_TEMPLATES_DIR / f"{kind}.md").read_text(encoding="utf-8")
    names = _PLACEHOLDER_RE.findall(text)
    for name in names:
        if name not in fields:
            raise KeyError(f"missing placeholder for render_body({kind!r}): {name!r}")
    return _PLACEHOLDER_RE.sub(lambda m: fields[m.group(1)], text)
