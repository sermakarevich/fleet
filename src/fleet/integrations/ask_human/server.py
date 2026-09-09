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
arbitrarily long waits, the shared blocking wait (``store.wait_for_answer``)
runs in a worker thread while the event loop emits a periodic progress
notification as a keepalive, so the client won't time the request out and
drop it.

Run standalone:  fleet ask-human serve   (or python -m fleet.integrations.ask_human.server;
stdio transport). Vendored from ~/git/claude/mcp/ask_human — keep
behavior-identical so the two stay easy to diff.
"""

from __future__ import annotations

import asyncio
import os
from os.path import basename
from typing import Any

import structlog
from mcp.server.fastmcp import Context, FastMCP

from .store import Question, QuestionStore, wait_for_answer

_log = structlog.get_logger(__name__)

# How often the shared wait polls the store, and how often to emit a
# keepalive progress notification while a question is still pending. The
# keepalive doubles as a liveness signal and resets the client's request
# timeout, so an open-ended wait is never dropped.
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


class _StoreBox:
    """Named owner of the process-wide question store (built once, in ``main``)."""

    store: QuestionStore | None = None


def build_store() -> QuestionStore:
    """Question store for this server process.

    The MCP child inherits ``ASK_HUMAN_DB`` from ``fleet_mcp_servers``;
    without it (manual runs) ``QuestionStore`` falls back to the FLEET_HOME
    database. Built here and in ``main()``, never at import time.
    """
    return QuestionStore()


def get_store() -> QuestionStore:
    """Process-wide store, built on first use (``main()`` builds it eagerly)."""
    if _StoreBox.store is None:
        _StoreBox.store = build_store()
    return _StoreBox.store


def _result(question: Question) -> dict[str, Any]:
    """Project a stored question down to what the calling agent needs."""
    return {
        "id": question["id"],
        "status": question["status"],  # answered | expired | cancelled
        "answer": question["answer"],  # str, list[str] (multi_select), or None
        "note": question.get("note"),  # operator's free-text note/correction, or None
        "answered_by": question.get("answered_by"),
    }


def _default_agent_id() -> str | None:
    """Derive a task-id agent_id from the FLEET_TASK_DIR env var when none is passed."""
    task_dir = os.environ.get("FLEET_TASK_DIR")
    if task_dir:
        # Extract task id from path like /.../.fleet/tasks/fleet-xxxx
        name = basename(task_dir)
        if name:
            return name
    return None


async def _await_answer(
    store: QuestionStore,
    qid: str,
    ctx: Context | None = None,
    poll_interval: float = _POLL_INTERVAL_S,
    keepalive_s: float = _KEEPALIVE_S,
) -> Question:
    """Wait until ``qid`` resolves, without ever blocking the event loop.

    The shared ``wait_for_answer`` runs in a worker thread (same
    implementation as the synchronous ``QuestionStore.wait``); this
    coroutine only waits on it in ``keepalive_s`` slices so it can emit a
    progress notification as a liveness signal / request-timeout reset.
    Honors the question's ``timeout_s`` (expiring to its ``default`` on
    timeout); with ``timeout_s=None`` it waits indefinitely.
    """
    waiter = asyncio.create_task(
        asyncio.to_thread(wait_for_answer, store, qid, poll_interval=poll_interval)
    )
    waited = 0.0
    try:
        while not waiter.done():
            done, _pending = await asyncio.wait({waiter}, timeout=keepalive_s)
            if done:
                break
            waited += keepalive_s
            if ctx is not None:
                try:
                    await ctx.report_progress(
                        progress=waited,
                        total=None,
                        message="waiting for a human operator…",
                    )
                except Exception as exc:
                    _log.debug("ask_human keepalive failed", error=str(exc))
        return waiter.result()
    finally:
        if not waiter.done():
            waiter.cancel()


@mcp.tool()
async def ask_human_question(
    prompt: str,
    options: list[str] | None = None,
    multi_select: bool = False,
    agent_id: str | None = None,
    session_id: str | None = None,
    priority: int = 0,
    ctx: Context | None = None,
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
    # Default agent_id from FLEET_TASK_DIR env var when none is passed,
    # so the operator always sees attribution (env default > none).
    effective_agent_id = agent_id or _default_agent_id()

    store = get_store()
    qid = store.create(
        prompt=prompt,
        options=options,
        multi_select=multi_select,
        agent_id=effective_agent_id,
        session_id=session_id,
        priority=priority,
    )
    return _result(await _await_answer(store, qid, ctx))


def main() -> None:
    get_store()
    mcp.run()


if __name__ == "__main__":
    main()
