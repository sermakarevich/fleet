_EXACT_KEYS = frozenset(
    {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "OPENAI_API_KEY", "GEMINI_API_KEY"}
)
_SUBSTRING_KEYS = ("password", "secret")


def _is_credential_key(key: str) -> bool:
    if key in _EXACT_KEYS:
        return True
    lower = key.lower()
    if any(s in lower for s in _SUBSTRING_KEYS):
        return True
    # Singular "token" is a credential (auth_token, access_token, …).
    # Plural "tokens" is an LLM usage count (input_tokens, output_tokens,
    # cache_creation_input_tokens, …) and must not be redacted.
    if "token" in lower and "tokens" not in lower:
        return True
    return False


def redact(payload: dict) -> dict:
    """Return a new dict with credential keys replaced by '<redacted>'."""
    result = {}
    for k, v in payload.items():
        if _is_credential_key(k):
            result[k] = "<redacted>"
        elif isinstance(v, dict):
            result[k] = redact(v)
        else:
            result[k] = v
    return result
