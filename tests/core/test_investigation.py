"""Tests for the INVESTIGATION.md parser (core/investigation.py)."""

from fleet.core.investigation import HEADLINE_MAX_CHARS, parse_report


def test_heading_form_parses_all_sections():
    text = (
        "# Investigation: t1 — blocked\n"
        "\n"
        "## Root cause\n"
        "\n"
        "The worker was stopped by hand mid-edit.\n"
        "\n"
        "## Evidence\n"
        "\n"
        "- exit_code -15, empty stderr\n"
        "\n"
        "## Category\n"
        "\n"
        "needs-human-decision\n"
        "\n"
        "## Recommended action\n"
        "\n"
        "unblock-as-is\n"
        "\n"
        "## Confidence\n"
        "\n"
        "high\n"
    )
    report = parse_report(text)
    assert report.root_cause == "The worker was stopped by hand mid-edit."
    assert report.evidence == "- exit_code -15, empty stderr"
    assert report.category == "needs-human-decision"
    assert report.recommended_action == "unblock-as-is"
    assert report.confidence == "high"
    assert not report.is_empty
    assert report.raw == text


def test_heading_match_is_case_insensitive_and_colon_tolerant():
    report = parse_report("## ROOT CAUSE:\n\nSome cause.\n")
    assert report.root_cause == "Some cause."
    assert not report.is_empty


def test_label_form_parses_bullet_sections():
    text = (
        "- Root cause: the worker was stopped by hand\n"
        "- Evidence: exit_code -15\n"
        "- Category: needs-human-decision\n"
        "- Recommended action: unblock-as-is\n"
        "- Confidence: high\n"
    )
    report = parse_report(text)
    assert report.root_cause == "the worker was stopped by hand"
    assert report.evidence == "exit_code -15"
    assert report.category == "needs-human-decision"
    assert report.recommended_action == "unblock-as-is"
    assert report.confidence == "high"
    assert not report.is_empty


def test_label_form_collects_continuation_lines_until_blank():
    text = "- Root cause: first line\nsecond line\n\ntrailing\n"
    report = parse_report(text)
    assert report.root_cause == "first line\nsecond line"


def test_heading_form_wins_over_label_form():
    text = "- Root cause: from label.\n\n## Root cause\n\nFrom heading.\n"
    assert parse_report(text).root_cause == "From heading."


def test_partial_report_leaves_missing_fields_empty():
    report = parse_report("## Root cause\n\nOnly this.\n")
    assert report.root_cause == "Only this."
    assert report.evidence == ""
    assert report.category == ""
    assert report.recommended_action == ""
    assert report.confidence == ""
    assert not report.is_empty


def test_empty_and_unknown_text_are_empty():
    assert parse_report("").is_empty
    assert parse_report("").headline() == ""
    assert parse_report("").raw == ""
    assert parse_report("# Just a title\n\nSome prose.\n").is_empty


def test_headline_returns_first_sentence_of_root_cause():
    report = parse_report("## Root cause\n\nFirst sentence. Second sentence.\n")
    assert report.headline() == "First sentence."


def test_headline_truncates_long_sentence_with_ellipsis():
    long = "word " * 60
    report = parse_report(f"## Root cause\n\n{long.strip()}.\n")
    headline = report.headline()
    assert headline.endswith("…")
    assert len(headline) <= HEADLINE_MAX_CHARS + 1
    assert "…" not in headline[:-1]


def test_headline_falls_back_to_first_content_line():
    report = parse_report("# Title\n\nA stray note here.\n")
    assert report.headline() == "A stray note here."


def test_headline_collapses_whitespace():
    report = parse_report("## Root cause\n\nLots   of\n\tspace here.\n")
    assert report.headline() == "Lots of space here."


def test_raw_round_trips_input():
    text = "## Evidence\n\n- a: 1\n- b: 2\n"
    assert parse_report(text).raw == text
