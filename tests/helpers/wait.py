"""Condition waits for tests: poll a predicate instead of sleeping a fixed time.

Called by any test that waits for background work (a poller tick, a listener
loop, a daemon shutdown). The sleep lives here, inside this helper, so the
hygiene test's ``sleep`` budget counts only unexplained ad-hoc sleeps in
test bodies.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable


def wait_until(pred: Callable[[], bool], timeout: float = 5.0, step: float = 0.02) -> bool:
    """Return True once *pred* holds; False when *timeout* seconds pass first."""
    deadline = time.monotonic() + timeout
    while True:
        if pred():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(step)


async def await_until(pred: Callable[[], bool], timeout: float = 5.0, step: float = 0.02) -> bool:
    """Async version of wait_until for tests already inside a running loop."""
    deadline = time.monotonic() + timeout
    while True:
        if pred():
            return True
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(step)
