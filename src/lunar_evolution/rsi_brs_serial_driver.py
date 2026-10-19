"""Private composition for an original fully reserved native BRS wave.

Public BRS admission remains closed. The plan marker below only distinguishes
retained staging data; it never grants launch, claim or publication authority.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import stat
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import dataclass

from .candidate_evaluation_spec import canonical_json, strict_json
from .rsi_brs_lineage_prefix import BRSLineagePrefix
from .rsi_brs_preparation_exchange import _BRSNativePreparationExchange
from .rsi_brs_reserved_ledger import assert_reserved_brs_ledger
from .rsi_brs_reserved_reservation import (
    BRSReservedReservationObservation,
    read_reserved_brs_finalization_reservation,
    read_reserved_brs_reservation,
)
from .rsi_brs_reserved_wave import (
    BRSReservedWaveProjection,
    project_reserved_brs_wave,
    select_reserved_brs_child,
)
from .rsi_budget import RSIRunBudget
from .rsi_gateway import SolverRequest
from .rsi_learning import MemorySnapshot, PracticeEpisode, RSILearningError
from .rsi_native_plan import NativeRSIExecutionPlan
from .rsi_python_admission import RSIPythonAdmissionRecord


def _fail(reason):
    raise RSILearningError("rsi_brs_reserved_serial_" + reason)


def reserved_brs_staging_mode(state: object) -> bool:
    """Recognize original private staging metadata, without observing authority.

    Store readers separately compare the original run and every checkpoint.
    The live controller must also verify the persisted executable policy, whole
    original reservation, prefix, held lease and selected child before dispatch.
    """
    if (type(state) is not dict or type(state.get("mode")) is not str
            or state["mode"] != "brs"):
        return False
    plan = state.get("plan")
    policy = state.get("producer_brs_checkpoint_policy")
    return (type(plan) is dict and type(plan.get("mode")) is str and plan["mode"] == "brs"
            and plan.get("reserved_native_serial") is True
            and type(plan.get("max_workers")) is int and plan["max_workers"] == 1
            and state.get("producer_child_execution") is True
            and state.get("producer_multi_episode_publication") is True
            and type(policy) is dict and type(policy.get("mode")) is str and policy["mode"] == "brs"
            and type(policy.get("max_workers")) is int and policy["max_workers"] == 1
            and policy.get("production_admission") is False
            and policy.get("online_publication") is False)


@dataclass(frozen=True, slots=True)
class _BRSReservedSerialObservation:
    reservation: BRSReservedReservationObservation
    prefix: BRSLineagePrefix
    prefix_batches: tuple[dict, ...]
    projection: BRSReservedWaveProjection


@dataclass(frozen=True, slots=True)
class _BRSReservedChildScope:
    """One fresh selected child's original objects, retained by its owner stack."""

    observation: _BRSReservedSerialObservation
    episode: PracticeEpisode
    request: SolverRequest
    memory: MemorySnapshot
    gateway: object
    preview_plan: NativeRSIExecutionPlan
    exchange: _BRSNativePreparationExchange
    deadline: float
    owner_thread: int


def read_reserved_brs_serial_observation(controller, state) -> _BRSReservedSerialObservation | None:
    """Join the original reservation, whole ledger and retained prefix under one lease.

    Extra admission, reconciliation and historical-fence traces are inspected
    before adapting to the projection's narrower data model. They cannot vanish
    merely because a current root fence is absent.
    """
    from .rsi_brs_publication_lineage import _policy, _validate_persisted_policy
    from .rsi_brs_rejection_owner import read_reserved_brs_material_inventory
    from .rsi_brs_reserved_owner import (
        read_reserved_brs_finalization_prefix,
        read_reserved_brs_prefix,
    )
    from .rsi_controller import RSILearningController
    from .rsi_store import RSILedger

    if (type(controller) is not RSILearningController or type(controller.ledger) is not RSILedger
            or not reserved_brs_staging_mode(state)):
        _fail("original_scope_required")
    ledger, run_id = controller.ledger, state.get("run_id")
    RSILedger._assert_controller_lock(ledger, run_id)
    payload = RSILearningController._python_admission_flow_payload(state)
    checkpoint = RSILedger.controller_checkpoint(ledger, run_id)
    if checkpoint is None or RSILearningController._python_admission_flow_payload(checkpoint[1]) != payload:
        _fail("checkpoint_conflict")
    _validate_persisted_policy(controller, run_id=run_id, state=state, expected=_policy())
    plan = state["plan"]
    if (type(plan.get("wave")) is not int or type(plan.get("practices")) is not list
            or not 1 <= len(plan["practices"]) <= 8):
        _fail("domain_invalid")
    domain = tuple(f"{run_id}-practice-{plan['wave']}-{index}" for index in range(len(plan["practices"])))
    # Completed waves use the finalization checkpoint contract.  The running-wave
    # projection intentionally rejects ``status == completed``; replay must
    # validate the existing finalization tail instead of reconstructing a
    # selectable child projection.
    if (state.get("status") == "completed" and type(state.get("executions")) is dict
            and set(state["executions"]) == set(domain)):
        from .rsi_brs_serial_finalization import read_reserved_brs_finalization

        record = ledger.get_run(run_id)
        if record is None:
            _fail("run_missing")
        read_reserved_brs_finalization(controller, record, state)
        return None
    reservation_reader = (
        read_reserved_brs_finalization_reservation
        if (state.get("status") == "completed" and set(state.get("executions", {})) == set(domain))
        else read_reserved_brs_reservation
    )
    reservation = reservation_reader(ledger, run_id=run_id, episode_ids=domain,
                                     expected_checkpoint_sha256=checkpoint[0])
    original = (reservation.original_checkpoint_sha256, reservation.original_state_bytes)
    prefix_reader = (
        read_reserved_brs_finalization_prefix
        if reservation_reader is read_reserved_brs_finalization_reservation
        else read_reserved_brs_prefix
    )
    prefix, batches = prefix_reader(ledger, controller.producer_workspace,
        original_checkpoint=original, expected_checkpoint_sha256=checkpoint[0])
    wire = state.get("producer_publication_lineage")
    if wire is None:
        if prefix.settled_prefix:
            _fail("lineage_missing")
        materials, episode_materials = (), {}
    else:
        materials, episode_materials = read_reserved_brs_material_inventory(
            controller.producer_workspace, wire, prefix_batches=batches,
        )
    refs, traces = state.get("python_admission_refs", {}), reservation.ledger.ledger_traces()
    adapted, terminal_captures = {}, []
    settled = {item[0] for item in prefix.settled_prefix}
    for key in domain:
        trace = traces[key]
        if trace["reconciliation_rows"]:
            _fail("reconciliation_requires_review")
        if key not in settled:
            if trace["admission_rows"] or trace["historical_obligation_sha256s"]:
                _fail("attempt_requires_reconcile")
        else:
            rows, reference = trace["admission_rows"], refs.get(key)
            if (len(rows) != 1 or type(reference) is not dict
                    or len(trace["historical_obligation_sha256s"]) != 1):
                _fail("settled_admission_drift")
            row = rows[0]
            record = RSIPythonAdmissionRecord.from_dict(strict_json(row["payload"], maximum=128 * 1024))
            if ((row["run_id"], row["episode_id"], row["journal_id"], row["record_sha256"])
                    != (run_id, key, reference.get("journal_id"), reference.get("record_sha256"))
                    or record.to_dict() != json.loads(row["payload"])
                    or record.digest() != row["record_sha256"]):
                _fail("settled_admission_drift")
            terminal_captures.append((key, read_reserved_brs_settled_terminal(
                ledger, reservation, key, trace, reference, state["executions"][key])))
        adapted[key] = {name: trace[name] for name in ("episode", "claim", "result", "obligation_sha256")}
        adapted[key].update(
            material_sha256s=list(episode_materials.get(key, ())),
            reference_sha256=(hashlib.sha256(canonical_json(refs[key], maximum=128 * 1024)).hexdigest()
                              if key in refs else None),
        )
    settled_materials = materials
    candidate_count = sum(len(ref["prepared_journal"]["candidates"]) for ref in refs.values())
    untouched_materials = read_reserved_brs_untouched_materials(controller, state, domain, settled)
    materials = (*materials, *untouched_materials)
    retained = tuple((hashlib.sha256(canonical_json({"path": path, "pin": record})).hexdigest(),
                      record["size"] if record["size"] is not None else 0) for path, record in materials)
    projection = project_reserved_brs_wave(reservation.original_state(), state,
        attempt_traces=adapted, settled_prefix=prefix.settled_prefix,
        retained_materials=retained, candidate_count=candidate_count)
    RSIRunBudget.load(state["budget_state"]).check()
    assert_reserved_brs_ledger(ledger, reservation.ledger)
    if read_reserved_brs_untouched_materials(controller, state, domain, settled) != untouched_materials:
        _fail("untouched_material_drift")
    if wire is not None and read_reserved_brs_material_inventory(
            controller.producer_workspace, wire, prefix_batches=batches,
    ) != (settled_materials, episode_materials):
        _fail("settled_material_drift")
    for key, captured in terminal_captures:
        if read_reserved_brs_settled_terminal(
                ledger, reservation, key, traces[key], refs[key], state["executions"][key]) != captured:
            _fail("settled_terminal_drift")
    if RSILearningController._python_admission_flow_payload(state) != payload:
        _fail("checkpoint_conflict")
    return _BRSReservedSerialObservation(reservation, prefix, batches, projection)


def read_reserved_brs_untouched_materials(controller, state, domain, settled):
    """Observe all unattempted journals, allowing only verified ready staging files.

    No directory is created. A native trace in any later ordinal blocks the
    current selection even when no SQLite episode or claim has been written.
    """
    from .producer_process import _held_directory

    stager = controller.producer_stager
    if stager is None:
        _fail("stager_required")
    stager.validate_state(controller, state)
    workspace = controller.producer_workspace
    parent = workspace / "evolution/producer-batches"
    records = []

    def observe(path, children):
        with _held_directory(path) as directory:
            before = os.fstat(directory)
            names = tuple(sorted(os.listdir(directory)))
            if any(name not in children for name in names):
                _fail("untouched_native_trace")
            records.append((path.relative_to(workspace).as_posix(), {
                "kind": "directory", "device": before.st_dev, "inode": before.st_ino,
                "mode": stat.S_IMODE(before.st_mode), "size": None,
                "mtime_ns": before.st_mtime_ns, "ctime_ns": before.st_ctime_ns,
            }))
            for name in names:
                expected = children[name]
                if type(expected) is dict:
                    observe(path / name, expected)
                    continue
                named = os.stat(name, dir_fd=directory, follow_symlinks=False)
                if (not stat.S_ISREG(named.st_mode) or named.st_nlink != 1
                        or named.st_size > 128 * 1024
                        or stat.S_IMODE(named.st_mode) != expected):
                    _fail("untouched_material_invalid")
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                             dir_fd=directory)
                try:
                    opened = os.fstat(fd)
                    chunks, remaining = [], 128 * 1024 + 1
                    while remaining:
                        chunk = os.read(fd, min(65536, remaining))
                        if not chunk:
                            break
                        chunks.append(chunk)
                        remaining -= len(chunk)
                    raw = b"".join(chunks)
                    after = os.fstat(fd)
                    final = os.stat(name, dir_fd=directory, follow_symlinks=False)
                    fields = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
                    if (len(raw) != named.st_size or any(getattr(item, field) != getattr(named, field)
                            for item in (opened, after, final) for field in fields)):
                        _fail("untouched_material_drift")
                    records.append(((path / name).relative_to(workspace).as_posix(), {
                        "kind": "file", "device": named.st_dev, "inode": named.st_ino,
                        "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "mode": expected,
                        "mtime_ns": named.st_mtime_ns, "ctime_ns": named.st_ctime_ns,
                    }))
                finally:
                    os.close(fd)
            after = os.fstat(directory)
            if (names != tuple(sorted(os.listdir(directory))) or any(
                    getattr(before, field) != getattr(after, field) for field in (
                        "st_dev", "st_ino", "st_mode", "st_mtime_ns", "st_ctime_ns"))):
                _fail("untouched_material_drift")

    with _held_directory(parent) as directory:
        for key in domain:
            if key in settled:
                continue
            request = SolverRequest.from_dict(state["intents"][key]["request"])
            identity = stager.identity(controller, state, request, MemorySnapshot.from_dict(state["root_snapshot"]))
            entry = state.get("producer_episode_staging", {}).get(key)
            try:
                os.stat(identity["journal_id"], dir_fd=directory, follow_symlinks=False)
            except FileNotFoundError:
                if entry is not None:
                    _fail("untouched_staging_missing")
                continue
            if (type(entry) is not dict or entry.get("state") != "ready"
                    or entry.get("identity", {}).get("journal_id") != identity["journal_id"]):
                _fail("untouched_native_trace")
            observe(parent / identity["journal_id"], {
                ".rsi-input": {"request.json": 0o400, "memory.json": 0o400, "manifest.json": 0o400},
                "native-rsi-launch.json": 0o400, "python-producer-binding.json": 0o600,
                ".recovery.lock": 0o600, "lineage": {"rsi-ready.snapshot": 0o600},
                "work": {}, "output": {},
            })
    identities = [(record["device"], record["inode"]) for _path, record in records]
    if len(identities) != len(set(identities)) or len(records) > 1024:
        _fail("untouched_material_invalid")
    return tuple(sorted(records))


def read_reserved_brs_settled_terminal(ledger, reservation, key, trace, reference, execution):
    """Bind an historical fence to its original transport, callback and root delta."""
    from .rsi_brs_mailbox_evidence import (
        validate_brs_mailbox_history,
        validate_brs_mailbox_root_history,
    )
    from .rsi_brs_reconcile import FIELD, parse_brs_reconcile_obligations
    from .rsi_python_brs_terminal_lifecycle import _messages, validate_brs_terminal_history

    roots = ledger.controller_checkpoint_history(reservation.ledger.run_id)
    matches = [(index, head, body) for index, (head, body) in enumerate(roots)
               if key in body.get("executions", {})]
    if not matches:
        _fail("settled_root_missing")
    index, _head, settled = matches[0]
    if index == 0 or settled["executions"][key] != execution:
        _fail("settled_root_drift")
    source = roots[index - 1][1]
    obligation = parse_brs_reconcile_obligations(source.get(FIELD)).get(key)
    claim = trace["claim"]
    if (obligation is None or trace["historical_obligation_sha256s"] != [obligation.digest()]
            or claim is None
            or (obligation.run_id, obligation.episode_id, obligation.request_sha256,
                obligation.native_plan_sha256, obligation.native_claim_sha256)
            != (reservation.ledger.run_id, key, claim["request_sha256"],
                claim["plan_sha256"], claim["claim_sha256"])
            or reference["native_plan"]["plan_sha256"] != obligation.native_plan_sha256):
        _fail("settled_obligation_drift")
    expected = json.loads(canonical_json(source, maximum=128 * 1024))
    expected["executions"][key] = execution
    expected.update(phase="evaluated", current_episode_id=key)
    del expected[FIELD][key]
    if expected != settled:
        _fail("settled_root_delta")
    transport = ledger.controller_checkpoint_history("rsi-brs-mailbox:" + obligation.digest())
    terminal = ledger.controller_checkpoint_history("rsi-brs-terminal:" + obligation.digest())
    last = validate_brs_terminal_history(terminal, reserved=True)
    if (last is None or len(terminal) != 4 or last[1]["facts"]["future_outcome"] != "returned"
            or terminal[2][1]["facts"]["outcome"] != "returned"):
        _fail("settled_terminal_missing")
    binding = last[1]["binding"]["mailbox_binding"]
    if binding["obligation"] != obligation.to_dict():
        _fail("settled_obligation_drift")
    tail = validate_brs_mailbox_history(transport, binding=binding)
    if tail is None or len(transport) != 4 or tail[1]["worker_receipt_observed"] is not True:
        _fail("settled_transport_missing")
    validate_brs_mailbox_root_history(roots[:index], transport, binding=binding)
    indices = {head: i for i, (head, _body) in enumerate(roots[:index])}
    previous = indices[tail[1]["root_checkpoint_sha256"]]
    for _head, record in terminal:
        current = indices.get(record["root_checkpoint_sha256"])
        if (current is None or current < previous
                or roots[current][1].get(FIELD, {}).get(key) != obligation.to_dict()
                or roots[current][1].get("producer_publication_lineage")
                    != terminal[0][1]["facts"]["publication"]["lineage"]):
            _fail("settled_terminal_root_drift")
        previous = current
    message, response = _messages(terminal[0][1]["facts"], last[1]["binding"], reserved=True)
    if (message.request_sha256 != tail[1]["mailbox_request_sha256"]
            or hashlib.sha256(message.payload).hexdigest() != tail[1]["request_payload_sha256"]
            or response.response_sha256 != tail[1]["response_sha256"]
            or hashlib.sha256(response.payload).hexdigest() != tail[1]["response_payload_sha256"]):
        _fail("settled_transport_drift")
    return canonical_json({"transport": transport, "terminal": terminal}, maximum=8 * 1024 * 1024)


def assert_reserved_brs_child(controller, wave, scope, handoff, *, before_claim=False, hot=False):
    """Check one original child without borrowing the owner's run lease on a worker."""
    from .rsi_controller import RSILearningController, _PythonAdmissionBRSWave
    from .rsi_native_scheduler import NativeRSISchedulerContext
    from .rsi_producer_gateway import PythonProducerRSISolverGateway
    from .rsi_python_brs_handoff import BRSSelectedChildHandoff
    from .rsi_python_scheduler_inputs import _request_memory
    from .rsi_store import RSILedger

    if (type(controller) is not RSILearningController or type(wave) is not _PythonAdmissionBRSWave
            or type(scope) is not _BRSReservedChildScope
            or type(scope.observation) is not _BRSReservedSerialObservation
            or type(scope.gateway) is not PythonProducerRSISolverGateway
            or type(handoff) is not BRSSelectedChildHandoff or type(before_claim) is not bool
            or type(hot) is not bool
            or type(scope.exchange) is not _BRSNativePreparationExchange
            or type(scope.owner_thread) is not int or scope.owner_thread != wave.owner_thread
            or type(scope.deadline) not in (int, float) or not math.isfinite(scope.deadline)
            or wave.reserved_scope is not scope or wave.selected_handoff is not handoff
            or wave.controller is not controller or wave.ledger is not controller.ledger
            or type(controller.ledger) is not RSILedger or scope.gateway.ledger is not controller.ledger
            or controller.gateway is scope.gateway or not reserved_brs_staging_mode(wave.state)):
        _fail("child_scope_invalid")
    if not hot:
        _request_memory(scope.request, scope.memory)
        selection = select_reserved_brs_child(scope.observation.projection)
        if (selection is None or wave.episode_ids != (selection.episode_id,)
                or scope.episode.episode_id != selection.episode_id
                or scope.request.episode_id != selection.episode_id
                or canonical_json(PracticeEpisode.to_record_dict(scope.episode)) != selection.episode_bytes
                or canonical_json(SolverRequest.to_dict(scope.request)) != selection.request_bytes
                or scope.memory.to_dict() != wave.state["root_snapshot"]
                or scope.request.memory_snapshot_sha256 != scope.memory.digest()
                or scope.preview_plan.request != scope.request
                or scope.preview_plan.memory_snapshot_sha256 != scope.memory.digest()
                or handoff.episode_id != selection.episode_id or handoff.ordinal != selection.ordinal
                or handoff.request_sha256 != selection.request_sha256
                or scope.exchange._request is not scope.request
                or scope.exchange._plan_sha256 != scope.preview_plan.plan_sha256
                or scope.exchange._deadline != scope.deadline):
            _fail("child_original_drift")
    elif (scope.exchange._request is not scope.request
          or scope.exchange._plan_sha256 != scope.preview_plan.plan_sha256
          or scope.exchange._deadline != scope.deadline
          or wave.selected_handoff is not handoff
          or handoff.run_id != wave.run_id
          or handoff.episode_id != scope.request.episode_id
          or handoff.request_sha256 != scope.request.digest()):
        _fail("child_original_drift")
    native = scope.gateway.producer_config.inputs.native_context
    if type(native) is not NativeRSISchedulerContext:
        _fail("child_native_invalid")
    _BRSNativePreparationExchange._fixed(scope.exchange)
    if hot:
        if threading.get_ident() == scope.owner_thread:
            controller._python_admission_active_brs_owner(wave)
        else:
            controller._python_admission_active_brs_worker(wave.run_id, scope.request.episode_id)
    else:
        # The complete source/fingerprint gate ran while binding the handoff and
        # runs again at native claim/dispatch.  Polls here only need the captured
        # identity plus the live checkpoint head.
        controller._python_admission_assert_selected_brs_cached(wave, handoff)
    RSIRunBudget.load(wave.budget_state).check()
    if time.monotonic() >= scope.deadline:
        _fail("deadline_expired")
    if native.execution_control is not None:
        native.execution_control.check("rsi_brs_reserved_serial")
    if native.cancelled is not None and bool(native.cancelled()):
        _fail("cancelled")
    if before_claim and not hot:
        with controller.ledger.read_only_observations():
            claim = controller.ledger.inspect_native_episode_claim(
                scope.request, plan_sha256=scope.preview_plan.plan_sha256)
        if claim is not None:
            _fail("fresh_claim_required")


@contextmanager
def reserved_brs_child_wave(controller, state, scope):
    """Allocate fresh selected transport while retaining the full original envelope."""
    from .rsi_controller import RSILearningController, _PythonAdmissionBRSWave
    from .rsi_python_brs_admission import BRSAdmissionChannel

    if (type(controller) is not RSILearningController or type(scope) is not _BRSReservedChildScope
            or type(state) is not dict or not reserved_brs_staging_mode(state)
            or controller._python_admission_brs_wave is not None
            or controller.producer_stager is None or controller.producer_known_rejection is not True
            or threading.get_ident() != scope.owner_thread):
        _fail("original_scope_required")
    observation = read_reserved_brs_serial_observation(controller, state)
    if observation != scope.observation:
        _fail("observation_changed")
    selected = select_reserved_brs_child(observation.projection)
    if selected is None or selected.episode_id != scope.request.episode_id:
        _fail("selection_invalid")
    payload = RSILearningController._python_admission_flow_payload(state)
    wave = _PythonAdmissionBRSWave(controller, state, state["run_id"], (selected.episode_id,),
        controller.ledger, controller.producer_workspace, controller.producer_sidecar, scope.owner_thread,
        observation.reservation.ledger.checkpoint_sha256, payload,
        BRSAdmissionChannel(state["run_id"], (selected.episode_id,), owner_thread=scope.owner_thread),
        json.loads(RSILearningController._python_admission_flow_payload(state["budget_state"])),
        reserved_scope=scope)
    controller._python_admission_brs_wave = wave
    try:
        controller._python_admission_active_brs_owner(wave)
        yield wave
    finally:
        with controller._python_admission_brs_observations():
            wave.active = False
            controller._python_admission_brs_wave = None
        # Close and wake before the driver's finally joins its original executor.
        wave.channel.close()


def execute_reserved_brs_child(controller, wave, scope, handoff):
    """Run the exact selected objects through the ordinary runner and gateway."""
    from .rsi_controller import PracticeEpisodeRunner

    previous = (getattr(controller._python_admission_brs_local, "dispatch", None),
                getattr(controller._python_admission_brs_local, "active", None),
                getattr(controller._python_admission_brs_local, "publication_forbidden", False))
    if previous[0] is not None or previous[1] is not None or threading.get_ident() == scope.owner_thread:
        _fail("original_worker_required")
    controller._python_admission_brs_local.publication_forbidden = True
    controller._python_admission_brs_local.dispatch = (wave, wave.state, scope.request.episode_id)
    try:
        with controller._python_admission_brs_worker_scope(wave.state, scope.request.episode_id):
            assert_reserved_brs_child(controller, wave, scope, handoff, before_claim=True)
            with controller._python_admission_brs_observations():
                if wave.selected_worker_started:
                    _fail("duplicate_worker")
                wave.selected_worker_started = True
            budget = RSIRunBudget.load(wave.budget_state)

            class ControllerVerifier:
                def verify(self, episode, request, result):
                    return controller._verify_episode(episode, request, result, budget.check)

            def before_run():
                controller._check_memory_admission(scope.request, parent_run_id=wave.run_id)
                assert_reserved_brs_child(controller, wave, scope, handoff, before_claim=True)

            def check():
                assert_reserved_brs_child(controller, wave, scope, handoff)

            return PracticeEpisodeRunner(scope.gateway, ControllerVerifier(), controller.ledger,
                controller.usage_ledger, memory_snapshot=scope.memory,
                before_run=before_run, before_dispatch=check, before_settlement=check,
            ).run(scope.episode, scope.request)
    except BaseException:
        # A claim-before-offer failure must wake the owner without inventing a fence.
        exchange = scope.exchange
        if (type(exchange) is _BRSNativePreparationExchange and type(exchange._scope) is tuple
                and len(exchange._scope) == 6 and exchange._scope[0] is exchange._condition
                and type(exchange._condition) is threading.Condition):
            _BRSNativePreparationExchange._poison(exchange)
        raise
    finally:
        (controller._python_admission_brs_local.dispatch,
         controller._python_admission_brs_local.active,
         controller._python_admission_brs_local.publication_forbidden) = previous


def _child_deadline(native, projection):
    """Intersect original absolute limits; never reset a retained timeout."""
    limits = []
    if native.execution_control is not None:
        native.execution_control.check("rsi_brs_reserved_serial")
        if native.execution_control.deadline is not None:
            limits.append(native.execution_control.deadline)
    # Convert the original controller Unix deadline once for the new transport;
    # the retained deadline and the native execution control stay fixed.
    now, monotonic = time.time(), time.monotonic()
    for deadline in (projection.deadline_unix,):
        if deadline is not None:
            if type(deadline) not in (int, float) or not math.isfinite(deadline):
                _fail("deadline_invalid")
            limits.append(monotonic + deadline - now)
    if not limits or any(type(item) not in (int, float) or not math.isfinite(item) for item in limits):
        _fail("deadline_required")
    deadline = min(limits)
    if deadline <= time.monotonic():
        _fail("deadline_expired")
    return deadline


def read_reserved_brs_published_ready(controller, owner, ready) -> str:
    """Reobserve success's original retained admission; ACK creates no new record."""
    from .rsi_brs_publication_lineage import _BRSLineageCheckpointOwner
    from .rsi_controller import RSILearningController
    from .rsi_python_brs_admission import BRSAdmissionReady, build_brs_admission_ready

    if (type(controller) is not RSILearningController or type(owner) is not _BRSLineageCheckpointOwner
            or owner._controller is not controller or owner._reserved_prefix is None
            or owner._phase != "terminal" or owner._poisoned is not False
            or type(ready) is not BRSAdmissionReady
            or ready.run_id != owner._run_id or ready.episode_id != owner._request.episode_id
            or build_brs_admission_ready(ready.run_id, ready.episode_id, ready.payload) != ready):
        _fail("published_ready_invalid")
    owner._check_owner()
    head, payload = owner._head, owner._payload
    value = strict_json(ready.payload, maximum=128 * 1024)
    if (type(value) is not dict or set(value) != {"native_plan", "prepared_journal", "expected_anchor_sha256"}
            or canonical_json(value, maximum=128 * 1024) != ready.payload
            or value["native_plan"] != owner._plan.to_dict()
            or value["prepared_journal"] != owner._prepared.to_dict()):
        _fail("published_ready_drift")
    plan, journal, binding = controller._python_admission_inputs(
        owner._plan, owner._prepared, value["expected_anchor_sha256"])
    with controller.ledger.read_only_observations():
        expected, run_head, checkpoint_head, episode_head = controller._python_admission_evidence(
            owner._run_id, ready.episode_id, plan, journal, binding, value["expected_anchor_sha256"])
        reference = json.loads(payload).get("python_admission_refs", {}).get(ready.episode_id)
        if (type(reference) is not dict or reference.get("record_sha256") != expected.digest()
                or reference.get("native_plan") != value["native_plan"]
                or reference.get("prepared_journal") != value["prepared_journal"]
                or checkpoint_head != head):
            _fail("published_ready_drift")
        retained = controller.ledger.python_admission_record(owner._run_id, ready.episode_id, plan.journal_id,
            expected_record_sha256=expected.digest(), expected_run_record_sha256=run_head,
            expected_checkpoint_sha256=head, expected_episode_record_sha256=episode_head)
        if retained is None or retained.to_dict() != expected.to_dict():
            _fail("published_ready_drift")
    owner._check_owner()
    if (owner._head, owner._payload) != (head, payload) or owner._phase != "terminal":
        _fail("published_ready_drift")
    return expected.digest()


def drive_reserved_brs_native_serial(controller, record, state):
    """Run one original reserved wave under its bounded checkpoint contract."""
    from .rsi_brs_publication_lineage import _policy_observation_scope
    from .rsi_publication_lineage import reserved_checkpoint_scope

    # A reserved wave is one bounded owner transaction.  Every observation
    # still performs the lightweight alias/runtime drift checks in ``_policy``,
    # while the expensive finite component fingerprint graph is shared for the
    # duration of this transaction.  Without this scope, the serial driver's
    # repeated checkpoint/owner polls rebuild the graph for each child check
    # and can exhaust an otherwise generous wall-clock budget before the worker
    # gets a chance to settle.
    with reserved_checkpoint_scope(), _policy_observation_scope():
        return _drive_reserved_brs_native_serial(controller, record, state)


def _drive_reserved_brs_native_serial(controller, record, state):
    """Service one natural child at a time under the caller's original run lease.

    No public driver dispatches here. This private composition consumes only an
    originally marked, fully reserved wave and refuses any ambiguous attempt.
    """
    from .rsi_brs_native_provider import bind_brs_native_provider
    from .rsi_brs_publication_lineage import _create_reserved_brs_lineage_owner
    from .rsi_brs_serial_finalization import finalize_reserved_brs_serial
    from .rsi_controller import RSILearningController
    from .rsi_producer_gateway import resolve_reserved_python_producer_episode_gateway
    from .rsi_python_brs_publication_mailbox import BRSOwnerPublicationMailbox
    from .rsi_python_brs_terminal_lifecycle import open_brs_terminal_lifecycle

    if type(controller) is not RSILearningController or not reserved_brs_staging_mode(state):
        _fail("original_scope_required")
    # This assertion deliberately does not acquire the non-reentrant run lease.
    controller.ledger._assert_controller_lock(state["run_id"])
    domain = tuple(f"{state['run_id']}-practice-{state['plan']['wave']}-{index}"
                   for index in range(len(state["plan"]["practices"])))
    if type(state.get("executions")) is dict and set(state["executions"]) == set(domain):
        return finalize_reserved_brs_serial(controller, record, state)
    while True:
        observation = read_reserved_brs_serial_observation(controller, state)
        selection = select_reserved_brs_child(observation.projection)
        if selection is None:
            break
        episode = PracticeEpisode.from_dict(json.loads(selection.episode_bytes))
        request = SolverRequest.from_dict(json.loads(selection.request_bytes))
        memory = MemorySnapshot.from_dict(state["root_snapshot"])
        if controller.snapshot.to_dict() != memory.to_dict():
            _fail("frozen_memory_drift")
        staged = state.get("producer_episode_staging", {}).get(selection.episode_id)
        if staged is None:
            controller._stage_producer_episode(state, episode, request)
        elif type(staged) is not dict or staged.get("state") != "ready":
            _fail("staging_requires_reconcile")
        else:
            # A fresh lease may use the original retained ready capsule read-only.
            controller.producer_stager.validate_state(controller, state)
        observation = read_reserved_brs_serial_observation(controller, state)
        child = resolve_reserved_python_producer_episode_gateway(controller, request, memory,
            expected_checkpoint_sha256=observation.reservation.ledger.checkpoint_sha256)
        preview = child._plan(request, memory)
        deadline = _child_deadline(child.producer_config.inputs.native_context, observation.projection)
        exchange = _BRSNativePreparationExchange(request, expected_plan_sha256=preview.plan_sha256,
                                                  deadline=deadline)
        scope = _BRSReservedChildScope(observation, episode, request, memory, child, preview,
                                       exchange, deadline, threading.get_ident())
        pool = None
        try:
            with reserved_brs_child_wave(controller, state, scope) as wave:
                handoff = controller._python_admission_bind_selected_brs_handoff(wave)
                child.bind_reserved_brs_child_controller(controller, wave=wave, scope=scope, handoff=handoff)
                bind_brs_native_provider(child.config.receipt_provider, controller=controller,
                                         wave=wave, scope=scope, handoff=handoff)
                assert_reserved_brs_child(controller, wave, scope, handoff, before_claim=True)
                pool = ThreadPoolExecutor(max_workers=1)
                future = pool.submit(execute_reserved_brs_child, controller, wave, scope, handoff)
                exchange.attach_worker(future, pool)

                def owner_check(_stage=None, *, wave=wave, scope=scope, handoff=handoff):
                    assert_reserved_brs_child(controller, wave, scope, handoff)

                def owner_hot_check(_stage=None, *, wave=wave, scope=scope, handoff=handoff):
                    assert_reserved_brs_child(controller, wave, scope, handoff, hot=True)

                try:
                    offer = exchange.take(check=owner_check, hot_check=owner_hot_check)
                except BaseException as error:
                    if Future.done(future) and not Future.cancelled(future):
                        worker_error = Future.exception(future)
                        if worker_error is not None and worker_error is not error:
                            error.add_note(f"worker_exception={worker_error!r}")
                    raise
                original = (observation.reservation.original_checkpoint_sha256,
                            observation.reservation.original_state_bytes)
                owner = _create_reserved_brs_lineage_owner(controller, wave, request=request, memory=memory,
                    native_plan=offer.plan, original_checkpoint=original, prefix=observation.prefix,
                    prefix_batches=observation.prefix_batches)
                mailbox = BRSOwnerPublicationMailbox(handoff, worker_thread=offer.thread.ident)
                session = open_brs_terminal_lifecycle(owner, mailbox, future=future, executor=pool)
                exchange.return_endpoint(offer, session.worker_endpoint)
                owner_check()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    _fail("deadline_expired")
                try:
                    session.serve(offer.preparation, check=owner_check,
                                  timeout=min(60.0, remaining))
                except BaseException as error:
                    # The owner/lifecycle failure is authoritative. Preserve it while
                    # attaching the worker failure for reconciliation diagnostics; the
                    # exchange teardown must never replace the primary exception.
                    if future.done() and not future.cancelled():
                        worker_error = future.exception()
                        if worker_error is not None and worker_error is not error:
                            error.add_note(f"worker_exception={worker_error!r}")
                    raise
                controller._python_admission_settle_original_brs_terminal(owner, session)
                if owner._phase != "retired" or session._poisoned is not True:
                    _fail("retirement_incomplete")
        finally:
            exchange.fail()
            if pool is not None:
                pool.shutdown(wait=True)
    return finalize_reserved_brs_serial(controller, record, state)
