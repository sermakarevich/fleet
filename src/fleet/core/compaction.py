"""The bounded inputs for a STATE.md compaction prompt.

Called by ``workers/compact.py`` (``collect_material`` builds one from the
task dir) and ``core/compaction_fallback.py`` (the deterministic fallback
renders one without a model). Never raw logs: the current STATE.md, the
last few derived attempt summaries, the last RESULT.json, and short git
context of the workdir.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class CompactionMaterial:
    """Bounded inputs for the compaction prompt. Never raw logs."""

    state: str = ""
    summaries: list[str] = field(default_factory=list)
    result_text: str = ""
    git_log: list[str] = field(default_factory=list)
    git_status: list[str] = field(default_factory=list)
