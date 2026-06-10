#!/usr/bin/env python3
"""MCP server letting headless agents ask a human operator and block for the answer.

Subagents and Workflow agents cannot use Claude Code's ``AskUserQuestion`` tool
(it is filtered out at the system level). They *can* call MCP tools, and an MCP
tool is allowed to block until it returns. This server records each question in
a shared SQLite store (see ``store.py``) and blocks until a human answers it via
any operator frontend — the ``fleet ask-human`` CLI/TUI, the web dashboard, the
fleet web UI chat tab, or a Telegram reply — then returns the answer to the
calling agent.

The wait is asynchronous and open-ended: a question blocks *indefinitely* until
a human answers — there is no timeout. To keep the MCP connection healthy across
arbitrarily long waits, the tool never blocks the event loop (it ``await``s
between store polls) and emits a periodic progress notification as a keepalive,
so the client won't time the request out and drop it.

Run standalone:  fleet ask-human serve   (or python -m fleet.ask_human.server;
stdio transport). Vendored from ~/git/claude/mcp/ask_human — keep
behavior-identical so the two stay easy to diff.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

from mcp.server.fastmcp import Context, FastMCP

from .store import QuestionStore

store = QuestionStore()

# How often to poll the store, and how often to emit a keepalive progress
# notification while a question is still pending. The keepalive doubles as a
# liveness signal and resets the client's request timeout, so an open-ended
# wait is never dropped.
_POLL_INTERVAL_S = 1.0
_KEEPALIVE_S = 20.0

mcp = FastMCP(
    "ask_human",
    instructions=(
        "Reach a human operator for decisions you cannot make on your own. Call "
        "`ask_human_question` whenever you need human judgment, approval, or missing "
        "information to proceed instead of guessing — it records the question and "
        "BLOCKS until a person answers from a separate operator console, then returns "
        "their answer. The wait is open-ended (no timeout): it blocks until a "
        "human responds. Pass `options` for a multiple-choice decision, or omit "
        "them for free-text input. The operator can ALWAYS add a free-text `note` "
        "alongside (or instead of) the options — so always read the returned `note`: "
        "it may supplement the chosen `answer`, replace it (when `answer` is null/empty "
        "because none of your options fit), or tell you a premise of the question was "
        "wrong. Treat a `note` as the operator's authoritative correction."
    ),
)


def _result(q: dict) -> dict[str, Any]:
    """Project a stored question down to what the calling agent needs."""
    return {
        "id": q["id"],
        "status": q["status"],          # answered | expired | cancelled
        "answer": q["answer"],          # str, list[str] (multi_select), or None
        "note": q.get("note"),          # operator's free-text note/correction, or None
        "answered_by": q.get("answered_by"),
    }


async def _await_answer(
    store: QuestionStore,
    qid: str,
    ctx: Optional[Context] = None,
    poll_interval: float = _POLL_INTERVAL_S,
    keepalive_s: float = _KEEPALIVE_S,
) -> dict:
    """Wait until ``qid`` resolves, without ever blocking the event loop.

    Unlike ``QuestionStore.wait`` (synchronous — fine for the standalone CLI),
    this is for the async MCP server: it ``await``s between quick store polls so
    the server keeps servicing the MCP protocol during long waits, and emits a
    progress notification every ``keepalive_s`` seconds as a liveness signal /
    request-timeout reset. Honors the question's ``timeout_s`` (expiring to its
    ``default`` on timeout); with ``timeout_s=None`` it waits indefinitely.
    """
    q = store.get(qid)
    if q is None:
        raise KeyError(qid)
    deadline = (q["created_at"] + q["timeout_s"]) if q["timeout_s"] else None
    waited = 0.0
    since_keepalive = 0.0
    while q["status"] == "pending":
        if deadline is not None and time.time() >= deadline:
            store._expire_if_pending(qid)
            return store.get(qid)
        await asyncio.sleep(poll_interval)
        waited += poll_interval
        since_keepalive += poll_interval
        if ctx is not None and since_keepalive >= keepalive_s:
            since_keepalive = 0.0
            try:
                await ctx.report_progress(
                    progress=waited,
                    total=None,
                    message="waiting for a human operator…",
                )
            except Exception:
                pass  # keepalive is best-effort; never fail the wait over it
        q = store.get(qid)
    return q


@mcp.tool()
async def ask_human_question(
    prompt: str,
    options: Optional[list[str]] = None,
    multi_select: bool = False,
    agent_id: Optional[str] = None,
    session_id: Optional[str] = None,
    priority: int = 0,
    ctx: Optional[Context] = None,
) -> dict[str, Any]:
    """Ask the human operator a question and BLOCK until they answer.

    The wait is open-ended: the call blocks until a human responds — there is no
    timeout. The connection is kept alive across long waits (a periodic progress
    ping resets the client's request timeout), so blocking for minutes or hours
    is safe.

    Args:
        prompt: The question to show the operator.
        options: Optional list of choices. Omit for a free-text answer. Even when
            you pass options, the operator can still reply with free text (a
            `note`) instead of — or in addition to — picking one, so phrase the
            prompt so a written correction is meaningful.
        multi_select: If true, the operator may pick several options.
        agent_id: Label for who is asking (e.g. the subagent/task label) so the
            operator can tell concurrent questions apart.
        session_id: Optional grouping key (e.g. the workflow run id).
        priority: Higher numbers surface first in the operator's queue.

    Returns:
        {"id", "status", "answer", "note", "answered_by"}. `status` is "answered"
        or "cancelled". `answer` is the selected option(s) (or the typed text for
        a free-text question), and is null/empty when the operator only left a
        `note`. ALWAYS read `note`: it is the operator's free-text message and may
        add context to, override, or correct the `answer` (e.g. "none of these —
        do X" or "your premise is wrong"). When `note` is present, treat it as the
        operator's authoritative intent.
    """
    qid = store.create(
        prompt=prompt,
        options=options,
        multi_select=multi_select,
        agent_id=agent_id,
        session_id=session_id,
        priority=priority,
    )
    return _result(await _await_answer(store, qid, ctx))


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
