"""fleet.integrations.ask_human — human-in-the-loop question broker (vendored).

An MCP server (``server``) lets headless agents ask a human and block for the
answer; the operator answers via the fleet web UI Chat tab or Telegram, using
the shared SQLite store (``store``), which is also where the serve process and
the Telegram bot read pending questions and write answers.

Vendored from the standalone ``agent-chat`` project (~/git/claude/mcp/ask_human)
so fleet is self-contained; the original remains the upstream. Keep changes here
minimal and behavior-identical so the two stay easy to diff.
"""

__version__ = "0.2.0"
