"""Prompt assembly for coder launches: which template files, in which order, per mode.

The markdown files themselves stay in ``fleet/templates/`` (data, owned by
this package's table). This module owns the policy of which files make up a
launch prompt for each launch mode. Called by every coder's ``build_argv``
(through :func:`render`) via ``coders.base.prompt_context``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from fleet.core.task import Task

_TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
_ISOLATED_PROTOCOL = "ISOLATED_PROTOCOL.md"

LaunchMode = Literal["fresh", "continue", "validate", "research", "design"]


@dataclass(frozen=True)
class TemplateSet:
    """Template files rendered in order for one launch mode.

    The first file is the header (``str.format`` with the task fields); the
    rest are plain instruction markdown. The launch pack goes between the
    header and the instructions; the isolated-worktree protocol is appended
    when the task runs isolated.
    """

    files: tuple[str, ...]


MODE_TEMPLATES: dict[LaunchMode, TemplateSet] = {
    "fresh": TemplateSet(("coder_header.md.tmpl", "INSTRUCTION_FRESH.md", "INSTRUCTION_COMMON.md")),
    "continue": TemplateSet(
        ("coder_header.md.tmpl", "INSTRUCTION_CONTINUE.md", "INSTRUCTION_COMMON.md")
    ),
    "validate": TemplateSet(
        ("coder_header.md.tmpl", "INSTRUCTION_VALIDATE.md", "INSTRUCTION_COMMON.md")
    ),
    "research": TemplateSet(
        ("coder_header.md.tmpl", "INSTRUCTION_RESEARCH.md", "INSTRUCTION_COMMON.md")
    ),
    "design": TemplateSet(
        ("coder_header.md.tmpl", "INSTRUCTION_DESIGN.md", "INSTRUCTION_COMMON.md")
    ),
}


@dataclass(frozen=True)
class PromptContext:
    """Resolved inputs for one prompt render (Workspace already applied)."""

    task: Task
    task_dir: Path
    pack: str = ""
    workdir: str | None = None
    worktree: str | None = None
    isolated: bool = False


def _header(template_name: str, ctx: PromptContext) -> str:
    """Render the header template with the task fields."""
    return (
        (_TEMPLATES_DIR / template_name)
        .read_text(encoding="utf-8")
        .format(
            task_id=ctx.task.id,
            task_title=ctx.task.title,
            task_description=ctx.task.description or "",
            task_dir=ctx.task_dir,
            invocation_line=f"Invocation directory: {ctx.workdir}" if ctx.workdir else "",
        )
        .strip()
    )


def _plain(template_name: str) -> str:
    """Read one instruction template, stripped."""
    return (_TEMPLATES_DIR / template_name).read_text(encoding="utf-8").strip()


def _protocol(ctx: PromptContext) -> str:
    """The isolated-worktree protocol with the worktree path filled in."""
    text = _plain(_ISOLATED_PROTOCOL)
    return text.replace("{worktree_path}", ctx.worktree or "your working directory")


def render(mode: str, ctx: PromptContext) -> str:
    """Build the one prompt every coder sends: header + pack + mode instructions.

    *mode* selects a row of ``MODE_TEMPLATES`` (unknown modes fall back to
    ``fresh``, as before); *ctx* carries the task, the continue pack, and the
    resolved workdir/isolation (see ``coders.base.prompt_context``).
    """
    key: LaunchMode = cast(LaunchMode, mode) if mode in MODE_TEMPLATES else "fresh"
    names = MODE_TEMPLATES[key].files
    parts = [_header(names[0], ctx)]
    if ctx.pack:
        parts.append(ctx.pack)
    parts.extend(_plain(name) for name in names[1:])
    if ctx.isolated:
        parts.append(_protocol(ctx))
    return "\n\n---\n\n".join(parts)
