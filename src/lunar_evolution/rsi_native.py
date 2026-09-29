"""Bounded native RSI execution with retained evidence and independent re-evaluation.

Host-owned profiles supply the contract, exact evaluator and local candidate factory.  This
adapter runs one multi-file proposal through the native population pipeline.  Verification
reopens native evidence and runs the proposal and evaluator again in fresh retained workspaces.
It provides process/workspace separation, not an OS security sandbox or a transfer-effect claim.
"""
from __future__ import annotations

import hashlib
import inspect
import math
import os
import re
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, is_dataclass, replace
from pathlib import Path

from . import _benchmark_files as files
from ._candidate_workspace_io import DirectoryChain
from .automatic_solve_lifecycle import SolveExecutionCancelled
from .bundle_evolution import MultiFileCandidatePipeline, _ensure_private_directory, _runner_digest
from .candidate_bundle import parse_candidate_source_bundle, verify_candidate_source_bundle
from .candidate_evaluation import inspect_candidate_evaluation
from .candidate_evaluation_spec import candidate_output_contract_sha256, canonical_json, strict_json
from .candidate_execution import admit_candidate_execution
from .candidate_execution_evidence import inspect_candidate_execution_record
from .candidate_workspace_plan import parse_candidate_workspace_plan
from .evolution import CandidateDraft, EvolutionConfig, EvolutionContext, PopulationStrategy
from .rsi_budget import RSIRunBudget
from .rsi_gateway import SolverRequest, SolverResult
from .rsi_learning import PracticeEpisode, RSILearningError, VerifierCheck, VerifierDecision

_MAX = 128 * 1024
_PROTOCOL = "lunar-rsi-native-v1"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def _fail(code: str) -> None:
    raise RSILearningError("rsi_native_" + code)


def _json(value: object) -> bytes:
    return canonical_json(value, maximum=_MAX)


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _hash(value: object) -> str:
    return _sha(_json(value))


def _read(path: Path, maximum: int = _MAX) -> bytes:
    return files.read_regular_file(files.absolute_path(path), maximum)


def _record(path: Path) -> dict:
    raw = _read(path)
    result = strict_json(raw, maximum=_MAX)
    if not isinstance(result, dict) or _json(result) != raw:
        _fail("record_invalid")
    return result


def _relative(value: str) -> str:
    if (type(value) is not str or not value or "\\" in value or "\x00" in value
            or Path(value).is_absolute() or any(p in {"", ".", ".."} for p in value.split("/"))):
        _fail("path_invalid")
    return value


def _at(root: Path, value: str) -> Path:
    return root / _relative(value)


def _node(path: Path) -> dict:
    """Hash one retained regular file and recheck its inode/size around the read."""
    before = path.lstat()
    if not path.is_file() or path.is_symlink():
        _fail("material_invalid")
    raw = _read(path, 64 * 1024 * 1024)
    after = path.lstat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns
    ) or len(raw) != after.st_size:
        _fail("material_changed")
    return {"size": len(raw), "sha256": _sha(raw), "device": after.st_dev, "inode": after.st_ino}


def _stable_value(value: object, depth: int = 0):
    if depth > 16:
        _fail("actor_fingerprint_required")
    if value is None or type(value) in {str, bool, int, float}:
        return value
    if isinstance(value, Path):
        return {"path": str(value)}
    if type(value) in {list, tuple}:
        return [_stable_value(item, depth + 1) for item in value]
    if type(value) is dict and all(type(key) is str for key in value):
        return {key: _stable_value(item, depth + 1) for key, item in value.items()}
    if inspect.isclass(value):
        try:
            source = inspect.getsource(value)
        except (OSError, TypeError):
            _fail("actor_fingerprint_required")
        return {"class": f"{value.__module__}.{value.__qualname__}", "source": source}
    if is_dataclass(value):
        return {"dataclass": f"{type(value).__module__}.{type(value).__qualname__}",
                "value": _stable_value(asdict(value), depth + 1)}
    _fail("actor_fingerprint_required")


def _callable_fingerprint(value: object) -> str:
    supplied = getattr(value, "fingerprint", None)
    if callable(supplied):
        result = supplied()
        if type(result) is str and re.fullmatch(r"[0-9a-f]{64}", result):
            return result
        _fail("actor_fingerprint_invalid")
    if not inspect.isfunction(value):
        _fail("actor_fingerprint_required")
    try:
        source = inspect.getsource(value)
    except (OSError, TypeError):
        source = None
    payload = {"module": value.__module__, "qualname": value.__qualname__,
               "source": source, "bytecode": value.__code__.co_code.hex(),
               "constants": _stable_value(list(value.__code__.co_consts)),
               "defaults": _stable_value(value.__defaults__),
               "kwdefaults": _stable_value(value.__kwdefaults__),
               "closure": [_stable_value(cell.cell_contents) for cell in (value.__closure__ or ())]}
    return _hash({"protocol": _PROTOCOL + "-actor", "callable": payload})


def _write_new(path: Path, value: dict) -> None:
    """Exclusive durable records; incomplete records are evidence and never overwritten."""
    chain = DirectoryChain(path.parent, "rsi_native_directory_changed")
    descriptor = None
    try:
        descriptor = os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=chain.fd)
        os.fsync(chain.fd)
        view = memoryview(_json(value))
        while view:
            count = os.write(descriptor, view)
            if count <= 0:
                _fail("record_write_failed")
            view = view[count:]
        os.fsync(descriptor)
        chain.check()
        os.fsync(chain.fd)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        chain.close()


def native_dependency_fingerprint(root: str | Path, paths: Sequence[str] = ()) -> str:
    """Hash explicit dependency bytes, including a meaningful empty dependency manifest."""
    root = files.absolute_path(root)
    names = tuple(_relative(item) for item in paths)
    if len(names) > 32 or len(set(names)) != len(names):
        _fail("dependencies_invalid")
    records = []
    for name in sorted(names):
        content = _read(root / name, 16 * 1024 * 1024)
        records.append({"path": name, "size": len(content), "sha256": _sha(content)})
    return _hash({"protocol": _PROTOCOL + "-dependencies", "files": records})


def native_environment_fingerprint(pipeline: MultiFileCandidatePipeline) -> str:
    """Bind actual executables and both declared process environments; no OS closure claim."""
    profiles = []
    for command, environment in ((pipeline.command, pipeline.environment),
                                 (pipeline.evaluator.command, pipeline.evaluator.environment)):
        executable = Path(command[0]).resolve(strict=True)
        content = _read(executable, 64 * 1024 * 1024)
        profiles.append({"command": list(command), "environment": dict(environment),
                         "executable_sha256": _sha(content), "executable_size": len(content)})
    return _hash({"protocol": _PROTOCOL + "-environment", "profiles": profiles})


@dataclass(frozen=True)
class NativeEvaluationProfile:
    """Host-owned local execution authority, separate from Actor-provided results."""

    contract: object
    pipeline: MultiFileCandidatePipeline
    dependency_root: Path
    dependency_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "dependency_root", files.absolute_path(self.dependency_root))
        object.__setattr__(self, "dependency_paths", tuple(_relative(item) for item in self.dependency_paths))

    def fingerprint(self) -> str:
        return _hash({
            "protocol": _PROTOCOL + "-profile",
            "contract_sha256": self.contract.digest(),
            "evaluator_sha256": self.pipeline.evaluator.digest(),
            "runner_fingerprint": self.pipeline.runner_fingerprint,
            "harness_path": str(self.pipeline.harness_path),
            "input_root": str(self.pipeline.input_root),
            "environment_sha256": native_environment_fingerprint(self.pipeline),
            "dependency_sha256": native_dependency_fingerprint(self.dependency_root, self.dependency_paths),
            "dependency_root": str(self.dependency_root),
            "dependency_paths": list(self.dependency_paths),
        })

    def validate(self, request: SolverRequest) -> None:
        if request.solver_id != "native_population":
            _fail("solver_mismatch")
        if self.contract.digest() != request.contract_sha256:
            _fail("contract_mismatch")
        if self.pipeline.evaluator.digest() != request.evaluator_sha256:
            _fail("evaluator_mismatch")
        if (native_environment_fingerprint(self.pipeline) != request.environment_sha256
                or self.pipeline.environment_sha256 != request.environment_sha256):
            _fail("environment_mismatch")
        dependency = native_dependency_fingerprint(self.dependency_root, self.dependency_paths)
        if dependency != self.pipeline.dependency_sha256:
            _fail("dependency_mismatch")
        settings = dict(request.solver_settings)
        if settings and settings != {"dependency_sha256": dependency}:
            _fail("settings_unsupported")
        self.pipeline.preflight()

    def context(self, root: Path) -> EvolutionContext:
        # Reconstruct a separate pipeline so operational callbacks cannot leak between actor
        # and verifier.  Exact evaluator and execution declarations remain unchanged.
        p = self.pipeline
        pipeline = MultiFileCandidatePipeline(
            evaluator=p.evaluator, harness_path=p.harness_path, input_root=p.input_root,
            inputs=p.inputs, command=p.command, dependency_sha256=p.dependency_sha256,
            environment_sha256=p.environment_sha256, environment=p.environment,
            timeout_seconds=p.timeout_seconds, max_output_bytes=p.max_output_bytes,
        )
        config = pipeline.configure(EvolutionConfig(
            population_size=1, offspring_per_iteration=1, max_rounds=1,
            timeout_seconds=p.timeout_seconds + p.evaluator.timeout_seconds,
        ))
        return EvolutionContext(self.contract, root, lambda _: None, pipeline,
                                config=config, bundle_pipeline=pipeline)


def _result_from(value: dict) -> SolverResult:
    expected = {"protocol", "request", "result", "candidate_descriptor"}
    if set(value) != expected or value["protocol"] != _PROTOCOL:
        _fail("result_invalid")
    payload = value["result"]
    if not isinstance(payload, dict) or payload.get("trace_events") != []:
        _fail("result_invalid")
    result = SolverResult(
        payload["episode_id"], payload["request_sha256"], payload["status"],
        payload["candidate_receipt_sha256"], payload["execution_receipt_sha256"],
        payload["official_evaluation_receipt_sha256"], payload["trace_digest"],
        payload["solver_score"], payload["terminal_reason"],
        tuple(sorted(payload["solver_provenance"].items())), payload["candidate_source_sha256"],
        payload["dependency_sha256"], actor_fingerprint=payload["actor_fingerprint"],
    )
    if result.to_dict() != payload:
        _fail("result_invalid")
    return result


def _inspect(profile: NativeEvaluationProfile, root: Path, request: SolverRequest,
             result: SolverResult, *, expected_gateway_fingerprint: str | None = None):
    profile.validate(request)
    stored = _record(root / "native-result.json")
    if stored["request"] != request.to_dict() or _result_from(stored).to_dict() != result.to_dict():
        _fail("result_mismatch")
    intent = _record(root / "native-intent.json")
    if (set(intent) != {"protocol", "request", "gateway_fingerprint"}
            or intent["protocol"] != _PROTOCOL or intent["request"] != request.to_dict()
            or type(intent["gateway_fingerprint"]) is not str
            or not re.fullmatch(r"[0-9a-f]{64}", intent["gateway_fingerprint"])
            or (expected_gateway_fingerprint is not None
                and intent["gateway_fingerprint"] != expected_gateway_fingerprint)):
        _fail("request_mismatch")
    receipt_path = root / "native-candidate.json"
    if stored["candidate_descriptor"] != _node(receipt_path):
        _fail("candidate_replaced")
    receipt = _record(receipt_path)
    if set(receipt) != {"protocol", "request_sha256", "source_root", "run_root", "evaluation_path", "files"} or receipt["protocol"] != _PROTOCOL:
        _fail("candidate_invalid")
    if not isinstance(receipt["files"], dict) or not 4 <= len(receipt["files"]) <= 67:
        _fail("materials_invalid")
    nodes = [(item.get("device"), item.get("inode")) for item in receipt["files"].values()]
    if len(set(nodes)) != len(nodes):
        _fail("material_reused")
    if result.candidate_receipt_sha256 != _sha(_read(receipt_path)):
        _fail("candidate_mismatch")
    if receipt["request_sha256"] != request.digest():
        _fail("request_mismatch")
    source = _at(root, receipt["source_root"])
    run = _at(root, receipt["run_root"])
    for relative, descriptor in receipt["files"].items():
        if _node(_at(root, relative)) != descriptor:
            _fail("material_changed")
    bundle = parse_candidate_source_bundle(strict_json(_read(source / "bundle-manifest.json")))
    if bundle.digest() != result.candidate_source_sha256 or result.actor_fingerprint is None:
        _fail("source_mismatch")
    verify_candidate_source_bundle(bundle, source_root=source, contract_sha256=request.contract_sha256,
                                   expected_bundle_sha256=result.candidate_source_sha256)
    sources = {item.path: _read(source / item.path, item.size).decode("utf-8") for item in bundle.files}
    plan = parse_candidate_workspace_plan(run / "plan.json")
    admission = admit_candidate_execution(
        _read(run / "admission.json"), plan=plan, expected_bundle_sha256=bundle.digest(),
        expected_contract_sha256=request.contract_sha256,
    ).admission
    p = profile.pipeline
    if (admission.evaluator != p.evaluator.pin() or admission.dependency_sha256 != p.dependency_sha256
            or admission.dependency_sha256 != result.dependency_sha256
            or admission.environment_sha256 != request.environment_sha256
            or _runner_digest(plan, admission.inputs) != p.runner_fingerprint
            or admission.output_contract_sha256 != candidate_output_contract_sha256(profile.contract.outputs)):
        _fail("authority_mismatch")
    execution = inspect_candidate_execution_record(
        run / "attempt", plan=plan, admission=admission,
        expected_completion_sha256=result.execution_receipt_sha256,
    )
    if (execution.status != "recorded" or execution.cleanup_status != "verified"
            or execution.to_dict().get("runner_result", {}).get("status") != "succeeded"):
        _fail("execution_invalid")
    evaluation = inspect_candidate_evaluation(
        _at(root, receipt["evaluation_path"]),
        expected_evaluation_sha256=result.official_evaluation_receipt_sha256,
    )
    expected_binding = {
        "workspace_plan_sha256": plan.digest(), "admission_sha256": admission.digest(),
        "bundle_sha256": bundle.digest(), "contract_sha256": request.contract_sha256,
        "evaluator_fingerprint": request.evaluator_sha256,
        "launch_intent_sha256": execution.launch_intent_sha256,
        "completion_sha256": execution.completion_sha256,
        "source_file_table_sha256": plan.file_table_sha256,
        "input_file_table_sha256": _hash([item.to_dict() for item in admission.inputs]),
        "output_contract_sha256": admission.output_contract_sha256,
    }
    if evaluation.to_dict()["binding"] != expected_binding:
        _fail("evaluation_binding_mismatch")
    if result.solver_score != evaluation.report.combined_score:
        _fail("score_mismatch")
    expected_files = {str((source / item.path).relative_to(root)) for item in bundle.files}
    expected_files.update(str(path.relative_to(root)) for path in
                          (source / "bundle-manifest.json", run / "plan.json", run / "admission.json"))
    if set(receipt["files"]) != expected_files:
        _fail("materials_invalid")
    # Every retained descriptor is checked again after all reads.  This closes a mutation window
    # where a source could be replaced after its first byte/inode observation.
    for relative, descriptor in receipt["files"].items():
        if _node(_at(root, relative)) != descriptor:
            _fail("material_changed")
    if _node(receipt_path) != stored["candidate_descriptor"]:
        _fail("candidate_changed")
    return bundle, sources, evaluation


def _episode_root(root: Path, episode_id: str, *, create: bool) -> Path:
    if not _SAFE_ID.fullmatch(episode_id):
        _fail("episode_id_invalid")
    if create:
        _ensure_private_directory(Path(root.anchor), tuple(root.parts[1:]))
        return _ensure_private_directory(root, ("episodes", episode_id))
    path = root / "episodes" / episode_id
    chain = DirectoryChain(path, "rsi_native_directory_changed")
    chain.close()
    return path


class NativePopulationGateway:
    """One real local native proposal per request, with exact read-only terminal retry."""

    stage_budget_accounting = frozenset({"evaluator"})

    def __init__(self, profile: NativeEvaluationProfile,
                 draft_factory: Callable[[SolverRequest], CandidateDraft], workspace_root: str | Path,
                 *, actor_fingerprint: str | None = None):
        if not isinstance(profile, NativeEvaluationProfile) or not callable(draft_factory):
            raise TypeError("a native profile and draft factory are required")
        self.profile = profile
        self.draft_factory = draft_factory
        self.workspace_root = files.absolute_path(workspace_root)
        if actor_fingerprint is not None and not re.fullmatch(r"[0-9a-f]{64}", actor_fingerprint):
            _fail("actor_fingerprint_invalid")
        self.actor_fingerprint = actor_fingerprint or _callable_fingerprint(draft_factory)

    def fingerprint(self) -> str:
        return _hash({"protocol": _PROTOCOL + "-gateway", "profile": self.profile.fingerprint(),
                      "actor_fingerprint": self.actor_fingerprint,
                      "workspace_root": str(self.workspace_root)})

    def _terminal(self, request: SolverRequest, status: str, reason: str) -> SolverResult:
        return SolverResult(request.episode_id, request.digest(), status, None, None, None,
                            _hash({"request": request.digest(), "status": status}), terminal_reason=reason,
                            solver_provenance=(("backend", "native_population"), ("fixture", False)),
                            actor_fingerprint=self.actor_fingerprint)

    def run(self, request: SolverRequest) -> SolverResult:
        root = _episode_root(self.workspace_root, request.episode_id, create=True)
        result_path, intent_path = root / "native-result.json", root / "native-intent.json"
        intent = {"protocol": _PROTOCOL, "request": request.to_dict(),
                  "gateway_fingerprint": self.fingerprint()}
        if intent_path.exists() or intent_path.is_symlink():
            if _record(intent_path) != intent:
                _fail("request_reuse")
            if not result_path.exists():
                return self._terminal(request, "unknown", "native_incomplete_intent")
            stored = _record(result_path)
            result = _result_from(stored)
            if stored["request"] != request.to_dict():
                _fail("request_reuse")
            if result.status == "completed":
                _inspect(self.profile, root, request, result, expected_gateway_fingerprint=self.fingerprint())
            return result
        if result_path.exists() or result_path.is_symlink():
            _fail("intent_missing")
        self.profile.validate(request)
        budget = dict(request.budget)
        from .rsi_stage_accounting import accounting_available
        controller_limits = set(RSIRunBudget.create(None).state["planned"])
        if set(budget) & controller_limits and not accounting_available():
            _fail("budget_accounting_required")
        if set(budget) - {"candidate_attempts", "wall_timeout_seconds", *controller_limits}:
            _fail("budget_unsupported")
        if "candidate_attempts" in budget and (type(budget["candidate_attempts"]) is not int or budget["candidate_attempts"] < 1):
            _fail("budget_invalid")
        timeout = budget.get("wall_timeout_seconds", self.profile.pipeline.timeout_seconds + self.profile.pipeline.evaluator.timeout_seconds)
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            _fail("budget_invalid")
        _write_new(intent_path, intent)
        candidate_descriptor = None
        try:
            from .automatic_solve_lifecycle import SolveExecutionControl
            context = self.profile.context(root)
            control = SolveExecutionControl(float(timeout))
            context = replace(context, remaining_timeout=lambda stage: control.effective_timeout(stage=stage))
            strategy = PopulationStrategy(context)
            draft = self.draft_factory(request)
            if not isinstance(draft, CandidateDraft):
                _fail("draft_invalid")
            native = context.bundle_pipeline.evaluate_draft_non_publishing(
                strategy, draft, journal_id="rsi-" + request.digest()[:24], candidate_id="candidate-0",
                iteration=0, generation=0, island_id=0,
            )
            paths = [native.source_root / item.path for item in native.bundle.files]
            paths += [native.source_root / "bundle-manifest.json", native.run_root / "plan.json",
                      native.run_root / "admission.json"]
            candidate = {
                "protocol": _PROTOCOL, "request_sha256": request.digest(),
                "source_root": str(native.source_root.relative_to(root)),
                "run_root": str(native.run_root.relative_to(root)),
                "evaluation_path": str(native.evaluation.evaluation_path.relative_to(root)),
                "files": {str(path.relative_to(root)): _node(path) for path in paths},
            }
            _write_new(root / "native-candidate.json", candidate)
            candidate_descriptor = _node(root / "native-candidate.json")
            result = SolverResult(
                request.episode_id, request.digest(), "completed", candidate_descriptor["sha256"],
                native.execution.completion_sha256, native.evaluation.digest(),
                _hash({"request": request.digest(), "candidate": native.bundle.digest()}),
                native.report.combined_score, "native_candidate_evaluated",
                (("backend", "native_population"), ("fixture", False),), native.bundle.digest(), self.profile.pipeline.dependency_sha256,
                actor_fingerprint=self.actor_fingerprint,
            )
        except RSILearningError as exc:
            if exc.code.startswith(("rsi_budget_", "rsi_stage_")):
                raise
            result = self._terminal(request, "unknown", "native_evidence_incomplete")
        except SolveExecutionCancelled:
            result = self._terminal(request, "cancelled", "native_cancelled")
        except TimeoutError:
            result = self._terminal(request, "timed_out", "native_timeout")
        except Exception:  # noqa: BLE001 - preserve partial native evidence, never silently replay
            result = self._terminal(request, "unknown", "native_evidence_incomplete")
        _write_new(result_path, {"protocol": _PROTOCOL, "request": request.to_dict(),
                                 "result": result.to_dict(), "candidate_descriptor": candidate_descriptor})
        if result.status == "completed":
            _inspect(self.profile, root, request, result, expected_gateway_fingerprint=self.fingerprint())
        return result


class NativeIndependentVerifier:
    """Read original evidence and retain a fresh candidate/evaluator rerun before passing."""

    stage_budget_accounting = frozenset({"evaluator"})

    def __init__(self, profile: NativeEvaluationProfile, workspace_root: str | Path,
                 *, verification_root: str | Path | None = None):
        self.profile = profile
        self.workspace_root = files.absolute_path(workspace_root)
        self.verification_root = files.absolute_path(verification_root or self.workspace_root / "verifications")
        self.verifier_fingerprint = self.fingerprint()

    def fingerprint(self) -> str:
        return _hash({"protocol": _PROTOCOL, "role": "independent-verifier",
                      "profile": self.profile.fingerprint(), "workspace_root": str(self.workspace_root),
                      "verification_root": str(self.verification_root)})

    def _cache_path(self, request: SolverRequest, result: SolverResult) -> Path:
        key = _hash({"request": request.to_dict(), "result": result.to_dict(),
                     "verifier": self.fingerprint()})
        return self.verification_root / ("receipt-" + key + ".json")

    def validate_retained(self, episode: PracticeEpisode, request: SolverRequest,
                          result: SolverResult, decision: VerifierDecision) -> None:
        """Read-only resume gate: inspect saved rerun evidence without executing anything."""
        self._identity(episode, request, result)
        if decision.verifier_fingerprint != self.fingerprint():
            _fail("verifier_fingerprint_drift")
        if decision.outcome != "pass":
            # A rejection/unresolved decision grants no memory authority, but its original
            # execution/evaluator receipts must still be intact on terminal resume.
            _inspect(self.profile, _episode_root(self.workspace_root, request.episode_id, create=False), request, result)
            return
        original_root = _episode_root(self.workspace_root, request.episode_id, create=False)
        _, _, original = _inspect(self.profile, original_root, request, result)
        cache = _record(self._cache_path(request, result))
        if set(cache) != {"protocol", "request", "result", "decision", "verification", "receipt_node"}:
            _fail("verification_cache_invalid")
        if (cache["protocol"] != _PROTOCOL or cache["request"] != request.to_dict()
                or cache["result"] != result.to_dict() or cache["decision"] != decision.to_dict()):
            _fail("verification_cache_mismatch")
        verification = _at(self.verification_root, cache["verification"])
        receipt_path = verification / "verifier-receipt.json"
        if _node(receipt_path) != cache["receipt_node"]:
            _fail("verification_receipt_changed")
        evidence_record = _record(receipt_path)
        evidence = evidence_record["evidence"]
        if (evidence_record["protocol"] != _PROTOCOL or _hash(evidence) != decision.receipt_sha256
                or evidence != {"request": request.to_dict(), "result": result.to_dict(),
                                "checks": [check.to_dict() for check in decision.checks], "outcome": decision.outcome}):
            _fail("verification_receipt_mismatch")
        rerun_root = _episode_root(verification, request.episode_id, create=False)
        rerun = _result_from(_record(rerun_root / "native-result.json"))
        _, _, fresh = _inspect(self.profile, rerun_root, request, rerun)
        if (_json(fresh.report.to_dict()) != _json(original.report.to_dict())
                or original.report.validity != 1 or decision.outcome != "pass"):
            _fail("verification_report_mismatch")
        _inspect(self.profile, original_root, request, result)
        if _node(receipt_path) != cache["receipt_node"]:
            _fail("verification_receipt_changed")

    @staticmethod
    def _identity(episode: PracticeEpisode, request: SolverRequest, result: SolverResult) -> None:
        if (result.status != "completed" or episode.status != "completed"
                or episode.episode_id != request.episode_id or result.episode_id != request.episode_id
                or result.request_sha256 != request.digest()
                or any(getattr(episode, field) != getattr(request, field) for field in
                       ("contract_sha256", "evaluator_sha256", "environment_sha256", "memory_snapshot_sha256", "solver_id"))):
            _fail("identity_mismatch")
        for field in ("candidate_receipt_sha256", "execution_receipt_sha256", "official_evaluation_receipt_sha256"):
            if getattr(episode, field) != getattr(result, field):
                _fail("episode_evidence_mismatch")

    def verify(self, episode: PracticeEpisode, request: SolverRequest, result: SolverResult) -> VerifierDecision:
        checks = []
        fresh = None
        outcome, diagnosis = "unresolved", "native evidence could not be independently verified"
        try:
            self._identity(episode, request, result)
            if self.fingerprint() != self.verifier_fingerprint:
                _fail("verifier_fingerprint_drift")
            cache_path = self._cache_path(request, result)
            if cache_path.exists() or cache_path.is_symlink():
                value = _record(cache_path)["decision"]
                value = dict(value)
                value["checks"] = tuple(VerifierCheck(**item) for item in value["checks"])
                cached = VerifierDecision(**value)
                self.validate_retained(episode, request, result, cached)
                return cached
            root = _episode_root(self.workspace_root, request.episode_id, create=False)
            bundle, sources, evaluation = _inspect(self.profile, root, request, result)
            checks.extend((
                VerifierCheck("retained_native_evidence", "pass", result.candidate_receipt_sha256),
                VerifierCheck("official_evaluator", "pass" if evaluation.report.validity == 1 else "fail", evaluation.digest()),
            ))
            if evaluation.report.validity != 1:
                outcome, diagnosis = "fail", "official local evaluator rejected the candidate"
            else:
                _ensure_private_directory(Path(self.verification_root.anchor), tuple(self.verification_root.parts[1:]))
                chain = DirectoryChain(self.verification_root, "rsi_native_directory_changed")
                try:
                    fresh = Path(tempfile.mkdtemp(prefix="verify-", dir=self.verification_root))
                    chain.check()
                finally:
                    chain.close()
                gateway = NativePopulationGateway(self.profile, lambda _: CandidateDraft.from_files(sources, entrypoint=bundle.entrypoint), fresh,
                                                  actor_fingerprint=_hash({"verifier": self.fingerprint(), "bundle": bundle.digest()}))
                rerun = gateway.run(request)
                if rerun.status != "completed":
                    _fail("rerun_incomplete")
                _, _, rerun_evaluation = _inspect(self.profile, fresh / "episodes" / request.episode_id, request, rerun)
                if _json(rerun_evaluation.report.to_dict()) != _json(evaluation.report.to_dict()):
                    _fail("rerun_mismatch")
                # Inspect originals again after the rerun: verification cannot bless evidence
                # changed concurrently while the fresh candidate/evaluator were running.
                _inspect(self.profile, root, request, result)
                checks.append(VerifierCheck("independent_rerun", "pass", rerun.official_evaluation_receipt_sha256))
                outcome, diagnosis = "pass", "retained native evidence and independent rerun passed"
        except RSILearningError as exc:
            if exc.code.startswith(("rsi_budget_", "rsi_stage_")):
                raise
            checks.append(VerifierCheck("independent_verification", "unresolved", _hash({"request": request.digest(), "status": "unresolved"})))
        except Exception:  # noqa: BLE001 - all integrity ambiguity remains non-admitting
            checks.append(VerifierCheck("independent_verification", "unresolved", _hash({"request": request.digest(), "status": "unresolved"})))
        evidence = {"request": request.to_dict(), "result": result.to_dict(), "checks": [c.to_dict() for c in checks], "outcome": outcome}
        receipt = _hash(evidence)
        if fresh is not None:
            try:
                _write_new(fresh / "verifier-receipt.json", {"protocol": _PROTOCOL, "evidence": evidence})
            except Exception:  # noqa: BLE001 - loss of durable verification evidence cannot pass
                outcome, diagnosis = "unresolved", "independent verification receipt unavailable"
                checks.append(VerifierCheck("verification_receipt", "unresolved", receipt))
                evidence["outcome"] = outcome
                evidence["checks"] = [c.to_dict() for c in checks]
                receipt = _hash(evidence)
        decision = VerifierDecision(
            episode.episode_id, outcome, receipt, diagnosis, self.verifier_fingerprint, tuple(checks),
            contract_sha256=request.contract_sha256, evaluator_sha256=request.evaluator_sha256,
            environment_sha256=request.environment_sha256,
            official_evaluation_receipt_sha256=result.official_evaluation_receipt_sha256,
            evidence_sha256=receipt, candidate_receipt_sha256=result.candidate_receipt_sha256,
            execution_receipt_sha256=result.execution_receipt_sha256,
        )
        if outcome == "pass" and fresh is not None:
            try:
                _write_new(self._cache_path(request, result), {
                    "protocol": _PROTOCOL, "request": request.to_dict(), "result": result.to_dict(),
                    "decision": decision.to_dict(), "verification": str(fresh.relative_to(self.verification_root)),
                    "receipt_node": _node(fresh / "verifier-receipt.json"),
                })
            except Exception:  # noqa: BLE001 - a missing cache cannot authorize recovery
                return replace(decision, outcome="unresolved", diagnosis="verification cache unavailable")
        return decision


__all__ = [
    "NativeEvaluationProfile",
    "NativeIndependentVerifier",
    "NativePopulationGateway",
    "native_dependency_fingerprint",
    "native_environment_fingerprint",
]
