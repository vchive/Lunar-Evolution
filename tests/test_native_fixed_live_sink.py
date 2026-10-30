"""Host-owned pipe and synthetic expanded-profile comparison; no model/runtime claim."""

from __future__ import annotations

import copy
import json
import os
import threading
import time
from dataclasses import replace

import pytest
from test_native_grant_control import (
    control_owner as control_owner,  # noqa: PLC0414 - pytest fixture re-export
)
from test_static_python_fixed_live_modules import _comparison_vector
from test_static_python_fixed_profile import _closure_raw, _image, _parse, _pins, _raw, _sha

from lunar_evolution import static_python_fixed_live_modules as live
from lunar_evolution.native_bootstrap import (
    FIXED_LIVE_MODULES_SINK_FD,
    NativeBootstrapError,
    NativeBootstrapPrivateSink,
    encode_native_bootstrap_control_v2,
    encode_native_bootstrap_control_v3,
)
from lunar_evolution.native_fixed_live_sink import (
    FixedPythonLiveSinkRequest,
    NativeFixedLiveSinkCapture,
    NativeFixedLiveSinkError,
)
from tools.static_python_rsi_fixture.live_module_source import prepare_fixed_live_sink_launcher


def _writer(fd, raw):
    def write():
        try:
            offset = 0
            while offset < len(raw):
                offset += os.write(fd, raw[offset:])
        except BrokenPipeError:
            pass
        finally:
            os.close(fd)

    thread = threading.Thread(target=write)
    thread.start()
    return thread


def _request_vector():
    installed, main, _startup, payload = _comparison_vector()
    description = installed.to_dict()
    closure = json.loads(installed.closure_bytes)
    closure["sources"].append({"path": live.FIXED_LIVE_SINK_LAUNCHER_PATH,
                               "size": live.FIXED_LIVE_SINK_LAUNCHER_SOURCE_BYTES,
                               "sha256": live.FIXED_LIVE_SINK_LAUNCHER_SOURCE_SHA256})
    closure["sources"].sort(key=lambda item: item["path"])
    description["runtime_closure_sha256"] = _sha(_closure_raw(closure))
    installed = _parse(description, closure, _pins(description, closure))
    return FixedPythonLiveSinkRequest(installed, _image(), main, installed.installation_sha256), payload


def test_bound_host_comparison_uses_original_image_pid_and_manifest_without_authority():
    request, payload = _request_vector()
    request.validate(target_sha256=_sha(_image()))
    observed = request.compare(_raw(payload) + b"\n", image_device=19, image_inode=77,
                               target_pid=123, manifest_sha256=payload["manifest_sha256"])
    assert observed.canonical_bytes == _raw(payload) + b"\n"
    assert not observed.live_runtime_authenticated
    assert not observed.immutable_custody_verified and not observed.production_admission


@pytest.mark.parametrize("field,value", [("image_device", 20), ("image_inode", 78),
                                         ("target_pid", 124), ("manifest_sha256", "b" * 64)])
def test_bound_comparison_refuses_original_binding_drift(field, value):
    request, payload = _request_vector()
    arguments = {"image_device": 19, "image_inode": 77, "target_pid": 123,
                 "manifest_sha256": payload["manifest_sha256"]}
    arguments[field] = value
    with pytest.raises(NativeFixedLiveSinkError, match="comparison_refused"):
        request.compare(_raw(payload) + b"\n", **arguments)


@pytest.mark.parametrize("fault", ["partial", "table", "image", "claims", "noncanonical"])
def test_bound_comparison_refuses_partial_changed_or_self_authorized_wire(fault):
    request, payload = _request_vector()
    payload = copy.deepcopy(payload)
    if fault == "table":
        payload["modules"][0]["loader"] = "untrusted"
    elif fault == "image":
        payload["image"]["sha256"] = "b" * 64
    elif fault == "claims":
        payload["claims"]["production_admission"] = True
    raw = _raw(payload) + b"\n"
    if fault == "partial":
        raw = raw[:-2]
    elif fault == "noncanonical":
        raw = b" " + raw
    with pytest.raises(NativeFixedLiveSinkError, match="comparison_refused"):
        request.compare(raw, image_device=19, image_inode=77, target_pid=123,
                        manifest_sha256=payload["manifest_sha256"])


@pytest.mark.parametrize("field,value", [("source_profile", "fixed-live-modules-v1"),
                                         ("image", b"not-the-image"), ("runtime_main_source", b"pass\n"),
                                         ("expected_installation_sha256", "b" * 64)])
def test_request_cannot_select_unpinned_image_source_or_profile(field, value):
    request, _payload = _request_vector()
    with pytest.raises(NativeFixedLiveSinkError, match="request_invalid"):
        replace(request, **{field: value}).validate(target_sha256=_sha(_image()))


def test_collector_only_profile_cannot_upgrade_to_sink_request():
    installed, main, _startup, _payload = _comparison_vector()
    request = FixedPythonLiveSinkRequest(installed, _image(), main, installed.installation_sha256)
    with pytest.raises(NativeFixedLiveSinkError, match="request_invalid"):
        request.validate(target_sha256=_sha(_image()))


@pytest.mark.parametrize("raw", [b"private\n", b"x" * (128 * 1024)])
def test_reader_drains_before_terminal_and_requires_eof(raw):
    read_fd, write_fd = os.pipe()
    capture = NativeFixedLiveSinkCapture(read_fd, deadline=time.monotonic() + 2).start()
    writer = _writer(write_fd, raw)
    try:
        assert capture.finish() == raw
    finally:
        capture.cancel()
        writer.join(timeout=2)
    assert not writer.is_alive()
    with pytest.raises(OSError):
        os.fstat(read_fd)


@pytest.mark.parametrize("fault", ["empty", "oversize", "no-eof"])
def test_reader_never_returns_empty_overflow_or_unterminated_data(fault):
    read_fd, write_fd = os.pipe()
    capture = NativeFixedLiveSinkCapture(read_fd, deadline=time.monotonic() + (0.05 if fault == "no-eof" else 2)).start()
    writer = None
    try:
        if fault == "oversize":
            raw = b"x" * (128 * 1024 + 1)
            writer = _writer(write_fd, raw)
            write_fd = -1
        elif fault == "no-eof":
            os.write(write_fd, b"partial")
        if fault == "empty":
            os.close(write_fd)
            write_fd = -1
        with pytest.raises(NativeFixedLiveSinkError):
            capture.finish()
    finally:
        if write_fd >= 0:
            os.close(write_fd)
        capture.cancel()
        if writer is not None:
            writer.join(timeout=2)
            assert not writer.is_alive()
    with pytest.raises(OSError):
        os.fstat(read_fd)


def test_reader_cancel_closes_fd_synchronously_without_a_helper_thread():
    read_fd, write_fd = os.pipe()
    try:
        capture = NativeFixedLiveSinkCapture(read_fd, deadline=time.monotonic() + 2).start()
        capture.cancel()
        assert not hasattr(capture, "_thread")
        with pytest.raises(OSError):
            os.fstat(read_fd)
        with pytest.raises(NativeFixedLiveSinkError, match="cancelled"):
            capture.finish()
    finally:
        os.close(write_fd)


def test_original_cancellation_is_observed_inside_the_reader():
    read_fd, write_fd = os.pipe()
    try:
        capture = NativeFixedLiveSinkCapture(read_fd, deadline=time.monotonic() + 2,
                                             cancelled=lambda: True).start()
        with pytest.raises(NativeFixedLiveSinkError, match="native_trusted_attempt_cancelled"):
            capture.finish()
        with pytest.raises(OSError):
            os.fstat(read_fd)
    finally:
        os.close(write_fd)


@pytest.mark.parametrize("callback", ["monotonic", "cancelled"])
def test_foreign_callback_errors_are_fixed_refusals_and_close_reader(callback):
    read_fd, write_fd = os.pipe()

    def broken():
        raise RuntimeError("foreign callback content")

    try:
        capture = NativeFixedLiveSinkCapture(
            read_fd, deadline=time.monotonic() + 2, **{callback: broken},
        ).start()
        with pytest.raises(NativeFixedLiveSinkError) as caught:
            capture.finish()
        assert "foreign" not in str(caught.value)
        with pytest.raises(OSError):
            os.fstat(read_fd)
    finally:
        os.close(write_fd)


def test_close_failure_cannot_become_success_on_second_finish(monkeypatch):
    import lunar_evolution.native_fixed_live_sink as sink_module

    read_fd, write_fd = os.pipe()
    capture = NativeFixedLiveSinkCapture(read_fd, deadline=time.monotonic() + 2).start()
    os.write(write_fd, b"private\n")
    os.close(write_fd)
    original = sink_module.os.close

    def failed_close(fd):
        original(fd)
        if fd == read_fd:
            raise OSError("simulated close failure")

    monkeypatch.setattr(sink_module.os, "close", failed_close)
    for _ in range(2):
        with pytest.raises(NativeFixedLiveSinkError, match="close_unknown"):
            capture.finish()


def test_v3_extension_leaves_legacy_v2_record_byte_exact(control_owner):
    read_fd, write_fd = os.pipe()
    try:
        info = os.fstat(write_fd)
        sink = NativeBootstrapPrivateSink(write_fd, info.st_dev, info.st_ino, 123456789)
        legacy = encode_native_bootstrap_control_v2(**control_owner)
        selected = encode_native_bootstrap_control_v3(**control_owner, private_sink=sink)
        assert selected[:8] == b"LNB1\x00\x03\x00\x00"
        assert selected[8:-28] == legacy[8:]
        assert selected[-28:] == (write_fd.to_bytes(4, "big") + info.st_dev.to_bytes(8, "big")
                                  + info.st_ino.to_bytes(8, "big") + (123456789).to_bytes(8, "big"))
        assert encode_native_bootstrap_control_v2(**control_owner) == legacy
    finally:
        os.close(read_fd)
        os.close(write_fd)


@pytest.mark.parametrize("fault", ["read-direction", "inode", "device", "deadline", "reserved", "fixed-slot", "grant"])
def test_v3_rejects_pipe_and_fd_binding_faults(control_owner, fault):
    read_fd, write_fd = os.pipe()
    try:
        info = os.fstat(write_fd)
        sink = NativeBootstrapPrivateSink(write_fd, info.st_dev, info.st_ino, 123456789)
        if fault == "read-direction":
            sink = replace(sink, fd=read_fd)
        elif fault in {"inode", "device"}:
            sink = replace(sink, **{fault: getattr(sink, fault) + 1})
        elif fault == "deadline":
            sink = replace(sink, deadline_monotonic_ns=0)
        elif fault == "grant":
            sink = replace(sink, fd=control_owner["held_grants"].pass_fds[0])
        else:
            control_owner["reserved_fds"] = (write_fd if fault == "reserved" else FIXED_LIVE_MODULES_SINK_FD,)
        with pytest.raises(NativeBootstrapError):
            encode_native_bootstrap_control_v3(**control_owner, private_sink=sink)
    finally:
        os.close(read_fd)
        os.close(write_fd)


def test_new_launcher_asset_is_separately_pinned_and_old_asset_is_unchanged():
    from pathlib import Path

    source = prepare_fixed_live_sink_launcher()
    assert len(source) == live.FIXED_LIVE_SINK_LAUNCHER_SOURCE_BYTES
    assert _sha(source) == live.FIXED_LIVE_SINK_LAUNCHER_SOURCE_SHA256
    legacy = Path(__file__).parents[1] / "tools/static_python_rsi_fixture/assets/launcher.c"
    assert len(legacy.read_bytes()) == 1740
    assert _sha(legacy.read_bytes()) == "3a81211b2869727469c1de3bfad79144d11f17c99ccc100c3c48015c0398a0e0"
