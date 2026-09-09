"""Shared Ollama routing URL for the opencode and pi coders.

The tunnel host/port constants live in ``integrations.ollama_tunnel``
(single owner); this module re-exports the default URL so neither coder
duplicates it. The Bedrock AWS env overlay used to live here as
``ollama_env``; it moved to ``coders/env.py::bedrock_env`` next to the
``FLEET_*`` pair. Called by ``coders/opencode.py`` and ``coders/pi.py``.
"""

from fleet.integrations.ollama_tunnel import DEFAULT_OLLAMA_URL

__all__ = ["DEFAULT_OLLAMA_URL"]
