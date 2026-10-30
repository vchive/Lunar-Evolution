"""Single-PID accounting uses synthetic proc files and injected clocks only."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "linux_process_accounting", Path(__file__).resolve().parents[1] / "tools/linux_process_accounting.py",
)
assert _SPEC and _SPEC.loader
accounting = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(accounting)

_PID = 4321
_START = 98765
_MAX_UINT = (1 << 64) - 1
_PRIVATE = b"private-name ) ( argv --secret=hidden\xff\n"


def _stat(*, pid=_PID, start=_START, comm=_PRIVATE, values=None, fields=40):
    tail = [b"0"] * 40
    tail[0] = b"R"
    tail[11], tail[12] = b"41", b"7"
    tail[13], tail[14] = b"-900", b"-800"  # Child CPU is not process CPU.
    tail[15], tail[16] = b"20", b"-20"  # Signed fields are not selected.
    tail[17], tail[19], tail[39] = b"3", str(start).encode(), b"19"
    for index, value in (values or {}).items():
        tail[index] = value
    return str(pid).encode() + b" (" + comm + b") " + b" ".join(tail[:fields]) + b"\n"


def _io():
    return b"\n".join(
        key.encode() + b": " + str(index).encode()
        for index, key in enumerate(accounting.IO_FIELDS)
    ) + b"\n"


def _status(uid):
    return (
        b"Name:\tprivate-process-name\nUid:\t" + b"\t".join([str(uid).encode()] * 4)
        + b"\nvoluntary_ctxt_switches:\t13\nnonvoluntary_ctxt_switches:\t5\n"
        + b"PrivateField:\tsecret-value\n"
    )


@pytest.fixture
def proc(tmp_path):
    root = tmp_path / "synthetic-proc"
    target = root / str(_PID)
    target.mkdir(parents=True)
    values = {
        "stat": _stat(), "schedstat": b"1000000000 2000000000 3\n",
        "io": _io(), "status": _status(accounting.os.geteuid()),
    }
    for name, raw in values.items():
        (target / name).write_bytes(raw)
    return SimpleNamespace(root=root, target=target, values=values)


def _error(code, call):
    with pytest.raises(accounting.DiagnosticError) as error:
        call()
    assert error.value.code == code
    assert str(error.value) == code


def test_stat_uses_final_comm_parenthesis_and_only_approved_numeric_fields():
    parsed = accounting.parse_stat(_stat(), _PID)
    assert parsed == {
        "starttime_ticks": _START, "process_cpu_ticks": {"user": 41, "system": 7},
        "num_threads": 3, "block_io_delay_ticks": 19,
    }
    encoded = json.dumps(parsed)
    assert "private" not in encoded and "hidden" not in encoded
    assert "900" not in encoded and "800" not in encoded


@pytest.mark.parametrize("fields", [20, 21, 39])
def test_stat_without_optional_delay_field_does_not_invent_zero(fields):
    parsed = accounting.parse_stat(_stat(fields=fields), _PID)
    assert parsed["block_io_delay_ticks"] is None
    assert parsed["process_cpu_ticks"] == {"user": 41, "system": 7}


def test_stat_uint64_max_is_preserved_without_units_or_delta_conversion():
    parsed = accounting.parse_stat(_stat(values={
        index: str(_MAX_UINT).encode() for index in (11, 12, 17, 19, 39)
    }), _PID)
    assert parsed["starttime_ticks"] == parsed["num_threads"] == _MAX_UINT
    assert parsed["process_cpu_ticks"] == {"user": _MAX_UINT, "system": _MAX_UINT}
    assert parsed["block_io_delay_ticks"] == _MAX_UINT


@pytest.mark.parametrize("raw", [b"", b"4321 no-parentheses", b"4321 (missing", b"4321 ) ( x"])
def test_stat_missing_comm_envelope_is_malformed(raw):
    _error("malformed", lambda: accounting.parse_stat(raw, _PID))


def test_stat_rejects_wrong_numeric_pid():
    _error("identity_changed", lambda: accounting.parse_stat(_stat(pid=_PID + 1), _PID))


@pytest.mark.parametrize("fields", [0, 1, 19])
def test_stat_missing_required_fields_is_malformed(fields):
    _error("malformed", lambda: accounting.parse_stat(_stat(fields=fields), _PID))


@pytest.mark.parametrize("index", [11, 12, 17, 19, 39])
@pytest.mark.parametrize("value", [b"-1", b"+1", b"1.0", b"NaN", b"18446744073709551616"])
def test_stat_selected_counters_are_bounded_unsigned_decimals(index, value):
    _error("malformed", lambda: accounting.parse_stat(_stat(values={index: value}), _PID))


@pytest.mark.parametrize("index", [17, 19])
def test_stat_requires_positive_thread_count_and_starttime(index):
    _error("malformed", lambda: accounting.parse_stat(_stat(values={index: b"0"}), _PID))


@pytest.mark.parametrize("raw", [b"", b"0 0", b"0 0 0 0", b"1 -1 1", b"1 1.0 1", b"1 1 +1"])
def test_schedstat_requires_three_unsigned_counters(raw):
    _error("malformed", lambda: accounting.parse_schedstat(raw))


def test_zero_schedstat_is_an_observed_raw_value_not_a_claim_of_no_wait():
    assert accounting.parse_schedstat(b"0 0 0\n") == {
        "runtime_ns": 0, "runqueue_ns": 0, "timeslices": 0,
    }


def test_io_and_status_ignore_unknown_private_lines_and_keep_numeric_allowlist():
    assert accounting.parse_io(_io() + b"PrivateKey: secret\n") == {
        key: index for index, key in enumerate(accounting.IO_FIELDS)
    }
    assert accounting.parse_status(_status(12), 12) == {"voluntary": 13, "nonvoluntary": 5}


@pytest.mark.parametrize("kind", ["missing", "duplicate", "negative", "overflow"])
def test_io_selected_fields_must_be_complete_unique_bounded_counters(kind):
    raw = _io()
    if kind == "missing":
        raw = raw.partition(b"\n")[2]
    elif kind == "duplicate":
        raw += b"rchar: 0\n"
    elif kind == "negative":
        raw = raw.replace(b"rchar: 0", b"rchar: -1")
    else:
        raw = raw.replace(b"rchar: 0", b"rchar: 18446744073709551616")
    _error("malformed", lambda: accounting.parse_io(raw))


@pytest.mark.parametrize("kind", ["missing", "duplicate", "short-uid", "bad-uid", "negative-switches"])
def test_status_rejects_malformed_selected_fields(kind):
    raw = _status(12)
    if kind == "missing":
        raw = raw.replace(b"voluntary_ctxt_switches:\t13\n", b"")
    elif kind == "duplicate":
        raw += b"Uid: 12 12 12 12\n"
    elif kind == "short-uid":
        raw = raw.replace(b"12\t12\t12\t12", b"12 12 12")
    elif kind == "bad-uid":
        raw = raw.replace(b"12\t12\t12\t12", b"12 bad 12 12")
    else:
        raw = raw.replace(b"switches:\t13", b"switches:\t-1")
    _error("malformed", lambda: accounting.parse_status(raw, 12))


@pytest.mark.parametrize("index", range(4))
def test_any_status_uid_disagreement_is_fatal_owner_drift(index):
    values = [b"12"] * 4
    values[index] = b"13"
    raw = _status(12).replace(b"12\t12\t12\t12", b"\t".join(values))
    _error("owner_changed", lambda: accounting.parse_status(raw, 12))


@pytest.mark.parametrize("pid", [0, -1, True, 1.0, "1", (1 << 31)])
def test_observer_rejects_invalid_pid_before_reading_proc(pid, monkeypatch):
    monkeypatch.setattr(accounting.os, "open", lambda *_a, **_k: pytest.fail("opened a target"))
    _error("invalid_pid", lambda: accounting.ProcessObserver(pid, proc_root="unused"))


@pytest.mark.parametrize("start", [0, -1, True, 1.0, "1", 1 << 64])
def test_observer_rejects_invalid_expected_starttime(start):
    _error("invalid_starttime", lambda: accounting.ProcessObserver(
        _PID, start, proc_root="unused",
    ))


@pytest.mark.parametrize("uid", [True, 1.0, "1", -1])
def test_observer_expected_uid_requires_exact_current_effective_uid(uid):
    _error("invalid_expected_uid", lambda: accounting.ProcessObserver(
        _PID, expected_uid=uid, proc_root="unused",
    ))


def test_observer_samples_only_one_target_and_baseline_binding_stays_explicit(proc, monkeypatch):
    original_open = accounting.os.open
    opened = []

    def opened_file(path, flags, *args, **kwargs):
        opened.append((path, flags, kwargs.get("dir_fd")))
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(accounting.os, "open", opened_file)
    observer = accounting.ProcessObserver(_PID, proc_root=proc.root)
    with observer:
        first = observer.sample()
        second = observer.sample()
        held_fd = observer._fd
        assert first == second
        assert first["target"] == {
            "pid": _PID, "uid": accounting.os.geteuid(), "starttime_ticks": _START,
            "identity_binding": "baseline_only",
        }
        assert first["process_stat"]["values"]["process_cpu_ticks"] == {"user": 41, "system": 7}
        assert first["leader_schedstat"]["values"]["runqueue_ns"] == 2_000_000_000
        assert first["process_io"]["status"] == "observed"
        assert first["leader_context_switches"]["values"] == {"voluntary": 13, "nonvoluntary": 5}
    assert observer._fd is None
    assert opened[0][0] == proc.target and opened[0][2] is None
    assert [path for path, _flags, _fd in opened[1:]] == [
        "stat", "schedstat", "io", "status", "stat",
    ] * 2
    assert all(fd == held_fd for _path, _flags, fd in opened[1:])
    assert all(flags & accounting.os.O_NOFOLLOW for _path, flags, _fd in opened)
    output = json.dumps(first)
    assert all(secret not in output for secret in ("private", "hidden", "secret", str(proc.root)))
    observer.close()
    _error("target_not_open", observer.sample)


def test_caller_expected_starttime_and_uid_are_retained(proc):
    uid = accounting.os.geteuid()
    with accounting.ProcessObserver(_PID, _START, uid, proc_root=proc.root) as observer:
        assert observer.sample()["target"]["identity_binding"] == "caller_expected"


@pytest.mark.parametrize("source,output_key", [
    ("schedstat", "leader_schedstat"), ("io", "process_io"),
    ("status", "leader_context_switches"),
])
@pytest.mark.parametrize("failure", ["unavailable", "malformed", "too_large", "not_regular"])
def test_optional_failure_is_explicit_and_never_fabricates_zero(proc, source, output_key, failure):
    path = proc.target / source
    if failure in {"unavailable", "not_regular"}:
        path.unlink()
        if failure == "not_regular":
            path.mkdir()
    else:
        path.write_bytes(b"invalid-private" if failure == "malformed" else
                         b"x" * (accounting.FILE_LIMITS[source] + 1))
    with accounting.ProcessObserver(_PID, proc_root=proc.root) as observer:
        sample = observer.sample()
    assert sample[output_key] == {"status": failure, "values": None}
    assert sample["process_stat"]["status"] == "observed"
    assert "invalid-private" not in json.dumps(sample)


@pytest.mark.parametrize("source,output_key", [
    ("schedstat", "leader_schedstat"), ("io", "process_io"),
    ("status", "leader_context_switches"),
])
def test_optional_permission_failure_reports_fixed_code_without_exception_text(
    proc, monkeypatch, source, output_key,
):
    original_open = accounting.os.open

    def denied(path, *args, **kwargs):
        if path == source:
            raise PermissionError("private/path/credential")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(accounting.os, "open", denied)
    with accounting.ProcessObserver(_PID, proc_root=proc.root) as observer:
        sample = observer.sample()
    assert sample[output_key] == {"status": "denied", "values": None}
    assert "credential" not in json.dumps(sample)


@pytest.mark.parametrize("failure,code", [
    ("unavailable", "stat_unavailable"), ("malformed", "stat_malformed"),
    ("too_large", "stat_too_large"), ("not_regular", "stat_not_regular"),
])
def test_required_stat_failure_stops_instead_of_establishing_a_baseline(proc, failure, code):
    path = proc.target / "stat"
    if failure in {"unavailable", "not_regular"}:
        path.unlink()
        if failure == "not_regular":
            path.mkdir()
    else:
        path.write_bytes(b"private" if failure == "malformed" else b"x" * 8193)
    with accounting.ProcessObserver(_PID, proc_root=proc.root) as observer:
        _error(code, observer.sample)
        assert observer.starttime is None


def test_optional_symlink_is_never_followed(proc, tmp_path):
    private = tmp_path / "private-file"
    private.write_bytes(proc.values["io"])
    path = proc.target / "io"
    path.unlink()
    path.symlink_to(private)
    with accounting.ProcessObserver(_PID, proc_root=proc.root) as observer:
        sample = observer.sample()
    assert sample["process_io"] == {"status": "read_error", "values": None}
    assert private.read_bytes() == proc.values["io"]


def test_target_directory_symlink_is_refused(proc):
    linked = proc.root / str(_PID + 1)
    linked.symlink_to(proc.target, target_is_directory=True)
    observer = accounting.ProcessObserver(_PID + 1, proc_root=proc.root)
    with pytest.raises(accounting.DiagnosticError) as error, observer:
        pytest.fail("followed target directory symlink")
    assert error.value.code.startswith("target_")
    assert observer._fd is None


def test_missing_target_stays_unavailable_and_leaves_observer_closed(proc):
    observer = accounting.ProcessObserver(_PID + 1, proc_root=proc.root)
    _error("target_unavailable", observer.__enter__)
    assert observer._fd is None


@pytest.mark.parametrize("change", ["pid", "starttime"])
@pytest.mark.parametrize("when", ["first", "second", "later-sample"])
def test_identity_change_is_fatal_and_never_adopts_replacement(proc, monkeypatch, change, when):
    with accounting.ProcessObserver(_PID, _START, proc_root=proc.root) as observer:
        original_read = observer._read
        reads = []

        def read(name):
            reads.append(name)
            if name != "stat":
                return original_read(name)
            ordinal = reads.count("stat")
            changed = ordinal >= {"first": 1, "second": 2, "later-sample": 3}[when]
            return _stat(**({"pid": _PID + 1} if change == "pid" else {"start": _START + 1})) \
                if changed else _stat()

        monkeypatch.setattr(observer, "_read", read)
        if when == "later-sample":
            assert observer.sample()["target"]["starttime_ticks"] == _START
        _error("identity_changed", observer.sample)
        assert observer.starttime == _START
        if when == "first":
            assert reads == ["stat"]


def test_status_uid_drift_is_fatal_even_though_status_is_optional(proc):
    (proc.target / "status").write_bytes(_status(accounting.os.geteuid() + 1))
    with accounting.ProcessObserver(_PID, proc_root=proc.root) as observer:
        _error("owner_changed", observer.sample)
        assert observer.starttime is None


@pytest.mark.parametrize("when", ["entry", "before-sample", "after-sample"])
def test_directory_ownership_is_rechecked_before_and_after_sources(proc, monkeypatch, when):
    observer = accounting.ProcessObserver(_PID, proc_root=proc.root)
    original_fstat = accounting.os.fstat
    checks = []

    def fstat(fd):
        info = original_fstat(fd)
        if fd == observer._fd:
            checks.append(fd)
            limit = {"entry": 1, "before-sample": 2, "after-sample": 3}[when]
            return SimpleNamespace(st_uid=info.st_uid + (len(checks) >= limit), st_mode=info.st_mode)
        return info

    monkeypatch.setattr(accounting.os, "fstat", fstat)
    if when == "entry":
        _error("owner_changed", observer.__enter__)
    else:
        with observer:
            _error("owner_changed", observer.sample)
            assert observer.starttime is None
    assert observer._fd is None


class _Clock:
    def __init__(self):
        self.now = 0
        self.sleeps = []

    def read(self):
        return self.now

    def sleep(self, seconds):
        assert seconds > 0
        self.sleeps.append(seconds)
        self.now += round(seconds * 1_000_000_000)


class _Observer:
    def __init__(self, clock, *, work_ns=0, error_at=None):
        self.clock = clock
        self.work_ns = work_ns
        self.error_at = error_at
        self.calls = 0

    def sample(self):
        index = self.calls
        self.calls += 1
        self.clock.now += self.work_ns
        if index == self.error_at:
            raise accounting.DiagnosticError("identity_changed")
        return {"target": {"pid": _PID}, "raw_counter": index}


@pytest.fixture
def sampling(monkeypatch):
    monkeypatch.setattr(accounting.os, "sysconf", lambda name: 100 if name == "SC_CLK_TCK" else
                        pytest.fail("unexpected sysconf"))
    clock = _Clock()
    observer = _Observer(clock)
    emitted = []

    def run(*, count=3, interval=0.25, duration=10):
        return accounting.run_sampling(
            observer, count=count, interval_seconds=interval, duration_seconds=duration,
            emit=emitted.append, clock_ns=clock.read, sleep=clock.sleep,
        )

    return SimpleNamespace(clock=clock, observer=observer, emitted=emitted, run=run)


def test_count_limit_emits_raw_samples_bounded_windows_and_one_end(sampling):
    assert sampling.run() == "sample_limit"
    assert sampling.observer.calls == 3
    assert sampling.clock.sleeps == [0.25, 0.25]
    assert [record["kind"] for record in sampling.emitted] == [
        "header", "sample", "sample", "sample", "end",
    ]
    samples = sampling.emitted[1:-1]
    assert [sample["sample_index"] for sample in samples] == [0, 1, 2]
    assert [sample["sample_window_monotonic_ns"] for sample in samples] == [
        [0, 0], [250_000_000, 250_000_000], [500_000_000, 500_000_000],
    ]
    header = sampling.emitted[0]
    assert header["clock_ticks_per_second"] == 100
    assert header["limits"]["file_bytes"] == accounting.FILE_LIMITS
    assert "single_pid_only_no_descendants" in header["limitations"]
    assert "cooperative_sampling_deadline_not_hard_syscall_timeout" in header["limitations"]
    assert sampling.emitted[-1] == {"kind": "end", "reason": "sample_limit"}


@pytest.mark.parametrize("count", [1, accounting.MAX_SAMPLES])
def test_inclusive_count_limits_never_sleep_after_last_sample(sampling, count):
    assert sampling.run(count=count, interval=0.05, duration=600) == "sample_limit"
    assert sampling.observer.calls == count
    assert len(sampling.clock.sleeps) == count - 1


def test_duration_limit_sleeps_only_remaining_time_and_does_not_start_at_deadline(sampling):
    assert sampling.run(count=10, interval=1, duration=0.3) == "duration_limit"
    assert sampling.observer.calls == 1
    assert sampling.clock.sleeps == [0.3]
    assert sampling.emitted[-1] == {"kind": "end", "reason": "duration_limit"}


def test_running_sample_can_finish_after_cooperative_deadline_without_extra_sleep(sampling):
    sampling.observer.work_ns = 400_000_000
    assert sampling.run(count=3, interval=1, duration=0.3) == "duration_limit"
    assert sampling.observer.calls == 1 and sampling.clock.sleeps == []
    assert sampling.emitted[1]["sample_window_monotonic_ns"] == [0, 400_000_000]
    assert sampling.emitted[-1] == {"kind": "end", "reason": "duration_limit"}


def test_work_is_not_followed_by_catchup_or_busy_loop(sampling):
    sampling.observer.work_ns = 200_000_000
    assert sampling.run(count=3, interval=0.1, duration=10) == "sample_limit"
    assert sampling.clock.sleeps == [0.1, 0.1]
    assert [sample["sample_window_monotonic_ns"][0] for sample in sampling.emitted
            if sample["kind"] == "sample"] == [0, 300_000_000, 600_000_000]


def test_identity_error_emits_one_fixed_error_and_never_success_end_or_retry(sampling):
    sampling.observer.error_at = 1
    assert sampling.run(count=5) == "identity_changed"
    assert sampling.observer.calls == 2
    assert [record["kind"] for record in sampling.emitted] == ["header", "sample", "error"]
    assert sampling.emitted[-1] == {
        "kind": "error", "sample_index": 1, "reason": "identity_changed",
        "sample_window_monotonic_ns": [250_000_000, 250_000_000],
    }


@pytest.mark.parametrize("field,value,code", [
    ("count", 0, "invalid_count"), ("count", -1, "invalid_count"),
    ("count", True, "invalid_count"), ("count", 1.0, "invalid_count"),
    ("count", 1202, "invalid_count"),
    ("interval", 0.049, "invalid_interval"), ("interval", 60.01, "invalid_interval"),
    ("interval", True, "invalid_interval"), ("interval", float("nan"), "invalid_interval"),
    ("interval", float("inf"), "invalid_interval"), ("interval", "1", "invalid_interval"),
    ("duration", 0, "invalid_duration"), ("duration", -1, "invalid_duration"),
    ("duration", 600.01, "invalid_duration"), ("duration", True, "invalid_duration"),
    ("duration", float("nan"), "invalid_duration"),
    ("duration", float("-inf"), "invalid_duration"), ("duration", "1", "invalid_duration"),
])
def test_invalid_sampling_budget_refuses_before_observation_or_output(sampling, field, value, code):
    _error(code, lambda: sampling.run(**{field: value}))
    assert sampling.observer.calls == 0 and sampling.emitted == []
    assert sampling.clock.sleeps == []


def test_status_uid_drift_is_not_hidden_by_missing_optional_counters():
    _error("owner_changed", lambda: accounting.parse_status(b"Uid: 13 13 13 13\n", 12))
    _error("malformed", lambda: accounting.parse_status(b"Uid: 12 12 12 12\n", 12))


@pytest.mark.parametrize("source,output_key", [
    ("stat", "process_stat"), ("schedstat", "leader_schedstat"),
    ("io", "process_io"), ("status", "leader_context_switches"),
])
def test_each_file_limit_accepts_exact_bytes_and_refuses_one_extra(proc, source, output_key):
    limit = accounting.FILE_LIMITS[source]
    raw = proc.values[source]
    assert len(raw) < limit
    padded = raw + b" " * (limit - len(raw))
    (proc.target / source).write_bytes(padded)
    with accounting.ProcessObserver(_PID, proc_root=proc.root) as observer:
        assert observer.sample()[output_key]["status"] == "observed"
        (proc.target / source).write_bytes(padded + b" ")
        if source == "stat":
            _error("stat_too_large", observer.sample)
        else:
            assert observer.sample()[output_key] == {"status": "too_large", "values": None}


def test_short_reads_stop_after_limit_plus_one_without_reading_extra_bytes(proc, monkeypatch):
    limit = accounting.FILE_LIMITS["io"]
    raw = b"x" * (limit + 123)
    (proc.target / "io").write_bytes(raw)
    original_read = accounting.os.read
    reads = []

    def short_read(fd, maximum):
        value = original_read(fd, min(3, maximum))
        reads.append((maximum, len(value)))
        return value

    with accounting.ProcessObserver(_PID, proc_root=proc.root) as observer:
        monkeypatch.setattr(accounting.os, "read", short_read)
        _error("too_large", lambda: observer._read("io"))
    assert sum(size for _maximum, size in reads) == limit + 1
    assert all(0 < size <= 3 for _maximum, size in reads)
    assert reads[0][0] == limit + 1 and reads[-1] == (2, 2)
    assert len(reads) == (limit + 3) // 3
    assert (proc.target / "io").read_bytes() == raw


def test_held_directory_does_not_follow_replacement_at_original_pid_path(proc):
    with accounting.ProcessObserver(_PID, proc_root=proc.root) as observer:
        baseline = observer.sample()
        original_inode = accounting.os.fstat(observer._fd).st_ino
        retained = proc.root / "original-held-directory"
        proc.target.rename(retained)
        proc.target.mkdir()
        for name, raw in proc.values.items():
            (proc.target / name).write_bytes(_stat(start=_START + 1) if name == "stat" else raw)

        assert proc.target.stat().st_ino != original_inode
        assert accounting.parse_stat((proc.target / "stat").read_bytes(), _PID)[
            "starttime_ticks"
        ] == _START + 1
        assert observer.sample() == baseline
        assert accounting.os.fstat(observer._fd).st_ino == retained.stat().st_ino == original_inode
        assert observer.starttime == _START


@pytest.mark.parametrize("field", ["interval", "duration"])
def test_huge_integer_budget_gets_fixed_refusal_without_float_conversion_overflow(sampling, field):
    _error("invalid_" + field, lambda: sampling.run(**{field: 10**400}))
    assert sampling.observer.calls == 0 and sampling.emitted == []


@pytest.mark.parametrize("argv", [
    ["--pid", "private-sentinel-input"],
    ["--pid", "4321", "--output", "safe", "--private-sentinel-input"],
    ["--pid", "4321", "--output", "safe", "--count", "private-sentinel-input"],
    ["--pid", "4321", "--output", "safe", "--interval-seconds", "private-sentinel-input"],
    [],
])
def test_cli_invalid_arguments_are_fixed_private_free_errors_before_any_target_open(
    monkeypatch, capsys, argv,
):
    monkeypatch.setattr(accounting.os, "open", lambda *_a, **_k: pytest.fail("opened a target"))
    assert accounting.main(argv) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {"kind": "error", "reason": "invalid_arguments"}
    assert "private-sentinel-input" not in captured.err


@pytest.fixture
def cli(proc, monkeypatch):
    original_observer = accounting.ProcessObserver
    original_sampling = accounting.run_sampling
    clock = _Clock()
    monkeypatch.setattr(accounting, "ProcessObserver", lambda pid, start, uid: original_observer(
        pid, start, uid, proc_root=proc.root,
    ))
    monkeypatch.setattr(accounting.os, "sysconf", lambda _name: 100)

    def run(observer, **kwargs):
        return original_sampling(observer, **kwargs, clock_ns=clock.read, sleep=clock.sleep)

    monkeypatch.setattr(accounting, "run_sampling", run)

    def main(output, *extra):
        return accounting.main([
            "--pid", str(_PID), "--count", "1", "--output", str(output), *extra,
        ])

    return main


def test_cli_creates_private_jsonl_with_one_synthetic_sample(cli, tmp_path, capsys):
    output = tmp_path / "accounting.jsonl"
    assert cli(output) == 0
    assert output.stat().st_mode & 0o777 == 0o600
    lines = output.read_text().splitlines()
    records = [json.loads(line) for line in lines]
    assert [record["kind"] for record in records] == ["header", "sample", "end"]
    assert records[-1] == {"kind": "end", "reason": "sample_limit"}
    assert "private" not in output.read_text() and "hidden" not in output.read_text()
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("kind", ["file", "symlink"])
def test_cli_never_replaces_existing_output_or_follows_output_symlink(cli, tmp_path, capsys, kind):
    output = tmp_path / "output"
    original = b"original-private-output"
    if kind == "file":
        output.write_bytes(original)
        retained = output
    else:
        retained = tmp_path / "private-target"
        retained.write_bytes(original)
        output.symlink_to(retained)
    assert cli(output) == 2
    assert retained.read_bytes() == original
    assert json.loads(capsys.readouterr().err) == {"kind": "error", "reason": "output_error"}


def test_cli_identity_failure_is_nonzero_without_successful_end_record(cli, tmp_path, capsys):
    output = tmp_path / "identity-error.jsonl"
    assert cli(output, "--expected-starttime-ticks", str(_START + 1)) == 2
    records = [json.loads(line) for line in output.read_text().splitlines()]
    assert [record["kind"] for record in records] == ["header", "error"]
    assert records[-1]["reason"] == "identity_changed"
    assert capsys.readouterr().err == ""


@pytest.mark.parametrize("flag,value,reason", [
    ("--count", "0", "invalid_count"),
    ("--count", "1202", "invalid_count"),
    ("--interval-seconds", "nan", "invalid_interval"),
    ("--interval-seconds", "0.049", "invalid_interval"),
    ("--duration-seconds", "0", "invalid_duration"),
    ("--duration-seconds", "inf", "invalid_duration"),
])
def test_cli_invalid_budgets_do_not_open_target_or_create_output(
    tmp_path, monkeypatch, capsys, flag, value, reason,
):
    output = tmp_path / "must-not-exist"
    monkeypatch.setattr(accounting.os, "open", lambda *_a, **_k: pytest.fail("opened a target"))
    assert accounting.main([
        "--pid", str(_PID), "--output", str(output), flag, value,
    ]) == 2
    assert not output.exists()
    assert json.loads(capsys.readouterr().err) == {"kind": "error", "reason": reason}


@pytest.mark.parametrize("invalid", ["private-sentinel\x00path", "private-sentinel\ud800path"])
def test_cli_invalid_output_paths_have_fixed_error_without_path_contents(cli, capsys, invalid):
    assert cli(invalid) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {"kind": "error", "reason": "output_error"}
    assert "private-sentinel" not in captured.err
