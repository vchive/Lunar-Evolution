"""Read-only inspection and publication of a retained acceptance observation.

This layer deliberately does not run an evaluator or contact a provider.  It reopens the
retained eight-probe workspace produced by :mod:`acceptance_runtime_binding`, reconstructs
the runtime receipt from the native preparation, and publishes a small child manifest only
after every retained byte has been checked again.
"""
from __future__ import annotations

import hashlib
import os
import re
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ._benchmark_files import BenchmarkFileError, absolute_path, read_regular_file
from ._candidate_workspace_io import DirectoryChain
from .acceptance_runtime_binding import (
    _canonical,
    _criteria,
    _registration,
    _verify_contract,
    bind_acceptance_runtime,
)
from .algorithm import AlgorithmProblemContract
from .automatic_solve_bundle import _parent, _read_preparation, validate_automatic_solve_bundle
from .candidate_evaluation_spec import strict_json
from .candidate_workspace_plan import CandidateWorkspaceError
from .evolution import EvolutionError

_SHA = re.compile(r"^[0-9a-f]{64}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_COMMIT = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{64})$")
_SCHEMA = "1"
_MANIFEST_SCOPE = "acceptance_observation_manifest"
_BINDING_SCOPE = "acceptance_observation_binding"
_MAX_JSON = 256 * 1024


class AcceptanceObservationBindingError(ValueError):
    """A bounded, provider-free observation binding failure."""

    def __init__(self, code: str) -> None:
        self.code = code if isinstance(code, str) and re.fullmatch(r"[a-z0-9_]+", code) else "invalid"
        super().__init__(self.code)


def _fail(code: str) -> None:
    raise AcceptanceObservationBindingError(code)


def _sha(value: object, code: str) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None:
        _fail(code)
    return value


def _text(value: object, pattern: re.Pattern[str], code: str) -> str:
    if type(value) is not str or pattern.fullmatch(value) is None:
        _fail(code)
    return value


def _digest(value: bytes, expected: object, code: str) -> str:
    if not isinstance(value, bytes) or hashlib.sha256(value).hexdigest() != expected:
        _fail(code)
    return hashlib.sha256(value).hexdigest()


def _json_bytes(value: object, code: str = "observation_json_invalid") -> bytes:
    try:
        result = _canonical(value)  # runtime binder's bounded canonical encoder
    except Exception as exc:
        raise AcceptanceObservationBindingError(code) from exc
    if len(result) > _MAX_JSON:
        _fail(code)
    return result


def _load_canonical(path: Path, code: str) -> tuple[dict[str, Any], bytes]:
    try:
        raw = read_regular_file(path, _MAX_JSON, exact_size=False)
        value = strict_json(raw, maximum=_MAX_JSON)
    except Exception as exc:
        if isinstance(exc, AcceptanceObservationBindingError):
            raise
        _fail(code)
    if not isinstance(value, dict):
        _fail(code)
    if _json_bytes(value) != raw:
        _fail(f"{code}_noncanonical")
    return value, raw


def _material(reg: Mapping[str, Any], materials: Mapping[str, bytes], field: str, code: str) -> bytes:
    descriptor = reg.get(field)
    if not isinstance(descriptor, Mapping) or set(descriptor) != {"path", "size", "sha256"}:
        _fail(code)
    path, size, digest = descriptor.get("path"), descriptor.get("size"), descriptor.get("sha256")
    raw = materials.get(path) if isinstance(path, str) else None
    if not isinstance(raw, bytes) or type(size) is not int or size != len(raw) or hashlib.sha256(raw).hexdigest() != digest:
        _fail(code)
    return raw


def _receipt_digest(receipt: Mapping[str, Any]) -> str:
    if not isinstance(receipt, Mapping) or "binding_sha256" not in receipt:
        _fail("runtime_receipt_schema_invalid")
    digest = _sha(receipt.get("binding_sha256"), "runtime_receipt_digest_invalid")
    payload = {key: value for key, value in receipt.items() if key != "binding_sha256"}
    if hashlib.sha256(_json_bytes(payload)).hexdigest() != digest:
        _fail("runtime_receipt_digest_mismatch")
    return digest


def _prepared_event(store: Any, parent_id: str, parent: Any) -> tuple[dict[str, Any], str]:
    try:
        events = [item for item in store.list_events(parent_id) if item.get("type") == "bundle_profile_prepared"]
    except Exception as exc:
        raise AcceptanceObservationBindingError("prepared_event_invalid") from exc
    if len(events) != 1 or not isinstance(events[0].get("payload"), dict):
        _fail("prepared_event_invalid")
    payload = events[0]["payload"]
    return payload, hashlib.sha256(_json_bytes(payload)).hexdigest()


def _read_probe_rows(reg: Mapping[str, Any], materials: Mapping[str, bytes], workspace: Path) -> tuple[dict[str, Any], ...]:
    pins = reg.get("holdout_pins")
    if not isinstance(pins, list) or len(pins) != 8:
        _fail("probe_pins_invalid")
    rows: list[dict[str, Any]] = []
    for ordinal, pin in enumerate(pins):
        if not isinstance(pin, Mapping) or pin.get("ordinal") != ordinal:
            _fail("probe_pins_invalid")
        item = workspace / f"{ordinal:02d}"
        try:
            snapshot = read_regular_file(item / "snapshot.bin", pin["input"]["size"], exact_size=True)
            expected_raw = read_regular_file(item / "expected.json", pin["expected"]["size"], exact_size=True)
            actual = read_regular_file(item / "actual.json", _MAX_JSON, exact_size=False)
            evidence_raw = read_regular_file(item / "evidence.json", _MAX_JSON, exact_size=False)
        except BenchmarkFileError as exc:
            code = "retained_probe_missing" if exc.reason == "missing" else "retained_probe_mismatch"
            raise AcceptanceObservationBindingError(code) from exc
        except Exception as exc:
            raise AcceptanceObservationBindingError("retained_probe_mismatch") from exc
        if (not isinstance(pin.get("input"), Mapping) or not isinstance(pin.get("expected"), Mapping)
                or hashlib.sha256(snapshot).hexdigest() != pin["input"].get("sha256")
                or hashlib.sha256(expected_raw).hexdigest() != pin["expected"].get("sha256")):
            _fail("retained_probe_mismatch")
        try:
            evidence = strict_json(evidence_raw, maximum=_MAX_JSON)
            projection = evidence["projection"] if isinstance(evidence, dict) else None
            if not isinstance(evidence, dict) or not isinstance(projection, Mapping):
                _fail("retained_probe_invalid")
            if _json_bytes(projection) != actual:
                _fail("retained_probe_mismatch")
            if _json_bytes(evidence) != evidence_raw:
                _fail("retained_probe_noncanonical")
        except AcceptanceObservationBindingError:
            raise
        except Exception as exc:
            raise AcceptanceObservationBindingError("retained_probe_invalid") from exc
        rows.append({
            "ordinal": ordinal,
            "holdout_id": pin.get("holdout_id"),
            "input_sha256": hashlib.sha256(snapshot).hexdigest(),
            "expected_output_sha256": hashlib.sha256(expected_raw).hexdigest(),
            "actual_output_sha256": hashlib.sha256(actual).hexdigest(),
            "outcome": "passed",
            "evidence": evidence,
        })
    return tuple(rows)


def _check_tree(workspace: Path) -> None:
    """Reject links/replacements and unexpected entries in the retained probe tree."""
    try:
        root = os.stat(workspace, follow_symlinks=False)
        if not stat.S_ISDIR(root.st_mode):
            _fail("binding_workspace_invalid")
        expected_root = {*(f"{n:02d}" for n in range(8)), "binding-receipt.json", "observation"}
        with os.scandir(workspace) as entries:
            seen = set()
            for entry in entries:
                if entry.name not in expected_root or entry.name in seen:
                    _fail("retained_tree_changed")
                seen.add(entry.name)
                info = entry.stat(follow_symlinks=False)
                if entry.name == "binding-receipt.json":
                    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                            or stat.S_IMODE(info.st_mode) != 0o600):
                        _fail("retained_tree_changed")
                elif entry.name == "observation":
                    if not stat.S_ISDIR(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o700:
                        _fail("retained_tree_changed")
                    with os.scandir(workspace / "observation") as child_entries:
                        child_seen = set()
                        for child in child_entries:
                            if child.name not in {"manifest.json", "binding.json"} or child.name in child_seen:
                                _fail("retained_tree_changed")
                            child_seen.add(child.name)
                            child_info = child.stat(follow_symlinks=False)
                            if (not stat.S_ISREG(child_info.st_mode) or child_info.st_nlink != 1
                                    or stat.S_IMODE(child_info.st_mode) != 0o600):
                                _fail("retained_tree_changed")
                elif not stat.S_ISDIR(info.st_mode):
                    _fail("retained_tree_changed")
    except AcceptanceObservationBindingError:
        raise
    except (OSError, ValueError) as exc:
        raise AcceptanceObservationBindingError("retained_tree_changed") from exc


def _prepare(registration: Mapping[str, Any], *, store: Any, parent_id: str, materials: Mapping[str, bytes], contract: AlgorithmProblemContract):
    reg = _registration(registration)
    if not isinstance(materials, Mapping) or not isinstance(parent_id, str) or not isinstance(contract, AlgorithmProblemContract):
        _fail("observation_wrapper_invalid")
    try:
        validate_automatic_solve_bundle(store, parent_id)
        parent, prepared_contract = _parent(store, parent_id)
        if prepared_contract is None or prepared_contract.digest() != contract.digest():
            _fail("prepared_contract_mismatch")
        pipeline, bundle, profile_raw, _ = _read_preparation(store, parent, contract)
    except AcceptanceObservationBindingError:
        raise
    except (EvolutionError, AttributeError, KeyError, OSError, TypeError, ValueError, RecursionError) as exc:
        raise AcceptanceObservationBindingError("prepared_binding_invalid") from exc
    task = _material(reg, materials, "task_material", "material_binding_invalid")
    input_bytes = _material(reg, materials, "input_material", "material_binding_invalid")
    evaluator = _material(reg, materials, "evaluator_material", "material_binding_invalid")
    profile_criteria = _material(reg, materials, "evaluator_profile_material", "material_binding_invalid")
    if parent.goal.encode("utf-8") != task:
        _fail("parent_task_material_mismatch")
    criteria, _ = _criteria(evaluator, profile_criteria, reg)
    _verify_contract(contract, criteria)
    event, event_digest = _prepared_event(store, parent_id, parent)
    return reg, parent, pipeline, bundle, profile_raw, task, input_bytes, evaluator, profile_criteria, event, event_digest


def inspect_acceptance_observation_binding(
    registration: Mapping[str, Any], *, store: Any, parent_id: str,
    materials: Mapping[str, bytes], contract: AlgorithmProblemContract,
    workspace: Path, check_active: Any = None, remaining_timeout: Any = None,
) -> dict[str, Any]:
    """Reopen and verify a completed retained binding without running probes."""
    del check_active, remaining_timeout  # inspection itself has no execution phase
    try:
        root = absolute_path(workspace)
        _check_tree(root)
        reg, _parent_run, pipeline, bundle, profile_raw, task, input_bytes, evaluator, profile_criteria, _event, event_digest = _prepare(
            registration, store=store, parent_id=parent_id, materials=materials, contract=contract,
        )
        receipt, receipt_raw = _load_canonical(root / "binding-receipt.json", "runtime_receipt")
        _receipt_digest(receipt)
        rows = _read_probe_rows(reg, materials, root)
        rebuilt = bind_acceptance_runtime(
            reg, task_bytes=task, input_bytes=input_bytes, evaluator_criteria_bytes=evaluator,
            profile_criteria_bytes=profile_criteria, contract=contract, pipeline=pipeline, bundle=bundle,
            profile_bytes=profile_raw, materials=materials, probe_results=rows,
        )
        expected_receipt = {
            **rebuilt, "parent_run_id": parent_id, "prepared_event_sha256": event_digest,
        }
        expected_receipt["binding_sha256"] = hashlib.sha256(_json_bytes({
            key: value for key, value in expected_receipt.items() if key != "binding_sha256"
        })).hexdigest()
        if receipt != expected_receipt or _json_bytes(receipt) != receipt_raw:
            _fail("runtime_receipt_mismatch")
        manifest_payload = {
            "schema_version": _SCHEMA, "scope": _MANIFEST_SCOPE,
            "registration_id": reg["registration_id"], "campaign_id": reg["campaign_id"],
            "attempt_id": reg["attempt_id"], "product_commit": reg["product_commit"],
            "campaign_root": reg["campaign_root"], "task_sha256": reg["task_sha256"],
            "input_sha256": reg["input_sha256"], "evaluator_sha256": reg["evaluator_sha256"],
            "provider": reg["provider"], "model": reg["model"], "runtime": reg["runtime"],
            "budgets": dict(reg["budgets"]), "parent_run_id": parent_id,
            "prepared_event_sha256": event_digest, "runtime_binding_sha256": receipt["binding_sha256"],
            "contract_sha256": receipt["contract_sha256"], "input_table_sha256": receipt["input_table_sha256"],
            "harness_sha256": receipt["harness_sha256"], "runtime_profile_sha256": receipt["runtime_profile_sha256"],
            "runtime_input_profile_sha256": receipt["runtime_input_profile_sha256"],
            "evaluator_bundle_sha256": receipt["evaluator_bundle_sha256"], "status": "criteria_bound",
        }
        manifest_payload_bytes = _json_bytes(manifest_payload)
        manifest = {**manifest_payload, "manifest_sha256": hashlib.sha256(manifest_payload_bytes).hexdigest()}
        binding_payload = {
            "schema_version": _SCHEMA, "scope": _BINDING_SCOPE, "status": "criteria_bound",
            "registration_id": reg["registration_id"], "campaign_id": reg["campaign_id"],
            "attempt_id": reg["attempt_id"], "registration_sha256": reg["registration_sha256"],
            "parent_run_id": parent_id, "prepared_event_sha256": event_digest,
            "runtime_binding_sha256": receipt["binding_sha256"], "manifest_sha256": manifest["manifest_sha256"],
            "contract_sha256": receipt["contract_sha256"], "input_table_sha256": receipt["input_table_sha256"],
            "harness_sha256": receipt["harness_sha256"],
        }
        binding = {**binding_payload, "observation_binding_sha256": hashlib.sha256(_json_bytes(binding_payload)).hexdigest()}
        return {"manifest": manifest, "binding": binding, "runtime_receipt": receipt}
    except AcceptanceObservationBindingError:
        raise
    except (OSError, TypeError, ValueError, RecursionError) as exc:
        raise AcceptanceObservationBindingError("observation_inspection_failed") from exc


def _write_create_only(parent_fd: int, name: str, content: bytes) -> None:
    try:
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=parent_fd)
    except OSError as exc:
        raise AcceptanceObservationBindingError("observation_publish_conflict") from exc
    try:
        view = memoryview(content)
        while view:
            count = os.write(fd, view)
            if count <= 0:
                _fail("observation_publish_failed")
            view = view[count:]
        os.fsync(fd)
        info = os.fstat(fd)
        named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISREG(named.st_mode) or named.st_nlink != 1 or (named.st_dev, named.st_ino) != (info.st_dev, info.st_ino) or named.st_size != len(content):
            _fail("observation_publish_changed")
    except OSError as exc:
        raise AcceptanceObservationBindingError("observation_publish_failed") from exc
    finally:
        os.close(fd)


def publish_acceptance_observation_binding(
    registration: Mapping[str, Any], *, store: Any, parent_id: str,
    materials: Mapping[str, bytes], contract: AlgorithmProblemContract,
    workspace: Path, check_active: Any = None, remaining_timeout: Any = None,
) -> dict[str, Any]:
    """Publish ``workspace/observation`` create-only after a final read-only inspection."""
    result = inspect_acceptance_observation_binding(
        registration, store=store, parent_id=parent_id, materials=materials, contract=contract,
        workspace=workspace, check_active=check_active, remaining_timeout=remaining_timeout,
    )
    root = absolute_path(workspace)
    try:
        parent_chain = DirectoryChain(root, "observation_workspace_changed")
        try:
            try:
                os.mkdir("observation", 0o700, dir_fd=parent_chain.fd)
            except FileExistsError as exc:
                raise AcceptanceObservationBindingError("observation_publish_conflict") from exc
            except OSError as exc:
                raise AcceptanceObservationBindingError("observation_publish_failed") from exc
            os.fsync(parent_chain.fd)
            if check_active is not None:
                check_active()
            if remaining_timeout is not None:
                value = remaining_timeout("observation-publish")
                if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
                    _fail("observation_deadline_exceeded")
            child = DirectoryChain(root / "observation", "observation_workspace_changed")
            try:
                _write_create_only(child.fd, "manifest.json", _json_bytes(result["manifest"]))
                os.fsync(child.fd)
                if check_active is not None:
                    check_active()
                if remaining_timeout is not None:
                    value = remaining_timeout("observation-binding")
                    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
                        _fail("observation_deadline_exceeded")
                # Reinspect the retained parent before the binding (last) file is published.
                verify = inspect_acceptance_observation_binding(
                    registration, store=store, parent_id=parent_id, materials=materials, contract=contract,
                    workspace=workspace, check_active=check_active, remaining_timeout=remaining_timeout,
                )
                if verify["manifest"] != result["manifest"] or verify["binding"] != result["binding"]:
                    _fail("observation_reinspection_mismatch")
                _write_create_only(child.fd, "binding.json", _json_bytes(result["binding"]))
                os.fsync(child.fd)
                child.check()
                if read_regular_file(root / "observation/manifest.json", _MAX_JSON) != _json_bytes(result["manifest"]):
                    _fail("observation_publish_changed")
                if read_regular_file(root / "observation/binding.json", _MAX_JSON) != _json_bytes(result["binding"]):
                    _fail("observation_publish_changed")
            finally:
                child.close()
        finally:
            parent_chain.close()
        return result
    except AcceptanceObservationBindingError:
        raise
    except (CandidateWorkspaceError, OSError, TypeError, ValueError, RecursionError) as exc:
        raise AcceptanceObservationBindingError("observation_publish_failed") from exc


__all__ = [
    "AcceptanceObservationBindingError", "inspect_acceptance_observation_binding",
    "publish_acceptance_observation_binding",
]
