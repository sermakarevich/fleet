from fleet.coders.base import Coder
from fleet.coders.claude import ClaudeCoder
from fleet.coders.agy import AgyCoder
from fleet.coders.codex import CodexCoder

_REGISTRY: dict[str, type[Coder]] = {
    "claude": ClaudeCoder,
    "agy": AgyCoder,
    "codex": CodexCoder,
}


def get_coder(name: str) -> type[Coder]:
    """Return the coder class for the given name, or raise ValueError."""
    try:
        return _REGISTRY[name]
    except KeyError:
        available = list(_REGISTRY)
        raise ValueError(f"Unknown coder {name!r}. Available: {available}") from None


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
