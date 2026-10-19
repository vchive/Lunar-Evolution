"""Original waiting native BRS owner creates before evidence; no transaction."""

from __future__ import annotations

import socket
import subprocess
import sys
from copy import deepcopy
from dataclasses import replace
from threading import get_ident
from types import FunctionType

import pytest
import test_rsi_brs_publication_lineage_owner as owner_fixture
import test_rsi_python_brs_publication_recovery as retained

from lunar_evolution import bundle_evolution
from lunar_evolution import producer_bundle_staging as staging
from lunar_evolution import producer_bundle_transaction as transaction
from lunar_evolution import rsi_brs_publication_lineage as brs
from lunar_evolution import rsi_producer_staging_capsule as capsule
from lunar_evolution.automatic_solve_lifecycle import (
    SolveExecutionBudgetExceeded,
    SolveExecutionControl,
)
from lunar_evolution.producer_bundle_lineage import (
    LineageSnapshotPin,
    read_lineage_descriptor_pinned,
)
from lunar_evolution.rsi_gateway import SolverResult
from lunar_evolution.rsi_learning import RSILearningError

_ORIGINAL_COMMIT = staging.commit_producer_bundle_publication


@pytest.fixture
def tmp_path(tmp_path_factory):
    return tmp_path_factory.mktemp("v")


@pytest.fixture(autouse=True)
def inert_only(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("before evidence invoked execution/evaluation/publication")

    for module, names in (
        (subprocess, ("Popen", "run")), (socket, ("create_connection",)),
        (transaction, ("run_native_producer_bundle_publication_transaction",)),
        # Keep canonical stage/commit identities for the BRS policy fingerprint;
        # block their actual publication paths through unpinned staging helpers.
        (staging, ("_journal_for_stage", "_verify_stage")),
        (bundle_evolution, ("evaluate_candidate_execution",)),
    ):
        for name in names:
            monkeypatch.setattr(module, name, forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(bundle_evolution.MultiFileCandidatePipeline, "evaluate_draft_non_publishing", forbidden)


def _inputs(value):
    archive = value.workspace / "evolution/archive.jsonl"
    return (archive.read_bytes() if archive.exists() else b"", (value.workspace / "evolution/state.json").read_bytes())


def _validate(value):
    return value.owner.validate_before(value.journal, *_inputs(value), value.native.strategy,
                                       admission_plan=value.admission)


def _full_ready_reference(value):
    workspace = value.workspace.stat()
    parent = value.workspace.parent.stat()
    pin = LineageSnapshotPin(
        name=capsule.READY_CAPSULE_FILENAME,
        sha256="a" * 64,
        size=capsule.MAX_READY_CAPSULE_BYTES,
        device=workspace.st_dev,
        inode=workspace.st_ino,
        parent_device=parent.st_dev,
        parent_inode=parent.st_ino,
    )
    return {
        "protocol": capsule.READY_CAPSULE_PROTOCOL,
        "workspace": str(value.workspace),
        "journal_id": value.journal.journal_id,
        "workspace_identity": {"device": workspace.st_dev, "inode": workspace.st_ino},
        "file_pin": pin.to_dict(),
    }


@pytest.mark.parametrize("present_archive", [False, True])
def test_real_before_retention_has_one_owner_cas_and_original_source_pins(tmp_path, monkeypatch, present_archive):
    with retained._waiting(tmp_path, monkeypatch) as value:
        archive = value.workspace / "evolution/archive.jsonl"
        if present_archive:
            archive.write_bytes(b"")
            archive.chmod(0o600)
        original = owner_fixture._capture(value)
        budget, memory = deepcopy(value.wave.state["budget_state"]), deepcopy(value.wave.state["root_snapshot"])
        lineage = value.batch / "lineage"
        assert _validate(value) == ()
        assert not lineage.exists()
        owner_fixture._unchanged(value, original)
        write, calls = value.ledger.write_controller_checkpoint, []

        def checkpoint(run_id, state, *, expected_sha256):
            assert get_ident() == value.owner_thread != value.worker_thread
            assert value.ledger.controller_lock_held(run_id)
            assert getattr(value.ledger._observation_scope, "depth", 0) == 0
            calls.append((expected_sha256, deepcopy(state)))
            return write(run_id, state, expected_sha256=expected_sha256)

        monkeypatch.setattr(value.ledger, "write_controller_checkpoint", checkpoint)
        value.owner.retain_before(value.journal, *_inputs(value))
        assert len(calls) == 1 and calls[0][0] == original[0]
        wire = value.wave.state["producer_publication_lineage"]
        assert value.wave.state == original[2] | {"producer_publication_lineage": wire}
        assert value.owner._head == value.wave.checkpoint_sha256 != original[0]
        assert value.owner._phase == "before" and not value.owner._poisoned
        entry = wire["batches"][0]
        assert {path.name for path in lineage.iterdir()} == {"archive-before.snapshot", "state-before.snapshot", "before.json"}
        assert (lineage / "archive-before.snapshot").read_bytes() == b""
        assert (lineage / "state-before.snapshot").read_bytes() == _inputs(value)[1]
        assert ("missing" not in entry["before_sources"]["archive"]) == present_archive
        assert entry["evidence_pins"] == {} and wire["head"] is None and wire["rejections"] == []
        assert entry["before"] == read_lineage_descriptor_pinned(value.workspace, value.journal.journal_id,
            kind="before", expected_file_pin=LineageSnapshotPin.from_dict(entry["before_file_pin"])).to_dict()
        assert _validate(value) == ()
        assert value.ledger.get_episode(value.episode_id).state == "running"
        assert value.ledger.inspect_native_episode_claim(value.request, plan_sha256=value.plan.plan_sha256).status == "started"
        assert value.ledger.episode_result(value.episode_id) is None
        assert value.wave.state["budget_state"] == budget and value.wave.state["root_snapshot"] == memory
        assert not value.ready.is_set() and value.messages.empty()
        assert not value.wave.channel._requests and not value.wave.channel._queue
        assert value.controller.producer_multi_episode_publication is False
        assert value.wave.state["producer_brs_checkpoint_policy"]["online_publication"] is False


def test_before_retention_needs_neither_prepared_journal_nor_attempt_anchor(tmp_path, monkeypatch):
    with retained._waiting(tmp_path, monkeypatch) as value:
        for name in ("journal.prepared.json", "python-producer-admission-anchor.json"):
            (value.batch / name).rename(value.batch / (name + ".not-yet-published"))
        assert _validate(value) == ()
        value.owner.retain_before(value.journal, *_inputs(value))
        assert value.owner._phase == "before"
        assert not (value.batch / "journal.prepared.json").exists()
        assert not (value.batch / "python-producer-admission-anchor.json").exists()


def test_new_before_evidence_composes_original_prepared_reference_and_evidence_cas(tmp_path, monkeypatch):
    with retained._waiting(tmp_path, monkeypatch) as value:
        _validate(value)
        value.owner.retain_before(value.journal, *_inputs(value))
        before = value.owner._head
        record = value.controller._pin_python_admission_for_original_brs_owner(
            value.owner, expected_anchor_sha256=value.anchor.anchor_sha256,
        )
        reference = value.wave.checkpoint_sha256
        evidence = value.owner.acknowledge_prepared(value.journal, record)
        assert len({before, reference, evidence}) == 3
        assert value.owner._phase == "prepared-evidence" and not value.owner._poisoned
        assert _validate(value) == ()
        assert value.ledger.episode_result(value.episode_id) is None


@pytest.mark.parametrize("fault", ["no-validation", "duplicate", "journal", "strategy", "config", "prefix", "admission", "handoff", "bytes"])
def test_invalid_or_repeated_before_inputs_refuse_without_new_checkpoint(tmp_path, monkeypatch, fault):
    with retained._waiting(tmp_path, monkeypatch) as value:
        archive, state = _inputs(value)
        journal, strategy, admission = value.journal, value.native.strategy, value.admission
        if fault == "duplicate":
            _validate(value)
            value.owner.retain_before(journal, archive, state)
        original = owner_fixture._capture(value)
        history = value.ledger.controller_checkpoint_history(value.binding.run_id)
        before_files = retained._files(value.batch / "lineage")
        if fault == "journal":
            journal = replace(journal, task_id="foreign-task", python_handoff_sha256=None,
                python_handoff_file_pin=None, journal_sha256=None)
        elif fault == "strategy":
            strategy = object()
        elif fault == "config":
            journal = replace(journal, population_config_sha256="f" * 64, journal_sha256=None)
        elif fault == "prefix":
            journal = replace(journal, archive_prefix_sha256="f" * 64, journal_sha256=None)
        elif fault == "admission":
            admission = replace(admission, environment_sha256="f" * 64)
        elif fault == "handoff":
            journal = replace(journal, native_execution_receipt_sha256="f" * 64, journal_sha256=None)
        elif fault == "bytes":
            state += b" "
        with pytest.raises((RSILearningError, ValueError)):
            if fault in {"no-validation", "duplicate"}:
                value.owner.retain_before(journal, archive, state)
            else:
                value.owner.validate_before(journal, archive, state, strategy, admission_plan=admission)
        owner_fixture._unchanged(value, original)
        assert value.owner._poisoned
        assert value.ledger.controller_checkpoint_history(value.binding.run_id) == history
        assert retained._files(value.batch / "lineage") == before_files


@pytest.mark.parametrize("fault", ["source-bytes", "marker", "completed-claim", "closed-channel"])
def test_retention_rechecks_original_live_obligations_before_creating_files(tmp_path, monkeypatch, fault):
    with retained._waiting(tmp_path, monkeypatch) as value:
        _validate(value)
        original = owner_fixture._capture(value)
        archive, state = _inputs(value)
        if fault == "source-bytes":
            (value.workspace / "evolution/state.json").write_bytes(state + b" ")
        elif fault == "marker":
            (value.workspace / "evolution/producer-publication.json").write_bytes(b"{}")
        elif fault == "completed-claim":
            # A real claim transition is outside the original owner's capture.
            result = SolverResult(episode_id=value.episode_id, request_sha256=value.request.digest(),
                status="completed", candidate_receipt_sha256="a" * 64, execution_receipt_sha256="a" * 64,
                official_evaluation_receipt_sha256="a" * 64, trace_digest="a" * 64,
                terminal_reason="inert-cannot-revive")
            value.ledger.publish_native_episode_result(value.request, plan_sha256=value.plan.plan_sha256, result=result)
        else:
            value.wave.channel.close()
        with pytest.raises((RSILearningError, ValueError)):
            value.owner.retain_before(value.journal, archive, state)
        owner_fixture._unchanged(value, original)
        assert value.owner._poisoned and not (value.batch / "lineage").exists()


def test_shared_ready_capsule_allowance_is_checked_before_creating_files(tmp_path, monkeypatch):
    with retained._waiting(tmp_path, monkeypatch) as value:
        reference = _full_ready_reference(value)
        state = {
            "producer_multi_episode_publication": True,
            "producer_episode_staging": {
            str(index): {"ready": reference} for index in range(
                brs.MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES // capsule.MAX_READY_CAPSULE_BYTES
                )
            },
        }
        assert capsule.retained_ready_capsule_bytes(state) == brs.MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES
        extra = deepcopy(reference["file_pin"])
        extra["name"] = "extra.snapshot"
        extra["size"] = 1
        wire = {"batches": [{"snapshots": {"extra": extra}}]}
        with pytest.raises(RSILearningError, match="capacity_exceeded"):
            brs.lineage.RSIPublicationLineage._retained_bytes(wire, state)


@pytest.mark.parametrize("failure", ["write", "readback", "post-close"])
def test_failed_checkpoint_preserves_created_evidence_and_stale_capture(tmp_path, monkeypatch, failure):
    with retained._waiting(tmp_path, monkeypatch) as value:
        _validate(value)
        original = owner_fixture._capture(value)
        write = value.ledger.write_controller_checkpoint

        def checkpoint(run_id, state, *, expected_sha256):
            if failure == "write":
                raise RSILearningError("fixture_before_write_failed")
            head = write(run_id, state, expected_sha256=expected_sha256)
            if failure == "post-close":
                value.wave.channel.close()
                return head
            return head + "corrupt"

        monkeypatch.setattr(value.ledger, "write_controller_checkpoint", checkpoint)
        with pytest.raises(RSILearningError):
            value.owner.retain_before(value.journal, *_inputs(value))
        owner_fixture._unchanged(value, original)
        assert value.owner._poisoned
        assert {path.name for path in (value.batch / "lineage").iterdir()} == {
            "archive-before.snapshot", "state-before.snapshot", "before.json",
        }
        durable = value.ledger.controller_checkpoint(value.binding.run_id)
        assert (durable[0] != original[0]) == (failure != "write")


def test_new_before_facade_does_not_open_drs_transaction_or_staging_dispatch(tmp_path, monkeypatch):
    with retained._waiting(tmp_path, monkeypatch) as value:
        _validate(value)
        value.owner.retain_before(value.journal, *_inputs(value))
        with pytest.raises(transaction.NativeProducerBundleTransactionError, match="configuration_invalid"):
            transaction._validate_lineage_owner(True, value.owner)
        # Use the retained unpatched original facade: its exact owner check must
        # still refuse before publication locking or any callback.
        with pytest.raises(staging.ProducerBundlePublicationStagingError, match="lineage_owner_invalid"):
            _ORIGINAL_COMMIT(value.workspace, value.journal, lineage_owner=value.owner)


def test_same_bytes_source_replacement_after_create_is_refused_with_evidence_retained(tmp_path, monkeypatch):
    with retained._waiting(tmp_path, monkeypatch) as value:
        _validate(value)
        original = owner_fixture._capture(value)
        state_path = value.workspace / "evolution/state.json"
        raw, source_inode = state_path.read_bytes(), state_path.stat().st_ino
        configuration, replaced = value.gateway.rsi_fingerprint_config, []

        def config():
            assert not staging._HELD_PUBLICATION_LOCKS.get()
            if (value.batch / "lineage/before.json").exists() and not replaced:
                state_path.rename(state_path.with_suffix(".original"))
                state_path.write_bytes(raw)
                state_path.chmod(0o600)
                replaced.append(True)
            return configuration()

        monkeypatch.setattr(value.gateway, "rsi_fingerprint_config", config)
        with pytest.raises((RSILearningError, ValueError)):
            value.owner.retain_before(value.journal, *_inputs(value))
        assert replaced and state_path.stat().st_ino != source_inode
        owner_fixture._unchanged(value, original)
        assert value.owner._poisoned and (value.batch / "lineage/before.json").exists()


@pytest.mark.parametrize("shadow", ["journal", "admission"])
def test_dto_subclass_refuses_before_worker_serializers(tmp_path, monkeypatch, shadow):
    with retained._waiting(tmp_path, monkeypatch) as value:
        journal, admission = value.journal, value.admission
        original = owner_fixture._capture(value)

        class Shadow(type(journal if shadow == "journal" else admission)):
            def to_dict(self):
                pytest.fail("worker serializer was invoked")

        if shadow == "journal":
            journal = object.__new__(Shadow)
        else:
            admission = object.__new__(Shadow)
        with pytest.raises((RSILearningError, ValueError)):
            value.owner.validate_before(journal, *_inputs(value), value.native.strategy, admission_plan=admission)
        owner_fixture._unchanged(value, original)
        assert value.owner._poisoned and not (value.batch / "lineage").exists()


def test_last_source_callback_cannot_close_channel_then_obtain_before_cas(tmp_path, monkeypatch):
    with retained._waiting(tmp_path, monkeypatch) as value:
        _validate(value)
        original = owner_fixture._capture(value)
        configuration, closed = value.gateway.rsi_fingerprint_config, []

        def config():
            frame = sys._getframe()
            try:
                while frame is not None:
                    if frame.f_code.co_name == "_write":
                        value.wave.channel.close()
                        closed.append(True)
                        break
                    frame = frame.f_back
            finally:
                del frame
            return configuration()

        monkeypatch.setattr(value.gateway, "rsi_fingerprint_config", config)
        with pytest.raises(RSILearningError, match="before_channel_drift"):
            value.owner.retain_before(value.journal, *_inputs(value))
        assert closed and (value.batch / "lineage/before.json").exists()
        owner_fixture._unchanged(value, original)
        assert value.ledger.controller_checkpoint(value.binding.run_id)[0] == original[0]
        assert value.owner._poisoned


@pytest.mark.parametrize("fault", ["cancelled", "timed-out", "post-cancelled"])
def test_original_native_allowance_is_live_before_retention_and_after_cas(tmp_path, monkeypatch, fault):
    now, cancelled = [0.0], [False]
    control = SolveExecutionControl(30, started_at=0, clock=lambda: now[0])
    setup = retained._setup

    def controlled(root, patch):
        value = setup(root, patch)
        object.__setattr__(value.native, "execution_control", control)
        object.__setattr__(value.native, "cancelled", lambda: cancelled[0])
        return value

    monkeypatch.setattr(retained, "_setup", controlled)
    with retained._waiting(tmp_path, monkeypatch) as value:
        _validate(value)
        original = owner_fixture._capture(value)
        if fault == "cancelled":
            cancelled[0] = True
        elif fault == "timed-out":
            now[0] = 31.0
        else:
            write = value.ledger.write_controller_checkpoint

            def checkpoint(*args, **kwargs):
                head = write(*args, **kwargs)
                cancelled[0] = True
                return head

            monkeypatch.setattr(value.ledger, "write_controller_checkpoint", checkpoint)
        with pytest.raises((RSILearningError, SolveExecutionBudgetExceeded)):
            value.owner.retain_before(value.journal, *_inputs(value))
        owner_fixture._unchanged(value, original)
        assert value.owner._poisoned
        assert (value.batch / "lineage").exists() == (fault == "post-cancelled")
        assert (value.ledger.controller_checkpoint(value.binding.run_id)[0] != original[0]) == (fault == "post-cancelled")


@pytest.mark.parametrize("method", ["_validate_candidate_integrity_state", "_active"])
def test_population_same_code_with_foreign_globals_cannot_pass_original_policy(tmp_path, monkeypatch, method):
    with retained._waiting(tmp_path, monkeypatch) as value:
        _validate(value)
        original = owner_fixture._capture(value)
        kind = type(value.native.strategy)
        function = getattr(kind, method)
        rebound = FunctionType(function.__code__, dict(function.__globals__), function.__name__, function.__defaults__)
        rebound.__kwdefaults__ = function.__kwdefaults__
        monkeypatch.setattr(kind, method, rebound)
        with pytest.raises(RSILearningError, match="globals_drift"):
            value.owner.retain_before(value.journal, *_inputs(value))
        owner_fixture._unchanged(value, original)
        assert value.owner._poisoned and not (value.batch / "lineage").exists()
