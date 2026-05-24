#!/usr/bin/env python3
"""Fake Claude CLI for integration tests.

Controlled via env vars:
  FAKE_CLAUDE_SCENARIO  — one of the scenarios below (default: clean_exit)
  FAKE_CLAUDE_USAGE_PCT — float, used by rate_limit_info scenario
  FAKE_CLAUDE_RESETS_AT — epoch seconds, used by rate_limit scenarios
  FAKE_CLAUDE_SLEEP_SEC — float, used by slow/slow_ignore_sigterm
  FAKE_CLAUDE_BD_ROOT   — path passed as cwd to bd subcommands
  FLEET_TASK_ID         — inherited from supervisor (used by bd scenarios)
  FLEET_TASK_DIR        — inherited from supervisor (task root)
  FLEET_ARTIFACT_DIR    — inherited from supervisor (task_dir/artifacts)

Scenarios:
  clean_exit           emit init + result, exit 0
  rate_limit_info      emit init + rate_limit_event(usage_pct), result, exit 0
  rate_limit_rejected  emit init + 429 rejection, loop until SIGTERM
  context_pressure     emit init, touch task_dir/.context_pressure, result, exit 0
  crash                emit init, exit 1
  slow                 emit init, sleep FAKE_CLAUDE_SLEEP_SEC, result, exit 0
  slow_ignore_sigterm  same as slow but ignores SIGTERM (for SIGKILL test)
  block_via_bd         write Q&A.md Q block, bd update blocked, result, exit 0
  read_qa_and_close    verify A block in Q&A.md, bd close, result, exit 0
"""
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def emit(data: dict) -> None:
    print(json.dumps(data), flush=True)


def main() -> None:
    scenario = os.environ.get("FAKE_CLAUDE_SCENARIO", "clean_exit")
    task_id = os.environ.get("FLEET_TASK_ID", "unknown")
    task_dir = Path(os.environ.get("FLEET_TASK_DIR", "."))
    artifact_dir = Path(os.environ.get("FLEET_ARTIFACT_DIR", "."))
    bd_root = os.environ.get("FAKE_CLAUDE_BD_ROOT", ".")

    emit({"type": "system", "subtype": "init", "session_id": "fake"})

    if scenario == "clean_exit":
        emit({"type": "result", "session_id": "fake"})
        sys.exit(0)

    elif scenario == "record_cwd":
        # Write the subprocess cwd to a file given by FAKE_CLAUDE_CWD_FILE.
        out = os.environ.get("FAKE_CLAUDE_CWD_FILE")
        if out:
            Path(out).write_text(str(Path.cwd()), encoding="utf-8")
        emit({"type": "result", "session_id": "fake"})
        sys.exit(0)

    elif scenario == "rate_limit_info":
        usage_pct = float(os.environ.get("FAKE_CLAUDE_USAGE_PCT", "92"))
        resets_at = os.environ.get("FAKE_CLAUDE_RESETS_AT")
        info: dict = {"usage_pct": usage_pct, "rateLimitType": "five_hour"}
        if resets_at:
            info["resetsAt"] = int(resets_at)
        emit({"type": "rate_limit_event", "rate_limit_info": info})
        emit({"type": "result", "session_id": "fake"})
        sys.exit(0)

    elif scenario == "rate_limit_rejected":
        resets_at = os.environ.get("FAKE_CLAUDE_RESETS_AT")
        rejection: dict = {"api_error_status": 429}
        if resets_at:
            rejection["resetsAt"] = int(resets_at)
        emit(rejection)
        # Keep emitting until SIGTERM'd by the runner
        try:
            while True:
                time.sleep(0.05)
                emit({"type": "assistant", "message": {"content": []}})
        except (KeyboardInterrupt, BrokenPipeError):
            pass
        sys.exit(0)

    elif scenario == "context_pressure":
        task_dir.mkdir(parents=True, exist_ok=True)
        (task_dir / ".context_pressure").touch()
        emit({"type": "result", "session_id": "fake"})
        sys.exit(0)

    elif scenario == "crash":
        sys.exit(1)

    elif scenario == "slow":
        sleep_sec = float(os.environ.get("FAKE_CLAUDE_SLEEP_SEC", "5"))
        _stop = [False]

        def _sig(*_: object) -> None:
            _stop[0] = True

        signal.signal(signal.SIGTERM, _sig)
        deadline = time.monotonic() + sleep_sec
        while not _stop[0] and time.monotonic() < deadline:
            time.sleep(0.05)
        if not _stop[0]:
            emit({"type": "result", "session_id": "fake"})
        sys.exit(0)

    elif scenario == "slow_ignore_sigterm":
        # Used in shutdown stubborn-child sub-test; ignores SIGTERM, exits only on SIGKILL
        sleep_sec = float(os.environ.get("FAKE_CLAUDE_SLEEP_SEC", "5"))
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        time.sleep(sleep_sec)
        emit({"type": "result", "session_id": "fake"})
        sys.exit(0)

    elif scenario == "block_via_bd":
        artifact_dir.mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y-%m-%d %H:%M")
        qa_path = artifact_dir / "Q&A.md"
        with qa_path.open("a") as fh:
            fh.write(
                f"## Q: What is the magic number? — {ts}, fake_claude\n\n"
                "**Context:** Integration test for Q&A flow\n"
                "**Tried:** Nothing, this is a test\n"
                "**Need:** An answer from the human\n\n"
            )
        subprocess.run(
            ["bd", "update", task_id, "--status", "blocked",
             "--notes", "QUESTION: magic number?"],
            cwd=bd_root,
            check=False,
        )
        emit({"type": "result", "session_id": "fake"})
        sys.exit(0)

    elif scenario == "read_qa_and_close":
        qa_path = artifact_dir / "Q&A.md"
        if not qa_path.exists():
            print(f"ERROR: Q&A.md not found at {qa_path}", file=sys.stderr)
            sys.exit(1)
        if "## A:" not in qa_path.read_text():
            print("ERROR: expected ## A: block in Q&A.md", file=sys.stderr)
            sys.exit(1)
        subprocess.run(["bd", "close", task_id], cwd=bd_root, check=False)
        emit({"type": "result", "session_id": "fake"})
        sys.exit(0)

    else:
        print(f"Unknown scenario: {scenario!r}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
