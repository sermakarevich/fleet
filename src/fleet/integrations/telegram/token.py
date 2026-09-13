"""Resolve the Telegram bot token: env var, else `<fleet_home>/telegram_token`.

launchd-started daemons run with a bare environment, so `TELEGRAM_BOT_TOKEN`
set in an interactive shell never reaches them. The token file lets the
token survive a daemon restart without spreading the secret into the plist.
"""

from __future__ import annotations

import logging
import os
import stat
from pathlib import Path

from fleet.state import paths as state_paths

logger = logging.getLogger(__name__)

_warned_permissive: set[Path] = set()


def telegram_token(fleet_home: Path | None = None) -> str:
    """TELEGRAM_BOT_TOKEN env var, else stripped contents of telegram_token file, else ''."""
    env_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if env_token:
        return env_token
    home = fleet_home if fleet_home is not None else state_paths.fleet_home()
    token_path = home / "telegram_token"
    if not token_path.exists():
        return ""
    mode = stat.S_IMODE(token_path.stat().st_mode)
    if mode & 0o077 and token_path not in _warned_permissive:
        logger.warning(
            "%s is readable by group/other (mode %o); run `chmod 600 %s`.",
            token_path,
            mode,
            token_path,
        )
        _warned_permissive.add(token_path)
    return token_path.read_text().strip()
