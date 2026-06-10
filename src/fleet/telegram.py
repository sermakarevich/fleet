from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import structlog

from fleet.ask_human_db import answer_question, count_pending, fetch_pending_questions, get_question

_MAX_TEXT = 4096
_GETUPDATE_TIMEOUT = 30  # seconds for Telegram long-poll
_BACKOFF_MAX = 60
_ALLOWED_IDS_POLL_INTERVAL = 10  # sleep interval when allowlist is empty
_log = structlog.get_logger(__name__)


def is_configured() -> bool:
    """Return True if TELEGRAM_BOT_TOKEN env var is set and non-empty."""
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN"))


def get_me(token: str) -> dict:
    """Call Telegram getMe synchronously; return bot info dict. Raises RuntimeError on failure."""
    url = f"https://api.telegram.org/bot{token}/getMe"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
            raise RuntimeError(body.get("description", str(exc))) from exc
        except (json.JSONDecodeError, AttributeError):
            raise RuntimeError(str(exc)) from exc
    if not data.get("ok"):
        raise RuntimeError(data.get("description", "getMe failed"))
    return data.get("result", {})


def get_updates(token: str, offset: int | None = None, timeout: int = 5) -> list[dict]:
    """Blocking call to getUpdates; raises on network/API error."""
    params: dict[str, Any] = {"timeout": timeout, "allowed_updates": ["message"]}
    if offset is not None:
        params["offset"] = offset
    url = (
        f"https://api.telegram.org/bot{token}/getUpdates"
        f"?{urllib.parse.urlencode(params)}"
    )
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout + 10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
            raise RuntimeError(body.get("description", str(exc))) from exc
        except (json.JSONDecodeError, AttributeError):
            raise RuntimeError(str(exc)) from exc
    if not data.get("ok"):
        raise RuntimeError(f"getUpdates returned not-ok: {data.get('description', data)}")
    return data.get("result", [])


def send_message_raise(token: str, chat_id: str, text: str) -> None:
    """Send a Telegram message synchronously; raise RuntimeError with API description on failure."""
    text = text[:_MAX_TEXT]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": text}).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8"))
            raise RuntimeError(body.get("description", str(exc))) from exc
        except (json.JSONDecodeError, AttributeError):
            raise RuntimeError(str(exc)) from exc
    if not data.get("ok"):
        raise RuntimeError(data.get("description", "sendMessage failed"))


async def send_message(token: str, chat_id: str, text: str) -> None:
    """POST text to Telegram sendMessage; fire-and-forget, never raises."""
    text = text[:_MAX_TEXT]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": text}).encode()

    def _post() -> None:
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp.read()

    try:
        await asyncio.to_thread(_post)
    except Exception as exc:
        _log.error("telegram.send_message failed", error=str(exc))


async def send_message_with_id(token: str, chat_id: str, text: str) -> int | None:
    """POST text to Telegram sendMessage; return message_id on success, None on any failure."""
    text = text[:_MAX_TEXT]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": text}).encode()

    def _post() -> int | None:
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            _log.error("telegram.send_message_with_id failed", error=str(exc))
            return None
        if not data.get("ok"):
            _log.error("telegram.send_message_with_id not ok", description=data.get("description"))
            return None
        result = data.get("result") or {}
        mid = result.get("message_id")
        try:
            return int(mid) if mid is not None else None
        except (TypeError, ValueError):
            return None

    try:
        return await asyncio.to_thread(_post)
    except Exception as exc:
        _log.error("telegram.send_message_with_id failed", error=str(exc))
        return None


_QUESTION_MSG_CAP = 200


def record_question_message(path: Path, message_id: int, question_id: str) -> None:
    """Persist message_id -> question_id; insertion-ordered, capped at 200 entries."""
    try:
        try:
            raw = path.read_text(encoding="utf-8")
            mapping: dict = json.loads(raw)
            if not isinstance(mapping, dict):
                mapping = {}
        except (OSError, json.JSONDecodeError, ValueError):
            mapping = {}

        mapping[str(message_id)] = question_id

        if len(mapping) > _QUESTION_MSG_CAP:
            keys = list(mapping.keys())
            for k in keys[: len(mapping) - _QUESTION_MSG_CAP]:
                del mapping[k]

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(mapping), encoding="utf-8")
    except OSError as exc:
        _log.warning("telegram.record_question_message failed", error=str(exc))


def lookup_question_for_message(path: Path, message_id: int) -> str | None:
    """Return question_id for message_id, or None if not found or file missing."""
    try:
        raw = path.read_text(encoding="utf-8")
        mapping = json.loads(raw)
        if isinstance(mapping, dict):
            return mapping.get(str(message_id))
        return None
    except (OSError, json.JSONDecodeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Inbound listener helpers
# ---------------------------------------------------------------------------


def _parse_allowed_ids(raw: str) -> set[str]:
    """Parse comma-separated ID string into a set of stripped strings."""
    return {s.strip() for s in raw.split(",") if s.strip()}


def _is_allowed(update: dict, allowed: set[str]) -> bool:
    """Return True if the update's from-user id OR chat id appears in allowed."""
    msg = update.get("message") or {}
    from_id = str((msg.get("from") or {}).get("id", ""))
    chat_id = str((msg.get("chat") or {}).get("id", ""))
    return (bool(from_id) and from_id in allowed) or (bool(chat_id) and chat_id in allowed)


def _parse_task_command(text: str) -> tuple[str, str | None] | None:
    """Parse a /task command; return (title, description) or None if not a /task message."""
    text = text.strip()
    if not text.startswith("/task"):
        return None
    remainder = text[len("/task"):]
    # Allow /task@botname variant
    if remainder and remainder[0] == "@":
        space = remainder.find(" ")
        newline = remainder.find("\n")
        candidates = [i for i in (space, newline) if i != -1]
        if not candidates:
            return None
        remainder = remainder[min(candidates):]
    elif remainder and remainder[0] not in (" ", "\n", "\r", "\t"):
        return None
    remainder = remainder.lstrip(" \t")
    lines = remainder.splitlines()
    if not lines or not lines[0].strip():
        return None
    title = lines[0].strip()
    desc_lines = [ln for ln in lines[1:] if ln.strip()]
    description = "\n".join(desc_lines) if desc_lines else None
    return title, description


def _load_offset(offset_path: Path) -> int | None:
    """Load persisted update_id offset; return None if absent or invalid."""
    try:
        return int(offset_path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _save_offset(offset_path: Path, offset: int) -> None:
    """Persist update_id offset; swallow errors so a bad FS never kills the loop."""
    try:
        offset_path.parent.mkdir(parents=True, exist_ok=True)
        offset_path.write_text(str(offset), encoding="utf-8")
    except OSError as exc:
        _log.warning("telegram.save_offset failed", error=str(exc))


def _fetch_updates(token: str, offset: int | None) -> list[dict]:
    return get_updates(token, offset=offset, timeout=_GETUPDATE_TIMEOUT)


async def _handle_answer(token: str, chat_id: str, qid: str, raw_text: str) -> None:
    """Apply numeric option shortcut, call answer_question, and send reply."""
    answer: object = raw_text.strip()
    q: dict | None = None
    try:
        idx = int(str(answer))
        q = await asyncio.to_thread(get_question, qid)
        opts = (q or {}).get("options") or []
        if opts and 1 <= idx <= len(opts):
            answer = opts[idx - 1]
    except ValueError:
        pass

    result = await asyncio.to_thread(answer_question, qid, answer, "telegram")
    if result["ok"]:
        if q is None:
            q = await asyncio.to_thread(get_question, qid)
        label = (q or {}).get("agent_id") or qid
        await send_message(token, chat_id, f"Answered [{label}]")
    elif result["status"] in ("answered", "conflict"):
        await send_message(token, chat_id, "Question already answered")
    else:
        await send_message(token, chat_id, "Unknown or expired question")


async def inbound_listener(app: Any, offset_path: Path, qmsg_path: Path | None = None) -> None:
    """Long-poll Telegram getUpdates; create tasks and answer ask_human questions.

    Security: if telegram_allowed_ids is empty the loop polls nothing.
    Runs until cancelled; catches all errors with exponential backoff.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        _log.debug("telegram.inbound_listener: no token, listener inactive")
        return

    offset: int | None = _load_offset(offset_path)
    backoff: float = 1.0

    while True:
        try:
            cfg = app.state.fleet_state.config
            allowed = _parse_allowed_ids(cfg.telegram_allowed_ids)
            if not allowed:
                # Default-deny: no allowlist → sleep and re-check config
                await asyncio.sleep(_ALLOWED_IDS_POLL_INTERVAL)
                continue

            updates = await asyncio.to_thread(_fetch_updates, token, offset)
            backoff = 1.0  # reset backoff on success

            for update in updates:
                update_id: int = update.get("update_id", 0)
                next_offset = update_id + 1

                if not _is_allowed(update, allowed):
                    msg = update.get("message") or {}
                    from_id = str((msg.get("from") or {}).get("id", "?"))
                    chat_id = str((msg.get("chat") or {}).get("id", "?"))
                    _log.warning(
                        "telegram.inbound: rejected sender",
                        from_id=from_id,
                        chat_id=chat_id,
                    )
                    if offset is None or next_offset > offset:
                        offset = next_offset
                        _save_offset(offset_path, offset)
                    continue

                msg = update.get("message") or {}
                text = msg.get("text") or ""
                chat_id = str((msg.get("chat") or {}).get("id", ""))

                parsed = _parse_task_command(text)
                if parsed is not None:
                    title, description = parsed
                    default_cwd = cfg.telegram_default_cwd or None
                    try:
                        task = await asyncio.to_thread(
                            app.state.queue.create_task,
                            title,
                            description,
                            None,
                            None,
                            default_cwd,
                        )
                        reply = f"Created task {task.id}: {task.title}"
                        _log.info("telegram.inbound: created task", task_id=task.id, title=task.title)
                    except Exception as exc:
                        reply = f"Error creating task: {exc}"
                        _log.error("telegram.inbound: create_task failed", error=str(exc))
                    if chat_id:
                        await send_message(token, chat_id, reply)
                elif text.strip().startswith("/task"):
                    if chat_id:
                        await send_message(
                            token,
                            chat_id,
                            "Usage: /task <title>\n[optional description lines]",
                        )
                else:
                    reply_to = msg.get("reply_to_message")
                    if reply_to is not None:
                        replied_mid = reply_to.get("message_id") or 0
                        qid = (
                            lookup_question_for_message(qmsg_path, replied_mid)
                            if qmsg_path is not None
                            else None
                        )
                        if qid and chat_id:
                            await _handle_answer(token, chat_id, qid, text)
                        elif chat_id:
                            await send_message(token, chat_id, "Unknown or expired question")
                    elif text and not text.strip().startswith("/"):
                        pending = await asyncio.to_thread(count_pending)
                        if pending == 1:
                            qs = await asyncio.to_thread(fetch_pending_questions, 1)
                            if qs and chat_id:
                                await _handle_answer(token, chat_id, qs[0]["id"], text)
                        elif pending > 1 and chat_id:
                            await send_message(
                                token,
                                chat_id,
                                f"{pending} questions pending - reply directly to the specific question message to answer it",
                            )

                if offset is None or next_offset > offset:
                    offset = next_offset
                    _save_offset(offset_path, offset)

        except asyncio.CancelledError:
            raise
        except Exception:
            _log.exception("telegram.inbound: error, backing off", backoff=backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _BACKOFF_MAX)
