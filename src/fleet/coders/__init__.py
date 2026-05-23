from fleet.coder import Coder
from fleet.coders.claude import ClaudeCoder
from fleet.coders.agy import AgyCoder

_REGISTRY: dict[str, type[Coder]] = {
    "claude": ClaudeCoder,
    "agy": AgyCoder,
}


def get_coder(name: str) -> type[Coder]:
    """Return the coder class for the given name, or raise ValueError."""
    try:
        return _REGISTRY[name]
    except KeyError:
        available = list(_REGISTRY)
        raise ValueError(f"Unknown coder {name!r}. Available: {available}") from None
