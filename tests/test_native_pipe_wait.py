"""Readiness regression at the descriptor numbers retained in failed CI."""

from __future__ import annotations

import os
import select
import sys
from contextlib import ExitStack

import pytest
from _native_pipe_wait import pipe_readable

try:
    import fcntl
    import resource
except ImportError:
    fcntl = resource = None


@pytest.mark.skipif(fcntl is None, reason="POSIX pipe descriptors")
@pytest.mark.parametrize("minimum", [1024, 1189, 1447])
def test_pipe_readiness_above_select_descriptor_limit(minimum):
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    required = minimum + 16
    if hard != resource.RLIM_INFINITY and hard < required:
        pytest.skip("platform descriptor hard limit below recorded CI fixture")
    with ExitStack() as stack:
        if soft != resource.RLIM_INFINITY and soft < required:
            resource.setrlimit(resource.RLIMIT_NOFILE, (required, hard))
            stack.callback(resource.setrlimit, resource.RLIMIT_NOFILE, (soft, hard))
        read_fd, write_fd = os.pipe()
        stack.callback(os.close, read_fd)
        stack.callback(os.close, write_fd)
        high_fd = fcntl.fcntl(read_fd, fcntl.F_DUPFD, minimum)
        stack.callback(os.close, high_fd)
        assert high_fd >= minimum
        if sys.platform == "linux":
            with pytest.raises(ValueError, match="out of range"):
                select.select([high_fd], [], [], 0)
        assert not pipe_readable(high_fd, 0)
        os.write(write_fd, b"R")
        assert pipe_readable(high_fd, 0.1)
        assert os.read(high_fd, 1) == b"R"
        assert not pipe_readable(high_fd, 0)
        assert os.fstat(high_fd)  # The helper does not own or close caller pipes.


def test_eof_remains_readable_without_consuming_or_closing_pipe():
    read_fd, write_fd = os.pipe()
    os.close(write_fd)
    try:
        assert pipe_readable(read_fd, 0.1)
        assert os.read(read_fd, 1) == b""
        assert os.fstat(read_fd)
    finally:
        os.close(read_fd)


@pytest.mark.parametrize("failure", ["register", "select", None])
def test_wait_uses_one_supplied_timeout_and_closes_selector(monkeypatch, failure):
    import _native_pipe_wait as helper

    calls = []

    class Watcher:
        def __enter__(self):
            calls.append("enter")
            return self

        def __exit__(self, *_args):
            calls.append("close")

        def register(self, pipe, events):
            calls.append(("register", pipe, events))
            if failure == "register":
                raise ValueError("inert registration refusal")

        def select(self, timeout):
            calls.append(("select", timeout))
            if failure == "select":
                raise ValueError("inert select refusal")
            return [(object(), helper.selectors.EVENT_READ)]

    monkeypatch.setattr(helper.selectors, "DefaultSelector", Watcher)
    if failure:
        with pytest.raises(ValueError, match="inert"):
            pipe_readable(1447, 0.25)
    else:
        assert pipe_readable(1447, 0.25)
    assert calls[-1] == "close"
    expected = ["enter", ("register", 1447, helper.selectors.EVENT_READ)]
    if failure != "register":
        expected.append(("select", 0.25))
    assert calls == [*expected, "close"]
