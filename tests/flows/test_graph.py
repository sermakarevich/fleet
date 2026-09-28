"""Tests for fleet.flows.graph."""

from __future__ import annotations

from typing import Any

import pytest

from fleet.core.errors import TemplateError
from fleet.flows import graph
from fleet.flows.graph import Item
from fleet.flows.model import Flow, Step, flow_from_dict


def _flow(definition: dict[str, Any]) -> Flow:
    """Parse a minimal flow mapping, keeping file order."""
    return flow_from_dict({"fleet_flow": 2, "steps": definition}, name="demo")


def _chain_flow() -> Flow:
    """Three-step chain: first -> second -> third."""
    return _flow(
        {
            "first": {"prompt": "one"},
            "second": {"prompt": "two", "needs": ["first"]},
            "third": {"prompt": "three", "needs": ["second"]},
        }
    )


def test_ready_steps_only_heads_at_start() -> None:
    """With no statuses, only steps without needs are ready."""
    ready = graph.ready_steps(_chain_flow(), {}, set())
    assert [step.name for step in ready] == ["first"]


def test_ready_steps_after_succeeded_needs() -> None:
    """A step becomes ready once every need succeeded."""
    flow = _chain_flow()
    ready = graph.ready_steps(flow, {"first": "succeeded"}, {"first"})
    assert [step.name for step in ready] == ["second"]


def test_ready_steps_skipped_counts_as_ok() -> None:
    """Skipped needs unblock dependents like succeeded ones."""
    flow = _chain_flow()
    ready = graph.ready_steps(flow, {"first": "skipped"}, {"first"})
    assert [step.name for step in ready] == ["second"]


def test_ready_steps_failed_need_blocks_forever() -> None:
    """A failed need never yields, even if the step was never started."""
    flow = _chain_flow()
    assert graph.ready_steps(flow, {"first": "failed"}, {"first"}) == []
    assert graph.ready_steps(flow, {"first": "cancelled"}, {"first"}) == []


def test_ready_steps_started_are_excluded() -> None:
    """Steps already in started never come back, in flow order."""
    flow = _flow(
        {
            "alpha": {"prompt": "a"},
            "beta": {"prompt": "b"},
        }
    )
    ready = graph.ready_steps(flow, {}, {"alpha"})
    assert [step.name for step in ready] == ["beta"]


def _fan_step(extra: dict[str, Any] | None = None) -> Step:
    """Build a for_each step over steps.units.outputs.units."""
    fields: dict[str, Any] = {
        "prompt": "do {{ item }}",
        "for_each": "{{ steps.units.outputs.units }}",
    }
    if extra:
        fields.update(extra)
    flow = _flow({"fan": fields})
    return flow.step("fan")


def test_expand_string_items_get_index_keys() -> None:
    """Plain string items fall back to str(index) keys with no waits."""
    step = _fan_step()
    items = graph.expand(step, {"steps": {"units": {"outputs": {"units": ["a", "b"]}}}})
    assert [(item.index, item.key, item.after) for item in items] == [
        (0, "0", ()),
        (1, "1", ()),
    ]
    assert [item.value for item in items] == ["a", "b"]


def test_expand_object_items_with_key_and_after() -> None:
    """Object items render key/after templates over item and index."""
    step = _fan_step({"key": "{{ item.unit }}", "after": "{{ item.after | default([]) }}"})
    context = {
        "steps": {
            "units": {
                "outputs": {
                    "units": [
                        {"unit": "M1"},
                        {"unit": "M2"},
                        {"unit": "R3", "after": ["M1"]},
                    ]
                }
            }
        }
    }
    items = graph.expand(step, context)
    assert [(item.key, item.after) for item in items] == [
        ("M1", ()),
        ("M2", ()),
        ("R3", ("M1",)),
    ]


def test_expand_after_string_becomes_singleton() -> None:
    """A rendered after string is one dependency, not a char list."""
    step = _fan_step({"key": "{{ item.unit }}", "after": "{{ item.after | default([]) }}"})
    context = {
        "steps": {
            "units": {
                "outputs": {
                    "units": [{"unit": "M1"}, {"unit": "R1", "after": "M1"}],
                }
            }
        },
    }
    assert graph.expand(step, context)[1].after == ("M1",)


def test_expand_sequential_chains_previous_key() -> None:
    """parallel: false adds each previous item key to the next waits."""
    step = _fan_step({"key": "{{ item }}", "parallel": False})
    items = graph.expand(step, {"steps": {"units": {"outputs": {"units": ["a", "b"]}}}})
    assert [item.after for item in items] == [(), ("a",)]


def test_expand_parallel_template_false_chains() -> None:
    """A parallel template rendering false chains like the bool."""
    step = _fan_step({"key": "{{ item }}", "parallel": "{{ go }}"})
    items = graph.expand(
        step, {"steps": {"units": {"outputs": {"units": ["a", "b"]}}}, "go": False}
    )
    assert [item.after for item in items] == [(), ("a",)]
    parallel_items = graph.expand(
        step, {"steps": {"units": {"outputs": {"units": ["a", "b"]}}}, "go": True}
    )
    assert [item.after for item in parallel_items] == [(), ()]


def test_expand_duplicate_key_raises() -> None:
    """Two items rendering the same key raise TemplateError naming it."""
    step = _fan_step({"key": "{{ item.unit }}"})
    context = {
        "steps": {"units": {"outputs": {"units": [{"unit": "M1"}, {"unit": "M1"}]}}},
    }
    with pytest.raises(TemplateError, match="M1"):
        graph.expand(step, context)


def test_expand_unknown_after_raises() -> None:
    """An after naming no item key raises TemplateError naming it."""
    step = _fan_step({"key": "{{ item.unit }}", "after": "{{ item.after }}"})
    context = {
        "steps": {"units": {"outputs": {"units": [{"unit": "R1", "after": ["ghost"]}]}}},
    }
    with pytest.raises(TemplateError, match="ghost"):
        graph.expand(step, context)


def test_expand_non_list_raises_template_error() -> None:
    """A for_each rendering to a non-list raises TemplateError."""
    step = _fan_step()
    with pytest.raises(TemplateError):
        graph.expand(step, {"steps": {"units": {"outputs": {"units": {"unit": "M1"}}}}})


def test_expand_without_for_each_raises_value_error() -> None:
    """Expanding a plain step is a caller bug, hence ValueError."""
    flow = _flow({"plain": {"prompt": "x"}})
    with pytest.raises(ValueError):
        graph.expand(flow.step("plain"), {})


def test_ready_items_diamond() -> None:
    """R3 waits until both M1 and M2 reach OK; pending items alone run."""
    items = [
        Item(index=0, value="M1", key="M1", after=()),
        Item(index=1, value="M2", key="M2", after=()),
        Item(index=2, value="R3", key="R3", after=("M1", "M2")),
    ]
    assert [item.key for item in graph.ready_items(items, {})] == ["M1", "M2"]
    partial = graph.ready_items(items, {"M1": "succeeded"})
    assert [item.key for item in partial] == ["M2"]
    both = graph.ready_items(items, {"M1": "succeeded", "M2": "skipped"})
    assert [item.key for item in both] == ["R3"]
    running = graph.ready_items(items, {"M1": "succeeded", "M2": "running"})
    assert [item.key for item in running] == []


def test_aggregate_truth_table() -> None:
    """Empty/unfinished fold to None; failed beats cancelled beats succeeded."""
    assert graph.aggregate([]) is None
    assert graph.aggregate(["succeeded", "running"]) is None
    assert graph.aggregate(["succeeded", "skipped"]) == "succeeded"
    assert graph.aggregate(["succeeded", "cancelled"]) == "cancelled"
    assert graph.aggregate(["cancelled", "failed"]) == "failed"


def test_flow_status_truth_table() -> None:
    """Missing or unfinished steps give None; otherwise aggregate applies."""
    assert graph.flow_status({}, ["first"]) is None
    assert graph.flow_status({"first": "succeeded"}, ["first", "second"]) is None
    assert graph.flow_status({"first": "running"}, ["first"]) is None
    assert graph.flow_status({"first": "succeeded", "second": "skipped"}, ["first", "second"]) == (
        "succeeded"
    )
    assert graph.flow_status({"first": "failed", "second": "succeeded"}, ["first", "second"]) == (
        "failed"
    )
    assert graph.flow_status(
        {"first": "cancelled", "second": "succeeded"}, ["first", "second"]
    ) == ("cancelled")


def test_skip_renders_condition() -> None:
    """Unset skip_if is False; set values render as bools."""
    flow = _flow({"gated": {"prompt": "x", "skip_if": "{{ inputs.auto == 'on' }}"}})
    gated = flow.step("gated")
    assert graph.skip(gated, {"inputs": {"auto": "on"}}) is True
    assert graph.skip(gated, {"inputs": {"auto": "off"}}) is False
    plain = _flow({"plain": {"prompt": "x"}}).step("plain")
    assert graph.skip(plain, {}) is False
