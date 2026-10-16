"""Local pure/create-only/read-only evidence contracts; no producer can be launched."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest

from lunar_evolution import producer_bundle_lineage as lineage
from lunar_evolution import rsi_producer_staging_capsule as capsule
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.producer_bundle_lineage import (
    MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES,
    capture_lineage_snapshot_pin,
    lineage_directory,
    persist_lineage_bytes_snapshot,
)
from lunar_evolution.rsi_learning import RSILearningError


@pytest.fixture(autouse=True)
def _forbid_launch(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("ready evidence must never launch a producer")
    monkeypatch.setattr(subprocess, "Popen", forbidden)


def _ready(workspace: Path, journal_id: str = "batch-1") -> dict:
    info = workspace.stat()
    return {
        "binding": {"fixture": "full independently retained binding"},
        "producer_checkpoint": {"fixture": "original child proof"},
        "plan": {"journal_id": journal_id},
        "inputs": {"workspace": str(workspace), "journal_id": journal_id},
        "input_manifest": {"journal_id": journal_id,
                           "workspace_identity": {"device": info.st_dev, "inode": info.st_ino}},
    }


def _batch(workspace: Path, journal_id: str = "batch-1") -> None:
    (workspace / "evolution" / "producer-batches" / journal_id).mkdir(parents=True)


def _persist(workspace: Path, journal_id: str = "batch-1") -> tuple[dict, dict, Path]:
    _batch(workspace, journal_id)
    ready = _ready(workspace, journal_id)
    ref = capsule.persist_ready_capsule(workspace, journal_id, ready)
    return ready, ref, lineage_directory(workspace, journal_id) / capsule.READY_CAPSULE_FILENAME


def _forbid_io(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("invalid or ordinary ready value performed capsule I/O")
    monkeypatch.setattr(capsule, "DirectoryChain", forbidden)
    monkeypatch.setattr(capsule, "_observe_file", forbidden)
    monkeypatch.setattr(capsule, "persist_lineage_bytes_snapshot", forbidden)


def test_ready_capsule_round_trip_is_original_and_read_only(tmp_path: Path) -> None:
    ready, ref, path = _persist(tmp_path)
    assert set(ref) == {"protocol", "workspace", "journal_id", "workspace_identity", "file_pin"}
    assert ref["protocol"] == capsule.READY_CAPSULE_PROTOCOL
    assert ref["file_pin"]["name"] == capsule.READY_CAPSULE_FILENAME
    assert ref["file_pin"]["size"] == len(canonical_json(ready))
    before = {name: (file.stat(), file.read_bytes()) for name, file in
              ((str(item), item) for item in tmp_path.rglob("*") if item.is_file())}
    expanded = capsule.materialize_ready(ref, allow_capsule=True,
                                         expected_workspace=tmp_path, expected_journal_id="batch-1")
    assert expanded == ready
    assert expanded is not ready
    assert path.read_bytes() == canonical_json(ready)
    after = {name: (file.stat(), file.read_bytes()) for name, file in
             ((str(item), item) for item in tmp_path.rglob("*") if item.is_file())}
    # Reads can update atime; all independently pinned metadata and all bytes are unchanged.
    assert set(before) == set(after)
    for name, (old, raw) in before.items():
        new, current = after[name]
        assert (old.st_dev, old.st_ino, old.st_size, old.st_mtime_ns, old.st_ctime_ns) == (
            new.st_dev, new.st_ino, new.st_size, new.st_mtime_ns, new.st_ctime_ns)
        assert raw == current


def test_equal_existing_capsule_is_never_adopted(tmp_path: Path) -> None:
    ready, ref, path = _persist(tmp_path)
    with pytest.raises(RSILearningError, match="persist_failed"):
        capsule.persist_ready_capsule(tmp_path, "batch-1", ready)
    assert path.read_bytes() == canonical_json(ready)
    assert capsule.materialize_ready(ref, allow_capsule=True) == ready


def test_existing_orphan_cannot_be_adopted_without_reference(tmp_path: Path) -> None:
    _batch(tmp_path)
    ready = _ready(tmp_path)
    raw = canonical_json(ready)
    persist_lineage_bytes_snapshot(tmp_path, "batch-1", name="rsi-ready", raw=raw,
                                   expected_sha256=hashlib.sha256(raw).hexdigest())
    with pytest.raises(RSILearningError, match="persist_failed"):
        capsule.persist_ready_capsule(tmp_path, "batch-1", ready)


class _Callback:
    def __str__(self) -> str:
        raise AssertionError("scalar string callback ran")

    def __fspath__(self) -> str:
        pytest.fail("path callback ran")

    def __eq__(self, other: object) -> bool:
        pytest.fail("scalar comparison callback ran")


class _DictCallback(dict):
    def items(self):
        pytest.fail("mapping callback ran")


@pytest.mark.parametrize("bad", [_Callback(), _DictCallback(), (_Callback(),), float("nan")])
def test_callback_tree_refused_before_serialization_and_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad: object,
) -> None:
    ready = _ready(tmp_path)
    ready["binding"]["bad"] = bad
    _forbid_io(monkeypatch)
    with pytest.raises(RSILearningError, match="shape_invalid"):
        capsule.persist_ready_capsule(tmp_path, "batch-1", ready)
    with pytest.raises(RSILearningError, match="shape_invalid"):
        capsule.materialize_ready(ready, allow_capsule=True)


@pytest.mark.parametrize("field,bad", [
    ("protocol", "other"), ("workspace", "relative"), ("workspace", "/tmp/../tmp"),
    ("journal_id", "../other"), ("workspace_identity", {"device": 1, "inode": True}),
    ("file_pin", {"name": "rsi-ready.snapshot"}),
])
def test_reference_schema_refused_before_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, bad: object,
) -> None:
    _, ref, _ = _persist(tmp_path)
    ref[field] = bad
    _forbid_io(monkeypatch)
    with pytest.raises(RSILearningError):
        capsule.materialize_ready(ref, allow_capsule=True)


@pytest.mark.parametrize("field,bad", [
    ("name", "other.snapshot"), ("size", 0), ("size", capsule.MAX_READY_CAPSULE_BYTES + 1),
    ("inode", 0), ("mode", 0o400), ("nlink", 2), ("mtime_ns", True),
])
def test_original_pin_schema_refused_before_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str, bad: object,
) -> None:
    _, ref, _ = _persist(tmp_path)
    ref["file_pin"][field] = bad
    _forbid_io(monkeypatch)
    with pytest.raises(RSILearningError, match="file_pin_invalid"):
        capsule.materialize_ready(ref, allow_capsule=True)


@pytest.mark.parametrize("kwargs", [
    {}, {"allow_capsule": 1}, {"allow_capsule": _Callback()},
    {"allow_capsule": True, "expected_workspace": "/foreign"},
    {"allow_capsule": True, "expected_workspace": _Callback()},
    {"allow_capsule": True, "expected_journal_id": "foreign"},
    {"allow_capsule": True, "expected_journal_id": _Callback()},
])
def test_mode_and_expected_association_refused_before_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kwargs: dict,
) -> None:
    _, ref, _ = _persist(tmp_path)
    _forbid_io(monkeypatch)
    with pytest.raises(RSILearningError):
        capsule.materialize_ready(ref, **kwargs)


def test_legacy_full_ready_has_no_capsule_io(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ready = _ready(tmp_path)
    _forbid_io(monkeypatch)
    assert capsule.materialize_ready(ready) is ready
    assert capsule.materialize_ready(ready, allow_capsule=True) is ready
    assert capsule.retained_ready_capsule_bytes({"producer_episode_staging": {"one": {"ready": ready}}}) == 0


@pytest.mark.parametrize("bound", ["binding", "ready", "aggregate", "retained_callback"])
def test_writer_bounds_are_pure_pre_io(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bound: str,
) -> None:
    ready = _ready(tmp_path)
    retained: object = 0
    if bound == "binding":
        ready["binding"]["payload"] = "a" * capsule.MAX_READY_BINDING_BYTES
    elif bound == "ready":
        ready["inputs"]["payload"] = "a" * capsule.MAX_READY_CAPSULE_BYTES
    elif bound == "aggregate":
        retained = MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES
    else:
        retained = _Callback()
    _forbid_io(monkeypatch)
    with pytest.raises(RSILearningError):
        capsule.persist_ready_capsule(tmp_path, "batch-1", ready, retained_bytes=retained)


@pytest.mark.parametrize("field", ["inputs", "plan", "input_manifest", "workspace_identity"])
def test_writer_original_association_refuses_before_snapshot_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str,
) -> None:
    ready = _ready(tmp_path)
    if field == "workspace_identity":
        ready["input_manifest"]["workspace_identity"] = {"device": 0, "inode": 1}
    else:
        ready[field]["journal_id"] = "foreign"
    if field == "workspace_identity":
        # Identity is compared to the original held workspace before any snapshot creation.
        monkeypatch.setattr(capsule, "persist_lineage_bytes_snapshot", lambda *args, **kwargs: pytest.fail("write"))
    else:
        _forbid_io(monkeypatch)
    with pytest.raises(RSILearningError, match="association_invalid|workspace_identity_drift"):
        capsule.persist_ready_capsule(tmp_path, "batch-1", ready)


@pytest.mark.parametrize("mutation", ["bytes", "touch", "replace", "hardlink", "symlink", "missing", "mode"])
def test_original_file_pin_drift_refuses_without_writes(tmp_path: Path, mutation: str) -> None:
    _, ref, path = _persist(tmp_path)
    raw = path.read_bytes()
    if mutation == "bytes":
        path.write_bytes(raw[:-1] + b" ")
    elif mutation == "touch":
        info = path.stat()
        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000))
    elif mutation == "replace":
        replacement = path.with_name("replacement")
        replacement.write_bytes(raw)
        replacement.chmod(0o600)
        os.replace(replacement, path)
    elif mutation == "hardlink":
        os.link(path, path.with_name("hardlink"))
    elif mutation == "symlink":
        original = path.with_name("original")
        path.rename(original)
        path.symlink_to(original)
    elif mutation == "missing":
        path.unlink()
    else:
        path.chmod(0o400)
    with pytest.raises(RSILearningError, match="read_failed"):
        capsule.materialize_ready(ref, allow_capsule=True)


def test_equal_bytes_parent_directory_replacement_refuses(tmp_path: Path) -> None:
    _, ref, path = _persist(tmp_path)
    parent = path.parent
    old = parent.with_name("lineage-original")
    parent.rename(old)
    parent.mkdir()
    replacement = parent / path.name
    replacement.write_bytes((old / path.name).read_bytes())
    replacement.chmod(0o600)
    with pytest.raises(RSILearningError, match="read_failed"):
        capsule.materialize_ready(ref, allow_capsule=True)


def test_workspace_replacement_refuses_original_identity(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _, ref, _ = _persist(workspace)
    workspace.rename(tmp_path / "original-workspace")
    workspace.mkdir()
    with pytest.raises(RSILearningError, match="workspace_identity_drift"):
        capsule.materialize_ready(ref, allow_capsule=True)


def test_post_parse_original_pin_is_rechecked(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, ref, path = _persist(tmp_path)
    original = capsule.strict_json
    def mutate(raw: bytes, *, maximum: int):
        value = original(raw, maximum=maximum)
        info = path.stat()
        os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000))
        return value
    monkeypatch.setattr(capsule, "strict_json", mutate)
    with pytest.raises(RSILearningError, match="read_failed"):
        capsule.materialize_ready(ref, allow_capsule=True)


def test_drift_during_held_read_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, ref, path = _persist(tmp_path)
    original_read = lineage.os.read
    mutated = False
    def mutate(descriptor: int, maximum: int) -> bytes:
        nonlocal mutated
        raw = original_read(descriptor, maximum)
        if not mutated:
            mutated = True
            info = path.stat()
            os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1_000_000))
        return raw
    monkeypatch.setattr(lineage.os, "read", mutate)
    with pytest.raises(RSILearningError, match="read_failed"):
        capsule.materialize_ready(ref, allow_capsule=True)
    assert mutated


def test_directory_drift_during_parse_refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _, ref, path = _persist(tmp_path)
    original = capsule.strict_json
    def mutate(raw: bytes, *, maximum: int):
        value = original(raw, maximum=maximum)
        parent = path.parent
        moved = parent.with_name("original-lineage")
        parent.rename(moved)
        parent.mkdir()
        replacement = parent / path.name
        replacement.write_bytes((moved / path.name).read_bytes())
        replacement.chmod(0o600)
        return value
    monkeypatch.setattr(capsule, "strict_json", mutate)
    with pytest.raises(RSILearningError, match="read_failed"):
        capsule.materialize_ready(ref, allow_capsule=True)


@pytest.mark.parametrize("invalid", ["whitespace", "association", "manifest_identity", "binding_bound"])
def test_pinned_invalid_full_payload_still_refuses(tmp_path: Path, invalid: str) -> None:
    ready, ref, path = _persist(tmp_path)
    if invalid == "association":
        ready["inputs"]["workspace"] = "/foreign"
    elif invalid == "manifest_identity":
        ready["input_manifest"]["workspace_identity"]["inode"] += 1
    elif invalid == "binding_bound":
        ready["binding"]["payload"] = "a" * capsule.MAX_READY_BINDING_BYTES
    raw = json.dumps(ready).encode() if invalid == "whitespace" else canonical_json(ready)
    path.write_bytes(raw)
    # This is a malformed independently supplied reference, never a reader refreshing authority.
    ref["file_pin"] = capture_lineage_snapshot_pin(path, name=path.name).to_dict()
    with pytest.raises(RSILearningError, match="canonical_invalid|association_invalid|binding_too_large"):
        capsule.materialize_ready(ref, allow_capsule=True)


def test_failed_post_create_observation_leaves_orphan_and_never_adopts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _batch(tmp_path)
    ready = _ready(tmp_path)
    original = capsule._observe_file
    def fail(*args: object, **kwargs: object):
        raise OSError("simulated failure after owned creation")
    monkeypatch.setattr(capsule, "_observe_file", fail)
    with pytest.raises(RSILearningError, match="persist_failed"):
        capsule.persist_ready_capsule(tmp_path, "batch-1", ready)
    path = lineage_directory(tmp_path, "batch-1") / capsule.READY_CAPSULE_FILENAME
    assert path.is_file()
    monkeypatch.setattr(capsule, "_observe_file", original)
    with pytest.raises(RSILearningError, match="persist_failed"):
        capsule.persist_ready_capsule(tmp_path, "batch-1", ready)


def test_retained_accounting_is_pure_and_requires_original_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    ready, ref, _ = _persist(tmp_path)
    _, second, _ = _persist(tmp_path, "batch-2")
    entries = {"one": {"ready": ref}, "two": {"ready": second},
               "preparing": {"ready": None}, "legacy": {"ready": ready}}
    _forbid_io(monkeypatch)
    state = {"producer_multi_episode_publication": True, "producer_episode_staging": entries}
    assert capsule.retained_ready_capsule_bytes(state) == ref["file_pin"]["size"] + second["file_pin"]["size"]
    for flag in (False, None, 1, "true"):
        state["producer_multi_episode_publication"] = flag
        with pytest.raises(RSILearningError, match="mode_required"):
            capsule.retained_ready_capsule_bytes(state)


def test_retained_accounting_rejects_malformed_or_oversized_original_pin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, ref, _ = _persist(tmp_path)
    _forbid_io(monkeypatch)
    ref["file_pin"]["size"] = capsule.MAX_READY_CAPSULE_BYTES + 1
    state = {"producer_multi_episode_publication": True, "producer_episode_staging": {"one": {"ready": ref}}}
    with pytest.raises(RSILearningError, match="file_pin_invalid"):
        capsule.retained_ready_capsule_bytes(state)
    ref["file_pin"]["size"] = capsule.MAX_READY_CAPSULE_BYTES
    state["producer_episode_staging"] = {str(i): {"ready": copy.deepcopy(ref)} for i in range(1025)}
    with pytest.raises(RSILearningError, match="aggregate_exhausted"):
        capsule.retained_ready_capsule_bytes(state)


def test_shared_evidence_accounting_is_pure_and_bounded_before_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, ref, _ = _persist(tmp_path)
    pin = copy.deepcopy(ref["file_pin"])
    pin["name"] = "archive-before.snapshot"
    pin["size"] = 16 * 1024 * 1024
    snapshots = {}
    for name in ("archive-before", "state-before", "archive-after", "state-after"):
        snapshots[name] = {**pin, "name": name + ".snapshot"}
    state = {"producer_multi_episode_publication": True,
             "producer_publication_lineage": {"batches": [{"snapshots": snapshots}]}}
    _forbid_io(monkeypatch)
    assert capsule.retained_publication_evidence_bytes(state) == MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES
    state["producer_episode_staging"] = {"one": {"ready": ref}}
    with pytest.raises(RSILearningError, match="aggregate_exhausted"):
        capsule.retained_publication_evidence_bytes(state)
    snapshots["archive-before"]["size"] -= ref["file_pin"]["size"]
    assert capsule.retained_publication_evidence_bytes(state) == MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES


@pytest.mark.parametrize("mutation", ["flag", "callback", "batches", "pin_name", "pin_size"])
def test_shared_evidence_shape_gates_are_pure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mutation: str,
) -> None:
    _, ref, _ = _persist(tmp_path)
    pin = {**ref["file_pin"], "name": "archive-before.snapshot"}
    state = {"producer_multi_episode_publication": True,
             "producer_publication_lineage": {"batches": [{"snapshots": {"archive-before": pin}}]}}
    if mutation == "flag":
        state["producer_multi_episode_publication"] = 1
    elif mutation == "callback":
        state["producer_publication_lineage"]["batches"][0]["snapshots"] = _DictCallback()
    elif mutation == "batches":
        state["producer_publication_lineage"]["batches"] = [{}] * 9
    elif mutation == "pin_name":
        pin["name"] = "foreign.snapshot"
    else:
        pin["size"] = 16 * 1024 * 1024 + 1
    _forbid_io(monkeypatch)
    with pytest.raises(RSILearningError):
        capsule.retained_publication_evidence_bytes(state)
