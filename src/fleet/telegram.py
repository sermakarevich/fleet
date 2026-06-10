from __future__ import annotations

import asyncio
import json
import os
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import structlog

_MAX_TEXT = 4096
_GETUPDATE_TIMEOUT = 30  # seconds for Telegram long-poll
_BACKOFF_MAX = 60
_ALLOWED_IDS_POLL_INTERVAL = 10  # sleep interval when allowlist is empty
_log = structlog.get_logger(__name__)


def is_configured() -> bool:
    """Return True if TELEGRAM_BOT_TOKEN env var is set and non-empty."""
    return bool(os.environ.get("TELEGRAM_BOT_TOKEN"))


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
    """Blocking call to getUpdates; raises on network/API error."""
    params: dict[str, Any] = {"timeout": _GETUPDATE_TIMEOUT, "allowed_updates": ["message"]}
    if offset is not None:
        params["offset"] = offset
    url = (
        f"https://api.telegram.org/bot{token}/getUpdates"
        f"?{urllib.parse.urlencode(params)}"
    )
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=_GETUPDATE_TIMEOUT + 10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if not data.get("ok"):
        raise RuntimeError(f"getUpdates returned not-ok: {data}")
    return data.get("result", [])


async def inbound_listener(app: Any, offset_path: Path) -> None:
    """Long-poll Telegram getUpdates; create fleet tasks from /task commands.

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

                if offset is None or next_offset > offset:
                    offset = next_offset
                    _save_offset(offset_path, offset)

        except asyncio.CancelledError:
            raise
        except Exception:
            _log.exception("telegram.inbound: error, backing off", backoff=backoff)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _BACKOFF_MAX)
