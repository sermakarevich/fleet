"""Tests for the HELPER_REPORT.md parser (core/helper_report.py)."""

from fleet.core.helper_report import parse_report


def test_heading_form_parses_all_sections_same_as_previous_yes():
    text = (
        "# Helper report: t1 — blocked\n"
        "\n"
        "## Root cause\n"
        "\n"
        "The worker was stopped by hand mid-edit.\n"
        "\n"
        "## Evidence\n"
        "\n"
        "- exit_code -15, empty stderr\n"
        "\n"
        "## Same as previous root cause\n"
        "\n"
        "Yes.\n"
        "\n"
        "## Proposed fixes\n"
        "\n"
        "Retry with opus.\n"
    )
    report = parse_report(text)
    assert report.root_cause == "The worker was stopped by hand mid-edit."
    assert report.evidence == "- exit_code -15, empty stderr"
    assert report.same_as_previous is True
    assert report.proposed_fixes == "Retry with opus."
    assert report.raw == text


def test_same_as_previous_no_is_case_insensitive_with_trailing_text():
    report = parse_report(
        "## Same as previous root cause\n\nno — new cause found this time.\n"
    )
    assert report.same_as_previous is False


def test_missing_same_as_previous_heading_is_none():
    report = parse_report("## Root cause\n\nSome cause.\n")
    assert report.same_as_previous is None


def test_unparsable_same_as_previous_value_is_none():
    report = parse_report("## Same as previous root cause\n\nunclear, maybe.\n")
    assert report.same_as_previous is None


def test_empty_and_garbage_text_yield_defaults_no_exception():
    report = parse_report("")
    assert report.root_cause == ""
    assert report.evidence == ""
    assert report.same_as_previous is None
    assert report.proposed_fixes == ""
    assert report.raw == ""

    report = parse_report("random garbage with no headings at all")
    assert report.root_cause == ""
    assert report.same_as_previous is None


def test_label_form_parses_bullet_sections():
    text = (
        "- Root cause: the worker was stopped by hand\n"
        "- Evidence: exit_code -15\n"
        "- Same as previous root cause: yes, matches earlier helper\n"
        "- Proposed fixes: bump timeout\n"
    )
    report = parse_report(text)
    assert report.root_cause == "the worker was stopped by hand"
    assert report.evidence == "exit_code -15"
    assert report.same_as_previous is True
    assert report.proposed_fixes == "bump timeout"


def test_heading_form_wins_over_label_form():
    text = (
        "- Same as previous root cause: yes\n"
        "\n"
        "## Same as previous root cause\n"
        "\n"
        "no\n"
    )
    assert parse_report(text).same_as_previous is False


def test_non_string_input_yields_defaults():
    report = parse_report(None)  # type: ignore[arg-type]
    assert report.root_cause == ""
    assert report.same_as_previous is None
    assert report.raw == ""
