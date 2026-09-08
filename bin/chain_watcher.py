#!/usr/bin/env python3
"""Restart the fleet supervisor between beads of a self-modifying chain.

Every bead in the "Worker n/12" chain changes fleet's own code, and the
running supervisor keeps old code in memory. This watcher keeps the *next*
bead deferred (so the stale supervisor cannot claim it), and when the
current bead closes it restarts the supervisor and un-defers the next one.

State lives in beads only (status closed / deferred), so the script is
idempotent and can be restarted at any time. Logs to
~/.fleet/logging/chain_watcher.log. Stop with: kill $(cat ~/.fleet/chain_watcher.pid)

The chain itself is read from ~/.fleet/chain.txt on every tick (falls back to
the built-in CHAIN list), so appending bead ids to that file extends a running
chain without a restart.
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
    "fleet-hldrt",  # Runner 1/5 foundation (ADR 0005)
    "fleet-wrtar",  # Runner 2/5 simple services
    "fleet-42936",  # Runner 3/5 claim/spawn/RunningWorker
    "fleet-t97gn",  # Runner 4/5 reap/stall/leases/triage
    "fleet-sh3hm",  # Runner 5/5 tests + docs
    # ADR 0006 codebase-wide clean-code program (serial, after the runner chain)
    "fleet-w2mc1",  # Clean 1/15 tooling: just check, strict ruff, mypy, CI
    "fleet-0yd8z",  # Clean 2/15 state owners: TaskMeta, AttemptJournal, RunRecord
    "fleet-6onqj",  # Clean 3/15 layer fixes + tests/test_layering.py
    "fleet-fmoxq",  # Clean 4/15 beads: Queue, claim, _FLAGS, BdClient
    "fleet-ropuo",  # Clean 5/15 core policy tables
    "fleet-c2kja",  # Clean 6/15 workers/session
    "fleet-7vhe4",  # Clean 7/15 coders + prompts/
    "fleet-hkmr2",  # Clean 8/15 workers job/observe
    "fleet-4j9xv",  # Clean 9/15 serve core
    "fleet-ksw0h",  # Clean 10/15 serve analytics metrics
    "fleet-zjq7z",  # Clean 11/15 integrations
    "fleet-mlb4c",  # Clean 12/15 cli
    "fleet-q9ijr",  # Clean 13/15 API models + generated UI types
    "fleet-l203y",  # Clean 14/15 UI structure + vitest/eslint
    "fleet-4jsuo",  # Clean 15/15 docs, ADR 0006 accepted
]
REPO = str(Path(__file__).resolve().parent.parent)
HOME = Path.home() / ".fleet"
CHAIN_FILE = HOME / "chain.txt"  # one bead id per line, "#" comments; re-read every tick
LOG = HOME / "logging" / "chain_watcher.log"
PIDFILE = HOME / "chain_watcher.pid"
POLL_SEC = 30
# Bead lookups go straight to `bd` in the fleet home (where .beads lives) so a
# worker's half-edited fleet CLI cannot blind the watcher. Only the supervisor
# restart needs the fleet CLI itself.


def load_chain() -> list[str]:
    """Bead ids in order: ~/.fleet/chain.txt when present, else the built-in CHAIN.

    Reading the file every tick means new beads can be appended to a running
    chain without restarting the watcher.
    """
    if not CHAIN_FILE.exists():
        return CHAIN
    ids = []
    for line in CHAIN_FILE.read_text(encoding="utf-8").splitlines():
        bead_id = line.split("#", 1)[0].strip()
        if bead_id:
            ids.append(bead_id)
    return ids or CHAIN


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
    chain = load_chain()
    statuses = {b: bead(b).get("status") for b in chain}
    pending = [b for b in chain if statuses[b] != "closed"]
    if not pending:
        # The last bead also changed fleet's code: restart once more so the
        # supervisor is not left running stale code after the chain ends.
        log("chain complete; final supervisor restart")
        restart_supervisor()
        return False
    cur = pending[0]
    nxt = pending[1] if len(pending) > 1 else None

    # Keep the bead after the current one parked so a stale supervisor cannot claim it.
    if nxt and statuses[nxt] == "open":
        defer(nxt)

    if statuses[cur] == "deferred":
        # The previous bead has closed; the supervisor has old code in memory.
        prev_idx = chain.index(cur) - 1
        prev = chain[prev_idx] if prev_idx >= 0 else None
        log(f"{prev} closed -> {cur} is next")
        if restart_supervisor():
            undefer(cur)
    elif statuses[cur] == "blocked":
        log(f"{cur} is BLOCKED; waiting for a human (unblock in UI)")
    return True


def main() -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    PIDFILE.write_text(str(os.getpid()))
    log(f"watcher started pid={os.getpid()} chain={' '.join(load_chain())}")
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
