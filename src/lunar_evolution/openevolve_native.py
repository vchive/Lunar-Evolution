"""Explicit one-shot native execution for the existing OpenEvolve seed strategy.

Native execution and local seed admission have different authority tuples. This module keeps
both, claims before effects, and replays only a completely acknowledged atomic seed commit.
It does not register a Python project or authenticate a remote worker.
"""
from __future__ import annotations

import hashlib
import math
import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn
from urllib.parse import urlsplit

from . import _benchmark_files as files
from .automatic_solve_lifecycle import (
    SolveExecutionBudgetExceeded,
    SolveExecutionCancelled,
    SolveExecutionControl,
)
from .candidate_evaluation_spec import canonical_json, strict_json
from .evolution import MAX_ARCHIVE_BYTES, EvolutionError
from .native_bootstrap import NativeBootstrapArtifact
from .producer_broker_ipc import ProducerBrokerConfig
from .producer_bundle_handoff import BundleGroup
from .producer_handoff import admit_producer_envelope, prepare_producer_seed_manifest
from .producer_launch_inputs import (
    ProducerLaunchInputDescriptor,
    prepare_producer_launch_inputs,
    validate_producer_launch_inputs,
)
from .producer_launcher import (
    ProducerLaunchAttestation,
    ProducerLaunchIntent,
    parse_producer_launch_attestation,
    parse_producer_launch_intent,
    preflight_producer_launch,
)
from .producer_lifecycle import (
    ProducerLifecyclePreparation,
    recover_native_trusted_lifecycle,
    run_native_trusted_lifecycle,
)
from .producer_process import _held_directory
from .seed_handoff import recover_retained_seed_admission

if TYPE_CHECKING:
    from .evolution import EvolutionContext, OpenEvolveStrategy, StrategyResult

_PROTOCOL = "lunar-openevolve-native-admission-v1"
_MAX = 256 * 1024
_CONFIG_ARG = "../.producer-input/config.json"


def _fail(reason: str) -> NoReturn:
    raise EvolutionError("openevolve_native_" + reason)


def _canonical(value: object) -> bytes:
    return canonical_json(value, maximum=_MAX)


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _node(path: Path) -> dict[str, int]:
    with _held_directory(path) as descriptor:
        info = os.fstat(descriptor)
        return {"device": info.st_dev, "inode": info.st_ino}


def openevolve_native_workspace(workspace: str | Path) -> Path:
    """Return the fixed companion location, without creating or resolving it."""
    return files.absolute_path(workspace) / ".producer-runs" / "openevolve"


def _config(strategy: OpenEvolveStrategy) -> dict[str, Any]:
    return {
        "schema_version": "1", "contract": strategy.context.contract.to_dict(),
        "workspace": str(openevolve_native_workspace(strategy.context.workspace)),
        "result_path": "../output/producer-result.json",
        "producer": {"id": "openevolve", "fingerprint": strategy._producer_fingerprint()},
        "budget": strategy._budget(),
    }


def prepare_openevolve_native_inputs(
    context: EvolutionContext, *, journal_id: str,
) -> ProducerLaunchInputDescriptor:
    """Freeze config before building the intent and its one-time attestation.

    The configured command's first argument is an absolute native executable. The intent argv
    must use its relative name, the remaining command arguments, the config argument above and
    the returned descriptor's argv_fragment. Bind the descriptor with the ordinary producer
    launch-input API after building the attestation. Repeated preparation never overwrites files.
    """
    from .evolution import OpenEvolveStrategy

    strategy = OpenEvolveStrategy(context, read_only=True)
    canonical = files.absolute_path(context.workspace)
    _node(canonical)
    runtime = openevolve_native_workspace(canonical)
    with _held_directory(runtime, create=True):
        return prepare_producer_launch_inputs(runtime, journal_id=journal_id, config=_config(strategy))


@dataclass(frozen=True, slots=True, repr=False)
class OpenEvolveNativeExecution:
    """Process-local opt-in; host-only broker configuration is never serialized."""

    producer_root: Path
    intent: ProducerLaunchIntent
    attestation: ProducerLaunchAttestation
    artifact: NativeBootstrapArtifact
    broker_config: ProducerBrokerConfig
    groups: tuple[BundleGroup, ...]
    deadline_unix: float

    def __post_init__(self) -> None:
        if (type(self.intent) is not ProducerLaunchIntent
                or type(self.attestation) is not ProducerLaunchAttestation
                or type(self.artifact) is not NativeBootstrapArtifact
                or type(self.broker_config) is not ProducerBrokerConfig
                or type(self.groups) is not tuple or len(self.groups) != 1
                or type(self.groups[0]) is not BundleGroup
                or len(self.groups[0].material_paths) != 1
                or self.groups[0].entrypoint != self.groups[0].material_paths[0]):
            _fail("execution_invalid")
        try:
            if (type(self.deadline_unix) not in (int, float)
                    or not math.isfinite(float(self.deadline_unix)) or self.deadline_unix <= 0):
                _fail("deadline_invalid")
            object.__setattr__(self, "producer_root", files.absolute_path(self.producer_root))
            endpoint = urlsplit(self.broker_config.endpoint)
            if endpoint.username is not None or endpoint.password is not None or endpoint.query or endpoint.fragment:
                _fail("broker_endpoint_invalid")
        except (OverflowError, ValueError, TypeError) as exc:
            raise EvolutionError("openevolve_native_execution_invalid") from exc


def _binding(strategy: OpenEvolveStrategy, execution: OpenEvolveNativeExecution) -> dict[str, Any]:
    if type(execution) is not OpenEvolveNativeExecution:
        _fail("execution_invalid")
    # Revalidate DTOs at this composition boundary, including nested caller-owned objects.
    if (parse_producer_launch_intent(execution.intent.to_dict()) != execution.intent
            or parse_producer_launch_attestation(execution.attestation.to_dict()) != execution.attestation):
        _fail("binding_mismatch")
    execution.__post_init__()
    context, intent = strategy.context, execution.intent
    root = files.absolute_path(context.workspace)
    runtime = openevolve_native_workspace(root)
    inputs = validate_producer_launch_inputs(
        runtime, intent=intent, attestation=execution.attestation, artifact=execution.artifact,
    )
    command = strategy.config.command
    executable = execution.producer_root / intent.executable_relative
    if (inputs is None or inputs.config != _config(strategy)
            or intent.producer_id != "openevolve"
            or intent.producer_fingerprint != strategy._producer_fingerprint()
            or intent.contract_sha256 != context.contract.digest()
            or intent.evaluator_kind != "exact_harness"
            or intent.evaluator_fingerprint != strategy.config.evaluator_fingerprint
            or intent.working_directory != "work" or intent.output_directory != "output"
            or intent.wall_timeout_seconds > strategy.config.timeout_seconds
            or files.absolute_path(command[0]) != executable
            or intent.argv != (intent.executable_relative, *command[1:], _CONFIG_ARG, *inputs.argv_fragment)):
        _fail("binding_mismatch")
    group = execution.groups[0]
    canonical_group = BundleGroup(group.bundle_id, group.entrypoint, group.material_paths)
    if group != canonical_group:
        _fail("binding_mismatch")
    for name, value in (
        ("evaluator_kind", context.evaluator_kind), ("evaluator_kind", strategy.config.evaluator_kind),
        ("runner_fingerprint", strategy.config.runner_fingerprint),
        ("generator_fingerprint", strategy.config.generator_fingerprint),
        ("dependency_sha256", context.dependency_sha256), ("dependency_sha256", strategy.config.dependency_sha256),
        ("environment_sha256", context.environment_sha256), ("environment_sha256", strategy.config.environment_sha256),
    ):
        if value is not None and value != getattr(intent, name):
            _fail("binding_mismatch")
    preflight_producer_launch(
        runtime, intent, producer_root=execution.producer_root,
        candidate_integrity_authority={"schema_version": "1", **{
            name: getattr(intent, name) for name in (
                "contract_sha256", "evaluator_kind", "evaluator_fingerprint", "dependency_sha256",
                "environment_sha256", "runner_fingerprint", "generator_fingerprint",
            )
        }}, expected_run_id=intent.run_id, expected_parent_task_id=intent.parent_task_id,
        expected_task_id=intent.task_id,
    )
    return {
        "schema_version": "1", "protocol": _PROTOCOL,
        "canonical_workspace": str(root), "canonical_identity": _node(root),
        "runtime_workspace": str(runtime), "runtime_identity": _node(runtime),
        "producer_root": str(execution.producer_root), "producer_root_identity": _node(execution.producer_root),
        "config_sha256": _sha(strategy.config.to_dict()),
        "context_authority": strategy.integrity_authority.to_dict(),
        "intent": intent.to_dict(), "attestation": execution.attestation.to_dict(),
        "bootstrap_descriptor": execution.artifact.descriptor.to_dict(),
        "bootstrap_artifact_sha256": execution.artifact.artifact_sha256,
        "inputs": inputs.to_dict(), "deadline_unix": execution.deadline_unix,
        "group": {"bundle_id": group.bundle_id, "entrypoint": group.entrypoint,
                  "material_paths": list(group.material_paths)},
        # Destination identity only. Credentials and credential-derived fingerprints stay out.
        "broker_endpoint_sha256": hashlib.sha256(execution.broker_config.endpoint.encode()).hexdigest(),
    }


def _read_checkpoint(path: Path) -> dict[str, Any]:
    raw = files.read_regular_file(path, _MAX)
    info = path.lstat()
    value = strict_json(raw, maximum=_MAX)
    if (not isinstance(value, dict) or raw != _canonical(value)
            or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o400
            or value.get("file_identity") != {"device": info.st_dev, "inode": info.st_ino}
            or value.get("checkpoint_sha256") != _sha({
                key: item for key, item in value.items() if key != "checkpoint_sha256"
            })):
        _fail("checkpoint_mismatch")
    return value


def _checkpoint(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    """Create-only acknowledgement with a self-inode binding and durable directory entry."""
    with _held_directory(path.parent) as directory:
        fd = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o400, dir_fd=directory)
        try:
            os.fchmod(fd, 0o400)
            info = os.fstat(fd)
            value = {**payload, "file_identity": {"device": info.st_dev, "inode": info.st_ino}}
            value["checkpoint_sha256"] = _sha(value)
            raw = _canonical(value)
            offset = 0
            while offset < len(raw):
                written = os.write(fd, raw[offset:])
                if written <= 0:
                    _fail("checkpoint_write_failed")
                offset += written
            os.fsync(fd)
            os.fsync(directory)
        finally:
            os.close(fd)
    if _read_checkpoint(path) != value:
        _fail("checkpoint_mismatch")
    return value


def _arguments(strategy: OpenEvolveStrategy, execution: OpenEvolveNativeExecution) -> dict[str, Any]:
    intent = execution.intent
    return {
        "intent": intent, "attestation": execution.attestation, "artifact": execution.artifact,
        "contract": strategy.context.contract, "groups": execution.groups,
        "evaluator_kind": intent.evaluator_kind, "evaluator_fingerprint": intent.evaluator_fingerprint,
        "runner_fingerprint": intent.runner_fingerprint, "dependency_sha256": intent.dependency_sha256,
        "environment_sha256": intent.environment_sha256,
    }


def _check_preparation(prepared: ProducerLifecyclePreparation, execution: OpenEvolveNativeExecution) -> None:
    group, receipt, envelope = execution.groups[0], prepared.receipt, prepared.envelope
    if (prepared.native_run is None or prepared.publication is not None
            or prepared.execution_outcome != "completed" or receipt.status != "completed"
            or receipt.exit_code != 0 or not receipt.gate_released
            or receipt.cleanup_status not in {"cleaned", "already_exited"}
            or prepared.request_coverage != "brokered_requests_only"
            or not receipt.trusted_execution
            or len(envelope.materials) != 1 or len(prepared.drafts) != 1 or len(prepared.bundles) != 1
            or envelope.materials[0].path != group.entrypoint
            or envelope.producer_id != "openevolve"
            or envelope.producer_fingerprint != execution.intent.producer_fingerprint):
        _fail("preparation_mismatch")


def _publication_snapshot(strategy: OpenEvolveStrategy) -> dict[str, Any]:
    candidates = strategy.archive.records()
    if len(candidates) != 1:
        _fail("publication_mismatch")
    candidate = candidates[0]
    paths = [strategy.archive.state_path, strategy.archive.archive_path,
             strategy.archive.root / "seed-commit.json"]
    source = strategy.archive.workspace / candidate.code_path
    paths.extend([source, source.parent / "record.json", source.parent / "receipt.json"])
    contract = strategy.archive.root / "contract.json"
    if contract.exists() or contract.is_symlink():
        paths.append(contract)
    result = {}
    for path in paths:
        raw = files.read_regular_file(path, MAX_ARCHIVE_BYTES)
        info = path.lstat()
        if info.st_nlink != 1:
            _fail("publication_mismatch")
        result[path.relative_to(strategy.archive.workspace).as_posix()] = {
            "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw),
            "device": info.st_dev, "inode": info.st_ino,
            "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns,
        }
    return result


def _replay(strategy: OpenEvolveStrategy, execution: OpenEvolveNativeExecution,
            binding: dict[str, Any], claim: dict[str, Any], state: dict[str, Any]) -> StrategyResult:
    runtime = openevolve_native_workspace(strategy.context.workspace)
    if state.get("status") != "completed":
        _fail("recovery_required")
    complete_path = runtime / "completion.json"
    if not complete_path.exists():
        _fail("recovery_required")
    completion = _read_checkpoint(complete_path)
    local = _read_checkpoint(runtime / "admission.json")
    plan_sha = _sha(binding)
    expected_state = {
        "protocol": _PROTOCOL, "plan_sha256": plan_sha,
        "claim_sha256": claim["checkpoint_sha256"],
        "admission_sha256": local["checkpoint_sha256"],
    }
    if (state.get("trusted_native_admission") != expected_state
            or local.get("protocol") != _PROTOCOL or local.get("plan_sha256") != plan_sha
            or local.get("claim_sha256") != claim["checkpoint_sha256"]
            or completion.get("protocol") != _PROTOCOL
            or completion.get("admission_sha256") != local["checkpoint_sha256"]
            or completion.get("publication") != _publication_snapshot(strategy)):
        _fail("publication_mismatch")
    before = _publication_snapshot(strategy)
    prepared = recover_native_trusted_lifecycle(runtime, **_arguments(strategy, execution))
    _check_preparation(prepared, execution)
    if (local.get("execution_receipt_sha256") != prepared.receipt.receipt_sha256
            or local.get("envelope_sha256") != prepared.envelope.envelope_sha256
            or local.get("native_admission_plan_sha256") != prepared.admission_plan.digest()):
        _fail("admission_mismatch")
    output = runtime / "evolution" / "producer-batches" / execution.intent.journal_id / "output"
    manifest = prepare_producer_seed_manifest(
        output, strategy.context.contract, evaluator_fingerprint=execution.intent.evaluator_fingerprint,
        producer_fingerprint=execution.intent.producer_fingerprint, producer_id="openevolve",
    )
    candidate = strategy.archive.records()[0]
    if local.get("candidate_id") != candidate.candidate_id:
        _fail("admission_mismatch")
    seed = recover_retained_seed_admission(
        manifest, candidate, candidate_root=strategy.archive.candidates_root / candidate.candidate_id,
        expected_receipt_sha256=local["local_evaluator_receipt_sha256"],
    )
    if (local.get("seed_dependency_sha256") != manifest.dependency_sha256
            or local.get("seed_environment_sha256") != manifest.environment_sha256):
        _fail("admission_mismatch")
    strategy.archive.validate_initial_seeds(
        (seed,), state=state, contract_sha256=strategy.context.contract.digest(),
        evaluator_fingerprint=strategy.config.evaluator_fingerprint, canonical_strategy="openevolve",
    )
    result = strategy.archive.result("openevolve", "completed", 1)
    if (_binding(strategy, execution) != binding or _publication_snapshot(strategy) != before
            or _read_checkpoint(runtime / "admission-claim.json") != claim
            or _read_checkpoint(runtime / "admission.json") != local
            or _read_checkpoint(complete_path) != completion):
        _fail("replay_changed")
    return result


def run_openevolve_native(strategy: OpenEvolveStrategy, state: dict[str, Any]) -> StrategyResult:
    """Execute a claimed attempt once, or revalidate its complete retained publication."""
    execution = strategy.context.trusted_native_execution
    try:
        binding = _binding(strategy, execution)
        runtime = openevolve_native_workspace(strategy.context.workspace)
        claim_path = runtime / "admission-claim.json"
        if claim_path.exists() or claim_path.is_symlink():
            claim = _read_checkpoint(claim_path)
            if (claim.get("protocol") != _PROTOCOL or claim.get("status") != "started"
                    or claim.get("binding") != binding or claim.get("plan_sha256") != _sha(binding)):
                _fail("binding_mismatch")
            return _replay(strategy, execution, binding, claim, state)
        if state:
            _fail("protocol_mismatch")
        # Sample monotonic first: a pause between clocks can only shorten the allowance.
        sampled_monotonic = time.monotonic()
        sampled_unix = time.time()
        if execution.deadline_unix > sampled_unix + strategy.config.timeout_seconds:
            _fail("deadline_invalid")
        remaining = execution.deadline_unix - sampled_unix
        if remaining <= 0:
            observed = time.monotonic()
            raise SolveExecutionBudgetExceeded("openevolve_native_launch", started_at=observed,
                                               deadline=observed, observed_at=observed)
        owner_errors: list[Exception] = []

        def cancelled() -> bool:
            # Native polling must notice owner loss while a target is active. Translate the
            # guard failure into cancellation for cleanup, then propagate its original type.
            if strategy.context.continuation_guard is not None:
                try:
                    strategy.context.continuation_guard()
                except Exception as exc:  # noqa: BLE001 - owner callback is a caller boundary
                    owner_errors.append(exc)
                    return True
            return strategy._cancelled()

        control = SolveExecutionControl(remaining, started_at=sampled_monotonic, cancelled=cancelled)

        def guard(stage: str) -> float:
            if strategy.context.continuation_guard is not None:
                strategy.context.continuation_guard()
            if strategy.context.remaining_timeout is not None:
                parent_sample = control._now()
                parent = strategy.context.remaining_timeout(stage)
                if type(parent) not in (int, float) or not math.isfinite(float(parent)):
                    _fail("parent_budget_invalid")
                # Narrow the same monotonic deadline, never allocate a fresh stage budget.
                control.deadline = min(control.deadline, parent_sample + max(0, parent))
            return control.check(stage)

        guard("openevolve_native_claim")
        # The claim is the only launch/evaluation/commit owner. An O_EXCL competitor never retries.
        try:
            claim = _checkpoint(claim_path, {
                "protocol": _PROTOCOL, "status": "started", "binding": binding, "plan_sha256": _sha(binding),
            })
        except FileExistsError:
            _fail("recovery_required")
        guard("openevolve_native_launch")
        if _binding(strategy, execution) != binding:
            _fail("binding_mismatch")
        try:
            prepared = run_native_trusted_lifecycle(
                runtime, **_arguments(strategy, execution), producer_root=execution.producer_root,
                broker_config=execution.broker_config, execution_control=control, strategy=None,
            )
        except SolveExecutionCancelled:
            if owner_errors:
                raise owner_errors[0]
            raise
        _check_preparation(prepared, execution)
        guard("openevolve_native_evaluation")
        if _binding(strategy, execution) != binding or _read_checkpoint(claim_path) != claim:
            _fail("binding_mismatch")
        # Provide the same original deadline to cooperative evaluator objects, and guard function
        # callbacks before/after. Uncooperative in-process callbacks cannot be preempted here.
        setter = getattr(strategy.context.evaluate, "set_remaining_timeout", None)
        callback_errors: list[BaseException] = []

        def evaluate(path, contract):
            try:
                guard("openevolve_native_evaluation")
                report = strategy.context.evaluate(path, contract)
                guard("openevolve_native_after_evaluation")
                return report
            except BaseException as exc:
                callback_errors.append(exc)
                raise

        output = runtime / "evolution" / "producer-batches" / execution.intent.journal_id / "output"
        try:
            if callable(setter):
                setter(guard)
            admission = admit_producer_envelope(
                output, prepared.envelope, strategy.context.contract, evaluate,
                evaluator_fingerprint=execution.intent.evaluator_fingerprint,
                producer_fingerprint=execution.intent.producer_fingerprint, producer_id="openevolve",
                staging_root=runtime / "local-admission", num_islands=1,
            )
        except Exception:  # noqa: BLE001 - admission fixes arbitrary evaluator errors
            if callback_errors and isinstance(callback_errors[0], (SolveExecutionCancelled, SolveExecutionBudgetExceeded)):
                raise callback_errors[0]
            _fail("local_evaluation_failed")
        finally:
            if callable(setter):
                setter(strategy.context.remaining_timeout)
        if len(admission.admitted) != 1 or admission.rejected:
            _fail("local_evaluation_failed")
        seed = admission.admitted[0]
        guard("openevolve_native_admission")
        if _binding(strategy, execution) != binding or _read_checkpoint(claim_path) != claim:
            _fail("binding_mismatch")
        # Re-read the same formal attempt/material after evaluator callbacks, before publication.
        retained = recover_native_trusted_lifecycle(runtime, **_arguments(strategy, execution))
        _check_preparation(retained, execution)
        if (retained.receipt.receipt_sha256 != prepared.receipt.receipt_sha256
                or retained.envelope.envelope_sha256 != prepared.envelope.envelope_sha256):
            _fail("admission_mismatch")
        local = _checkpoint(runtime / "admission.json", {
            "protocol": _PROTOCOL, "plan_sha256": _sha(binding), "claim_sha256": claim["checkpoint_sha256"],
            "execution_receipt_sha256": prepared.receipt.receipt_sha256,
            "envelope_sha256": prepared.envelope.envelope_sha256,
            "native_admission_plan_sha256": prepared.admission_plan.digest(),
            "candidate_id": seed.candidate_id, "local_evaluator_receipt_sha256": seed.receipt.receipt_sha256,
            "seed_dependency_sha256": seed.receipt.dependency_sha256,
            "seed_environment_sha256": seed.receipt.environment_sha256,
        })
        guard("openevolve_native_publication")
        if (_binding(strategy, execution) != binding or _read_checkpoint(claim_path) != claim
                or _read_checkpoint(runtime / "admission.json") != local):
            _fail("binding_mismatch")
        final_prepared = recover_native_trusted_lifecycle(runtime, **_arguments(strategy, execution))
        _check_preparation(final_prepared, execution)
        if (final_prepared.receipt.receipt_sha256 != prepared.receipt.receipt_sha256
                or final_prepared.envelope.envelope_sha256 != prepared.envelope.envelope_sha256):
            _fail("admission_mismatch")
        candidates = strategy.archive.commit_initial_seeds(
            (seed,), state=strategy._state_payload(
                "completed", 1, error=None, best_candidate_id=seed.candidate_id,
                trusted_native_admission={"protocol": _PROTOCOL, "plan_sha256": _sha(binding),
                                          "claim_sha256": claim["checkpoint_sha256"],
                                          "admission_sha256": local["checkpoint_sha256"]},
            ), contract_sha256=strategy.context.contract.digest(),
            evaluator_fingerprint=strategy.config.evaluator_fingerprint, canonical_strategy="openevolve",
        )
        # Commit critical region: success is acknowledged before any further budget check.
        _checkpoint(runtime / "completion.json", {
            "protocol": _PROTOCOL, "admission_sha256": local["checkpoint_sha256"],
            "publication": _publication_snapshot(strategy),
        })
        strategy._observe_seed_commit(candidates)
        return _replay(strategy, execution, binding, claim, strategy.archive.read_state())
    except (EvolutionError, SolveExecutionCancelled, SolveExecutionBudgetExceeded):
        raise
    except Exception as exc:  # preserve producer/provider prose behind a fixed boundary
        raise EvolutionError("openevolve_native_evidence_invalid") from exc


__all__ = [
    "OpenEvolveNativeExecution", "openevolve_native_workspace", "prepare_openevolve_native_inputs",
]
