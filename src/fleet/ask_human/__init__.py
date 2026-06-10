"""fleet.ask_human — human-in-the-loop question broker (vendored).

An MCP server (``fleet.ask_human.server``) lets headless agents ask a human and
block for the answer; the operator console (``fleet.ask_human.cli``, exposed as
``fleet ask-human``) and web dashboard (``fleet.ask_human.web``) answer them,
all over one shared SQLite store (``fleet.ask_human.store``).

Vendored from the standalone ``agent-chat`` project (~/git/claude/mcp/ask_human)
so fleet is self-contained; the original remains the upstream. Keep changes here
minimal and behavior-identical so the two stay easy to diff.

Related fleet-internal module: ``fleet.ask_human_db`` is the lightweight helper
the serve process (web chat + Telegram relay) uses to read and answer the same
DB; this package is the authoritative schema owner (it creates and migrates the
``questions`` table).
"""

__version__ = "0.2.0"
