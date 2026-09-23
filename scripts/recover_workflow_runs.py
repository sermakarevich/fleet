"""One-shot recovery: rebuild workflow_runs + workflow_run_steps wiped by the
fleet-folie cascade delete (INSERT OR REPLACE on workflows, 2026-09-22).

Reads the surviving on-disk truth — beads (labels + metadata
fleet_workflow_id/fleet_workflow_run/fleet_workflow_step), per-run work dirs
(~/.fleet/workflows/summarise/<run_id>/chunks.json + source.md), and closed
steps' ~/.fleet/tasks/<task_id>/outputs.json — regenerates each run's expanded
spec offline with builders.summarise._stages (never re-fetches the source),
and inserts the run + step rows.

Only runs with at least one non-closed bead are rebuilt (finished history
stays gone; nothing needs releasing there).

Usage:
    uv run python scripts/recover_workflow_runs.py [--dry-run] [--check-release]
        [--db PATH] [--fleet-home PATH] [--beads-json PATH]
        [--backup PATH | --no-backup] [--create-missing] [--repair-labels]
        [--run wfr-xxx (--run wfr-yyy ...)]

    --dry-run: print what would be inserted, write nothing.
    --check-release: read-only simulation of runs._release_ready rendering
        against the (rebuilt) store + live beads; exits nonzero when a step
        whose dependencies all closed would NOT render cleanly.
    --create-missing: recreate beads the run should have but doesn't
        (wfr-3lrdcthc lost verify+file) via the same _open_step path
        start_run uses (raw text, DEFER_FAR, deps wired).
    --repair-labels: re-add missing run:/step: labels (fleet-e2ubu lost its).
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
import sys
from dataclasses import replace
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from fleet.beads.queue import BeadsQueue  # noqa: E402
from fleet.state.paths import read_outputs, task_dir  # noqa: E402
from fleet.workflows.builders.chunking import CHUNK_CHARS_DEFAULT, Chunk  # noqa: E402
from fleet.workflows.builders.sources import Source, SourceKind  # noqa: E402
from fleet.workflows.builders.summarise import _stages  # noqa: E402
from fleet.workflows.model import (  # noqa: E402
    RunStatus,
    Trigger,
    Workflow,
    WorkflowRun,
    dependencies_of,
    ensure_valid,
)
from fleet.workflows.planning import plan  # noqa: E402
from fleet.workflows.runs import DEFER_FAR, _open_step  # noqa: E402
from fleet.workflows.store import WorkflowStore  # noqa: E402
from fleet.workflows.templates import TemplateContext, render_with_missing  # noqa: E402

WORKFLOW_ID = "wf-hgtt7ao2"
BUILDER = "summarise"
KNOWN_STATUSES = {"open", "in_progress", "blocked", "closed"}


def parse_source_header(text: str) -> tuple[str, str, SourceKind, str]:
    """Title, url, kind, tool from a run work dir source.md provenance header."""
    lines = text.splitlines()
    if not lines or not lines[0].startswith("# "):
        raise ValueError("source.md: first line is not a '# title' header")
    title = lines[0][2:].strip()
    fields: dict[str, str] = {}
    for line in lines[1:9]:
        for key in ("Source:", "Kind:", "Fetched:", "Tool:"):
            if line.startswith(key):
                fields[key] = line[len(key):].strip()
    for key in ("Source:", "Kind:", "Tool:"):
        if not fields.get(key):
            raise ValueError(f"source.md: missing {key} provenance line")
    try:
        kind = SourceKind(fields["Kind:"])
    except ValueError:
        raise ValueError(f"source.md: unknown kind {fields['Kind:']!r}") from None
    return title, fields["Source:"], kind, fields["Tool:"]


def chunks_from_manifest(workdir: Path, records: list[dict]) -> list[Chunk]:
    """Chunk list for _stages; validates slugs against the on-disk chunk files."""
    chunks: list[Chunk] = []
    for record in records:
        chunk = Chunk(index=int(record["index"]), title=str(record["title"]), text="")
        if chunk.slug != record["slug"]:
            raise ValueError(
                f"{workdir.name}: chunk slug skew: manifest {record['slug']!r} "
                f"!= derived {chunk.slug!r} (title {record['title']!r})"
            )
        body = workdir / "chunks" / f"{chunk.slug}.md"
        if not body.is_file():
            alt = Path(str(record.get("path") or ""))
            if not (alt.is_file() and alt.name == f"{chunk.slug}.md"):
                raise ValueError(f"{workdir.name}: missing chunk body {body}")
        chunks.append(chunk)
    if [c.index for c in chunks] != sorted(c.index for c in chunks):
        raise ValueError(f"{workdir.name}: chunks.json not in index order")
    return chunks


def build_expanded_spec(
    base: Workflow, url: str, kind: SourceKind, title: str, tool: str,
    chunks: list[Chunk], workdir: Path,
) -> Workflow:
    """Regenerate the run's frozen spec offline (no fetch, no writes)."""
    source = Source(url=url, kind=kind, title=title, text="", tool=tool)
    stages = _stages(source, chunks, workdir, url)
    expanded = replace(replace(base, stages=stages), builder=None)
    ensure_valid(expanded)
    return expanded


def norm_stamp(raw: str) -> str:
    """Bead 'Z' stamps to the '+00:00' shape the store writes elsewhere."""
    text = str(raw or "")
    return text[:-1] + "+00:00" if text.endswith("Z") else text


def load_beads(beads_json: str | None) -> list[dict]:
    """Live beads with the workflow label (bd subprocess or a JSON file)."""
    if beads_json is not None:
        return json.loads(Path(beads_json).read_text(encoding="utf-8"))
    proc = subprocess.run(
        ["bd", "list", "-l", f"workflow:{WORKFLOW_ID}", "--all", "-n", "0", "--json"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"bd list failed: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def run_groups(beads: list[dict]) -> dict[str, list[dict]]:
    """Beads by metadata run id, keeping only runs with a non-closed bead."""
    groups: dict[str, list[dict]] = {}
    for bead in beads:
        run_id = (bead.get("metadata") or {}).get("fleet_workflow_run", "")
        if run_id:
            groups.setdefault(run_id, []).append(bead)
    return {
        run_id: items
        for run_id, items in groups.items()
        if any(item.get("status") != "closed" for item in items)
    }


def reconstruct_run(
    run_id: str,
    beads: list[dict],
    base: Workflow,
    fleet_home: Path,
    chunk_chars_default: str,
) -> tuple[WorkflowRun, list[dict], Workflow, dict[str, list[str]]]:
    """Rebuilt run row + per-bead step info + expanded spec + stage index map."""
    workdir = fleet_home / "workflows" / BUILDER / run_id
    header = (workdir / "source.md").read_text(encoding="utf-8")
    title, url, kind, tool = parse_source_header(header)
    records = json.loads((workdir / "chunks.json").read_text(encoding="utf-8"))
    chunks = chunks_from_manifest(workdir, records)
    expanded = build_expanded_spec(base, url, kind, title, tool, chunks, workdir)
    stage_of = {planned.step.name: planned.stage_index for planned in plan(expanded)}

    spec_steps = set(stage_of)
    bead_steps = {
        (bead.get("metadata") or {}).get("fleet_workflow_step", "") for bead in beads
    }
    unknown = bead_steps - spec_steps - {""}
    if unknown:
        raise ValueError(f"{run_id}: beads for unknown steps {sorted(unknown)}")
    if "" in bead_steps:
        raise ValueError(f"{run_id}: a bead has no fleet_workflow_step metadata")

    started_at = min(norm_stamp(bead.get("created_at", "")) for bead in beads)
    missing = sorted(spec_steps - bead_steps)
    step_infos: list[dict] = []
    for bead in beads:
        status = str(bead.get("status", ""))
        if status not in KNOWN_STATUSES:
            raise ValueError(f"{run_id}: bead {bead['id']} status {status!r}")
        step_name = (bead.get("metadata") or {})["fleet_workflow_step"]
        outputs = read_outputs(task_dir(fleet_home, str(bead["id"])))
        step_infos.append(
            {
                "step_name": step_name,
                "stage_index": stage_of[step_name],
                "task_id": str(bead["id"]),
                "task_status": status,
                "updated_at": norm_stamp(str(bead.get("updated_at") or "")),
                "outputs": {str(k): str(v) for k, v in outputs.items()},
                "released": not bead.get("defer_until"),
            }
        )
    run = WorkflowRun(
        id=run_id,
        workflow_id=WORKFLOW_ID,
        n=0,  # assigned by started_at order after all runs reconstruct
        trigger=Trigger.manual,
        schedule_id=None,
        spec=expanded,
        status=RunStatus.running,
        started_at=started_at,
        inputs={
            "url": url,
            "chunk_chars": chunk_chars_default,
            "research_target": "",
        },
    )
    return run, step_infos, expanded, {"missing": missing}


def backup_db(db_path: Path, dest: Path | None) -> Path:
    """Copy the live db via the sqlite backup API (safe under a running supervisor)."""
    target = dest or db_path.with_name(
        f"{db_path.name}.bak-{datetime.now().strftime('%Y%m%dT%H%M%S')}"
    )
    src = sqlite3.connect(db_path)
    dst = sqlite3.connect(target)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return target


def check_release(store: WorkflowStore, beads: list[dict]) -> list[str]:
    """Read-only release simulation: steps whose deps closed must render cleanly.

    Mirrors runs._release_ready's render decision without touching beads.
    Returns human problem lines (empty means the release pass will proceed).
    """
    problems: list[str] = []
    live = {str(b["id"]): str(b.get("status", "")) for b in beads}
    for run in store.list_runs(limit=10_000):
        if run.workflow_id != WORKFLOW_ID or run.status not in (
            RunStatus.running,
            RunStatus.attention,
        ):
            continue
        steps = store.step_runs(run.id)
        by_name = {s.step_name: s for s in steps}
        closed = {
            s.step_name
            for s in steps
            if live.get(s.task_id, s.task_status) == "closed"
        }
        try:
            run_date = datetime.fromisoformat(run.started_at).date().isoformat()
        except ValueError:
            problems.append(f"{run.id}: bad started_at {run.started_at!r}")
            continue
        for step in steps:
            if step.released:
                continue
            defined = {s.name: s for st in run.spec.stages for s in st.steps}.get(
                step.step_name
            )
            if defined is None:
                problems.append(f"{run.id}: step {step.step_name} not in spec")
                continue
            if any(name not in closed for name in dependencies_of(
                run.spec, step.stage_index, defined
            )):
                continue
            ctx = TemplateContext(
                workflow_name=run.spec.name,
                run_id=run.id,
                run_n=run.n,
                run_date=run_date,
                step_name=step.step_name,
                task_ids={s.step_name: s.task_id for s in steps},
                inputs=dict(run.inputs),
                step_outputs={s.step_name: dict(s.outputs) for s in steps},
            )
            _, missing_title = render_with_missing(defined.title, ctx)
            _, missing_desc = render_with_missing(defined.description, ctx)
            missing = sorted(set(missing_title) | set(missing_desc))
            if step.step_name in closed:
                continue  # refresh just records the warning, nothing to render
            if missing:
                dead = sorted(
                    m
                    for m in missing
                    if m.split(".")[1] not in by_name or m.split(".")[1] in closed
                )
                problems.append(
                    f"{run.id}: step {step.step_name} would render with "
                    f"missing={missing} dead={dead}"
                )
    return problems


def main(argv: list[str] | None = None) -> int:
    """CLI entry: reconstruct every stranded run, then insert rows."""
    parser = argparse.ArgumentParser(description="Rebuild wiped workflow runs.")
    parser.add_argument("--db", default=None)
    parser.add_argument("--fleet-home", default=None)
    parser.add_argument("--beads-json", default=None)
    parser.add_argument("--backup", default=None)
    parser.add_argument("--no-backup", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--check-release", action="store_true")
    parser.add_argument("--create-missing", action="store_true")
    parser.add_argument("--repair-labels", action="store_true")
    parser.add_argument("--run", action="append", default=None)
    args = parser.parse_args(argv)

    import os

    fleet_home = (
        Path(args.fleet_home)
        if args.fleet_home
        else Path(os.environ.get("FLEET_HOME", str(Path.home() / ".fleet")))
    )
    db_path = Path(args.db) if args.db else fleet_home / "workflows.db"
    store = WorkflowStore(db_path)
    base = store.get(WORKFLOW_ID)
    if base is None:
        print(f"error: workflow {WORKFLOW_ID} not in {db_path}", file=sys.stderr)
        return 2
    chunk_chars_default = CHUNK_CHARS_DEFAULT
    for item in base.inputs:
        if item.name == "chunk_chars" and item.default is not None:
            chunk_chars_default = item.default

    beads = load_beads(args.beads_json)
    groups = run_groups(beads)
    if args.run:
        wanted = set(args.run)
        groups = {rid: items for rid, items in groups.items() if rid in wanted}
    print(f"runs to rebuild: {len(groups)}")

    reconstructions: list[tuple[WorkflowRun, list[dict], Workflow, list[str]]] = []
    for run_id in sorted(groups):
        try:
            run, infos, expanded, extra = reconstruct_run(
                run_id, groups[run_id], base, fleet_home, chunk_chars_default
            )
        except (OSError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        reconstructions.append((run, infos, expanded, extra["missing"]))
    reconstructions.sort(key=lambda item: (item[0].started_at, item[0].id))
    for position, (run, infos, expanded, missing) in enumerate(reconstructions, start=1):
        reconstructions[position - 1] = (replace(run, n=position), infos, expanded, missing)

    for run, infos, _, missing in reconstructions:
        n_open = sum(1 for i in infos if i["task_status"] != "closed")
        print(
            f"  {run.id} n={run.n} steps={len(infos)} open={n_open} "
            f"started={run.started_at} missing_beads={missing or '-'}"
        )

    problems: list[str] = []
    if args.check_release or args.dry_run:
        mem = WorkflowStore(":memory:")
        mem.save(base)
        for run, infos, _, _ in reconstructions:
            mem.save_run(run)
            from fleet.workflows.model import StepRun as _StepRun

            mem.save_step_runs(
                [
                    _StepRun(
                        run_id=run.id,
                        step_name=i["step_name"],
                        stage_index=i["stage_index"],
                        task_id=i["task_id"],
                        task_status=i["task_status"],
                        updated_at=i["updated_at"],
                        outputs=i["outputs"],
                        released=i["released"],
                    )
                    for i in infos
                ]
            )
        problems = check_release(mem, beads)
        mem.close()
        if problems:
            print("release simulation problems:")
            for line in problems:
                print(f"  {line}")
        else:
            print("release simulation: every ready step renders cleanly")
    if args.dry_run:
        print("dry run: no rows written")
        store.close()
        return 1 if problems else 0

    saved_backup: Path | None = None
    if not args.no_backup:
        saved_backup = backup_db(db_path, Path(args.backup) if args.backup else None)
        print(f"backup: {saved_backup}")

    if args.create_missing or args.repair_labels:
        queue = BeadsQueue(fleet_home)
        ctx_now = datetime.now().astimezone()
        stamp = ctx_now.isoformat()
        run_date = ctx_now.date().isoformat()
        for run, infos, expanded, missing in reconstructions:
            task_ids = {i["step_name"]: i["task_id"] for i in infos}
            if args.repair_labels:
                for bead in groups[run.id]:
                    labels = bead.get("labels") or []
                    step = (bead.get("metadata") or {}).get("fleet_workflow_step", "")
                    want = [f"run:{run.id}", f"step:{step}"]
                    lacking = [label for label in want if label not in labels]
                    if lacking:
                        proc = subprocess.run(
                            ["bd", "label", "add", bead["id"], *lacking],
                            capture_output=True,
                            text=True,
                            check=False,
                        )
                        if proc.returncode != 0:
                            print(
                                f"error: bd label add failed: {proc.stderr.strip()}",
                                file=sys.stderr,
                            )
                            return 2
                        print(f"  labels repaired: {bead['id']} +{lacking}")
            if args.create_missing and missing:
                for planned in plan(expanded):
                    if planned.step.name not in missing:
                        continue
                    task = _open_step(
                        expanded, run, run.n, run_date, planned, task_ids,
                        queue, DEFER_FAR,
                    )
                    task_ids[planned.step.name] = task.id
                    infos.append(
                        {
                            "step_name": planned.step.name,
                            "stage_index": planned.stage_index,
                            "task_id": task.id,
                            "task_status": "open",
                            "updated_at": stamp,
                            "outputs": {},
                            "released": False,
                        }
                    )
                    print(f"  bead recreated: {task.id} step {planned.step.name}")

    from fleet.workflows.model import StepRun as _StepRun

    for run, infos, _, _ in reconstructions:
        store.save_run(run)
        store.save_step_runs(
            [
                _StepRun(
                    run_id=run.id,
                    step_name=i["step_name"],
                    stage_index=i["stage_index"],
                    task_id=i["task_id"],
                    task_status=i["task_status"],
                    updated_at=i["updated_at"],
                    outputs=i["outputs"],
                    released=i["released"],
                )
                for i in infos
            ]
        )
    print(f"inserted {len(reconstructions)} runs")
    if args.check_release and problems:
        return 1
    store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
