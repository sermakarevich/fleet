"""Non-interactive logic behind `fleet telegram setup`.

Polling/validation/config-writing live here; `cli/telegram.py` owns every
prompt, confirmation, and printed message.
"""

from __future__ import annotations

from pathlib import Path

from fleet.integrations.telegram.api import get_me, get_updates, send_message_raise
from fleet.state.config_file import write as write_config

DISCOVERY_ROUNDS = 8  # ~40s of polling at POLL_TIMEOUT_SEC per round
POLL_TIMEOUT_SEC = 5


def validate_token(token: str) -> dict:
    """Return bot info from Telegram's getMe. Raises on an invalid/unreachable token."""
    return get_me(token)


def discover_chats(token: str) -> tuple[list[dict], int | None]:
    """Poll getUpdates until at least one chat has posted a message.

    Returns (chats, next_offset). Each chat dict has id/type/title. Raises on
    a network/API error; returns ([], offset) if nothing arrived in time.
    """
    offset: int | None = None
    seen_chats: dict[str, dict] = {}
    for _ in range(DISCOVERY_ROUNDS):
        updates = get_updates(token, offset=offset, timeout=POLL_TIMEOUT_SEC)
        for upd in updates:
            uid = upd.get("update_id", 0)
            if offset is None or uid + 1 > offset:
                offset = uid + 1
            msg = upd.get("message") or {}
            chat = msg.get("chat") or {}
            cid = str(chat.get("id", ""))
            if cid and cid not in seen_chats:
                title = chat.get("title") or chat.get("username") or chat.get("first_name") or "?"
                seen_chats[cid] = {"id": cid, "type": chat.get("type", "?"), "title": title}
        if seen_chats:
            break
    return list(seen_chats.values()), offset


def discover_users(token: str, offset: int | None) -> tuple[dict[str, str], int | None]:
    """Poll getUpdates until at least one user has sent a message.

    Returns ({user_id: username}, next_offset).
    """
    seen_users: dict[str, str] = {}
    for _ in range(DISCOVERY_ROUNDS):
        updates = get_updates(token, offset=offset, timeout=POLL_TIMEOUT_SEC)
        for upd in updates:
            uid = upd.get("update_id", 0)
            if offset is None or uid + 1 > offset:
                offset = uid + 1
            msg = upd.get("message") or {}
            from_user = msg.get("from") or {}
            fid = str(from_user.get("id", ""))
            if fid and fid not in seen_users:
                seen_users[fid] = from_user.get("username") or from_user.get("first_name") or "?"
        if seen_users:
            break
    return seen_users, offset


def write_chat_id(path: Path, chat_id: str) -> None:
    write_config(path, {"telegram_chat_id": chat_id})


def write_inbound_config(path: Path, allowed_ids: str, default_cwd: str) -> None:
    write_config(
        path,
        {"telegram_allowed_ids": allowed_ids, "telegram_default_cwd": default_cwd},
    )


def send_test_message(token: str, chat_id: str, text: str = "fleet: telegram configured") -> None:
    send_message_raise(token, chat_id, text)
