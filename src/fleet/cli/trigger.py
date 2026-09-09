"""`fleet trigger` — event triggers (ADR 0011) from the terminal.

Thin typer sub-app (ADR 0006 rule 3): each command parses flags, calls a
module-level `run_*` helper that computes through `triggers.*`, and prints
through `cli/render.py`. Time is read here via `datetime.now(UTC)` only;
everything stored is an ISO-8601 UTC string. Called by `cli/main.py`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from dataclasses import replace as dc_replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

import typer

from fleet.cli import bootstrap, render
from fleet.cli.errors import ExitCode, fail
from fleet.coders import get_coder
from fleet.triggers import firing as firing_mod
from fleet.triggers.model import Trigger, new_id
from fleet.triggers.sources import SOURCES, UnknownSource, source_for, source_params
from fleet.triggers.sources.base import SourceContext
from fleet.triggers.store import TriggerStore

_MIN_PRIORITY = 0
_MAX_PRIORITY = 4
_SHOW_FIRING_LIMIT = 20
_FIRINGS_DEFAULT_LIMIT = 50


@dataclass(frozen=True)
class TriggerRow:
    """One `fleet trigger list` line: the trigger plus computed columns."""

    trigger: Trigger
    firing_count: int
    last_fired_at: str | None


def _store(fleet_home: Path) -> TriggerStore:
    """Trigger store rooted at *fleet_home*."""
    return TriggerStore(fleet_home)


def _fetch(store: TriggerStore, trigger_id: str) -> Trigger:
    """One trigger, exiting NOT_FOUND when the id is unknown."""
    trigger = store.get(trigger_id)
    if trigger is None:
        fail(f"Trigger {trigger_id} not found.", ExitCode.NOT_FOUND)
    return trigger


def _check_coder(coder: str | None) -> None:
    """Exit USAGE when *coder* names no registered coder CLI."""
    if coder is None:
        return
    try:
        get_coder(coder)
    except ValueError as exc:
        fail(f"coder: {exc}", ExitCode.USAGE)


def _check_cwd(cwd: str | None) -> None:
    """Exit USAGE when *cwd* is set but is not an existing directory."""
    if cwd is not None and not Path(cwd).is_dir():
        fail(f"cwd: not an existing directory: {cwd!r}", ExitCode.USAGE)


def _check_priority(priority: int) -> None:
    """Exit USAGE when *priority* is outside the 0-4 bead range."""
    if not _MIN_PRIORITY <= priority <= _MAX_PRIORITY:
        fail(f"priority: must be 0-4, got {priority}", ExitCode.USAGE)


def _check_source(source: str) -> None:
    """Exit USAGE when *source* names no registered event source."""
    if source not in SOURCES:
        fail(f"source: unknown source {source!r}", ExitCode.USAGE)


def _parse_param_pair(raw: str) -> tuple[str, str]:
    """Split one --param name=value pair, exiting USAGE when malformed."""
    name, sep, value = raw.partition("=")
    if not sep or not name:
        fail(f"invalid argument {raw!r} — expected name=value format.", ExitCode.USAGE)
    return name, value


def _read_body_file(path: Path | None) -> str | None:
    """Body-file text, exiting NOT_FOUND when the path is unreadable."""
    if path is None:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        fail(f"cannot read {path}: {exc}", ExitCode.NOT_FOUND)
    return None  # unreachable: fail() always raises


def _row(store: TriggerStore, trigger: Trigger) -> TriggerRow:
    """List row for one trigger: firing count plus latest firing time."""
    last = store.last_firing(trigger.id)
    return TriggerRow(
        trigger=trigger,
        firing_count=store.firing_count(trigger.id),
        last_fired_at=last.fired_at if last is not None else None,
    )


def _parse_moment(raw: str) -> datetime | None:
    """Parse a stored ISO-8601 timestamp, or None when unparseable."""
    try:
        moment = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def _build_trigger(  # noqa: PLR0913, PLR0917  # one trigger, one call shape
    *,
    trigger_id: str,
    name: str,
    source: str,
    params: dict[str, str],
    title: str,
    description: str,
    cwd: str | None,
    coder: str | None,
    model: str | None,
    priority: int,
    isolation: str | None,
    labels: list[str],
    max_open: int,
    cooldown_sec: int,
    enabled: bool,
    created_at: str,
    now: datetime,
) -> Trigger:
    """Validate fields like the serve API and return the trigger."""
    if not name.strip():
        fail("name: required and must not be empty", ExitCode.USAGE)
    if not title.strip():
        fail("title: required and must not be empty", ExitCode.USAGE)
    _check_source(source)
    _check_coder(coder)
    _check_cwd(cwd)
    _check_priority(priority)
    if max_open < 0:
        fail(f"max_open: must be >= 0, got {max_open}", ExitCode.USAGE)
    if cooldown_sec < 0:
        fail(f"cooldown_sec: must be >= 0, got {cooldown_sec}", ExitCode.USAGE)
    try:
        return Trigger.from_dict(
            {
                "id": trigger_id,
                "name": name,
                "source": source,
                "title": title,
                "description": description,
                "source_params": params,
                "enabled": enabled,
                "cwd": cwd,
                "coder": coder,
                "model": model,
                "priority": priority,
                "isolation": isolation,
                "labels": labels,
                "max_open": max_open,
                "cooldown_sec": cooldown_sec,
                "created_at": created_at,
                "updated_at": now.isoformat(),
            }
        )
    except ValueError as exc:
        fail(str(exc), ExitCode.USAGE)
    raise AssertionError("unreachable")  # fail() always raises


def run_list(fleet_home: Path) -> None:
    """Print every trigger as a table."""
    store = _store(fleet_home)
    render.print_trigger_list([_row(store, item) for item in store.list()])


def run_show(fleet_home: Path, trigger_id: str) -> None:
    """Print one trigger as pretty JSON plus the last 20 firings."""
    store = _store(fleet_home)
    trigger = _fetch(store, trigger_id)
    typer.echo(json.dumps(trigger.to_dict(), indent=2))
    firings = store.firings(trigger_id, limit=_SHOW_FIRING_LIMIT)
    if not firings:
        typer.echo("firings: (none)")
        return
    typer.echo(f"firings: {len(firings)}")
    for firing in firings:
        typer.echo(
            f"  #{firing.n} event={firing.event_key} fired={firing.fired_at}"
            f" task={firing.task_id or '-'}"
            + (f" skipped ({firing.reason})" if firing.skipped else "")
        )


def run_sources() -> None:
    """Print every source kind with its parameter help."""
    for kind in sorted(SOURCES):
        typer.echo(f"{kind}:")
        params = source_params(kind)
        if not params:
            typer.echo("  (no parameters)")
            continue
        for name in sorted(params):
            typer.echo(f"  {name}: {params[name]}")


def run_create(  # noqa: PLR0913, PLR0917  # one trigger, one call shape
    fleet_home: Path,
    now: datetime,
    *,
    name: str,
    source: str,
    raw_params: list[str],
    title: str,
    description: str,
    body_file: Path | None,
    cwd: str | None,
    coder: str | None,
    model: str | None,
    priority: int,
    isolation: str | None,
    labels: list[str],
    max_open: int,
    cooldown_sec: int,
    trigger_id: str | None,
    disabled: bool,
) -> None:
    """Validate, save with a fresh id, and print the id."""
    body = _read_body_file(body_file)
    if body is not None and description:
        fail("--description and --body-file are mutually exclusive", ExitCode.USAGE)
    params = dict(_parse_param_pair(raw) for raw in raw_params)
    trigger = _build_trigger(
        trigger_id=trigger_id or new_id(),
        name=name,
        source=source,
        params=params,
        title=title,
        description=body if body is not None else description,
        cwd=cwd,
        coder=coder,
        model=model,
        priority=priority,
        isolation=isolation,
        labels=list(labels),
        max_open=max_open,
        cooldown_sec=cooldown_sec,
        enabled=not disabled,
        created_at=now.isoformat(),
        now=now,
    )
    _store(fleet_home).save(trigger)
    typer.echo(trigger.id)


def _read_definition(path: Path) -> Any:
    """JSON file text parsed, exiting NOT_FOUND/ERROR when unreadable."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        fail(f"cannot read {path}: {exc}", ExitCode.NOT_FOUND)
    try:
        return json.loads(text)
    except ValueError as exc:
        fail(f"invalid JSON in {path}: {exc}", ExitCode.ERROR)
    return None  # unreachable: fail() always raises


def run_import(fleet_home: Path, now: datetime, path: Path, replace: str | None) -> None:
    """Validate a JSON definition file and save it, printing its id."""
    data = _read_definition(path)
    if not isinstance(data, dict):
        fail(f"invalid: {path} must hold a JSON object", ExitCode.USAGE)
    store = _store(fleet_home)
    if replace is not None:
        existing = _fetch(store, replace)
        trigger_id = existing.id
        created_at = existing.created_at or now.isoformat()
    else:
        trigger_id = str(data.get("id") or new_id())
        created_at = str(data.get("created_at") or now.isoformat())
    payload = {**data, "id": trigger_id, "created_at": created_at}
    payload["updated_at"] = now.isoformat()
    source = payload.get("source", "")
    if source not in SOURCES:
        fail(f"source: unknown source {source!r}", ExitCode.USAGE)
    try:
        trigger = Trigger.from_dict(payload)
    except ValueError as exc:
        fail(str(exc), ExitCode.USAGE)
    store.save(trigger)
    typer.echo(trigger.id)


def run_export(fleet_home: Path, trigger_id: str) -> None:
    """Print one trigger definition as JSON."""
    typer.echo(json.dumps(_fetch(_store(fleet_home), trigger_id).to_dict(), indent=2))


def run_set_enabled(fleet_home: Path, now: datetime, trigger_id: str, enabled: bool) -> None:
    """Flip a trigger's enabled flag, bumping updated_at."""
    store = _store(fleet_home)
    existing = _fetch(store, trigger_id)
    store.save(dc_replace(existing, enabled=enabled, updated_at=now.isoformat()))
    typer.echo(f"Trigger {trigger_id} {'enabled' if enabled else 'disabled'}.")


def run_remove(fleet_home: Path, trigger_id: str) -> None:
    """Remove a trigger and its firing history."""
    if not _store(fleet_home).delete(trigger_id):
        fail(f"Trigger {trigger_id} not found.", ExitCode.NOT_FOUND)
    typer.echo(f"Removed trigger {trigger_id}.")


def run_firings(fleet_home: Path, trigger_id: str, limit: int) -> None:
    """Print one trigger's firing history as a table."""
    store = _store(fleet_home)
    _fetch(store, trigger_id)
    if limit < 0:
        fail(f"limit: must be >= 0, got {limit}", ExitCode.USAGE)
    render.print_trigger_firings(store.firings(trigger_id, limit=limit))


def run_test(fleet_home: Path, now: datetime, trigger_id: str) -> None:
    """Dry run: poll the source now, print decide() per event, open nothing."""
    store = _store(fleet_home)
    trigger = _fetch(store, trigger_id)
    try:
        source = source_for(trigger.source)
    except UnknownSource:
        fail(f"source: unknown source {trigger.source!r}", ExitCode.USAGE)
    queue = bootstrap.queue(fleet_home)
    events = source.poll(
        SourceContext(
            fleet_home=fleet_home,
            queue=queue,
            now=now,
            params=dict(trigger.source_params),
        )
    )
    count = firing_mod.open_count(trigger, queue)
    last = store.last_firing(trigger.id)
    last_at = _parse_moment(last.fired_at) if last is not None else None
    if not events:
        typer.echo("No events.")
        return
    for event in events:
        decision = firing_mod.decide(
            trigger,
            event,
            already_fired=store.has_fired(trigger.id, event.key),
            open_count=count,
            last_fired_at=last_at,
            now=now,
        )
        reason = decision.reason or "-"
        typer.echo(f"{event.key}: decide({decision.action}) {reason}")


def register(app: typer.Typer) -> None:
    """Wire `fleet trigger` as a thin sub-app over the helpers above."""
    trigger_app = typer.Typer(
        no_args_is_help=True,
        help="Manage event triggers: open a bead when a watched signal fires.",
        epilog=(
            "Examples:\n\n"
            "  fleet trigger sources\n"
            '  fleet trigger create --name invest --source blocked_task --title "Investigate"\n'
            "  fleet trigger test trg-abc123"
        ),
    )
    app.add_typer(trigger_app, name="trigger")

    @trigger_app.command("list")
    def list_cmd() -> None:
        """List every trigger with firing counts."""
        run_list(bootstrap.fleet_home())

    @trigger_app.command("show")
    def show_cmd(
        trigger_id: Annotated[str, typer.Argument(help="Trigger id.")],
    ) -> None:
        """Show one trigger definition plus its recent firings."""
        run_show(bootstrap.fleet_home(), trigger_id)

    @trigger_app.command("sources")
    def sources_cmd() -> None:
        """List every event-source kind with its parameter help."""
        run_sources()

    @trigger_app.command("create")
    def create_cmd(  # noqa: PLR0913, PLR0917  # create takes one flag per field
        name: Annotated[str, typer.Option("--name", help="Short trigger name.")] = "",
        source: Annotated[str, typer.Option("--source", help="Event-source kind.")] = "",
        raw_params: Annotated[
            list[str] | None,
            typer.Option("--param", help="Source param as name=value (repeatable)."),
        ] = None,
        title: Annotated[str, typer.Option("--title", help="Bead title template.")] = "",
        description: Annotated[str, typer.Option("--description", help="Bead body template.")] = "",
        body_file: Annotated[
            Path | None,
            typer.Option("--body-file", help="Read the bead body from this file."),
        ] = None,
        cwd: Annotated[
            str | None, typer.Option("--cwd", help="Working directory for opened tasks.")
        ] = None,
        coder: Annotated[str | None, typer.Option("--coder", help="Coder CLI override.")] = None,
        model: Annotated[str | None, typer.Option("--model", help="Model override.")] = None,
        priority: Annotated[int, typer.Option("--priority", "-p", help="Bead priority 0-4.")] = 2,
        isolation: Annotated[
            str | None, typer.Option("--isolation", help="worktree or none.")
        ] = None,
        labels: Annotated[
            list[str] | None,
            typer.Option("--label", help="Extra bead label (repeatable)."),
        ] = None,
        max_open: Annotated[int, typer.Option("--max-open", help="Max not-yet-closed beads.")] = 2,
        cooldown_sec: Annotated[
            int, typer.Option("--cooldown-sec", help="Min seconds between firings.")
        ] = 0,
        trigger_id: Annotated[
            str | None, typer.Option("--id", help="Trigger id slug (fresh one by default).")
        ] = None,
        disabled: Annotated[
            bool, typer.Option("--disabled", help="Create the trigger disabled.")
        ] = False,
    ) -> None:
        """Create a trigger and print its id."""
        run_create(
            bootstrap.fleet_home(),
            datetime.now(UTC),
            name=name,
            source=source,
            raw_params=raw_params or [],
            title=title,
            description=description,
            body_file=body_file,
            cwd=cwd,
            coder=coder,
            model=model,
            priority=priority,
            isolation=isolation,
            labels=labels or [],
            max_open=max_open,
            cooldown_sec=cooldown_sec,
            trigger_id=trigger_id,
            disabled=disabled,
        )

    @trigger_app.command("import")
    def import_cmd(
        file: Annotated[Path, typer.Argument(help="JSON definition file to import.")],
        replace: Annotated[
            str | None, typer.Option("--replace", help="Replace this trigger id.")
        ] = None,
    ) -> None:
        """Validate a JSON file and save it as a trigger, printing its id."""
        run_import(bootstrap.fleet_home(), datetime.now(UTC), file, replace)

    @trigger_app.command("export")
    def export_cmd(
        trigger_id: Annotated[str, typer.Argument(help="Trigger id.")],
    ) -> None:
        """Print one trigger definition as JSON."""
        run_export(bootstrap.fleet_home(), trigger_id)

    @trigger_app.command("enable")
    def enable_cmd(
        trigger_id: Annotated[str, typer.Argument(help="Trigger id.")],
    ) -> None:
        """Enable a trigger."""
        run_set_enabled(bootstrap.fleet_home(), datetime.now(UTC), trigger_id, True)

    @trigger_app.command("disable")
    def disable_cmd(
        trigger_id: Annotated[str, typer.Argument(help="Trigger id.")],
    ) -> None:
        """Disable a trigger (it keeps its history and fires no more beads)."""
        run_set_enabled(bootstrap.fleet_home(), datetime.now(UTC), trigger_id, False)

    @trigger_app.command("remove")
    def remove_cmd(
        trigger_id: Annotated[str, typer.Argument(help="Trigger id.")],
    ) -> None:
        """Remove a trigger and its firing history."""
        run_remove(bootstrap.fleet_home(), trigger_id)

    @trigger_app.command("firings")
    def firings_cmd(
        trigger_id: Annotated[str, typer.Argument(help="Trigger id.")],
        limit: Annotated[
            int, typer.Option("--limit", "-n", help="Maximum firings to list.")
        ] = _FIRINGS_DEFAULT_LIMIT,
    ) -> None:
        """List one trigger's firing history."""
        run_firings(bootstrap.fleet_home(), trigger_id, limit)

    @trigger_app.command("test")
    def test_cmd(
        trigger_id: Annotated[str, typer.Argument(help="Trigger id.")],
    ) -> None:
        """Dry run: poll the source now and print decide() per event."""
        run_test(bootstrap.fleet_home(), datetime.now(UTC), trigger_id)
