"""Execute the eight preregistered acceptance snapshot holdouts exactly once.

This runner is intentionally provider-free.  It consumes the immutable material bytes pinned by
the registration, invokes the frozen native snapshot evaluator once per ordinal, and returns
detached rows suitable for a later holdout receipt writer.  It never retries a probe or upgrades
unknown cleanup/process observations to success.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .acceptance_probes import AcceptanceSnapshotEvidence, _expected, run_acceptance_snapshot_probe
from .algorithm import AlgorithmProblemContract
from .evaluator_bundle import EvaluatorProbe, ProbeFile


class AcceptanceHoldoutError(ValueError):
    """A fixed malformed holdout batch or material failure."""


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


def _material(materials: Mapping[str, bytes], pin: Mapping[str, Any], code: str) -> bytes:
    path = pin.get("path")
    if type(path) is not str or path not in materials or not isinstance(materials[path], bytes):
        raise AcceptanceHoldoutError(code)
    raw = materials[path]
    if pin.get("size") != len(raw) or pin.get("sha256") != _sha(raw):
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


def _validate_fixed_pair(snapshot: EvaluatorProbe, expected: Mapping[str, Any], code: str) -> None:
    """Require the registered snapshot/expected pair to describe one fixed integer judgment."""
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
    limit, value = limit_raw["limit"], value_raw["value"]
    valid = 0 <= value <= limit
    derived = {
        "validity": int(valid), "quality": value if valid else None,
        "combined_score": value if valid else 0,
        "constraint_code": None if valid else "valid-value",
    }
    if dict(expected) != derived or snapshot.expected_validity != int(valid):
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
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise AcceptanceHoldoutError("holdout_deadline_exceeded")
    return float(value)


def _check_root(root_fd: int, root: Path) -> None:
    try:
        named = os.stat(root, follow_symlinks=False)
        held = os.fstat(root_fd)
    except OSError as exc:
        raise AcceptanceHoldoutError("holdout_workspace_changed") from exc
    if (not stat.S_ISDIR(named.st_mode) or stat.S_IMODE(named.st_mode) != 0o700
            or (named.st_dev, named.st_ino) != (held.st_dev, held.st_ino)):
        raise AcceptanceHoldoutError("holdout_workspace_changed")


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
        if pin.get("ordinal") != ordinal:
            raise AcceptanceHoldoutError("holdout_order_invalid")
        holdout_id = pin.get("holdout_id")
        if type(holdout_id) is not str or not holdout_id or holdout_id in seen_ids:
            raise AcceptanceHoldoutError("holdout_identity_invalid")
        seen_ids.add(holdout_id)
        duration = pin.get("max_duration_ms")
        if type(duration) is not int or duration <= 0:
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
        _validate_fixed_pair(snapshot, expected, "holdout_pair_invalid")
        prepared.append((ordinal, holdout_id, snapshot_raw, expected_raw, snapshot, expected, duration))

    root = Path(workspace)
    if root.exists() or root.is_symlink():
        raise AcceptanceHoldoutError("holdout_workspace_exists")
    parent_fd = -1
    root_fd = -1
    try:
        parent_fd = os.open(root.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        os.mkdir(root.name, 0o700, dir_fd=parent_fd)
        root_fd = os.open(root.name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent_fd)
        os.fchmod(root_fd, 0o700)
        os.fsync(root_fd)
        os.fsync(parent_fd)
    except OSError as exc:
        if root_fd >= 0:
            os.close(root_fd)
        if parent_fd >= 0:
            os.close(parent_fd)
        raise AcceptanceHoldoutError("holdout_workspace_create_failed") from exc

    if check_active is not None:
        check_active()

    rows: list[dict[str, Any]] = []
    for ordinal, pin in enumerate(pins):
        ordinal, holdout_id, snapshot_raw, expected_raw, snapshot, expected, duration = prepared[ordinal]
        _check_root(root_fd, root)
        _remaining(remaining_timeout, f"holdout-{ordinal:02d}-before")
        if check_active is not None:
            check_active()
        try:
            os.mkdir(f"{ordinal:02d}", 0o700, dir_fd=root_fd)
            item_fd = os.open(f"{ordinal:02d}", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=root_fd)
            os.fsync(root_fd)
        except OSError as exc:
            raise AcceptanceHoldoutError("holdout_workspace_create_failed") from exc
        item_path = root / f"{ordinal:02d}"
        try:
            _write_new(item_fd, "snapshot.bin", snapshot_raw)
            _write_new(item_fd, "expected.json", expected_raw)
            if check_active is not None:
                check_active()
            remaining = _remaining(remaining_timeout, f"holdout-{ordinal:02d}-run")
            timeout = duration / 1000
            if remaining is not None:
                timeout = min(timeout, remaining)
            evidence: AcceptanceSnapshotEvidence = run_acceptance_snapshot_probe(
                evaluator, snapshot, contract, item_path,
                expected=expected, timeout_seconds=timeout, check_active=check_active,
            )
            actual_bytes = evidence.actual_output_bytes
            evidence_bytes = _canonical(evidence.to_dict())
            _write_new(item_fd, "actual.json", actual_bytes)
            _write_new(item_fd, "evidence.json", evidence_bytes)
            os.fsync(item_fd)
        finally:
            os.close(item_fd)
        _check_root(root_fd, root)
        _remaining(remaining_timeout, f"holdout-{ordinal:02d}-after")
        outcome = "passed" if evidence.passed else ("failed" if evidence.reason not in {"cancelled", "timeout", "exception", "cleanup_unknown"} else "unknown")
        rows.append({
            "ordinal": ordinal,
            "holdout_id": holdout_id,
            "outcome": outcome,
            "input_sha256": _sha(snapshot_raw),
            "expected_output_sha256": _sha(expected_raw),
            "actual_output_sha256": _sha(evidence.actual_output_bytes),
            "evidence": evidence.to_dict(),
        })
    os.close(root_fd)
    os.close(parent_fd)
    return tuple(rows)


__all__ = ["AcceptanceHoldoutError", "run_acceptance_holdouts"]
