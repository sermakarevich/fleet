#!/usr/bin/env python3
"""Restart the fleet supervisor between beads of a self-modifying chain.

Every bead in the "Worker n/12" chain changes fleet's own code, and the
running supervisor keeps old code in memory. This watcher keeps the *next*
bead deferred (so the stale supervisor cannot claim it), and when the
current bead closes it restarts the supervisor and un-defers the next one.

State lives in beads only (status closed / deferred), so the script is
idempotent and can be restarted at any time. Logs to
~/.fleet/logging/chain_watcher.log. Stop with: kill $(cat ~/.fleet/chain_watcher.pid)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

CHAIN = [
    "fleet-l9i2m",  # 3/12 launch modes
    "fleet-ukh2r",  # 4/12 retry policy
    "fleet-ul4t5",  # 5/12 compaction
    "fleet-y4x9w",  # 5b/12 per-model context window
    "fleet-q16mb",  # 6/12 lease heartbeat
    "fleet-jojvk",  # 7/12 isolation
    "fleet-ml2s9",  # 8/12 mcp wiring
    "fleet-o5xr2",  # 9/12 triage
    "fleet-bdbk7",  # 10/12 gc
    "fleet-kc107",  # 11/12 observer
    "fleet-k7obx",  # 12/12 job
    "fleet-pltbj",  # 13/13 task dir artifacts (ADR 0004)
]
REPO = str(Path(__file__).resolve().parent.parent)
HOME = Path.home() / ".fleet"
LOG = HOME / "logging" / "chain_watcher.log"
PIDFILE = HOME / "chain_watcher.pid"
POLL_SEC = 30
# Bead lookups go straight to `bd` in the fleet home (where .beads lives) so a
# worker's half-edited fleet CLI cannot blind the watcher. Only the supervisor
# restart needs the fleet CLI itself.


def log(msg: str) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    with LOG.open("a", encoding="utf-8") as f:
        f.write(f"{ts} {msg}\n")


def run(*argv: str, timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, cwd=REPO)


def bd(*argv: str) -> subprocess.CompletedProcess:
    return subprocess.run(["bd", *argv], capture_output=True, text=True, timeout=60, cwd=HOME)


def bead(bead_id: str) -> dict:
    cp = bd("show", bead_id, "--json")
    if cp.returncode != 0:
        raise RuntimeError(f"bd show {bead_id}: {cp.stderr.strip()[:200]}")
    data = json.loads(cp.stdout)
    return data[0] if isinstance(data, list) else data


def defer(bead_id: str) -> None:
    cp = bd("update", bead_id, "--defer", "+3d")
    log(f"defer {bead_id}: rc={cp.returncode} {cp.stdout.strip()[:80]}{cp.stderr.strip()[:80]}")


def undefer(bead_id: str) -> None:
    cp = bd("update", bead_id, "--defer", "")
    log(f"undefer {bead_id}: rc={cp.returncode} {cp.stdout.strip()[:80]}{cp.stderr.strip()[:80]}")
    if bead(bead_id).get("status") == "deferred":
        cp = bd("update", bead_id, "--status", "open")
        log(f"force open {bead_id}: rc={cp.returncode}")


def restart_supervisor() -> bool:
    log("restarting supervisor (picks up new code)")
    cp = run("uv", "run", "fleet", "run", "restart", timeout=180)
    log(f"restart rc={cp.returncode} {cp.stdout.strip()[-160:]} {cp.stderr.strip()[-160:]}")
    for _ in range(12):
        time.sleep(5)
        st = run("uv", "run", "fleet", "run", "status")
        if "running" in st.stdout:
            log(f"supervisor up: {st.stdout.strip()[:120]}")
            return True
    log("supervisor did NOT come back; leaving next bead deferred")
    return False


def tick() -> bool:
    """One pass. Returns False when the chain is finished."""
    statuses = {b: bead(b).get("status") for b in CHAIN}
    pending = [b for b in CHAIN if statuses[b] != "closed"]
    if not pending:
        log("chain complete")
        return False
    cur = pending[0]
    nxt = pending[1] if len(pending) > 1 else None

    # Keep the bead after the current one parked so a stale supervisor cannot claim it.
    if nxt and statuses[nxt] == "open":
        defer(nxt)

    if statuses[cur] == "deferred":
        # The previous bead has closed; the supervisor has old code in memory.
        prev_idx = CHAIN.index(cur) - 1
        prev = CHAIN[prev_idx] if prev_idx >= 0 else None
        log(f"{prev} closed -> {cur} is next")
        if restart_supervisor():
            undefer(cur)
    elif statuses[cur] == "blocked":
        log(f"{cur} is BLOCKED; waiting for a human (unblock in UI)")
    return True


def main() -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    PIDFILE.write_text(str(os.getpid()))
    log(f"watcher started pid={os.getpid()} chain={' '.join(CHAIN)}")
    try:
        while True:
            try:
                if not tick():
                    break
            except Exception as exc:  # noqa: BLE001
                log(f"tick error: {exc!r}")
            time.sleep(POLL_SEC)
    finally:
        PIDFILE.unlink(missing_ok=True)
        log("watcher stopped")


if __name__ == "__main__":
    sys.exit(main())
