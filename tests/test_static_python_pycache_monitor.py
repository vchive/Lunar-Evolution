"""Pure wire tests plus Linux original directory/inotify diagnostics only.

No solver, native target, evaluator, grant authentication or accepted strict
write-view claim is exercised. macOS runs the pure parser/refusal coverage.
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
import sys
import time

import pytest

from lunar_evolution import static_python_pycache_monitor as monitor


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":")).encode("ascii")


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _facts(root, directories=(".",)):
    return {"schema": monitor.FINITE_WRITE_VIEW_SCHEMA, "original_grants_sha256": "a" * 64,
            "unknown_write_capabilities": [],
            "roots": [{"grant_id": "original-output-grant", "path": str(root), "directories": list(directories)}]}


def _parse(facts):
    raw = _canonical(facts)
    return monitor.parse_reviewed_write_view(raw, expected_sha256=_sha(raw), original_grants_sha256="a" * 64)


def _arm(root, directories=(".",), **overrides):
    raw = _canonical(_facts(root, directories))
    arguments = {"reviewed_grants_bytes": raw, "expected_grants_sha256": _sha(raw),
                 "original_grants_sha256": "a" * 64, "deadline_monotonic_ns": time.monotonic_ns() + 10**10,
                 "diagnostic_profile": monitor.FINITE_WRITE_VIEW_PROFILE}
    arguments.update(overrides)
    return monitor.FinitePycacheMonitor.arm_before_target(**arguments)


def _event(name=b"", mask=monitor.IN_CREATE, wd=1, cookie=0):
    padded = name + b"\0" if name else b""
    padded += b"\0" * (-len(padded) % 4)
    return struct.pack("=iIII", wd, mask, cookie, len(padded)) + padded


def test_grants_reference_explicit_finite_roots_without_authenticating_them(tmp_path):
    result = _parse(_facts(tmp_path, (".", "output", "output/nested")))
    assert result.original_grants_sha256 == "a" * 64
    assert result.roots[0].directories == (".", "output", "output/nested")
    assert result.roots[0].grant_id == "original-output-grant"


@pytest.mark.parametrize("mutation", (
    "unknown", "grant_digest", "relative_root", "root_alias", "missing_parent", "duplicate_directory",
    "overlap_root", "duplicate_grant", "extra", "bad_directory",
))
def test_unbounded_or_unknown_write_views_refuse(tmp_path, mutation):
    facts = _facts(tmp_path)
    root = facts["roots"][0]
    if mutation == "unknown":
        facts["unknown_write_capabilities"] = ["unreviewed-inherited-fd"]
    elif mutation == "grant_digest":
        facts["original_grants_sha256"] = "b" * 64
    elif mutation == "relative_root":
        root["path"] = "relative"
    elif mutation == "root_alias":
        root["path"] += "/../alias"
    elif mutation == "missing_parent":
        root["directories"] = [".", "missing/child"]
    elif mutation == "duplicate_directory":
        root["directories"] = [".", "."]
    elif mutation == "overlap_root":
        facts["roots"].append({**root, "path": str(tmp_path / "child"), "grant_id": "other"})
    elif mutation == "duplicate_grant":
        facts["roots"].append({**root, "path": str(tmp_path) + "-other"})
    elif mutation == "extra":
        facts["authenticated"] = True
    else:
        root["directories"] = [".", "../escape"]
    with pytest.raises(monitor.PycacheMonitorError, match="grant_scope"):
        _parse(facts)


def test_manifest_pin_and_duplicate_key_refuse(tmp_path):
    raw = _canonical(_facts(tmp_path))
    with pytest.raises(monitor.PycacheMonitorError, match="grant_pin"):
        monitor.parse_reviewed_write_view(raw + b" ", expected_sha256=_sha(raw), original_grants_sha256="a" * 64)
    raw = b'{"schema":"first","schema":"second"}'
    with pytest.raises(monitor.PycacheMonitorError, match="duplicate_key"):
        monitor.parse_reviewed_write_view(raw, expected_sha256=_sha(raw), original_grants_sha256="a" * 64)


@pytest.mark.parametrize("name", (
    b"__pycache__", b"__pycache__.tmp", b"module.pyc", b"module.pyo", b"module.pyc.12345",
    b".module.cpython-313.pyc.tmp", b"module.pyo~", b"module.pyc-backup",
))
def test_standard_and_temporary_cache_names(name):
    assert monitor.is_python_cache_name(name)


@pytest.mark.parametrize("name", (b"module.py", b"my_pycache", b"archive.pyconfig", b"output.txt"))
def test_other_names_are_not_cache_evidence(name):
    assert not monitor.is_python_cache_name(name)


def test_pure_event_parser_retains_original_mask_cookie_and_bytes():
    raw = _event(b"module.pyc.314", monitor.IN_MOVED_TO, 7, 123) + _event(mask=monitor.IN_Q_OVERFLOW, wd=-1)
    first, second = monitor.parse_inotify_events(raw)
    assert (first.watch_descriptor, first.mask, first.cookie, first.name) == (7, monitor.IN_MOVED_TO, 123, b"module.pyc.314")
    assert second.watch_descriptor == -1 and second.mask == monitor.IN_Q_OVERFLOW


@pytest.mark.parametrize("raw", (
    b"", b"short", struct.pack("=iIII", 1, monitor.IN_CREATE, 0, 4097),
    struct.pack("=iIII", 1, monitor.IN_CREATE, 0, 4) + b"abcd",
    struct.pack("=iIII", 1, monitor.IN_CREATE, 0, 4) + b"x\0y\0",
    _event(b"../bad"), _event(b".."), _event(wd=0), _event(wd=-1), _event(mask=0x80000000),
))
def test_malformed_event_frames_fail_coverage(raw):
    with pytest.raises(monitor.PycacheMonitorError, match="event_frame"):
        monitor.parse_inotify_events(raw)


def test_profile_default_disabled(tmp_path):
    with pytest.raises(monitor.PycacheMonitorError, match="profile_disabled"):
        _arm(tmp_path, diagnostic_profile=None)


def test_macos_actual_monitor_refuses_without_linux_calls(tmp_path, monkeypatch):
    monkeypatch.setattr(monitor.sys, "platform", "darwin")
    monkeypatch.setattr(monitor.ctypes, "CDLL", lambda *_args, **_kwargs: pytest.fail("must not load libc"))
    with pytest.raises(monitor.PycacheMonitorError, match="linux_inotify_unavailable"):
        _arm(tmp_path)


linux_only = pytest.mark.skipif(sys.platform != "linux", reason="original Linux inotify diagnostics")


@linux_only
def test_original_transient_cache_creation_is_retained_after_unlink(tmp_path):
    capture = _arm(tmp_path)
    try:
        path = tmp_path / "module.pyc.314"
        path.write_bytes(b"original temporary bytes")
        path.unlink()
        observed = capture.drain()
        assert "python_cache_observed" in observed.failures
        assert any(item.event.name == b"module.pyc.314" for item in observed.events)
        assert not observed.strict_view_accepted and not observed.coverage_complete
    finally:
        final = capture.finish()
    assert "original_quiescence_unavailable" in final.failures
    assert not final.original_quiescence_observed and not final.production_admission


@linux_only
def test_all_precreated_nested_directories_are_watched_and_bound(tmp_path):
    nested = tmp_path / "output" / "nested"
    nested.mkdir(parents=True)
    capture = _arm(tmp_path, (".", "output", "output/nested"))
    try:
        (nested / "result.pyo").write_bytes(b"transient")
        (nested / "result.pyo").unlink()
        result = capture.drain()
        assert result.initial_scan_completed and result.all_watches_installed_before_initial_scan
        event = next(item for item in result.events if item.event.name == b"result.pyo")
        assert event.relative_directory == "output/nested"
        identity = next(item for item in result.directories if item.relative_path == "output/nested")
        actual = nested.stat()
        assert (identity.device, identity.inode, identity.mode, identity.nlink) == (
            actual.st_dev, actual.st_ino, actual.st_mode, actual.st_nlink,
        )
    finally:
        capture.finish()


@linux_only
@pytest.mark.parametrize("operation", ("create", "move_in"))
def test_new_or_moved_directory_invalidates_coverage_without_new_watches(tmp_path, operation):
    root = tmp_path / "write"
    root.mkdir()
    other = tmp_path / "staged"
    other.mkdir()
    capture = _arm(root)
    try:
        if operation == "create":
            (root / "new").mkdir()
        else:
            other.rename(root / "new")
        result = capture.drain()
        assert "directory_topology_changed" in result.failures
        assert len(result.directories) == 1
    finally:
        capture.finish()


@linux_only
@pytest.mark.parametrize("kind", ("unlisted_directory", "cache", "symlink", "hardlink", "fifo"))
def test_initial_scan_rejects_uncovered_or_cache_material(tmp_path, kind):
    if kind == "unlisted_directory":
        (tmp_path / "unlisted").mkdir()
    elif kind == "cache":
        (tmp_path / "old.pyc").write_bytes(b"existing")
    elif kind == "symlink":
        (tmp_path / "alias").symlink_to("outside")
    elif kind == "hardlink":
        (tmp_path / "original").write_bytes(b"shared")
        os.link(tmp_path / "original", tmp_path / "alias")
    else:
        os.mkfifo(tmp_path / "fifo")
    with pytest.raises(monitor.PycacheMonitorError, match="initial_view_incomplete"):
        _arm(tmp_path)


@linux_only
def test_directory_replacement_and_mode_changes_never_restore_coverage(tmp_path):
    root = tmp_path / "write"
    root.mkdir()
    capture = _arm(root)
    original_mode = root.stat().st_mode & 0o777
    root.chmod(0o700 if original_mode != 0o700 else 0o750)
    root.chmod(original_mode)
    root.rename(tmp_path / "old")
    root.mkdir()
    final = capture.finish()
    assert "directory_identity_changed" in final.failures
    assert "watch_coverage_lost" in final.failures
    assert not final.strict_view_accepted


@linux_only
def test_empty_queue_and_public_boolean_do_not_supply_quiescence(tmp_path):
    capture = _arm(tmp_path)
    try:
        with pytest.raises(TypeError):
            capture.finish(True)
        interim = capture.drain()
        assert interim.capture_running and not interim.original_quiescence_observed
    finally:
        result = capture.finish()
    assert result.terminal_scan_completed and not result.capture_running
    assert result.failures == ("original_quiescence_unavailable",)
    assert result.original_grants_authenticated is False
    assert result.writer_enclosure_verified is False
    assert result.coverage_complete is result.strict_view_accepted is result.production_admission is False
    assert capture.finish() == result


@linux_only
def test_reader_start_failure_releases_original_descriptors(tmp_path, monkeypatch):
    original_close = monitor.os.close
    closed = []

    def close(descriptor):
        closed.append(descriptor)
        return original_close(descriptor)

    def refuse_start(_thread):
        raise RuntimeError("artificial startup failure")

    monkeypatch.setattr(monitor.os, "close", close)
    monkeypatch.setattr(monitor.threading.Thread, "start", refuse_start)
    with pytest.raises(monitor.PycacheMonitorError, match="reader_start"):
        _arm(tmp_path)
    # Component traversal also closes descriptors; the monitor's originals must
    # all be invalid after release, with no new descriptor allocation here.
    for descriptor in set(closed):
        with pytest.raises(OSError):
            os.fstat(descriptor)


@linux_only
@pytest.mark.parametrize("fault_kind", ("memory", "interrupt", "os", "attribute"))
def test_acquisition_primary_survives_real_reader_close_failure(tmp_path, monkeypatch, fault_kind):
    acquisition_error = {"memory": MemoryError("inert scan failure"), "interrupt": KeyboardInterrupt(),
                         "os": OSError("inert scan failure"), "attribute": AttributeError("inert scan failure")}[fault_kind]
    cleanup_error = OSError("inert reader close failure")
    original_close = os.close
    captures, original_fds, reader_fds = [], [], []

    def fail_scan(self):
        captures.append(self)
        reader_fds.append(self._fd)
        original_fds.extend((self._fd, *self._owned_directory_fds))
        raise acquisition_error

    def close(descriptor):
        original_close(descriptor)
        if reader_fds and descriptor == reader_fds[0]:
            raise cleanup_error

    monkeypatch.setattr(monitor.FinitePycacheMonitor, "_scan", fail_scan)
    monkeypatch.setattr(monitor.os, "close", close)
    expected_type = monitor.PycacheMonitorError if fault_kind in {"os", "attribute"} else type(acquisition_error)
    with pytest.raises(expected_type) as caught:
        _arm(tmp_path)
    if fault_kind in {"os", "attribute"}:
        assert str(caught.value) == "static_python_pycache_monitor_directory_or_inotify_unavailable"
        assert caught.value.__context__ is acquisition_error
    else:
        assert caught.value is acquisition_error
    assert acquisition_error.__notes__ == ["static_python_pycache_monitor_reader_cleanup_unknown"]
    assert len(captures) == 1 and captures[0]._closed
    assert captures[0]._owned_directory_fds == []
    assert "reader_resource_cleanup_unknown" in captures[0]._failures
    for descriptor in original_fds:
        with pytest.raises(OSError):
            os.fstat(descriptor)


def test_overflow_watch_loss_and_event_limit_remain_diagnostic(monkeypatch):
    # Pure event-flow exercise on an inert object; no fake kernel capture claim.
    instance = object.__new__(monitor.FinitePycacheMonitor)
    instance._read_bytes = 0
    instance._events = []
    instance._failures = []
    instance._watches = {}
    instance._data_lock = monitor.threading.Lock()
    instance._stop = monitor.threading.Event()
    instance._consume(_event(mask=monitor.IN_Q_OVERFLOW, wd=-1))
    instance._consume(_event(mask=monitor.IN_IGNORED, wd=7))
    assert "kernel_queue_overflow" in instance._failures
    assert "unknown_watch" in instance._failures
    assert "watch_coverage_lost" in instance._failures
    monkeypatch.setattr(monitor, "MAX_EVENTS", len(instance._events))
    instance._consume(_event(b"output.txt"))
    assert "event_limit" in instance._failures
    assert instance._stop.is_set()


def test_original_capture_byte_budget_cannot_be_silently_truncated(monkeypatch):
    instance = object.__new__(monitor.FinitePycacheMonitor)
    instance._read_bytes = 0
    instance._events = []
    instance._failures = []
    instance._watches = {}
    instance._data_lock = monitor.threading.Lock()
    instance._stop = monitor.threading.Event()
    monkeypatch.setattr(monitor, "MAX_CAPTURE_BYTES", 1)
    instance._consume(_event(b"output.txt"))
    assert instance._failures == ["capture_byte_limit"]
    assert instance._events == [] and instance._stop.is_set()


def _deadline_instance():
    instance = object.__new__(monitor.FinitePycacheMonitor)
    instance._deadline = 100
    instance._failures = []
    instance._data_lock = monitor.threading.Lock()
    instance._io_lock = monitor.threading.Lock()
    instance._stop = monitor.threading.Event()
    return instance


def test_original_deadline_bounds_each_directory_component_and_closes_partial_fds(monkeypatch):
    clock = iter((90, 95, 100))
    opened, closed = [], []

    def open_directory(path, *_args, **_kwargs):
        opened.append(path)
        return len(opened) + 1000

    monkeypatch.setattr(monitor.time, "monotonic_ns", lambda: next(clock))
    monkeypatch.setattr(monitor.os, "open", open_directory)
    monkeypatch.setattr(monitor.os, "close", closed.append)
    with pytest.raises(monitor.PycacheMonitorError, match="deadline"):
        monitor._open_directory("/one/two", 100)
    assert opened == ["/", "one"]
    assert closed == [1001, 1002]


@pytest.mark.parametrize("cleanup_fault", (False, True))
def test_component_close_failure_preserves_reused_number_and_cleans_new_child(tmp_path, monkeypatch, cleanup_fault):
    original_open, original_close = os.open, os.close
    opened, replacements, injected = [], [], []
    primary = OSError("inert retired component close fault")

    def open_directory(*args, **options):
        descriptor = original_open(*args, **options)
        opened.append(descriptor)
        return descriptor

    def close(descriptor):
        original_close(descriptor)
        if descriptor == opened[0] and not injected:
            injected.append(True)
            replacement = original_open(os.devnull, os.O_RDONLY)
            if replacement != descriptor:
                os.dup2(replacement, descriptor)
                original_close(replacement)
            replacements.append(descriptor)
            raise primary
        if cleanup_fault and descriptor == opened[1]:
            raise OSError("inert child cleanup fault")

    monkeypatch.setattr(monitor.os, "open", open_directory)
    monkeypatch.setattr(monitor.os, "close", close)
    try:
        with pytest.raises(OSError) as caught:
            monitor._open_directory(str(tmp_path), time.monotonic_ns() + 10**10)
        assert caught.value is primary
        assert len(opened) == 2 and replacements == [opened[0]]
        os.fstat(replacements[0])
        with pytest.raises(OSError):
            os.fstat(opened[1])
        assert getattr(primary, "__notes__", []) == (
            ["static_python_pycache_monitor_directory_cleanup_unknown"] if cleanup_fault else []
        )
    finally:
        for descriptor in {*opened, *replacements}:
            try:
                original_close(descriptor)
            except OSError:
                pass


@linux_only
def test_identity_failure_and_uncertain_close_preserve_primary_before_reader_transfer(tmp_path, monkeypatch):
    original_close = os.close
    original_release = monitor.FinitePycacheMonitor._release
    primary = MemoryError("inert pre-transfer identity fault")
    directory_fds, captures = [], []

    def fail_identity(descriptor, *_args):
        directory_fds.append(descriptor)
        raise primary

    def close(descriptor):
        original_close(descriptor)
        if descriptor in directory_fds:
            raise OSError("inert identity descriptor close uncertainty")

    def retain_release(self):
        captures.append(self)
        return original_release(self)

    monkeypatch.setattr(monitor, "_identity", fail_identity)
    monkeypatch.setattr(monitor.os, "close", close)
    monkeypatch.setattr(monitor.FinitePycacheMonitor, "_release", retain_release)
    with pytest.raises(MemoryError) as caught:
        _arm(tmp_path)
    assert caught.value is primary
    assert primary.__notes__ == ["static_python_pycache_monitor_directory_cleanup_unknown"]
    assert len(captures) == 1 and captures[0]._closed and captures[0]._fd == -1
    assert captures[0]._owned_directory_fds == []
    for descriptor in directory_fds:
        with pytest.raises(OSError):
            os.fstat(descriptor)


def test_expired_original_deadline_skips_scan_and_read_without_terminal_coverage(monkeypatch):
    instance = _deadline_instance()
    instance._directories = [(None, None, None)]
    instance._closed = False
    instance.snapshot = lambda: "inert diagnostic only"
    monkeypatch.setattr(monitor.time, "monotonic_ns", lambda: 100)
    monkeypatch.setattr(monitor.os, "fstat", lambda *_args: pytest.fail("expired scan must not touch directory"))
    monkeypatch.setattr(monitor.os, "read", lambda *_args: pytest.fail("expired drain must not read"))
    assert instance._scan() is False
    assert instance.drain() == "inert diagnostic only"
    assert instance._failures == ["capture_deadline_reached"]
    assert instance._stop.is_set()


def test_reader_poll_timeout_uses_original_remaining_budget(monkeypatch):
    instance = _deadline_instance()
    instance._deadline = 3_000_001
    instance._started = monitor.threading.Event()
    instance._fd = 1234
    timeouts = []

    class Poll:
        def register(self, *_args):
            pass

        def poll(self, timeout):
            timeouts.append(timeout)
            instance._stop.set()
            return []

    monkeypatch.setattr(monitor.time, "monotonic_ns", lambda: 1)
    monkeypatch.setattr(monitor.select, "poll", Poll, raising=False)
    instance._reader()
    assert timeouts == [3]


@pytest.mark.parametrize("resource", ("reader", "directory"))
@pytest.mark.parametrize("close_effect", ("released_and_reused", "still_open"))
def test_release_retires_real_fd_numbers_before_close_failure_and_continues(tmp_path, monkeypatch, resource, close_effect):
    # Actual portable descriptors exercise resource retirement only. This is
    # neither a kernel event acquisition nor evidence about original writers.
    instance = _deadline_instance()
    instance._thread = None
    instance._closed = False
    instance._fd = os.open(os.devnull, os.O_RDONLY)
    instance._owned_directory_fds = [os.open(tmp_path, os.O_RDONLY) for _ in range(3)]
    instance._directories = [(fd, None, object()) for fd in instance._owned_directory_fds]
    identities = tuple(instance._directories)
    original_fds = (instance._fd, *instance._owned_directory_fds)
    fault_fd = instance._fd if resource == "reader" else instance._owned_directory_fds[-1]
    original_close = os.close
    fault = OSError("inert descriptor close fault")
    calls, injected = [], []

    def close(descriptor):
        calls.append(descriptor)
        if descriptor == fault_fd and not injected:
            injected.append(True)
            if close_effect == "released_and_reused":
                original_close(descriptor)
                replacement = os.open(os.devnull, os.O_RDONLY)
                if replacement != descriptor:
                    os.dup2(replacement, descriptor)
                    original_close(replacement)
            raise fault
        return original_close(descriptor)

    monkeypatch.setattr(monitor.os, "close", close)
    try:
        with pytest.raises(OSError) as caught:
            instance._release()
        assert caught.value is fault
        assert instance._closed and instance._fd == -1 and instance._owned_directory_fds == []
        assert tuple(instance._directories) == identities
        assert instance._failures == ["reader_resource_cleanup_unknown"]
        assert set(calls) == set(original_fds) and len(calls) == len(original_fds)
        # A close failure leaves the old or a newly reused number live. Since
        # this object's ownership retired first, a later release must not
        # close either number as if it still belonged to the capture.
        os.fstat(fault_fd)
        instance._release()
        os.fstat(fault_fd)
        assert calls.count(fault_fd) == 1
        for descriptor in set(original_fds) - {fault_fd}:
            with pytest.raises(OSError):
                os.fstat(descriptor)
    finally:
        # The injected uncertain close is intentionally not retried by the
        # component. The test owns this known retained/replacement descriptor.
        original_close(fault_fd)


@linux_only
def test_arm_cannot_return_success_after_directory_open_consumes_deadline(tmp_path, monkeypatch):
    current = [0]
    original_open = monitor._open_directory

    def open_and_expire(path, deadline):
        descriptor = original_open(path, deadline)
        current[0] = deadline
        return descriptor

    monkeypatch.setattr(monitor.time, "monotonic_ns", lambda: current[0])
    monkeypatch.setattr(monitor, "_open_directory", open_and_expire)
    with pytest.raises(monitor.PycacheMonitorError, match="deadline"):
        _arm(tmp_path, deadline_monotonic_ns=100)
