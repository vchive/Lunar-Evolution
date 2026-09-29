"""Read-only native evidence for the automatic-solve WorkerService bridge.

The WorkerService result is only an observation of a native automatic Run.  This module is the
bridge's evidence reader: it reopens the native request, runtime, reciprocal child, retained
delivery and process-cleanup records without starting a solver, evaluator, publisher or cleanup
operation.  A result reference is deliberately a digest-only projection; the native bytes stay
in the Run workspace and Store evidence.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

from ._candidate_workspace_io import DirectoryChain
from .automatic_solve_worker_binding import (
    AutomaticSolveWorkerBinding,
    AutomaticSolveWorkerBindingState,
    AutomaticSolveWorkerResultReference,
)
from .candidate_evaluation_spec import canonical_json
from .models import RunStatus

_SCHEMA = "1"
_KIND = "lunar-native-result-reference"
_MAX_REFERENCE_BYTES = 12 * 1024
_TERMINAL = {RunStatus.SUCCEEDED.value, RunStatus.FAILED.value, RunStatus.CANCELLED.value}
_HEX = set("0123456789abcdef")


class NativeResultReferenceError(ValueError):
    """A fixed, path-free failure for incomplete or changed native evidence."""

    _CODES = frozenset({
        "invalid", "binding", "request", "runtime", "workspace", "contract", "child",
        "terminal", "delivery", "artifact", "cleanup", "reference",
    })

    def __init__(self, code: str = "invalid") -> None:
        suffix = code.removeprefix("automatic_solve_native_result_") if isinstance(code, str) else ""
        self.code = "automatic_solve_native_result_" + (suffix if suffix in self._CODES else "invalid")
        super().__init__(self.code)


def _fail(code: str = "invalid") -> None:
    raise NativeResultReferenceError(code)


def _digest(value: object, *, maximum: int = _MAX_REFERENCE_BYTES) -> str:
    try:
        raw = canonical_json(value, maximum=maximum)
    except Exception as exc:
        _fail("reference")
        raise AssertionError from exc
    return hashlib.sha256(raw).hexdigest()


def _sha_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _safe_text(value: object, *, maximum: int = 512) -> str:
    if type(value) is not str or not value or "\x00" in value or len(value.encode("utf-8")) > maximum:
        _fail("reference")
    return value


def _canonical_event(event: dict[str, object]) -> str:
    if type(event) is not dict:
        _fail("terminal")
    try:
        return _sha_bytes(canonical_json(event, maximum=128 * 1024))
    except Exception as exc:
        _fail("terminal")
        raise AssertionError from exc


def _one_event(controller: Any, run_id: str, event_type: str) -> dict[str, object] | None:
    rows = [event for event in controller.store.list_events(run_id) if event.get("type") == event_type]
    if len(rows) > 1:
        _fail("terminal")
    if not rows:
        return None
    payload = rows[0].get("payload")
    if not isinstance(payload, dict):
        _fail("terminal")
    # Hash the complete event, including its immutable id/type/task binding.
    return {key: rows[0][key] for key in rows[0]}


def _request_runtime_workspace(controller: Any, binding: AutomaticSolveWorkerBinding, run: Any, chain: DirectoryChain) -> dict[str, object]:
    if run is None or run.id != binding.run_id:
        _fail("binding")
    if binding.state is AutomaticSolveWorkerBindingState.UNKNOWN:
        _fail("binding")
    try:
        from .cli import _compiler_fingerprint, _conversation_manifest

        workspace = Path(run.workspace)
        if str(workspace) != binding.workspace_identity:
            _fail("workspace")
        requests = [event.get("payload") for event in controller.store.list_events(run.id)
                    if event.get("type") == "evolution_requested"]
        if len(requests) != 1 or type(requests[0]) is not dict:
            _fail("request")
        request = requests[0]
        policy = json.loads(binding.normalized_policy())
        if type(policy) is not dict:
            _fail("request")
        wrapped = set(policy) == {"native_request", "worker_active_timeout", "manifest_sha256"}
        if not wrapped and set(policy) != set(request):
            _fail("request")
        if wrapped:
            native_request = policy["native_request"]
            timeout = policy["worker_active_timeout"]
            manifest_pin = policy["manifest_sha256"]
            if type(native_request) is not dict or (timeout is not None and (
                    isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                    or not math.isfinite(float(timeout)) or timeout <= 0 or timeout > 24 * 60 * 60)):
                _fail("request")
            if manifest_pin is not None and (
                    type(manifest_pin) is not str or len(manifest_pin) != 64
                    or any(char not in _HEX for char in manifest_pin)):
                _fail("request")
            manifest = _conversation_manifest(run)
            observed_manifest = _digest(manifest, maximum=512 * 1024) if manifest is not None else None
            if observed_manifest != manifest_pin:
                _fail("runtime")
        else:
            native_request, timeout, manifest_pin = policy, None, None
        if (type(native_request.get("automatic_lifecycle_version")) is not int
                or native_request.get("automatic_lifecycle_version") != 1 or native_request.get("bundle_mode") != "compiled"
                or _digest(native_request, maximum=16 * 1024) != binding.lifecycle_digest
                or _digest(request, maximum=16 * 1024) != binding.lifecycle_digest):
            _fail("request")
        if _compiler_fingerprint(controller.runtime) != binding.runtime_fingerprint:
            _fail("runtime")
    except NativeResultReferenceError:
        raise
    except Exception as exc:
        _fail("request")
        raise AssertionError from exc
    chain.check()
    opened = os.fstat(chain.fd)
    return {
        "lifecycle_digest": binding.lifecycle_digest,
        "runtime_fingerprint": binding.runtime_fingerprint,
        "manifest_sha256": manifest_pin,
        "worker_active_timeout": timeout,
        "workspace": {
            "sha256": _digest(str(workspace), maximum=8 * 1024),
            "device": int(opened.st_dev),
            "inode": int(opened.st_ino),
        },
    }


def _contract_and_child(controller: Any, binding: AutomaticSolveWorkerBinding, parent: Any):
    try:
        contract = controller._algorithm_contract(parent)
    except Exception as exc:
        _fail("contract")
        raise AssertionError from exc
    if binding.contract_digest is not None and (contract is None or contract.digest() != binding.contract_digest):
        _fail("contract")
    links = [event.get("payload") for event in controller.store.list_events(parent.id)
             if event.get("type") == "evolution_linked"]
    if len(links) > 1 or any(not isinstance(item, dict) for item in links):
        _fail("child")
    if links and set(links[0]) != {"evolution_run_id", "contract_sha256", "strategy"}:
        _fail("child")
    if links and (type(links[0]["evolution_run_id"]) is not str or not links[0]["evolution_run_id"]):
        _fail("child")
    child_id = links[0].get("evolution_run_id") if links else None
    if child_id is not None:
        if not isinstance(child_id, str) or child_id == parent.id or binding.child_run_id != child_id:
            _fail("child")
        if contract is None or binding.contract_digest is None or links[0] != {
            "evolution_run_id": child_id, "contract_sha256": contract.digest(), "strategy": "population",
        }:
            _fail("child")
        child = controller.store.get_run(child_id)
        reverse = [] if child is None else [event.get("payload") for event in controller.store.list_events(child.id)
                                             if event.get("type") == "evolution_parent_linked"]
        if child is None or reverse != [{"parent_run_id": parent.id, "contract_sha256": contract.digest()}]:
            _fail("child")
    elif binding.child_run_id is not None:
        _fail("child")
    else:
        child = None
    return contract, child


def _terminal_event(controller: Any, run: Any) -> tuple[str, dict[str, object]]:
    if run.status.value not in _TERMINAL or controller.store.pending_input(run.id) is not None:
        _fail("terminal")
    event_type = "run_" + run.status.value
    event = _one_event(controller, run.id, event_type)
    if event is None and run.status is RunStatus.FAILED:
        event_type = "budget_exceeded"
        event = _one_event(controller, run.id, event_type)
    if event is None:
        _fail("terminal")
    return event_type, event


def _child_terminal(controller: Any, parent: Any, child: Any) -> dict[str, object] | None:
    if child is None:
        return None
    expected = Path(parent.workspace) / "evolution-run"
    if Path(child.workspace) != expected:
        _fail("child")
    held = None
    try:
        held = DirectoryChain(expected, "automatic_solve_native_result_child")
        info = os.fstat(held.fd)
        event_type, event = _terminal_event(controller, child)
        result = {
            "status": child.status.value,
            "terminal_event": event_type,
            "terminal_event_sha256": _canonical_event(event),
            "workspace": {
                "sha256": _digest(str(expected), maximum=8 * 1024),
                "device": int(info.st_dev), "inode": int(info.st_ino),
            },
        }
        held.check()
        return result
    except NativeResultReferenceError:
        raise
    except Exception as exc:
        raise NativeResultReferenceError("child") from exc
    finally:
        if held is not None:
            held.close()


def _artifact_digest(controller: Any, run_ids: tuple[str, ...]) -> tuple[str, int]:
    rows: list[dict[str, object]] = []
    for run_id in run_ids:
        for row in controller.store.list_artifacts(run_id):
            if type(row) is not dict:
                _fail("artifact")
            path, digest, size, kind = row.get("path"), row.get("sha256"), row.get("size"), row.get("kind")
            if (type(path) is not str or not path or len(path.encode()) > 512
                    or type(digest) is not str or len(digest) != 64 or any(c not in _HEX for c in digest)
                    or type(size) is not int or size < 0 or type(kind) is not str or len(kind.encode()) > 256):
                _fail("artifact")
            rows.append({"run_id": run_id, "path": path, "sha256": digest, "size": size, "kind": kind})
    if len(rows) > 4096:
        _fail("artifact")
    rows.sort(key=lambda item: (item["run_id"], item["path"], item["kind"], item["sha256"], item["size"]))
    return _digest(rows, maximum=256 * 1024), len(rows)


def _cleanup(controller: Any, binding: AutomaticSolveWorkerBinding, run_ids: tuple[str, ...]) -> dict[str, int]:
    for run_id in run_ids:
        run = controller.store.get_run(run_id)
        if run is None or (run.runner_pid, run.runner_pgid) != (None, None):
            _fail("cleanup")
        try:
            if controller.store.list_attempt_processes(run_id):
                _fail("cleanup")
        except Exception as exc:
            _fail("cleanup")
            raise AssertionError from exc
    try:
        worker_processes = controller.store.list_worker_processes(
            binding.worker_id, binding.worker_attempt_id, binding.service_owner_id,
        )
    except Exception as exc:
        _fail("cleanup")
        raise AssertionError from exc
    if worker_processes:
        _fail("cleanup")
    return {"native_attempt_processes": 0, "worker_processes": 0}


def _read_success_delivery(controller: Any, binding: AutomaticSolveWorkerBinding, parent: Any, child: Any, contract: Any) -> dict[str, object]:
    if child is None or contract is None or binding.contract_digest is None:
        _fail("delivery")
    if parent.status is not RunStatus.SUCCEEDED or child.status is not RunStatus.SUCCEEDED:
        _fail("delivery")
    try:
        from . import bundle_parent_delivery as bundle
        from . import output_publication as publication

        # These are the pure validation primitives of inspect_bundle_parent_delivery.  Its
        # recover_output_batch(reconcile=False) wrapper still creates a missing .lock, so use
        # the read-only journal inspector directly; never acquire publication authority here.
        parent, child, identity, materials, result, owner = bundle._validated(
            controller, parent.id, child.id, contract,
        )
        copied = bundle._prepared(controller, parent, child, identity, materials)
        if copied is None:
            _fail("delivery")
        terminal = bundle._event(controller, parent, child, bundle._TERMINAL)
        prepared = bundle._outputs(controller, parent, contract, materials, check_targets=False)
        specs = tuple(spec for spec, _ in prepared)
        root = publication._root(parent)
        directory = publication._confined(root, f"{publication._ROOT}/{publication._key(parent.id, child.id)}")
        if not publication._present(directory):
            publication._require_no_output_evidence(controller.store, parent, child.id)
            if prepared:
                _fail("delivery")
            outputs = ()
        else:
            held = DirectoryChain(directory, "automatic_solve_native_result_delivery")
            try:
                journal, journal_sha256 = publication._load(directory, parent, child.id, specs)
                metadata = [{key: value for key, value in entry["output"].items() if key != "artifact_id"}
                            for entry in journal["entries"]]
                if canonical_json(metadata) != canonical_json(bundle._output_metadata(prepared)):
                    _fail("delivery")
                status, outputs = publication._inspect_batch(controller.store, parent, child.id, specs, directory)
                if status != "committed":
                    _fail("delivery")
                if publication._load(directory, parent, child.id, specs)[1] != journal_sha256:
                    _fail("delivery")
                held.check()
            finally:
                held.close()
        expected = bundle._payload(parent, child, identity, result, copied, outputs)
        if terminal is None or canonical_json(terminal, maximum=128 * 1024) != canonical_json(expected, maximum=128 * 1024):
            _fail("delivery")
        bundle._artifacts(controller, parent, owner, copied, materials, register=False)
    except Exception as exc:
        _fail("delivery")
        raise AssertionError from exc
    if not isinstance(terminal, dict):
        _fail("delivery")
    required = {"receipt_sha256", "bundle_sha256", "evaluation_sha256", "candidate_id"}
    if any(key not in identity for key in required):
        _fail("delivery")
    outputs = terminal.get("outputs")
    if not isinstance(outputs, list) or len(outputs) > 64:
        _fail("delivery")
    return {
        "candidate_id": _safe_text(identity["candidate_id"], maximum=256),
        "bundle_sha256": identity["bundle_sha256"],
        "receipt_sha256": identity["receipt_sha256"],
        "evaluation_sha256": identity["evaluation_sha256"],
        "delivery_sha256": terminal["delivery_sha256"],
        "terminal_event_sha256": _canonical_event(_one_event(controller, parent.id, "bundle_candidate_delivered") or {}),
        "outputs_count": len(outputs),
    }


def _capture(controller: Any, binding: AutomaticSolveWorkerBinding, chain: DirectoryChain) -> dict[str, object]:
    parent = controller.store.get_run(binding.run_id)
    pins = _request_runtime_workspace(controller, binding, parent, chain)
    contract, child = _contract_and_child(controller, binding, parent)
    outcome = parent.status.value
    terminal_type, terminal_event = _terminal_event(controller, parent)
    child_terminal = _child_terminal(controller, parent, child)
    run_ids = (parent.id,) + ((child.id,) if child is not None else ())
    cleanup = _cleanup(controller, binding, run_ids)
    artifact_sha256, artifact_count = _artifact_digest(controller, run_ids)
    delivery = None
    if outcome == RunStatus.SUCCEEDED.value:
        delivery = _read_success_delivery(controller, binding, parent, child, contract)
    reference = {
        "schema_version": _SCHEMA,
        "kind": _KIND,
        "binding": {
            "binding_id": binding.binding_id, "generation": binding.generation,
            "run_id": binding.run_id, "worker_attempt_id": binding.worker_attempt_id,
        },
        "outcome": outcome,
        **pins,
        "native": {
            "status": parent.status.value,
            "child_run_id": child.id if child is not None else None,
            "child": child_terminal,
            "contract_digest": contract.digest() if contract is not None else None,
            "terminal_event": terminal_type,
            "terminal_event_sha256": _canonical_event(terminal_event),
            "artifact_manifest_sha256": artifact_sha256,
            "artifact_count": artifact_count,
            "delivery": delivery,
        },
        "cleanup": cleanup,
    }
    try:
        canonical_json(reference, maximum=_MAX_REFERENCE_BYTES)
    except Exception as exc:
        _fail("reference")
        raise AssertionError from exc
    return reference


def _validate_reference_shape(candidate: object, binding: AutomaticSolveWorkerBinding) -> dict[str, object]:
    if type(candidate) is not dict:
        _fail("reference")
    expected_binding = {
        "binding_id": binding.binding_id, "generation": binding.generation,
        "run_id": binding.run_id, "worker_attempt_id": binding.worker_attempt_id,
    }
    if (candidate.get("schema_version") != _SCHEMA or candidate.get("kind") != _KIND
            or candidate.get("binding") != expected_binding
            or candidate.get("outcome") not in _TERMINAL):
        _fail("reference")
    native = candidate.get("native")
    if type(native) is not dict or native.get("status") != candidate.get("outcome"):
        _fail("reference")
    for key in ("terminal_event_sha256", "artifact_manifest_sha256"):
        value = native.get(key)
        if type(value) is not str or len(value) != 64 or any(char not in _HEX for char in value):
            _fail("reference")
    for key in ("lifecycle_digest", "runtime_fingerprint"):
        value = candidate.get(key)
        if value != getattr(binding, "lifecycle_digest" if key == "lifecycle_digest" else "runtime_fingerprint"):
            _fail("reference")
    workspace = candidate.get("workspace")
    if (type(workspace) is not dict or type(workspace.get("sha256")) is not str
            or len(workspace["sha256"]) != 64 or any(char not in _HEX for char in workspace["sha256"])
            or type(workspace.get("device")) is not int or type(workspace.get("inode")) is not int):
        _fail("reference")
    cleanup = candidate.get("cleanup")
    if cleanup != {"native_attempt_processes": 0, "worker_processes": 0}:
        _fail("reference")
    delivery = native.get("delivery")
    if candidate["outcome"] == RunStatus.SUCCEEDED.value:
        if type(delivery) is not dict:
            _fail("reference")
        for key in ("bundle_sha256", "receipt_sha256", "evaluation_sha256", "delivery_sha256", "terminal_event_sha256"):
            value = delivery.get(key)
            if type(value) is not str or len(value) != 64 or any(char not in _HEX for char in value):
                _fail("reference")
        if type(delivery.get("outputs_count")) is not int or delivery["outputs_count"] < 0:
            _fail("reference")
    elif delivery is not None:
        _fail("reference")
    try:
        canonical_json(candidate, maximum=_MAX_REFERENCE_BYTES)
    except Exception as exc:
        _fail("reference")
        raise AssertionError from exc
    return candidate


def capture_native_result(controller: Any, binding: AutomaticSolveWorkerBinding) -> dict[str, object]:
    """Capture a bounded native result reference without executing or mutating anything."""
    if not isinstance(binding, AutomaticSolveWorkerBinding):
        _fail("binding")
    chain = None
    try:
        workspace = Path(binding.workspace_identity)
        if not workspace.is_absolute():
            _fail("workspace")
        chain = DirectoryChain(workspace, "automatic_solve_native_result_workspace")
        result = _capture(controller, binding, chain)
        # Terminal inspection cannot produce a coherent reference if Store pins/status/process
        # evidence changed during the byte reads.  Recheck the cheap durable observations.
        parent = controller.store.get_run(binding.run_id)
        if parent is None or parent.status.value != result["outcome"]:
            _fail("terminal")
        # Recheck every durable request/runtime pin captured above, including the active
        # timeout and conversation-manifest pin carried by the adapter's wrapped policy.
        if _request_runtime_workspace(controller, binding, parent, chain) != {
            key: result[key] for key in (
                "lifecycle_digest",
                "runtime_fingerprint",
                "manifest_sha256",
                "worker_active_timeout",
                "workspace",
            )
        }:
            _fail("reference")
        _contract, child = _contract_and_child(controller, binding, parent)
        run_ids = (parent.id,) + ((child.id,) if child is not None else ())
        _cleanup(controller, binding, run_ids)
        native = result["native"]
        if (_artifact_digest(controller, run_ids) != (native["artifact_manifest_sha256"], native["artifact_count"])
                or _child_terminal(controller, parent, child) != native["child"]
                or _canonical_event(_one_event(controller, parent.id, native["terminal_event"]) or {}) != native["terminal_event_sha256"]):
            _fail("reference")
        chain.check()
        return result
    except NativeResultReferenceError:
        raise
    except Exception as exc:
        raise NativeResultReferenceError("invalid") from exc
    finally:
        if chain is not None:
            chain.close()


def validate_native_result(
    controller: Any,
    binding: AutomaticSolveWorkerBinding,
    reference: dict[str, object] | AutomaticSolveWorkerResultReference,
) -> dict[str, object]:
    """Reopen and compare native evidence; returns the freshly verified reference."""
    if isinstance(reference, AutomaticSolveWorkerResultReference):
        if (reference.binding_id, reference.generation, reference.run_id, reference.worker_attempt_id) != (
            binding.binding_id, binding.generation, binding.run_id, binding.worker_attempt_id,
        ):
            _fail("reference")
        if reference.outcome not in _TERMINAL:
            _fail("reference")
        try:
            rebuilt = AutomaticSolveWorkerResultReference(
                binding_id=reference.binding_id, generation=reference.generation,
                run_id=reference.run_id, worker_attempt_id=reference.worker_attempt_id,
                outcome=reference.outcome, reference=dict(reference.reference),
                sha256=reference.sha256, created_at=reference.created_at,
            )
            if rebuilt.outcome != rebuilt.reference.get("outcome"):
                _fail("reference")
        except Exception as exc:
            _fail("reference")
            raise AssertionError from exc
        candidate = rebuilt.reference
    elif type(reference) is dict:
        candidate = reference
    else:
        _fail("reference")
    _validate_reference_shape(candidate, binding)
    current = capture_native_result(controller, binding)
    if canonical_json(candidate, maximum=_MAX_REFERENCE_BYTES) != canonical_json(current, maximum=_MAX_REFERENCE_BYTES):
        _fail("reference")
    return current


__all__ = ["NativeResultReferenceError", "capture_native_result", "validate_native_result"]
