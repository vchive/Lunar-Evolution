"""Local file/FD fixtures only; no producer, scheduler or controller is executed."""

from __future__ import annotations

import itertools
import json
import os
import stat
from dataclasses import replace

import pytest
from test_rsi_native_provenance import payload as success_payload
from test_rsi_native_rejection import (
    CALLBACK_MUTATIONS,
    digest,
    polluted_evidence,
    rejection_evidence,
)

import lunar_evolution.rsi_native_failure as failure
import lunar_evolution.rsi_native_provenance as success
import lunar_evolution.rsi_native_rejection as rejection
from lunar_evolution.rsi_native_rejection import (
    NATIVE_RSI_REJECTION_PROVENANCE_NAME,
    NativeRSIRejectionError,
    NativeRSIRejectionFilePin,
    map_native_rejection_to_solver_result,
    persist_native_rsi_rejection_provenance,
    read_native_rsi_rejection_provenance,
)


def _image(directory):
    return {p.name: (p.read_bytes(), rejection._metadata(p.stat())) for p in directory.iterdir() if p.is_file()}


def _persist(directory):
    evidence = rejection_evidence()
    digest_, pin = persist_native_rsi_rejection_provenance(directory, evidence, retained_bytes=0)
    return evidence, digest_, pin


def test_original_fd_pin_readback_mapping_and_no_fresh_adoption(tmp_path):
    evidence, digest_, pin = _persist(tmp_path)
    path = tmp_path / NATIVE_RSI_REJECTION_PROVENANCE_NAME
    original = _image(tmp_path)
    info = path.stat()
    assert pin.inode == info.st_ino and pin.device == info.st_dev
    assert pin.mode == 0o400 and stat.S_IMODE(info.st_mode) == 0o400 and pin.nlink == 1
    assert pin.parent_inode == tmp_path.stat().st_ino
    restored = read_native_rsi_rejection_provenance(tmp_path, expected_file_pin=pin)
    assert restored.provenance_sha256 == digest_ and restored.provenance_file_pin == pin
    assert restored.to_dict() == evidence.to_dict()
    result = map_native_rejection_to_solver_result(evidence.plan.request, evidence.plan, restored)
    assert result.status == "failed" and result.terminal_reason == "native_all_rejected"
    assert result.solver_score is None and result.candidate_receipt_sha256 is None
    assert result.execution_receipt_sha256 is None and result.official_evaluation_receipt_sha256 is None
    assert result.trace_digest == evidence.producer_output_sha256
    assert "candidate_id" not in dict(result.solver_provenance)
    assert "candidate_source_sha256" not in dict(result.solver_provenance)
    with pytest.raises(NativeRSIRejectionError, match="already_exists"):
        persist_native_rsi_rejection_provenance(tmp_path, evidence, retained_bytes=0)
    with pytest.raises(NativeRSIRejectionError, match="fresh_evidence_required"):
        persist_native_rsi_rejection_provenance(tmp_path, restored, retained_bytes=0)
    assert _image(tmp_path) == original


@pytest.mark.parametrize("mutation", ["replacement", "mtime", "mode", "hardlink", "symlink", "parent-pin"])
def test_independent_expected_pin_never_refreshes_on_drift(tmp_path, mutation):
    _, _, pin = _persist(tmp_path)
    path = tmp_path / NATIVE_RSI_REJECTION_PROVENANCE_NAME
    if mutation == "replacement":
        raw = path.read_bytes()
        path.rename(tmp_path / "original-retained")
        path.write_bytes(raw)
        path.chmod(0o400)
    elif mutation == "mtime":
        info = path.stat()
        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1))
    elif mutation == "mode":
        path.chmod(0o600)
    elif mutation == "hardlink":
        os.link(path, tmp_path / "alias")
    elif mutation == "symlink":
        path.rename(tmp_path / "original-retained")
        path.symlink_to(tmp_path / "original-retained")
    else:
        pin = replace(pin, parent_inode=pin.parent_inode + 1)
    before = _image(tmp_path)
    with pytest.raises(NativeRSIRejectionError):
        read_native_rsi_rejection_provenance(tmp_path, expected_file_pin=pin)
    assert _image(tmp_path) == before


@pytest.mark.parametrize("field,value", [("name", "another"), ("mode", 0o600), ("inode", 0),
                                          ("device", True), ("nlink", 2), ("size", 0), ("sha256", "bad")])
def test_exact_pin_fields_and_missing_expected_pin_refuse(tmp_path, field, value):
    _, _, pin = _persist(tmp_path)
    with pytest.raises(NativeRSIRejectionError):
        replace(pin, **{field: value})
    with pytest.raises(TypeError):
        read_native_rsi_rejection_provenance(tmp_path)
    with pytest.raises(NativeRSIRejectionError):
        read_native_rsi_rejection_provenance(tmp_path, expected_file_pin=None)
    wire = pin.to_dict()
    wire["authority"] = True
    with pytest.raises(NativeRSIRejectionError):
        NativeRSIRejectionFilePin.from_dict(wire)


def test_budget_projection_and_c1_accounting_refuse_before_directory_io(tmp_path, monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("budget refusal reached directory I/O")
    monkeypatch.setattr(rejection, "_directory", forbidden)
    evidence = rejection_evidence(retained_bytes=rejection.MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES)
    with pytest.raises(NativeRSIRejectionError, match="capacity_exceeded"):
        persist_native_rsi_rejection_provenance(tmp_path, evidence, retained_bytes=evidence.lineage.retained_bytes)
    with pytest.raises(NativeRSIRejectionError, match="retained_bytes_mismatch"):
        persist_native_rsi_rejection_provenance(tmp_path, rejection_evidence(), retained_bytes=1)
    with pytest.raises(NativeRSIRejectionError):
        persist_native_rsi_rejection_provenance(tmp_path, rejection_evidence(), retained_bytes=True)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("mutation", CALLBACK_MUTATIONS)
def test_writer_shape_refuses_nested_callbacks_before_capacity_or_directory_io(tmp_path, monkeypatch, mutation):
    callbacks = []
    evidence = polluted_evidence(mutation, callbacks)
    def forbidden_directory(*_args, **_kwargs):
        pytest.fail("shape refusal reached directory I/O")
    monkeypatch.setattr(rejection, "_directory", forbidden_directory)
    with pytest.raises(NativeRSIRejectionError, match="shape_invalid"):
        persist_native_rsi_rejection_provenance(tmp_path, evidence, retained_bytes=0)
    assert callbacks == [] and list(tmp_path.iterdir()) == []


def test_reader_checks_polluted_pin_before_serializer_or_directory_io(tmp_path, monkeypatch):
    _, _, pin = _persist(tmp_path)
    callbacks = []
    class CallbackDigest(str):
        def __str__(self):
            callbacks.append("str")
            raise AssertionError("untrusted callback ran")
    object.__setattr__(pin, "sha256", CallbackDigest(pin.sha256))
    def forbidden_directory(*_args, **_kwargs):
        pytest.fail("pin refusal reached directory I/O")
    monkeypatch.setattr(rejection, "_directory", forbidden_directory)
    with pytest.raises(NativeRSIRejectionError, match="shape_invalid"):
        read_native_rsi_rejection_provenance(tmp_path, expected_file_pin=pin)
    assert callbacks == []


def test_partial_write_is_retained_and_retry_never_adopts_it(tmp_path, monkeypatch):
    original_write = os.write
    calls = 0
    def partial(descriptor, raw):
        nonlocal calls
        calls += 1
        if calls == 1:
            return original_write(descriptor, raw[:2])
        raise OSError("inert write interruption")
    with monkeypatch.context() as patch:
        patch.setattr(rejection.os, "write", partial)
        with pytest.raises(NativeRSIRejectionError, match="write_failed"):
            _persist(tmp_path)
    path = tmp_path / NATIVE_RSI_REJECTION_PROVENANCE_NAME
    assert path.read_bytes() == b'{"'
    before = _image(tmp_path)
    with pytest.raises(NativeRSIRejectionError, match="already_exists"):
        _persist(tmp_path)
    assert _image(tmp_path) == before


def test_final_original_fd_named_compare_catches_replacement_after_last_read(tmp_path, monkeypatch):
    original_read = rejection._read
    calls = 0
    def read_then_replace(chain, pin):
        nonlocal calls
        evidence = original_read(chain, pin)
        calls += 1
        if calls == 2:
            path = tmp_path / NATIVE_RSI_REJECTION_PROVENANCE_NAME
            raw = path.read_bytes()
            path.rename(tmp_path / "original-publishing-fd-retained")
            path.write_bytes(raw)
            path.chmod(0o400)
        return evidence
    monkeypatch.setattr(rejection, "_read", read_then_replace)
    with pytest.raises(NativeRSIRejectionError, match="changed"):
        _persist(tmp_path)
    assert calls == 2
    assert (tmp_path / "original-publishing-fd-retained").exists()


def test_final_mode_is_checked_before_original_pin_capture(tmp_path, monkeypatch):
    original_fsync = os.fsync
    def fsync_and_mutate(descriptor):
        original_fsync(descriptor)
        if stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.fchmod(descriptor, 0o600)
    monkeypatch.setattr(rejection.os, "fsync", fsync_and_mutate)
    with pytest.raises(NativeRSIRejectionError, match="file_pin_invalid"):
        _persist(tmp_path)
    assert stat.S_IMODE((tmp_path / NATIVE_RSI_REJECTION_PROVENANCE_NAME).stat().st_mode) == 0o600


def test_provenance_identity_digest_must_match_raw_pin_even_in_pure_mapper(tmp_path):
    _, _, pin = _persist(tmp_path)
    restored = read_native_rsi_rejection_provenance(tmp_path, expected_file_pin=pin)
    with pytest.raises(NativeRSIRejectionError, match="provenance_pin_mismatch"):
        replace(restored, provenance_sha256=digest("invented"))
    with pytest.raises(NativeRSIRejectionError, match="provenance_pin_mismatch"):
        replace(restored, provenance_file_pin=replace(pin, sha256=digest("invented-raw")))


NAMES = (success.NATIVE_RSI_PROVENANCE_NAME, failure.NATIVE_RSI_FAILURE_PROVENANCE_NAME,
         NATIVE_RSI_REJECTION_PROVENANCE_NAME)


@pytest.mark.parametrize("own,other", list(itertools.permutations(NAMES, 2)))
@pytest.mark.parametrize("sibling", ["partial", "symlink"])
def test_all_six_ordered_sibling_conflicts_refuse_standalone_readers(tmp_path, own, other, sibling):
    if own == NAMES[2]:
        _, _, pin = _persist(tmp_path)
        reader = lambda: read_native_rsi_rejection_provenance(tmp_path, expected_file_pin=pin)
    elif own == NAMES[0]:
        success.persist_native_rsi_provenance(tmp_path, success_payload())
        reader = lambda: success.read_native_rsi_provenance(tmp_path)
    else:
        (tmp_path / own).write_bytes(b"partial")
        (tmp_path / own).chmod(0o400)
        reader = lambda: failure.read_native_rsi_failure_provenance(tmp_path)
    if sibling == "symlink":
        (tmp_path / other).symlink_to(tmp_path / "absent")
    else:
        (tmp_path / other).write_bytes(b"partial")
    with pytest.raises(ValueError, match="conflicting_provenance"):
        reader()


@pytest.mark.parametrize("own,other", [(NAMES[0], NAMES[1]), (NAMES[0], NAMES[2]),
                                       (NAMES[2], NAMES[0]), (NAMES[2], NAMES[1])])
def test_fresh_success_and_rejection_writers_refuse_each_sibling_before_create(tmp_path, own, other):
    (tmp_path / other).write_bytes(b"partial")
    with pytest.raises(ValueError, match="conflicting_provenance"):
        if own == NAMES[0]:
            success.persist_native_rsi_provenance(tmp_path, success_payload())
        else:
            _persist(tmp_path)
    assert not (tmp_path / own).exists()


def test_sibling_created_at_directory_fsync_refuses_original_pin_return(tmp_path, monkeypatch):
    original_fsync = os.fsync
    def fsync_then_conflict(descriptor):
        original_fsync(descriptor)
        if stat.S_ISDIR(os.fstat(descriptor).st_mode):
            (tmp_path / NAMES[1]).write_bytes(b"partial")
    monkeypatch.setattr(rejection.os, "fsync", fsync_then_conflict)
    with pytest.raises(NativeRSIRejectionError, match="conflicting_provenance"):
        _persist(tmp_path)
    assert (tmp_path / NAMES[2]).exists()


def test_no_follow_missing_directory_and_noncanonical_file_are_never_repaired(tmp_path):
    missing = tmp_path / "missing"
    with pytest.raises(NativeRSIRejectionError, match="path_invalid"):
        _persist(missing)
    assert not missing.exists()
    _, _, pin = _persist(tmp_path)
    path = tmp_path / NAMES[2]
    value = json.loads(path.read_bytes())
    path.chmod(0o600)
    raw = json.dumps(value, indent=2).encode()
    path.write_bytes(raw)
    path.chmod(0o400)
    # The test supplies a changed pin deliberately: strict canonical verification
    # remains independent of pin equality and cannot trust a matching file digest.
    new_pin = rejection._pin(raw, path.stat(), tmp_path.stat())
    before = _image(tmp_path)
    with pytest.raises(NativeRSIRejectionError, match="noncanonical"):
        read_native_rsi_rejection_provenance(tmp_path, expected_file_pin=new_pin)
    assert _image(tmp_path) == before and pin != new_pin
