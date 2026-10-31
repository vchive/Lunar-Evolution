"""Inert procfs status fixtures; no process, namespace or Podman is started."""

from __future__ import annotations

import pytest

from tools.static_python_rsi_fixture import podman_worker_init as worker_init

PID = 4242
FIELDS = (b"Pid", b"Tgid", b"NSpid", b"NStgid")


def status_bytes(*, pid=PID, tgid=PID, pids=(PID, 1), tgids=None):
    if tgids is None:
        tgids = pids

    def vector(values):
        return b"\t".join(str(value).encode("ascii") for value in values)

    return (b"Name:\tinert worker\nState:\tS (sleeping)\nTgid:\t" + str(tgid).encode("ascii")
            + b"\nPid:\t" + str(pid).encode("ascii") + b"\nPPid:\t1234\nNStgid:\t" + vector(tgids)
            + b"\nNSpid:\t" + vector(pids) + b"\nCapEff:\t0000000000000000\n")


@pytest.mark.parametrize("pids", [(PID, 1), (PID, 17, 1), (PID, *range(32, 1, -1), 1)])
def test_original_leader_init_accepts_bounded_nested_kernel_vectors(pids):
    assert worker_init.verify_worker_namespace_init(status_bytes(pids=pids), PID) is None


def test_other_status_fields_are_data_and_do_not_become_a_pid_authority():
    raw = b"Name:\t\xffopaque name\nPidExtra:\t9999\n" + status_bytes()
    assert worker_init.verify_worker_namespace_init(raw, PID) is None


@pytest.mark.parametrize("field", FIELDS)
def test_relevant_status_field_must_exist_exactly_once(field):
    raw = status_bytes()
    selected = next(line for line in raw.splitlines(keepends=True) if line.startswith(field + b":"))
    with pytest.raises(ValueError, match="^podman_worker_init$"):
        worker_init.verify_worker_namespace_init(raw + selected, PID)


@pytest.mark.parametrize("field", FIELDS)
def test_missing_original_status_field_refuses(field):
    raw = b"".join(line for line in status_bytes().splitlines(keepends=True)
                   if not line.startswith(field + b":"))
    with pytest.raises(ValueError, match="^podman_worker_init$"):
        worker_init.verify_worker_namespace_init(raw, PID)


@pytest.mark.parametrize("old,new", [
    (b"Pid:\t4242", b"Pid: 4242"), (b"Pid:\t4242", b"Pid:4242"),
    (b"Pid:\t4242", b"Pid:\t\t4242"), (b"Pid:\t4242", b" Pid:\t4242"),
    (b"Pid:\t4242", b"Pid :\t4242"), (b"NSpid:\t4242\t1", b"NSpid:\t4242 1"),
    (b"NSpid:\t4242\t1", b"NSpid:\t4242\t1\t"), (b"Pid:\t4242", b"Pid:\t4242\r"),
])
def test_related_fields_require_unambiguous_kernel_tab_representation(old, new):
    with pytest.raises(ValueError, match="^podman_worker_init$"):
        worker_init.verify_worker_namespace_init(status_bytes().replace(old, new), PID)


@pytest.mark.parametrize("value", [b"0", b"-1", b"+1", b"01", b"2147483648", b"9" * 1000])
def test_each_namespace_pid_is_positive_canonical_bounded_decimal(value):
    raw = status_bytes()
    for field in (b"NSpid", b"NStgid"):
        raw = raw.replace(field + b":\t4242\t1\n", field + b":\t4242\t" + value + b"\t1\n")
    with pytest.raises(ValueError, match="^podman_worker_init$"):
        worker_init.verify_worker_namespace_init(raw, PID)


@pytest.mark.parametrize("pid", [True, 0, -1, 2**31, "4242", None])
def test_caller_original_pid_is_a_positive_kernel_pid_integer(pid):
    with pytest.raises(ValueError, match="^podman_worker_init$"):
        worker_init.verify_worker_namespace_init(status_bytes(), pid)


@pytest.mark.parametrize("changes", [
    {"pid": PID + 1}, {"tgid": PID + 1}, {"pids": (PID + 1, 1)}, {"pids": (PID, 2)},
    {"tgids": (PID, 17, 1)}, {"pids": (1,)}, {"pids": (PID, *range(33, 1, -1), 1)},
])
def test_nonleader_noninit_cross_view_and_excessive_nesting_refuse(changes):
    with pytest.raises(ValueError, match="^podman_worker_init$"):
        worker_init.verify_worker_namespace_init(status_bytes(**changes), PID)


@pytest.mark.parametrize("raw", [
    b"", bytearray(status_bytes()), status_bytes().decode("ascii"),
    status_bytes()[:-1], status_bytes() + b"Name:\tbad\x00name\n",
])
def test_status_type_empty_truncation_and_nul_refuse(raw):
    with pytest.raises(ValueError, match="^podman_worker_init$"):
        worker_init.verify_worker_namespace_init(raw, PID)


def test_status_byte_limit_includes_uninterpreted_fields():
    base = status_bytes()
    raw = base + b"X:" + b"x" * (worker_init.MAX_WORKER_STATUS_BYTES - len(base) - 3) + b"\n"
    assert len(raw) == worker_init.MAX_WORKER_STATUS_BYTES
    assert worker_init.verify_worker_namespace_init(raw, PID) is None
    with pytest.raises(ValueError, match="^podman_worker_init$"):
        worker_init.verify_worker_namespace_init(raw + b"\n", PID)


@pytest.mark.parametrize("error", [RuntimeError("original deadline"), KeyboardInterrupt("original cancellation")])
@pytest.mark.parametrize("moment", ["before-parse", "during-parse"])
def test_original_checkpoint_failure_is_preserved(error, moment):
    calls = 0

    def checkpoint():
        nonlocal calls
        calls += 1
        if moment == "before-parse" or calls == 5:
            raise error

    with pytest.raises(type(error)) as caught:
        worker_init.verify_worker_namespace_init(status_bytes(), PID, checkpoint=checkpoint)
    assert caught.value is error
    assert calls == (1 if moment == "before-parse" else 5)


def test_invalid_checkpoint_refuses_without_interpreting_status():
    with pytest.raises(ValueError, match="^podman_worker_init$"):
        worker_init.verify_worker_namespace_init(status_bytes(), PID, checkpoint=False)
