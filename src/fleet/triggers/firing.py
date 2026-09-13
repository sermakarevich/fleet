"""Firing policy for event triggers: decide, open, and tick every trigger.

Pure `decide()` answers "should this event open a task or be skipped"
(ADR 0006 rule "pure policy is a pure function"); `fire()` is the one
writer of firing rows, and `fire_due()` ticks every enabled trigger. Called
by the supervisor's trigger service; mirrors `schedules/firing.py`.
"""

from __future__ import annotations

import json
import shlex
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from fleet.beads.client import BdError
from fleet.beads.queue import Queue
from fleet.state import paths as state_paths
from fleet.state.task_meta import TaskMeta
from fleet.triggers.model import Firing, Trigger, TriggerEvent
from fleet.triggers.render import render
from fleet.triggers.sources import UnknownSource, source_for
from fleet.triggers.sources.base import SourceContext
from fleet.triggers.store import TriggerStore

#: What the firing policy wants: open a task or skip this event.
Action = Literal["open", "skip"]


@dataclass(frozen=True, slots=True)
class Decision:
    """The pure outcome of `decide()`: an action plus why."""

    action: Action
    reason: str = ""


def _as_utc(moment: datetime) -> datetime:
    """Return `moment` as aware UTC (naive values are assumed UTC)."""
    if moment.tzinfo is None:
        return moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC)


def _parse_moment(raw: str) -> datetime | None:
    """Parse a stored ISO-8601 timestamp, or None when unparseable."""
    try:
        return _as_utc(datetime.fromisoformat(raw))
    except (TypeError, ValueError):
        return None


def decide(
    trigger: Trigger,
    event: TriggerEvent,
    *,
    already_fired: bool,
    open_count: int,
    last_fired_at: datetime | None,
    now: datetime,
    rendered_cwd: str | None = None,
) -> Decision:
    """Say whether `event` opens a task for `trigger`, or why it is skipped."""
    if not trigger.enabled:
        return Decision("skip", "disabled")
    if already_fired:
        return Decision("skip", f"already fired for {event.key}")
    if trigger.cwd and (not rendered_cwd or "{{" in rendered_cwd):
        return Decision("skip", "cwd template rendered empty")
    if open_count >= trigger.max_open:
        return Decision("skip", f"max_open {trigger.max_open} reached")
    if last_fired_at is not None and trigger.cooldown_sec > 0:
        until = _as_utc(last_fired_at) + timedelta(seconds=trigger.cooldown_sec)
        if until > _as_utc(now):
            return Decision("skip", f"cooldown until {until.isoformat()}")
    return Decision("open")


def _metadata(
    trigger: Trigger, event: TriggerEvent, n: int, *, cwd: str | None
) -> dict[str, Any]:
    """Bead metadata mirroring `beads/create_args.py` fleet_* keys."""
    meta: dict[str, Any] = {
        "fleet_trigger_id": trigger.id,
        "fleet_trigger_event": event.key,
        "fleet_trigger_n": n,
    }
    if cwd is not None:
        meta["fleet_cwd"] = cwd
    if trigger.coder is not None:
        meta["fleet_coder"] = trigger.coder
    if trigger.model is not None:
        meta["fleet_model"] = trigger.model
    if trigger.isolation is not None:
        meta["fleet_isolation"] = trigger.isolation
    return meta


def _extra_args(trigger: Trigger, event: TriggerEvent, n: int, *, cwd: str | None) -> str:
    """Extra `bd create` args: priority, labels, and quoted metadata JSON."""
    labels = ",".join(["trigger:" + trigger.id, *trigger.labels])
    metadata = shlex.quote(json.dumps(_metadata(trigger, event, n, cwd=cwd)))
    return f"-p {trigger.priority} -l {labels} --metadata {metadata}"


def open_task(
    trigger: Trigger,
    event: TriggerEvent,
    queue: Queue,
    firing_n: int,
    fleet_home: Path | None = None,
) -> str:
    """Render the template, open one bead from it, and return the task id."""
    title = render(trigger.title, trigger=trigger, event=event, firing_n=firing_n)
    description = render(trigger.description, trigger=trigger, event=event, firing_n=firing_n)
    cwd = render(trigger.cwd or "", trigger=trigger, event=event, firing_n=firing_n) or None
    task = queue.create_task(
        title,
        description or None,
        cwd=cwd,
        coder=trigger.coder,
        model=trigger.model,
        extra_args=_extra_args(trigger, event, firing_n, cwd=cwd),
    )
    if trigger.isolation is not None:
        queue.set_overrides(
            task.id,
            coder=trigger.coder,
            model=trigger.model,
            worker=None,
            isolation=trigger.isolation,
            job_gate=None,
        )
    if fleet_home is not None:
        TaskMeta.update(state_paths.task_dir(fleet_home, task.id), fleet_trigger_id=trigger.id)
    return task.id


def open_count(trigger: Trigger, queue: Queue) -> int:
    """Not-yet-closed beads opened by `trigger` (0 when the query fails)."""
    try:
        tasks = queue.list_by_metadata("fleet_trigger_id", trigger.id)
    except Exception:
        return 0
    return len([task for task in tasks if task.status != "closed"])


def fire(
    trigger: Trigger,
    event: TriggerEvent,
    *,
    store: TriggerStore,
    queue: Queue,
    now: datetime,
    fleet_home: Path | None = None,
) -> Firing:
    """Open one bead for `event` and append its firing row (the one writer)."""
    n = store.firing_count(trigger.id) + 1
    try:
        task_id = open_task(trigger, event, queue, n, fleet_home)
    except BdError as exc:
        firing = Firing(
            trigger_id=trigger.id,
            n=n,
            event_key=event.key,
            fired_at=_as_utc(now).isoformat(),
            task_id=None,
            skipped=True,
            reason=f"bd error: {exc}",
        )
        store.append_firing(firing)
        raise
    firing = Firing(
        trigger_id=trigger.id,
        n=n,
        event_key=event.key,
        fired_at=_as_utc(now).isoformat(),
        task_id=task_id,
        skipped=False,
    )
    store.append_firing(firing)
    return firing


def _last_fired_at(store: TriggerStore, trigger_id: str) -> datetime | None:
    """Newest firing time for a trigger, or None when there is none."""
    last = store.last_firing(trigger_id)
    if last is None:
        return None
    return _parse_moment(last.fired_at)


def _fire_one_trigger(  # noqa: PLR0913  # one tick, one call-site shape
    trigger: Trigger,
    *,
    store: TriggerStore,
    queue: Queue,
    fleet_home: Path,
    now: datetime,
    log: Any,
    fired: list[Firing],
) -> None:
    """Poll one trigger's source and open one bead per event worth opening."""
    source = source_for(trigger.source)
    events = source.poll(
        SourceContext(
            fleet_home=fleet_home,
            queue=queue,
            now=now,
            params=dict(trigger.source_params),
        )
    )
    count = open_count(trigger, queue)
    last_at = _last_fired_at(store, trigger.id)
    for event in events:
        n = store.firing_count(trigger.id) + 1
        rendered_cwd = (
            render(trigger.cwd, trigger=trigger, event=event, firing_n=n) if trigger.cwd else None
        )
        decision = decide(
            trigger,
            event,
            already_fired=store.has_fired(trigger.id, event.key),
            open_count=count,
            last_fired_at=last_at,
            now=now,
            rendered_cwd=rendered_cwd,
        )
        if decision.action != "open":
            if decision.reason == "cwd template rendered empty":
                log.warning("trigger_skipped", trigger_id=trigger.id, reason=decision.reason)
            elif not decision.reason.startswith("already fired"):
                log.debug("trigger_skipped", trigger_id=trigger.id, reason=decision.reason)
            continue
        try:
            firing = fire(trigger, event, store=store, queue=queue, now=now, fleet_home=fleet_home)
        except Exception as exc:
            log.error("trigger_fire_failed", trigger_id=trigger.id, error=str(exc))
            continue
        count += 1
        last_at = _parse_moment(firing.fired_at) or _as_utc(now)
        log.info(
            "trigger_fired", trigger_id=trigger.id, event_key=event.key, task_id=firing.task_id
        )
        fired.append(firing)


def fire_due(
    *,
    store: TriggerStore,
    queue: Queue,
    fleet_home: Path,
    now: datetime,
    log: Any,
) -> list[Firing]:
    """Decide and fire every enabled trigger; one failure never stops the rest."""
    fired: list[Firing] = []
    for trigger in store.list():
        if not trigger.enabled:
            continue
        try:
            _fire_one_trigger(
                trigger,
                store=store,
                queue=queue,
                fleet_home=fleet_home,
                now=now,
                log=log,
                fired=fired,
            )
        except UnknownSource:
            log.warning("trigger_source_unknown", trigger_id=trigger.id, source=trigger.source)
        except Exception as exc:
            log.error("trigger_fire_failed", trigger_id=trigger.id, error=str(exc))
    return fired
