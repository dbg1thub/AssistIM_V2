"""Shared asyncio utilities for safe shutdown and task lifecycle management."""

from __future__ import annotations

import asyncio
from typing import Iterable

from client.core import logging

logger = logging.get_logger(__name__)


DEFAULT_CANCEL_TIMEOUT_SECONDS = 2.0


async def bounded_cancel_gather(
    tasks: Iterable[asyncio.Task],
    *,
    timeout: float = DEFAULT_CANCEL_TIMEOUT_SECONDS,
    label: str = "",
) -> None:
    """Cancel pending tasks and wait for completion with a hard timeout.

    Used during manager close paths where unbounded ``asyncio.gather`` would
    hang the entire shutdown if any task fails to respond to cancellation
    (e.g. blocked on broken network IO that does not honour ``CancelledError``).

    Behaviour:

    - Each not-done task receives ``cancel()``.
    - Waits up to ``timeout`` seconds for tasks to finish.
    - Tasks that do not finish in time are abandoned with a warning log;
      they continue running but will not block the close path.
    - Returns silently when there are no pending tasks.
    """
    pending = [task for task in tasks if task is not None and not task.done()]
    if not pending:
        return

    for task in pending:
        task.cancel()

    try:
        _done, still_pending = await asyncio.wait(pending, timeout=timeout)
    except Exception:
        logger.exception("bounded_cancel_gather wait failed (label=%s)", label or "<unset>")
        return

    if still_pending:
        logger.warning(
            "bounded_cancel_gather timeout: %d task(s) did not finish in %.1fs (label=%s)",
            len(still_pending),
            timeout,
            label or "<unset>",
        )


__all__ = ["bounded_cancel_gather", "DEFAULT_CANCEL_TIMEOUT_SECONDS"]
