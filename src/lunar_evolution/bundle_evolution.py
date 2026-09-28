"""Multi-file execution and evaluation inside the existing native population loop."""
from __future__ import annotations

import hashlib
import math
import os
import re
import stat
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from . import _benchmark_files as files
from ._candidate_workspace_io import DirectoryChain, PrivateTree
from .automatic_solve_lifecycle import SolveExecutionBudgetExceeded, SolveExecutionCancelled
from .candidate_bundle import (
    MAX_CANDIDATE_BUNDLE_BYTES,
    CandidateSourceBundle,
    CandidateSourceFile,
    parse_candidate_source_bundle,
    verify_candidate_source_bundle,
)
from .candidate_evaluation import evaluate_candidate_execution, inspect_candidate_evaluation
from .candidate_evaluation_spec import (
    candidate_output_contract_sha256,
    canonical_json,
    parse_candidate_evaluation_spec,
    strict_json,
)
from .candidate_execution import (
    MAX_EXECUTION_ADMISSION_BYTES,
    CandidateExecutionBudget,
    _inputs,
    admit_candidate_execution,
    build_candidate_execution_admission,
)
from .candidate_execution_evidence import (
    inspect_candidate_execution_record,
    run_candidate_execution_recorded,
)
from .candidate_input_staging import stage_candidate_execution_inputs
from .candidate_workspace import materialize_candidate_source_bundle
from .candidate_workspace_plan import build_candidate_workspace_plan, parse_candidate_workspace_plan
from .source_constraints import validate_source_capabilities

_PROTOCOL = "lunar-population-bundle-v1"
_BUNDLE_NAME = "bundle-manifest.json"
_BINDING_FIELDS = {
    "protocol", "bundle_sha256", "bundle_path", "source_root", "run_root", "plan_sha256",
    "admission_sha256", "completion_sha256", "evaluation_path", "evaluation_sha256",
}
_DIGEST_FIELDS = {"bundle_sha256", "plan_sha256", "admission_sha256", "completion_sha256", "evaluation_sha256"}
_HEX24 = re.compile(r"^[0-9a-f]{24}$")
_DRAFT_BINDING_NAME = "draft-binding.json"
_DRAFT_BINDING_PROTOCOL = "lunar-native-draft-binding-v1"
_DRAFT_BINDING_FIELDS = {
    "protocol", "journal_id", "candidate_id", "run_id", "bundle_id", "bundle_sha256",
    "ordinal", "parent_id", "generation", "iteration", "island_id", "source_root",
    "source_identity", "run_root", "run_identity", "plan_sha256", "admission_sha256",
}


def _fail(code="invalid"):
    from .evolution import EvolutionError
    raise EvolutionError("bundle_candidate_" + code)


def _sha(content):
    return hashlib.sha256(content).hexdigest()


def validate_bundle_draft(draft, contract_sha256):
    """Validate a complete in-memory source map without recursively constructing a draft."""
    from .evolution import _RESERVED_CANDIDATE_SOURCE_BASENAMES
    try:
        sources = draft.source_files
        if sources is None:
            sources = {draft.filename: draft.source}
        if not isinstance(sources, dict) or not 1 <= len(sources) <= 64:
            _fail()
        if sources.get(draft.filename) != draft.source:
            _fail()
        declarations = []
        for name, source in sources.items():
            if not isinstance(name, str) or not isinstance(source, str) or "\x00" in source:
                _fail()
            if name == _BUNDLE_NAME or Path(name).name in _RESERVED_CANDIDATE_SOURCE_BASENAMES:
                _fail()
            content = source.encode("utf-8")
            declarations.append(CandidateSourceFile(name, len(content), _sha(content)))
        return CandidateSourceBundle(contract_sha256, draft.filename, tuple(declarations))
    except (AttributeError, TypeError, ValueError, UnicodeError, RecursionError):
        _fail()


def validate_bundle_evidence_shape(value):
    try:
        value = strict_json(canonical_json(value, maximum=4096), maximum=4096)
        if not isinstance(value, dict) or set(value) != _BINDING_FIELDS or value["protocol"] != _PROTOCOL:
            _fail()
        for name in _DIGEST_FIELDS:
            if not isinstance(value[name], str) or re.fullmatch("[0-9a-f]{64}", value[name]) is None:
                _fail()
        source = value["source_root"]
        run = value["run_root"]
        evaluation = value["evaluation_path"]
        if (not isinstance(source, str) or re.fullmatch(r"evolution/candidates/[A-Za-z0-9][A-Za-z0-9_.-]*", source) is None
                or not isinstance(run, str) or re.fullmatch(r"evolution/bundle-attempts/\.bundle-run-[0-9a-f]{24}", run) is None
                or value["bundle_path"] != source + "/" + _BUNDLE_NAME
                or not isinstance(evaluation, str)
                or re.fullmatch(re.escape(run) + r"/evaluations/\.candidate-evaluation-[0-9a-f]{24}", evaluation) is None):
            _fail()
        return value
    except (ValueError, TypeError, OverflowError, RecursionError):
        _fail()


def _read(path, maximum):
    return files.read_regular_file(files.absolute_path(path), maximum)


def _runner_digest(plan, inputs):
    return _sha(canonical_json({
        "protocol": "lunar-population-bundle-runner-v1", "command": list(plan.command),
        "environment": dict(plan.environment), "timeout_seconds": plan.timeout_seconds,
        "max_output_bytes": plan.max_output_bytes, "inputs": [item.to_dict() for item in inputs],
        "max_processes": 1,
    }))


def derive_native_draft_run_id(journal_id, candidate_id, bundle_sha256):
    """Derive the fixed native attempt suffix used by a draft-only journal evaluation."""
    if not isinstance(journal_id, str) or not journal_id or "/" in journal_id or "\\" in journal_id:
        _fail("run_id_invalid")
    if not isinstance(candidate_id, str) or not candidate_id or "/" in candidate_id or "\\" in candidate_id:
        _fail("candidate_id_invalid")
    if not isinstance(bundle_sha256, str) or re.fullmatch(r"[0-9a-f]{64}", bundle_sha256) is None:
        _fail("bundle_digest_invalid")
    return hashlib.sha256(canonical_json({
        "protocol": "lunar-native-draft-run-v1",
        "journal_id": journal_id,
        "candidate_id": candidate_id,
        "bundle_sha256": bundle_sha256,
    })).hexdigest()[:24]


def _ensure_private_directory(root: Path, parts: tuple[str, ...]) -> Path:
    """Create a workspace-relative directory tree without following a link component."""
    root = files.absolute_path(root)
    chain = DirectoryChain(root, "destination_changed")
    try:
        for name in parts:
            if not isinstance(name, str) or not name or name in {".", ".."} or "/" in name:
                _fail("destination_changed")
            try:
                before = os.stat(name, dir_fd=chain.fd, follow_symlinks=False)
            except FileNotFoundError:
                try:
                    os.mkdir(name, 0o700, dir_fd=chain.fd)
                    before = os.stat(name, dir_fd=chain.fd, follow_symlinks=False)
                except OSError:
                    _fail("destination_changed")
            if stat.S_ISLNK(before.st_mode) or not stat.S_ISDIR(before.st_mode):
                _fail("destination_changed")
            try:
                child = os.open(
                    name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=chain.fd,
                )
            except OSError:
                _fail("destination_changed")
            parent = chain.fd
            chain.fds.append(child)
            chain.links.append((parent, name, child))
            observed = os.fstat(child)
            if (before.st_dev, before.st_ino) != (observed.st_dev, observed.st_ino):
                _fail("destination_changed")
            chain.check()
        return root.joinpath(*parts)
    finally:
        chain.close()


def _draft_binding(*, journal_id: str, candidate_id: str, run_id: str, bundle_id: str,
                   bundle_sha256: str, ordinal: int | None, parent_id: str | None,
                   generation: int, iteration: int, island_id: int, source_root: str,
                   source_identity: tuple[int, int], run_root: str,
                   run_identity: tuple[int, int], plan_sha256: str,
                   admission_sha256: str, journal_sha256: str | None = None) -> dict:
    value = {
        "protocol": _DRAFT_BINDING_PROTOCOL,
        "journal_id": journal_id,
        "candidate_id": candidate_id,
        "run_id": run_id,
        "bundle_id": bundle_id,
        "bundle_sha256": bundle_sha256,
        "ordinal": ordinal,
        "parent_id": parent_id,
        "generation": generation,
        "iteration": iteration,
        "island_id": island_id,
        "source_root": source_root,
        "source_identity": list(source_identity),
        "run_root": run_root,
        "run_identity": list(run_identity),
        "plan_sha256": plan_sha256,
        "admission_sha256": admission_sha256,
    }
    if journal_sha256 is not None:
        value["journal_sha256"] = journal_sha256
    return value


def _directory_identity(path: Path) -> tuple[int, int]:
    """Return a directory inode only after checking every parent without following links."""
    chain = DirectoryChain(files.absolute_path(path), "destination_changed")
    try:
        info = os.fstat(chain.fd)
        if not stat.S_ISDIR(info.st_mode):
            _fail("destination_changed")
        return info.st_dev, info.st_ino
    finally:
        chain.close()


def _safe_atomic_write(archive, path: Path, content: bytes, *, error: str) -> None:
    """Write through a held no-follow parent check before using the archive's atomic writer."""
    root = files.absolute_path(archive.root)
    absolute = files.absolute_path(path)
    try:
        relative_parent = absolute.parent.relative_to(root)
    except ValueError:
        _fail("destination_changed")
    _ensure_private_directory(root, tuple(relative_parent.parts))
    parent = DirectoryChain(absolute.parent, "destination_changed")
    try:
        if path.is_symlink() or (path.exists() and not path.is_file()):
            _fail("destination_changed")
        archive._atomic_write_bytes(path, content, error=error)
        parent.check()
    finally:
        parent.close()


@dataclass(frozen=True)
class NativeDraftEvaluationResult:
    """Retained native execution/evaluation evidence before publication."""

    candidate_id: str
    journal_id: str
    run_id: str
    bundle: CandidateSourceBundle
    source_root: Path
    run_root: Path
    plan: object
    admission: object
    execution: object
    evaluation: object
    bundle_id: str | None = None
    parent_id: str | None = None
    generation: int | None = None
    iteration: int | None = None
    island_id: int | None = None
    ordinal: int | None = None
    metadata: dict | None = None
    journal_sha256: str | None = None

    @property
    def report(self):
        return self.evaluation.report

    def to_dict(self):
        return {
            "status": "evaluated",
            "candidate_id": self.candidate_id,
            "journal_id": self.journal_id,
            "journal_sha256": self.journal_sha256,
            "run_id": self.run_id,
            "bundle_sha256": self.bundle.digest(),
            "source_root": str(self.source_root),
            "run_root": str(self.run_root),
            "plan_sha256": self.plan.digest(),
            "admission_sha256": self.admission.digest(),
            "execution": self.execution.to_dict(),
            "evaluation": self.evaluation.to_dict(),
            "bundle_id": self.bundle_id,
            "parent_id": self.parent_id,
            "generation": self.generation,
            "iteration": self.iteration,
            "island_id": self.island_id,
            "ordinal": self.ordinal,
        }


def _bundle_source(workspace, evidence, code_path):
    value = validate_bundle_evidence_shape(evidence)
    workspace = files.absolute_path(workspace)
    bundle = parse_candidate_source_bundle(strict_json(_read(workspace / value["bundle_path"], MAX_CANDIDATE_BUNDLE_BYTES)))
    if (bundle.digest() != value["bundle_sha256"]
            or code_path != value["source_root"] + "/" + bundle.entrypoint):
        _fail("source_mismatch")
    verify_candidate_source_bundle(
        bundle, source_root=workspace / value["source_root"], contract_sha256=bundle.contract_sha256,
        expected_bundle_sha256=value["bundle_sha256"],
    )
    return workspace, value, bundle


def validate_candidate_bundle_evidence(workspace, evidence, *, code_path, evaluation, authority):
    """Recheck full source, saved declarations and successful execution/evaluation before reuse."""
    from .evolution import _sanitized_evaluation
    try:
        workspace, value, bundle = _bundle_source(workspace, evidence, code_path)
        authority = authority.to_dict() if hasattr(authority, "to_dict") else dict(authority)
        run = workspace / value["run_root"]
        plan = parse_candidate_workspace_plan(run / "plan.json")
        admitted = admit_candidate_execution(
            _read(run / "admission.json", MAX_EXECUTION_ADMISSION_BYTES), plan=plan,
            expected_admission_sha256=value["admission_sha256"], expected_plan_sha256=value["plan_sha256"],
            expected_bundle_sha256=bundle.digest(), expected_contract_sha256=authority["contract_sha256"],
        ).admission
        if (admitted.evaluator.kind != authority["evaluator_kind"]
                or admitted.evaluator.fingerprint != authority["evaluator_fingerprint"]
                or admitted.dependency_sha256 != authority["dependency_sha256"]
                or admitted.environment_sha256 != authority["environment_sha256"]
                or _runner_digest(plan, admitted.inputs) != authority["runner_fingerprint"]):
            _fail("authority_mismatch")
        record = inspect_candidate_execution_record(
            run / "attempt", plan=plan, admission=admitted,
            expected_completion_sha256=value["completion_sha256"],
        )
        if record.status != "recorded" or record.to_dict()["runner_result"]["status"] != "succeeded":
            _fail("execution_invalid")
        result = inspect_candidate_evaluation(
            workspace / value["evaluation_path"], expected_evaluation_sha256=value["evaluation_sha256"],
        )
        binding = result.to_dict()["binding"]
        expected = {
            "workspace_plan_sha256": value["plan_sha256"], "admission_sha256": value["admission_sha256"],
            "bundle_sha256": bundle.digest(), "contract_sha256": authority["contract_sha256"],
            "evaluator_fingerprint": authority["evaluator_fingerprint"],
            "launch_intent_sha256": record.launch_intent_sha256, "completion_sha256": value["completion_sha256"],
            "source_file_table_sha256": plan.file_table_sha256,
            "input_file_table_sha256": _sha(canonical_json([item.to_dict() for item in admitted.inputs])),
            "output_contract_sha256": admitted.output_contract_sha256,
        }
        if binding != expected:
            _fail("evaluation_mismatch")
        if canonical_json(_sanitized_evaluation(result.report).to_dict()) != canonical_json(evaluation.to_dict()):
            _fail("evaluation_mismatch")
        # Declarations and code are checked again after the potentially longer snapshot inspection.
        if parse_candidate_workspace_plan(run / "plan.json").digest() != value["plan_sha256"]:
            _fail("evaluation_mismatch")
        _bundle_source(workspace, value, code_path)
        return result
    except (ValueError, TypeError, KeyError, AttributeError, OSError, RecursionError):
        _fail("evidence_invalid")


def read_candidate_source_files(workspace, candidate):
    """Expose complete verified source for generation context and novelty calculation."""
    try:
        if candidate.bundle_evidence is None:
            from .evolution import MAX_SOURCE_BYTES
            return {Path(candidate.code_path).name: _read(Path(workspace) / candidate.code_path, MAX_SOURCE_BYTES).decode("utf-8")}
        workspace, value, bundle = _bundle_source(workspace, candidate.bundle_evidence, candidate.code_path)
        result = {}
        for item in bundle.files:
            content = _read(workspace / value["source_root"] / item.path, item.size)
            if len(content) != item.size or _sha(content) != item.sha256:
                _fail("source_mismatch")
            result[item.path] = content.decode("utf-8")
        _bundle_source(workspace, value, candidate.code_path)
        return result
    except (ValueError, TypeError, OSError, UnicodeError, AttributeError):
        _fail("source_mismatch")


def read_bundle_delivery_materials(workspace, candidate, *, authority=None):
    """Return verified portable bytes; retained inode-bound records themselves are not relocated."""
    try:
        if authority is None:
            from .evolution import CandidateIntegrityAuthority
            fields = CandidateIntegrityAuthority.__dataclass_fields__
            authority = CandidateIntegrityAuthority.from_dict({name: candidate.integrity[name] for name in fields})
        result = validate_candidate_bundle_evidence(
            workspace, candidate.bundle_evidence, code_path=candidate.code_path,
            evaluation=candidate.evaluation, authority=authority,
        )
        root = result.evaluation_path
        manifest_bytes = _read(root / "evaluation.json", 128 * 1024)
        if _sha(manifest_bytes) != result.digest():
            _fail("evaluation_mismatch")
        manifest = strict_json(manifest_bytes)
        request_bytes = _read(root / "request.json", 128 * 1024)
        if _sha(request_bytes) != manifest["files"]["request.json"]["sha256"]:
            _fail("evaluation_mismatch")
        request = strict_json(request_bytes)
        sources = read_candidate_source_files(workspace, candidate)
        material = {"source/" + name: source.encode("utf-8") for name, source in sources.items()}
        selected = {item["path"] for item in request["outputs"] if item["present"]}
        selected.update("inputs/" + item["target"] for item in request["inputs"])
        selected.update({"report.json", "evaluator.py"})
        if "source-checks.json" in manifest["files"]:
            selected.add("source-checks.json")
        for name in sorted(selected):
            descriptor = manifest["files"][name]
            content = _read(root / name, descriptor["size"])
            if len(content) != descriptor["size"] or _sha(content) != descriptor["sha256"]:
                _fail("evaluation_mismatch")
            target = {"report.json": "evaluation/report.json", "evaluator.py": "evaluation/evaluator.py",
                      "source-checks.json": "evaluation/source-checks.json"}.get(name, name)
            material[target] = content
        material["evaluation/spec.json"] = canonical_json(request["evaluator"])
        material["contract.json"] = canonical_json(request["contract"])
        material["source-bundle.json"] = _read(Path(workspace) / candidate.bundle_evidence["bundle_path"], MAX_CANDIDATE_BUNDLE_BYTES)
        validate_candidate_bundle_evidence(
            workspace, candidate.bundle_evidence, code_path=candidate.code_path,
            evaluation=candidate.evaluation, authority=authority,
        )
        return material
    except (ValueError, TypeError, KeyError, AttributeError, OSError, RecursionError):
        _fail("delivery_invalid")


class MultiFileCandidatePipeline:
    """Explicit local profile; native population owns selection, lineage and recovery state."""

    def __init__(self, *, evaluator, harness_path, input_root, inputs, command,
                 dependency_sha256, environment_sha256, environment=(), timeout_seconds=30.0,
                 max_output_bytes=16384):
        try:
            self.evaluator = parse_candidate_evaluation_spec(evaluator)
            self.harness_path = files.absolute_path(harness_path)
            self.input_root = files.absolute_path(input_root)
            self.inputs = _inputs(inputs)
            stub = CandidateSourceBundle("0" * 64, "main.py", (CandidateSourceFile("main.py", 1, "1" * 64),))
            plan = build_candidate_workspace_plan(
                stub, command=command, environment=environment, contract_sha256=stub.contract_sha256,
                timeout_seconds=timeout_seconds, max_output_bytes=max_output_bytes,
            )
            self.command, self.environment = plan.command, plan.environment
            self.timeout_seconds, self.max_output_bytes = plan.timeout_seconds, plan.max_output_bytes
            self.budget = CandidateExecutionBudget(self.timeout_seconds, self.max_output_bytes, 16 * 1024 * 1024, 1)
            # Reuse admission's exact field and aggregate input validation even before a real draft.
            build_candidate_execution_admission(
                plan, inputs=self.inputs, dependency_sha256=dependency_sha256, environment_sha256=environment_sha256,
                evaluator=self.evaluator.pin(), output_contract_sha256="1" * 64, budget=self.budget,
            )
            self.dependency_sha256, self.environment_sha256 = dependency_sha256, environment_sha256
            self._remaining_timeout: Callable[[str], float] | None = None
            self._process_observer = None
            self._process_released = None
            self._continuation_guard = None
        except (ValueError, TypeError, OSError, AttributeError):
            _fail("profile_invalid")

    @property
    def runner_fingerprint(self):
        return _runner_digest(self, self.inputs)

    def configure(self, config):
        from .evolution import EvolutionConfig
        if not isinstance(config, EvolutionConfig) or config.strategy != "population":
            _fail("profile_invalid")
        values = {
            "evaluator_kind": self.evaluator.pin().kind, "evaluator_fingerprint": self.evaluator.digest(),
            "runner_fingerprint": self.runner_fingerprint, "dependency_sha256": self.dependency_sha256,
            "environment_sha256": self.environment_sha256,
        }
        if any(getattr(config, name) not in (None, value) for name, value in values.items()):
            _fail("authority_mismatch")
        return replace(config, **values)

    def set_remaining_timeout(self, callback: Callable[[str], float] | None) -> None:
        if callback is not None and not callable(callback):
            raise TypeError("remaining timeout callback must be callable or None")
        self._remaining_timeout = callback

    def set_process_observer(self, observer, released=None) -> None:
        for callback in (observer, released):
            if callback is not None and not callable(callback):
                raise TypeError("process callback must be callable or None")
        self._process_observer, self._process_released = observer, released

    def set_continuation_guard(self, guard) -> None:
        self._continuation_guard = guard

    def build_publication_artifact(self, archive, candidate):
        """Project one persisted candidate into the Feature 153 publication artifact.

        This is a read-only hand-off: the native execution/evaluation records are inspected and
        wrapped into portable receipts, while the publication transaction remains responsible for
        staging and committing bytes.  No candidate is executed or evaluated by this method.
        """
        from .producer_bundle_receipts import build_producer_bundle_publication_artifact

        return build_producer_bundle_publication_artifact(archive, candidate)

    # Keep the shorter spelling convenient for callers that treat the pipeline as the owner of
    # per-candidate evidence.
    publication_artifact = build_publication_artifact

    def _effective_timeout(self, stage: str) -> float:
        if self._continuation_guard is not None:
            self._continuation_guard()
        if self._remaining_timeout is None:
            return self.timeout_seconds
        remaining = self._remaining_timeout(stage)
        if (
            isinstance(remaining, bool)
            or not isinstance(remaining, (int, float))
            or not math.isfinite(float(remaining))
            or remaining <= 0
        ):
            _fail("solve_budget_exhausted")
        return min(self.timeout_seconds, float(remaining))

    def validate_context(self, context, authority):
        try:
            validate_source_capabilities(context.contract)
        except (TypeError, ValueError):
            _fail("unsupported_constraints")
        configured = self.configure(context.config)
        if configured.to_dict() != context.config.to_dict() or context.initial_seeds:
            _fail("profile_invalid")
        candidate_output_contract_sha256(context.contract.outputs)
        expected = {
            "contract_sha256": context.contract.digest(),
            "evaluator_kind": self.evaluator.pin().kind, "evaluator_fingerprint": self.evaluator.digest(),
            "runner_fingerprint": self.runner_fingerprint, "dependency_sha256": self.dependency_sha256,
            "environment_sha256": self.environment_sha256,
        }
        if any(getattr(authority, name) != value for name, value in expected.items()):
            _fail("authority_mismatch")

    def __call__(self, *_):
        _fail("pipeline_required")

    def preflight(self):
        """Check explicitly supplied harness and input bytes without creating run state."""
        try:
            evaluator = parse_candidate_evaluation_spec(self.evaluator)
            harness = _read(self.harness_path, evaluator.harness_size)
            if (len(harness) != evaluator.harness_size or _sha(harness) != evaluator.harness_sha256
                    or b"\x00" in harness):
                _fail("profile_invalid")
            harness.decode("utf-8")
            for item in _inputs(self.inputs):
                content = _read(self.input_root / item.target, item.size)
                if len(content) != item.size or _sha(content) != item.sha256:
                    _fail("profile_invalid")
        except (ValueError, TypeError, AttributeError, OSError):
            _fail("profile_invalid")

    @staticmethod
    def _allocate_run(archive, run_id=None):
        archive._ensure_layout()
        chain = DirectoryChain(archive.root, "destination_changed")
        try:
            try:
                os.mkdir("bundle-attempts", 0o700, dir_fd=chain.fd)
            except FileExistsError:
                pass
            os.fsync(chain.fd)
            parent_path = archive.root / "bundle-attempts"
            parent = DirectoryChain(parent_path, "destination_changed")
            try:
                if run_id is None:
                    tree = PrivateTree(parent, prefix=".bundle-run-")
                    try:
                        name = tree.name
                        for child in ("workspaces", "inputs", "evaluations"):
                            os.mkdir(child, 0o700, dir_fd=tree.fd)
                        os.fsync(tree.fd)
                        os.fsync(parent.fd)
                        tree.check_root()
                        return parent_path / name
                    finally:
                        tree.close()
                if not isinstance(run_id, str) or _HEX24.fullmatch(run_id) is None:
                    _fail("run_id_invalid")
                name = ".bundle-run-" + run_id
                try:
                    os.mkdir(name, 0o700, dir_fd=parent.fd)
                except FileExistsError:
                    _fail("run_exists")
                os.fsync(parent.fd)
                path = parent_path / name
                for child in ("workspaces", "inputs", "evaluations"):
                    (path / child).mkdir(mode=0o700)
                for child in ("workspaces", "inputs", "evaluations"):
                    os.chmod(path / child, 0o700)
                return path
            finally:
                parent.close()
        finally:
            chain.close()

    def evaluate_draft_non_publishing(
        self, strategy, draft, *, journal_id, candidate_id=None, ordinal=None,
        journal_candidate=None, admission_plan=None, iteration=None, generation=None, parent=None,
        parent_id=None, island_id=None, run_id=None, journal_sha256=None,
    ):
        """Execute and independently evaluate one journal-planned draft without publishing it.

        The source tree is retained under the private producer batch area and native execution
        evidence stays at its original ``bundle-attempts`` path.  This method deliberately never
        allocates an archive candidate ID and never calls ``CandidateArchive.persist``.
        """
        from .evolution import CandidateDraft, EvolutionError, _InitialCandidateFailure
        from .producer_bundle_preflight import derive_producer_bundle_candidate_id
        from .producer_bundle_publication import ProducerBundlePublicationCandidate

        if not isinstance(draft, CandidateDraft):
            _fail("draft_invalid")
        journal_parent_id = None
        if journal_candidate is not None:
            if not isinstance(journal_candidate, ProducerBundlePublicationCandidate):
                _fail("journal_candidate_invalid")
            if candidate_id is not None or iteration is not None or generation is not None or island_id is not None:
                _fail("candidate_mapping_ambiguous")
            from .producer_bundle_admission import ProducerBundleAdmissionPlan
            if not isinstance(admission_plan, ProducerBundleAdmissionPlan):
                _fail("journal_admission_plan_invalid")
            if (
                journal_candidate.status != "planned"
                or journal_candidate.execution_receipt_sha256 is not None
                or journal_candidate.evaluation_receipt_sha256 is not None
                or journal_candidate.publication_receipt_sha256 is not None
            ):
                _fail("journal_candidate_state_invalid")
            if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 0:
                _fail("journal_candidate_ordinal_invalid")
            if ordinal >= len(admission_plan.bundles):
                _fail("journal_candidate_ordinal_invalid")
            planned_bundle = admission_plan.bundles[ordinal]
            if (
                journal_candidate.bundle_id != planned_bundle.bundle_id
                or journal_candidate.bundle_sha256 != planned_bundle.bundle_sha256
            ):
                _fail("journal_candidate_bundle_mapping_invalid")
            candidate_id = journal_candidate.candidate_id
            iteration = journal_candidate.iteration
            generation = journal_candidate.generation
            island_id = journal_candidate.island_id
            journal_parent_id = journal_candidate.parent_id
            if parent_id is not None and parent_id != journal_candidate.parent_id:
                _fail("lineage_invalid")
            parent_id = journal_candidate.parent_id
        archive = strategy.archive
        if journal_sha256 is not None:
            from .producer_bundle_intent import verify_producer_bundle_prepared_intent
            from .producer_bundle_publication import parse_producer_bundle_publication_journal

            prepared = parse_producer_bundle_publication_journal(
                archive.root / "producer-batches" / journal_id / "journal.prepared.json",
            )
            if (journal_candidate is None or prepared.digest() != journal_sha256
                    or prepared.journal_id != journal_id
                    or prepared.admission_sha256 != admission_plan.digest()
                    or ordinal >= len(prepared.candidates)
                    or prepared.candidates[ordinal] != journal_candidate):
                _fail("draft_binding_mismatch")
            verify_producer_bundle_prepared_intent(archive.workspace, prepared)
        self.validate_context(strategy.context, strategy.integrity_authority)
        self.preflight()
        if parent is not None:
            derived_parent = getattr(parent, "candidate_id", None)
            if journal_candidate is not None and derived_parent != journal_parent_id:
                _fail("lineage_invalid")
            if parent_id is not None and parent_id != derived_parent:
                _fail("lineage_invalid")
            parent_id = derived_parent
        if not isinstance(journal_id, str) or not journal_id or "/" in journal_id or "\\" in journal_id:
            _fail("journal_id_invalid")
        if not isinstance(candidate_id, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", candidate_id) is None:
            _fail("candidate_id_invalid")
        if isinstance(iteration, bool) or not isinstance(iteration, int) or iteration < 0:
            _fail("iteration_invalid")
        if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
            _fail("generation_invalid")
        if isinstance(island_id, bool) or not isinstance(island_id, int) or island_id < 0:
            _fail("island_invalid")
        draft = CandidateDraft(draft.source, draft.filename, dict(draft.metadata),
                               dict(draft.source_files) if draft.source_files is not None else None)
        bundle = validate_bundle_draft(draft, strategy.context.contract.digest())
        bundle_sha256 = bundle.digest()
        if journal_candidate is not None:
            if journal_candidate.bundle_sha256 != bundle_sha256:
                _fail("bundle_mismatch")
            if candidate_id != derive_producer_bundle_candidate_id(
                journal_id, ordinal, journal_candidate.bundle_id, bundle_sha256,
            ):
                _fail("candidate_id_mismatch")
        bundle_id = journal_candidate.bundle_id if journal_candidate is not None else (
            draft.metadata.get("producer_bundle", {}).get("bundle_id", candidate_id)
            if isinstance(draft.metadata, dict) and isinstance(draft.metadata.get("producer_bundle"), dict)
            else candidate_id
        )
        expected_run_id = derive_native_draft_run_id(journal_id, candidate_id, bundle.digest())
        if run_id is None:
            run_id = expected_run_id
        elif run_id != expected_run_id:
            _fail("run_id_mismatch")

        archive._ensure_layout()
        batch_parent = _ensure_private_directory(
            archive.root, ("producer-batches", journal_id, "native-drafts"),
        )
        batch_root = batch_parent / candidate_id
        if batch_root.is_symlink():
            _fail("draft_exists")
        if batch_root.exists():
            # A retry of the exact journal mapping is read-only.  Reopen the original evidence
            # instead of replaying execution or evaluation under the same candidate identity.
            try:
                _directory_identity(batch_root)
                binding_bytes = _read(batch_root / _DRAFT_BINDING_NAME, 16 * 1024)
                binding = strict_json(binding_bytes)
                source_root = batch_root / "source"
                run_root = archive.root / "bundle-attempts" / (".bundle-run-" + run_id)
                source_identity = _directory_identity(source_root)
                run_identity = _directory_identity(run_root)
                saved_bundle = parse_candidate_source_bundle(strict_json(_read(source_root / _BUNDLE_NAME, MAX_CANDIDATE_BUNDLE_BYTES)))
                if saved_bundle.digest() != bundle.digest():
                    _fail("draft_exists")
                plan = parse_candidate_workspace_plan(
                    strict_json(_read(run_root / "plan.json", MAX_EXECUTION_ADMISSION_BYTES))
                )
                admission_bytes = _read(run_root / "admission.json", MAX_EXECUTION_ADMISSION_BYTES)
                admission = admit_candidate_execution(
                    admission_bytes, plan=plan,
                    expected_plan_sha256=plan.digest(), expected_bundle_sha256=bundle.digest(),
                    expected_contract_sha256=strategy.context.contract.digest(),
                ).admission
                expected_binding = _draft_binding(
                    journal_id=journal_id, candidate_id=candidate_id, run_id=run_id,
                    bundle_id=bundle_id, bundle_sha256=bundle_sha256, ordinal=ordinal,
                    parent_id=parent_id, generation=generation, iteration=iteration, island_id=island_id,
                    source_root=source_root.relative_to(archive.workspace).as_posix(),
                    source_identity=source_identity, run_root=run_root.relative_to(archive.workspace).as_posix(),
                    run_identity=run_identity, plan_sha256=plan.digest(), admission_sha256=admission.digest(),
                    journal_sha256=journal_sha256,
                )
                if binding != expected_binding:
                    _fail("draft_binding_mismatch")
                record = inspect_candidate_execution_record(
                    run_root / "attempt", plan=plan, admission=admission,
                    expected_admission_sha256=admission.digest(), expected_plan_sha256=plan.digest(),
                    expected_bundle_sha256=bundle.digest(), expected_contract_sha256=strategy.context.contract.digest(),
                )
                evaluation_root = run_root / "evaluations"
                entries = list(evaluation_root.iterdir())
                if len(entries) != 1 or entries[0].is_symlink() or not entries[0].is_dir() \
                        or re.fullmatch(r"\.candidate-evaluation-[0-9a-f]{24}", entries[0].name) is None:
                    _fail("evidence_invalid")
                evaluation_path = entries[0]
                result = inspect_candidate_evaluation(evaluation_path)
                return NativeDraftEvaluationResult(
                    candidate_id=candidate_id, journal_id=journal_id, run_id=run_id, bundle=bundle,
                    source_root=source_root, run_root=run_root, plan=plan, admission=admission,
                    execution=record, evaluation=result, bundle_id=bundle_id, parent_id=parent_id,
                    generation=generation, iteration=iteration, island_id=island_id, ordinal=ordinal,
                    metadata=dict(draft.metadata), journal_sha256=journal_sha256,
                )
            except EvolutionError:
                raise
            except Exception:  # noqa: BLE001 - stale or malformed retained evidence fails closed
                _fail("draft_exists")
        _ensure_private_directory(archive.root, (
            "producer-batches", journal_id, "native-drafts", candidate_id,
        ))
        source_root = batch_root / "source"
        _ensure_private_directory(archive.root, (
            "producer-batches", journal_id, "native-drafts", candidate_id, "source",
        ))
        sources = draft.source_files or {draft.filename: draft.source}
        for item in bundle.files:
            relative_parts = tuple(Path(item.path).parts)
            if len(relative_parts) > 1:
                _ensure_private_directory(
                    source_root, relative_parts[:-1],
                )
            _safe_atomic_write(
                archive,
                source_root / item.path, sources[item.path].encode("utf-8"),
                error="bundle_candidate_source_changed",
            )
        bundle_path = source_root / _BUNDLE_NAME
        _safe_atomic_write(
            archive,
            bundle_path, canonical_json(bundle.to_dict()), error="bundle_candidate_source_changed",
        )
        run_root = self._allocate_run(archive, run_id)
        copied = materialize_candidate_source_bundle(
            bundle, source_root=source_root, workspace_root=run_root / "workspaces",
            contract_sha256=bundle.contract_sha256, expected_bundle_sha256=bundle.digest(),
        )
        plan = build_candidate_workspace_plan(
            bundle, command=self.command, environment=self.environment,
            contract_sha256=bundle.contract_sha256, timeout_seconds=self.timeout_seconds,
            max_output_bytes=self.max_output_bytes,
        )
        admission = build_candidate_execution_admission(
            plan, inputs=self.inputs, dependency_sha256=self.dependency_sha256,
            environment_sha256=self.environment_sha256, evaluator=self.evaluator.pin(),
            output_contract_sha256=candidate_output_contract_sha256(strategy.context.contract.outputs),
            budget=self.budget,
        )
        staged = stage_candidate_execution_inputs(
            admission, plan=plan, input_root=self.input_root, staging_root=run_root / "inputs",
        )
        for name, value in (("plan", plan), ("admission", admission)):
            archive._atomic_write_bytes(run_root / (name + ".json"), canonical_json(value.to_dict()), error="bundle_candidate_record_failed")
        source_identity = _directory_identity(source_root)
        run_identity = _directory_identity(run_root)
        _safe_atomic_write(
            archive,
            batch_root / _DRAFT_BINDING_NAME,
            canonical_json(_draft_binding(
                journal_id=journal_id, candidate_id=candidate_id, run_id=run_id,
                bundle_id=bundle_id, bundle_sha256=bundle_sha256, ordinal=ordinal,
                parent_id=parent_id, generation=generation, iteration=iteration, island_id=island_id,
                source_root=source_root.relative_to(archive.workspace).as_posix(),
                source_identity=source_identity, run_root=run_root.relative_to(archive.workspace).as_posix(),
                run_identity=run_identity, plan_sha256=plan.digest(), admission_sha256=admission.digest(),
                journal_sha256=journal_sha256,
            )),
            error="bundle_candidate_record_failed",
        )
        if strategy._cancelled():
            raise SolveExecutionCancelled("candidate_execution")
        record = run_candidate_execution_recorded(
            admission, plan=plan, workspace_path=copied.workspace_path, input_path=staged.input_path,
            attempt_path=run_root / "attempt", expected_admission_sha256=admission.digest(),
            expected_plan_sha256=plan.digest(), expected_bundle_sha256=bundle.digest(),
            expected_contract_sha256=strategy.context.contract.digest(),
            timeout_seconds=self._effective_timeout("candidate_execution"),
            remaining_timeout=self._remaining_timeout, process_observer=self._process_observer,
            process_released=self._process_released,
        )
        self._effective_timeout("candidate_execution")
        if record.to_dict().get("runner_result", {}).get("status") != "succeeded":
            raise _InitialCandidateFailure("candidate_failed")
        self._effective_timeout("evaluation")
        result = evaluate_candidate_execution(
            admission, plan=plan, contract=strategy.context.contract, evaluator=self.evaluator,
            harness_path=self.harness_path, workspace_path=copied.workspace_path,
            input_path=staged.input_path, attempt_path=run_root / "attempt",
            evaluation_root=run_root / "evaluations", expected_admission_sha256=admission.digest(),
            expected_completion_sha256=record.completion_sha256, remaining_timeout=self._remaining_timeout,
            process_observer=self._process_observer, process_released=self._process_released,
        )
        self._effective_timeout("evaluation")
        return NativeDraftEvaluationResult(
            candidate_id=candidate_id, journal_id=journal_id, run_id=run_id, bundle=bundle,
            source_root=source_root, run_root=run_root, plan=plan, admission=admission,
            execution=record, evaluation=result, bundle_id=bundle_id, parent_id=parent_id,
            generation=generation, iteration=iteration, island_id=island_id, ordinal=ordinal,
            metadata=dict(draft.metadata), journal_sha256=journal_sha256,
        )

    def persist(self, strategy, draft, *, iteration, generation, parent, island_id):
        from .evolution import (
            CandidateDraft,
            _CandidateArchivePublicationUnknown,
            _InitialCandidateFailure,
        )
        archive = strategy.archive
        self._effective_timeout("candidate_execution")
        candidate_id = archive.next_id()
        # Only the reusable source staging is discarded. Allocated run roots are never removed.
        strategy._discard_unarchived_candidate(candidate_id)
        try:
            self.validate_context(strategy.context, strategy.integrity_authority)
            self.preflight()
            draft = CandidateDraft(draft.source, draft.filename, dict(draft.metadata),
                                   dict(draft.source_files) if draft.source_files is not None else None)
            bundle = validate_bundle_draft(draft, strategy.context.contract.digest())
            sources = draft.source_files or {draft.filename: draft.source}
            archive._ensure_layout()
            for item in bundle.files:
                path = archive.candidate_source_path(candidate_id, item.path)
                archive._atomic_write_bytes(path, sources[item.path].encode("utf-8"), error="bundle_candidate_source_changed")
            source_root = archive.candidates_root / candidate_id
            bundle_path = source_root / _BUNDLE_NAME
            archive._atomic_write_bytes(bundle_path, canonical_json(bundle.to_dict()), error="bundle_candidate_source_changed")
            run_root = self._allocate_run(archive)
            copied = materialize_candidate_source_bundle(
                bundle, source_root=source_root, workspace_root=run_root / "workspaces",
                contract_sha256=bundle.contract_sha256, expected_bundle_sha256=bundle.digest(),
            )
            plan = build_candidate_workspace_plan(
                bundle, command=self.command, environment=self.environment, contract_sha256=bundle.contract_sha256,
                timeout_seconds=self.timeout_seconds, max_output_bytes=self.max_output_bytes,
            )
            admission = build_candidate_execution_admission(
                plan, inputs=self.inputs, dependency_sha256=self.dependency_sha256,
                environment_sha256=self.environment_sha256, evaluator=self.evaluator.pin(),
                output_contract_sha256=candidate_output_contract_sha256(strategy.context.contract.outputs),
                budget=self.budget,
            )
            staged = stage_candidate_execution_inputs(
                admission, plan=plan, input_root=self.input_root, staging_root=run_root / "inputs",
            )
            for name, value in (("plan", plan), ("admission", admission)):
                archive._atomic_write_bytes(run_root / (name + ".json"), canonical_json(value.to_dict()), error="bundle_candidate_record_failed")
            if strategy._cancelled():
                raise _InitialCandidateFailure("candidate_failed")
            record = run_candidate_execution_recorded(
                admission, plan=plan, workspace_path=copied.workspace_path, input_path=staged.input_path,
                attempt_path=run_root / "attempt", expected_admission_sha256=admission.digest(),
                timeout_seconds=self._effective_timeout("candidate_execution"),
                remaining_timeout=self._remaining_timeout,
                process_observer=self._process_observer,
                process_released=self._process_released,
            )
            self._effective_timeout("candidate_execution")
            if record.to_dict().get("runner_result", {}).get("status") != "succeeded":
                raise _InitialCandidateFailure("candidate_failed")
            self._effective_timeout("evaluation")
            result = evaluate_candidate_execution(
                admission, plan=plan, contract=strategy.context.contract, evaluator=self.evaluator,
                harness_path=self.harness_path, workspace_path=copied.workspace_path, input_path=staged.input_path,
                attempt_path=run_root / "attempt", evaluation_root=run_root / "evaluations",
                expected_admission_sha256=admission.digest(), expected_completion_sha256=record.completion_sha256,
                remaining_timeout=self._remaining_timeout,
                process_observer=self._process_observer,
                process_released=self._process_released,
            )
            self._effective_timeout("evaluation")
            binding = {
                "protocol": _PROTOCOL, "bundle_sha256": bundle.digest(),
                "bundle_path": bundle_path.relative_to(archive.workspace).as_posix(),
                "source_root": source_root.relative_to(archive.workspace).as_posix(),
                "run_root": run_root.relative_to(archive.workspace).as_posix(),
                "plan_sha256": plan.digest(), "admission_sha256": admission.digest(),
                "completion_sha256": record.completion_sha256,
                "evaluation_path": result.evaluation_path.relative_to(archive.workspace).as_posix(),
                "evaluation_sha256": result.digest(),
            }
            candidate = archive.persist(
                draft, candidate_id=candidate_id, strategy="population", iteration=iteration,
                generation=generation, parent_id=parent.candidate_id if parent else None, island_id=island_id,
                evaluation=result.report, integrity_authority=strategy.integrity_authority, bundle_evidence=binding,
            )
            self._effective_timeout("candidate_persistence")
        except (SolveExecutionBudgetExceeded, SolveExecutionCancelled):
            strategy._discard_unarchived_candidate(candidate_id)
            raise
        except _CandidateArchivePublicationUnknown:
            raise
        except Exception:  # noqa: BLE001 - all operational failures use the population outcome journal
            strategy._discard_unarchived_candidate(candidate_id)
            raise _InitialCandidateFailure("candidate_failed") from None
        strategy._transient_evaluations[candidate.candidate_id] = result.report
        try:
            strategy.context.observe("candidate", candidate.to_dict())
        except Exception as exc:  # noqa: BLE001 - optional observer cannot change published selection
            del exc
        return candidate


def load_bundle_pipeline(profile_path):
    """Read an explicit local profile; relative paths belong to the profile's directory."""
    from .candidate_execution import CandidateExecutionInput
    try:
        path = files.absolute_path(profile_path)
        value = strict_json(_read(path, 128 * 1024))
        fields = {
            "schema_version", "protocol", "evaluator", "harness_path", "input_root", "inputs",
            "command", "environment", "timeout_seconds", "max_output_bytes",
            "dependency_sha256", "environment_sha256",
        }
        if (not isinstance(value, dict) or set(value) != fields or value["schema_version"] != "1"
                or value["protocol"] != "lunar-bundle-pipeline-v1"
                or not isinstance(value["inputs"], list) or len(value["inputs"]) > 64):
            _fail("profile_invalid")
        for name in ("harness_path", "input_root"):
            if not isinstance(value[name], str) or not value[name]:
                _fail("profile_invalid")
            value[name] = files.absolute_path(path.parent / value[name])
        pipeline = MultiFileCandidatePipeline(
            **{name: value[name] for name in fields - {"schema_version", "protocol", "inputs"}},
            inputs=tuple(CandidateExecutionInput.from_dict(item) for item in value["inputs"]),
        )
        pipeline.preflight()
        return pipeline
    except (ValueError, TypeError, KeyError, OSError, AttributeError, RecursionError):
        _fail("profile_invalid")


__all__ = [
    "MultiFileCandidatePipeline", "NativeDraftEvaluationResult", "derive_native_draft_run_id",
    "load_bundle_pipeline", "read_bundle_delivery_materials", "read_candidate_source_files",
]
