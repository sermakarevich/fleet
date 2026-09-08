"""Per-model context windows: the one denominator for supervisor and UI.

Before this module the context percentage divided by one number per coder
(``OpencodeCoder.context_limit`` / ``RuntimeConfig.opencode_context_limit``),
so a Muse Spark session at 142k tokens showed 102-110 % while its real
window is 1,048,576 tokens. Every caller — ``workers/llm_session.py``
(checkpoint/kill), ``state/task_summary.py`` (UI pct), and each coder's
``context_limit_for`` — resolves through ``resolve_window`` here.
"""

from __future__ import annotations

DEFAULT_WINDOWS: dict[str, int] = {
    # Muse Spark via opencode-go (models.dev): 1M window.
    "muse-spark-1.3-contributor": 1_048_576,
    "muse-spark-1.2-contributor": 1_048_576,
    "muse-spark": 1_048_576,
    # Claude family (CLI + Bedrock inference profiles).
    "sonnet": 200_000,
    "opus": 200_000,
    "haiku": 200_000,
    "claude": 200_000,
    "claude-sonnet": 200_000,
    "claude-opus": 200_000,
    "claude-haiku": 200_000,
    "us.anthropic.claude-sonnet-4-5-20250929-v1:0": 200_000,
    "us.anthropic.claude-opus-4-5-20250929-v1:0": 200_000,
    "anthropic": 200_000,
    "amazon-bedrock": 200_000,
    # Local Ollama models behind the rtx tunnel (64k-class windows).
    "qwen3": 65_000,
    "qwen": 65_000,
    "gpt-oss": 128_000,
    "deepseek": 128_000,
    "gemma": 128_000,
}


def parse_context_windows(raw: str) -> dict[str, int]:
    """Parse ``"model:tokens,model:tokens"`` into ``{model: tokens}``.

    Splits each entry on the LAST colon, so model tags with colons
    (``"qwen3.6:latest:100000"``) parse correctly. Raises ``ValueError``
    on any malformed entry (missing colon, empty model, non-integer or
    non-positive token count). Blank input yields {}.
    """
    result: dict[str, int] = {}
    if not raw.strip():
        return result
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" not in part:
            raise ValueError(f"Invalid context_windows entry (missing ':'): {part!r}")
        name, _, value = part.rpartition(":")
        name = name.strip()
        value = value.strip()
        if not name:
            raise ValueError(f"Invalid context_windows entry (empty model): {part!r}")
        try:
            tokens = int(value)
        except ValueError:
            raise ValueError(
                f"Invalid context_windows entry (tokens not an int): {part!r}"
            ) from None
        if tokens <= 0:
            raise ValueError(
                f"Invalid context_windows entry (tokens must be > 0): {part!r}"
            )
        result[name] = tokens
    return result


def _strip_provider(model: str) -> str:
    """Return the bare model id without a single leading ``<provider>/`` prefix."""
    model = model.strip()
    if "/" in model:
        return model.split("/", 1)[1]
    return model


def _family_match(
    stripped: str, table: dict[str, int]
) -> int | None:
    """Longest prefix-match of *stripped* against table keys (case-insensitive).

    Matches either direction — the table key is a prefix of the model
    (``muse-spark-1.3`` key vs ``muse-spark-1.3-contributor`` model) or the
    model is a prefix of the key — so family shorthands resolve both ways.
    """
    lowered = stripped.lower()
    best: int | None = None
    best_len = -1
    for key, tokens in table.items():
        k = key.lower()
        if lowered.startswith(k) or k.startswith(lowered):
            if len(k) > best_len:
                best = tokens
                best_len = len(k)
    return best


def resolve_window(
    model: str | None,
    overrides: dict[str, int] | None,
    coder_default: int,
) -> int:
    """Resolve the real context window for *model*.

    Lookup order: exact model id in overrides → id without provider prefix
    in overrides → family prefix match in overrides → same three steps in
    ``DEFAULT_WINDOWS`` → *coder_default*. ``None``/blank model returns
    *coder_default*.
    """
    if not model or not model.strip():
        return coder_default
    bare = _strip_provider(model)
    candidates = (model.strip(), bare)
    for table in (overrides or {}, DEFAULT_WINDOWS):
        if not table:
            continue
        for cand in candidates:
            for key, tokens in table.items():
                if cand == key or cand.lower() == key.lower():
                    return tokens
        for cand in candidates:
            hit = _family_match(cand, table)
            if hit is not None:
                return hit
    return coder_default
