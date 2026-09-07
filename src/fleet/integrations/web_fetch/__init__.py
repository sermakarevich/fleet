"""fleet.integrations.web_fetch — fetch a URL and distill it with the local model.

A dependency-free clone of Claude Code's WebFetch: ``fleet.integrations.web_fetch.server`` is
an MCP server whose ``web_fetch`` tool fetches a URL, strips it to text, and asks
the local ollama model to answer a prompt about the page — returning only the
distilled answer, not the raw HTML, so big pages never flood the caller's context.
"""

__version__ = "0.1.0"
