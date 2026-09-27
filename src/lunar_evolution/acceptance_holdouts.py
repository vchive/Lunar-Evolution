"""Execute the eight preregistered acceptance snapshot holdouts exactly once.

This runner is intentionally provider-free.  It consumes the immutable material bytes pinned by
the registration, invokes the frozen native snapshot evaluator once per ordinal, and returns
detached rows suitable for a later holdout receipt writer.  It never retries a probe or upgrades
unknown cleanup/process observations to success.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import stat
from collections.abc import Mapping
from contextlib import ExitStack
from pathlib import Path
from typing import Any

from ._benchmark_files import BenchmarkFileError, absolute_path
from ._candidate_workspace_io import DirectoryChain
from .acceptance_probes import AcceptanceSnapshotEvidence, _expected, run_acceptance_snapshot_probe
from .algorithm import AlgorithmProblemContract
from .candidate_workspace_plan import CandidateWorkspaceError
from .evaluator_bundle import EvaluatorProbe, ProbeFile


class AcceptanceHoldoutError(ValueError):
    """A fixed malformed holdout batch or material failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


_FIXED_HOLDOUT_PAIRS = ((1, -1), (1, 0), (1, 1), (1, 2), (3, 0), (3, 2), (3, 3), (3, 4))


def _fixed_holdout_name(limit: int, value: int) -> str:
    return f"limit-{limit}-value-{'minus-' if value < 0 else ''}{abs(value)}"


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json(raw: bytes, code: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (TypeError, ValueError, UnicodeDecodeError, RecursionError) as exc:
        raise AcceptanceHoldoutError(code) from exc
    if not isinstance(value, dict):
        raise AcceptanceHoldoutError(code)
    try:
        canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as exc:
        raise AcceptanceHoldoutError(code) from exc
    if canonical != raw:
        raise AcceptanceHoldoutError(code)
    return value


def _material(materials: Mapping[str, bytes], pin: object, code: str) -> bytes:
    if not isinstance(pin, Mapping) or set(pin) != {"path", "size", "sha256"}:
        raise AcceptanceHoldoutError(code)
    path = pin.get("path")
    if type(path) is not str or path not in materials or not isinstance(materials[path], bytes):
        raise AcceptanceHoldoutError(code)
    raw = materials[path]
    if (type(pin.get("size")) is not int or not 0 < pin["size"] <= 512 * 1024
            or pin["size"] != len(raw) or pin.get("sha256") != _sha(raw)):
        raise AcceptanceHoldoutError(code)
    return raw


def _probe(raw: bytes, code: str) -> EvaluatorProbe:
    value = _json(raw, code)
    required = {"name", "constraint_id", "expected_validity", "files"}
    if set(value) != required or type(value["name"]) is not str:
        raise AcceptanceHoldoutError(code)
    if value["constraint_id"] is not None and type(value["constraint_id"]) is not str:
        raise AcceptanceHoldoutError(code)
    if type(value["expected_validity"]) is not int or value["expected_validity"] not in (0, 1):
        raise AcceptanceHoldoutError(code)
    files = value["files"]
    if not isinstance(files, list) or not files:
        raise AcceptanceHoldoutError(code)
    parsed: list[ProbeFile] = []
    seen: set[str] = set()
    for item in files:
        if not isinstance(item, Mapping) or set(item) != {"path", "content"}:
            raise AcceptanceHoldoutError(code)
        if type(item["path"]) is not str or item["path"] in seen or type(item["content"]) is not str:
            raise AcceptanceHoldoutError(code)
        seen.add(item["path"])
        parsed.append(ProbeFile(item["path"], item["content"]))
    return EvaluatorProbe(value["name"], value["constraint_id"], value["expected_validity"], tuple(parsed))


def _validate_fixed_pair(ordinal: int, snapshot: EvaluatorProbe, expected: Mapping[str, Any], code: str) -> None:
    """Require the registered snapshot/expected pair to describe one fixed integer judgment."""
    if ordinal < 0 or ordinal >= len(_FIXED_HOLDOUT_PAIRS):
        raise AcceptanceHoldoutError(code)
    limit, value = _FIXED_HOLDOUT_PAIRS[ordinal]
    if snapshot.name != _fixed_holdout_name(limit, value):
        raise AcceptanceHoldoutError(code)
    files = {item.path: item.content for item in snapshot.files}
    if set(files) != {"data/raw/limit.json", "output/result.json"}:
        raise AcceptanceHoldoutError(code)
    try:
        limit_raw = json.loads(files["data/raw/limit.json"])
        value_raw = json.loads(files["output/result.json"])
    except (TypeError, ValueError, UnicodeDecodeError, RecursionError) as exc:
        raise AcceptanceHoldoutError(code) from exc
    if (not isinstance(limit_raw, dict) or set(limit_raw) != {"limit"}
            or type(limit_raw["limit"]) is not int
            or not isinstance(value_raw, dict) or set(value_raw) != {"value"}
            or type(value_raw["value"]) is not int):
        raise AcceptanceHoldoutError(code)
    if (limit_raw["limit"], value_raw["value"]) != (limit, value):
        raise AcceptanceHoldoutError(code)
    valid = 0 <= value <= limit
    derived = {
        "validity": int(valid), "quality": value if valid else None,
        "combined_score": value if valid else 0,
        "constraint_code": None if valid else "valid-value",
    }
    if (_canonical(dict(expected)) != _canonical(derived)
            or snapshot.expected_validity != int(valid)
            or snapshot.constraint_id != derived["constraint_code"]
            or snapshot.files != (
                ProbeFile("data/raw/limit.json", f'{{"limit":{limit}}}\n'),
                ProbeFile("output/result.json", f'{{"value":{value}}}\n'),
            )):
        raise AcceptanceHoldoutError(code)


def _write_new(parent_fd: int, name: str, content: bytes) -> None:
    if not isinstance(content, bytes):
        raise AcceptanceHoldoutError("evidence_bytes_invalid")
    try:
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=parent_fd)
    except OSError as exc:
        raise AcceptanceHoldoutError("evidence_write_failed") from exc
    try:
        view = memoryview(content)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise AcceptanceHoldoutError("evidence_write_failed")
            view = view[written:]
        os.fsync(fd)
        info = os.fstat(fd)
        named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if (not stat.S_ISREG(named.st_mode) or info.st_nlink != 1 or named.st_nlink != 1
                or info.st_size != len(content) or named.st_size != len(content)
                or (info.st_dev, info.st_ino) != (named.st_dev, named.st_ino)):
            raise AcceptanceHoldoutError("evidence_file_changed")
    except OSError as exc:
        raise AcceptanceHoldoutError("evidence_write_failed") from exc
    finally:
        os.close(fd)


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as exc:
        raise AcceptanceHoldoutError("evidence_json_invalid") from exc


def _remaining(callback: Any, stage: str) -> float | None:
    if callback is None:
        return None
    if not callable(callback):
        raise AcceptanceHoldoutError("remaining_timeout_invalid")
    try:
        value = callback(stage)
    except Exception as exc:
        raise AcceptanceHoldoutError("holdout_deadline_exceeded") from exc
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or value <= 0):
        raise AcceptanceHoldoutError("holdout_deadline_exceeded")
    return float(value)


def _check_directories(*chains: DirectoryChain) -> None:
    try:
        for chain in chains:
            chain.check()
    except (CandidateWorkspaceError, OSError) as exc:
        raise AcceptanceHoldoutError("holdout_workspace_changed") from exc


def _active(check_active: Any, *chains: DirectoryChain) -> None:
    _check_directories(*chains)
    try:
        if check_active is not None:
            check_active()
    finally:
        _check_directories(*chains)


def _new_directory(parent: DirectoryChain, path: Path, stack: ExitStack) -> DirectoryChain:
    _check_directories(parent)
    try:
        os.mkdir(path.name, 0o700, dir_fd=parent.fd)
    except FileExistsError as exc:
        raise AcceptanceHoldoutError("holdout_workspace_exists") from exc
    except OSError as exc:
        raise AcceptanceHoldoutError("holdout_workspace_create_failed") from exc
    try:
        before = os.stat(path.name, dir_fd=parent.fd, follow_symlinks=False)
        child = DirectoryChain(path, "holdout_workspace_changed")
        stack.callback(child.close)
        opened = os.fstat(child.fd)
        if (not stat.S_ISDIR(before.st_mode)
                or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)):
            raise AcceptanceHoldoutError("holdout_workspace_changed")
        os.fchmod(child.fd, 0o700)
        os.fsync(child.fd)
        os.fsync(parent.fd)
        _check_directories(parent, child)
        return child
    except (CandidateWorkspaceError, OSError) as exc:
        raise AcceptanceHoldoutError("holdout_workspace_changed") from exc


def _contract_inputs_outputs(contract: AlgorithmProblemContract) -> None:
    if len(contract.inputs) != 1 or len(contract.outputs) != 1:
        raise AcceptanceHoldoutError("holdout_contract_mismatch")
    source, output = contract.inputs[0], contract.outputs[0]
    if (source.path != "limit.json" or source.format != "json" or set(source.fields) != {"limit"}
            or output.path != "output/result.json" or output.format != "json"
            or output.fields != ("value",) or output.required is not True):
        raise AcceptanceHoldoutError("holdout_contract_mismatch")


def run_acceptance_holdouts(
    registration: Mapping[str, Any],
    *,
    materials: Mapping[str, bytes],
    evaluator: Path,
    contract: AlgorithmProblemContract,
    workspace: Path,
    check_active: Any = None,
    remaining_timeout: Any = None,
) -> tuple[dict[str, Any], ...]:
    """Run each registered holdout once and return ordered, digest-bound observations."""
    if not isinstance(registration, Mapping) or not isinstance(materials, Mapping):
        raise AcceptanceHoldoutError("batch_invalid")
    pins = registration.get("holdout_pins")
    if not isinstance(pins, list) or len(pins) != 8:
        raise AcceptanceHoldoutError("holdout_count_invalid")
    if not isinstance(evaluator, Path) or not isinstance(workspace, Path):
        raise AcceptanceHoldoutError("path_invalid")
    if not isinstance(contract, AlgorithmProblemContract):
        raise AcceptanceHoldoutError("contract_invalid")
    _contract_inputs_outputs(contract)
    if check_active is not None and not callable(check_active):
        raise AcceptanceHoldoutError("check_active_invalid")
    if remaining_timeout is not None and not callable(remaining_timeout):
        raise AcceptanceHoldoutError("remaining_timeout_invalid")

    # Validate every registered material and every pair before creating the root or running one
    # evaluator. This makes a partial eight-probe batch impossible after a late material drift.
    prepared: list[tuple[int, str, bytes, bytes, EvaluatorProbe, dict[str, Any], int]] = []
    seen_ids: set[str] = set()
    for ordinal, pin in enumerate(pins):
        if not isinstance(pin, Mapping) or set(pin) != {"ordinal", "holdout_id", "input", "expected", "max_duration_ms"}:
            raise AcceptanceHoldoutError("holdout_schema_invalid")
        if type(pin.get("ordinal")) is not int or pin["ordinal"] != ordinal:
            raise AcceptanceHoldoutError("holdout_order_invalid")
        holdout_id = pin.get("holdout_id")
        if type(holdout_id) is not str or not holdout_id or holdout_id in seen_ids:
            raise AcceptanceHoldoutError("holdout_identity_invalid")
        seen_ids.add(holdout_id)
        duration = pin.get("max_duration_ms")
        if type(duration) is not int or not 1 <= duration <= 5000:
            raise AcceptanceHoldoutError("holdout_duration_invalid")
        snapshot_raw = _material(materials, pin.get("input", {}), "holdout_input_invalid")
        expected_raw = _material(materials, pin.get("expected", {}), "holdout_expected_invalid")
        snapshot = _probe(snapshot_raw, "holdout_snapshot_invalid")
        if snapshot.name != holdout_id:
            raise AcceptanceHoldoutError("holdout_identity_mismatch")
        expected = _json(expected_raw, "holdout_expected_invalid")
        if set(expected) != {"validity", "quality", "combined_score", "constraint_code"}:
            raise AcceptanceHoldoutError("holdout_expected_invalid")
        try:
            expected = _expected(expected)
        except Exception as exc:
            raise AcceptanceHoldoutError("holdout_expected_invalid") from exc
        _validate_fixed_pair(ordinal, snapshot, expected, "holdout_pair_invalid")
        prepared.append((ordinal, holdout_id, snapshot_raw, expected_raw, snapshot, expected, duration))

    try:
        root = absolute_path(workspace)
    except BenchmarkFileError as exc:
        raise AcceptanceHoldoutError("path_invalid") from exc
    rows: list[dict[str, Any]] = []
    with ExitStack() as stack:
        try:
            parent_chain = DirectoryChain(root.parent, "holdout_parent_invalid")
            stack.callback(parent_chain.close)
        except (CandidateWorkspaceError, OSError) as exc:
            raise AcceptanceHoldoutError("holdout_parent_invalid") from exc
        root_chain = _new_directory(parent_chain, root, stack)
        _active(check_active, parent_chain, root_chain)
        for ordinal, holdout_id, snapshot_raw, expected_raw, snapshot, expected, duration in prepared:
            _remaining(remaining_timeout, f"holdout-{ordinal:02d}-before")
            _active(check_active, parent_chain, root_chain)
            item_path = root / f"{ordinal:02d}"
            with ExitStack() as item_stack:
                item_chain = _new_directory(root_chain, item_path, item_stack)
                probe_chain = _new_directory(item_chain, item_path / "probe", item_stack)
                chains = (parent_chain, root_chain, item_chain, probe_chain)
                _write_new(item_chain.fd, "snapshot.bin", snapshot_raw)
                _write_new(item_chain.fd, "expected.json", expected_raw)
                os.fsync(item_chain.fd)
                _active(check_active, *chains)
                remaining = _remaining(remaining_timeout, f"holdout-{ordinal:02d}-run")
                timeout = duration / 1000 if remaining is None else min(duration / 1000, remaining)
                _check_directories(*chains)

                def guarded_active(held_chains=chains) -> None:
                    _active(check_active, *held_chains)

                try:
                    evidence: AcceptanceSnapshotEvidence = run_acceptance_snapshot_probe(
                        evaluator, snapshot, contract, item_path / "probe", expected=expected,
                        timeout_seconds=timeout, check_active=guarded_active,
                    )
                finally:
                    _check_directories(*chains)
                _write_new(item_chain.fd, "actual.json", evidence.actual_output_bytes)
                _write_new(item_chain.fd, "evidence.json", _canonical(evidence.to_dict()))
                os.fsync(item_chain.fd)
                _active(check_active, *chains)
            _remaining(remaining_timeout, f"holdout-{ordinal:02d}-after")
            _check_directories(parent_chain, root_chain)
            outcome = "passed" if evidence.passed else ("failed" if evidence.reason not in {"cancelled", "timeout", "exception", "cleanup_unknown"} else "unknown")
            rows.append({
                "ordinal": ordinal, "holdout_id": holdout_id, "outcome": outcome,
                "input_sha256": _sha(snapshot_raw), "expected_output_sha256": _sha(expected_raw),
                "actual_output_sha256": _sha(evidence.actual_output_bytes), "evidence": evidence.to_dict(),
            })
    return tuple(rows)


__all__ = ["AcceptanceHoldoutError", "run_acceptance_holdouts"]
