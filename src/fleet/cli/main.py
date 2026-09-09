"""fleet CLI — typer-based surface for the fleet supervisor (FR-32).

Each command group lives in its own module; this file only builds the
top-level `app` and wires the groups in.
"""

from __future__ import annotations

import typer

from fleet.cli import ask_human, beads, config, daemons, schedule, tasks, telegram, workflow

app = typer.Typer(
    no_args_is_help=True,
    help=(
        "fleet — parallel coding-agent supervisor.\n\n"
        "Pulls tasks from a centralized beads queue and runs them in parallel "
        "through a coder CLI (claude, agy, codex, or opencode) in a headless loop. "
        "Each task carries its own project directory and optional coder/model "
        "override, so a single supervisor can drive work across many projects "
        "and agent backends from one machine.\n\n"
        "Typical flow:  fleet init  →  fleet bd create  →  fleet run start"
    ),
    epilog=(
        "Examples:\n\n"
        '  fleet bd create "Fix login redirect" --coder opencode\n'
        "  fleet task fleet-abc log\n"
        "  fleet run restart"
    ),
)

tasks.register(app)
beads.register(app)
daemons.register(app)
config.register(app)
telegram.register(app)
ask_human.register(app)
schedule.register(app)
workflow.register(app)
