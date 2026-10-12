"""Bounded native-fixture pipe waits at any valid POSIX descriptor number."""

from __future__ import annotations

import selectors


def pipe_readable(pipe, timeout: float) -> bool:
    """Wait once for readability without select's fixed FD_SETSIZE limit.

    The caller retains its original absolute deadline and owns the pipe. Each
    transient selector closes on success or refusal; this helper neither reads
    nor closes the supplied descriptor. EOF is readable, matching select().
    """
    with selectors.DefaultSelector() as watcher:
        watcher.register(pipe, selectors.EVENT_READ)
        return bool(watcher.select(timeout))
