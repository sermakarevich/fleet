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


def test_crashing_background_task_is_logged(caplog: LogCaptureFixture) -> None:
    """A failed supervised task logs 'background task failed', not silence."""

    async def _main() -> None:
        async def _boom() -> None:
            raise RuntimeError("boom")

        task = supervise(_boom(), "test_task")
        with contextlib.suppress(RuntimeError):
            await task
        await asyncio.sleep(0)

    with caplog.at_level(logging.ERROR, logger="fleet.serve.app"):
        asyncio.run(_main())
    assert "background task failed" in caplog.text


def test_cancelled_background_task_stays_quiet(caplog: LogCaptureFixture) -> None:
    """Cancelling a supervised task (normal shutdown) logs nothing."""

    async def _main() -> None:
        async def _wait() -> None:
            await asyncio.sleep(60)

        task = supervise(_wait(), "test_task")
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        await asyncio.sleep(0)

    with caplog.at_level(logging.ERROR, logger="fleet.serve.app"):
        asyncio.run(_main())
    assert "background task failed" not in caplog.text
