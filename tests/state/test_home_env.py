from __future__ import annotations

from pathlib import Path

from fleet.state.home_env import load_home_env, parse_env_file


def test_parse_env_file_handles_export_quotes_and_comments() -> None:
    text = (
        "# comment\n\nexport A=1\nB='two words'\nC=\"q\"\nD=plain # trailing comment\nnot a line\n"
    )
    assert parse_env_file(text) == {"A": "1", "B": "two words", "C": "q", "D": "plain"}


def test_load_home_env_adds_missing_keys_only(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("export TYPESAFE_API_KEY=k1\nexport PATH=/bad\n")
    environ = {"PATH": "/keep"}

    added = load_home_env(env_file, environ)

    assert added == ["TYPESAFE_API_KEY"]
    assert environ == {"PATH": "/keep", "TYPESAFE_API_KEY": "k1"}


def test_load_home_env_missing_file_is_noop(tmp_path: Path) -> None:
    environ: dict[str, str] = {}
    assert load_home_env(tmp_path / "absent", environ) == []
    assert environ == {}
