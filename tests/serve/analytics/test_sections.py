"""Section tests: every SUMMARY_SECTIONS entry on empty and fixture input.

Empty input must never crash and yields the zero value of each shape;
fixture input spot-checks real numbers (the full shape is pinned by
test_summary_snapshot.py).
"""

from __future__ import annotations

from pathlib import Path

from fleet.serve.analytics import records as records_mod
from fleet.serve.analytics.records import AttemptRecord, collect_records
from fleet.serve.analytics.summary import SUMMARY_SECTIONS, reconcile, summarize
from fleet.serve.analytics.window import Window, build_window
from tests.serve.analytics.fixture_home import build_fixture_home

_SECTION_KEYS = [section.key for section in SUMMARY_SECTIONS]


def _empty_window() -> Window:
    """All-time window with no overrides (fully deterministic)."""
    return Window(days=0, cutoff=None, bucket_size="day", context_overrides={})


def _fixture_inputs(home: Path) -> tuple[list[AttemptRecord], Window]:
    """Reconciled fixture records plus their all-time window."""
    records_mod._events_cache.clear()
    build_fixture_home(home)
    records = collect_records(home)
    reconciled = reconcile(records, None)
    return reconciled, build_window(home, 0)


def test_registry_covers_every_response_key() -> None:
    """SUMMARY_SECTIONS renders exactly the legacy response keys."""
    assert _SECTION_KEYS == [
        "kpis",
        "throughput",
        "token_throughput",
        "by_model",
        "by_project",
        "tools",
        "context_histogram",
        "heatmap",
        "errors_recent",
        "rate_limits",
    ]


def test_summarize_dispatches_one_key_per_section(tmp_path: Path) -> None:
    """summarize returns one entry per registry section."""
    records, window = _fixture_inputs(tmp_path)
    assert set(summarize(records, window)) == set(_SECTION_KEYS)


class TestEmptyInput:
    """Every section computes on an empty record list."""

    def test_sections_on_empty(self) -> None:
        """Empty input yields zero values, never an exception."""
        window = _empty_window()
        out = summarize([], window)
        assert out["kpis"]["completed"] == 0
        assert out["kpis"]["success_rate"] == 0.0
        assert out["kpis"]["median_run_sec"] == 0.0
        assert out["kpis"]["total_output_tokens"] == 0
        assert out["throughput"] == {"bucket_size": "day", "buckets": []}
        assert out["token_throughput"] == {"bucket_size": "day", "buckets": []}
        assert out["by_model"] == []
        assert out["by_project"] == []
        assert out["tools"] == {"total": 0, "rows": []}
        assert out["context_histogram"] == {
            "buckets": {"0-25": 0, "25-50": 0, "50-75": 0, "75-100": 0, "100+": 0}
        }
        assert out["heatmap"] == [[0] * 24 for _ in range(7)]
        assert out["errors_recent"] == []
        assert out["rate_limits"] == []


class TestFixtureInput:
    """Every section computes real numbers on the fixture home."""

    def test_kpis(self, tmp_path: Path) -> None:
        """Headline counts over the six fixture tasks."""
        out = summarize(*_fixture_inputs(tmp_path))
        assert out["kpis"]["completed"] == 5
        assert out["kpis"]["success_rate"] == 0.6
        assert out["kpis"]["active_now"] == 1
        assert out["kpis"]["total_output_tokens"] == 550
        assert out["kpis"]["noclose_count"] == 1
        assert out["kpis"]["rate_limited_tasks"] == 1

    def test_throughput(self, tmp_path: Path) -> None:
        """One day bucket per completion day."""
        out = summarize(*_fixture_inputs(tmp_path))
        assert out["throughput"]["bucket_size"] == "day"
        assert [b["bucket"] for b in out["throughput"]["buckets"]] == [
            "2025-06-01",
            "2025-06-02",
            "2025-06-03",
            "2025-06-04",
            "2025-06-05",
        ]

    def test_token_throughput(self, tmp_path: Path) -> None:
        """Cache tokens fold creation plus read."""
        out = summarize(*_fixture_inputs(tmp_path))
        first = out["token_throughput"]["buckets"][0]
        assert (first["output_tokens"], first["input_tokens"], first["cache_tokens"]) == (
            200,
            100,
            60,
        )

    def test_by_model(self, tmp_path: Path) -> None:
        """Unknown coder/model collapse to unknown; biggest group first."""
        out = summarize(*_fixture_inputs(tmp_path))
        assert [(r["coder"], r["model"], r["total"]) for r in out["by_model"]] == [
            ("claude", "sonnet", 3),
            ("claude", "opus", 1),
            ("unknown", "unknown", 1),
        ]

    def test_by_project(self, tmp_path: Path) -> None:
        """Per-cwd totals over windowed completions."""
        out = summarize(*_fixture_inputs(tmp_path))
        assert [(r["cwd"], r["total"]) for r in out["by_project"]] == [
            ("/proj-a", 3),
            ("/proj-b", 2),
        ]

    def test_tools(self, tmp_path: Path) -> None:
        """Merged tool counts across in-window records."""
        out = summarize(*_fixture_inputs(tmp_path))
        assert out["tools"]["total"] == 3
        assert {r["name"] for r in out["tools"]["rows"]} == {"Read", "Edit", "Write"}

    def test_context_histogram(self, tmp_path: Path) -> None:
        """Peaks with usage data bucket under 25 percent of the fallback limit."""
        out = summarize(*_fixture_inputs(tmp_path))
        assert sum(out["context_histogram"]["buckets"].values()) == 3
        assert out["context_histogram"]["buckets"]["0-25"] == 3

    def test_heatmap(self, tmp_path: Path) -> None:
        """7x24 matrix whose cells sum to the fixture event count."""
        out = summarize(*_fixture_inputs(tmp_path))
        assert len(out["heatmap"]) == 7
        assert all(len(row) == 24 for row in out["heatmap"])
        assert sum(sum(row) for row in out["heatmap"]) == 10

    def test_errors_recent(self, tmp_path: Path) -> None:
        """Flagged completions newest first, labeled by flag."""
        out = summarize(*_fixture_inputs(tmp_path))
        assert [(e["id"], e["outcome"]) for e in out["errors_recent"]] == [
            ("task-zeta", "context_pressure"),
            ("task-eps", "noclose"),
            ("task-gamma", "blocked"),
            ("task-beta", "failed"),
        ]

    def test_rate_limits(self, tmp_path: Path) -> None:
        """Only rejected rate-limit events, oldest first."""
        out = summarize(*_fixture_inputs(tmp_path))
        assert out["rate_limits"] == [{"ts": "2025-06-02T12:00:00Z", "task_id": "task-beta"}]
