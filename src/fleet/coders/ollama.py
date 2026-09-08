"""Shared Ollama routing helpers for the opencode and pi coders.

The tunnel host/port constants live in ``integrations.ollama_tunnel``
(single owner); this module re-exports the default URL and the Bedrock AWS
env overlay so neither coder duplicates them. Called by
``coders/opencode.py`` and ``coders/pi.py``.
"""

from fleet.integrations.ollama_tunnel import DEFAULT_OLLAMA_URL

__all__ = ["DEFAULT_OLLAMA_URL", "ollama_env"]


def ollama_env(
    *,
    is_bedrock: bool,
    bedrock_profile: str = "",
    bedrock_region: str = "",
) -> dict[str, str]:
    """AWS env overlay for Bedrock-routed models; empty when routing to Ollama.

    Ollama needs no env (its URL travels in coder config); Bedrock needs the
    profile/region the operator configured.
    """
    if not is_bedrock:
        return {}
    env: dict[str, str] = {}
    if bedrock_profile:
        env["AWS_PROFILE"] = bedrock_profile
    if bedrock_region:
        env["AWS_REGION"] = bedrock_region
    return env
