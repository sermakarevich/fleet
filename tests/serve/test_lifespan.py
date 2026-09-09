"""Supervised serve background tasks (ADR 0006 bead 22).

A crashing background task must be logged with its name, never silent until
shutdown: `serve/app.py::supervise` adds the done-callback that does it.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from _pytest.logging import LogCaptureFixture

from fleet.serve.app import supervise
from tests.helpers.wait import wait_until


def test_crashing_background_task_is_logged(caplog: LogCaptureFixture) -> None:
    """A failed supervised task logs 'background task failed', not silence."""

    async def _main() -> None:
        async def _boom() -> None:
            raise RuntimeError("boom")

        task = supervise(_boom(), "test_task")
        with contextlib.suppress(RuntimeError):
            await task

    with caplog.at_level(logging.ERROR, logger="fleet.serve.app"):
        asyncio.run(_main())
    # The failure is logged from a done-callback: wait for the record itself.
    assert wait_until(lambda: "background task failed" in caplog.text), caplog.text


def test_cancelled_background_task_stays_quiet(caplog: LogCaptureFixture) -> None:
    """Cancelling a supervised task (normal shutdown) logs nothing."""

    async def _main() -> None:
        async def _wait() -> None:
            await asyncio.Event().wait()  # block until cancelled; no fixed sleep

        task = supervise(_wait(), "test_task")
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        # One loop tick so the (quiet) done-callback runs before we assert.
        await asyncio.sleep(0)

    with caplog.at_level(logging.ERROR, logger="fleet.serve.app"):
        asyncio.run(_main())
    assert "background task failed" not in caplog.text
