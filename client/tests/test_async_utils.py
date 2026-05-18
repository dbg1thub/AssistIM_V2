"""Behaviour tests for ``client.core.async_utils.bounded_cancel_gather``."""

from __future__ import annotations

import asyncio

from client.core.async_utils import bounded_cancel_gather


def _run(coro):
    return asyncio.run(coro)


def test_bounded_cancel_gather_returns_immediately_when_no_pending() -> None:
    async def scenario() -> None:
        await bounded_cancel_gather([])

    _run(scenario())


def test_bounded_cancel_gather_cancels_responsive_tasks() -> None:
    async def slow_but_cancellable() -> None:
        await asyncio.sleep(60)

    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        task = loop.create_task(slow_but_cancellable())
        await asyncio.sleep(0)  # let task enter the sleep
        await bounded_cancel_gather([task], timeout=1.0, label="responsive")
        assert task.done()
        assert task.cancelled()

    _run(scenario())


def test_bounded_cancel_gather_skips_already_done_tasks() -> None:
    async def quick() -> None:
        return None

    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        task = loop.create_task(quick())
        await task
        # Done tasks must not raise or block.
        await bounded_cancel_gather([task], timeout=1.0)

    _run(scenario())


def test_bounded_cancel_gather_returns_within_timeout_for_unresponsive_task(caplog) -> None:
    async def cancel_resistant() -> None:
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:
            # Simulate a task that swallows cancellation and keeps running.
            try:
                await asyncio.sleep(60)
            except asyncio.CancelledError:
                # Eventually accept the cancel so the test does not leak.
                raise

    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        task = loop.create_task(cancel_resistant())
        await asyncio.sleep(0)
        # bounded_cancel_gather must return within roughly the timeout window
        # even though the task is briefly cancel-resistant.
        start = loop.time()
        await bounded_cancel_gather([task], timeout=0.2, label="resistant")
        elapsed = loop.time() - start
        assert elapsed < 1.0
        # The function must log a warning on timeout.
        assert any(
            "bounded_cancel_gather timeout" in record.message
            for record in caplog.records
        )
        # Clean up the still-pending task so the loop can shut down cleanly.
        if not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    _run(scenario())


def test_bounded_cancel_gather_handles_none_entries() -> None:
    async def slow_but_cancellable() -> None:
        await asyncio.sleep(60)

    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        task = loop.create_task(slow_but_cancellable())
        await asyncio.sleep(0)
        await bounded_cancel_gather([None, task, None], timeout=1.0)
        assert task.done()

    _run(scenario())
