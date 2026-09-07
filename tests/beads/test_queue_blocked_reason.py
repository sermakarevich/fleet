import json
from pathlib import Path
from unittest.mock import patch

from fleet.beads.queue import BeadsQueue


def test_set_blocked_writes_reason_and_clears_on_release(tmp_path: Path) -> None:
    q = BeadsQueue(repo_root=tmp_path)

    def mock_bd(*args: str, json_envelope: bool = True, actor=None):
        return None

    with patch.object(q, "_bd", side_effect=mock_bd):
        q.set_blocked("t-001", "needs human review")
        meta_path = tmp_path / "tasks" / "t-001" / "task.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert meta["status"] == "blocked"
        assert meta["blocked_reason"] == "needs human review"
        assert "blocked_at" in meta

        q.release("t-001", reason="retry")
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        assert meta["status"] == "open"
        assert "blocked_reason" not in meta
        assert "blocked_at" not in meta
