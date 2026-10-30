"""Bounded, read-only accounting for one explicitly identified Linux PID.

This development tool does not launch a task or establish acceptance evidence.
Only allowlisted numeric proc fields are emitted, never comm/argv/environment.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import stat
import sys
import time
from collections.abc import Callable
from pathlib import Path

MAX_SAMPLES = 1201
FILE_LIMITS = {"stat": 8192, "schedstat": 4096, "io": 4096, "status": 65536}
IO_FIELDS = (
    "rchar", "wchar", "syscr", "syscw", "read_bytes", "write_bytes", "cancelled_write_bytes"
)
LIMITATIONS = [
    "single_pid_only_no_descendants",
    "cpu_ticks_thread_group_excludes_children",
    "schedstat_and_context_switches_leader_only",
    "zero_schedstat_may_mean_accounting_disabled",
    "block_io_delay_ticks_may_be_disabled_and_do_not_cover_all_waits",
    "io_counters_do_not_measure_all_io_or_blocking",
    "cooperative_sampling_deadline_not_hard_syscall_timeout",
    "observation_only_no_execution_or_admission_authority",
]


class DiagnosticError(Exception):
    """A fixed reason code; never attach proc bytes or exception paths."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _uint(raw: bytes) -> int:
    if not raw or len(raw) > 20 or not raw.isdigit():
        raise DiagnosticError("malformed")
    value = int(raw)
    if value > (1 << 64) - 1:
        raise DiagnosticError("malformed")
    return value


def _positive(value: object, code: str, maximum: int = (1 << 31) - 1) -> int:
    if type(value) is not int or not 0 < value <= maximum:
        raise DiagnosticError(code)
    return value


def parse_stat(raw: bytes, pid: int) -> dict:
    """Read the numeric tail after comm, which may contain arbitrary bytes."""
    opening, closing = raw.find(b"("), raw.rfind(b")")
    if opening < 0 or closing <= opening:
        raise DiagnosticError("malformed")
    if _uint(raw[:opening].strip()) != pid:
        raise DiagnosticError("identity_changed")
    fields = raw[closing + 1:].split()
    if len(fields) < 20 or len(fields[0]) != 1:
        raise DiagnosticError("malformed")
    threads, starttime = _uint(fields[17]), _uint(fields[19])
    if not threads or not starttime:
        raise DiagnosticError("malformed")
    return {
        "starttime_ticks": starttime,
        "process_cpu_ticks": {"user": _uint(fields[11]), "system": _uint(fields[12])},
        "num_threads": threads,
        "block_io_delay_ticks": _uint(fields[39]) if len(fields) > 39 else None,
    }


def parse_schedstat(raw: bytes) -> dict:
    fields = raw.split()
    if len(fields) != 3:
        raise DiagnosticError("malformed")
    return dict(zip(("runtime_ns", "runqueue_ns", "timeslices"), map(_uint, fields)))


def _selected_lines(raw: bytes, names: set[bytes]) -> dict[bytes, bytes]:
    selected = {}
    for line in raw.splitlines():
        key, separator, value = line.partition(b":")
        if key in names:
            if not separator or key in selected:
                raise DiagnosticError("malformed")
            selected[key] = value.strip()
    if set(selected) != names:
        raise DiagnosticError("malformed")
    return selected


def parse_io(raw: bytes) -> dict:
    selected = _selected_lines(raw, {key.encode("ascii") for key in IO_FIELDS})
    return {key: _uint(selected[key.encode("ascii")]) for key in IO_FIELDS}


def parse_status(raw: bytes, uid: int) -> dict:
    # Owner drift must not be hidden by an unrelated missing counter.
    uids = _selected_lines(raw, {b"Uid"})[b"Uid"].split()
    if len(uids) != 4:
        raise DiagnosticError("malformed")
    if any(_uint(value) != uid for value in uids):
        raise DiagnosticError("owner_changed")
    selected = _selected_lines(raw, {b"voluntary_ctxt_switches", b"nonvoluntary_ctxt_switches"})
    return {
        "voluntary": _uint(selected[b"voluntary_ctxt_switches"]),
        "nonvoluntary": _uint(selected[b"nonvoluntary_ctxt_switches"]),
    }


def _os_reason(error: OSError) -> str:
    if isinstance(error, PermissionError):
        return "denied"
    if isinstance(error, (FileNotFoundError, ProcessLookupError)):
        return "unavailable"
    return "read_error"


class ProcessObserver:
    def __init__(
        self, pid: int, expected_starttime_ticks: int | None = None,
        expected_uid: int | None = None, *, proc_root: str | Path = "/proc",
    ):
        self.pid = _positive(pid, "invalid_pid")
        self.uid = os.geteuid()
        if expected_uid is not None and (
            type(expected_uid) is not int or expected_uid != self.uid
        ):
            raise DiagnosticError("invalid_expected_uid")
        self.starttime = (
            _positive(expected_starttime_ticks, "invalid_starttime", (1 << 64) - 1)
            if expected_starttime_ticks is not None else None
        )
        self.binding = "caller_expected" if self.starttime is not None else "baseline_only"
        self._proc_root = Path(proc_root)
        self._fd = None

    def __enter__(self):
        try:
            self._fd = os.open(
                self._proc_root / str(self.pid),
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
            )
            self._check_owner()
        except OSError as error:
            self.close()
            raise DiagnosticError("target_" + _os_reason(error)) from None
        except DiagnosticError:
            self.close()
            raise
        return self

    def close(self):
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def __exit__(self, *_):
        self.close()

    def _check_owner(self):
        if self._fd is None:
            raise DiagnosticError("target_not_open")
        try:
            owner = os.fstat(self._fd).st_uid
        except OSError as error:
            raise DiagnosticError("target_" + _os_reason(error)) from None
        if owner != self.uid:
            raise DiagnosticError("owner_changed")

    def _read(self, name: str) -> bytes:
        limit = FILE_LIMITS[name]
        fd = None
        try:
            fd = os.open(
                name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                dir_fd=self._fd,
            )
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise DiagnosticError("not_regular")
            chunks, size = [], 0
            while size <= limit:
                chunk = os.read(fd, limit + 1 - size)
                if not chunk:
                    return b"".join(chunks)
                chunks.append(chunk)
                size += len(chunk)
            raise DiagnosticError("too_large")
        except OSError as error:
            raise DiagnosticError(_os_reason(error)) from None
        finally:
            if fd is not None:
                os.close(fd)

    def _stat(self):
        try:
            return parse_stat(self._read("stat"), self.pid)
        except DiagnosticError as error:
            if error.code == "identity_changed":
                raise
            raise DiagnosticError("stat_" + error.code) from None

    def sample(self) -> dict:
        self._check_owner()
        before = self._stat()
        if self.starttime is not None and before["starttime_ticks"] != self.starttime:
            raise DiagnosticError("identity_changed")
        optional = {}
        for name, parser in (
            ("schedstat", parse_schedstat), ("io", parse_io),
            ("status", lambda raw: parse_status(raw, self.uid)),
        ):
            try:
                values = parser(self._read(name))
                optional[name] = {"status": "observed", "values": values}
            except DiagnosticError as error:
                if error.code == "owner_changed":
                    raise
                optional[name] = {"status": error.code, "values": None}
        after = self._stat()
        self._check_owner()
        if before["starttime_ticks"] != after["starttime_ticks"]:
            raise DiagnosticError("identity_changed")
        if self.starttime is None:
            self.starttime = before["starttime_ticks"]
        return {
            "target": {"pid": self.pid, "uid": self.uid, "starttime_ticks": self.starttime,
                       "identity_binding": self.binding},
            "process_stat": {"status": "observed", "values": after},
            "leader_schedstat": optional["schedstat"],
            "process_io": optional["io"],
            "leader_context_switches": optional["status"],
        }


def _seconds(value: object, minimum: float, maximum: float, code: str) -> float:
    if type(value) not in (int, float):
        raise DiagnosticError(code)
    if not minimum <= value <= maximum or not math.isfinite(value):
        raise DiagnosticError(code)
    return float(value)


def _sampling_options(count, interval_seconds, duration_seconds):
    _positive(count, "invalid_count", MAX_SAMPLES)
    interval = _seconds(interval_seconds, 0.05, 60, "invalid_interval")
    duration = _seconds(duration_seconds, 0, 600, "invalid_duration")
    if duration <= 0:
        raise DiagnosticError("invalid_duration")
    return interval, duration


def run_sampling(
    observer: ProcessObserver, *, count: int, interval_seconds: float,
    duration_seconds: float, emit: Callable[[dict], None],
    clock_ns: Callable[[], int] = time.monotonic_ns,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    interval, duration = _sampling_options(count, interval_seconds, duration_seconds)
    deadline = clock_ns() + int(duration * 1_000_000_000)
    emit({"kind": "header", "schema_version": 1,
          "scope": "linux-process-accounting-diagnostic",
          "clock_ticks_per_second": os.sysconf("SC_CLK_TCK"),
          "limits": {"samples": count, "interval_seconds": interval,
                     "duration_seconds": duration, "file_bytes": dict(FILE_LIMITS)},
          "limitations": list(LIMITATIONS)})
    reason = "sample_limit"
    for index in range(count):
        started = clock_ns()
        if started >= deadline:
            reason = "duration_limit"
            break
        try:
            sample = observer.sample()
        except DiagnosticError as error:
            emit({"kind": "error", "sample_index": index, "reason": error.code,
                  "sample_window_monotonic_ns": [started, clock_ns()]})
            return error.code
        emit({"kind": "sample", "sample_index": index,
              "sample_window_monotonic_ns": [started, clock_ns()], **sample})
        if index + 1 < count:
            remaining = deadline - clock_ns()
            if remaining <= 0:
                reason = "duration_limit"
                break
            sleep(min(interval, remaining / 1_000_000_000))
    emit({"kind": "end", "reason": reason})
    return reason


class _Parser(argparse.ArgumentParser):
    def error(self, message):
        raise DiagnosticError("invalid_arguments")


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(prog="linux-process-accounting", description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--expected-starttime-ticks", type=int)
    parser.add_argument("--expected-uid", type=int)
    parser.add_argument("--count", type=int, default=61)
    parser.add_argument("--interval-seconds", type=float, default=1.0)
    parser.add_argument("--duration-seconds", type=float, default=60.0)
    parser.add_argument("--output", required=True)
    try:
        args = parser.parse_args(argv)
        _sampling_options(args.count, args.interval_seconds, args.duration_seconds)
        with ProcessObserver(args.pid, args.expected_starttime_ticks, args.expected_uid) as observer:
            fd = os.open(
                args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
            )
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                def emit(record):
                    output.write(json.dumps(record, separators=(",", ":"), allow_nan=False) + "\n")
                    output.flush()
                reason = run_sampling(
                    observer, count=args.count, interval_seconds=args.interval_seconds,
                    duration_seconds=args.duration_seconds, emit=emit,
                )
        return 0 if reason in ("sample_limit", "duration_limit") else 2
    except (DiagnosticError, OSError, ValueError) as error:
        code = error.code if isinstance(error, DiagnosticError) else "output_error"
        print(json.dumps({"kind": "error", "reason": code}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
