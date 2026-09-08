"""Tests for core.process.pid_alive (moved from test_daemon.py)."""

from __future__ import annotations

import os
import subprocess
import sys

from fleet.core.process import pid_alive


def test_pid_alive_true_for_self() -> None:
    assert pid_alive(os.getpid()) is True


def test_pid_alive_false_for_reaped_child() -> None:
    proc = subprocess.Popen([sys.executable, "-c", ""])
    proc.wait()  # reap so the PID is fully gone
    assert pid_alive(proc.pid) is False


def test_pid_alive_false_for_nonpositive() -> None:
    assert pid_alive(0) is False
    assert pid_alive(-1) is False


def test_pid_alive_false_for_non_int() -> None:
    assert pid_alive("123") is False
    assert pid_alive(None) is False
    assert pid_alive(True) is False
