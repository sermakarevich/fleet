import types

from fleet.orchestrator.claim import cap_for_coder, parse_overrides, running_by_coder


def test_parse_overrides_empty() -> None:
    assert parse_overrides("") == {}


def test_parse_overrides_single() -> None:
    assert parse_overrides("claude:2") == {"claude": 2}


def test_parse_overrides_multiple_with_whitespace() -> None:
    assert parse_overrides("claude:2, opencode:4 , pi:1") == {
        "claude": 2,
        "opencode": 4,
        "pi": 1,
    }


def test_parse_overrides_malformed_entries() -> None:
    assert parse_overrides("claude,opencode:x,:3,foo:0,bar:-1") == {}


def test_cap_for_coder_with_override() -> None:
    assert cap_for_coder("claude", 3, "claude:2") == 2


def test_cap_for_coder_fallback() -> None:
    assert cap_for_coder("pi", 3, "claude:2") == 3


def test_running_by_coder_empty() -> None:
    assert running_by_coder([], "claude") == {}


def test_running_by_coder_counts_by_effective_coder() -> None:
    tasks = [
        types.SimpleNamespace(coder="claude"),
        types.SimpleNamespace(coder=None),
        types.SimpleNamespace(coder="opencode"),
        types.SimpleNamespace(coder=None),
        types.SimpleNamespace(coder="claude"),
    ]
    result = running_by_coder(tasks, "default_coder")
    assert result == {"claude": 2, "opencode": 1, "default_coder": 2}
