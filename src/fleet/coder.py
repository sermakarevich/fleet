from abc import ABC, abstractmethod
from pathlib import Path

from fleet.schemas import Event, Task


class Coder(ABC):
    name: str
    context_limit: int = 200_000

    @abstractmethod
    def build_argv(self, task: Task, task_dir: Path) -> list[str]:
        """Return the argv list to spawn the coder CLI subprocess."""

    @abstractmethod
    def env(self, task: Task, task_dir: Path) -> dict[str, str]:
        """Return env-var overlay merged over os.environ when spawning.

        MUST include FLEET_TASK_ID, FLEET_TASK_DIR, FLEET_ARTIFACT_DIR.
        MUST NOT include ANTHROPIC_API_KEY (owned by the CLI).
        """

    @abstractmethod
    def normalize_event(self, raw_line: str) -> Event | None:
        """Parse one line of subprocess stdout into a normalized Event.

        Returns None for malformed JSON or lines the coder wants to drop.
        SHALL be pure: no I/O, no logging, no side effects.
        """
