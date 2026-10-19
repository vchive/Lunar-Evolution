"""Read-only resolution of one durably staged Python RSI child input context."""

from __future__ import annotations

from dataclasses import replace

from .candidate_evaluation_spec import canonical_json
from .python_producer_binding import parse_python_producer_binding
from .python_producer_binding_store import PythonProducerBindingSidecar
from .rsi_gateway import SolverRequest
from .rsi_learning import MemorySnapshot, RSILearningError
from .rsi_native_inputs import NATIVE_RSI_INPUT_MARKER
from .rsi_producer_staging_capsule import materialize_ready, retained_publication_evidence_bytes
from .rsi_python_admission import validate_rsi_python_admission_shapes
from .rsi_python_scheduler_inputs import (
    PythonRSISchedulerInputContext,
    PythonRSISchedulerInputError,
    PythonRSISchedulerPlanFactory,
    _context,
    _read_runtime,
    _read_sidecar,
    _request_memory,
    validate_python_rsi_scheduler_inputs,
)
from .rsi_store import RSILedger


def _fail(reason: str) -> None:
    raise PythonRSISchedulerInputError("episode_" + reason)


def resolve_python_rsi_episode_input_context(
    root_context: PythonRSISchedulerInputContext,
    ledger: RSILedger,
    request: SolverRequest,
    memory: MemorySnapshot,
    *,
    expected_checkpoint_sha256: str,
) -> PythonRSISchedulerInputContext:
    """Resolve ready child inputs under an explicit checkpoint without launch authority.

    Only intent and attestation differ in the returned native context. The caller's
    root context remains immutable and independently validated throughout the read.
    No strategy, handoff supplier, broker, solver, or evaluator is invoked.
    """
    return _resolve_python_rsi_episode_input_context(
        root_context, ledger, request, memory,
        expected_checkpoint_sha256=expected_checkpoint_sha256, mode="drs",
    )


def resolve_reserved_python_rsi_episode_input_context(
    root_context: PythonRSISchedulerInputContext,
    ledger: RSILedger,
    request: SolverRequest,
    memory: MemorySnapshot,
    *,
    expected_checkpoint_sha256: str,
) -> PythonRSISchedulerInputContext:
    """Read one privately staged original BRS child under its existing run lease.

    This separate read-only entry preserves the public resolver's DRS restriction.
    It does not bind a controller, claim an episode or authorize execution.
    """
    return _resolve_python_rsi_episode_input_context(
        root_context, ledger, request, memory,
        expected_checkpoint_sha256=expected_checkpoint_sha256, mode="brs",
    )


def _resolve_python_rsi_episode_input_context(
    root_context, ledger, request, memory, *, expected_checkpoint_sha256, mode,
):
    # Exact typed/pure gates run before SQLite and filesystem observations.
    native, root_sidecar = _context(root_context)
    supplied_request, supplied_memory = request, memory
    request, memory = _request_memory(request, memory)
    if type(ledger) is not RSILedger:
        _fail("ledger_invalid")
    if (type(expected_checkpoint_sha256) is not str or len(expected_checkpoint_sha256) != 64
            or any(char not in "0123456789abcdef" for char in expected_checkpoint_sha256)
            or expected_checkpoint_sha256 == "0" * 64):
        _fail("checkpoint_pin_invalid")
    run_id = root_sidecar.binding.run_id
    try:
        with ledger.read_only_observations():
            root, selected = ledger.resolve_python_producer_checkpoint(
                run_id, request.episode_id, expected_checkpoint_sha256=expected_checkpoint_sha256,
            )
            if root.to_json() != root_context.original_producer_checkpoint.to_json() or selected == root:
                _fail("child_proof_required")
            checkpoint = ledger.controller_checkpoint(run_id)
            if checkpoint is None or checkpoint[0] != expected_checkpoint_sha256:
                _fail("checkpoint_conflict")
            state = checkpoint[1]
            if state.get("mode") != mode:
                _fail("mode_invalid")
            if mode == "brs":
                from .rsi_brs_reserved_reservation import (
                    read_reserved_brs_finalization_reservation,
                    read_reserved_brs_reservation,
                )
                from .rsi_brs_serial_driver import reserved_brs_staging_mode

                if not reserved_brs_staging_mode(state):
                    _fail("mode_invalid")
                plan = state["plan"]
                domain = tuple(f"{run_id}-practice-{plan['wave']}-{index}"
                               for index in range(len(plan["practices"])))
                reservation_reader = (
                    read_reserved_brs_finalization_reservation
                    if (state.get("status") == "completed"
                        and set(state.get("executions", {})) == set(domain))
                    else read_reserved_brs_reservation
                )
                original = reservation_reader(
                    ledger, run_id=run_id, episode_ids=domain,
                    expected_checkpoint_sha256=expected_checkpoint_sha256,
                )
                if (request.episode_id not in domain
                        or memory.to_dict() != original.original_state()["root_snapshot"]):
                    _fail("request_memory_drift")
            entry = state.get("producer_episode_staging", {}).get(request.episode_id)
            if type(entry) is not dict or entry.get("state") != "ready":
                _fail("child_proof_not_ready")
            ready, identity = entry["ready"], entry["identity"]
            validate_rsi_python_admission_shapes((ready, identity))
            if (identity["intent"]["request"] != request.to_dict()
                    or identity["memory"] != memory.to_dict()):
                _fail("request_memory_drift")
            retained_publication_evidence_bytes(state)
            ready = materialize_ready(
                ready, allow_capsule=state.get("producer_multi_episode_publication") is True,
                expected_workspace=native.workspace, expected_journal_id=identity["journal_id"],
            )
            binding = parse_python_producer_binding(canonical_json(ready["binding"], maximum=2 * 1024 * 1024))
            root_wire, child_wire = root_sidecar.binding.to_dict(), binding.to_dict()
            unchanged = set(root_wire) - {"intent", "attestation", "binding_sha256"}
            if any(canonical_json(root_wire[key]) != canonical_json(child_wire[key]) for key in unchanged):
                _fail("root_policy_drift")
            root_intent, child_intent = root_wire["intent"], child_wire["intent"]
            changed = {"journal_id", "launch_id", "task_id", "argv", "argv_sha256", "intent_sha256"}
            if any(root_intent[key] != child_intent[key] for key in set(root_intent) - changed):
                _fail("root_policy_drift")
            root_argv = root_sidecar.binding.intent.argv
            if NATIVE_RSI_INPUT_MARKER in root_argv:
                if root_argv.count(NATIVE_RSI_INPUT_MARKER) != 1 or root_argv[-2] != NATIVE_RSI_INPUT_MARKER:
                    _fail("root_policy_drift")
                root_argv = root_argv[:-2]
            if (binding.intent.argv[:-2] != root_argv
                    or binding.intent.argv[-2] != NATIVE_RSI_INPUT_MARKER
                    or binding.attestation.nonce == root_sidecar.binding.attestation.nonce):
                _fail("root_policy_drift")
            child_sidecar = PythonProducerBindingSidecar(binding=binding, **dict(selected.sidecar_pin))
            child_native = replace(native, intent=binding.intent, attestation=binding.attestation)
            child_context = PythonRSISchedulerInputContext(child_native, child_sidecar, selected)
            _read_sidecar(native, root_sidecar)
            _read_runtime(root_sidecar)
            inputs = validate_python_rsi_scheduler_inputs(child_context, request, memory)
            plan = PythonRSISchedulerPlanFactory(child_context)(request, memory)
            if inputs.to_dict() != ready["inputs"] or plan.to_dict() != ready["plan"]:
                _fail("ready_plan_drift")
            repeated = ledger.resolve_python_producer_checkpoint(
                run_id, request.episode_id, expected_checkpoint_sha256=expected_checkpoint_sha256,
            )
            if repeated != (root, selected):
                _fail("proof_drift")
            _read_sidecar(native, root_sidecar)
            _read_runtime(root_sidecar)
            _context(root_context)
            if _request_memory(supplied_request, supplied_memory) != (request, memory):
                _fail("request_memory_drift")
            return child_context
    except PythonRSISchedulerInputError:
        raise
    except (AttributeError, KeyError, IndexError, TypeError, ValueError, OSError, RSILearningError) as exc:
        raise PythonRSISchedulerInputError("episode_evidence_invalid") from exc


__all__ = ["resolve_python_rsi_episode_input_context"]
