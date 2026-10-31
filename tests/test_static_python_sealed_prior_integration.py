"""Original readback integration; process and OCI controls remain inert doubles."""

from __future__ import annotations

import os
import sys

import pytest

from tests import test_static_python_rsi_vfs_lifetime as lifecycle
from tests import test_static_python_worker_boundaries as boundaries
from tests.test_static_python_podman_helper_inputs import _elf, _write
from tests.test_static_python_source_data_backend import (
    inert_v2_tool as inert_v2_tool,  # noqa: PLC0414
)
from tests.test_static_python_source_data_backend import (
    v2_fixture as v2_fixture,  # noqa: PLC0414
)
from tests.test_static_python_source_data_vfs_retained_backend import options
from tools.static_python_rsi_fixture import execution_backend as execution
from tools.static_python_rsi_fixture import podman_custody as custody
from tools.static_python_rsi_fixture import podman_vfs_lifetime as lifetime
from tools.static_python_rsi_fixture import podman_vfs_snapshots as retained
from tools.static_python_rsi_fixture.execution_backend import BuildExecutionError
from tools.static_python_rsi_fixture.podman_sealed_prior import _SealedPriorBank

worker_owner_vector = boundaries.worker_owner_vector
original_vector = lifecycle.original_vector
retained_vector = lifecycle.retained_vector
service_root_double = lifecycle.service_root_double
LINUX = pytest.mark.skipif(sys.platform != "linux", reason="requires actual Linux memfd seals")


@LINUX
def test_original_lifetime_captures_from_held_output_before_successor_staging(worker_owner_vector, tmp_path):
    vector = worker_owner_vector
    owner, records = boundaries.advance_to_readback(vector)
    bank = _SealedPriorBank(vector.checkpoint)
    batch = bank.begin(records)
    try:
        owner.finish_readback(records, {**vector.binding, "vfs_snapshots": vector.vfs_pin},
                              _sealed_batch=batch)
        with pytest.raises(ValueError):
            bank.read_record(records[0])
        owner.close()
        batch.commit()
        (vector.root / "out/objects/result.o").write_bytes(b"late changed output")
        destination = tmp_path / "successor-prior"
        bank.snapshot(destination, records)
        assert (destination / "objects/result.o").read_bytes() == b"obj"
        assert vector.capture.completed and owner.closed
    finally:
        batch.abort()
        owner.close()
        bank.close()


@LINUX
@pytest.mark.parametrize("moment", ["capture-complete", "after-readback"])
def test_late_original_readback_failure_cannot_publish_pending_bytes(
        worker_owner_vector, monkeypatch, tmp_path, moment):
    vector = worker_owner_vector
    owner, records = boundaries.advance_to_readback(vector)
    bank = _SealedPriorBank(vector.checkpoint)
    batch = bank.begin(records)
    error = RuntimeError("original late readback refusal")
    if moment == "capture-complete":
        monkeypatch.setattr(vector.capture, "complete", lambda _binding: (_ for _ in ()).throw(error))
    else:
        phase = owner._phase

        def refuse(name, links):
            if name == "after-readback":
                raise error
            return phase(name, links)

        monkeypatch.setattr(owner, "_phase", refuse)
    try:
        with pytest.raises(RuntimeError) as caught:
            owner.finish_readback(records, {**vector.binding, "vfs_snapshots": vector.vfs_pin},
                                  _sealed_batch=batch)
        assert caught.value is error
        batch.abort(error)
        with pytest.raises(ValueError):
            bank.snapshot(tmp_path / "unpublished", records)
        assert not (tmp_path / "unpublished").exists()
    finally:
        batch.abort()
        owner.close()
        bank.close()


@LINUX
def test_original_image_preparation_takes_prior_bytes_from_same_bank(tmp_path):
    destination = tmp_path / "attempt"
    destination.mkdir()
    subject = custody.PodmanCustody(
        destination=destination, prefix=["never-executed"], recipe_sha256="a" * 64,
        checkpoint=lambda: None, snapshot_mounts=True, source_data=True,
        vfs_roots=True, vfs_retained=True, vfs_lifetime=True, vfs_worker_input_view=True,
    )
    raw = b"original output from preceding command"
    record = {"path": "objects/unit.o", "size": len(raw), "sha256": retained._sha(raw), "executable": False}
    source = tmp_path / "original-output"
    source.write_bytes(raw)
    batch = subject._sealed_prior.begin([record])
    descriptor = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        batch.capture(descriptor, record)
        batch.commit()
    finally:
        os.close(descriptor)
        batch.abort()
    roots = {role: tmp_path / role for role in ("source", "toolchain")}
    for root in roots.values():
        root.mkdir()
    work = tmp_path / "work"
    (work / "objects").mkdir(parents=True)
    (work / record["path"]).write_bytes(b"mutated work mirror")
    archive = tmp_path / "base-image.tar"
    archive.write_bytes(b"inert reused image archive")
    pin = custody._observe(archive.parent, archive.name, 1024)
    subject.base_image = ("b" * 64, archive, pin)
    command_root = subject.root / "compile-1"
    command_root.mkdir()
    try:
        image, readonly = subject._prepare_image(
            root=command_root, inputs={"source": [], "toolchain": []}, snapshots=roots,
            prior=[record], work=work, observation={}, operations=[],
        )
        assert image == "b" * 64
        assert (readonly["work"] / record["path"]).read_bytes() == raw
        assert (work / record["path"]).read_bytes() == b"mutated work mirror"
    finally:
        subject.close()


@pytest.mark.parametrize("failure", [None, "after-readback", "close"])
@pytest.mark.parametrize("abort_failure", [False, True])
def test_original_custody_commits_only_after_successful_lifetime_release(
        retained_vector, monkeypatch, failure, abort_failure):
    run, evidence, _work, events, _owners = lifecycle.original_runner(
        retained_vector, monkeypatch, failure=failure)
    subject = retained_vector[0][0][0]
    subject.vfs_worker_input_view = True
    select_capture = subject.snapshot_store._lifetime
    monkeypatch.setattr(subject.snapshot_store, "_lifetime",
                        lambda stage, index, **_options: select_capture(stage, index))
    original_owner = lifetime._VfsExecutionLifetime

    class Owner(original_owner):
        def _bind_worker_inputs(self, *_args, **_options):
            pass

        def _bind_worker_filesystem(self, *_args, **_options):
            pass

        def finish_readback(self, outputs, binding, *, _sealed_batch):
            assert _sealed_batch is batch
            events.append("pending-original-output-group")
            return super().finish_readback(outputs, binding)

    class Batch:
        def commit(self):
            assert "lifetime-close" in events and "service-close" in events
            events.append("sealed-prior-commit")

        def abort(self):
            events.append("sealed-prior-abort")
            if abort_failure:
                raise ValueError("original pending frame release unknown")

    batch = Batch()

    class Bank:
        def begin(self, outputs):
            assert outputs == evidence["custody"]["readback_outputs"]
            events.append("sealed-prior-begin")
            return batch

    subject._sealed_prior = Bank()
    monkeypatch.setattr(lifetime, "_VfsExecutionLifetime", Owner)
    if failure is None:
        run()
        assert events[-1] == "sealed-prior-commit"
        assert "sealed-prior-abort" not in events and evidence["status"] == "complete"
    else:
        with pytest.raises((BuildExecutionError, ValueError)):
            run()
        assert events[-1] == "sealed-prior-abort"
        assert "sealed-prior-commit" not in events and evidence["status"] == "partial"
        assert evidence["custody"].get("sealed_prior_close_unknown", False) is abort_failure


@pytest.mark.parametrize("failure", ["business", "io", "interrupt", "system-exit"])
@pytest.mark.parametrize("close_failure", [None, "value", "interrupt", "system-exit"])
def test_attempt_always_releases_bank_and_preserves_original_failure(
        v2_fixture, monkeypatch, failure, close_failure):
    prep, wire, kwargs = options(v2_fixture, monkeypatch)
    contents = {"configure": b"#!/not-an-executor\n", "unit.c": b"unit",
                "zig": _elf(), "lib/crt.o": b"crt"}
    for role in ("source", "toolchain"):
        for record in wire["inputs"][role]:
            _write(kwargs[role + "_root"], record["path"], contents[record["path"]],
                   executable=record["executable"])
    monkeypatch.setattr(custody, "preflight_podman_custody", lambda: ["never-executed"])
    error = {"business": BuildExecutionError("original_command_refusal"),
             "io": OSError("original fixture I/O failure"),
             "interrupt": KeyboardInterrupt(), "system-exit": SystemExit(73)}[failure]
    calls = []

    class OriginalCustody:
        def __init__(self, **_selected):
            calls.append("acquire")

        def run(self, *_args, **_selected):
            calls.append("run")
            raise error

        def close(self):
            calls.append("close")
            if close_failure == "value":
                raise ValueError("original bank release unknown")
            if close_failure == "interrupt":
                raise KeyboardInterrupt()
            if close_failure == "system-exit":
                raise SystemExit(91)

    monkeypatch.setattr(custody, "PodmanCustody", OriginalCustody)
    expected = SystemExit if failure == "system-exit" else BuildExecutionError
    with pytest.raises(expected) as caught:
        execution.run_pinned_build_v4_vfs_worker_input_view(prep, **kwargs)
    assert calls == ["acquire", "run", "close"]
    if failure == "system-exit":
        assert caught.value is error
        assert ("podman_sealed_prior_close_unknown" in getattr(error, "__notes__", ())) is (close_failure is not None)
    else:
        reason = {"business": "original_command_refusal", "io": "attempt_io_failure",
                  "interrupt": "interrupted"}[failure]
        assert caught.value.report.reason == reason and caught.value.report.status == "partial"
