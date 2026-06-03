import json
import os
import shlex
import shutil
import subprocess
from abc import ABC, abstractmethod
from pathlib import Path

from fleet.schemas import Task


class BeadsError(RuntimeError):
    pass


class Queue(ABC):
    @abstractmethod
    def claim_next(self, claimer_id: str) -> Task | None: ...

    @abstractmethod
    def release(self, task_id: str, reason: str = "") -> None: ...

    @abstractmethod
    def set_blocked(self, task_id: str, reason: str) -> None: ...

    @abstractmethod
    def close(self, task_id: str, reason: str = "completed") -> None: ...

    @abstractmethod
    def comment(self, task_id: str, body: str) -> None: ...

    @abstractmethod
    def get(self, task_id: str) -> Task: ...

    @abstractmethod
    def list_ready(self, limit: int = 50) -> list[Task]: ...

    @abstractmethod
    def list_in_progress(self, limit: int = 50) -> list[Task]: ...

    @abstractmethod
    def freeze_coder_model(self, task_id: str, coder: str, model: str) -> None: ...

    @abstractmethod
    def delete(self, task_id: str) -> None: ...

    @abstractmethod
    def create_task(
        self,
        title: str,
        description: str | None = None,
        depends_on: list[str] | None = None,
        labels: list[str] | None = None,
        cwd: str | None = None,
        coder: str | None = None,
        model: str | None = None,
        extra_args: str | None = None,
    ) -> Task: ...


class BeadsQueue(Queue):
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root

    def _meta_path(self, task_id: str) -> Path:
        return self.repo_root / "tasks" / task_id / "task.json"

    def _load_meta(self, task_id: str) -> dict:
        path = self._meta_path(task_id)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _write_meta(self, task_id: str, data: dict) -> None:
        path = self._meta_path(task_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def set_cwd(self, task_id: str, cwd: str) -> None:
        """Persist invocation cwd into task.json, preserving other fields if present."""
        meta = self._load_meta(task_id) or {"id": task_id}
        meta["cwd"] = cwd
        self._write_meta(task_id, meta)

    def set_overrides(
        self,
        task_id: str,
        coder: str | None = None,
        model: str | None = None,
    ) -> None:
        """Persist per-task coder/model overrides into task.json.

        Only the non-None fields are written; existing meta keys are preserved.
        Distinct from freeze_coder_model, which writes both fields at spawn time.
        """
        if coder is None and model is None:
            return
        meta = self._load_meta(task_id) or {"id": task_id}
        if coder is not None:
            meta["coder"] = coder
        if model is not None:
            meta["model"] = model
        self._write_meta(task_id, meta)

    def freeze_coder_model(self, task_id: str, coder: str, model: str) -> None:
        """Lock the effective coder and model into task.json at first spawn.

        Called once per execution start so that config changes to runtime.toml
        after a task begins do not affect retries or context-pressure reclaims.
        """
        meta = self._load_meta(task_id) or {"id": task_id}
        meta["coder"] = coder
        meta["model"] = model
        self._write_meta(task_id, meta)

    def _snapshot_meta(
        self,
        body: dict,
        status: str | None = None,
        cwd: str | None = None,
        coder: str | None = None,
        model: str | None = None,
    ) -> dict:
        """Build a task.json payload from a bd body, preserving prior fleet fields."""
        existing = self._load_meta(body["id"])
        return {
            "id": body["id"],
            "title": body.get("title", existing.get("title")),
            "description": body.get("description", existing.get("description")),
            "status": status or body.get("status") or existing.get("status", "open"),
            "cwd": cwd if cwd is not None else existing.get("cwd"),
            "coder": coder if coder is not None else existing.get("coder"),
            "model": model if model is not None else existing.get("model"),
        }

    def _bd(self, *args: str, json_envelope: bool = True, actor: str | None = None) -> dict | None:
        env = {**os.environ}
        if json_envelope:
            env["BD_JSON_ENVELOPE"] = "1"
        if actor is not None:
            env["BEADS_ACTOR"] = actor
        result = subprocess.run(
            ["bd", *args],
            capture_output=True,
            text=True,
            env=env,
            cwd=self.repo_root,
        )
        if result.returncode != 0:
            raise BeadsError(result.stderr.strip())
        if json_envelope and result.stdout.strip():
            return json.loads(result.stdout)
        return None

    def _task_from_dict(self, body: dict, *, status_override: str | None = None) -> Task:
        meta = self._load_meta(body["id"])
        return Task(
            id=body["id"],
            title=body["title"],
            description=body.get("description"),
            status=status_override or body.get("status", "open"),
            cwd=meta.get("cwd"),
            coder=meta.get("coder"),
            model=meta.get("model"),
        )

    def claim_next(self, claimer_id: str) -> Task | None:
        ready = self._bd("ready", "--json", "--limit", "10")
        items: list = ready.get("data", ready) if isinstance(ready, dict) else (ready or [])
        if not isinstance(items, list):
            items = []
        for cand in items:
            try:
                self._bd("update", cand["id"], "--claim", json_envelope=False, actor=claimer_id)
            except BeadsError:
                continue
            self._write_meta(cand["id"], self._snapshot_meta(cand, status="in_progress"))
            return self._task_from_dict(cand, status_override="in_progress")
        return None

    def release(self, task_id: str, reason: str = "") -> None:
        self._bd("update", task_id, "--status", "open", "--assignee", "", json_envelope=False)
        if reason:
            self._bd("comment", task_id, reason, json_envelope=False)
        meta = self._load_meta(task_id) or {"id": task_id}
        meta["status"] = "open"
        self._write_meta(task_id, meta)

    def set_blocked(self, task_id: str, reason: str) -> None:
        self._bd("update", task_id, "--status", "blocked", "--notes", reason, json_envelope=False)
        meta = self._load_meta(task_id) or {"id": task_id}
        meta["status"] = "blocked"
        self._write_meta(task_id, meta)

    def close(self, task_id: str, reason: str = "completed") -> None:
        self._bd("close", task_id, "--reason", reason, json_envelope=False)
        meta = self._load_meta(task_id) or {"id": task_id}
        meta["status"] = "closed"
        self._write_meta(task_id, meta)

    def delete(self, task_id: str) -> None:
        self._bd("delete", task_id, "--force", json_envelope=False)
        task_dir = self.repo_root / "tasks" / task_id
        if task_dir.exists():
            shutil.rmtree(task_dir)

    def comment(self, task_id: str, body: str) -> None:
        self._bd("comment", task_id, body, json_envelope=False)

    def get(self, task_id: str) -> Task:
        data = self._bd("show", task_id, "--json")
        if data is None:
            raise BeadsError(f"bd show {task_id}: empty response")
        body = data.get("data", data) if isinstance(data, dict) else data
        if isinstance(body, list):
            if not body:
                raise BeadsError(f"bd show {task_id}: no issue returned")
            body = body[0]
        return self._task_from_dict(body)

    def list_ready(self, limit: int = 50) -> list[Task]:
        data = self._bd("ready", "--json", "--limit", str(limit))
        items: list = data.get("data", data) if isinstance(data, dict) else (data or [])
        if not isinstance(items, list):
            items = []
        return [self._task_from_dict(item) for item in items]

    def list_in_progress(self, limit: int = 50) -> list[Task]:
        data = self._bd(
            "list", "--status", "in_progress", "--json", "--limit", str(limit)
        )
        items: list = data.get("data", data) if isinstance(data, dict) else (data or [])
        if not isinstance(items, list):
            items = []
        return [
            self._task_from_dict(item, status_override="in_progress") for item in items
        ]

    def create_task(
        self,
        title: str,
        description: str | None = None,
        depends_on: list[str] | None = None,
        labels: list[str] | None = None,
        cwd: str | None = None,
        coder: str | None = None,
        model: str | None = None,
        extra_args: str | None = None,
    ) -> Task:
        args = ["create", "--title", title, "--json"]
        if description:
            args += ["--description", description]
        if extra_args:
            args += shlex.split(extra_args)
        data = self._bd(*args)
        body = data.get("data", data) if isinstance(data, dict) else data
        task_id = (body or {}).get("id", "") if isinstance(body, dict) else ""
        if not task_id:
            raise BeadsError("bd create returned no task id")
        if depends_on:
            for dep_id in depends_on:
                self._bd("dep", "add", task_id, dep_id, json_envelope=False)
        # Snapshot the fresh task (title/description/status) into task.json,
        # adding fleet-managed fields (cwd, coder, model) if provided.
        self._write_meta(
            task_id,
            self._snapshot_meta(body or {"id": task_id}, cwd=cwd, coder=coder, model=model),
        )
        return self.get(task_id)
