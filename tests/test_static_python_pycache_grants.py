"""Live held-grant binding and original Linux inotify diagnostics.

Kernel cases are distinct from portable original-owner/refusal tests. Neither
set runs a native target or proves writer enclosure/quiescence/cache absence.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import time
from contextlib import contextmanager

import pytest

from lunar_evolution import static_python_pycache_grants as binding
from lunar_evolution import static_python_pycache_monitor as monitor
from lunar_evolution.producer_grant_anchors import (
    HeldProducerGrantPlan,
    ProducerGrantRequest,
    hold_producer_grants,
)


@contextmanager
def _held(tmp_path):
    base = tmp_path.resolve()
    working, output = base / "work", base / "output"
    working.mkdir()
    output.mkdir()
    requests = (ProducerGrantRequest(str(working), "writable-directory"),
                ProducerGrantRequest(str(working), "cwd"),
                ProducerGrantRequest(str(output), "writable-directory"))
    with hold_producer_grants(requests) as owner:
        yield owner, working, output


def _facts(owner, *, directories=None):
    roots = [{"grant_id": f"write-{index}", "path": record.path,
              "directories": list((directories or {}).get(record.path, (".",)))}
             for index, record in enumerate(owner.manifest.records)
             if "writable-directory" in record.roles]
    return {"schema": monitor.FINITE_WRITE_VIEW_SCHEMA,
            "original_grants_sha256": owner.manifest.manifest_sha256,
            "unknown_write_capabilities": [], "roots": roots}


def _arm(owner, facts=None, **overrides):
    raw = json.dumps(facts or _facts(owner), sort_keys=True, ensure_ascii=True,
                     separators=(",", ":")).encode("ascii")
    arguments = {"held_grants": owner, "reviewed_grants_bytes": raw,
                 "expected_grants_sha256": hashlib.sha256(raw).hexdigest(),
                 "deadline_monotonic_ns": time.monotonic_ns() + 10**10,
                 "diagnostic_profile": binding.ORIGINAL_GRANT_DIAGNOSTIC_PROFILE}
    arguments.update(overrides)
    return binding.GrantBoundPycacheMonitor.arm_before_target(**arguments)


def _assert_incomplete(result):
    assert result.original_grants_authenticated
    assert not result.writer_enclosure_verified
    assert not result.original_quiescence_observed
    assert not result.coverage_complete and not result.strict_view_accepted
    assert not result.production_admission


def test_default_off_refuses_before_touching_any_original_owner():
    with pytest.raises(binding.PycacheGrantBindingError, match="profile_disabled"):
        binding.GrantBoundPycacheMonitor.arm_before_target(
            held_grants=None, reviewed_grants_bytes=b"", expected_grants_sha256="",
            deadline_monotonic_ns=0,
        )


@pytest.mark.parametrize("owner", (None, object(), {}, ()))
def test_detached_or_missing_owner_refuses(owner):
    with pytest.raises(binding.PycacheGrantBindingError, match="original_owner_required"):
        binding.GrantBoundPycacheMonitor.arm_before_target(
            held_grants=owner, reviewed_grants_bytes=b"", expected_grants_sha256="",
            deadline_monotonic_ns=0,
            diagnostic_profile=binding.ORIGINAL_GRANT_DIAGNOSTIC_PROFILE,
        )


def test_detached_manifest_is_not_an_original_owner(tmp_path):
    with _held(tmp_path) as (owner, _working, _output):
        facts = _facts(owner)
        with pytest.raises(binding.PycacheGrantBindingError, match="original_owner_required"):
            _arm(owner.manifest, facts)


def test_closed_original_owner_refuses_before_kernel_acquisition(tmp_path, monkeypatch):
    with _held(tmp_path) as (owner, _working, _output):
        facts = _facts(owner)
    monkeypatch.setattr(monitor.FinitePycacheMonitor, "arm_before_target",
                        lambda **_options: pytest.fail("closed owner must not arm"))
    with pytest.raises(binding.PycacheGrantBindingError, match="original_owner_unavailable"):
        _arm(owner, facts)


@pytest.mark.parametrize("mutation", ("missing", "extra", "readonly_root", "grant_digest"))
def test_reviewed_view_must_match_the_entire_original_write_set(tmp_path, monkeypatch, mutation):
    with _held(tmp_path) as (owner, working, output):
        facts = _facts(owner)
        if mutation == "missing":
            facts["roots"].pop()
        elif mutation == "extra":
            extra = tmp_path.resolve() / "extra"
            extra.mkdir()
            facts["roots"].append({"grant_id": "extra", "path": str(extra), "directories": ["."]})
            facts["roots"].sort(key=lambda root: root["path"])
        elif mutation == "readonly_root":
            # A path can exist beside work/output without being an original
            # writable grant. The manifest cannot confer a new role on it.
            facts["roots"][0]["path"] = str(working.parent / "readonly")
            facts["roots"].sort(key=lambda root: root["path"])
        else:
            facts["original_grants_sha256"] = "a" * 64
        monkeypatch.setattr(monitor.FinitePycacheMonitor, "arm_before_target",
                            lambda **_options: pytest.fail("mismatched view must not arm"))
        code = "grant_scope" if mutation == "grant_digest" else "writable_root_set_changed"
        with pytest.raises((binding.PycacheGrantBindingError, monitor.PycacheMonitorError), match=code):
            _arm(owner, facts)
        assert output.is_dir()


def test_direct_construction_is_not_an_acquisition():
    with pytest.raises(binding.PycacheGrantBindingError, match="use_arm_before_target"):
        binding.GrantBoundPycacheMonitor()


linux_only = pytest.mark.skipif(sys.platform != "linux", reason="actual original Linux inotify")


@linux_only
def test_all_original_writes_bound_and_transient_kernel_event_retained(tmp_path):
    with _held(tmp_path) as (owner, working, output):
        nested = working / "precreated"
        nested.mkdir()
        facts = _facts(owner, directories={str(working): (".", "precreated")})
        capture = _arm(owner, facts)
        try:
            for root in (working, output, nested):
                cache = root / "candidate.pyc.314"
                cache.write_bytes(b"transient original cache")
                cache.unlink()
            result = capture.drain()
            _assert_incomplete(result)
            assert result.initial_scan_completed
            assert result.all_watches_installed_before_initial_scan
            assert "python_cache_observed" in result.failures
            actual_roots = {item.path: (item.device, item.inode) for item in result.directories
                            if item.relative_path == "."}
            expected = {record.path: (record.identity.device, record.identity.inode)
                        for record in owner.manifest.records if "writable-directory" in record.roles}
            assert actual_roots == expected
            assert {item.relative_directory for item in result.events
                    if item.event.name == b"candidate.pyc.314"} == {".", "precreated"}
            assert {item.grant_id for item in result.events
                    if item.event.name == b"candidate.pyc.314"} == {"write-0", "write-1"}
        finally:
            final = capture.finish()
        _assert_incomplete(final)
        assert "original_quiescence_unavailable" in final.failures
        assert not final.capture_running and final.terminal_scan_completed


@linux_only
def test_clean_final_scan_keeps_missing_enclosure_and_quiescence(tmp_path):
    with _held(tmp_path) as (owner, _working, _output):
        capture = _arm(owner)
        _assert_incomplete(capture.snapshot())
        final = capture.finish()
        _assert_incomplete(final)
        assert final.failures == ("original_quiescence_unavailable",)
        _assert_incomplete(capture.finish())


@linux_only
@pytest.mark.parametrize("operation", ("drain", "snapshot", "finish"))
def test_replaced_original_root_refuses_and_releases_monitor(tmp_path, operation):
    with _held(tmp_path) as (owner, working, _output):
        capture = _arm(owner)
        retained = working.with_name("original-work")
        working.rename(retained)
        working.mkdir()
        try:
            with pytest.raises(binding.PycacheGrantBindingError, match="original_owner_unavailable"):
                getattr(capture, operation)()
            assert capture._original_capture._closed
            with pytest.raises(binding.PycacheGrantBindingError, match="capture_refused"):
                capture.drain()
        finally:
            working.rmdir()
            retained.rename(working)


@linux_only
def test_leaving_original_context_refuses_even_with_clean_open_monitor(tmp_path):
    with _held(tmp_path) as (owner, _working, _output):
        capture = _arm(owner)
    with pytest.raises(binding.PycacheGrantBindingError, match="original_owner_unavailable"):
        capture.finish()
    assert capture._original_capture._closed


@linux_only
def test_another_live_owner_cannot_replace_original_object(tmp_path):
    with _held(tmp_path) as (owner, working, output):
        capture = _arm(owner)
        requests = (ProducerGrantRequest(str(working), "writable-directory"),
                    ProducerGrantRequest(str(working), "cwd"),
                    ProducerGrantRequest(str(output), "writable-directory"))
        with hold_producer_grants(requests) as other:
            assert type(other) is HeldProducerGrantPlan and other is not owner
            capture._owner = other
            with pytest.raises(binding.PycacheGrantBindingError, match="original_owner_changed"):
                capture.drain()
            assert capture._original_capture._closed


@linux_only
def test_root_replacement_during_arm_releases_the_actual_acquisition(tmp_path, monkeypatch):
    with _held(tmp_path) as (owner, working, _output):
        original_arm = monitor.FinitePycacheMonitor.arm_before_target
        retained = working.with_name("original-work")
        armed = []

        def arm_then_replace(**options):
            actual = original_arm(**options)
            armed.append(actual)
            working.rename(retained)
            working.mkdir()
            return actual

        monkeypatch.setattr(monitor.FinitePycacheMonitor, "arm_before_target", arm_then_replace)
        try:
            with pytest.raises(binding.PycacheGrantBindingError, match="original_owner_unavailable"):
                _arm(owner)
            assert len(armed) == 1 and armed[0]._closed
        finally:
            working.rmdir()
            retained.rename(working)


@linux_only
def test_role_set_change_with_same_owner_and_original_inodes_refuses(tmp_path):
    with _held(tmp_path) as (owner, _working, _output):
        capture = _arm(owner)
        records = owner._records
        owner._records = tuple(record for record in records if "cwd" in record.roles)
        try:
            with pytest.raises(binding.PycacheGrantBindingError, match="original_owner_changed"):
                capture.drain()
            assert capture._original_capture._closed
        finally:
            owner._records = records


@linux_only
def test_replacement_monitor_cannot_inherit_original_root_binding(tmp_path):
    with _held(tmp_path) as (owner, _working, _output):
        capture = _arm(owner)
        capture._capture = object()
        with pytest.raises(binding.PycacheGrantBindingError, match="original_capture_changed"):
            capture.drain()
        assert capture._original_capture._closed


@linux_only
@pytest.mark.parametrize("close_fault", (False, True))
def test_cleanup_error_cannot_replace_original_refusal(tmp_path, monkeypatch, close_fault):
    with _held(tmp_path) as (owner, _working, _output):
        capture = _arm(owner)
        reader = capture._original_capture
        original_finish = reader.finish
        original_close = monitor.os.close
        reader_fd, directory_fds = reader._fd, tuple(reader._owned_directory_fds)

        def fail_cleanup():
            raise OSError("inert cleanup failure")

        def close(descriptor):
            original_close(descriptor)
            if close_fault and descriptor == reader_fd:
                raise OSError("inert reader close uncertainty")

        monkeypatch.setattr(reader, "finish", fail_cleanup)
        monkeypatch.setattr(monitor.os, "close", close)
        capture._owner = None
        try:
            with pytest.raises(binding.PycacheGrantBindingError, match="original_owner_changed") as caught:
                capture.finish()
            expected = ["static_python_pycache_grants_reader_cleanup_unknown"]
            if close_fault:
                expected.append("static_python_pycache_grants_original_reader_cleanup_unknown")
            assert caught.value.__notes__ == expected
            assert reader._closed and not reader._owned_directory_fds
            for descriptor in (reader_fd, *directory_fds):
                with pytest.raises(OSError):
                    monitor.os.fstat(descriptor)
        finally:
            original_finish()


@linux_only
@pytest.mark.parametrize("boundary", ("allocation", "slot_initialization", "original_check"))
@pytest.mark.parametrize("finish_fault", (False, True))
def test_post_acquisition_initialization_failure_releases_original_reader(tmp_path, monkeypatch, boundary, finish_fault):
    with _held(tmp_path) as (owner, _working, _output):
        original_arm = monitor.FinitePycacheMonitor.arm_before_target
        armed = []
        failure = MemoryError("inert allocation fault") if boundary == "allocation" else KeyboardInterrupt()

        def fail_finish():
            raise OSError("inert finish-before-release fault")

        def retain_arm(**options):
            actual = original_arm(**options)
            armed.append(actual)
            if finish_fault:
                monkeypatch.setattr(actual, "finish", fail_finish)
            return actual

        def fail_setattr(*_args):
            raise failure

        class RefusingAllocation:
            def __new__(cls, *_args):
                raise failure

        monkeypatch.setattr(monitor.FinitePycacheMonitor, "arm_before_target", retain_arm)
        if boundary == "allocation":
            monkeypatch.setattr(binding, "object", RefusingAllocation, raising=False)
        elif boundary == "slot_initialization":
            monkeypatch.setattr(binding.GrantBoundPycacheMonitor, "__setattr__", fail_setattr, raising=False)
        else:
            monkeypatch.setattr(binding.GrantBoundPycacheMonitor, "_check_original", fail_setattr)
        with pytest.raises(type(failure)) as caught:
            _arm(owner)
        assert caught.value is failure
        assert len(armed) == 1 and armed[0]._closed
        assert armed[0]._owned_directory_fds == []
        if finish_fault:
            assert failure.__notes__ == ["static_python_pycache_grants_reader_cleanup_unknown"]
        owner.validate()


@linux_only
@pytest.mark.parametrize("operation", (copy.copy, copy.deepcopy))
def test_copy_does_not_transfer_original_acquisition(tmp_path, operation):
    with _held(tmp_path) as (owner, _working, _output):
        capture = _arm(owner)
        try:
            with pytest.raises(binding.PycacheGrantBindingError, match="original_owner_required"):
                operation(capture)
            _assert_incomplete(capture.drain())
        finally:
            capture.finish()


def test_non_linux_actual_acquisition_refuses_after_original_binding(tmp_path, monkeypatch):
    with _held(tmp_path) as (owner, _working, _output):
        monkeypatch.setattr(monitor.sys, "platform", "darwin")
        with pytest.raises(monitor.PycacheMonitorError, match="linux_inotify_unavailable"):
            _arm(owner)
