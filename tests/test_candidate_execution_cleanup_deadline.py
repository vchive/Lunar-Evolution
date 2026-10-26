"""Cleanup deadline observations use fake processes, clocks, selectors, and reads."""
from __future__ import annotations

from collections import Counter
from types import SimpleNamespace

import pytest

from lunar_evolution import candidate_execution_runner as runner


class _Stream:
    def __init__(self, name: str, descriptor: int):
        self.name = name
        self.descriptor = descriptor
        self.closed = False

    def fileno(self):
        return self.descriptor

    def close(self):
        self.closed = True


class _Scenario:
    def __init__(
        self, monkeypatch, actions, *, returncode=None, spawn_time=0.005,
        kill_confirmed=True, group_confirmed=True, tracked=False,
    ):
        self.now = 0.0
        self.actions = list(actions)
        self.waits = []
        self.reads = []
        self.pending = {}
        self.kills = 0
        self.reap_waits = []
        self.group_probes = []
        self.observed = []
        self.released = []
        self.ownership_events = []
        self.tracked = tracked
        self.process = SimpleNamespace(
            pid=4321, returncode=returncode,
            stdout=_Stream("stdout", 101), stderr=_Stream("stderr", 102),
        )
        self.process.poll = lambda: self.process.returncode

        def wait(*, timeout):
            self.reap_waits.append(timeout)
            assert self.kills and self.process.returncode is not None
            assert timeout == runner.PROCESS_CLEANUP_GRACE_SECONDS
            return self.process.returncode

        self.process.wait = wait
        self.process.kill = lambda: pytest.fail("unexpected fallback process.kill")
        self.registered = {}

        def start(*args, **kwargs):
            assert kwargs["start_new_session"] is True
            self.now = spawn_time
            return self.process

        def kill(process):
            assert process is self.process
            self.kills += 1
            if process.returncode is None:
                process.returncode = -9
            return kill_confirmed

        def group_exit(pid, pgid):
            self.group_probes.append((pid, pgid))
            self.ownership_events.append(("probe", pid, pgid))
            return group_confirmed

        def read(descriptor, maximum):
            self.reads.append((len(self.waits), descriptor, maximum))
            assert descriptor in self.pending, "read attempted on an unready descriptor"
            value = self.pending.pop(descriptor)
            if isinstance(value, BaseException):
                raise value
            return value

        scenario = self

        class Selector:
            def register(self, stream, events, name):
                assert events == 1
                scenario.registered[name] = SimpleNamespace(fileobj=stream, data=name)

            def get_map(self):
                return scenario.registered

            def unregister(self, stream):
                del scenario.registered[stream.name]

            def select(self, timeout):
                scenario.waits.append(timeout)
                assert scenario.actions, "cleanup tried an additional selector batch"
                at, observations = scenario.actions.pop(0)
                scenario.now = at
                scenario.pending = {}
                ready = []
                for name, value in observations.items():
                    key = scenario.registered[name]
                    scenario.pending[key.fileobj.fileno()] = value
                    ready.append((key, 1))
                return ready

            def close(self):
                pass

        process_api = SimpleNamespace(
            Popen=start, DEVNULL=-1, PIPE=-1, TimeoutExpired=runner.subprocess.TimeoutExpired,
        )
        monkeypatch.setattr(runner, "subprocess", process_api)
        monkeypatch.setattr(runner, "selectors", SimpleNamespace(DefaultSelector=Selector, EVENT_READ=1))
        monkeypatch.setattr(runner, "time", SimpleNamespace(monotonic=lambda: self.now))
        monkeypatch.setattr(runner, "os", SimpleNamespace(read=read))
        monkeypatch.setattr(runner, "_kill_group", kill)
        monkeypatch.setattr(runner, "_wait_owned_group_exit", group_exit)

    def run(self, *, timeout=0.005, continuation_guard=None):
        def observed(*identity):
            self.observed.append(identity)
            self.ownership_events.append(("observed", *identity))

        def released(*identity):
            self.released.append(identity)
            self.ownership_events.append(("released", *identity))

        return runner._bounded_process_bytes(
            ["fake-command"], cwd="fake-directory", environment={}, timeout=timeout,
            output_limit=8, capture_limit=4,
            process_observer=observed if self.tracked else None,
            process_released=released,
            continuation_guard=continuation_guard,
        )

    def assert_bounded_expired_batch(self, expected_waits=(0.05, 0.0)):
        assert self.waits == list(expected_waits)
        assert not self.actions
        counts = Counter(descriptor for batch, descriptor, _ in self.reads if batch == len(self.waits))
        assert all(count == 1 for count in counts.values())
        assert len(counts) <= 2
        assert all(maximum == runner.PROCESS_READ_CHUNK_BYTES for _, _, maximum in self.reads)
        assert self.process.stdout.closed and self.process.stderr.closed


@pytest.mark.parametrize("first_observations", [{}, {"stdout": b""}])
def test_expired_cleanup_observes_ready_eof_without_waiting(monkeypatch, first_observations):
    remaining = {name: b"" for name in ("stdout", "stderr") if name not in first_observations}
    scenario = _Scenario(monkeypatch, [(0.30, first_observations), (0.30, remaining)])
    actual = scenario.run()

    assert actual == (b"", b"", "timed_out", None, "process_timed_out")
    scenario.assert_bounded_expired_batch()
    assert scenario.kills == 1


@pytest.mark.parametrize("observation", ["unready", "data", "blocking", "interrupted"])
def test_expired_cleanup_cannot_promote_an_open_pipe(monkeypatch, observation):
    value = {"data": b"tail", "blocking": BlockingIOError(), "interrupted": InterruptedError()}
    second = {} if observation == "unready" else {"stderr": value[observation]}
    scenario = _Scenario(monkeypatch, [(0.30, {"stdout": b""}), (0.30, second)])
    actual = scenario.run()

    assert actual == (b"", b"", "failed", None, "process_cleanup_failed")
    scenario.assert_bounded_expired_batch()
    assert "stderr" in scenario.registered
    assert scenario.released == []


def test_expired_cleanup_eof_does_not_reset_a_failed_kill(monkeypatch):
    scenario = _Scenario(
        monkeypatch, [(0.30, {}), (0.30, {"stdout": b"", "stderr": b""})],
        kill_confirmed=False,
    )
    assert scenario.run() == (b"", b"", "failed", None, "process_cleanup_failed")
    scenario.assert_bounded_expired_batch()
    assert scenario.released == []


@pytest.mark.parametrize("group_confirmed", [False, True])
def test_expired_cleanup_eof_requires_tracked_group_confirmation(monkeypatch, group_confirmed):
    scenario = _Scenario(
        monkeypatch, [(0.30, {}), (0.30, {"stdout": b"", "stderr": b""})],
        group_confirmed=group_confirmed, tracked=True,
    )
    expected = ("timed_out", None, "process_timed_out") if group_confirmed else (
        "failed", None, "process_cleanup_failed",
    )
    assert scenario.run() == (b"", b"", *expected)
    scenario.assert_bounded_expired_batch()
    assert scenario.observed == scenario.group_probes == [(4321, 4321)]
    assert scenario.released == ([(4321, 4321)] if group_confirmed else [])
    assert scenario.ownership_events == [
        ("observed", 4321, 4321), ("probe", 4321, 4321),
    ] + ([("released", 4321, 4321)] if group_confirmed else [])


def test_expired_cleanup_read_oserror_propagates_after_finally(monkeypatch):
    error = OSError("fake read failure")
    scenario = _Scenario(monkeypatch, [(0.30, {}), (0.30, {"stderr": error})])
    with pytest.raises(OSError) as observed:
        scenario.run()
    assert observed.value is error
    scenario.assert_bounded_expired_batch()


@pytest.mark.parametrize("returncode,expected", [(0, ("succeeded", 0, None)), (7, ("failed", 7, "process_failed"))])
def test_natural_exit_also_observes_ready_eof_at_cleanup_deadline(monkeypatch, returncode, expected):
    scenario = _Scenario(
        monkeypatch, [(0.30, {}), (0.30, {"stdout": b"", "stderr": b""})],
        returncode=returncode, spawn_time=0.0,
    )
    assert scenario.run(timeout=2) == (b"", b"", *expected)
    scenario.assert_bounded_expired_batch()


def test_expired_natural_exit_data_does_not_create_overflow_or_output(monkeypatch):
    scenario = _Scenario(
        monkeypatch, [(0.30, {}), (0.30, {"stdout": b"x" * 9, "stderr": b""})],
        returncode=0, spawn_time=0.0,
    )
    assert scenario.run(timeout=2) == (b"", b"", "failed", 0, "process_cleanup_failed")
    scenario.assert_bounded_expired_batch()
    assert "stdout" in scenario.registered
    assert scenario.released == []


@pytest.mark.parametrize("last_stdout", [b"", b"tail"])
def test_prior_overflow_keeps_its_existing_error_precedence(monkeypatch, last_stdout):
    scenario = _Scenario(
        monkeypatch, [(0.0, {"stdout": b"x" * 9}), (0.30, {}),
                      (0.30, {"stdout": last_stdout, "stderr": b""})],
        spawn_time=0.0,
    )
    assert scenario.run(timeout=2) == (b"xxxx", b"", "failed", -9, "output_limit_exceeded")
    scenario.assert_bounded_expired_batch((0.05, 0.05, 0.0))


def test_eof_before_cleanup_deadline_keeps_the_existing_path(monkeypatch):
    scenario = _Scenario(monkeypatch, [(0.006, {"stdout": b"", "stderr": b""})])
    assert scenario.run() == (b"", b"", "timed_out", None, "process_timed_out")
    assert scenario.waits == [0.05]
    assert scenario.kills == 1


def test_continuation_rejection_is_propagated_without_a_selector_batch(monkeypatch):
    scenario = _Scenario(monkeypatch, [], spawn_time=0.0)
    rejection = RuntimeError("fake continuation rejected")
    calls = []

    def guard():
        calls.append(None)
        if len(calls) == 2:
            raise rejection

    with pytest.raises(RuntimeError) as observed:
        scenario.run(timeout=2, continuation_guard=guard)
    assert observed.value is rejection
    assert scenario.waits == []
    assert scenario.kills == 1
    assert scenario.reap_waits == [runner.PROCESS_CLEANUP_GRACE_SECONDS]
    assert scenario.process.stdout.closed and scenario.process.stderr.closed
