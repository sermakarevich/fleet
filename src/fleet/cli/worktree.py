"""`fleet worktree merge|drop` — merge or drop a coder step's worktree.

Thin typer sub-app (ADR 0006 rule 3): each command parses flags, calls a
module-level `run_*` helper that computes through
`orchestrator.worktree_merge`, and prints the outcome as one JSON object
(`--json`) or one human line. Called by `cli/main.py`.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import typer

from fleet.cli import bootstrap
from fleet.cli.errors import ExitCode
from fleet.cli.options import TaskIdArgument
from fleet.orchestrator import worktree_merge
from fleet.orchestrator.worktree_merge import MergeOutcome


def _print(outcome: MergeOutcome, json_output: bool) -> None:
    """One JSON object with --json, else one human line (merged/message/failed)."""
    if json_output:
        typer.echo(json.dumps(asdict(outcome)))
        return
    if outcome.merged:
        typer.echo(f"merged {outcome.branch} into {outcome.base_ref}")
    elif outcome.ok:
        typer.echo(outcome.message)
    else:
        typer.echo(f"merge failed: {outcome.message}")


def _exit(outcome: MergeOutcome) -> None:
    """Exit 0 when the outcome is ok, else 1 (ExitCode.ERROR)."""
    if not outcome.ok:
        raise typer.Exit(int(ExitCode.ERROR))


def run_merge(fleet_home: Path, task_id: str, keep_branch: bool, json_output: bool) -> None:
    """Merge one coder step's worktree branch into its base ref and print the outcome."""
    outcome = worktree_merge.merge_task_worktree(
        fleet_home, bootstrap.config(fleet_home), task_id, keep_branch=keep_branch
    )
    _print(outcome, json_output)
    _exit(outcome)


def run_drop(fleet_home: Path, task_id: str, json_output: bool) -> None:
    """Drop one coder step's worktree and branch without merging; print the outcome."""
    outcome = worktree_merge.drop_task_worktree(fleet_home, task_id)
    _print(outcome, json_output)
    _exit(outcome)


def register(app: typer.Typer) -> None:
    """Wire `fleet worktree` as a thin sub-app over the helpers above."""
    worktree_app = typer.Typer(
        no_args_is_help=True,
        help="Merge or drop a flow coder step's isolated worktree.",
        epilog=(
            "Examples:\n\n  fleet worktree merge run-abc.build\n  fleet worktree drop run-abc.build"
        ),
    )
    app.add_typer(worktree_app, name="worktree")

    @worktree_app.command("merge")
    def merge_cmd(
        task_id: TaskIdArgument,
        keep_branch: Annotated[
            bool, typer.Option("--keep-branch", help="Keep fleet/<task id> after merging.")
        ] = False,
        json_output: Annotated[bool, typer.Option("--json", help="Emit the outcome as JSON.")] = (
            False
        ),
    ) -> None:
        """Merge a finished coder step's worktree branch into its base branch."""
        run_merge(bootstrap.fleet_home(), task_id, keep_branch, json_output)

    @worktree_app.command("drop")
    def drop_cmd(
        task_id: TaskIdArgument,
        json_output: Annotated[bool, typer.Option("--json", help="Emit the outcome as JSON.")] = (
            False
        ),
    ) -> None:
        """Remove a coder step's worktree and branch without merging."""
        run_drop(bootstrap.fleet_home(), task_id, json_output)
