"""Unit tests for fleet.integrations.ollama_tunnel (no network, no ssh).

The probe and the daemon spawn are patched: ``tunnel_is_up`` is stubbed
and ``start`` (imported into ``ollama_tunnel`` from
``observability/daemon``) is replaced with a fake, so no test ever opens
an SSH connection.
"""

from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import pytest

from fleet.core.config import RuntimeConfig
from fleet.integrations import ollama_tunnel as ot
from fleet.observability.daemon import StartResult


def _settings(**overrides) -> ot.TunnelSettings:
    base = {"local_url": "http://127.0.0.1:11435/v1"}
    return ot.TunnelSettings(**(base | overrides))


def _alive(*, already_running: bool = False) -> StartResult:
    return StartResult(pid=4242, already_running=already_running, alive=True)


def _dead() -> StartResult:
    return StartResult(pid=4242, already_running=False, alive=False)


def test_endpoint_parses_loopback_and_rejects_remote():
    assert ot.tunnel_endpoint("http://127.0.0.1:11435/v1") == ("127.0.0.1", 11435)
    assert ot.tunnel_endpoint("http://localhost:12345") == ("localhost", 12345)
    assert ot.tunnel_endpoint("http://127.0.0.1/v1") == ("127.0.0.1", 80)
    assert ot.tunnel_endpoint("https://127.0.0.1/v1") == ("127.0.0.1", 443)
    assert ot.tunnel_endpoint("http://rtx:11434/v1") is None
    assert ot.tunnel_endpoint("not-a-url") is None


def test_settings_from_config_defaults_keep_todays_values():
    settings = ot.TunnelSettings.from_config(RuntimeConfig())
    assert settings.local_url == "http://127.0.0.1:11435/v1"
    assert settings.ssh_host == "rtx"
    assert settings.remote_port == 11434


def test_settings_from_config_honors_declared_fields():
    config = RuntimeConfig(
        opencode_ollama_url="http://127.0.0.1:11436/v1",
        ollama_ssh_host="gpubox",
        ollama_remote_port=11435,
    )
    settings = ot.TunnelSettings.from_config(config)
    assert settings.local_url == "http://127.0.0.1:11436/v1"
    assert settings.ssh_host == "gpubox"
    assert settings.remote_port == 11435


def test_probe_derives_host_and_port_from_url(monkeypatch: pytest.MonkeyPatch):
    captured: list[str] = []

    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_urlopen(url, timeout=None):
        captured.append(url if isinstance(url, str) else url.full_url)
        return _Resp()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert ot.tunnel_is_up("http://127.0.0.1:11436/v1") is True
    assert captured == ["http://127.0.0.1:11436/api/tags"]


def test_probe_false_without_network(monkeypatch: pytest.MonkeyPatch):
    def fake_urlopen(url, timeout=None):
        raise OSError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    assert ot.tunnel_is_up("http://127.0.0.1:11435/v1") is False
    # A non-loopback URL never even probes: there is nothing to tunnel.
    assert ot.tunnel_is_up("http://rtx:11434/v1") is False


def test_ensure_skips_non_loopback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(
        ot, "start", lambda spec: (_ for _ in ()).throw(AssertionError("ssh must not start"))
    )
    res = ot.ensure_tunnel(_settings(local_url="http://rtx:11434/v1"), tmp_path)
    assert res.status == "skipped" and res.ok


def test_ensure_noop_when_already_up(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(ot, "tunnel_is_up", lambda url, timeout=2.0: True)
    monkeypatch.setattr(
        ot, "start", lambda spec: (_ for _ in ()).throw(AssertionError("ssh must not start"))
    )
    res = ot.ensure_tunnel(_settings(), tmp_path)
    assert res.status == "up" and res.local_port == 11435


def test_ensure_starts_daemon_when_down(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    probes = iter([False, True])  # down before ssh, up after
    monkeypatch.setattr(ot, "tunnel_is_up", lambda url, timeout=2.0: next(probes))
    seen: list = []
    monkeypatch.setattr(ot, "start", lambda spec: (seen.append(spec), _alive())[1])
    res = ot.ensure_tunnel(_settings(ssh_host="gpubox"), tmp_path)
    assert res.status == "started" and res.ok
    argv = seen[0].argv
    assert argv[0] == "ssh" and argv[-1] == "gpubox"
    assert "-N" in argv and "-f" not in argv
    assert "-L" in argv and argv[argv.index("-L") + 1] == "127.0.0.1:11435:127.0.0.1:11434"
    assert seen[0].pidfile == tmp_path / ".ollama_tunnel.pid"


def test_ensure_reports_dead_daemon(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(ot, "tunnel_is_up", lambda url, timeout=2.0: False)
    monkeypatch.setattr(ot, "start", lambda spec: _dead())
    res = ot.ensure_tunnel(_settings(), tmp_path)
    assert res.status == "failed" and not res.ok


def test_ensure_reports_missing_ssh(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(ot, "tunnel_is_up", lambda url, timeout=2.0: False)

    def no_ssh(spec):
        raise FileNotFoundError("ssh")

    monkeypatch.setattr(ot, "start", no_ssh)
    res = ot.ensure_tunnel(_settings(), tmp_path)
    assert res.status == "failed" and not res.ok
    assert "ssh binary not found" in res.detail


def test_ensure_reports_unanswered_forward(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(ot, "tunnel_is_up", lambda url, timeout=2.0: False)
    monkeypatch.setattr(ot, "start", lambda spec: _alive())
    settings = _settings(timeouts=ot.TunnelTimeouts(verify_s=0.0))
    res = ot.ensure_tunnel(settings, tmp_path)
    assert res.status == "failed" and not res.ok
    assert "did not answer" in res.detail


def test_ssh_argv_holds_forward_in_foreground():
    argv = ot.ssh_argv(11435, "gpubox")
    assert argv[:2] == ["ssh", "-N"]
    assert "-f" not in argv
    assert argv[-3:-1] == ["-L", "127.0.0.1:11435:127.0.0.1:11434"]
    assert argv[-1] == "gpubox"
    assert json.dumps(argv)  # argv stays JSON-serializable for the pidfile log
