from pathlib import Path

import pytest

from fleet.beads.queue import BeadsQueue


@pytest.fixture
def queue(tmp_path: Path) -> BeadsQueue:
    return BeadsQueue(repo_root=tmp_path)
