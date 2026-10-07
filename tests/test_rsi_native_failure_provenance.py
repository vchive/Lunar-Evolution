"""Detached strict sidecar fixtures plus actual inert native provider failure recovery."""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import shutil
import sqlite3
import stat
import sys
import time
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from _native_target_fixture import compile_native_target
from test_native_trusted_scheduler_e2e import fixture as native_fixture

import lunar_evolution.rsi_native_failure as provenance
import lunar_evolution.rsi_native_scheduler as scheduler
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.producer_bootstrap import TrustedBootstrapSession
from lunar_evolution.producer_launcher import (
    build_producer_launch_attestation,
    build_producer_launch_intent,
)
from lunar_evolution.rsi_gateway import SolverRequest
from lunar_evolution.rsi_learning import EMPTY_MEMORY_SNAPSHOT
from lunar_evolution.rsi_native_failure import (
    NATIVE_RSI_FAILURE_PROVENANCE_NAME,
    NativeRSIFailureError,
    NativeRSIFailureEvidence,
    map_native_failure_to_solver_result,
    persist_native_rsi_failure_provenance,
    read_native_rsi_failure_provenance,
)
from lunar_evolution.rsi_native_inputs import bind_native_rsi_launch, prepare_native_rsi_inputs
from lunar_evolution.rsi_native_provenance import NATIVE_RSI_PROVENANCE_NAME
from lunar_evolution.rsi_native_scheduler import (
    NativeRSISchedulerContext,
    NativeRSISchedulerProviderError,
    make_native_rsi_scheduler_provider,
)
from lunar_evolution.rsi_store import RSILedger

pytestmark = pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native platform")


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _file_state(path):
    # Read-only evidence checks may update access time; bytes and authority metadata may not.
    raw = path.read_bytes()
    info = path.stat()
    return (raw, info.st_dev, info.st_ino, info.st_mode, info.st_nlink, info.st_size,
            info.st_mtime_ns, info.st_ctime_ns)


def _native_failure_rsi_fixture(
    tmp_path: Path, *, target_source: str | None = None, episode_id: str = "native-rsi-failure",
    budget: dict | None = None, cancelled=None, practice_charter=None,
):
    # No HTTP request is made: this static target exits seven without using the broker.
    native = native_fixture(tmp_path, "http://127.0.0.1:9/inert")
    authority = native.strategy.integrity_authority
    request = SolverRequest.build(
        episode_id=episode_id, solver_id="native_population",
        contract_sha256=authority.contract_sha256, evaluator_sha256=authority.evaluator_fingerprint,
        environment_sha256=authority.environment_sha256,
        memory_snapshot_sha256=EMPTY_MEMORY_SNAPSHOT.digest(),
        budget=({"max_solver_invocations": 1, "deadline_unix": time.time() + 120}
                if budget is None else dict(budget)),
        practice_charter=practice_charter,
    )
    workspace = native.context.workspace
    inputs = prepare_native_rsi_inputs(
        workspace, journal_id=native.intent.journal_id, request=request, memory=EMPTY_MEMORY_SNAPSHOT,
    )
    producer = native.arguments["producer_root"]
    source = producer / "target.c"
    source.write_text(target_source or "int main(void) { return 7; }\n")
    compile_native_target(source, producer / "target")
    original = native.intent.to_dict()
    parameters = inspect.signature(build_producer_launch_intent).parameters
    values = {name: original[name] for name in parameters if name not in {"producer_root", "argv"}}
    intent = build_producer_launch_intent(
        producer_root=producer, argv=(*native.intent.argv, *inputs.argv_fragment), **values,
    )
    attestation = build_producer_launch_attestation(intent, "native-rsi-failure-once")
    inputs = bind_native_rsi_launch(
        workspace, intent=intent, attestation=attestation, artifact=native.artifact, inputs=inputs,
    )
    ledger = RSILedger(tmp_path / "rsi.sqlite")
    context = NativeRSISchedulerContext(
        workspace=workspace, producer_root=producer, intent=intent, attestation=attestation,
        artifact=native.artifact, broker_config=native.arguments["broker_config"],
        contract=native.context.contract, groups=native.arguments["groups"],
        evaluator_kind=authority.evaluator_kind, evaluator_fingerprint=authority.evaluator_fingerprint,
        runner_fingerprint=authority.runner_fingerprint, dependency_sha256=authority.dependency_sha256,
        environment_sha256=authority.environment_sha256, strategy=native.strategy,
        failure_ledger=ledger, cancelled=cancelled,
    )
    provider = make_native_rsi_scheduler_provider(context)
    plan = provider.plan(request, EMPTY_MEMORY_SNAPSHOT)
    return SimpleNamespace(
        request=request, plan=plan, context=context, provider=provider, ledger=ledger,
        native=native, inputs=inputs, workspace=workspace, batch=native.batch,
    )


@pytest.fixture(scope="module")
def failure_seed(tmp_path_factory):
    prepared = _native_failure_rsi_fixture(tmp_path_factory.mktemp("native-failure-seed"))
    prepared.ledger.claim_native_episode(prepared.request, plan_sha256=prepared.plan.plan_sha256)
    prepared.evidence = prepared.provider(prepared.request, prepared.plan)
    assert isinstance(prepared.evidence, NativeRSIFailureEvidence)
    assert prepared.evidence.failure.status == "failed" and prepared.evidence.failure.exit_code == 7
    return prepared


def _unpublished(seed):
    return replace(seed.evidence, provenance_sha256=None)


def _write_record(path, value, *, raw=None):
    path.chmod(0o600)
    if raw is None:
        body = {key: item for key, item in value.items() if key != "provenance_sha256"}
        value["provenance_sha256"] = hashlib.sha256(canonical_json(body)).hexdigest()
        raw = canonical_json(value)
    path.write_bytes(raw)
    path.chmod(0o400)


def test_create_read_and_identical_replay_preserve_original_inode(tmp_path, failure_seed):
    evidence = _unpublished(failure_seed)
    before = deepcopy(evidence.to_dict())
    digest = persist_native_rsi_failure_provenance(tmp_path, evidence)
    path = tmp_path / NATIVE_RSI_FAILURE_PROVENANCE_NAME
    retained = _file_state(path)
    restored = read_native_rsi_failure_provenance(tmp_path)
    assert restored == replace(evidence, provenance_sha256=digest)
    assert evidence.to_dict() == before
    assert stat.S_IMODE(path.stat().st_mode) == 0o400 and path.stat().st_nlink == 1
    assert persist_native_rsi_failure_provenance(tmp_path, evidence) == digest
    assert persist_native_rsi_failure_provenance(tmp_path, restored) == digest
    assert _file_state(path) == retained
    with pytest.raises(TypeError):
        restored.ledger_identity["inode"] = 1
    wire = restored.to_dict()
    wire["claim"]["created_at"] = "caller mutation"
    assert read_native_rsi_failure_provenance(tmp_path) == restored


@pytest.mark.parametrize("mutation", [
    "unknown", "schema", "protocol", "plan", "input", "ledger-extra", "ledger-inode",
    "ledger-path", "claim-extra", "claim-status", "claim-created", "claim-digest", "claim-plan",
    "failure", "binding",
])
def test_exact_payload_rejects_invalid_or_crossbound_data(failure_seed, mutation):
    wire = _unpublished(failure_seed).to_dict()
    if mutation == "unknown":
        wire["candidate"] = {}
    elif mutation == "schema":
        wire["schema_version"] = 1
    elif mutation == "protocol":
        wire["protocol"] = "other"
    elif mutation == "plan":
        wire["plan"]["plan_sha256"] = _digest("changed")
    elif mutation == "input":
        wire["input_binding_sha256"] = "bad"
    elif mutation == "ledger-extra":
        wire["ledger_identity"]["claimed_authority"] = True
    elif mutation == "ledger-inode":
        wire["ledger_identity"]["inode"] = True
    elif mutation == "ledger-path":
        wire["ledger_identity"]["database"] = "relative.sqlite"
    elif mutation == "claim-extra":
        wire["claim"]["execute"] = True
    elif mutation == "claim-status":
        wire["claim"]["status"] = "failed"
    elif mutation == "claim-created":
        wire["claim"]["created_at"] = ""
    elif mutation == "claim-digest":
        wire["claim"]["claim_sha256"] = _digest("changed")
    elif mutation == "claim-plan":
        wire["claim"]["plan_sha256"] = _digest("changed")
    elif mutation == "failure":
        wire["native_failure"] = {"status": "failed"}
    else:
        # A valid rehashed alternate plan still cannot bind another terminal/claim.
        alternate = replace(failure_seed.plan, task_id="another-task", plan_sha256=None)
        wire["plan"] = alternate.to_dict()
        wire["claim"]["plan_sha256"] = alternate.plan_sha256
        wire["claim"]["claim_sha256"] = RSILedger._native_claim_digest(
            alternate.request.episode_id, alternate.request_sha256, alternate.plan_sha256,
        )
    with pytest.raises(NativeRSIFailureError):
        NativeRSIFailureEvidence.from_dict(wire)


def test_failure_mapping_has_no_candidate_success_score_or_promotion(failure_seed):
    seed = failure_seed
    result = map_native_failure_to_solver_result(seed.request, seed.plan, seed.evidence)
    assert result.status == "failed" and result.terminal_reason == "native_exited_nonzero"
    assert result.trace_digest == seed.evidence.failure.digest()
    assert result.candidate_receipt_sha256 is None and result.execution_receipt_sha256 is None
    assert result.official_evaluation_receipt_sha256 is None and result.solver_score is None
    assert result.candidate_source_sha256 is None and result.dependency_sha256 is None
    assert result.actor_fingerprint is None and result.trace_events == ()
    pins = dict(result.solver_provenance)
    assert pins["native_claim_sha256"] == seed.evidence.claim_sha256
    assert pins["native_exit_code"] == 7
    assert pins["native_failure_provenance_sha256"] == seed.evidence.provenance_sha256
    assert not set(pins) & {"candidate_id", "publication_receipt_sha256", "approved", "active"}
    with pytest.raises(NativeRSIFailureError, match="provenance_missing"):
        map_native_failure_to_solver_result(seed.request, seed.plan, _unpublished(seed))
    with pytest.raises(NativeRSIFailureError, match="request_mismatch"):
        map_native_failure_to_solver_result(replace(seed.request, episode_id="different"), seed.plan, seed.evidence)


@pytest.mark.parametrize("kind", ["missing-directory", "missing-file", "symlink-directory", "symlink-file", "hardlink", "mode", "same-bytes-new-inode"])
def test_unsafe_provenance_paths_refuse_without_creating_or_repairing(tmp_path, failure_seed, kind):
    directory = tmp_path
    path = tmp_path / NATIVE_RSI_FAILURE_PROVENANCE_NAME
    if kind == "missing-directory":
        directory = tmp_path / "absent" / "nested"
    elif kind == "symlink-directory":
        directory = tmp_path / "linked"
        directory.symlink_to(tmp_path, target_is_directory=True)
    elif kind != "missing-file":
        persist_native_rsi_failure_provenance(tmp_path, _unpublished(failure_seed))
        if kind == "symlink-file":
            path.rename(tmp_path / "retained")
            path.symlink_to(tmp_path / "retained")
        elif kind == "hardlink":
            os.link(path, tmp_path / "alias")
        elif kind == "same-bytes-new-inode":
            replacement = tmp_path / "replacement"
            replacement.write_bytes(path.read_bytes())
            replacement.chmod(0o400)
            replacement.replace(path)
        else:
            path.chmod(0o600)
    before = sorted(item.name for item in tmp_path.iterdir())
    with pytest.raises(NativeRSIFailureError):
        read_native_rsi_failure_provenance(directory)
    assert sorted(item.name for item in tmp_path.iterdir()) == before
    assert not (tmp_path / "absent").exists()


@pytest.mark.parametrize("mutation", ["unknown", "digest", "identity", "duplicate", "noncanonical", "oversize", "partial"])
def test_invalid_durable_records_remain_unchanged(tmp_path, failure_seed, mutation):
    evidence = _unpublished(failure_seed)
    persist_native_rsi_failure_provenance(tmp_path, evidence)
    path = tmp_path / NATIVE_RSI_FAILURE_PROVENANCE_NAME
    value = json.loads(path.read_bytes())
    if mutation == "unknown":
        value["score"] = 1
        _write_record(path, value)
    elif mutation == "digest":
        value["provenance_sha256"] = _digest("wrong")
        _write_record(path, value, raw=canonical_json(value))
    elif mutation == "identity":
        value["file_identity"]["inode"] += 1
        _write_record(path, value)
    elif mutation == "duplicate":
        raw = path.read_bytes().replace(b'"schema_version":"1"', b'"schema_version":"1","schema_version":"1"', 1)
        _write_record(path, value, raw=raw)
    elif mutation == "noncanonical":
        _write_record(path, value, raw=json.dumps(value, indent=2).encode())
    elif mutation == "oversize":
        _write_record(path, value, raw=b"x" * (provenance.MAX_NATIVE_RSI_FAILURE_PROVENANCE_BYTES + 1))
    else:
        _write_record(path, value, raw=b'{"schema_version":')
    before = _file_state(path)
    with pytest.raises(NativeRSIFailureError):
        read_native_rsi_failure_provenance(tmp_path)
    with pytest.raises(NativeRSIFailureError):
        persist_native_rsi_failure_provenance(tmp_path, evidence)
    assert _file_state(path) == before


def test_conflicting_payload_and_dual_sidecar_never_overwrite(tmp_path, failure_seed):
    evidence = _unpublished(failure_seed)
    persist_native_rsi_failure_provenance(tmp_path, evidence)
    path = tmp_path / NATIVE_RSI_FAILURE_PROVENANCE_NAME
    before = _file_state(path)
    with pytest.raises(NativeRSIFailureError, match="conflict"):
        persist_native_rsi_failure_provenance(tmp_path, replace(evidence, input_binding_sha256=_digest("changed")))
    success = tmp_path / NATIVE_RSI_PROVENANCE_NAME
    success.write_bytes(b"malformed-success-still-conflicts")
    success.chmod(0o400)
    with pytest.raises(NativeRSIFailureError, match="conflicting_provenance"):
        read_native_rsi_failure_provenance(tmp_path)
    with pytest.raises(NativeRSIFailureError, match="conflicting_provenance"):
        persist_native_rsi_failure_provenance(tmp_path, evidence)
    assert _file_state(path) == before


def test_partial_write_keeps_bytes_and_refuses_later_recreation(tmp_path, failure_seed, monkeypatch):
    write = os.write
    calls = 0

    def interrupted(descriptor, content):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise OSError("local interrupted fixture")
        return write(descriptor, content[:27])

    monkeypatch.setattr(provenance.os, "write", interrupted)
    with pytest.raises(NativeRSIFailureError, match="write_failed"):
        persist_native_rsi_failure_provenance(tmp_path, _unpublished(failure_seed))
    path = tmp_path / NATIVE_RSI_FAILURE_PROVENANCE_NAME
    assert path.stat().st_size == 27 and stat.S_IMODE(path.stat().st_mode) == 0o400
    before = _file_state(path)
    monkeypatch.setattr(provenance.os, "write", write)
    with pytest.raises(NativeRSIFailureError):
        persist_native_rsi_failure_provenance(tmp_path, _unpublished(failure_seed))
    assert _file_state(path) == before


def test_read_replacement_after_first_read_is_detected(tmp_path, failure_seed, monkeypatch):
    persist_native_rsi_failure_provenance(tmp_path, _unpublished(failure_seed))
    read_once = provenance._read_once
    calls = 0

    def replacement(chain):
        nonlocal calls
        result = read_once(chain)
        calls += 1
        if calls == 1:
            path = tmp_path / NATIVE_RSI_FAILURE_PROVENANCE_NAME
            changed = tmp_path / "replacement"
            changed.write_bytes(path.read_bytes())
            changed.chmod(0o400)
            changed.replace(path)
        return result

    monkeypatch.setattr(provenance, "_read_once", replacement)
    with pytest.raises(NativeRSIFailureError, match="changed"):
        read_native_rsi_failure_provenance(tmp_path)


def test_rehashed_replacement_during_publish_cannot_repin_original_fd(tmp_path, failure_seed, monkeypatch):
    write = os.write
    swapped = False

    def replace_after_write(descriptor, content):
        nonlocal swapped
        count = write(descriptor, content)
        if not swapped:
            swapped = True
            path = tmp_path / NATIVE_RSI_FAILURE_PROVENANCE_NAME
            original = path.read_bytes()
            changed = tmp_path / "replacement"
            changed.write_bytes(original)
            value = json.loads(original)
            info = changed.stat()
            value["file_identity"] = {"device": info.st_dev, "inode": info.st_ino}
            _write_record(changed, value)
            changed.replace(path)
        return count

    monkeypatch.setattr(provenance.os, "write", replace_after_write)
    with pytest.raises(NativeRSIFailureError, match="changed"):
        persist_native_rsi_failure_provenance(tmp_path, _unpublished(failure_seed))
    assert swapped and (tmp_path / NATIVE_RSI_FAILURE_PROVENANCE_NAME).exists()


def test_rehashed_replacement_during_directory_fsync_refuses_before_return(tmp_path, failure_seed, monkeypatch):
    fsync = os.fsync
    swapped = False

    def replace_on_directory_sync(descriptor):
        nonlocal swapped
        fsync(descriptor)
        if stat.S_ISDIR(os.fstat(descriptor).st_mode) and not swapped:
            swapped = True
            path = tmp_path / NATIVE_RSI_FAILURE_PROVENANCE_NAME
            changed = tmp_path / "replacement"
            changed.write_bytes(path.read_bytes())
            value = json.loads(changed.read_bytes())
            info = changed.stat()
            value["file_identity"] = {"device": info.st_dev, "inode": info.st_ino}
            _write_record(changed, value)
            changed.replace(path)

    monkeypatch.setattr(provenance.os, "fsync", replace_on_directory_sync)
    with pytest.raises(NativeRSIFailureError, match="changed"):
        persist_native_rsi_failure_provenance(tmp_path, _unpublished(failure_seed))
    assert swapped and (tmp_path / NATIVE_RSI_FAILURE_PROVENANCE_NAME).exists()


def test_provider_actual_failure_recovery_never_relaunches_or_publishes(failure_seed, monkeypatch):
    seed = failure_seed
    before = {path: _file_state(path) for path in seed.batch.rglob("*") if path.is_file()}
    monkeypatch.setattr(scheduler, "run_native_trusted_producer_outcome", lambda *_a, **_k: pytest.fail("recovery launch"))
    monkeypatch.setattr(scheduler, "_build_receipts", lambda *_a, **_k: pytest.fail("success receipts"))
    original_deadline = dict(seed.request.budget)["deadline_unix"]
    monkeypatch.setattr(scheduler.time, "time", lambda: original_deadline + 1)
    assert seed.provider.recover(seed.request, seed.plan) == seed.evidence
    restarted = make_native_rsi_scheduler_provider(seed.context)
    assert restarted.recover(seed.request, seed.plan) == seed.evidence
    assert {path: _file_state(path) for path in seed.batch.rglob("*") if path.is_file()} == before
    assert seed.ledger.episode_result(seed.request.episode_id) is None
    assert not (seed.batch / "execution-receipt.json").exists()
    assert not (seed.batch / NATIVE_RSI_PROVENANCE_NAME).exists()


def test_provider_explicit_ledger_is_checked_before_launch_and_not_repin(tmp_path, monkeypatch):
    prepared = _native_failure_rsi_fixture(tmp_path)
    monkeypatch.setattr(scheduler, "run_native_trusted_producer_outcome", lambda *_a, **_k: pytest.fail("no claim launch"))
    with pytest.raises(NativeRSISchedulerProviderError, match="failure_claim_missing"):
        prepared.provider(prepared.request, prepared.plan)
    assert not (prepared.batch / "attestation-consumption.json").exists()
    prepared.ledger.claim_native_episode(prepared.request, plan_sha256=prepared.plan.plan_sha256)
    other = RSILedger(tmp_path / "other.sqlite")
    with pytest.raises(NativeRSISchedulerProviderError, match="failure_ledger_changed"):
        prepared.provider.assert_failure_ledger(other)
    original_pin = dict(prepared.provider._failure_ledger_identity)
    replacement = tmp_path / "replacement.sqlite"
    shutil.copyfile(prepared.ledger.database, replacement)
    replacement.replace(prepared.ledger.database)
    with pytest.raises(NativeRSISchedulerProviderError, match="failure_ledger_changed"):
        prepared.provider(prepared.request, prepared.plan)
    assert prepared.provider._failure_ledger_identity == original_pin
    assert not (prepared.batch / "attestation-consumption.json").exists()


def test_ledger_replacement_during_claim_read_is_caught_before_launch(tmp_path, monkeypatch):
    prepared = _native_failure_rsi_fixture(tmp_path)
    claim = prepared.ledger.claim_native_episode(prepared.request, plan_sha256=prepared.plan.plan_sha256)
    replacement = tmp_path / "replacement.sqlite"
    shutil.copyfile(prepared.ledger.database, replacement)

    def swapped_claim(*args, **kwargs):
        replacement.replace(prepared.ledger.database)
        return claim

    monkeypatch.setattr(prepared.ledger, "inspect_native_episode_claim", swapped_claim)
    monkeypatch.setattr(scheduler, "run_native_trusted_producer_outcome", lambda *_a, **_k: pytest.fail("drift launch"))
    with pytest.raises(NativeRSISchedulerProviderError, match="failure_ledger_changed"):
        prepared.provider(prepared.request, prepared.plan)
    assert not (prepared.batch / "attestation-consumption.json").exists()


def test_claim_creation_timestamp_and_sidecar_ledger_identity_are_original(failure_seed, monkeypatch):
    seed = failure_seed
    original_inspect = seed.ledger.inspect_native_episode_claim

    def changed_claim(*args, **kwargs):
        return replace(original_inspect(*args, **kwargs), created_at="different-original-row")

    monkeypatch.setattr(seed.ledger, "inspect_native_episode_claim", changed_claim)
    with pytest.raises(NativeRSISchedulerProviderError, match="failure_claim_changed"):
        seed.provider.recover(seed.request, seed.plan)


def test_sidecar_cannot_supply_missing_native_filesystem_reader(failure_seed, monkeypatch):
    seed = failure_seed
    reads = []

    def refuse(*args, **kwargs):
        reads.append(kwargs["expected"])
        raise ValueError("fixture original native proof missing")

    monkeypatch.setattr(scheduler, "recover_native_trusted_failure", refuse)
    with pytest.raises(NativeRSISchedulerProviderError, match="failure_provenance_invalid"):
        seed.provider.recover(seed.request, seed.plan)
    assert reads == [seed.evidence.failure]


def test_terminal_claim_replay_uses_original_started_claim_projection(failure_seed, monkeypatch):
    seed = failure_seed
    inspect_claim = seed.ledger.inspect_native_episode_claim

    def terminal_claim(*args, **kwargs):
        return replace(inspect_claim(*args, **kwargs), status="failed")

    monkeypatch.setattr(seed.ledger, "inspect_native_episode_claim", terminal_claim)
    assert seed.provider.recover(seed.request, seed.plan) == seed.evidence


def test_unknown_saved_claim_is_quarantined(failure_seed, monkeypatch):
    seed = failure_seed
    inspect_claim = seed.ledger.inspect_native_episode_claim
    monkeypatch.setattr(seed.ledger, "inspect_native_episode_claim", lambda *a, **k: replace(inspect_claim(*a, **k), status="unknown"))
    with pytest.raises(NativeRSISchedulerProviderError, match="failure_claim_missing"):
        seed.provider.recover(seed.request, seed.plan)


def test_original_sqlite_claim_fields_are_preserved(failure_seed):
    seed = failure_seed
    with sqlite3.connect(seed.ledger.database) as connection:
        row = connection.execute("SELECT created_at,claim_sha256 FROM rsi_native_episode_claims").fetchone()
    assert row == (seed.evidence.claim.created_at, seed.evidence.claim_sha256)


def test_actual_accepted_start_cancellation_maps_cancelled_not_failed(tmp_path, monkeypatch):
    source = (
        '#include <stdio.h>\n#include <unistd.h>\n'
        'int main(void){FILE *f=fopen("started","wb");'
        'if(!f||fputs("target",f)<0||fclose(f)!=0)return 2;sleep(3);return 0;}\n'
    )
    prepared = _native_failure_rsi_fixture(tmp_path, target_source=source)
    accepted = []
    accept_frame = TrustedBootstrapSession.accept_frame

    def observe_start(session, frame):
        accept_frame(session, frame)
        if frame.kind == "target_started":
            accepted.append(frame)

    def cancelled():
        return bool(accepted) and (prepared.batch / "work" / "started").exists()

    monkeypatch.setattr(TrustedBootstrapSession, "accept_frame", observe_start)
    context = replace(prepared.context, cancelled=cancelled)
    provider = make_native_rsi_scheduler_provider(context)
    prepared.ledger.claim_native_episode(prepared.request, plan_sha256=prepared.plan.plan_sha256)
    evidence = provider(prepared.request, prepared.plan)
    assert isinstance(evidence, NativeRSIFailureEvidence) and accepted
    result = map_native_failure_to_solver_result(prepared.request, prepared.plan, evidence)
    assert result.status == "cancelled" and result.terminal_reason == "native_cancelled"
    assert dict(result.solver_provenance)["native_exit_code"] is None
    assert result.execution_receipt_sha256 is None and result.official_evaluation_receipt_sha256 is None
    assert provider.recover(prepared.request, prepared.plan) == evidence


def test_live_provider_keeps_publishing_digest_when_sidecar_is_rehashed_after_persist(tmp_path, monkeypatch):
    prepared = _native_failure_rsi_fixture(tmp_path)
    prepared.ledger.claim_native_episode(prepared.request, plan_sha256=prepared.plan.plan_sha256)
    persist = scheduler.persist_native_rsi_failure_provenance
    original_pins = []

    def replace_after_persist(batch, evidence):
        original = persist(batch, evidence)
        path = batch / NATIVE_RSI_FAILURE_PROVENANCE_NAME
        value = json.loads(path.read_bytes())
        replacement = batch / "replacement-provenance"
        replacement.write_bytes(path.read_bytes())
        info = replacement.stat()
        value["file_identity"] = {"device": info.st_dev, "inode": info.st_ino}
        _write_record(replacement, value)
        replacement.replace(path)
        original_pins.append(original)
        return original

    monkeypatch.setattr(scheduler, "persist_native_rsi_failure_provenance", replace_after_persist)
    with pytest.raises(NativeRSISchedulerProviderError, match="failure_provenance_changed"):
        prepared.provider(prepared.request, prepared.plan)
    substituted = read_native_rsi_failure_provenance(prepared.batch)
    assert substituted.provenance_sha256 != original_pins[0]
    assert prepared.ledger.episode_result(prepared.request.episode_id) is None
    assert (prepared.batch / "native-trusted-process-terminal.json").exists()
