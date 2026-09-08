"""One model reference parser for the Ollama-routed coders.

Fleet's global ``RuntimeConfig.model`` defaults to ``sonnet`` and leaks into
every coder; these are Claude aliases, never valid Ollama model names. This
module owns that alias table and the ``provider/name`` split. Called by
``coders/opencode.py`` and ``coders/pi.py`` (each passes its own provider id
for bare names).
"""

from __future__ import annotations

from dataclasses import dataclass

CLAUDE_ALIASES = frozenset({"sonnet", "opus", "haiku"})


@dataclass(frozen=True)
class ModelRef:
    """A parsed model id: provider prefix plus the bare model name."""

    provider: str
    name: str

    @property
    def full_id(self) -> str:
        """Provider-qualified id as passed to the coder CLI (``provider/name``)."""
        return f"{self.provider}/{self.name}"


def resolve_model(model: str, default: str, *, default_provider: str = "") -> ModelRef:
    """Parse *model* into a ModelRef, mapping Claude aliases onto *default*.

    Names with a ``provider/`` prefix pass through untouched; bare names take
    *default_provider* (or *default*'s own prefix when it is qualified).
    """
    if model in CLAUDE_ALIASES:
        model = default
    if "/" in model:
        provider, name = model.split("/", 1)
        return ModelRef(provider, name)
    if "/" in default:
        provider, _ = default.split("/", 1)
        return ModelRef(provider, model)
    return ModelRef(default_provider, model)
