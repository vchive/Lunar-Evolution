"""Original BRS checkpoint owner over a waiting inert worker and actual SQLite CAS.

No producer/evaluator/model is executed. Fixture-only synthetic output files are
finalized before selected handoff capture; all owner observations/CAS/readbacks
then use real controller, claim, episode, descriptor and creator-pinned files.
"""

from __future__ import annotations

import hashlib
import json
import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import replace
from queue import Queue
from threading import Event, get_ident

import pytest
import test_rsi_python_brs_selected_service as selected
from test_rsi_python_admission import DIGEST, _plan

from lunar_evolution import RSILearningError
from lunar_evolution import rsi_brs_publication_lineage as brs
from lunar_evolution.producer_bundle_admission import (
    ProducerBundleAdmissionItem,
    ProducerBundleAdmissionPlan,
)
from lunar_evolution.producer_bundle_intent import _intent_content
from lunar_evolution.producer_bundle_lineage import (
    ProducerLineageBeforeIntent,
    capture_lineage_snapshot_pin,
    persist_lineage_bytes_snapshot,
    persist_lineage_descriptor,
    persist_lineage_snapshot,
)
from lunar_evolution.python_producer_admission_anchor import (
    persist_python_producer_admission_attempt_anchor,
    project_python_producer_admission_attempt_anchor,
)
from lunar_evolution.python_producer_admission_handoff import (
    PYTHON_PRODUCER_ADMISSION_HANDOFF_NAME,
    build_python_producer_admission_handoff,
    persist_python_producer_admission_handoff_pinned,
)


@pytest.fixture
def tmp_path(tmp_path_factory):
    # Preserve the existing staging cap on macOS by keeping fixture roots short.
    return tmp_path_factory.mktemp("b")


_REBOUND_CALLS = []


def _unexpected_rebound(*_args, **_kwargs):
    _REBOUND_CALLS.append(True)
    pytest.fail("replaced live dependency executed")


class _StopWorker(BaseException):
    pass


@pytest.fixture(autouse=True)
def inert_only(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("BRS checkpoint fixture invoked external execution")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def _setup(tmp_path, monkeypatch):
    value = selected._fixture(tmp_path, monkeypatch)
    binding = value.binding
    value.admission = ProducerBundleAdmissionPlan(
        binding.contract_sha256, "local", binding.evaluator_fingerprint,
        binding.intent.runner_fingerprint, binding.dependency_sha256, binding.environment_sha256,
        (ProducerBundleAdmissionItem("bundle-1", DIGEST, DIGEST, "main.py", ("main.py",), DIGEST),),
    )
    # Replace only the unselected fixture's placeholder output. Preserve its old
    # bytes separately; no owner capture or native claim for this BRS child exists.
    fields = value.handoff.to_dict()
    fields.pop("handoff_sha256")
    fields["admission_plan_sha256"] = value.admission.digest()
    value.handoff = build_python_producer_admission_handoff(**fields)
    handoff_path = value.batch / PYTHON_PRODUCER_ADMISSION_HANDOFF_NAME
    handoff_path.rename(handoff_path.with_suffix(".fixture-original"))
    pinned = persist_python_producer_admission_handoff_pinned(value.batch, handoff=value.handoff)
    value.pin = pinned.file_pin
    state = value.workspace / "evolution/state.json"
    state.write_bytes(b'{"config":{}}')
    state.chmod(0o600)
    value.journal = replace(
        value.journal, admission_sha256=value.admission.digest(), journal_sha256=None,
        base_archive_sha256=hashlib.sha256(b"").hexdigest(),
        archive_prefix_sha256=hashlib.sha256(b"").hexdigest(),
        base_state_sha256=hashlib.sha256(state.read_bytes()).hexdigest(),
        python_handoff_sha256=value.handoff.handoff_sha256, python_handoff_file_pin=value.pin,
    )
    journal_path = value.batch / "journal.prepared.json"
    journal_path.rename(journal_path.with_suffix(".fixture-original"))
    journal_path.write_bytes(_intent_content(value.journal)[0])
    journal_path.chmod(0o600)
    anchor_path = value.batch / "python-producer-admission-anchor.json"
    anchor_path.rename(anchor_path.with_suffix(".fixture-original"))
    value.anchor = project_python_producer_admission_attempt_anchor(value.handoff)
    persist_python_producer_admission_attempt_anchor(value.batch, anchor=value.anchor)
    return value


@contextmanager
def _waiting(tmp_path, monkeypatch):
    value = _setup(tmp_path, monkeypatch)
    messages, ready, stop = Queue(), Event(), Event()

    def operation(request):
        plan = _plan(value.binding, request, value.controller.snapshot)
        value.ledger.claim_native_episode(request, plan_sha256=plan.plan_sha256)
        messages.put((request, plan, get_ident()))
        if not ready.wait(timeout=90):
            raise AssertionError("fixture owner did not release worker")
        if not stop.is_set():
            digest = value.controller._request_python_admission_for_brs_worker(
                value.binding.run_id, request.episode_id, native_plan=plan,
                prepared_journal=value.journal, expected_anchor_sha256=value.anchor.anchor_sha256,
                wait_check=lambda: None,
            )
            messages.put(digest)
            if not stop.wait(timeout=90):
                raise AssertionError("fixture owner did not stop worker")
        raise _StopWorker()

    value.operation = operation
    with selected._wave(value) as wave, ThreadPoolExecutor(max_workers=1) as pool:
        handoff = value.controller._python_admission_bind_selected_brs_handoff(wave)
        future = pool.submit(value.controller._execute_brs_intent, wave, wave.state, handoff.episode_id, handoff)
        request, plan, worker_thread = messages.get(timeout=15)
        value.request, value.plan, value.worker_thread = request, plan, worker_thread
        value.ready, value.messages = ready, messages
        try:
            owner = brs._BRSLineageCheckpointOwner(
                value.controller, wave, request=request, memory=value.controller.snapshot, native_plan=plan,
            )
            value.owner, value.wave = owner, wave
            yield value
        finally:
            stop.set()
            ready.set()
            wave.channel.close()
            with pytest.raises((_StopWorker, RSILearningError)):
                future.result(timeout=20)


def _before(value):
    owner, workspace, journal = value.owner, value.workspace, value.journal
    state = workspace / "evolution/state.json"
    _archive_path, archive = persist_lineage_bytes_snapshot(
        workspace, journal.journal_id, name="archive-before", raw=b"",
        expected_sha256=hashlib.sha256(b"").hexdigest(), retained_bytes=0,
    )
    source = capture_lineage_snapshot_pin(state, name="state-before")
    _state_path, retained = persist_lineage_snapshot(
        workspace, journal.journal_id, name="state-before", source=state,
        expected_pin=source, retained_bytes=0,
    )
    before = ProducerLineageBeforeIntent(value.binding.run_id, journal.journal_id, 0, None, None, archive, retained)
    _path, pin = persist_lineage_descriptor(workspace, before)
    entry = {
        "journal_id": journal.journal_id, "ordinal": 0, "episode_id": value.episode_id,
        "request_sha256": value.request.digest(), "memory_snapshot_sha256": owner._memory.digest(),
        "native_plan_sha256": value.plan.plan_sha256, "admission_plan": value.admission.to_dict(),
        "prepared_journal": journal.to_dict(), "before": before.to_dict(), "before_file_pin": pin.to_dict(),
        "snapshots": {"archive-before": archive.to_dict(), "state-before": retained.to_dict()},
        "before_sources": {"archive": {"missing": True, "parent": brs.lineage._root_pin(state.parent)},
                           "state": source.to_dict()},
        "state": "before", "evidence_pins": {},
    }
    return {**deepcopy(owner._association), "batches": [entry], "head": None, "rejections": []}


def _pin(value):
    value.ready.set()
    assert value.wave.channel.service(
        lambda ready: value.controller._python_admission_service_brs_ready(value.wave, ready), timeout=10,
        observation_scope=lambda: value.controller._python_admission_brs_service_observations(value.wave),
    )
    return value.messages.get(timeout=10)


def _capture(value):
    return value.owner._head, value.owner._payload, deepcopy(value.wave.state)


def _unchanged(value, before):
    assert value.owner._head == before[0] and value.owner._payload == before[1]
    assert value.wave.state == before[2]


def test_genuine_brs_before_then_two_distinct_prepared_cas_keep_worker_running(tmp_path, monkeypatch):
    with _waiting(tmp_path, monkeypatch) as value:
        owner, wave = value.owner, value.wave
        original = _capture(value)
        write, calls = value.ledger.write_controller_checkpoint, []

        def observed(run_id, state, *, expected_sha256):
            assert get_ident() == value.owner_thread != value.worker_thread
            assert value.ledger.controller_lock_held(run_id)
            assert getattr(value.ledger._observation_scope, "depth", 0) == 0
            calls.append((expected_sha256, deepcopy(state)))
            return write(run_id, state, expected_sha256=expected_sha256)

        monkeypatch.setattr(value.ledger, "write_controller_checkpoint", observed)
        wire = _before(value)
        before_head = owner.checkpoint_before(wire)
        assert wave.state == original[2] | {"producer_publication_lineage": wire}
        assert owner._head == wave.checkpoint_sha256 == before_head
        record = _pin(value)
        reference_head = wave.checkpoint_sha256
        assert reference_head != before_head and owner._head == before_head
        assert owner.acknowledge_prepared(value.journal, record) == wave.checkpoint_sha256
        # Admission reference pin uses its own atomic store transaction rather
        # than the public write_controller_checkpoint method observed above.
        assert len(calls) == 2 and [x[0] for x in calls] == [original[0], reference_head]
        history = value.ledger.controller_checkpoint_history(value.binding.run_id)
        assert [head for head, _state in history[-3:]] == [before_head, reference_head, owner._head]
        assert history[-2][1]["producer_publication_lineage"] == wire
        assert history[-1][1]["python_admission_refs"] == history[-2][1]["python_admission_refs"]
        assert set(history[-1][1]["producer_publication_lineage"]["batches"][0]["evidence_pins"]) == {"journal.prepared.json"}
        assert value.ledger.controller_checkpoint(value.binding.run_id) == (owner._head, wave.state)
        assert value.ledger.get_episode(value.episode_id).state == "running"
        assert value.ledger.inspect_native_episode_claim(value.request, plan_sha256=value.plan.plan_sha256).status == "started"
        assert value.ledger.episode_result(value.episode_id) is None
        assert owner._phase == "prepared-evidence" and not owner._poisoned
        assert getattr(value.controller._python_admission_flow_local, "active", None) is None
        assert json.loads(owner._policy_bytes)["mode"] == "brs"
        assert json.loads(owner._policy_bytes)["production_admission"] is False
        assert value.controller.producer_multi_episode_publication is False


@pytest.mark.parametrize("fault", ["foreign-thread", "clone-controller", "clone-wave", "duplicate-owner"])
def test_exact_owner_scope_refuses_foreign_authority(tmp_path, monkeypatch, fault):
    with _waiting(tmp_path, monkeypatch) as value:
        before = _capture(value)
        if fault == "foreign-thread":
            with ThreadPoolExecutor(max_workers=1) as pool, pytest.raises(RSILearningError):
                pool.submit(value.owner.checkpoint_before, _before(value)).result(timeout=10)
        else:
            controller, wave = value.controller, value.wave
            if fault == "clone-controller":
                controller = object()
            if fault == "clone-wave":
                wave = replace(wave)
            with pytest.raises(RSILearningError):
                brs._BRSLineageCheckpointOwner(controller, wave, request=value.request,
                    memory=value.controller.snapshot, native_plan=value.plan)
        _unchanged(value, before)


@pytest.mark.parametrize("fault", ["staged", "terminal", "rejected", "run", "request", "plan", "journal", "extra", "callback"])
def test_checkpoint_primitive_rejects_arbitrary_or_unbound_wire(tmp_path, monkeypatch, fault):
    with _waiting(tmp_path, monkeypatch) as value:
        wire = _before(value)
        entry = wire["batches"][0]
        if fault in {"staged", "terminal", "rejected"}:
            entry["state"] = fault
        elif fault == "run":
            wire["run_id"] = "foreign"
        elif fault in {"request", "plan"}:
            entry["request_sha256" if fault == "request" else "native_plan_sha256"] = "e" * 64
        elif fault == "journal":
            entry["journal_id"] = "foreign"
        elif fault == "extra":
            wire["authority"] = True
        else:
            class Callback:
                def __eq__(self, _other):
                    pytest.fail("callback equality executed")
            entry["ordinal"] = Callback()
        before = _capture(value)
        history = value.ledger.controller_checkpoint_history(value.binding.run_id)
        with pytest.raises((RSILearningError, ValueError)):
            value.owner.checkpoint_before(wire)
        _unchanged(value, before)
        assert value.ledger.controller_checkpoint_history(value.binding.run_id) == history
        assert value.owner._poisoned


@pytest.mark.parametrize("fault", ["head", "source", "memory", "nonce", "budget", "claim-result"])
def test_original_pins_and_running_claim_cannot_drift(tmp_path, monkeypatch, fault):
    with _waiting(tmp_path, monkeypatch) as value:
        wire = _before(value)
        before = _capture(value)
        if fault == "head":
            value.ledger.write_controller_checkpoint(value.binding.run_id, before[2] | {"foreign": True}, expected_sha256=before[0])
        elif fault == "source":
            value.gateway.fingerprint = "foreign"
        elif fault == "memory":
            object.__setattr__(value.request, "memory_snapshot_sha256", "e" * 64)
        elif fault == "nonce":
            object.__setattr__(value.wave.selected_handoff, "lease_nonce", "Z" * 32)
        elif fault == "budget":
            value.wave.budget_state["planned"]["deadline_unix"] += 1
        else:
            claim = value.ledger.inspect_native_episode_claim(value.request, plan_sha256=value.plan.plan_sha256)
            result = selected.SolverResult(episode_id=value.request.episode_id, request_sha256=value.request.digest(),
                status="completed", candidate_receipt_sha256=DIGEST, execution_receipt_sha256=DIGEST,
                official_evaluation_receipt_sha256=DIGEST, trace_digest=DIGEST, terminal_reason="inert-cannot-revive")
            value.ledger.publish_native_episode_result(value.request, plan_sha256=value.plan.plan_sha256,
                result=result, expected_claim=claim)
        with pytest.raises((RSILearningError, ValueError)):
            value.owner.checkpoint_before(wire)
        _unchanged(value, before)
        assert value.owner._poisoned


@pytest.mark.parametrize("fault", ["missing", "head", "payload", "post-owner"])
def test_failed_after_write_readback_preserves_durable_unknown_and_stale_capture(tmp_path, monkeypatch, fault):
    with _waiting(tmp_path, monkeypatch) as value:
        wire, before = _before(value), _capture(value)
        write, read = value.ledger.write_controller_checkpoint, value.ledger.controller_checkpoint
        durable = []

        def observed(run_id, state, *, expected_sha256):
            head = write(run_id, state, expected_sha256=expected_sha256)
            durable.append((head, deepcopy(state)))
            return head

        def invalid(run_id):
            if not durable or fault == "post-owner":
                return read(run_id)
            if fault == "missing":
                return None
            return (("e" * 64, object()) if fault == "head" else (durable[0][0], {"changed": True}))

        monkeypatch.setattr(value.ledger, "write_controller_checkpoint", observed)
        monkeypatch.setattr(value.ledger, "controller_checkpoint", invalid)
        if fault == "post-owner":
            gate = value.controller._validate_original_run_checkpoint_producer_binding
            def post_gate(*args, **kwargs):
                if durable:
                    raise RSILearningError("inert_post_owner_failure")
                return gate(*args, **kwargs)
            monkeypatch.setattr(value.controller, "_validate_original_run_checkpoint_producer_binding", post_gate)
        with pytest.raises(RSILearningError):
            value.owner.checkpoint_before(wire)
        _unchanged(value, before)
        assert len(durable) == 1 and read(value.binding.run_id) == durable[0]
        assert value.owner._poisoned
        with pytest.raises(RSILearningError):
            value.owner.checkpoint_before(wire)
        assert len(durable) == 1


def test_hooks_run_outside_observation_mutex_before_each_cas(tmp_path, monkeypatch):
    with _waiting(tmp_path, monkeypatch) as value, ThreadPoolExecutor(max_workers=1) as observer:
        original = value.gateway.rsi_fingerprint_config
        calls = []
        def inspect():
            with value.controller._python_admission_brs_observations():
                return True
        def config():
            assert observer.submit(inspect).result(timeout=3)
            calls.append(get_ident())
            return original()
        monkeypatch.setattr(value.gateway, "rsi_fingerprint_config", config)
        value.owner.checkpoint_before(_before(value))
        assert calls and set(calls) == {value.owner_thread}


@pytest.mark.parametrize("helper", ["delta", "readback"])
def test_live_checkpoint_helper_replacement_is_refused_before_execution(tmp_path, monkeypatch, helper):
    with _waiting(tmp_path, monkeypatch) as value:
        wire, before = _before(value), _capture(value)
        _REBOUND_CALLS.clear()
        name = "_publication_lineage_checkpoint_delta" if helper == "delta" else "_validate_publication_lineage_checkpoint_readback"
        monkeypatch.setattr(brs.lineage, name, _unexpected_rebound)
        with pytest.raises(RSILearningError, match="policy_drift"):
            value.owner.checkpoint_before(wire)
        _unchanged(value, before)
        assert _REBOUND_CALLS == []


def test_prepared_reference_cannot_adopt_a_nonadjacent_latest_head(tmp_path, monkeypatch):
    with _waiting(tmp_path, monkeypatch) as value:
        value.owner.checkpoint_before(_before(value))
        before = _capture(value)
        record = _pin(value)
        head = value.wave.checkpoint_sha256
        current = deepcopy(value.wave.state)
        foreign = value.ledger.write_controller_checkpoint(value.binding.run_id, current, expected_sha256=head)
        value.wave.checkpoint_sha256 = foreign
        with pytest.raises(RSILearningError, match="prepared_reference_revision_invalid"):
            value.owner.acknowledge_prepared(value.journal, record)
        assert value.owner._head == before[0] and value.owner._payload == before[1]
        assert value.wave.checkpoint_sha256 == foreign
        assert value.owner._poisoned


def test_actual_competing_cas_preserves_original_capture_and_foreign_evidence(tmp_path, monkeypatch):
    with _waiting(tmp_path, monkeypatch) as value:
        wire, before = _before(value), _capture(value)
        write = value.ledger.write_controller_checkpoint
        calls = []
        foreign = before[2] | {"foreign_increment": True}
        def compete(run_id, state, *, expected_sha256):
            calls.append(expected_sha256)
            write(run_id, foreign, expected_sha256=expected_sha256)
            return write(run_id, state, expected_sha256=expected_sha256)
        monkeypatch.setattr(value.ledger, "write_controller_checkpoint", compete)
        with pytest.raises(RSILearningError, match="^rsi_controller_checkpoint_conflict$"):
            value.owner.checkpoint_before(wire)
        _unchanged(value, before)
        assert value.ledger.controller_checkpoint(value.binding.run_id)[1] == foreign
        assert calls == [before[0]] and value.owner._poisoned


@pytest.mark.parametrize("fault", ["missing", "head", "payload"])
def test_second_prepared_cas_lost_readback_keeps_exact_reference_capture(tmp_path, monkeypatch, fault):
    with _waiting(tmp_path, monkeypatch) as value:
        value.owner.checkpoint_before(_before(value))
        record = _pin(value)
        reference = (value.wave.checkpoint_sha256, value.wave.payload, deepcopy(value.wave.state))
        write, read = value.ledger.write_controller_checkpoint, value.ledger.controller_checkpoint
        durable = []
        def observed(run_id, state, *, expected_sha256):
            assert expected_sha256 == reference[0]
            head = write(run_id, state, expected_sha256=expected_sha256)
            durable.append((head, deepcopy(state)))
            return head
        def invalid(run_id):
            if not durable:
                return read(run_id)
            if fault == "missing":
                return None
            return (("e" * 64, object()) if fault == "head" else (durable[0][0], {"changed": True}))
        monkeypatch.setattr(value.ledger, "write_controller_checkpoint", observed)
        monkeypatch.setattr(value.ledger, "controller_checkpoint", invalid)
        with pytest.raises(RSILearningError, match="acknowledgement_readback_invalid"):
            value.owner.acknowledge_prepared(value.journal, record)
        assert (value.owner._head, value.owner._payload, value.wave.state) == reference
        assert value.wave.checkpoint_sha256 == reference[0] and value.wave.payload == reference[1]
        assert len(durable) == 1 and read(value.binding.run_id) == durable[0]
        assert value.owner._poisoned and value.owner._phase == "prepared-reference"
        with pytest.raises(RSILearningError):
            value.owner.acknowledge_prepared(value.journal, record)
        assert len(durable) == 1


@pytest.mark.parametrize("method", ["_write", "_before_entry"])
def test_new_live_owner_methods_are_bound_before_invocation(tmp_path, monkeypatch, method):
    with _waiting(tmp_path, monkeypatch) as value:
        wire, before = _before(value), _capture(value)
        _REBOUND_CALLS.clear()
        monkeypatch.setattr(brs._BRSLineageCheckpointOwner, method, _unexpected_rebound)
        with pytest.raises(RSILearningError, match="policy_drift"):
            value.owner.checkpoint_before(wire)
        _unchanged(value, before)
        assert _REBOUND_CALLS == []


def test_completed_service_return_cannot_construct_a_brs_publication_owner(tmp_path, monkeypatch):
    value = selected._fixture(tmp_path, monkeypatch)
    with selected._wave(value) as wave:
        execution = value.controller._python_admission_run_selected_brs_intent(wave)
        plan = _plan(value.binding, execution.request, value.controller.snapshot)
        assert value.ledger.get_episode(value.episode_id).state == "completed"
        history = value.ledger.controller_checkpoint_history(value.binding.run_id)
        with pytest.raises(RSILearningError, match="running_claim_required"):
            brs._BRSLineageCheckpointOwner(value.controller, wave, request=execution.request,
                memory=value.controller.snapshot, native_plan=plan)
        assert value.ledger.controller_checkpoint_history(value.binding.run_id) == history
        assert value.ledger.get_episode(value.episode_id).state == "completed"


def test_brs_checkpoint_owner_does_not_satisfy_original_drs_facade(tmp_path, monkeypatch):
    with _waiting(tmp_path, monkeypatch) as value:
        before = _capture(value)
        with pytest.raises(RSILearningError, match="^rsi_publication_lineage_owner_invalid$"):
            brs.lineage.acknowledge_publication_lineage_for_active_flow(value.controller, value.owner)
        _unchanged(value, before)
        assert not value.owner._poisoned


def test_late_owner_gate_cannot_adopt_a_same_payload_new_reference_revision(tmp_path, monkeypatch):
    with _waiting(tmp_path, monkeypatch) as value:
        value.owner.checkpoint_before(_before(value))
        original_owner_capture = (value.owner._head, value.owner._payload)
        record = _pin(value)
        reference_head, reference_payload = value.wave.checkpoint_sha256, value.wave.payload
        original = value.controller._python_admission_assert_selected_brs
        calls, inserted = [], []
        def gate(wave, handoff):
            original(wave, handoff)
            calls.append(True)
            # Inject at the late gate continuation, after the first exact history
            # observation. A config hook's immediate wave-head mutation is already
            # rejected by selected_pins' own inner gate; this covers the later gap.
            if len(calls) == 2:
                head = value.ledger.write_controller_checkpoint(value.binding.run_id,
                    deepcopy(wave.state), expected_sha256=wave.checkpoint_sha256)
                wave.checkpoint_sha256 = head
                inserted.append(head)
        monkeypatch.setattr(value.controller, "_python_admission_assert_selected_brs", gate)
        with pytest.raises(RSILearningError, match="prepared_reference_(delta|revision)_invalid"):
            value.owner.acknowledge_prepared(value.journal, record)
        assert len(inserted) == 1 and inserted[0] != reference_head
        assert value.wave.payload == reference_payload
        assert (value.owner._head, value.owner._payload) == original_owner_capture
        assert value.owner._poisoned
        history = value.ledger.controller_checkpoint_history(value.binding.run_id)
        assert [head for head, _state in history[-2:]] == [reference_head, inserted[0]]
        assert history[-1][1] == history[-2][1]
        assert history[-1][1]["producer_publication_lineage"]["batches"][0]["evidence_pins"] == {}
