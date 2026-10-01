"""Independent scoring of retained candidate attempts using evaluation-time snapshots.

The candidate is never rerun. A complete local record binds the bytes supplied to a trusted
evaluator, not process-exit output provenance or a sandboxed/authenticated host environment.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import stat
import sys
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

from . import candidate_execution_evidence as evidence
from ._benchmark_files import BenchmarkFileError, absolute_path
from ._candidate_workspace_io import DirectoryChain, PrivateTree, identity
from .algorithm import MAX_REPORT_BYTES, AlgorithmProblemContract, EvaluationReport
from .automatic_solve_lifecycle import SolveExecutionBudgetExceeded, SolveExecutionCancelled
from .candidate_evaluation_spec import (
    CandidateEvaluationError,
    candidate_output_contract_sha256,
    canonical_json,
    parse_candidate_evaluation_report,
    parse_candidate_evaluation_spec,
    strict_json,
)
from .candidate_execution_runner import (
    CandidateExecutionRunnerError,
    _bounded_process_bytes,
    _Executable,
)
from .candidate_workspace_plan import CandidateWorkspaceError
from .evaluator import _structured_content_check
from .source_constraints import (
    MAX_SOURCE_CHECK_BYTES,
    parse_source_check_evidence,
    source_check_evidence,
    source_constraints,
    source_failure_report,
    validate_source_capabilities,
)

_MAX_MANIFEST_BYTES = 128 * 1024
_REQUEST_PROTOCOL = "lunar-candidate-evaluation-request-v1"
_RECORD_PROTOCOL = "lunar-candidate-evaluation-v1"
_SOURCE_RECORD_PROTOCOL = "lunar-candidate-evaluation-source-v1"


def _fail(code):
    raise CandidateEvaluationError(code)


def _sha(content):
    return hashlib.sha256(content).hexdigest()


def _close(callback):
    active = sys.exception()
    try:
        callback()
    except (OSError, CandidateWorkspaceError):
        if not isinstance(active, (KeyboardInterrupt, SystemExit)):
            _fail("snapshot_changed")


class _Resources(ExitStack):
    def __init__(self):
        super().__init__()
        self.chains = {}


class _DirectoryView:
    """Borrow shared ancestors; each descriptor is closed once by the enclosing resources."""

    code = "destination_changed"
    check = DirectoryChain.check

    def __init__(self, fds, links):
        self.fds, self.links = fds, links

    @property
    def fd(self):
        return self.fds[-1]


def _chain(path, stack):
    if path in stack.chains:
        chain = stack.chains[path]
        chain.check()
        return chain
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    if path == path.parent:
        descriptor = os.open(path, flags)
        stack.callback(_close, lambda: os.close(descriptor))
        chain = _DirectoryView([descriptor], [])
    else:
        parent = _chain(path.parent, stack)
        before = os.stat(path.name, dir_fd=parent.fd, follow_symlinks=False)
        if not stat.S_ISDIR(before.st_mode):
            _fail("root_unsafe")
        descriptor = os.open(path.name, flags, dir_fd=parent.fd)
        stack.callback(_close, lambda: os.close(descriptor))
        if identity(before) != identity(os.fstat(descriptor)):
            _fail("root_unsafe")
        chain = _DirectoryView([*parent.fds, descriptor], [*parent.links, (parent.fd, path.name, descriptor)])
    chain.check()
    stack.chains[path] = chain
    return chain


class _Observation:
    """Hold a regular file or the first missing name, and detect observed changes."""

    def __init__(self, path, maximum, stack, *, code, optional=False):
        self.code = code
        self.maximum = maximum
        self.content = None
        self.descriptor = None
        self.fd = None
        parent = path.parent
        try:
            while True:
                try:
                    self.chain = _chain(parent, stack)
                    break
                except FileNotFoundError:
                    if not optional or parent == parent.parent:
                        raise
                    parent = parent.parent
            self.name = path.relative_to(parent).parts[0]
            try:
                before = os.stat(self.name, dir_fd=self.chain.fd, follow_symlinks=False)
            except FileNotFoundError:
                if not optional:
                    raise
                self.check()
                return
            if parent != path.parent or not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                _fail(code)
            if not 0 <= before.st_size <= maximum:
                _fail(code)
            self.fingerprint = evidence._fingerprint(before)
            self.fd = os.open(
                self.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                dir_fd=self.chain.fd,
            )
            stack.callback(_close, lambda: os.close(self.fd))
            self.content = self._read()
            self.descriptor = {
                "size": len(self.content), "sha256": _sha(self.content), **evidence._node(before),
            }
        except (OSError, CandidateWorkspaceError, CandidateEvaluationError):
            _fail(code)

    def _read(self):
        self.chain.check()
        if evidence._fingerprint(os.fstat(self.fd)) != self.fingerprint:
            _fail(self.code)
        os.lseek(self.fd, 0, os.SEEK_SET)
        chunks, remaining = [], self.maximum + 1
        while remaining:
            chunk = os.read(self.fd, min(remaining, 65536))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        content = b"".join(chunks)
        after = os.fstat(self.fd)
        named = os.stat(self.name, dir_fd=self.chain.fd, follow_symlinks=False)
        if (len(content) != after.st_size or len(content) > self.maximum
                or evidence._fingerprint(after) != self.fingerprint
                or evidence._fingerprint(named) != self.fingerprint):
            _fail(self.code)
        self.chain.check()
        return content

    def check(self):
        try:
            self.chain.check()
            if self.fd is None:
                try:
                    os.stat(self.name, dir_fd=self.chain.fd, follow_symlinks=False)
                except FileNotFoundError:
                    return
                _fail(self.code)
            if self._read() != self.content:
                _fail(self.code)
        except (OSError, CandidateWorkspaceError):
            _fail(self.code)


def _contract(value):
    try:
        raw = value.to_dict() if isinstance(value, AlgorithmProblemContract) else value
        # Detach mutable nested objects before any IO.
        result = AlgorithmProblemContract.from_dict(strict_json(canonical_json(raw)))
        candidate_output_contract_sha256(result.outputs)
        return result
    except (ValueError, TypeError, AttributeError, OverflowError, RecursionError):
        _fail("contract_mismatch")


def _format_valid(output, content):
    if content is None:
        return not output.required
    try:
        text = content.decode("utf-8")
        if output.format == "json":
            strict_json(content, maximum=len(content))
        elif output.format == "jsonl":
            for line in content.splitlines():
                if line.strip():
                    strict_json(line, maximum=len(line))
        error, _, _ = _structured_content_check(text, output.format, list(output.fields))
        return error is None
    except (ValueError, TypeError, UnicodeError, OverflowError, RecursionError):
        return False


def _invalid_report(evaluator_id):
    return EvaluationReport(
        "1", evaluator_id, 0, 0.0, {},
        ({"code": "output_contract_failed", "message": "Declared output validation failed."},),
    )


def _validate_harness(content, evaluator):
    if len(content) != evaluator.harness_size or _sha(content) != evaluator.harness_sha256:
        _fail("harness_changed")
    try:
        if "\x00" in content.decode("utf-8"):
            _fail("harness_changed")
    except UnicodeError:
        _fail("harness_changed")


def _object(value, fields):
    if not isinstance(value, dict) or set(value) != fields:
        _fail("invalid")
    return value


def _digest(value):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        _fail("invalid")
    return value


def _request_values(request):
    """Validate the portable request and return its reconstructed contract/spec."""
    _object(request, {
        "protocol", "schema_version", "observation", "binding", "contract", "evaluator",
        "inputs", "outputs",
    })
    if (request["protocol"] != _REQUEST_PROTOCOL or request["schema_version"] != "1"
            or request["observation"] != "evaluation-time"):
        _fail("invalid")
    contract = _contract(request["contract"])
    evaluator = parse_candidate_evaluation_spec(request["evaluator"])
    binding = _object(request["binding"], {
        "workspace_plan_sha256", "admission_sha256", "bundle_sha256", "contract_sha256",
        "source_file_table_sha256", "input_file_table_sha256", "launch_intent_sha256",
        "completion_sha256", "evaluator_fingerprint", "output_contract_sha256",
    })
    for value in binding.values():
        _digest(value)
    if (binding["contract_sha256"] != contract.digest()
            or binding["evaluator_fingerprint"] != evaluator.digest()
            or binding["output_contract_sha256"] != candidate_output_contract_sha256(contract.outputs)):
        _fail("identity_mismatch")
    # Admission validates input target namespaces; reconstruct that same bounded input table here.
    from .candidate_execution import MAX_EXECUTION_INPUT_BYTES, CandidateExecutionInput, _inputs
    try:
        if not isinstance(request["inputs"], list) or len(request["inputs"]) > 64:
            _fail("invalid")
        inputs = _inputs(tuple(CandidateExecutionInput.from_dict(item) for item in request["inputs"]))
    except (ValueError, TypeError, KeyError):
        _fail("invalid")
    if (request["inputs"] != [item.to_dict() for item in inputs]
            or _sha(canonical_json(request["inputs"])) != binding["input_file_table_sha256"]):
        _fail("identity_mismatch")
    if sum(item.size for item in inputs) > MAX_EXECUTION_INPUT_BYTES:
        _fail("invalid")
    if not isinstance(request["outputs"], list) or len(request["outputs"]) != len(contract.outputs):
        _fail("invalid")
    for spec, output in zip(sorted(contract.outputs, key=lambda s: s.path), request["outputs"], strict=True):
        _object(output, {"path", "present", "size", "sha256"})
        if output["path"] != spec.path or type(output["present"]) is not bool:
            _fail("invalid")
        if not output["present"]:
            if output["size"] is not None or output["sha256"] is not None:
                _fail("invalid")
        else:
            if type(output["size"]) is not int or not 0 <= output["size"] <= evaluator.max_output_file_bytes:
                _fail("invalid")
            _digest(output["sha256"])
    if sum(item["size"] or 0 for item in request["outputs"]) > evaluator.max_total_output_bytes:
        _fail("invalid")
    return contract, evaluator


@dataclass(frozen=True)
class CandidateEvaluationResult:
    evaluation_path: Path
    _manifest_json: bytes

    @property
    def status(self):
        return "evaluated"

    @property
    def report(self):
        return EvaluationReport.from_dict(json.loads(self._manifest_json)["report"])

    def digest(self):
        return _sha(self._manifest_json)

    def to_dict(self):
        manifest = json.loads(self._manifest_json)
        result = {
            "status": self.status, "observation": "evaluation-time", "evaluation_sha256": self.digest(),
            "binding": manifest["binding"], "report": manifest["report"],
            "output_contract_valid": manifest["output_contract_valid"],
            "harness_invoked": manifest["harness_invoked"],
        }
        if manifest["protocol"] == _SOURCE_RECORD_PROTOCOL:
            result["source_constraints_valid"] = manifest["source_constraints_valid"]
        return result


def _tree_names(chain, expected_files):
    """Reject undeclared names without recursively walking arbitrary untrusted trees."""
    directories = {()}
    for name in expected_files:
        parts = tuple(name.split("/"))
        directories.update(parts[:depth] for depth in range(1, len(parts)))
    for parts in sorted(directories):
        descriptors = []
        fd = chain.fd
        try:
            for part in parts:
                fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
                descriptors.append(fd)
            expected = {p[-1] for p in directories if p and p[:-1] == parts}
            expected.update(name.split("/")[-1] for name in expected_files if tuple(name.split("/")[:-1]) == parts)
            seen = set()
            with os.scandir(fd) as entries:
                for entry in entries:
                    if entry.name not in expected or entry.name in seen:
                        _fail("snapshot_changed")
                    seen.add(entry.name)
            if seen != expected:
                _fail("snapshot_changed")
        finally:
            for descriptor in reversed(descriptors):
                _close(lambda fd=descriptor: os.close(fd))
    chain.check()


def inspect_candidate_evaluation(evaluation_path, *, expected_evaluation_sha256=None):
    """Inspect a completed snapshot read-only; never infer or repair an incomplete result."""
    if expected_evaluation_sha256 is not None:
        _digest(expected_evaluation_sha256)
    try:
        path = absolute_path(evaluation_path)
        with _Resources() as stack:
            chain = _chain(path, stack)
            manifest_file = _Observation(
                path / "evaluation.json", _MAX_MANIFEST_BYTES, stack, code="snapshot_changed", optional=True,
            )
            if manifest_file.content is None:
                _fail("incomplete")
            raw = manifest_file.content
            manifest = strict_json(raw)
            extended = isinstance(manifest, dict) and manifest.get("protocol") == _SOURCE_RECORD_PROTOCOL
            manifest = _object(manifest, {
                "protocol", "schema_version", "observation", "evaluation_identity", "binding",
                "files", "report", "output_contract_valid", "harness_invoked",
            } | ({"source_constraints_valid"} if extended else set()))
            if canonical_json(manifest) != raw:
                _fail("invalid")
            if expected_evaluation_sha256 is not None and _sha(raw) != expected_evaluation_sha256:
                _fail("identity_mismatch")
            node = _object(manifest["evaluation_identity"], {"device", "inode"})
            if any(type(value) is not int or not 0 <= value < 2**64 for value in node.values()):
                _fail("invalid")
            if (manifest["protocol"] not in {_RECORD_PROTOCOL, _SOURCE_RECORD_PROTOCOL}
                    or manifest["schema_version"] != "1"
                    or manifest["observation"] != "evaluation-time"
                    or manifest["evaluation_identity"] != evidence._node(os.fstat(chain.fd))):
                _fail("identity_mismatch")
            files = manifest["files"]
            if not isinstance(files, dict) or len(files) > 100:
                _fail("invalid")
            request_file = _Observation(path / "request.json", _MAX_MANIFEST_BYTES, stack, code="snapshot_changed")
            request = strict_json(request_file.content)
            contract, evaluator = _request_values(request)
            if bool(source_constraints(contract)) != extended:
                _fail("identity_mismatch")
            if request_file.content != canonical_json(request) or manifest["binding"] != request["binding"]:
                _fail("identity_mismatch")
            expected = {
                "request.json": request_file.content,
                "evaluator.py": None, "report.json": None,
                **{"inputs/" + item["target"]: None for item in request["inputs"]},
                **{item["path"]: None for item in request["outputs"] if item["present"]},
            }
            if extended:
                expected["source-checks.json"] = None
            if set(files) != set(expected):
                _fail("invalid")
            observations = {}
            for name in expected:
                maximum = (evaluator.harness_size if name == "evaluator.py" else
                           MAX_REPORT_BYTES if name == "report.json" else
                           MAX_SOURCE_CHECK_BYTES if name == "source-checks.json" else
                           _MAX_MANIFEST_BYTES if name == "request.json"
                           else 16 * 1024 * 1024)
                observed = _Observation(path / name, maximum, stack, code="snapshot_changed")
                descriptor = _object(files[name], {"size", "sha256", "device", "inode"})
                if any(type(descriptor[key]) is not int or not 0 <= descriptor[key] < 2**64
                       for key in ("size", "device", "inode")):
                    _fail("invalid")
                _digest(descriptor["sha256"])
                if files[name] != observed.descriptor:
                    _fail("snapshot_changed")
                observations[name] = observed
            harness = observations["evaluator.py"]
            _validate_harness(harness.content, evaluator)
            for item in request["inputs"]:
                observed = observations["inputs/" + item["target"]]
                if len(observed.content) != item["size"] or _sha(observed.content) != item["sha256"]:
                    _fail("identity_mismatch")
            valid = True
            for spec, item in zip(sorted(contract.outputs, key=lambda s: s.path), request["outputs"], strict=True):
                observed = observations.get(spec.path)
                content = observed.content if observed else None
                if observed and (len(content) != item["size"] or _sha(content) != item["sha256"]):
                    _fail("identity_mismatch")
                valid = _format_valid(spec, content) and valid
            source_valid, source_evidence = True, None
            if extended:
                try:
                    validate_source_capabilities(contract)
                    source_evidence = parse_source_check_evidence(
                        observations["source-checks.json"].content, contract,
                        bundle_sha256=request["binding"]["bundle_sha256"],
                        source_file_table_sha256=request["binding"]["source_file_table_sha256"],
                    )
                    source_valid = source_evidence["validity"]
                except (ValueError, TypeError, KeyError):
                    _fail("source_constraints_invalid")
                if (type(manifest["source_constraints_valid"]) is not bool
                        or manifest["source_constraints_valid"] != source_valid):
                    _fail("invalid")
            if (type(manifest["output_contract_valid"]) is not bool
                    or type(manifest["harness_invoked"]) is not bool
                    or manifest["output_contract_valid"] != valid
                    or manifest["harness_invoked"] != (valid and source_valid)):
                _fail("invalid")
            report = parse_candidate_evaluation_report(observations["report.json"].content, evaluator_id=evaluator.evaluator_id)
            manifest_report = parse_candidate_evaluation_report(
                canonical_json(manifest["report"]), evaluator_id=evaluator.evaluator_id,
            )
            forced_report = (_invalid_report(evaluator.evaluator_id) if not valid else
                             source_failure_report(evaluator.evaluator_id, source_evidence)
                             if not source_valid else None)
            if (manifest_report.to_dict() != report.to_dict()
                    or (forced_report is not None and report.to_dict() != forced_report.to_dict())):
                _fail("identity_mismatch")
            _tree_names(chain, {*expected, "evaluation.json"})
            for observed in [manifest_file, request_file, *observations.values()]:
                observed.check()
            return CandidateEvaluationResult(path, raw)
    except (BenchmarkFileError, OSError, CandidateWorkspaceError):
        _fail("snapshot_changed")


def evaluate_candidate_execution(
    admission, *, plan, contract, evaluator, harness_path, workspace_path, input_path,
    attempt_path, evaluation_root, expected_admission_sha256=None, expected_plan_sha256=None,
    expected_bundle_sha256=None, expected_contract_sha256=None, expected_completion_sha256=None,
    remaining_timeout=None,
    process_observer=None,
    process_released=None,
):
    """Snapshot and score one successful attempt. Allocated evaluation trees are retained."""
    if remaining_timeout is not None and not callable(remaining_timeout):
        raise TypeError("remaining timeout callback must be callable or None")

    def effective_timeout():
        if remaining_timeout is None:
            return evaluator.timeout_seconds
        remaining = remaining_timeout("evaluation")
        if (isinstance(remaining, bool) or not isinstance(remaining, (int, float))
                or not math.isfinite(float(remaining)) or remaining <= 0):
            _fail("invalid")
        return min(evaluator.timeout_seconds, float(remaining))

    contract = _contract(contract)
    try:
        validate_source_capabilities(contract)
    except (ValueError, TypeError):
        _fail("unsupported_constraints")
    extended = bool(source_constraints(contract))
    evaluator = parse_candidate_evaluation_spec(evaluator)
    effective_timeout()
    pins = {
        "expected_admission_sha256": expected_admission_sha256,
        "expected_plan_sha256": expected_plan_sha256,
        "expected_bundle_sha256": expected_bundle_sha256,
        "expected_contract_sha256": expected_contract_sha256,
    }
    try:
        plan, admission, binding = evidence._request(admission, plan, pins)
    except evidence.CandidateExecutionEvidenceError as exc:
        _fail("plan_mismatch" if exc.code.endswith("plan_mismatch") else "admission_mismatch")
    if contract.digest() != plan.contract_sha256:
        _fail("contract_mismatch")
    if admission.evaluator != evaluator.pin():
        _fail("evaluator_mismatch")
    output_digest = candidate_output_contract_sha256(contract.outputs)
    if admission.output_contract_sha256 != output_digest:
        _fail("output_contract_mismatch")
    if expected_completion_sha256 is not None:
        _digest(expected_completion_sha256)
    try:
        workspace, inputs, attempt, parent, harness_path = map(
            absolute_path, (workspace_path, input_path, attempt_path, evaluation_root, harness_path),
        )
        with _Resources() as stack:
            roots = [_chain(path, stack) for path in (workspace, inputs, attempt, parent)]
            workspace_chain, input_chain, attempt_chain, parent_chain = roots
            for index, first in enumerate(roots[:3]):
                for second in roots[index + 1:3]:
                    evidence._disjoint(first, second)
                if identity(os.fstat(first.fd)) in {identity(os.fstat(fd)) for fd in parent_chain.fds}:
                    _fail("root_unsafe")
            record = evidence._inspect(attempt_chain, plan, admission, binding)
            if (record.status != "recorded" or record.to_dict()["runner_result"]["status"] != "succeeded"):
                _fail("execution_invalid")
            if expected_completion_sha256 is not None and expected_completion_sha256 != record.completion_sha256:
                _fail("identity_mismatch")
            intent_bytes, intent_descriptor = evidence._read(attempt_chain, "launch-intent.json")
            intent = evidence._decode(intent_bytes)
            if (_sha(intent_bytes) != record.launch_intent_sha256
                    or intent["workspace_identity"] != evidence._node(os.fstat(workspace_chain.fd))
                    or intent["input_identity"] != evidence._node(os.fstat(input_chain.fd))):
                _fail("identity_mismatch")
            observations = [
                _Observation(attempt / name, evidence.MAX_EXECUTION_RECORD_BYTES, stack,
                             code="execution_invalid")
                for name in ("launch-intent.json", "result.json", "completed.json")
            ]
            if observations[0].content != intent_bytes or observations[0].descriptor != intent_descriptor:
                _fail("identity_mismatch")
            if (_sha(observations[1].content) != record.result_sha256
                    or _sha(observations[2].content) != record.completion_sha256):
                _fail("identity_mismatch")
            for item in plan.bundle.files:
                observed = _Observation(workspace / item.path, item.size, stack, code="source_changed")
                observations.append(observed)
                if len(observed.content) != item.size or _sha(observed.content) != item.sha256:
                    _fail("source_changed")
            source_evidence = source_check_evidence(contract, plan.bundle) if extended else None
            source_valid = source_evidence["validity"] if extended else True
            input_observations = []
            for item in admission.inputs:
                observed = _Observation(inputs / item.target, item.size, stack, code="input_changed")
                observations.append(observed)
                input_observations.append(observed)
                if len(observed.content) != item.size or _sha(observed.content) != item.sha256:
                    _fail("input_changed")
            harness = _Observation(harness_path, evaluator.harness_size, stack, code="harness_changed")
            observations.append(harness)
            _validate_harness(harness.content, evaluator)
            output_observations, output_table = [], []
            total = 0
            for item in sorted(contract.outputs, key=lambda s: s.path):
                observed = _Observation(workspace / item.path, evaluator.max_output_file_bytes, stack,
                                        code="output_changed", optional=True)
                observations.append(observed)
                output_observations.append(observed)
                content = observed.content
                total += len(content) if content is not None else 0
                if total > evaluator.max_total_output_bytes:
                    _fail("output_changed")
                output_table.append({
                    "path": item.path, "present": content is not None,
                    "size": len(content) if content is not None else None,
                    "sha256": _sha(content) if content is not None else None,
                })
            request = {
                "protocol": _REQUEST_PROTOCOL, "schema_version": "1", "observation": "evaluation-time",
                "binding": {**binding, "launch_intent_sha256": record.launch_intent_sha256,
                            "completion_sha256": record.completion_sha256,
                            "evaluator_fingerprint": evaluator.digest(), "output_contract_sha256": output_digest},
                "contract": contract.to_dict(), "evaluator": evaluator.to_dict(),
                "inputs": [item.to_dict() for item in admission.inputs], "outputs": output_table,
            }
            _request_values(request)
            for observed in observations:
                observed.check()
            for root in roots:
                root.check()
            tree = PrivateTree(parent_chain, prefix=".candidate-evaluation-")
            stack.callback(_close, tree.close)
            destination = parent / tree.name
            copies = {"request.json": canonical_json(request), "evaluator.py": harness.content}
            copies.update({"inputs/" + item.target: observed.content for item, observed in zip(admission.inputs, input_observations, strict=True)})
            copies.update({item["path"]: observed.content for item, observed in zip(output_table, output_observations, strict=True) if item["present"]})
            for name, content in copies.items():
                tree.write(name, content)
            tree.sync_and_check()
            snapshots = {name: _Observation(destination / name, len(content), stack, code="snapshot_changed")
                         for name, content in copies.items()}
            for name, observed in snapshots.items():
                if observed.content != copies[name]:
                    _fail("snapshot_changed")
            valid = all(_format_valid(spec, observed.content) for spec, observed in
                        zip(sorted(contract.outputs, key=lambda s: s.path), output_observations, strict=True))
            for observed in observations:
                observed.check()
            executable = None
            if valid and source_valid:
                executable = _Executable(Path(evaluator.command[0]))
                stack.callback(_close, executable.close)
                executable.check()
                timeout = effective_timeout()
                try:
                    stdout, _, status, _, error = _bounded_process_bytes(
                        [*evaluator.command, "evaluator.py", "request.json"], cwd=str(destination),
                        environment=dict(evaluator.environment), timeout=timeout,
                        output_limit=MAX_REPORT_BYTES, capture_limit=MAX_REPORT_BYTES,
                        process_observer=process_observer,
                        process_released=process_released,
                        continuation_guard=effective_timeout if remaining_timeout is not None else None,
                    )
                except OSError:
                    _fail("process_start_failed")
                effective_timeout()
                if status != "succeeded":
                    _fail(error or "process_failed")
                report = parse_candidate_evaluation_report(stdout, evaluator_id=evaluator.evaluator_id)
                report_bytes = stdout
            elif not valid:
                report = _invalid_report(evaluator.evaluator_id)
                report_bytes = canonical_json(report.to_dict())
            else:
                report = source_failure_report(evaluator.evaluator_id, source_evidence)
                report_bytes = canonical_json(report.to_dict())
            for observed in [*observations, *snapshots.values()]:
                observed.check()
            if executable is not None:
                executable.check()
            for root in roots:
                root.check()
            if (evidence._inspect(attempt_chain, plan, admission, binding) != record
                    or evidence._read(attempt_chain, "launch-intent.json") != (intent_bytes, intent_descriptor)):
                _fail("identity_mismatch")
            tree.sync_and_check()
            effective_timeout()
            if extended:
                # The output harness must not supply or observe this independent evidence.
                tree.write("source-checks.json", canonical_json(source_evidence, maximum=MAX_SOURCE_CHECK_BYTES))
                snapshots["source-checks.json"] = _Observation(
                    destination / "source-checks.json", MAX_SOURCE_CHECK_BYTES, stack, code="snapshot_changed",
                )
            tree.write("report.json", report_bytes)
            report_file = _Observation(destination / "report.json", MAX_REPORT_BYTES, stack, code="snapshot_changed")
            manifest = {
                "protocol": _SOURCE_RECORD_PROTOCOL if extended else _RECORD_PROTOCOL,
                "schema_version": "1", "observation": "evaluation-time",
                "evaluation_identity": evidence._node(os.fstat(tree.fd)), "binding": request["binding"],
                "files": {**{name: observed.descriptor for name, observed in snapshots.items()},
                          "report.json": report_file.descriptor},
                "report": report.to_dict(), "output_contract_valid": valid,
                "harness_invoked": valid and source_valid,
            }
            if extended:
                manifest["source_constraints_valid"] = source_valid
            for observed in observations:
                observed.check()
            effective_timeout()
            tree.write("evaluation.json", canonical_json(manifest))
            tree.sync_and_check()
            return inspect_candidate_evaluation(
                destination, expected_evaluation_sha256=_sha(canonical_json(manifest)),
            )
    except (SolveExecutionBudgetExceeded, SolveExecutionCancelled):
        raise
    except evidence.CandidateExecutionEvidenceError:
        _fail("execution_invalid")
    except CandidateExecutionRunnerError:
        _fail("evaluator_mismatch")
    except BenchmarkFileError:
        _fail("root_unsafe")
    except (OSError, CandidateWorkspaceError):
        _fail("snapshot_changed")


__all__ = ["CandidateEvaluationResult", "evaluate_candidate_execution", "inspect_candidate_evaluation"]
