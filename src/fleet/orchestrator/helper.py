"""Supervisor service that spawns a priority-0 helper bead per block event.

See docs/design/blocked-task-helper.md. Each tick scans blocked beads;
every automatic block (task.json ``blocked_reason`` set, no active
``ignore_until``) without a live helper for its current ``blocked_at``
gets one helper bead rendered from templates/HELPER_INVESTIGATE.md. The
helper worker investigates, asks the operator, and implements the fix
itself; this service only creates the bead.

Helpers form a chain per original task: every helper carries
``chain_root`` (the first blocked task) and ``chain_seq`` (1, 2, ...). A
blocked helper is scanned like any other bead, so its own helper keeps the
same ``chain_root``. When the newest report in a chain says its root cause
repeats an earlier one, the chain stops and the operator gets one summary
question instead of another helper.
"""

from __future__ import annotations

import json
import shlex
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from fleet.beads.queue import Queue
from fleet.core.errors import FleetError
from fleet.core.helper_report import HelperReport, parse_report
from fleet.core.ignore_policy import ignore_active
from fleet.core.limits import STATUS_LOG_INTERVAL_SEC
from fleet.core.retry_policy import rounds_for_history
from fleet.core.task import TaskStatus
from fleet.orchestrator.service import ServiceOrder, run_periodic
from fleet.state import paths as state_paths
from fleet.state.attempt_summary import render_markdown, summarize
from fleet.state.attempts import latest_attempt_dir, load_attempts
from fleet.state.helper_report import read_report
from fleet.state.task_meta import TaskMeta

if TYPE_CHECKING:
    from fleet.core.config import RuntimeConfig
    from fleet.integrations.ask_human.store import QuestionStore

    from .state import SupervisorState

HELPER_TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "HELPER_INVESTIGATE.md"
_STDERR_TAIL_CHARS = 1500


def _read_meta(fleet_home: Path, task_id: str) -> dict:
    """Read task.json; {} when missing or unparsable."""
    try:
        data = json.loads((state_paths.task_dir(fleet_home, task_id) / "task.json").read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _is_helper_live(queue: Queue, helper_id: str) -> bool:
    """True when the helper bead is not provably closed (lookup errors count as live)."""
    try:
        return queue.get(helper_id).status != TaskStatus.CLOSED.value
    except Exception:
        return True


def _has_live_helper(queue: Queue, meta: dict) -> bool:
    """True when the task's last helper is still live, whatever block event it was for.

    A task that is retried and re-blocks quickly gets a new ``blocked_at``
    each time; matching on it would spawn one helper per re-block while the
    first is still working. A fresh helper is spawned only once it closes.
    """
    helper_id = meta.get("helper_task_id")
    if not isinstance(helper_id, str) or not helper_id:
        return False
    return _is_helper_live(queue, helper_id)


def collect_targets(
    queue: Queue,
    fleet_home: Path,
    config: RuntimeConfig,  # unused today; kept for a stable call shape
    now: datetime,
) -> list[dict]:
    """Blocked beads that should get a helper this tick.

    Skipped: human-blocked beads (no task.json ``blocked_reason``), beads
    with an active ``ignore_until``, and beads that already have a live
    helper (for any block event). A bead whose meta cannot be
    read is skipped too, never raised.
    """
    try:
        blocked = queue.list_blocked(limit=100)
    except Exception:
        return []
    targets: list[dict] = []
    for bead in blocked:
        try:
            meta = _read_meta(fleet_home, bead.id)
            blocked_reason = meta.get("blocked_reason")
            if not blocked_reason:
                continue
            if ignore_active(meta.get("ignore_until"), now):
                continue
            if _has_live_helper(queue, meta):
                continue
            targets.append(
                {
                    "id": bead.id,
                    "title": meta.get("title") or bead.title,
                    "blocked_reason": blocked_reason,
                    "blocked_at": meta.get("blocked_at"),
                    "cwd": meta.get("cwd") or bead.cwd,
                    "meta": meta,
                }
            )
        except Exception:  # noqa: BLE001 - one unreadable bead must not stop the scan
            continue
    return targets


def _chain_root(meta: dict, task_id: str) -> str:
    """Chain root of a bead: its ``chain_root`` when it is a helper, else itself."""
    return meta.get("chain_root") or task_id


def _chain_beads(queue: Queue, fleet_home: Path, root_id: str) -> list[tuple[int, str]]:
    """(chain_seq, id) of every helper in the chain, oldest first.

    Membership comes from bd metadata (``chain_root``, written by
    ``bd create --metadata``); ``chain_seq`` is read from the helper's
    task.json mirror since ``Task`` does not carry bd metadata.
    """
    beads = queue.list_by_metadata("chain_root", root_id)
    seqs: list[tuple[int, str]] = []
    for bead in beads:
        seq = _read_meta(fleet_home, bead.id).get("chain_seq", 0)
        seqs.append((seq if isinstance(seq, int) else 0, bead.id))
    return sorted(seqs)


def chain_reports(queue: Queue, fleet_home: Path, root_id: str) -> list[HelperReport]:
    """Parsed HELPER_REPORT.md of every helper in the chain, oldest first.

    Helpers that have not written a report yet are skipped.
    """
    reports: list[HelperReport] = []
    for _, bead_id in _chain_beads(queue, fleet_home, root_id):
        found = read_report(state_paths.task_dir(fleet_home, bead_id))
        if found is None:
            continue
        text, _path = found
        reports.append(parse_report(text))
    return reports


def _next_chain_seq(queue: Queue, fleet_home: Path, root_id: str) -> int:
    """Sequence number for the next helper in the chain (1 for the first)."""
    seqs = [seq for seq, _ in _chain_beads(queue, fleet_home, root_id)]
    return max([0, len(seqs), *seqs]) + 1


def _prior_reports_text(reports: list[HelperReport]) -> str:
    """Numbered root cause + evidence blocks for the template; "" when none."""
    blocks = []
    for n, report in enumerate(reports, start=1):
        root_cause = report.root_cause or "(not stated)"
        evidence = report.evidence or "(not stated)"
        blocks.append(f"{n}. Root cause: {root_cause}\n   Evidence: {evidence}")
    return "\n\n".join(blocks)


def _stderr_tail(task_dir: Path) -> str | None:
    """Tail of the latest attempt's derived summary, if any."""
    attempt_dir = latest_attempt_dir(task_dir)
    if attempt_dir is None:
        return None
    try:
        n = int(attempt_dir.name)
    except ValueError:
        return None
    try:
        text = render_markdown(summarize(task_dir, n))
    except (OSError, ValueError):
        return None
    tail = text.strip()[-_STDERR_TAIL_CHARS:]
    return tail or None


def _render_description(
    cand: dict, chain_root_id: str, reports: list[HelperReport], fleet_home: Path
) -> str:
    """Render HELPER_INVESTIGATE.md for one target (str.format, like prompts)."""
    task_dir = state_paths.task_dir(fleet_home, cand["id"])
    return HELPER_TEMPLATE.read_text(encoding="utf-8").format(
        target_id=cand["id"],
        title=cand["title"],
        blocked_reason=cand["blocked_reason"],
        blocked_at=cand["blocked_at"],
        cwd=cand["cwd"],
        task_dir=str(task_dir),
        rounds=rounds_for_history(load_attempts(task_dir)),
        stderr_tail=_stderr_tail(task_dir) or "(none)",
        prior_reports=_prior_reports_text(reports) or "(none — this is the first helper)",
        chain_root_id=chain_root_id,
    )


def spawn_helper(  # noqa: PLR0913, PLR0917 - mirrors the spec'd call shape
    queue: Queue,
    fleet_home: Path,
    config: RuntimeConfig,
    cand: dict,
    chain_root_id: str,
    chain_seq: int,
    reports: list[HelperReport],
) -> None:
    """Create one priority-0 helper bead for ``cand`` and link it both ways.

    The target's task.json gets ``helper_task_id``/``helper_blocked_at``
    (dedup); the helper's task.json mirrors its chain metadata so a later
    tick can read ``chain_root``/``chain_seq`` when the helper itself blocks.
    """
    description = _render_description(cand, chain_root_id, reports, fleet_home)
    metadata = {"chain_root": chain_root_id, "helper_for": cand["id"], "chain_seq": chain_seq}
    extra_args = (
        "--priority 0 --metadata "
        + shlex.quote(json.dumps(metadata))
        + f" -l helper,helps:{cand['id']},chain:{chain_root_id}"
    )
    helper = queue.create_task(
        f'Helper: unblock {cand["id"]} ("{cand["title"]}")',
        description=description,
        cwd=cand["cwd"],
        coder=config.helper_coder,
        model=config.helper_model,
        extra_args=extra_args,
    )
    TaskMeta.update(state_paths.task_dir(fleet_home, helper.id), **metadata)
    TaskMeta.update(
        state_paths.task_dir(fleet_home, cand["id"]),
        helper_task_id=helper.id,
        helper_blocked_at=cand["blocked_at"],
    )


def progress_check(reports: list[HelperReport]) -> bool:
    """True ("stop the chain") when the newest report repeats an earlier root cause."""
    return bool(reports) and reports[-1].same_as_previous is True


def chain_summary_text(reports: list[HelperReport]) -> str:
    """Plain-text summary of a stopped chain for the operator question (FR-24)."""
    paragraphs = [
        "Helpers stopped: the latest helper found the same root cause as an earlier one.",
    ]
    for n, report in enumerate(reports, start=1):
        paragraphs.append(
            f"Helper {n}: root cause: {report.root_cause or '(not stated)'}\n"
            f"Proposed fixes: {report.proposed_fixes or '(none)'}"
        )
    return "\n\n".join(paragraphs)


def _stop_chain(st: SupervisorState, store: QuestionStore, root_id: str, reports) -> bool:
    """Ask the operator once per stopped chain; True when a question was posted."""
    if _read_meta(st.fleet_home, root_id).get("chain_stopped"):
        return False
    store.ask(
        chain_summary_text(reports),
        None,
        task_id=root_id,
        context=f"chain-stopped:{root_id}",
        agent_id="helper",
    )
    TaskMeta.update(state_paths.task_dir(st.fleet_home, root_id), chain_stopped=True)
    return True


def helper_tick(st: SupervisorState, store: QuestionStore) -> dict:
    """Run one helper pass: spawn helpers or stop chains that stopped progressing."""
    summary = {"spawned": 0, "skipped": 0, "chain_stopped": 0}
    if not st.config.helper_enabled:
        return summary
    for cand in collect_targets(st.queue, st.fleet_home, st.config, st.clock.now()):
        try:
            chain_root_id = _chain_root(cand["meta"], cand["id"])
            reports = chain_reports(st.queue, st.fleet_home, chain_root_id)
            if progress_check(reports):
                summary["skipped"] += 1
                if _stop_chain(st, store, chain_root_id, reports):
                    summary["chain_stopped"] += 1
                continue
            seq = _next_chain_seq(st.queue, st.fleet_home, chain_root_id)
            spawn_helper(st.queue, st.fleet_home, st.config, cand, chain_root_id, seq, reports)
            summary["spawned"] += 1
        except Exception as exc:  # noqa: BLE001 - one bad bead skips, rest continue
            st.log.warning("helper_spawn_failed", task_id=cand.get("id"), error=str(exc))
            summary["skipped"] += 1
    return summary


class HelperSpawn:
    """Create a priority-0 helper bead for every automatically blocked task."""

    order = ServiceOrder.Helper
    name = "helper"

    def __init__(self, store: QuestionStore | None = None) -> None:
        self._store = store

    def _question_store(self) -> QuestionStore:
        """Return the injected ask_human question store."""
        if self._store is None:
            raise FleetError("HelperSpawn service needs a question store; pass store=...")
        return self._store

    async def _tick(self, st: SupervisorState) -> None:
        """Run helper_tick(); log and swallow failures so the loop survives."""
        try:
            summary = helper_tick(st, self._question_store())
        except Exception as exc:  # noqa: BLE001 - helper must not kill the loop
            st.log.warning("helper_tick_failed", error=str(exc))
        else:
            st.log.info("helper_tick", **summary)

    async def serve(self, st: SupervisorState) -> None:
        """Run a helper pass every STATUS_LOG_INTERVAL_SEC until shutdown."""
        await run_periodic(self.name, STATUS_LOG_INTERVAL_SEC, self._tick, st)
