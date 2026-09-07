"""Unit tests for fleet.ollama_tunnel (no network: probe and ssh are patched)."""

from __future__ import annotations

import subprocess

from fleet import ollama_tunnel as ot


def test_local_port_parses_loopback_and_rejects_remote():
    assert ot.local_port("http://127.0.0.1:11435/v1") == 11435
    assert ot.local_port("http://localhost:12345") == 12345
    assert ot.local_port("http://127.0.0.1/v1") == 80
    assert ot.local_port("http://rtx:11434/v1") is None


def test_ensure_skips_non_loopback(monkeypatch):
    monkeypatch.setattr(ot.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("ssh must not run")))
    res = ot.ensure_tunnel("http://rtx:11434/v1")
    assert res.status == "skipped" and res.ok


def test_ensure_noop_when_already_up(monkeypatch):
    monkeypatch.setattr(ot, "tunnel_is_up", lambda port, timeout=2.0: True)
    monkeypatch.setattr(ot.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("ssh must not run")))
    res = ot.ensure_tunnel("http://127.0.0.1:11435/v1")
    assert res.status == "up" and res.local_port == 11435


def test_ensure_starts_ssh_when_down(monkeypatch):
    probes = iter([False, True])  # down before ssh, up after
    monkeypatch.setattr(ot, "tunnel_is_up", lambda port, timeout=2.0: next(probes))
    calls: list[list[str]] = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(ot.subprocess, "run", fake_run)
    monkeypatch.setenv("FLEET_OLLAMA_SSH_HOST", "gpubox")
    res = ot.ensure_tunnel("http://127.0.0.1:11435/v1")
    assert res.status == "started" and res.ok
    argv = calls[0]
    assert argv[0] == "ssh" and argv[-1] == "gpubox"
    assert "-L" in argv and argv[argv.index("-L") + 1] == "127.0.0.1:11435:127.0.0.1:11434"
    assert "-f" in argv and "-N" in argv


def test_ensure_reports_ssh_failure(monkeypatch):
    monkeypatch.setattr(ot, "tunnel_is_up", lambda port, timeout=2.0: False)
    monkeypatch.setattr(
        ot.subprocess, "run",
        lambda argv, **k: subprocess.CompletedProcess(argv, 255, "", "Permission denied (publickey)"),
    )
    res = ot.ensure_tunnel("http://127.0.0.1:11435/v1")
    assert res.status == "failed" and not res.ok
    assert "Permission denied" in res.detail
