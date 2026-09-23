"""The `research` builder: one workflow run = one research job (ADR 0015).

The Workflows page lists saved definitions, so a research run starts like any
other workflow: pick `research`, fill the inputs, press Run. The builder turns
the inputs into the key/value description the research worker reads (spec:
`ai show research/get`) and returns one stage with one step whose bead
carries `worker: research`. That bead then discovers and ranks sources, asks
the operator to approve the shortlist, and spawns one `summarise` run per
source plus the digest/lens/index children.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from fleet.workflows.builders import BuildContext
from fleet.workflows.builders.topics import validate_topic
from fleet.workflows.model import Stage, Step, Workflow

KB_ROOT = str(Path.home() / ".ai")
N_SOURCES_DEFAULT = "10"
LENSES_DEFAULT = "tech, ai"
GATE_DEFAULT = "on"

#: Saved definition created on fleet start when no workflow of this name exists.
DEFINITION: dict = {
    "name": "research",
    "description": (
        "Multi-source research into the knowledge base (ai:research:get recipe). "
        "Discovers and ranks candidate sources with jev, asks you to approve the "
        "shortlist, runs summarise on every approved source, then builds "
        "hierarchical digests, lenses (business/product/tech/ai), disagreements "
        "and open questions under ~/.ai/knowledge/research/<target>/."
    ),
    "defaults": {"cwd": KB_ROOT, "priority": 1, "isolation": "none"},
    "inputs": [
        {
            "name": "topics",
            "description": "One or more topics, comma or semicolon separated",
            "required": True,
        },
        {
            "name": "focus",
            "description": "One sentence: the question the research should answer",
            "required": True,
        },
        {
            "name": "target",
            "description": "Folder slug under ~/.ai/knowledge/research/",
            "required": True,
        },
        {
            "name": "topic",
            "description": (
                "Research topic folder under /Users/sergii/.ai/knowledge/research_topics/ "
                "(snake_case, must exist; summarised sources are filed there)"
            ),
            "required": True,
        },
        {
            "name": "n_sources",
            "description": "How many sources to process",
            "default": N_SOURCES_DEFAULT,
        },
        {
            "name": "lenses",
            "description": "Comma-separated lenses: business, product, tech, ai",
            "default": LENSES_DEFAULT,
        },
        {
            "name": "gate",
            "description": "on = approve the shortlist before processing; off = run through",
            "default": GATE_DEFAULT,
        },
        {"name": "date_from", "description": "Ignore sources older than YYYY-MM-DD"},
        {
            "name": "kinds",
            "description": "Restrict source kinds: paper, article, video, repo, thread",
        },
    ],
}

_REQUIRED = ("topics", "focus", "target", "topic")
_OPTIONAL = ("date_from", "kinds")


def description_for(inputs: dict[str, str]) -> str:
    """The bead description the research worker parses: one `key: value` per line."""
    lines = ["Research job (ADR 0015). Spec: `ai show research/get`. Inputs:", ""]
    for key in _REQUIRED:
        lines.append(f"{key}: {inputs[key]}")
    lines.append(f"n_sources: {inputs.get('n_sources') or N_SOURCES_DEFAULT}")
    lines.append(f"lenses: {inputs.get('lenses') or LENSES_DEFAULT}")
    lines.append(f"gate: {inputs.get('gate') or GATE_DEFAULT}")
    for key in _OPTIONAL:
        value = (inputs.get(key) or "").strip()
        if value:
            lines.append(f"{key}: {value}")
    return "\n".join(lines) + "\n"


def build(workflow: Workflow, ctx: BuildContext) -> Workflow:
    """Return the workflow with one stage: the research epic bead."""
    inputs = {key: (value or "").strip() for key, value in ctx.inputs.items()}
    missing = [key for key in _REQUIRED if not inputs.get(key)]
    if missing:
        raise ValueError(f"input {missing[0]} is required")
    target = inputs["target"]
    if "/" in target or target in {".", ".."}:
        raise ValueError("input target must be a folder slug, not a path")
    topic = validate_topic(inputs.get("topic"))
    inputs["topic"] = topic
    step = Step(
        name="epic",
        title=f"research: {inputs['topics'][:80]}",
        description=description_for(inputs),
        worker="research",
    )
    return replace(workflow, stages=(Stage(name="research", steps=(step,)),))
