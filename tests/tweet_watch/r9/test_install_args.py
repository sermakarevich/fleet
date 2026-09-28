"""R9 install arguments (F1-F6): the exact create spec, pinned byte for byte.

A schedule installed with a variant name, cron, overlap policy, coder, or
shell-mangled cron is an install bug: delete it and recreate exactly.
"""

from __future__ import annotations

import shutil

from fleet.schedules.cron import CronError, parse
from fleet.schedules.model import OverlapPolicy

from .conftest import (
    EXPECTED_CREATE,
    REPO_ROOT,
    SCHEDULE_CODER,
    SCHEDULE_CRON,
    SCHEDULE_NAME,
    SCHEDULE_OVERLAP,
)


def test_install_names_exact_schedule_name(make_schedule) -> None:
    assert make_schedule().name == SCHEDULE_NAME == "tweet-watch"


def test_variant_name_is_a_mismatch(make_schedule) -> None:
    for bad in ("tweet_watch", "tweetwatch", "tweet-watch-v2"):
        assert make_schedule(name=bad).name != SCHEDULE_NAME


def test_install_uses_exact_cron(make_schedule) -> None:
    assert make_schedule().cron == SCHEDULE_CRON == "*/30 * * * *"


def test_cron_has_five_fields() -> None:
    assert len(SCHEDULE_CRON.split()) == 5


def test_expected_cron_parses() -> None:
    assert parse(SCHEDULE_CRON) is not None


def test_wrong_cron_is_a_mismatch(make_schedule) -> None:
    for bad in ("* * * * *", "0 * * * *", "*/30 * * *"):
        assert make_schedule(cron=bad).cron != SCHEDULE_CRON


def test_truncated_cron_is_rejected_by_parser() -> None:
    try:
        parse("*/30 * * *")
    except CronError:
        return
    raise AssertionError("truncated cron must not parse")


def test_install_uses_overlap_skip(make_schedule) -> None:
    assert make_schedule().overlap == SCHEDULE_OVERLAP == OverlapPolicy.skip


def test_missing_or_queue_overlap_is_a_mismatch(make_schedule) -> None:
    assert make_schedule(overlap=OverlapPolicy.queue).overlap != OverlapPolicy.skip


def test_install_uses_opencode_coder(make_schedule) -> None:
    assert make_schedule().coder == SCHEDULE_CODER == "opencode"


def test_wrong_coder_is_a_mismatch(make_schedule) -> None:
    for bad in (None, "other-coder"):
        assert make_schedule(coder=bad).coder != SCHEDULE_CODER


def test_create_command_quotes_cron_with_single_quotes() -> None:
    assert "--cron '*/30 * * * *'" in EXPECTED_CREATE


def test_create_command_pins_every_flag() -> None:
    assert EXPECTED_CREATE.startswith("fleet schedule create ")
    assert "--name tweet-watch" in EXPECTED_CREATE
    assert "--overlap skip" in EXPECTED_CREATE
    assert "--coder opencode" in EXPECTED_CREATE


def test_fleet_cli_is_the_install_path() -> None:
    assert shutil.which("fleet") is not None, "fleet CLI missing: hard stop, name it"


def test_schedule_cwd_is_the_fleet_repo_checkout(make_schedule) -> None:
    assert make_schedule().cwd == REPO_ROOT
    assert make_schedule(cwd="/tmp/other").cwd != REPO_ROOT
