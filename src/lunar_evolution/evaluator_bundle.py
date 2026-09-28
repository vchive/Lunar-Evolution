"""Compile, preflight, freeze, and reload a local algorithm evaluator bundle.

The generated evaluator is explicit executable authority.  This module reduces that authority with
a strict envelope, a conservative source check, synthetic probes, minimal subprocess environment,
and content-addressed recovery; it does not claim to be an operating-system sandbox.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .algorithm import (
    MAX_ERROR_INFO,
    MAX_METRICS,
    MAX_REPORT_BYTES,
    AlgorithmProblemContract,
    EvaluationReport,
)
from .automatic_solve_lifecycle import SolveExecutionBudgetExceeded, SolveExecutionCancelled
from .data_profile import (
    MAX_PROFILE_DEPTH,
    MAX_PROFILE_FIELD_BYTES,
    MAX_PROFILE_FIELDS,
    MAX_PROFILE_ROWS,
    DataProfileError,
    build_private_input_profile,
    canonical_profile_json,
    profile_sha256,
    validate_input_format,
)
from .evaluator import acceptance_evaluator
from .evaluator_diagnostics import EvaluatorPreparationDiagnostic
from .evaluator_request_diagnostics import (
    normalize_evaluator_request_failure,
    project_evaluator_request_failure,
)
from .evolution import CandidateExecution, CandidateInputArtifact, EvolutionError
from .runtime import Runtime, RuntimeResult

MAX_BUNDLE_RESPONSE_BYTES = 512 * 1024
MAX_OBJECTIVE_BYTES = 32 * 1024
MAX_EVALUATOR_BYTES = 128 * 1024
MAX_PROBES = 64
MAX_PROBE_FILES = 32
MAX_PROBE_FILE_BYTES = 64 * 1024
MAX_PROBE_BYTES = 512 * 1024
MAX_EVALUATOR_OUTPUT_BYTES = 64 * 1024
MAX_IDENTIFIER_BYTES = 128
MAX_SOLVER_EVALUATOR_EXCERPT_BYTES = 12 * 1024
BUNDLE_PROTOCOL = "frozen-evaluator-bundle-v2"
SNAPSHOT_BUNDLE_PROTOCOL = "frozen-evaluator-snapshot-v1"
COMPILED_BUNDLE_EVALUATOR_ID = "compiled-bundle"
BUNDLE_FILES = frozenset(
    {
        "audit.json",
        "objective.md",
        "evaluator.py",
        "probes.json",
        "input-profile.json",
        "manifest.json",
    }
)
_ALLOWED_IMPORTS = frozenset(
    {
        "bisect",
        "collections",
        "csv",
        "datetime",
        "decimal",
        "fractions",
        "functools",
        "heapq",
        "itertools",
        "json",
        "math",
        "pathlib",
        "statistics",
        "sys",
    }
)
_DANGEROUS_CALLS = frozenset(
    {
        "breakpoint",
        "compile",
        "delattr",
        "eval",
        "exec",
        "getattr",
        "globals",
        "input",
        "locals",
        "open",
        "setattr",
        "vars",
    }
)
_DANGEROUS_ATTRIBUTES = frozenset(
    {
        "chmod",
        "mkdir",
        "rename",
        "replace",
        "rmdir",
        "touch",
        "truncate",
        "unlink",
        "write",
        "write_bytes",
        "write_text",
        "writelines",
    }
)
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_SECRET = re.compile(
    r"(?i)(?:sk-[A-Za-z0-9_-]{12,}|bearer\s+[A-Za-z0-9._-]{12,}|"
    r"api[_-]?key\s*[:=]\s*\S+)"
)


class EvaluatorBundleError(EvolutionError):
    """A bounded evaluator compilation, preflight, or integrity failure."""


class _SuiteResponseError(EvaluatorBundleError):
    """Fixed auditor response category without retaining generated content."""

    def __init__(self, message: str, reason: str) -> None:
        self.reason = reason
        super().__init__(message)


class EvaluatorPreparationError(EvaluatorBundleError):
    """A local preparation failure with a controller-owned, bounded observation."""

    def __init__(self, message: str, diagnostic: EvaluatorPreparationDiagnostic) -> None:
        if type(diagnostic) is not EvaluatorPreparationDiagnostic:
            raise TypeError("invalid evaluator preparation diagnostic")
        self.diagnostic = EvaluatorPreparationDiagnostic.from_dict(diagnostic.to_dict())
        super().__init__(message)


class _ProbeFailure(EvaluatorBundleError):
    """Internal check identity; only a preflight caller can attach a preparation stage."""

    def __init__(self, message: str, reason: str) -> None:
        self.reason = reason
        super().__init__(message)


def _local_failure(message, stage, reason, *, probe_index=None, input_index=None, order_index=None):
    return EvaluatorPreparationError(message, EvaluatorPreparationDiagnostic(
        stage, reason, probe_index, input_index, order_index,
    ))


class UnsupportedEvaluatorConstraintsError(EvaluatorBundleError):
    """Declared requirements need evidence unavailable to generated probe evaluators."""

    def __init__(self, constraints: tuple[tuple[str, str], ...]) -> None:
        self.unsupported_constraints = constraints
        labels = ", ".join(f"{identifier} ({scope})" for identifier, scope in constraints)
        super().__init__("unsupported evaluator verification scopes: " + labels)

    def details(self) -> list[dict[str, str]]:
        return [{"id": identifier, "verification_scope": scope}
                for identifier, scope in self.unsupported_constraints]


def validate_evaluator_capabilities(contract: AlgorithmProblemContract, *, invocation="candidate") -> None:
    """Retain all requirements; never interpret verification strength as evidence scope.

    Unscoped historical contracts preserve their original probe-coverage assumptions. Both
    generated invocation modes use synthetic input/output probes. Only the snapshot controller
    additionally verifies supported source counts outside those probes.
    """
    from .source_constraints import unsupported_source_constraints

    _bundle_protocol(invocation)
    unsupported = unsupported_source_constraints(contract, allow_source_checks=invocation == "snapshot")
    if unsupported:
        raise UnsupportedEvaluatorConstraintsError(unsupported)


class EvaluatorBundleRuntimeError(EvaluatorBundleError):
    """A runtime invocation failed before its compiler/auditor response was accepted."""

    def __init__(self, stage: str, *, request_failure: object = None) -> None:
        if stage not in {"evaluator_compile", "evaluator_audit"}:
            raise ValueError("invalid evaluator runtime failure stage")
        self.stage = stage
        self.request_failure = (
            normalize_evaluator_request_failure(request_failure)
            if request_failure is not None else None
        )
        role = "compiler" if stage == "evaluator_compile" else "auditor"
        super().__init__(f"evaluator {role} failed: runtime_error")


class EvaluatorPreparationWallTimeout(EvaluatorBundleError):
    """The controller's monotonic preparation deadline was reached locally."""

    def __init__(self, stage: str, *, request_failure: object = None) -> None:
        if stage not in {"preparation", "evaluator_compile", "evaluator_audit",
                         "compiler_preflight", "auditor_preflight", "profile_publish"}:
            raise ValueError("invalid preparation timeout stage")
        self.stage = stage
        self.request_failure = (
            normalize_evaluator_request_failure(request_failure)
            if request_failure is not None else None
        )
        super().__init__("evaluator preparation wall timeout")


def _preparation_timeout(timeout, remaining, stage):
    return timeout if remaining is None else min(timeout, _timeout(remaining(stage)))


def _request_after_failure(remaining, stage, error):
    if remaining is not None:
        try:
            remaining(stage)
        except EvaluatorPreparationWallTimeout as exc:
            raise EvaluatorPreparationWallTimeout(
                stage, request_failure=project_evaluator_request_failure(error),
            ) from exc


class BundleRuntime(Protocol):
    name: str

    def run(self, prompt: str, workspace: Path, timeout: float | None = None) -> RuntimeResult:
        ...


@dataclass(frozen=True)
class ProbeFile:
    path: str
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"path": self.path, "content": self.content}


@dataclass(frozen=True)
class EvaluatorProbe:
    name: str
    constraint_id: str | None
    expected_validity: int
    files: tuple[ProbeFile, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "constraint_id": self.constraint_id,
            "expected_validity": self.expected_validity,
            "files": [item.to_dict() for item in self.files],
        }


@dataclass(frozen=True)
class ScoreOrder:
    better: str
    worse: str

    def to_dict(self) -> dict[str, str]:
        return {"better": self.better, "worse": self.worse}


@dataclass(frozen=True)
class EvaluatorBundleEnvelope:
    objective: str
    evaluator_source: str
    constraint_coverage: tuple[str, ...]
    probes: tuple[EvaluatorProbe, ...]
    score_order: tuple[ScoreOrder, ...]

    def probe_suite(self) -> ProbeSuite:
        return ProbeSuite(self.constraint_coverage, self.probes, self.score_order)


@dataclass(frozen=True)
class ProbeSuite:
    constraint_coverage: tuple[str, ...]
    probes: tuple[EvaluatorProbe, ...]
    score_order: tuple[ScoreOrder, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "1",
            "constraint_coverage": list(self.constraint_coverage),
            "probes": [item.to_dict() for item in self.probes],
            "score_order": [item.to_dict() for item in self.score_order],
        }


@dataclass(frozen=True)
class FrozenEvaluatorBundle:
    root: Path
    fingerprint: str
    contract_sha256: str
    input_profile_sha256: str
    timeout_seconds: float = 900.0
    invocation: str = "candidate"

    def __call__(
        self, candidate_path: Path, contract: AlgorithmProblemContract
    ) -> EvaluationReport:
        if self.invocation != "candidate":
            raise EvaluatorBundleError("snapshot evaluator requires independent candidate evaluation")
        if contract.digest() != self.contract_sha256:
            raise EvaluatorBundleError("frozen evaluator contract digest does not match")
        verified = load_evaluator_bundle(self.root, contract, timeout=self.timeout_seconds)
        if verified.fingerprint != self.fingerprint:
            raise EvaluatorBundleError("frozen evaluator bundle fingerprint changed")
        before = _candidate_evidence_snapshot(Path(candidate_path), contract)
        report = _run_evaluator(
            self.root / "evaluator.py", Path(candidate_path), self.timeout_seconds
        )
        after_evidence = _candidate_evidence_snapshot(Path(candidate_path), contract)
        if after_evidence != before:
            raise EvaluatorBundleError("frozen evaluator modified candidate evidence")
        after = load_evaluator_bundle(self.root, contract, timeout=self.timeout_seconds)
        if after.fingerprint != self.fingerprint:
            raise EvaluatorBundleError("frozen evaluator bundle changed during evaluation")
        return report


@dataclass(frozen=True)
class SolverScoringContract:
    """Verified, immutable scoring guidance made visible to a candidate-building Agent."""

    objective: str
    evaluator_source: str
    evaluator_sha256: str
    bundle_sha256: str
    schema_version: str = "1"
    authority: str = "frozen_evaluator"

    def __post_init__(self) -> None:
        objective = _text(
            self.objective, "solver scoring objective", MAX_OBJECTIVE_BYTES, strip=False
        )
        source = _text(
            self.evaluator_source,
            "solver scoring evaluator source",
            MAX_EVALUATOR_BYTES,
            strip=False,
        )
        if self.schema_version != "1" or self.authority != "frozen_evaluator":
            raise ValueError("solver scoring contract identity is invalid")
        if not _is_sha256(self.evaluator_sha256) or not _is_sha256(self.bundle_sha256):
            raise ValueError("solver scoring contract digests are invalid")
        if hashlib.sha256(source.encode("utf-8")).hexdigest() != self.evaluator_sha256:
            raise ValueError("solver scoring evaluator digest does not match source")
        object.__setattr__(self, "objective", objective)
        object.__setattr__(self, "evaluator_source", source)

    @classmethod
    def from_bundle(
        cls,
        bundle: FrozenEvaluatorBundle,
        contract: AlgorithmProblemContract,
    ) -> SolverScoringContract:
        if not isinstance(bundle, FrozenEvaluatorBundle):
            raise TypeError("bundle must be a FrozenEvaluatorBundle")
        verified = load_evaluator_bundle(
            bundle.root,
            contract,
            timeout=bundle.timeout_seconds,
        )
        if verified.fingerprint != bundle.fingerprint:
            raise EvaluatorBundleError("frozen evaluator bundle fingerprint changed")
        try:
            objective = (bundle.root / "objective.md").read_text(encoding="utf-8")
            evaluator_source = (bundle.root / "evaluator.py").read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise EvaluatorBundleError("frozen evaluator scoring guidance is unreadable") from exc
        return cls(
            objective=objective,
            evaluator_source=evaluator_source,
            evaluator_sha256=hashlib.sha256(evaluator_source.encode("utf-8")).hexdigest(),
            bundle_sha256=verified.fingerprint,
        )

    def prompt_dict(
        self, *, evaluator_excerpt_bytes: int = MAX_SOLVER_EVALUATOR_EXCERPT_BYTES
    ) -> dict[str, object]:
        if (
            isinstance(evaluator_excerpt_bytes, bool)
            or not isinstance(evaluator_excerpt_bytes, int)
            or not 0 <= evaluator_excerpt_bytes <= MAX_SOLVER_EVALUATOR_EXCERPT_BYTES
        ):
            raise ValueError("solver evaluator excerpt size is invalid")
        source = self.evaluator_source.encode("utf-8")
        excerpt = source[:evaluator_excerpt_bytes].decode(
            "utf-8", errors="ignore"
        )
        objective = self.objective.encode("utf-8")
        return {
            "schema_version": self.schema_version,
            "authority": self.authority,
            "bundle_sha256": self.bundle_sha256,
            "objective": {
                "path": "scoring/objective.md",
                "text": self.objective,
                "size": len(objective),
                "sha256": hashlib.sha256(objective).hexdigest(),
            },
            "evaluator": {
                "path": "scoring/evaluator.py",
                "size": len(source),
                "sha256": self.evaluator_sha256,
                "source_excerpt": excerpt,
                "truncated": len(source) > len(excerpt.encode("utf-8")),
            },
        }

    def stage(self, workspace: Path) -> None:
        root = Path(workspace).expanduser()
        if root.is_symlink():
            raise EvaluatorBundleError("solver scoring workspace must not be a symlink")
        root = root.resolve(strict=False)
        root.mkdir(parents=True, exist_ok=True)
        scoring = root / "scoring"
        if scoring.is_symlink():
            raise EvaluatorBundleError("solver scoring directory must not be a symlink")
        scoring.mkdir(parents=True, exist_ok=True)
        manifest = {
            "schema_version": self.schema_version,
            "authority": self.authority,
            "bundle_sha256": self.bundle_sha256,
            "objective": {
                "path": "scoring/objective.md",
                "size": len(self.objective.encode("utf-8")),
                "sha256": hashlib.sha256(self.objective.encode("utf-8")).hexdigest(),
            },
            "evaluator": {
                "path": "scoring/evaluator.py",
                "size": len(self.evaluator_source.encode("utf-8")),
                "sha256": self.evaluator_sha256,
            },
        }
        files = {
            "objective.md": self.objective.encode("utf-8"),
            "evaluator.py": self.evaluator_source.encode("utf-8"),
            "manifest.json": json.dumps(
                manifest,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"),
        }
        existing = tuple(scoring.iterdir())
        if any(path.name not in files for path in existing):
            raise EvaluatorBundleError("solver scoring directory contains an unexpected file")
        for name, content in files.items():
            target = scoring / name
            if target.is_symlink() or (target.exists() and not target.is_file()):
                raise EvaluatorBundleError("solver scoring file is unsafe")
            if target.exists():
                if target.read_bytes() != content:
                    raise EvaluatorBundleError(
                        "solver scoring file conflicts with frozen guidance"
                    )
            else:
                temporary: Path | None = None
                try:
                    with tempfile.NamedTemporaryFile(
                        dir=scoring,
                        prefix=f".{target.name}.",
                        suffix=".tmp",
                        delete=False,
                    ) as handle:
                        handle.write(content)
                        temporary = Path(handle.name)
                    temporary.chmod(0o444)
                    temporary.replace(target)
                finally:
                    if temporary is not None:
                        temporary.unlink(missing_ok=True)
            target.chmod(0o444)
        scoring.chmod(0o555)


def compile_evaluator_bundle(
    runtime: Runtime | BundleRuntime,
    contract: AlgorithmProblemContract,
    workspace: Path,
    *,
    inputs: tuple[CandidateInputArtifact, ...] = (),
    timeout: float = 900.0,
    preparation_request_timeout: float | None = None,
    preparation_remaining_timeout: Callable[[str], float] | None = None,
    invocation: str = "candidate",
    continuation_guard: Callable[[], None] | None = None,
    process_observer: Callable[[int, int | None], None] | None = None,
    process_released: Callable[[int, int | None], None] | None = None,
    process_exit_observed: Callable[[int | None], None] | None = None,
    process_result_observed: Callable[[str, int | None, str | None], None] | None = None,
) -> FrozenEvaluatorBundle:
    """Compile and preflight a bundle, or verify and reuse an existing frozen bundle."""
    if not isinstance(contract, AlgorithmProblemContract):
        raise TypeError("contract must be an AlgorithmProblemContract")
    process_options = _process_options(process_observer, process_released, process_exit_observed,
                                       process_result_observed)
    timeout = _timeout(timeout)
    request_timeout = timeout if preparation_request_timeout is None else _timeout(preparation_request_timeout)
    _preparation_timeout(timeout, preparation_remaining_timeout, "preparation")
    _bundle_protocol(invocation)
    validate_evaluator_capabilities(contract, invocation=invocation)
    if invocation == "snapshot":
        from .candidate_evaluation_spec import candidate_output_contract_sha256

        candidate_output_contract_sha256(contract.outputs)
        _snapshot_spec(b"# evaluator\n", timeout)
    raw_root = Path(workspace).expanduser()
    if raw_root.is_symlink():
        raise EvaluatorBundleError("evaluator bundle workspace must not be a symlink")
    root = raw_root.resolve(strict=False)
    root.mkdir(parents=True, exist_ok=True)
    destination = root / "evaluator-bundle"
    if destination.exists() or destination.is_symlink():
        profile = _build_input_profile(root, contract, inputs)
        return load_evaluator_bundle(
            destination,
            contract,
            input_profile=profile,
            timeout=timeout,
            invocation=invocation,
        )

    compiler_workspace = root / ".evaluator-compiler"
    if compiler_workspace.is_symlink():
        raise EvaluatorBundleError("evaluator compiler workspace must not be a symlink")
    compiler_workspace.mkdir(parents=True, exist_ok=True)
    profile = _build_input_profile(root, contract, inputs)
    prompt = _compiler_prompt(contract, profile, invocation=invocation)
    if continuation_guard is not None:
        continuation_guard()
    request_limit = _preparation_timeout(request_timeout, preparation_remaining_timeout, "evaluator_compile")
    try:
        result = _run_isolated(runtime, prompt, compiler_workspace, request_limit)
    except (SolveExecutionBudgetExceeded, SolveExecutionCancelled):
        raise
    except Exception as exc:
        _request_after_failure(preparation_remaining_timeout, "evaluator_compile", exc)
        raise EvaluatorBundleRuntimeError(
            "evaluator_compile", request_failure=project_evaluator_request_failure(exc),
        ) from exc
    if continuation_guard is not None:
        continuation_guard()
    _preparation_timeout(timeout, preparation_remaining_timeout, "evaluator_compile")
    try:
        if not isinstance(result, RuntimeResult):
            raise EvaluatorBundleError("evaluator compiler returned an invalid runtime result")
        envelope = _parse_envelope(result.text, contract, invocation=invocation)
    except (EvaluatorBundleError, ValueError, TypeError, RecursionError) as exc:
        raise _local_failure(str(exc), "compiler_response", "response_invalid") from exc
    staging = Path(tempfile.mkdtemp(prefix=".evaluator-bundle-", dir=root))
    try:
        objective_path = staging / "objective.md"
        evaluator_path = staging / "evaluator.py"
        probes_path = staging / "probes.json"
        profile_path = staging / "input-profile.json"
        audit_path = staging / "audit.json"
        objective_path.write_text(envelope.objective + "\n", encoding="utf-8")
        evaluator_path.write_text(envelope.evaluator_source, encoding="utf-8")
        probes_path.write_text(_canonical_probe_suite(envelope.probe_suite()), encoding="utf-8")
        profile_path.write_text(canonical_profile_json(profile), encoding="utf-8")
        frozen_inputs = {
            path.name: _sha256(path)
            for path in (objective_path, evaluator_path, probes_path, profile_path)
        }
        _preflight(
            evaluator_path,
            envelope.probe_suite(),
            contract,
            staging,
            timeout,
            label="compiler",
            invocation=invocation,
            preparation_remaining_timeout=preparation_remaining_timeout,
            **process_options,
        )
        current = tuple(staging.iterdir())
        if {path.name for path in current} != set(frozen_inputs) or any(
            path.is_symlink()
            or not path.is_file()
            or _sha256(path) != frozen_inputs[path.name]
            for path in current
        ):
            raise _local_failure("evaluator preflight modified the frozen bundle inputs",
                                 "compiler_preflight", "evidence_changed")
        audit_suite = _compile_audit_suite(
            runtime,
            contract,
            profile,
            envelope.objective,
            envelope.evaluator_source,
            root,
            request_timeout,
            invocation=invocation,
            continuation_guard=continuation_guard,
            preparation_remaining_timeout=preparation_remaining_timeout,
        )
        audit_path.write_text(_canonical_probe_suite(audit_suite), encoding="utf-8")
        frozen_inputs[audit_path.name] = _sha256(audit_path)
        _preflight(
            evaluator_path,
            audit_suite,
            contract,
            staging,
            timeout,
            label="audit",
            invocation=invocation,
            preparation_remaining_timeout=preparation_remaining_timeout,
            **process_options,
        )
        current = tuple(staging.iterdir())
        if {path.name for path in current} != set(frozen_inputs) or any(
            path.is_symlink()
            or not path.is_file()
            or _sha256(path) != frozen_inputs[path.name]
            for path in current
        ):
            raise _local_failure("evaluator audit modified the frozen bundle inputs",
                                 "auditor_preflight", "evidence_changed")
        manifest = _manifest(
            contract,
            objective_path,
            evaluator_path,
            probes_path,
            audit_path,
            profile_path,
            invocation=invocation,
        )
        manifest_path = staging / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        for path in (
            objective_path,
            evaluator_path,
            probes_path,
            audit_path,
            profile_path,
            manifest_path,
        ):
            path.chmod(0o444)
        staging.chmod(0o555)
        load_evaluator_bundle(staging, contract, input_profile=profile, timeout=timeout, invocation=invocation)
        if continuation_guard is not None:
            continuation_guard()
        _preparation_timeout(timeout, preparation_remaining_timeout, "preparation")
        try:
            staging.replace(destination)
        except FileExistsError:
            _remove_tree(staging)
            return load_evaluator_bundle(
                destination, contract, input_profile=profile, timeout=timeout, invocation=invocation,
            )
    except Exception:
        _remove_tree(staging)
        raise
    return load_evaluator_bundle(
        destination, contract, input_profile=profile, timeout=timeout, invocation=invocation,
    )


def load_evaluator_bundle(
    root: Path,
    contract: AlgorithmProblemContract,
    *,
    input_profile: dict[str, object] | None = None,
    timeout: float = 900.0,
    invocation: str = "candidate",
) -> FrozenEvaluatorBundle:
    """Load a frozen bundle after exact file, mode, schema, and digest verification."""
    timeout = _timeout(timeout)
    protocol = _bundle_protocol(invocation)
    validate_evaluator_capabilities(contract, invocation=invocation)
    raw_root = Path(root).expanduser()
    if raw_root.is_symlink():
        raise EvaluatorBundleError("frozen evaluator bundle must not be a symlink")
    root = raw_root.resolve(strict=False)
    if not root.is_dir():
        raise EvaluatorBundleError("frozen evaluator bundle is missing")
    if root.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
        raise EvaluatorBundleError("frozen evaluator bundle directory is writable")
    try:
        entries = tuple(root.iterdir())
    except OSError as exc:
        raise EvaluatorBundleError("frozen evaluator bundle is unreadable") from exc
    if {path.name for path in entries} != BUNDLE_FILES:
        raise EvaluatorBundleError("frozen evaluator bundle has an unexpected file set")
    for path in entries:
        if path.is_symlink() or not path.is_file():
            raise EvaluatorBundleError("frozen evaluator bundle contains an unsafe file")
        if path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
            raise EvaluatorBundleError("frozen evaluator bundle file is writable")
    manifest_path = root / "manifest.json"
    try:
        if manifest_path.stat().st_size > 16 * 1024:
            raise EvaluatorBundleError("frozen evaluator manifest exceeds the bounded size")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EvaluatorBundleError("frozen evaluator manifest is invalid") from exc
    expected_keys = {
        "schema_version",
        "protocol",
        "contract_sha256",
        "objective_sha256",
        "evaluator_sha256",
        "probes_sha256",
        "audit_sha256",
        "input_profile_sha256",
        "bundle_sha256",
    }
    if not isinstance(manifest, dict) or set(manifest) != expected_keys:
        raise EvaluatorBundleError("frozen evaluator manifest has an invalid shape")
    if manifest.get("schema_version") != "1" or manifest.get("protocol") != protocol:
        raise EvaluatorBundleError("frozen evaluator manifest protocol is unsupported")
    if manifest.get("contract_sha256") != contract.digest():
        raise EvaluatorBundleError("frozen evaluator contract digest does not match")
    for name, key in (
        ("objective.md", "objective_sha256"),
        ("evaluator.py", "evaluator_sha256"),
        ("probes.json", "probes_sha256"),
        ("audit.json", "audit_sha256"),
        ("input-profile.json", "input_profile_sha256"),
    ):
        if _sha256(root / name) != manifest.get(key):
            raise EvaluatorBundleError(f"frozen evaluator {name} digest does not match")
    for name, label in (("probes.json", "compiler"), ("audit.json", "audit")):
        path = root / name
        try:
            stored_suite = _parse_probe_suite(path.read_text(encoding="utf-8"), contract, label=label, invocation=invocation)
            if path.read_text(encoding="utf-8") != _canonical_probe_suite(stored_suite):
                raise EvaluatorBundleError(f"frozen evaluator {label} suite is not canonical")
        except (OSError, UnicodeDecodeError) as exc:
            raise EvaluatorBundleError(f"frozen evaluator {label} suite is invalid") from exc
    profile_path = root / "input-profile.json"
    try:
        stored_profile = json.loads(profile_path.read_text(encoding="utf-8"))
        if not isinstance(stored_profile, dict):
            raise EvaluatorBundleError("frozen evaluator input profile has an invalid shape")
        if profile_path.read_text(encoding="utf-8") != canonical_profile_json(stored_profile):
            raise EvaluatorBundleError("frozen evaluator input profile is not canonical")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, DataProfileError) as exc:
        raise EvaluatorBundleError("frozen evaluator input profile is invalid") from exc
    identity = {key: manifest[key] for key in expected_keys - {"bundle_sha256"}}
    if _dict_digest(identity) != manifest.get("bundle_sha256"):
        raise EvaluatorBundleError("frozen evaluator aggregate digest does not match")
    if input_profile is not None and profile_sha256(input_profile) != manifest.get(
        "input_profile_sha256"
    ):
        raise EvaluatorBundleError("frozen evaluator input profile digest does not match")
    try:
        source = (root / "evaluator.py").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise EvaluatorBundleError("frozen evaluator source is unreadable") from exc
    _validate_source(source)
    if invocation == "snapshot":
        _snapshot_spec(source.encode("utf-8"), timeout)
    return FrozenEvaluatorBundle(
        root=root,
        fingerprint=manifest["bundle_sha256"],
        contract_sha256=manifest["contract_sha256"],
        input_profile_sha256=manifest["input_profile_sha256"],
        timeout_seconds=timeout,
        invocation=invocation,
    )


def _parse_envelope(raw: str, contract: AlgorithmProblemContract, *, invocation="candidate") -> EvaluatorBundleEnvelope:
    if not isinstance(raw, str) or not raw.strip():
        raise EvaluatorBundleError("evaluator compiler returned empty output")
    if len(raw.encode("utf-8")) > MAX_BUNDLE_RESPONSE_BYTES:
        raise EvaluatorBundleError("evaluator compiler response exceeds the bounded size")
    if _SECRET.search(raw):
        raise EvaluatorBundleError("evaluator compiler response contains credential-like content")
    try:
        payload = _strict_json_loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise EvaluatorBundleError("evaluator compiler must return one strict JSON object") from exc
    expected = {
        "schema_version",
        "objective",
        "evaluator_source",
        "constraint_coverage",
        "probes",
        "score_order",
    }
    if not isinstance(payload, dict) or set(payload) != expected:
        raise EvaluatorBundleError("evaluator bundle envelope has an invalid shape")
    if payload["schema_version"] != "1":
        raise EvaluatorBundleError("evaluator bundle schema_version must be '1'")
    objective = _text(payload["objective"], "evaluator objective", MAX_OBJECTIVE_BYTES)
    source = _text(payload["evaluator_source"], "evaluator source", MAX_EVALUATOR_BYTES)
    _validate_source(source)
    probes = _parse_probes(payload["probes"], _required_probe_paths(contract))
    suite = _validate_probe_suite(
        payload["constraint_coverage"], probes, payload["score_order"], contract, invocation=invocation,
    )
    return EvaluatorBundleEnvelope(
        objective,
        source,
        suite.constraint_coverage,
        suite.probes,
        suite.score_order,
    )


def _parse_probe_suite(
    raw: str, contract: AlgorithmProblemContract, *, label: str = "audit", invocation="candidate",
) -> ProbeSuite:
    if not isinstance(raw, str) or not raw.strip():
        raise _SuiteResponseError(f"evaluator {label} returned empty output", "response_envelope_invalid")
    if len(raw.encode("utf-8")) > MAX_BUNDLE_RESPONSE_BYTES:
        raise _SuiteResponseError(f"evaluator {label} response exceeds the bounded size", "response_envelope_invalid")
    if _SECRET.search(raw):
        raise _SuiteResponseError(
            f"evaluator {label} response contains credential-like content", "response_envelope_invalid"
        )
    try:
        payload = _strict_json_loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise _SuiteResponseError(
            f"evaluator {label} must return one strict JSON object", "response_envelope_invalid"
        ) from exc
    expected = {"schema_version", "constraint_coverage", "probes", "score_order"}
    if not isinstance(payload, dict) or set(payload) != expected:
        raise _SuiteResponseError(f"evaluator {label} suite has an invalid shape", "response_envelope_invalid")
    if payload["schema_version"] != "1":
        raise _SuiteResponseError(f"evaluator {label} schema_version must be '1'", "response_envelope_invalid")
    required_probe_paths = _required_probe_paths(contract)
    try:
        probes = _parse_probes(payload["probes"], required_probe_paths)
    except EvaluatorBundleError as exc:
        raise _SuiteResponseError(str(exc), "response_probes_invalid") from exc
    try:
        return _validate_probe_suite(
            payload["constraint_coverage"], probes, payload["score_order"], contract,
            label=label, invocation=invocation,
        )
    except EvaluatorBundleError as exc:
        raise _SuiteResponseError(str(exc), "response_suite_invalid") from exc


def _required_probe_paths(contract: AlgorithmProblemContract) -> frozenset[str]:
    return frozenset(
        [
            *(f"data/raw/{item.path}" for item in contract.inputs),
            *(item.path for item in contract.outputs if item.required),
        ]
    )


def _output_constraint_ids(contract, invocation):
    from .source_constraints import source_constraints

    source_ids = {item.id for item in source_constraints(contract)} if invocation == "snapshot" else set()
    return tuple(item.id for item in contract.hard_constraints if item.id not in source_ids)


def _source_check_prompt(contract, invocation):
    from .source_constraints import source_constraints

    checks = source_constraints(contract) if invocation == "snapshot" else ()
    if not checks:
        return ""
    return (
        "\n\nSource requirements are checked independently by Lunar Evolution against the verified source bundle. "
        "Do not inspect source or try to infer source structure from input/output content. "
        "The evaluator must check exactly these output constraint IDs: "
        + json.dumps(_output_constraint_ids(contract, invocation)) + ". "
        "Return constraint_coverage with exactly those IDs and one invalid probe per such ID. "
        "Do not include these independently checked source IDs in output probes/coverage: "
        + json.dumps([item.id for item in checks]) + ". "
        "At least two valid output probes and strict score ordering are still required. "
        "Output validity is combined with source checks by Lunar Evolution; do not claim source verification."
    )


def _validate_probe_suite(
    coverage_value: object,
    probes: tuple[EvaluatorProbe, ...],
    orders_value: object,
    contract: AlgorithmProblemContract,
    *,
    label: str = "evaluator",
    invocation: str = "candidate",
) -> ProbeSuite:
    validate_evaluator_capabilities(contract, invocation=invocation)
    constraint_ids = _output_constraint_ids(contract, invocation)
    coverage = _string_array(coverage_value, f"{label} constraint coverage")
    if len(coverage) != len(set(coverage)) or set(coverage) != set(constraint_ids):
        raise EvaluatorBundleError(
            f"{label} constraint coverage must exactly match hard constraints"
        )
    valid_names = {probe.name for probe in probes if probe.expected_validity == 1}
    invalid_by_constraint = [
        probe.constraint_id for probe in probes if probe.expected_validity == 0
    ]
    if len(valid_names) < 2:
        raise EvaluatorBundleError(f"{label} requires at least two valid probes")
    if sorted(value for value in invalid_by_constraint if value is not None) != sorted(
        constraint_ids
    ) or any(
        probe.constraint_id is None for probe in probes if probe.expected_validity == 0
    ):
        raise EvaluatorBundleError(
            f"{label} constraint probe coverage must exactly match hard constraints"
        )
    if any(
        probe.constraint_id is not None for probe in probes if probe.expected_validity == 1
    ):
        raise EvaluatorBundleError(f"valid {label} probes cannot name a constraint")
    orders = _parse_score_order(orders_value, valid_names)
    return ProbeSuite(coverage, probes, orders)


def _parse_probes(
    value: object, required_paths: frozenset[str]
) -> tuple[EvaluatorProbe, ...]:
    if not isinstance(value, list) or not 2 <= len(value) <= MAX_PROBES:
        raise EvaluatorBundleError("evaluator probes must be a bounded array")
    probes: list[EvaluatorProbe] = []
    total_bytes = 0
    for raw in value:
        if not isinstance(raw, dict) or set(raw) != {
            "name",
            "constraint_id",
            "expected_validity",
            "files",
        }:
            raise EvaluatorBundleError("evaluator probe has an invalid shape")
        name = _identifier(raw["name"], "evaluator probe name")
        constraint_id = raw["constraint_id"]
        if constraint_id is not None:
            constraint_id = _identifier(constraint_id, "evaluator probe constraint_id")
        validity = raw["expected_validity"]
        if validity not in {0, 1} or isinstance(validity, bool):
            raise EvaluatorBundleError("evaluator probe expected_validity must be 0 or 1")
        raw_files = raw["files"]
        if not isinstance(raw_files, list) or not 1 <= len(raw_files) <= MAX_PROBE_FILES:
            raise EvaluatorBundleError("evaluator probe files must be a bounded array")
        files: list[ProbeFile] = []
        for raw_file in raw_files:
            if not isinstance(raw_file, dict) or set(raw_file) != {"path", "content"}:
                raise EvaluatorBundleError("evaluator probe file has an invalid shape")
            path = _probe_path(raw_file["path"])
            content = _text(
                raw_file["content"], "evaluator probe content", MAX_PROBE_FILE_BYTES, strip=False
            )
            total_bytes += len(content.encode("utf-8"))
            files.append(ProbeFile(path, content))
        if len({item.path for item in files}) != len(files):
            raise EvaluatorBundleError("evaluator probe file paths must be unique")
        missing = required_paths - {item.path for item in files}
        if missing:
            raise EvaluatorBundleError(
                "evaluator probe must include every declared input and required output"
            )
        probes.append(EvaluatorProbe(name, constraint_id, validity, tuple(files)))
    if len({probe.name for probe in probes}) != len(probes):
        raise EvaluatorBundleError("evaluator probe names must be unique")
    if total_bytes > MAX_PROBE_BYTES:
        raise EvaluatorBundleError("evaluator probes exceed the aggregate content limit")
    return tuple(probes)


def _parse_score_order(value: object, valid_names: set[str]) -> tuple[ScoreOrder, ...]:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_PROBES:
        raise EvaluatorBundleError("evaluator score order must be a bounded array")
    result: list[ScoreOrder] = []
    for raw in value:
        if not isinstance(raw, dict) or set(raw) != {"better", "worse"}:
            raise EvaluatorBundleError("evaluator score order has an invalid shape")
        better = _identifier(raw["better"], "better probe")
        worse = _identifier(raw["worse"], "worse probe")
        if better == worse or better not in valid_names or worse not in valid_names:
            raise EvaluatorBundleError("score order must reference two distinct valid probes")
        result.append(ScoreOrder(better, worse))
    return tuple(result)


def _validate_source(source: str) -> None:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise EvaluatorBundleError("evaluator source is not valid Python") from exc
    has_entrypoint = False
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = (
                [alias.name.split(".", 1)[0] for alias in node.names]
                if isinstance(node, ast.Import)
                else [(node.module or "").split(".", 1)[0]]
            )
            if not names or any(name not in _ALLOWED_IMPORTS for name in names):
                raise EvaluatorBundleError("evaluator source contains a forbidden import")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and (node.func.id in _DANGEROUS_CALLS or node.func.id == "__import__")
        ):
            raise EvaluatorBundleError("evaluator source contains forbidden dynamic execution")
        if isinstance(node, ast.If) and isinstance(node.test, ast.Compare):
            rendered = ast.unparse(node.test)
            if "__name__" in rendered and "__main__" in rendered:
                has_entrypoint = True
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value.strip()
            if value.startswith(("/", "~", "../")) or "/../" in value:
                raise EvaluatorBundleError("evaluator source contains a forbidden external path")
        if isinstance(node, ast.Attribute) and (
            node.attr.startswith("__")
            or node.attr == "modules"
            or node.attr in _DANGEROUS_ATTRIBUTES
        ):
            raise EvaluatorBundleError("evaluator source contains a forbidden attribute")
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "open"
        ):
            modes = [
                argument.value
                for argument in node.args[:1]
                if isinstance(argument, ast.Constant) and isinstance(argument.value, str)
            ]
            modes.extend(
                keyword.value.value
                for keyword in node.keywords
                if keyword.arg == "mode"
                and isinstance(keyword.value, ast.Constant)
                and isinstance(keyword.value.value, str)
            )
            if any(mode not in {"r", "rt", "rb"} for mode in modes):
                raise EvaluatorBundleError("evaluator source contains a writable file open")
    if not has_entrypoint:
        raise EvaluatorBundleError("evaluator source requires a normal script entry point")


def _bundle_protocol(invocation: str) -> str:
    if invocation not in ("candidate", "snapshot"):
        raise ValueError("evaluator invocation must be candidate or snapshot")
    return SNAPSHOT_BUNDLE_PROTOCOL if invocation == "snapshot" else BUNDLE_PROTOCOL


def _snapshot_spec(source: bytes, timeout: float):
    from .candidate_evaluation_spec import CandidateEvaluationSpec

    return CandidateEvaluationSpec(
        harness_sha256=hashlib.sha256(source).hexdigest(), harness_size=len(source),
        command=(str(Path(sys.executable).resolve()), "-I"),
        evaluator_id=COMPILED_BUNDLE_EVALUATOR_ID, timeout_seconds=timeout,
        environment=(("LANG", "C.UTF-8"), ("LC_ALL", "C.UTF-8"),
                     ("PYTHONHASHSEED", "0"), ("PYTHONIOENCODING", "utf-8")),
    )


def _snapshot_request_example() -> dict[str, object]:
    """Request shape only; the contract and identity values must be supplied by the controller."""
    from .candidate_evaluation_spec import CandidateEvaluationSpec
    from .candidate_execution import CandidateExecutionInput

    illustrative_digest = "0" * 64
    evaluator = CandidateEvaluationSpec(
        harness_sha256=illustrative_digest, harness_size=1,
        command=("/illustrative/python", "-I"), evaluator_id=COMPILED_BUNDLE_EVALUATOR_ID,
        environment=(("LANG", "C.UTF-8"),), timeout_seconds=5,
    )
    return {
        "protocol": "lunar-candidate-evaluation-request-v1", "schema_version": "1",
        "observation": "evaluation-time",
        "binding": dict.fromkeys((
            "workspace_plan_sha256", "admission_sha256", "bundle_sha256",
            "source_file_table_sha256", "launch_intent_sha256", "completion_sha256",
            "contract_sha256", "evaluator_fingerprint", "input_file_table_sha256",
            "output_contract_sha256",
        ), illustrative_digest),
        "contract": {}, "evaluator": evaluator.to_dict(),
        "inputs": [CandidateExecutionInput(
            "nested/example.txt", "opaque-label", 0, hashlib.sha256(b"").hexdigest(),
        ).to_dict()],
        "outputs": [
            {"path": "output/example.json", "present": True, "size": 3,
             "sha256": hashlib.sha256(b"{}\n").hexdigest()},
            {"path": "output/optional.txt", "present": False, "size": None, "sha256": None},
        ],
    }


def _snapshot_invocation_prompt() -> str:
    example = json.dumps(_snapshot_request_example(), ensure_ascii=False, separators=(",", ":"))
    return (
        "The Python evaluator receives request.json as sys.argv[1], using protocol "
        "lunar-candidate-evaluation-request-v1, schema_version='1', and "
        "observation='evaluation-time'. Its cwd contains only evaluator.py, request.json, "
        "declared inputs/<target>, and present files at outputs[].path. The request has exactly "
        "protocol, schema_version, observation, binding, contract, evaluator, inputs, outputs. "
        "contract is the full canonical contract object supplied below; the private input profile "
        "is generation context only, not a request field.\n\n"
        "inputs is an array sorted by target. Each entry has exactly target (relative logical "
        "input name), source_label (opaque string label), size (nonnegative integer byte count), "
        "sha256 (64 lowercase hex characters). Runtime inputs[] has no path field. Read each "
        "file with Path('inputs') / item['target'], preserving all nested directories. "
        "contract.inputs[].path equals that target; profile.files[].path and probe input file "
        "paths instead use data/raw/<target>. For example, contract path nested/example.txt "
        "becomes runtime target nested/example.txt, runtime file inputs/nested/example.txt, "
        "and profile/probe path data/raw/nested/example.txt. source_label is not a file location. "
        "A zero-byte input still has a descriptor and a file; size=0 does not mean absent.\n\n"
        "outputs is an array sorted by path with one entry per declared contract output. Each "
        "entry has exactly path (string already beginning output/), present (boolean), size, "
        "sha256. Read Path(item['path']) verbatim when present is true; do not prepend output/ "
        "again. A present output has nonnegative integer size and a 64-character lowercase hex "
        "sha256. An absent output stays in the array with present=false, size=null, sha256=null "
        "and no file. Optional outputs may be absent; missing required or schema-invalid outputs "
        "fail local validation before this evaluator runs.\n\n"
        "binding contains exactly the ten digest fields shown below, each a 64-character "
        "lowercase hex identity. evaluator contains its protocol/version, source hash/byte size, "
        "command (array of strings), evaluator_id, environment (string-to-string object), "
        "positive timeout_seconds, and positive integer byte limits as shown. These are "
        "controller-supplied identity and execution metadata, not file locations or scores; "
        "do not execute command or access its interpreter path. Compute validity and objective "
        "from the declared contract and snapshot input/output contents.\n\n"
        "The following JSON illustrates field names/types only. contract={} stands for the full "
        "canonical contract, not an empty runtime contract. Example paths, labels, digests and "
        "execution settings are illustrative, not task constants or an executable request; do "
        "not copy them into evaluator code or probe declarations. The protocol/version strings "
        "and evaluator_id='compiled-bundle' are fixed.\n"
        f"Snapshot request shape (illustrative metadata; contract is expanded at runtime):\n{example}\n\n"
        "The evaluator must not read candidate source, data/raw, execution.json, or original "
        "locations. It must leave every file unchanged and create no files. It must print only "
        "one JSON report containing exactly schema_version='1', evaluator_id='compiled-bundle', "
        "validity (integer 0 or 1), quality, combined_score, detailed_scores, and error_info, at "
        f"most {MAX_REPORT_BYTES} bytes. Invalid reports must have combined_score=0 and an "
        "explanatory error_info. Probe file declarations still use data/raw/ and output/; "
        "preflight maps declared data/raw/<target> to inputs/<target>. Include no undeclared "
        "probe files. Synthetic probes are not candidate execution evidence."
    )


def _process_options(process_observer, process_released, process_exit_observed=None,
                     process_result_observed=None):
    """Keep operational process ownership separate from frozen evaluator identity."""
    options = {}
    for name, callback in (("process_observer", process_observer),
                           ("process_released", process_released),
                           ("process_exit_observed", process_exit_observed),
                           ("process_result_observed", process_result_observed)):
        if callback is not None:
            if not callable(callback):
                raise TypeError(f"{name} must be callable or None")
            options[name] = callback
    return options


def _snapshot_probe(evaluator, probe, contract, workspace, timeout, *, preparation_remaining_timeout=None,
                    stage="compiler_preflight", process_observer=None, process_released=None,
                    process_exit_observed=None, process_result_observed=None, evaluator_source_observed=None):
    """Run the actual 108 harness interface on synthetic data, without an execution record."""
    from .algorithm import MAX_REPORT_BYTES
    from .candidate_evaluation import (
        _chain,
        _format_valid,
        _Observation,
        _request_values,
        _Resources,
        _tree_names,
    )
    from .candidate_evaluation_spec import (
        candidate_output_contract_sha256,
        canonical_json,
        parse_candidate_evaluation_report,
    )
    from .candidate_execution import CandidateExecutionInput, _inputs
    from .candidate_execution_runner import _bounded_process_bytes, _Executable

    try:
        source = evaluator.read_bytes()
        if evaluator_source_observed is not None:
            evaluator_source_observed(source)
        spec = _snapshot_spec(source, timeout)
        supplied = {item.path: item.content.encode("utf-8") for item in probe.files}
        declared = {"data/raw/" + item.path for item in contract.inputs} | {item.path for item in contract.outputs}
        if set(supplied) - declared:
            raise _ProbeFailure("snapshot probe contains undeclared files", "file_set_invalid")
        descriptors = _inputs(tuple(
            CandidateExecutionInput(item.path, "synthetic_probe", len(supplied["data/raw/" + item.path]),
                                    hashlib.sha256(supplied["data/raw/" + item.path]).hexdigest())
            for item in contract.inputs
        ))
        outputs = []
        for item in sorted(contract.outputs, key=lambda output: output.path):
            content = supplied.get(item.path)
            if not _format_valid(item, content):
                raise _ProbeFailure("snapshot probe violates the declared output schema", "output_schema_invalid")
            outputs.append({"path": item.path, "present": content is not None,
                            "size": len(content) if content is not None else None,
                            "sha256": hashlib.sha256(content).hexdigest() if content is not None else None})
        input_table = [item.to_dict() for item in descriptors]
        # These opaque synthetic identities are used only to exercise the request shape. No
        # admission, launch/completion record, evaluation receipt, Store row or score is created.
        binding = {key: hashlib.sha256(("synthetic-evaluator-probe:" + key).encode()).hexdigest()
                   for key in ("workspace_plan_sha256", "admission_sha256", "bundle_sha256",
                               "source_file_table_sha256", "launch_intent_sha256", "completion_sha256")}
        binding.update(contract_sha256=contract.digest(), evaluator_fingerprint=spec.digest(),
                       input_file_table_sha256=hashlib.sha256(canonical_json(input_table)).hexdigest(),
                       output_contract_sha256=candidate_output_contract_sha256(contract.outputs))
        request = {"protocol": "lunar-candidate-evaluation-request-v1", "schema_version": "1",
                   "observation": "evaluation-time", "binding": binding, "contract": contract.to_dict(),
                   "evaluator": spec.to_dict(), "inputs": input_table, "outputs": outputs}
        _request_values(request)
        copies = {("inputs/" + name.removeprefix("data/raw/")) if name.startswith("data/raw/") else name: content
                  for name, content in supplied.items()}
        copies.update({"request.json": canonical_json(request), "evaluator.py": source})
        for name, content in copies.items():
            target = workspace / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        with _Resources() as stack:
            chain = _chain(workspace, stack)
            observed = {name: _Observation(workspace / name, len(content), stack, code="snapshot_changed")
                        for name, content in copies.items()}
            if any(item.content != copies[name] for name, item in observed.items()):
                raise _ProbeFailure("snapshot evaluator probe files changed", "evidence_changed")
            _tree_names(chain, copies)
            executable = _Executable(Path(spec.command[0]))
            stack.callback(executable.close)
            process_timeout = _preparation_timeout(timeout, preparation_remaining_timeout, stage)
            try:
                stdout, _, status, exit_code, process_reason = _bounded_process_bytes(
                    [*spec.command, "evaluator.py", "request.json"], cwd=str(workspace),
                    environment=dict(spec.environment), timeout=process_timeout,
                    output_limit=MAX_REPORT_BYTES, capture_limit=MAX_REPORT_BYTES,
                    **_process_options(process_observer, process_released, process_exit_observed),
                )
                if process_result_observed is not None:
                    process_result_observed(status, exit_code, process_reason)
            except (SolveExecutionBudgetExceeded, SolveExecutionCancelled):
                raise
            except OSError as exc:
                raise _ProbeFailure("snapshot evaluator preflight failed", "process_failed") from exc
            if status != "succeeded":
                _preparation_timeout(timeout, preparation_remaining_timeout, stage)
                raise _ProbeFailure("snapshot evaluator process failed or exceeded its limits", "process_failed")
            try:
                report = parse_candidate_evaluation_report(stdout, evaluator_id=COMPILED_BUNDLE_EVALUATOR_ID)
            except (ValueError, TypeError, RecursionError) as exc:
                raise _ProbeFailure("snapshot evaluator preflight failed", "report_invalid") from exc
            try:
                for item in observed.values():
                    item.check()
                executable.check()
                _tree_names(chain, copies)
            except (OSError, ValueError, TypeError) as exc:
                raise _ProbeFailure("snapshot evaluator preflight failed", "evidence_changed") from exc
            _preparation_timeout(timeout, preparation_remaining_timeout, stage)
        return report
    except (SolveExecutionBudgetExceeded, SolveExecutionCancelled):
        raise
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise EvaluatorBundleError("snapshot evaluator preflight failed") from exc


def _preflight(
    evaluator: Path,
    suite: ProbeSuite,
    contract: AlgorithmProblemContract,
    staging: Path,
    timeout: float,
    *,
    label: str,
    invocation: str = "candidate",
    preparation_remaining_timeout: Callable[[str], float] | None = None,
    process_observer: Callable[[int, int | None], None] | None = None,
    process_released: Callable[[int, int | None], None] | None = None,
    process_exit_observed: Callable[[int | None], None] | None = None,
    process_result_observed: Callable[[str, int | None, str | None], None] | None = None,
) -> None:
    stage = "auditor_preflight" if label == "audit" else "compiler_preflight"
    try:
        _preflight_suite(evaluator, suite, contract, staging, timeout, label=label,
                         invocation=invocation, stage=stage,
                         preparation_remaining_timeout=preparation_remaining_timeout,
                         **_process_options(process_observer, process_released, process_exit_observed,
                                            process_result_observed))
    except (SolveExecutionBudgetExceeded, SolveExecutionCancelled,
            EvaluatorPreparationError, EvaluatorPreparationWallTimeout):
        raise
    except (EvaluatorBundleError, OSError, ValueError, TypeError, KeyError, RecursionError) as exc:
        raise _local_failure(str(exc), stage, "preflight_failed") from exc


def _preflight_suite(evaluator, suite, contract, staging, timeout, *, label, invocation, stage,
                     preparation_remaining_timeout=None, process_observer=None, process_released=None,
                     process_exit_observed=None, process_result_observed=None):
    # Admit the whole suite before executing even its first probe. This is creation-time
    # validation only; loading an existing frozen bundle never replays its probes.
    for probe_index, probe in enumerate(suite.probes, 1):
        _preparation_timeout(timeout, preparation_remaining_timeout, stage)
        supplied = {item.path: item.content for item in probe.files}
        for input_index, item in enumerate(contract.inputs, 1):
            try:
                validate_input_format(item.format, supplied["data/raw/" + item.path].encode("utf-8"))
            except (DataProfileError, KeyError, UnicodeError):
                raise _local_failure(
                    f"{label} probe input violates the declared input format",
                    stage, "input_format_invalid", probe_index=probe_index, input_index=input_index,
                ) from None
    reports: dict[str, EvaluationReport] = {}
    probe_root = staging / f".{label}-preflight"
    for probe_index, probe in enumerate(suite.probes, 1):
        _preparation_timeout(timeout, preparation_remaining_timeout, stage)
        workspace = probe_root / probe.name
        workspace.mkdir(parents=True)
        if invocation == "snapshot":
            try:
                options = ({"preparation_remaining_timeout": preparation_remaining_timeout, "stage": stage}
                           if preparation_remaining_timeout is not None else {})
                options.update(_process_options(process_observer, process_released, process_exit_observed,
                                                process_result_observed))
                report = _snapshot_probe(evaluator, probe, contract, workspace, timeout, **options)
            except _ProbeFailure as exc:
                raise _local_failure(str(exc), stage, exc.reason, probe_index=probe_index) from exc
            reports[probe.name] = report
            if report.validity != probe.expected_validity:
                raise _local_failure(f"{label} constraint probe {probe.name} returned wrong validity",
                                     stage, "validity_mismatch", probe_index=probe_index)
            if probe.constraint_id is not None and not any(
                item.get("code") == probe.constraint_id for item in report.error_info
            ):
                raise _local_failure(f"{label} constraint probe {probe.name} did not report {probe.constraint_id}",
                                     stage, "constraint_code_missing", probe_index=probe_index)
            continue
        candidate = workspace / "candidate.py"
        candidate.write_text("# synthetic evaluator probe\n", encoding="utf-8")
        for item in probe.files:
            target = workspace / item.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(item.content, encoding="utf-8")
        (workspace / "execution.json").write_text(
            json.dumps(
                CandidateExecution("succeeded", 0, 0).to_dict(),
                ensure_ascii=False,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        rules = [
            {
                "output_valid": {
                    "path": output.path,
                    "format": output.format,
                    "fields": list(output.fields),
                }
            }
            for output in contract.outputs
            if output.required
        ]
        if rules:
            validator = acceptance_evaluator(
                rules[0] if len(rules) == 1 else {"all": rules}
            )
            if validator is None or not validator.evaluate("", workspace).passed:
                raise _local_failure(
                    f"{label} probe {probe.name} violates the declared output schema",
                    stage, "output_schema_invalid", probe_index=probe_index,
                )
        try:
            process_timeout = _preparation_timeout(timeout, preparation_remaining_timeout, stage)
            report = _run_evaluator(evaluator, candidate, process_timeout,
                                    **_process_options(process_observer, process_released))
        except _ProbeFailure as exc:
            if exc.reason == "process_failed":
                _preparation_timeout(timeout, preparation_remaining_timeout, stage)
            raise _local_failure(str(exc), stage, exc.reason, probe_index=probe_index) from exc
        _preparation_timeout(timeout, preparation_remaining_timeout, stage)
        if report.validity != probe.expected_validity:
            raise _local_failure(
                f"{label} constraint probe {probe.name} returned wrong validity",
                stage, "validity_mismatch", probe_index=probe_index,
            )
        if probe.constraint_id is not None and not any(
            item.get("code") == probe.constraint_id for item in report.error_info
        ):
            raise _local_failure(
                f"{label} constraint probe {probe.name} did not report {probe.constraint_id}",
                stage, "constraint_code_missing", probe_index=probe_index,
            )
        reports[probe.name] = report
    for order_index, order in enumerate(suite.score_order, 1):
        if not (
            reports[order.better].combined_score
            > reports[order.worse].combined_score
        ):
            raise _local_failure(
                f"{label} score order failed: {order.better} must beat {order.worse}",
                stage, "score_order_mismatch", order_index=order_index,
            )
    shutil.rmtree(probe_root)


def _run_evaluator(
    evaluator: Path, candidate: Path, timeout: float, *,
    process_observer: Callable[[int, int | None], None] | None = None,
    process_released: Callable[[int, int | None], None] | None = None,
) -> EvaluationReport:
    if not candidate.is_file() or candidate.is_symlink():
        raise EvaluatorBundleError("evaluator candidate path is missing or unsafe")
    process_options = _process_options(process_observer, process_released)
    command = [sys.executable, "-I", str(evaluator), str(candidate)]
    environment = {
        "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8", "PYTHONHASHSEED": "0",
        "PYTHONIOENCODING": "utf-8",
    }
    try:
        if process_options:
            from .candidate_execution_runner import _bounded_process_bytes

            stdout, stderr, status, returncode, _ = _bounded_process_bytes(
                command, cwd=str(candidate.parent), environment=environment, timeout=timeout,
                output_limit=MAX_EVALUATOR_OUTPUT_BYTES, capture_limit=MAX_EVALUATOR_OUTPUT_BYTES,
                **process_options,
            )
            if status != "succeeded":
                raise _ProbeFailure("frozen evaluator failed or exceeded its limits", "process_failed")
            completed = subprocess.CompletedProcess(
                command, returncode, stdout.decode("utf-8"), stderr.decode("utf-8"),
            )
        else:
            completed = subprocess.run(
                command, cwd=candidate.parent, env=environment,
                stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout, check=False,
            )
    except (SolveExecutionBudgetExceeded, SolveExecutionCancelled):
        raise
    except subprocess.TimeoutExpired as exc:
        raise _ProbeFailure("frozen evaluator timed out", "process_failed") from exc
    except OSError as exc:
        raise _ProbeFailure("frozen evaluator could not start", "process_failed") from exc
    except UnicodeError as exc:
        raise _ProbeFailure("frozen evaluator returned an invalid EvaluationReport", "report_invalid") from exc
    if completed.returncode != 0:
        raise _ProbeFailure("frozen evaluator exited unsuccessfully", "process_failed")
    if (
        len(completed.stdout.encode("utf-8")) > MAX_EVALUATOR_OUTPUT_BYTES
        or len(completed.stderr.encode("utf-8")) > MAX_EVALUATOR_OUTPUT_BYTES
    ):
        raise _ProbeFailure("frozen evaluator output exceeds the bounded size", "process_failed")
    try:
        payload = json.loads(completed.stdout)
        return EvaluationReport.from_dict(payload)
    except (json.JSONDecodeError, TypeError, ValueError, RecursionError) as exc:
        raise _ProbeFailure("frozen evaluator returned an invalid EvaluationReport", "report_invalid") from exc


def _candidate_evidence_snapshot(
    candidate: Path, contract: AlgorithmProblemContract
) -> dict[str, str | None]:
    """Bind evaluator-visible authoritative files so scoring cannot rewrite its own evidence."""
    raw_candidate = candidate.expanduser()
    if raw_candidate.is_symlink() or not raw_candidate.is_file():
        raise EvaluatorBundleError("evaluator candidate path is missing or unsafe")
    root = raw_candidate.parent.resolve(strict=False)
    paths = [
        raw_candidate,
        root / "execution.json",
        *(root / "data" / "raw" / item.path for item in contract.inputs),
        *(root / item.path for item in contract.outputs),
    ]
    snapshot: dict[str, str | None] = {}
    for path in paths:
        resolved = path.resolve(strict=False)
        try:
            relative = resolved.relative_to(root).as_posix()
        except ValueError as exc:
            raise EvaluatorBundleError("candidate evidence escapes its workspace") from exc
        if path.is_symlink():
            raise EvaluatorBundleError("candidate evidence contains a symlink")
        current = path
        while current != root:
            if current.is_symlink():
                raise EvaluatorBundleError("candidate evidence contains a symlink")
            current = current.parent
        if not path.exists():
            snapshot[relative] = None
            continue
        if not path.is_file():
            raise EvaluatorBundleError("candidate evidence is not a regular file")
        snapshot[relative] = _sha256(path)
    return snapshot


def _manifest(
    contract: AlgorithmProblemContract,
    objective: Path,
    evaluator: Path,
    probes: Path,
    audit: Path,
    input_profile: Path,
    *,
    invocation: str = "candidate",
) -> dict[str, str]:
    identity = {
        "schema_version": "1",
        "protocol": _bundle_protocol(invocation),
        "contract_sha256": contract.digest(),
        "objective_sha256": _sha256(objective),
        "evaluator_sha256": _sha256(evaluator),
        "probes_sha256": _sha256(probes),
        "audit_sha256": _sha256(audit),
        "input_profile_sha256": _sha256(input_profile),
    }
    return {**identity, "bundle_sha256": _dict_digest(identity)}


def _build_input_profile(
    root: Path,
    contract: AlgorithmProblemContract,
    inputs: tuple[CandidateInputArtifact, ...],
) -> dict[str, object]:
    try:
        return build_private_input_profile(root, contract, inputs)
    except DataProfileError as exc:
        raise EvaluatorBundleError(str(exc)) from exc


def _response_example(*, compiler: bool) -> dict[str, object]:
    """Wire shape only: every source, path and content placeholder needs task semantics."""
    example = {
        "schema_version": "1",
        "constraint_coverage": ["constraint-id"],
        "probes": [
            {"name": name, "constraint_id": None if validity else "constraint-id",
             "expected_validity": validity,
             "files": [
                 {"path": "data/raw/<declared-input>", "content": "<synthetic input text>"},
                 {"path": "output/<declared-output>", "content": "<synthetic output text>"},
             ]}
            for name, validity in (("valid-better", 1), ("valid-worse", 1), ("violates-constraint", 0))
        ],
        "score_order": [{"better": "valid-better", "worse": "valid-worse"}],
    }
    if compiler:
        example.update(objective="<validity and scoring definition>",
                       evaluator_source="<complete Python script as a JSON string>")
    return example


def _report_examples() -> dict[str, object]:
    """Both examples pass the report parser; values are illustrative, never task scores."""
    return {
        "valid": {
            "schema_version": "1", "evaluator_id": COMPILED_BUNDLE_EVALUATOR_ID,
            "validity": 1, "quality": 1, "combined_score": 1,
            "detailed_scores": {"objective": {"value": 1, "direction": "maximize"}},
            "error_info": [],
        },
        "invalid": {
            "schema_version": "1", "evaluator_id": COMPILED_BUNDLE_EVALUATOR_ID,
            "validity": 0, "quality": None, "combined_score": 0, "detailed_scores": {},
            "error_info": [{"code": "constraint-id", "message": "Constraint violation."}],
        },
    }


def _response_protocol_prompt(contract, *, invocation: str, compiler: bool) -> str:
    coverage = _output_constraint_ids(contract, invocation)
    required = sorted(_required_probe_paths(contract))
    allowed = sorted({*("data/raw/" + item.path for item in contract.inputs),
                      *(item.path for item in contract.outputs)})
    response = json.dumps(_response_example(compiler=compiler), ensure_ascii=False, separators=(",", ":"))
    extra = (
        "objective and evaluator_source are nonempty JSON strings, respectively at most "
        f"{MAX_OBJECTIVE_BYTES} and {MAX_EVALUATOR_BYTES} UTF-8 bytes. "
        "evaluator_source holds a complete script, with newlines escaped within the JSON string. "
        if compiler else "Return only the probe suite; no objective or evaluator_source fields. "
    )
    return (
        "\n\nResponse shape (replace every placeholder with task-specific values):\n"
        + response + "\n"
        "The example specifies types, not an answer or a ready-made probe set. Return exactly the "
        "shown field names at every level; no extra fields, duplicate keys, Markdown or prose. "
        "schema_version is the string '1'. JSON numbers must be finite. "
        + extra
        + f"The complete response is at most {MAX_BUNDLE_RESPONSE_BYTES} UTF-8 bytes. "
        "constraint_coverage is an array of distinct strings containing exactly these IDs: "
        + json.dumps(coverage) + ". "
        "probes is an array; each object has exactly name, constraint_id, expected_validity, files. "
        f"Use 2..{MAX_PROBES} probes with unique names matching [A-Za-z0-9][A-Za-z0-9_.-]{{0,127}}. "
        "expected_validity is integer 0 or 1, never boolean. Valid probes have constraint_id=null; "
        "each invalid probe names one output constraint ID and the evaluator must include that "
        "exact code in error_info. Supply exactly one invalid probe per coverage ID and at least "
        "two valid probes. Keep synthetic instances small while preserving every required case; "
        "do not copy the private profile's row count just to match its size. "
        f"files is an array of 1..{MAX_PROBE_FILES} objects with exactly path and content. "
        "content is nonempty file text, not a nested JSON object or a file-path reference; encode "
        "JSON/CSV/etc. as a JSON string. No NUL or credential-like content. File paths are unique "
        "within each probe. Every probe includes these paths: "
        + json.dumps(required) + ". Allowed paths are: " + json.dumps(allowed) + ". "
        f"Each content is at most {MAX_PROBE_FILE_BYTES} UTF-8 bytes, and all probe file contents "
        f"together at most {MAX_PROBE_BYTES} bytes. Even expected_validity=0 probes must satisfy "
        "the declared output format and required fields: use business-value violations, not "
        "missing required files, malformed JSON/CSV or missing declared fields. Schema validation "
        "runs before the evaluator. Do not drop a hard constraint or silently relabel it to "
        "avoid this rule. score_order is an array of objects with exactly better and worse, "
        f"between 1 and {MAX_PROBES} entries. Each pair names two distinct valid probes and "
        "requires a strictly larger combined_score for better. Use a small shared synthetic input "
        "instance for the two ordered outputs when the task allows it. One ordering pair suffices. "
        "All source requirements remain outside output probe coverage."
        + _input_format_prompt()
    )


def _input_format_prompt() -> str:
    return (
        "\n\nSynthetic input format admission: before any probe in a compiler or auditor suite "
        "executes, every declared input in every probe must pass the same format parser used "
        "for private input profiling, including expected_validity=0 probes. All inputs use UTF-8. "
        "JSON roots must be an object or an array of objects (including {} or []), never a scalar. "
        "JSONL uses one object per nonblank line; blank lines and no records are allowed. "
        "JSON/JSONL reject duplicate object keys and non-finite numbers at every nesting level. "
        "CSV requires nonempty, unique headers and every row must have the same width; "
        "a header-only CSV is allowed. Text has no record schema. "
        f"Record inputs allow at most {MAX_PROFILE_ROWS} records and {MAX_PROFILE_FIELDS} distinct "
        f"top-level fields. Field names are nonempty, at most {MAX_PROFILE_FIELD_BYTES} UTF-8 bytes, "
        "without NUL or credential-like text. JSON/JSONL nesting is at most "
        f"{MAX_PROFILE_DEPTH} levels, counting the root as 1 and each child value as one level. "
        "Probe content must still satisfy the nonempty text and byte limits above. "
        "These checks validate format only: they do not enforce business field presence, types, "
        "ranges, or object-versus-array semantics. Design the evaluator and probes from the "
        "declared task semantics. Synthetic inputs need not match private row counts, unique/null "
        "counts or inferred field types; field descriptions are not an executable schema."
    )


def _evaluation_report_prompt(invocation: str) -> str:
    identity = (
        f"evaluator_id must be exactly '{COMPILED_BUNDLE_EVALUATOR_ID}'. "
        if invocation == "snapshot" else
        f"Choose a stable safe evaluator_id; '{COMPILED_BUNDLE_EVALUATOR_ID}' is suitable. "
    )
    return (
        "\n\nReport shape examples (illustrative values, not task scores):\n"
        + json.dumps(_report_examples(), separators=(",", ":")) + "\n"
        "The evaluator prints one report object, not this example wrapper. It has exactly "
        "schema_version, evaluator_id, validity, quality, combined_score, detailed_scores, error_info. "
        "schema_version is '1'; validity is integer 0 or 1, never boolean. "
        + identity
        + "combined_score is finite, nonnegative and higher-is-better, and must equal 0 when "
        "validity=0. quality is null or a finite nonnegative number; use null when unavailable. "
        "For invalid outputs use quality=null and at least one error. Define the score mapping "
        "from independently recomputed objective values; do not negate a minimization cost into "
        "a negative combined_score. detailed_scores is an object keyed by safe metric names, "
        f"at most {MAX_METRICS} entries. Each value has exactly value (finite number, may be "
        "negative) and direction ('maximize' or 'minimize'). error_info is an array of at most "
        f"{MAX_ERROR_INFO} objects with exactly code (safe identifier) and message (nonempty text, "
        "at most 512 UTF-8 bytes). Use empty objects/arrays where appropriate, never scalar "
        "detailed_scores or string errors. Identifiers use letters, digits, underscore, dot or "
        "hyphen; start with a letter or digit and keep at most 128 characters. "
        f"The entire report is at most {MAX_REPORT_BYTES} UTF-8 bytes. No NaN, Infinity, booleans "
        "as numbers, extra output or log text on stdout. Use json.dumps(..., allow_nan=False). "
        "On each invalid probe, include its constraint_id as one error code."
    )


def _source_policy_prompt() -> str:
    return (
        "\n\nEvaluator source policy: only deterministic standard-library code with imports from "
        + json.dumps(sorted(_ALLOWED_IMPORTS)) + ". Other standard-library modules are rejected. "
        "Read declared files with pathlib.Path.read_text/read_bytes or Path.open in r/rt/rb mode; "
        "the built-in open function is rejected even for reads. Do not create, change or delete "
        "files, execute/import candidate code, start processes, access the network or use external "
        "paths. Include if __name__ == '__main__': and a normal script entry point. "
        "The static validator forbids direct calls to "
        + json.dumps(sorted(_DANGEROUS_CALLS | {"__import__"})) + ". It also rejects attributes "
        "starting with '__', the attribute 'modules', and any attribute named "
        + json.dumps(sorted(_DANGEROUS_ATTRIBUTES)) + ", even on strings or other benign objects. "
        "Every stripped string literal starting with '/', '~' or '../', or containing '/../', "
        "is rejected as an external path even when it is not used as a filename. "
        "Use simple explicit parsing, loops and dictionaries within these restrictions. "
        "Reject invalid submitted values explicitly and recompute summaries/objectives from inputs."
    )


def _compiler_prompt(
    contract: AlgorithmProblemContract, input_profile: dict[str, object], *, invocation: str = "candidate",
) -> str:
    context = json.dumps(contract.to_dict(), ensure_ascii=False, sort_keys=True, indent=2)
    profile = json.dumps(input_profile, ensure_ascii=False, sort_keys=True, indent=2)
    profile_digest = profile_sha256(input_profile)
    prompt = (
        "You are compiling one frozen local evaluator bundle for a bounded algorithm evolution. "
        "Return exactly one JSON object with schema_version='1', objective, evaluator_source, "
        "constraint_coverage, probes, and score_order. The Python evaluator receives a candidate "
        "path whose sibling workspace already contains verified data/raw, output, and "
        "execution.json. It must independently recompute every hard constraint and objective from "
        "those files, print exactly one strict EvaluationReport, use only deterministic standard "
        "library modules allowed by the source policy below, and include an if __name__ == '__main__' "
        "entry point. combined_score is "
        "always higher-is-better. Provide exactly one expected_validity=0 synthetic probe per hard "
        "constraint with matching constraint_id/error_info.code, at least two valid probes, and at "
        "least one strict better/worse score_order assertion. Probe files may exist only under "
        "data/raw/ or output/. Do not return markdown, commands, credentials, or external paths.\n\n"
        "The private input profile contains structural counts and types only. Use observed fields "
        "to align parsing, but do not infer business semantics or constraints from missing values. "
        "Construct small synthetic input/output values from the declared business semantics for "
        "probes; they are not the private dataset and need not reproduce its row counts.\n\n"
        f"Canonical contract:\n{context}\n\n"
        f"Private input profile SHA-256: {profile_digest}\n"
        f"Private input profile:\n{profile}"
    )
    if invocation == "snapshot":
        prompt = prompt.replace(
            "The Python evaluator receives a candidate path whose sibling workspace already contains verified data/raw, output, and execution.json.",
            _snapshot_invocation_prompt(),
            1,
        )
    scope_prompt = _source_check_prompt(contract, invocation)
    if scope_prompt:
        # Replace only fixed instructions, never user-supplied contract/profile strings.
        header, context_section = prompt.split("Canonical contract:\n", 1)
        header = header.replace("every hard constraint", "every output constraint")
        header = header.replace("per hard constraint", "per output constraint")
        prompt = header + "Canonical contract:\n" + context_section
    return (prompt + scope_prompt + _response_protocol_prompt(contract, invocation=invocation, compiler=True)
            + _evaluation_report_prompt(invocation) + _source_policy_prompt())


def _compile_audit_suite(
    runtime: Runtime | BundleRuntime,
    contract: AlgorithmProblemContract,
    input_profile: dict[str, object],
    objective: str,
    evaluator_source: str,
    root: Path,
    timeout: float,
    *,
    invocation: str = "candidate",
    continuation_guard: Callable[[], None] | None = None,
    preparation_remaining_timeout: Callable[[str], float] | None = None,
) -> ProbeSuite:
    workspace = root / ".evaluator-auditor"
    if workspace.is_symlink():
        raise EvaluatorBundleError("evaluator auditor workspace must not be a symlink")
    workspace.mkdir(parents=True, exist_ok=True)
    if continuation_guard is not None:
        continuation_guard()
    prompt = _auditor_prompt(contract, input_profile, objective, evaluator_source, invocation=invocation)
    request_limit = _preparation_timeout(timeout, preparation_remaining_timeout, "evaluator_audit")
    try:
        result = _run_isolated(
            runtime,
            prompt,
            workspace,
            request_limit,
        )
    except (SolveExecutionBudgetExceeded, SolveExecutionCancelled):
        raise
    except Exception as exc:
        _request_after_failure(preparation_remaining_timeout, "evaluator_audit", exc)
        raise EvaluatorBundleRuntimeError(
            "evaluator_audit", request_failure=project_evaluator_request_failure(exc),
        ) from exc
    if continuation_guard is not None:
        continuation_guard()
    _preparation_timeout(timeout, preparation_remaining_timeout, "evaluator_audit")
    try:
        if not isinstance(result, RuntimeResult):
            raise EvaluatorBundleError("evaluator auditor returned an invalid runtime result")
        return _parse_probe_suite(result.text, contract, invocation=invocation)
    except _SuiteResponseError as exc:
        raise _local_failure(str(exc), "auditor_response", exc.reason) from exc
    except (EvaluatorBundleError, ValueError, TypeError, RecursionError) as exc:
        raise _local_failure(str(exc), "auditor_response", "response_invalid") from exc


def _run_isolated(
    runtime: Runtime | BundleRuntime,
    prompt: str,
    workspace: Path,
    timeout: float,
) -> RuntimeResult:
    isolated = getattr(runtime, "run_isolated", None)
    if callable(isolated):
        return isolated(prompt, workspace, timeout)
    return runtime.run(prompt, workspace, timeout)


def _auditor_prompt(
    contract: AlgorithmProblemContract,
    input_profile: dict[str, object],
    objective: str,
    evaluator_source: str,
    *,
    invocation: str = "candidate",
) -> str:
    context = json.dumps(contract.to_dict(), ensure_ascii=False, sort_keys=True, indent=2)
    profile = json.dumps(input_profile, ensure_ascii=False, sort_keys=True, indent=2)
    prompt = (
        "You are an independent adversarial evaluator auditor. Attack the supplied frozen evaluator "
        "before any solver candidate exists. Return exactly one JSON object with schema_version='1', "
        "constraint_coverage, probes, and score_order. Provide exactly one expected_validity=0 probe "
        "per hard constraint, at least two valid probes, and at least one strict better/worse score "
        "ordering. Probe boundary cases, duplicate/omitted entities, and false rejection where relevant. "
        "Each probe must include every declared input and required output, using only relative paths "
        "below data/raw/ or output/. Do not return evaluator code, fixes, markdown, credentials, commands, "
        "external paths, or prose. The private profile contains structure only: never request or "
        "attempt to recover private raw values. Construct your own small synthetic values from the "
        "declared semantics instead. You have deliberately not received the compiler's self probes.\n\n"
        f"Canonical contract:\n{context}\n\n"
        f"Private input profile SHA-256: {profile_sha256(input_profile)}\n"
        f"Private input profile:\n{profile}\n\n"
        f"Frozen objective:\n{objective}\n\n"
        f"Frozen evaluator source:\n{evaluator_source}"
    )
    if invocation == "snapshot":
        prompt = _snapshot_invocation_prompt() + "\n\n" + prompt
    scope_prompt = _source_check_prompt(contract, invocation)
    if scope_prompt:
        header, context_section = prompt.split("Canonical contract:\n", 1)
        header = header.replace("per hard constraint", "per output constraint")
        prompt = header + "Canonical contract:\n" + context_section
    return (prompt + scope_prompt + _response_protocol_prompt(contract, invocation=invocation, compiler=False)
            + _evaluation_report_prompt(invocation) + _source_policy_prompt())


def _canonical_probe_suite(suite: ProbeSuite) -> str:
    return json.dumps(
        suite.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _strict_json_loads(raw: str) -> object:
    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON object key")
            result[key] = value
        return result

    def constant(value: str) -> object:
        raise ValueError(f"non-finite JSON number: {value}")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def _probe_path(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise EvaluatorBundleError("evaluator probe path is invalid")
    path = Path(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise EvaluatorBundleError("evaluator probe path must be relative")
    relative = path.as_posix()
    if not relative.startswith(("data/raw/", "output/")):
        raise EvaluatorBundleError("evaluator probe path must be below data/raw/ or output/")
    return relative


def _identifier(value: object, field: str) -> str:
    if not isinstance(value, str) or not _SAFE_IDENTIFIER.fullmatch(value):
        raise EvaluatorBundleError(f"{field} must be a safe identifier")
    if len(value.encode("utf-8")) > MAX_IDENTIFIER_BYTES:
        raise EvaluatorBundleError(f"{field} exceeds the bounded size")
    return value


def _string_array(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, list) or len(value) > MAX_PROBES:
        raise EvaluatorBundleError(f"{field} must be a bounded string array")
    return tuple(_identifier(item, field) for item in value)


def _text(
    value: object, field: str, limit: int, *, strip: bool = True
) -> str:
    if not isinstance(value, str):
        raise EvaluatorBundleError(f"{field} must be text")
    normalized = value.strip() if strip else value
    if not normalized or "\x00" in normalized:
        raise EvaluatorBundleError(f"{field} must be non-empty text")
    if len(normalized.encode("utf-8")) > limit:
        raise EvaluatorBundleError(f"{field} exceeds the bounded size")
    if _SECRET.search(normalized):
        raise EvaluatorBundleError(f"{field} contains credential-like content")
    return normalized


def _timeout(value: float) -> float:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(float(value))
        or value <= 0
    ):
        raise ValueError("evaluator bundle timeout must be positive")
    return float(value)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _dict_digest(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _remove_tree(path: Path) -> None:
    """Remove a private staging tree even after it was made read-only for final verification."""
    if not path.exists() and not path.is_symlink():
        return
    try:
        if path.is_dir() and not path.is_symlink():
            path.chmod(0o700)
            for child in path.rglob("*"):
                if child.is_dir() and not child.is_symlink():
                    child.chmod(0o700)
                elif child.exists() and not child.is_symlink():
                    child.chmod(0o600)
    except OSError:
        pass
    shutil.rmtree(path, ignore_errors=True)


__all__ = [
    "EvaluatorBundleError",
    "EvaluatorBundleRuntimeError",
    "EvaluatorPreparationError",
    "EvaluatorPreparationWallTimeout",
    "FrozenEvaluatorBundle",
    "SolverScoringContract",
    "compile_evaluator_bundle",
    "load_evaluator_bundle",
]
