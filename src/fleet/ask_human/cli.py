#!/usr/bin/env python3
"""Operator console for the ask_human question broker — ``fleet ask-human``.

Vendored from the standalone agent-chat project (~/git/claude/mcp/ask_human);
keep behavior-identical so the two stay easy to diff.

Reads pending questions from the shared SQLite store and writes answers back.
The MCP server (fleet.ask_human.server) blocks agents until an answer appears here.

  fleet ask-human watch                  auto-refreshing answer loop
  fleet ask-human list                   show pending questions
  fleet ask-human answer <id> <text>     answer one (id may be a prefix)
  fleet ask-human web [--addr H:P]       launch the web dashboard

Also runnable as ``python -m fleet.ask_human.cli <cmd>`` (argparse main below).
For multi-select questions pass comma-separated choices, e.g. `py,go`.

On a question that offered options you're never boxed into them: append
``| your note`` to reply in free text alongside (or instead of) a choice — e.g.
``proceed | but skip the backup`` to add context, or ``| none of these, do X``
to answer purely in prose / correct a wrong premise. The note is delivered to
the agent as the operator's authoritative reply.

Point at a non-default DB with the ASK_HUMAN_DB environment variable.
"""

from __future__ import annotations

import argparse
import select
import sys
import time

from .store import QuestionStore


def _fmt_age(created_at: float) -> str:
    secs = max(0, int(time.time() - created_at))
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs // 60}m"
    return f"{secs // 3600}h{(secs % 3600) // 60}m"


def _print_pending(pending: list[dict]) -> None:
    if not pending:
        print("  (no pending questions)")
        return
    for q in pending:
        opts = ""
        if q["options"]:
            kind = "multi" if q["multi_select"] else "one"
            opts = f"  [{kind}: {', '.join(q['options'])}]"
        who = q["agent_id"] or "?"
        prio = f" !{q['priority']}" if q["priority"] else ""
        print(f"  {q['id'][:8]}  {_fmt_age(q['created_at']):>5}  {who}{prio}")
        print(f"           {q['prompt']}{opts}")


def _split_note(question: dict, raw: str) -> tuple[str, str | None]:
    """Peel a trailing ``| note`` off the raw answer for an *options* question.

    The text after ``|`` becomes a free-text ``note`` — a correction or extra
    context that's always allowed, even when the question offered choices. The
    operator can also give *only* a note (``| use sqlite instead``) to override
    the options entirely. Free-text (no-options) questions are never split: their
    whole answer is prose that may legitimately contain ``|``.
    """
    if question["options"] and "|" in raw:
        ans, _, note = raw.partition("|")
        return ans.strip(), (note.strip() or None)
    return raw, None


def _coerce_answer(question: dict, raw: str):
    """Turn raw CLI text into the right answer shape for the question.

    Returns ``None`` for an empty/blank single answer so a note-only reply (or a
    stray blank line) doesn't get recorded as an empty-string answer.
    """
    if question["multi_select"]:
        return [p.strip() for p in raw.split(",") if p.strip()]
    return raw.strip() or None


def _answer(store: QuestionStore, prefix: str, raw: str, by: str = "cli") -> None:
    try:
        qid = store.resolve_id(prefix)
    except ValueError as exc:
        print(f"  ! {exc}")
        return
    if qid is None:
        print(f"  ! no question matching '{prefix}'")
        return
    question = store.get(qid)
    if question["status"] != "pending":
        print(f"  ! {qid[:8]} is already {question['status']}")
        return
    answer_raw, note = _split_note(question, raw)
    answer = _coerce_answer(question, answer_raw)
    if not answer and not note:
        print("  ! nothing to send — give an answer, or '| your note' to reply in free text")
        return
    if store.answer(qid, answer, note=note, answered_by=by):
        shown = f"{answer!r}" if answer not in (None, []) else "(note only)"
        if note:
            shown += f"  note: {note!r}"
        print(f"  ✓ answered {qid[:8]} -> {shown}")
    else:
        print(f"  ! {qid[:8]} was just resolved by someone else")


def cmd_list(store: QuestionStore, args: argparse.Namespace) -> None:
    _print_pending(store.list_pending())


def cmd_answer(store: QuestionStore, args: argparse.Namespace) -> None:
    _answer(store, args.id, " ".join(args.text))


def _line_ready(timeout: float) -> bool:
    """Wait up to ``timeout`` seconds for a full line to be ready on stdin.

    Returns True when a line is waiting (so the following ``readline`` won't
    block), or False on timeout — the cue to re-poll the store and surface any
    questions that arrived while we sat idle at the prompt. Where ``select``
    can't watch stdin (Windows, or stdin isn't a real file) we degrade to the
    old blocking behavior: no auto-refresh, but answering still works.
    """
    try:
        return bool(select.select([sys.stdin], [], [], timeout)[0])
    except (OSError, ValueError):
        return True


def cmd_watch(store: QuestionStore, args: argparse.Namespace) -> None:
    print("ask_human watch — '<id> <answer>' to answer (id optional when one is pending),")
    print("                  add '| note' to reply in free text / correct the question,")
    print("                  auto-refreshes as questions arrive; Enter to refresh, 'q' to quit.\n")
    interval = max(0.5, args.interval)
    last_sig = None
    redraw = True
    while True:
        pending = store.list_pending()
        sig = tuple(q["id"] for q in pending)
        if redraw or sig != last_sig:
            # A change that lands under an idle prompt needs a fresh line so the
            # refreshed list doesn't collide with the leftover "answer>" line.
            if not redraw:
                print()
            print(f"--- pending: {len(pending)} --- {time.strftime('%H:%M:%S')}")
            _print_pending(pending)
            print("answer> ", end="", flush=True)
            last_sig, redraw = sig, False

        if not _line_ready(interval):
            continue  # idle timeout: loop back and surface any new questions

        line = sys.stdin.readline()
        if not line:  # EOF (Ctrl-D)
            print()
            return
        redraw = True  # reprint the list + prompt after handling this line
        line = line.strip()
        if line in ("q", "quit", "exit"):
            return
        if line in ("", "r", "refresh"):
            continue
        parts = line.split(maxsplit=1)
        # When exactly one question is pending the id is optional: if the first
        # token isn't that question's id prefix, treat the whole line as the answer.
        if len(pending) == 1 and not pending[0]["id"].startswith(parts[0]):
            _answer(store, pending[0]["id"], line, by="watch")
            continue
        if len(parts) < 2:
            print("  usage: <id> <answer>   (or just the answer when one question is pending)")
            continue
        _answer(store, parts[0], parts[1], by="watch")


def cmd_web(store: QuestionStore, args: argparse.Namespace) -> None:
    from . import web

    web.serve(args.addr)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="fleet ask-human",
        description="fleet ask-human — operator console for the ask_human MCP broker",
    )
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("list", help="show pending questions")

    p_answer = sub.add_parser("answer", help="answer a pending question")
    p_answer.add_argument("id", help="question id (a unique prefix is enough)")
    p_answer.add_argument(
        "text",
        nargs="+",
        help="the answer (comma-separated for multi-select; add '| note' to reply in free text)",
    )

    p_watch = sub.add_parser("watch", help="auto-refreshing answer loop (the default)")
    p_watch.add_argument(
        "--interval",
        type=float,
        default=2.0,
        help="seconds between auto-refreshes while idle (default 2.0)",
    )

    p_web = sub.add_parser("web", help="launch the web dashboard")
    p_web.add_argument("--addr", default=None, help="host:port (default 127.0.0.1:8765)")

    args = parser.parse_args()
    store = QuestionStore()
    handlers = {
        "list": cmd_list,
        "answer": cmd_answer,
        "watch": cmd_watch,
        "web": cmd_web,
    }
    # Bare `agent-chat` (no subcommand) drops you straight into the watch console.
    if args.cmd is None:
        args.interval = 2.0
        cmd_watch(store, args)
        return
    handlers[args.cmd](store, args)


if __name__ == "__main__":
    main()
