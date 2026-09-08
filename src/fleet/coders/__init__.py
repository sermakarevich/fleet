from fleet.coders.agy import AgyCoder
from fleet.coders.base import Coder
from fleet.coders.claude import ClaudeCoder
from fleet.coders.codex import CodexCoder
from fleet.coders.opencode import OpencodeCoder
from fleet.coders.pi import PiCoder

_REGISTRY: dict[str, type[Coder]] = {
    "claude": ClaudeCoder,
    "agy": AgyCoder,
    "codex": CodexCoder,
    "opencode": OpencodeCoder,
    "pi": PiCoder,
}


def get_coder(name: str) -> type[Coder]:
    """Return the coder class for the given name, or raise ValueError."""
    try:
        return _REGISTRY[name]
    except KeyError:
        available = list(_REGISTRY)
        raise ValueError(f"Unknown coder {name!r}. Available: {available}") from None


def context_limit_for(
    coder_name: str | None,
    model: str | None = None,
    overrides: dict[str, int] | None = None,
) -> int:
    """Resolved context window for a coder/model pair (one denominator for UI + supervisor)."""
    if not coder_name:
        return Coder.context_limit
    try:
        return get_coder(coder_name).context_limit_for(model, overrides)
    except ValueError:
        return Coder.context_limit


def list_coders() -> list[dict]:
    """Return coder metadata for all registered coders."""
    return [
        {
            "name": cls.name,
            "context_limit": cls.context_limit,
            "default_model": cls.default_model,
        }
        for cls in _REGISTRY.values()
    ]
