"""Executable adapters for the frozen reference-benchmark effect-trial protocol.

The module owns no benchmark data or service credentials. It runs Lunar Evolution as a fresh normal
subject, invokes owner-supplied frozen extractor/evaluator scripts, and converts an authorized
local FM-Eval WebAgent results export into the strict Feature 048 baseline schema.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import signal
import stat
import subprocess
import sys
import tempfile
import unicodedata
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .agent_loop import AgentLoopRuntime
from .deep_feedback import FeedbackError, normalize_feedback
from .effect_trial import (
    MAX_COST_MICROS,
    BaselineModel,
    BaselineProvenance,
    BenchmarkIdentity,
    EvaluationProfileIdentity,
    HarnessIdentity,
    PublicFile,
    TrialBaseline,
    TrialSuite,
)
from .profiles import ModelProfile
from .runtime import OpenAICompatibleRuntime
from .staged_workflow import StagedWorkflowConfig, StagedWorkflowRunner
from .subject_diagnostics import SubjectDiagnosticContext, SubjectDiagnosticObserver
from .tools import LocalToolRegistry
from .workflow_checkpoint import WorkflowController

MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_PROCESS_OUTPUT_BYTES = 2 * 1024 * 1024
MAX_ROWS = 10_000
MAX_TIMEOUT_SECONDS = 86_400.0
_LFS_PREFIX = b"version https://git-lfs.github.com/spec/v1"
_LFS_MAX_SIZE = 4096
_BASE_ENVIRONMENT = {
    "PATH": os.defpath,
    "LANG": "C.UTF-8",
    "LC_ALL": "C.UTF-8",
    "PYTHONUTF8": "1",
    "PYTHONDONTWRITEBYTECODE": "1",
}
_EXTRACTOR_BASE_ENV_NAMES = {
    "PATH",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TERM",
    "TZ",
    "PYTHONPATH",
    "PYTHONUNBUFFERED",
    "LD_LIBRARY_PATH",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "no_proxy",
    "IS_SANDBOX",
}
_MEDIA_TYPES = {
    ".csv": "text/csv",
    ".dockerfile": "text/plain",
    ".jar": "application/java-archive",
    ".json": "application/json",
    ".jsonl": "application/x-ndjson",
    ".md": "text/markdown",
    ".png": "image/png",
    ".py": "text/x-python",
    ".sh": "text/x-shellscript",
    ".toml": "application/toml",
    ".txt": "text/plain",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".yaml": "application/yaml",
    ".yml": "application/yaml",
    ".zip": "application/zip",
}
_BASELINE_ADAPTERS = {"agentserver", "company-platform", "webagent"}
_SAFE_BASELINE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


class EffectAdapterError(ValueError):
    """A built-in effect adapter request or external result is invalid."""

    def __init__(self, message: str, *, diagnostic_code: str | None = None) -> None:
        super().__init__(message)
        self.diagnostic_code = diagnostic_code


def _strict_object(value: object, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise EffectAdapterError(f"{label} must contain exactly: {', '.join(sorted(fields))}")
    return value


def _read_json(path: str | Path, label: str) -> dict[str, Any]:
    target = Path(path).expanduser()
    if target.is_symlink() or not target.is_file():
        raise EffectAdapterError(f"{label} must be a regular non-symlink file")
    content = target.read_bytes()
    if not content or len(content) > MAX_JSON_BYTES:
        raise EffectAdapterError(f"{label} exceeds its bounded size")
    try:
        value = json.loads(content)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise EffectAdapterError(f"{label} must be valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise EffectAdapterError(f"{label} must contain a JSON object")
    return value


def _atomic_json(path: Path, payload: object, *, overwrite: bool = True) -> None:
    content = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    if len(content) > MAX_JSON_BYTES:
        raise EffectAdapterError("adapter output exceeds its bounded size")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink() or (path.exists() and not overwrite):
        reason = "must not be a symlink" if path.is_symlink() else "already exists"
        raise EffectAdapterError(f"output {reason}: {path.name}")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        if overwrite:
            os.replace(temporary, path)
        else:
            try:
                os.link(temporary, path)
            except FileExistsError as exc:
                raise EffectAdapterError(f"output already exists: {path.name}") from exc
            temporary.unlink()
    finally:
        temporary.unlink(missing_ok=True)


def _relative_path(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or "\x00" in value
        or len(value.encode("utf-8")) > 1024
    ):
        raise EffectAdapterError(f"{label} must be a bounded POSIX relative path")
    path = Path(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise EffectAdapterError(f"{label} must be a confined relative path")
    return path.as_posix()


def _confined(root: Path, relative: str, label: str) -> Path:
    target = (root / relative).resolve(strict=False)
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise EffectAdapterError(f"{label} escapes its declared root") from exc
    current = root / relative
    while current != root and current != current.parent:
        if current.is_symlink():
            raise EffectAdapterError(f"{label} contains a symlink")
        current = current.parent
    return target


def _bounded_text(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\x00" in value
        or len(value.encode("utf-8")) > 512
    ):
        raise EffectAdapterError(f"{label} must be bounded non-empty text")
    return value


def _integer(value: object, label: str, *, minimum: int = 0, maximum: int = 100_000) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise EffectAdapterError(f"{label} must be an integer between {minimum} and {maximum}")
    return value


def _finite(value: object, label: str, *, nullable: bool = False) -> float | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise EffectAdapterError(f"{label} must be finite" + (" or null" if nullable else ""))
    return float(value)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _case_role(relative: str) -> str:
    path = Path(relative)
    parts = path.parts
    if len(parts) == 1 and parts[0] in {"instruction.md", "instruction_en.md"}:
        return "public_instruction"
    if len(parts) == 2 and parts[0] == "queries" and path.suffix == ".md":
        return "public_instruction_variant"
    if len(parts) == 2 and parts[0] == "data":
        return "public_case_input"
    if len(parts) == 1 and parts[0] == "cover.png":
        return "catalog_media"
    if (len(parts) == 1 and parts[0] == "task.toml") or (
        len(parts) >= 2 and parts[0] == "environment"
    ):
        return "trusted_runtime_metadata"
    if len(parts) == 1 and (
        parts[0] in {"information.md", "gt.json"} or parts[0].startswith("ground_truth.")
    ):
        return "private_ground_truth"
    if parts and parts[0] == "baseline":
        return "private_ground_truth"
    if parts and parts[0] in {"tests", "change_log"}:
        return "private_verifier"
    raise EffectAdapterError(f"private case contains an unsupported path: {relative}")


def benchmark_case_content_digest(case_root: str | Path) -> str:
    """Hash a private reference case in the Lunar Evolution case-format domain.

    This namespace produces new identities. It is not byte-equivalent to the external
    benchmark's original case digest and does not reidentify archived baseline evidence.
    """
    root = Path(case_root).expanduser()
    if root.is_symlink() or not root.is_dir():
        raise EffectAdapterError("private case root must be a regular non-symlink directory")
    root = root.resolve()
    files: list[tuple[str, Path, os.stat_result]] = []
    folded: set[str] = set()
    for current, directories, names in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        kept: list[str] = []
        for name in sorted(directories):
            path = current_path / name
            info = os.lstat(path)
            if name in {".DS_Store", "__pycache__"}:
                continue
            if not stat.S_ISDIR(info.st_mode) or path.is_symlink():
                raise EffectAdapterError("private case contains a linked or special directory")
            kept.append(name)
        directories[:] = kept
        for name in sorted(names):
            if name == ".DS_Store" or name.endswith(".pyc"):
                continue
            path = current_path / name
            info = os.lstat(path)
            if path.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise EffectAdapterError("private case contains a linked or special file")
            relative = path.relative_to(root).as_posix()
            if unicodedata.normalize("NFC", relative) != relative:
                raise EffectAdapterError("private case path is not NFC-normalized")
            folded_path = relative.casefold()
            if folded_path in folded:
                raise EffectAdapterError("private case paths collide under case folding")
            folded.add(folded_path)
            files.append((relative, path, info))
    files.sort(key=lambda value: value[0].encode("utf-8"))
    rows: list[dict[str, object]] = []
    for ordinal, (relative, path, info) in enumerate(files):
        executable = bool(info.st_mode & 0o111)
        if executable and not relative.startswith(("tests/", "environment/")):
            raise EffectAdapterError("private case has an executable non-script file")
        if relative.startswith("data/"):
            basename = path.name
            if (
                basename.startswith("-")
                or len(basename.encode("utf-8")) > 255
                or any(not character.isprintable() for character in basename)
            ):
                raise EffectAdapterError(f"private case has an unsafe data filename: {relative}")
        content = path.read_bytes()
        if len(content) <= _LFS_MAX_SIZE and content.startswith(_LFS_PREFIX):
            raise EffectAdapterError(f"private case contains an unmaterialized Git LFS file: {relative}")
        rows.append(
            {
                "ordinal": ordinal,
                "path": relative,
                "role": _case_role(relative),
                "media_type": (
                    "text/plain"
                    if path.name == "Dockerfile"
                    else _MEDIA_TYPES.get(path.suffix.lower(), "application/octet-stream")
                ),
                "size_bytes": len(content),
                "mode": "0755" if executable else "0644",
                "content_digest": "sha256:" + hashlib.sha256(content).hexdigest(),
            }
        )
    if not any(row["path"] == "instruction.md" for row in rows):
        raise EffectAdapterError("private case is missing instruction.md")
    payload = {
        "schema_revision": "case-content-v1",
        "case_format": "lunar-evolution-case-v1",
        "files": rows,
    }
    canonical = json.dumps(
        payload, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _verify_candidate_public_projection(candidate: Path, case_root: Path) -> None:
    projected = candidate / "case"
    if projected.is_symlink() or not projected.is_dir():
        raise EffectAdapterError("candidate public case projection is missing or unsafe")
    expected: dict[str, str] = {}
    instruction = case_root / "instruction.md"
    if instruction.is_symlink() or not instruction.is_file():
        raise EffectAdapterError("private case public instruction is missing or unsafe")
    expected["instruction.md"] = _sha256(instruction)
    data_root = case_root / "data"
    for source in sorted(data_root.iterdir(), key=lambda value: value.name.encode("utf-8")):
        if source.name in {".DS_Store", "__pycache__"} or source.name.endswith(".pyc"):
            continue
        if source.is_symlink() or not source.is_file():
            raise EffectAdapterError("private case data must contain only regular files")
        expected[f"data/{source.name}"] = _sha256(source)
    actual: dict[str, str] = {}
    for path in projected.rglob("*"):
        if path.is_symlink():
            raise EffectAdapterError("candidate public case projection contains a symlink")
        if path.is_file():
            actual[path.relative_to(projected).as_posix()] = _sha256(path)
    if actual != expected:
        raise EffectAdapterError("candidate public projection does not match the private CaseRevision")


def _verify_public_projection(
    workspace: Path, descriptors: Sequence[PublicFile], request_digest: str
) -> None:
    request_file = workspace / "request.json"
    if request_file.is_symlink() or not request_file.is_file() or _sha256(request_file) != request_digest:
        raise EffectAdapterError("subject changed the frozen request", diagnostic_code="frozen_request_changed")
    case_root = (workspace / "case").resolve()
    expected = {descriptor.path for descriptor in descriptors}
    actual: set[str] = set()
    for path in case_root.rglob("*"):
        if path.is_symlink():
            raise EffectAdapterError("subject public projection contains a symlink", diagnostic_code="public_symlink")
        if path.is_file():
            actual.add(path.relative_to(case_root).as_posix())
    if actual != expected:
        raise EffectAdapterError("subject changed the public projection file set", diagnostic_code="public_file_set_changed")
    for descriptor in descriptors:
        path = _confined(case_root, descriptor.path, "subject public file")
        if (
            path.is_symlink()
            or not path.is_file()
            or path.stat().st_size != descriptor.size
            or _sha256(path) != descriptor.sha256
        ):
            raise EffectAdapterError("subject changed a frozen public file", diagnostic_code="public_file_changed")


def _model_usage(metadata: Mapping[str, str]) -> dict[str, int] | None:
    keys = ("input_tokens", "output_tokens", "total_tokens")
    if not all(key in metadata for key in keys):
        return None
    try:
        usage = {key: int(metadata[key]) for key in keys}
    except (TypeError, ValueError) as exc:
        raise EffectAdapterError("subject runtime returned malformed token usage") from exc
    if (
        any(value < 0 for value in usage.values())
        or usage["input_tokens"] + usage["output_tokens"] != usage["total_tokens"]
    ):
        raise EffectAdapterError("subject runtime returned inconsistent token usage")
    return usage


def _model_profile_digest(profile: ModelProfile | None) -> str | None:
    """Return the credential-free canonical identity of a model profile."""
    if profile is None:
        return None
    canonical = json.dumps(
        profile.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _profile_digest(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise EffectAdapterError("subject model profile digest must be a SHA-256 hex string")
    return value


def run_subject_adapter(
    request_path: str | Path,
    *,
    endpoint: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    max_steps: int = 100,
    allow_exec: bool = True,
    timeout: float | None = None,
    model_runtime: object | None = None,
    model_profile: ModelProfile | None = None,
    workflow_config: StagedWorkflowConfig | None = None,
) -> dict[str, object]:
    """Run a fresh subject, optionally with same-process stages in normal mode.

    Deep requests intentionally execute one outer round at a time.  The caller owns the shared
    attempt workspace and supplies the bounded previous-round evaluator summary; this adapter still
    starts a fresh, stateless Agent session and never discovers machine-wide Agent state.
    """
    request_file = Path(request_path).expanduser()
    raw_request = _read_json(request_file, "subject request")
    mode = raw_request.get("mode") if isinstance(raw_request, dict) else None
    normal_fields = {
        "schema_version",
        "mode",
        "benchmark",
        "case",
        "run_index",
        "requested_model",
        "entrypoint",
        "public_files",
        "receipt_path",
    }
    # Profile provenance was added after the initial effect protocol.  Keep requests produced by
    # older kits readable while accepting the bound digest on all newly generated requests.
    profile_fields = normal_fields | {"model_profile_sha256"}
    deep_fields = normal_fields | {
        "round_index",
        "outer_rounds",
        "previous_evaluation",
    }
    deep_profile_fields = deep_fields | {"model_profile_sha256"}
    if mode == "normal":
        if set(raw_request) not in (normal_fields, profile_fields):
            raise EffectAdapterError(
                f"subject request must contain exactly: {', '.join(sorted(normal_fields))}"
            )
        request = dict(raw_request)
    elif mode == "deep_evolution":
        if set(raw_request) not in (deep_fields, deep_profile_fields):
            raise EffectAdapterError(
                f"deep subject request must contain exactly: {', '.join(sorted(deep_fields))}"
            )
        request = dict(raw_request)
    else:
        raise EffectAdapterError("subject request must describe schema v1 normal or deep_evolution mode")
    if request["schema_version"] != "1":
        raise EffectAdapterError("subject request must use schema version 1")
    if workflow_config is not None and mode != "normal":
        raise EffectAdapterError("staged workflow requires normal mode")
    BenchmarkIdentity.from_dict(request["benchmark"])
    case = _strict_object(request["case"], {"key", "revision_id", "digest"}, "subject case")
    for key, value in case.items():
        _bounded_text(value, f"subject case {key}")
    _integer(request["run_index"], "subject run index", minimum=1, maximum=1_000_000)
    requested_model = _bounded_text(request["requested_model"], "subject requested model")
    profile_digest = _profile_digest(request.get("model_profile_sha256"))
    expected_profile_digest = _model_profile_digest(model_profile)
    if model_profile is not None and model_profile.model != requested_model:
        raise EffectAdapterError("subject model profile model does not match the requested model")
    if "model_profile_sha256" in request and profile_digest != expected_profile_digest:
        raise EffectAdapterError("subject model profile digest does not match the supplied profile")
    if model_profile is not None and "model_profile_sha256" not in request:
        raise EffectAdapterError("subject request is missing model profile digest")
    entrypoint = _relative_path(request["entrypoint"], "subject entrypoint")
    receipt_relative = _relative_path(request["receipt_path"], "subject receipt path")
    round_index: int | None = None
    outer_rounds: int | None = None
    if mode == "deep_evolution":
        round_index = _integer(request["round_index"], "subject round index", minimum=1, maximum=1000)
        outer_rounds = _integer(request["outer_rounds"], "subject outer rounds", minimum=1, maximum=1000)
        if round_index > outer_rounds:
            raise EffectAdapterError("subject round index exceeds outer rounds")
        previous = request["previous_evaluation"]
        if previous is not None:
            try:
                normalize_feedback(previous, expected_round=round_index - 1)
            except FeedbackError as exc:
                raise EffectAdapterError(str(exc)) from exc
        elif round_index != 1:
            raise EffectAdapterError("deep subject continuation requires previous evaluation")
    if not isinstance(request["public_files"], list) or not request["public_files"]:
        raise EffectAdapterError("subject public file ledger must be a non-empty array")
    descriptors = tuple(PublicFile.from_dict(item) for item in request["public_files"])
    if len({item.path for item in descriptors}) != len(descriptors):
        raise EffectAdapterError("subject public file ledger contains duplicate paths")
    if entrypoint not in {item.path for item in descriptors}:
        raise EffectAdapterError("subject entrypoint is absent from the public file ledger")
    workspace = request_file.parent.resolve()
    if request_file.resolve() != workspace / request_file.name or request_file.is_symlink():
        raise EffectAdapterError("subject request path is unsafe")
    request_digest = _sha256(request_file)
    instruction_path = _confined(workspace / "case", entrypoint, "subject entrypoint")
    if instruction_path.is_symlink() or not instruction_path.is_file():
        raise EffectAdapterError("subject entrypoint does not exist")
    instruction = instruction_path.read_text(encoding="utf-8")
    if not instruction or len(instruction.encode("utf-8")) > 512 * 1024:
        raise EffectAdapterError("subject entrypoint exceeds its bounded size")
    receipt_path = _confined(workspace, receipt_relative, "subject receipt")
    if receipt_path.exists() or receipt_path.is_symlink():
        raise EffectAdapterError("subject receipt already exists or is unsafe")

    diagnostic_context = SubjectDiagnosticContext.from_request(workspace, request, request_digest)
    diagnostic_observer = SubjectDiagnosticObserver()
    agent = None
    try:
        runtime = model_runtime
        if runtime is None:
            runtime = OpenAICompatibleRuntime(endpoint=endpoint, model=model, api_key=api_key)
        configured_model = getattr(runtime, "model", None)
        effective_configured = model or configured_model
        if not isinstance(effective_configured, str) or effective_configured != requested_model:
            raise EffectAdapterError("subject runtime model does not match the requested model")
        if not 1 <= max_steps <= 10_000:
            raise EffectAdapterError("subject max_steps must be between 1 and 10000")
        if timeout is not None and (
            isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or not 0 < timeout <= MAX_TIMEOUT_SECONDS
        ):
            raise EffectAdapterError("subject timeout must be finite and within one day")

        runtime_api_key = getattr(runtime, "api_key", None)
        redactions = (runtime_api_key,) if isinstance(runtime_api_key, str) and runtime_api_key else ()
        diagnostic_observer.stage, diagnostic_observer.code = "public_projection", "public_projection_failed"
        _verify_public_projection(workspace, descriptors, request_digest)
        diagnostic_observer.stage, diagnostic_observer.code = "runtime", "runtime_failed"
        effective_max_steps = min(max_steps, model_profile.max_steps) if model_profile else max_steps
        effective_timeout = timeout
        if model_profile is not None:
            effective_timeout = min(
                model_profile.timeout_seconds,
                timeout if timeout is not None else model_profile.timeout_seconds,
            )
        if workflow_config is not None:
            if not isinstance(workflow_config, StagedWorkflowConfig):
                raise EffectAdapterError("workflow_config must be a StagedWorkflowConfig")
            manifest = workflow_config.manifest
            if model_profile is None or model_profile.max_total_tokens is None:
                raise EffectAdapterError("staged workflow requires a model profile with token ceiling")
            if (
                manifest.request_sha256 != request_digest
                or manifest.case_key != case["key"]
                or manifest.suite_key != request["benchmark"]["name"]
                or manifest.model_profile_sha256 != expected_profile_digest
                or dict(manifest.ceilings) != {
                    "max_wall_seconds": effective_timeout,
                    "max_tool_steps": effective_max_steps,
                    "max_total_tokens": model_profile.max_total_tokens,
                    "max_cost_micros": model_profile.max_cost_micros,
                }
            ):
                raise EffectAdapterError("staged manifest does not match frozen request/profile/limits")
            if (workspace / "workflow").exists() or (workspace / "workflow").is_symlink():
                raise EffectAdapterError("staged workflow requires a fresh attempt directory")
        tools = LocalToolRegistry(
            allow_exec=allow_exec,
            command_timeout=min(float(effective_timeout or 300.0), 300.0),
            redactions=redactions,
            command_environment={
                **_BASE_ENVIRONMENT,
                "PATH": os.environ.get("PATH", os.defpath),
            },
        )
        agent = AgentLoopRuntime(
            runtime,
            tools=tools,
            max_steps=effective_max_steps,
            profile=model_profile,
        )
        def subject_event(kind: str, payload: dict[str, object]) -> None:
            if workflow_config is not None and kind == "agent_model_turn":
                payload = {**payload, "turn": diagnostic_observer.model_turns + 1}
            diagnostic_observer.event(kind, payload)

        agent.set_event_sink(subject_event)
        if mode == "normal":
            prompt = f"""You are the normal-mode subject under an external reference-benchmark evaluation.

Solve the public task below and create the requested concrete data/solution files inside this
attempt workspace. Inspect `case/` as needed. Use `_agent_summary.md` to identify your final answer
file for the independent extractor. Do not score, evaluate, or claim a benchmark result yourself;
a separate private harness does that after you finish. Do not modify `request.json` or public files.
The entire `case/` tree is read-only: do not create scripts/caches, edit, delete, or rename any
file or directory within it. Write code and outputs elsewhere in this workspace, for example
`solve.py` and `output/`, and reference input files through `case/data/...`.

Public entrypoint: case/{entrypoint}
Case key: {case['key']}

--- public instruction ---
{instruction}
--- end instruction ---
"""
        else:
            previous = request["previous_evaluation"]
            feedback = "No previous round exists; establish a correct baseline candidate."
            if isinstance(previous, dict):
                try:
                    normalized_previous = normalize_feedback(previous, expected_round=round_index - 1)
                except FeedbackError as exc:
                    raise EffectAdapterError(str(exc)) from exc
                feedback = (
                    "Previous evaluator feedback (use only to improve the candidate; it is a bounded "
                    "projection, not private evaluator output):\n"
                    + json.dumps(normalized_previous, ensure_ascii=False, sort_keys=True)
                )
            prompt = f"""You are the deep-evolution subject in outer round {round_index}/{outer_rounds}.

Start a fresh bounded Agent session, but continue from the candidate artifacts already present in
this attempt workspace. Improve the concrete solution for the public task and preserve any valid
work while fixing weaknesses. The independent private harness will score this round after you
finish; never write a score or claim benchmark results. Do not modify request.json or public files.
The entire `case/` tree is read-only: do not create scripts/caches, edit, delete, or rename any
file or directory within it. Write code and outputs elsewhere in this workspace, for example
`solve.py` and `output/`, and reference input files through `case/data/...`.

{feedback}
Public entrypoint: case/{entrypoint}
Case key: {case['key']}

--- public instruction ---
{instruction}
--- end instruction ---
"""
        diagnostic_observer.stage, diagnostic_observer.code = "runtime", "runtime_failed"
        try:
            if workflow_config is None:
                result = agent.run(prompt, workspace, timeout=effective_timeout)
            else:
                controller = WorkflowController(workspace, workflow_config.manifest)
                staged = StagedWorkflowRunner(
                    controller, agent, workspace, policy=workflow_config.policy,
                )
                outcome = staged.run(prompt)
                if outcome.status == "checkpointed":
                    outcome = staged.resume()
                if outcome.status != "build_ready" or outcome.runtime is None:
                    raise EffectAdapterError("staged build did not complete")
                result = outcome.runtime
        except Exception as exc:
            raise EffectAdapterError(f"subject runtime failed: {type(exc).__name__}") from exc
        diagnostic_observer.stage, diagnostic_observer.code = "public_projection", "public_projection_failed"
        _verify_public_projection(workspace, descriptors, request_digest)
        diagnostic_observer.stage, diagnostic_observer.code = "receipt", "receipt_invalid"
        turns = _integer(int(result.metadata.get("turns", "0")), "subject interaction turns")
        response_model = result.metadata.get("response_model")
        if response_model:
            effective_model = _bounded_text(response_model, "subject response model")
            model_evidence = "provider_observed"
        else:
            effective_model = requested_model
            model_evidence = "runtime_observed"
        receipt: dict[str, object] = {
            "schema_version": "1",
            "mode": mode,
            "status": "completed",
            "requested_model": requested_model,
            "effective_model": effective_model,
            "model_evidence": model_evidence,
            "interaction_turns": turns,
            "usage": _model_usage(result.metadata),
        }
        if model_profile is not None:
            receipt["model_profile_sha256"] = expected_profile_digest
            receipt["cost_micros"] = (
                _integer(
                    int(result.metadata["cost_micros"]),
                    "subject cost micros",
                    minimum=0,
                    maximum=MAX_COST_MICROS,
                )
                if "cost_micros" in result.metadata
                else None
            )
        if mode == "deep_evolution":
            # Keep the score-free subject receipt bound to the exact request that drove this fresh
            # round.  The deep runner may reuse a receipt after an interruption, so a round/outer
            # index alone is insufficient to distinguish a stale receipt from the current request.
            receipt.update(
                {
                    "round_index": round_index,
                    "outer_rounds": outer_rounds,
                    "request_sha256": request_digest,
                }
            )
        _atomic_json(receipt_path, receipt, overwrite=False)
        return receipt
    except Exception as exc:
        code = exc.diagnostic_code if isinstance(exc, EffectAdapterError) else None
        accepted_usage = None
        try:
            if agent is not None:
                accepted_usage = agent.last_invocation.accepted_usage
        except Exception:  # noqa: BLE001 - optional diagnostics cannot mask the execution failure
            accepted_usage = None
        diagnostic_observer.emit_failure(
            diagnostic_context, exc, code=code, accepted_usage=accepted_usage,
        )
        raise


def _parse_process_json(content: bytes, label: str) -> dict[str, Any]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EffectAdapterError(f"{label} output is not UTF-8") from exc
    stripped = text.strip()
    try:
        value = json.loads(stripped)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for index, character in enumerate(text):
        if character != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise EffectAdapterError(f"{label} did not return a JSON object")


def _run_process(
    command: Sequence[str], *, cwd: Path, environment: Mapping[str, str], timeout: float
) -> tuple[int, bytes, bool]:
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        try:
            process = subprocess.Popen(
                command,
                cwd=cwd,
                env=dict(environment),
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
                close_fds=True,
            )
            try:
                returncode = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
                return 124, b"", False
        except OSError:
            return 127, b"", False
        stdout.seek(0)
        output = stdout.read(MAX_PROCESS_OUTPUT_BYTES + 1)
        bounded = len(output) <= MAX_PROCESS_OUTPUT_BYTES
        return returncode, output[:MAX_PROCESS_OUTPUT_BYTES], bounded


def _harness_failure(request: dict[str, Any], extraction_status: str) -> dict[str, object]:
    return {
        "schema_version": "1",
        "status": "completed",
        "benchmark": request["benchmark"],
        "evaluation_profile": request["evaluation_profile"],
        "case": request["case"],
        "harness": request["harness"],
        "extraction_status": extraction_status,
        "validity_score": 0.0,
        "overall_score": 0.0,
        "quality_score": 0.0,
        "detail_metrics": {},
    }


def _verify_harness_scripts(
    extractor: Path, evaluator: Path, identity: HarnessIdentity
) -> None:
    if (
        extractor.is_symlink()
        or not extractor.is_file()
        or evaluator.is_symlink()
        or not evaluator.is_file()
    ):
        raise EffectAdapterError("private case extractor/evaluator is missing or unsafe")
    if _sha256(extractor) != identity.extractor_sha256:
        raise EffectAdapterError("extractor digest does not match the frozen harness identity")
    if _sha256(evaluator) != identity.evaluator_sha256:
        raise EffectAdapterError("evaluator digest does not match the frozen harness identity")


def run_harness_adapter(
    request_path: str | Path,
    case_root: str | Path,
    *,
    python_bin: str | Path = sys.executable,
    extractor_environment: Mapping[str, str] | None = None,
    timeout: float = 600.0,
) -> dict[str, object]:
    """Run one exact owner-supplied reference-benchmark extractor/evaluator pair."""
    request_file = Path(request_path).expanduser()
    request = _strict_object(
        _read_json(request_file, "harness request"),
        {
            "schema_version",
            "candidate_workspace",
            "run_index",
            "benchmark",
            "evaluation_profile",
            "case",
            "harness",
            "receipt_path",
        },
        "harness request",
    )
    if request["schema_version"] != "1":
        raise EffectAdapterError("harness request must use schema version 1")
    BenchmarkIdentity.from_dict(request["benchmark"])
    EvaluationProfileIdentity.from_dict(request["evaluation_profile"])
    case = _strict_object(request["case"], {"key", "revision_id", "digest"}, "harness case")
    for key, value in case.items():
        _bounded_text(value, f"harness case {key}")
    identity = HarnessIdentity.from_dict(request["harness"])
    _integer(request["run_index"], "harness run index", minimum=1, maximum=1_000_000)
    if request["candidate_workspace"] != "../subject":
        raise EffectAdapterError("candidate workspace must be the sibling ../subject directory")
    receipt_relative = _relative_path(request["receipt_path"], "harness receipt path")
    harness_root = request_file.parent.resolve()
    if request_file.is_symlink() or request_file.resolve() != harness_root / request_file.name:
        raise EffectAdapterError("harness request path is unsafe")
    attempt_root = harness_root.parent.resolve()
    candidate = _confined(attempt_root, "subject", "candidate workspace")
    if candidate.is_symlink() or not candidate.is_dir():
        raise EffectAdapterError("candidate workspace must be a regular directory")
    receipt_path = _confined(harness_root, receipt_relative, "harness receipt")
    if receipt_path.exists() or receipt_path.is_symlink():
        raise EffectAdapterError("harness receipt already exists or is unsafe")
    case_path = Path(case_root).expanduser()
    if case_path.is_symlink() or not case_path.is_dir():
        raise EffectAdapterError("private case root must be a regular non-symlink directory")
    case_path = case_path.resolve()
    expected_case_digest = str(case["digest"])
    if benchmark_case_content_digest(case_path) != expected_case_digest:
        raise EffectAdapterError("private case content digest does not match the frozen CaseRevision")
    extractor = _confined(case_path, "tests/extractor_agent.py", "extractor script")
    evaluator = _confined(case_path, "tests/evaluator.py", "evaluator script")
    data_dir = _confined(case_path, "data", "private case data")
    if not data_dir.is_dir() or data_dir.is_symlink():
        raise EffectAdapterError("private case data directory is missing or unsafe")
    _verify_harness_scripts(extractor, evaluator, identity)
    _verify_candidate_public_projection(candidate, case_path)
    python_path = Path(python_bin).expanduser()
    if not python_path.is_absolute() or not python_path.exists():
        raise EffectAdapterError("harness Python must be an absolute regular non-symlink file")
    python_path = python_path.resolve()
    if python_path.is_symlink() or not python_path.is_file():
        raise EffectAdapterError("harness Python must resolve to a regular file")
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not math.isfinite(timeout)
        or not 0 < timeout <= MAX_TIMEOUT_SECONDS
    ):
        raise EffectAdapterError("harness timeout must be finite and within one day")
    extras = dict(extractor_environment or {})
    if len(extras) > 64 or any(
        not isinstance(key, str)
        or not isinstance(value, str)
        or "\x00" in key
        or "=" in key
        or "\x00" in value
        for key, value in extras.items()
    ):
        raise EffectAdapterError("extractor environment is invalid")

    with tempfile.TemporaryDirectory(prefix="lunar-evolution-harness-") as temporary:
        working = Path(temporary)
        normalized = working / "normalized"
        private_home = working / "extractor-home"
        private_config = working / "extractor-config"
        private_tmp = working / "extractor-tmp"
        for directory in (normalized, private_home, private_config, private_tmp):
            directory.mkdir()
        inherited_base = {
            name: os.environ[name] for name in _EXTRACTOR_BASE_ENV_NAMES if name in os.environ
        }
        extractor_env = {
            **_BASE_ENVIRONMENT,
            **inherited_base,
            **extras,
            "HOME": str(private_home),
            "CLAUDE_CONFIG_DIR": str(private_config),
            "TMPDIR": str(private_tmp),
        }
        extractor_command = (
            str(python_path),
            "-B",
            str(extractor),
            "--evaluator",
            str(evaluator),
            "--workspace",
            str(candidate),
            "--output",
            str(normalized),
        )
        rc, output, bounded = _run_process(
            extractor_command, cwd=case_path, environment=extractor_env, timeout=float(timeout)
        )
        if benchmark_case_content_digest(case_path) != expected_case_digest:
            raise EffectAdapterError("extractor changed the frozen private CaseRevision")
        _verify_candidate_public_projection(candidate, case_path)
        if rc != 0 or not bounded:
            receipt = _harness_failure(request, "error")
        else:
            try:
                extracted = _parse_process_json(output, "extractor")
            except EffectAdapterError:
                receipt = _harness_failure(request, "error")
            else:
                extraction_status = str(extracted.get("status") or "error").lower()
                if extraction_status != "success":
                    safe_status = (
                        extraction_status
                        if extraction_status in {"partial", "failed", "error"}
                        else "error"
                    )
                    receipt = _harness_failure(request, safe_status)
                else:
                    evaluator_command = (
                        str(python_path),
                        "-B",
                        str(evaluator),
                        "--data-dir",
                        str(data_dir),
                        "--submission-dir",
                        str(normalized),
                    )
                    rc, output, bounded = _run_process(
                        evaluator_command,
                        cwd=case_path,
                        environment=_BASE_ENVIRONMENT,
                        timeout=float(timeout),
                    )
                    if benchmark_case_content_digest(case_path) != expected_case_digest:
                        raise EffectAdapterError("evaluator changed the frozen private CaseRevision")
                    _verify_candidate_public_projection(candidate, case_path)
                    if rc != 0 or not bounded:
                        receipt = _harness_failure(request, "evaluation_error")
                    else:
                        try:
                            evaluated = _parse_process_json(output, "evaluator")
                            overall = _finite(evaluated.get("overall_score"), "overall score")
                            validity = _finite(evaluated.get("validity_score"), "validity score")
                            quality = _finite(
                                evaluated.get("quality_score"), "quality score", nullable=True
                            )
                            if validity is None or not 0.0 <= validity <= 1.0:
                                raise EffectAdapterError(
                                    "validity score must be between zero and one"
                                )
                        except EffectAdapterError:
                            receipt = _harness_failure(request, "evaluation_error")
                        else:
                            details: dict[str, float | None] = {}
                            for key, value in evaluated.items():
                                if key in {"overall_score", "validity_score", "quality_score"}:
                                    continue
                                if (
                                    isinstance(key, str)
                                    and key.replace("_", "").replace("-", "").isalnum()
                                    and not isinstance(value, bool)
                                    and isinstance(value, (int, float))
                                    and math.isfinite(value)
                                    and len(details) < 64
                                ):
                                    details[key] = float(value)
                            receipt = {
                                "schema_version": "1",
                                "status": "completed",
                                "benchmark": request["benchmark"],
                                "evaluation_profile": request["evaluation_profile"],
                                "case": request["case"],
                                "harness": request["harness"],
                                "extraction_status": "completed",
                                "validity_score": validity,
                                "overall_score": overall,
                                "quality_score": quality,
                                "detail_metrics": details,
                            }
    _atomic_json(receipt_path, receipt, overwrite=False)
    return receipt


def _experiment_identity(payload: Mapping[str, object]) -> str | None:
    for container_name, key in (("experiment", "id"), ("meta", "experiment_id")):
        container = payload.get(container_name)
        if isinstance(container, dict) and isinstance(container.get(key), str):
            return container[key]
    return None


def _fm_eval_adapter_evidence(
    payload: Mapping[str, object],
    paths: Sequence[tuple[str, ...]],
) -> list[tuple[str, str]]:
    evidence: list[tuple[str, str]] = []
    for path in paths:
        current: object = payload
        for key in path:
            if not isinstance(current, Mapping) or key not in current:
                break
            current = current[key]
        else:
            if current is None:
                continue
            if not isinstance(current, str) or not current:
                raise EffectAdapterError(
                    f"FM-Eval adapter evidence at {'.'.join(path)} must be non-empty text"
                )
            evidence.append((".".join(path), current))
    return evidence


def _require_adapter_evidence(
    evidence: Sequence[tuple[str, str]], expected: str, *, allow_legacy_missing: bool
) -> None:
    if not _SAFE_BASELINE_ID.fullmatch(expected) or expected not in _BASELINE_ADAPTERS:
        raise EffectAdapterError("baseline adapter kind is not allowlisted")
    if not evidence:
        if allow_legacy_missing:
            return
        raise EffectAdapterError("FM-Eval export is missing explicit adapter evidence")
    kinds = {value for _, value in evidence}
    if len(kinds) != 1:
        raise EffectAdapterError("FM-Eval export contains conflicting adapter evidence")
    if kinds != {expected}:
        raise EffectAdapterError(f"FM-Eval baseline must come from the {expected} adapter")


def _normalized_extraction(value: object) -> str:
    status = str(value or "").lower()
    if status in {"success", "completed", "extracted"}:
        return "completed"
    return status if status in {"partial", "failed", "error", "evaluation_error"} else "error"


def convert_fm_eval_baseline(
    results_path: str | Path,
    suite_path: str | Path,
    output_path: str | Path,
    *,
    experiment_id: str,
    requested_model: str,
    effective_model: str,
    model_evidence: str,
    authority: str = "descriptive",
    conclusion_eligibility: str = "ineligible",
    content_equivalence_attested: bool = False,
    adapter_kind: str = "webagent",
    baseline_source: str = "fm-eval",
) -> dict[str, object]:
    """Convert an authorized local evaluation export to a strict per-run baseline."""
    results_payload = _read_json(results_path, "FM-Eval results export")
    suite = TrialSuite.from_dict(_read_json(suite_path, "frozen suite"))
    experiment_id = _bounded_text(experiment_id, "experiment id")
    if not _SAFE_BASELINE_ID.fullmatch(baseline_source):
        raise EffectAdapterError("baseline source must be a bounded safe identifier")
    if adapter_kind not in _BASELINE_ADAPTERS:
        raise EffectAdapterError("baseline adapter kind is not allowlisted")
    if not isinstance(content_equivalence_attested, bool):
        raise EffectAdapterError("content-equivalence attestation must be boolean")
    if content_equivalence_attested:
        if authority != "descriptive" or conclusion_eligibility != "ineligible":
            raise EffectAdapterError(
                "content-equivalence attestation conflicts with authority or eligibility"
            )
        authority = "owner_attested_content_equivalent"
        conclusion_eligibility = "ineligible"
    observed_id = _experiment_identity(results_payload)
    if observed_id is None:
        raise EffectAdapterError("FM-Eval export does not contain an experiment identity")
    if observed_id != experiment_id:
        raise EffectAdapterError("FM-Eval export experiment identity does not match")
    adapter_evidence = _fm_eval_adapter_evidence(
        results_payload,
        (
            ("adapter",),
            ("adapter_kind",),
            ("experiment", "adapter"),
            ("experiment", "adapter_kind"),
            ("experiment", "request", "adapter"),
            ("experiment", "request", "adapter_kind"),
            ("experiment", "request", "adapter_request", "kind"),
            ("experiment", "request", "resolved_adapter_release", "adapter_kind"),
            ("experiment", "configuration", "adapter"),
            ("experiment", "configuration", "adapter_kind"),
            ("experiment", "configuration", "adapter_release", "adapter_kind"),
            ("experiment", "adapter_release", "adapter_kind"),
        ),
    )
    model = BaselineModel.from_dict(
        {
            "requested": requested_model,
            "effective": effective_model,
            "evidence": model_evidence,
        }
    )
    rows = results_payload.get("results")
    if not isinstance(rows, list) or not rows or len(rows) > MAX_ROWS:
        raise EffectAdapterError("FM-Eval results must be a bounded non-empty array")
    selected = {case.key: [] for case in suite.cases}
    for row in rows:
        if not isinstance(row, dict):
            raise EffectAdapterError("FM-Eval result row must be an object")
        case_key = row.get("case") or row.get("case_key")
        if case_key not in selected:
            continue
        adapter_evidence.extend(
            _fm_eval_adapter_evidence(
                row,
                (
                    (
                        "runtime_telemetry",
                        "adapter_request",
                        "receipt",
                        "adapter_kind",
                    ),
                ),
            )
        )
        raw_index = row.get("run_index", row.get("run_idx"))
        index = _integer(raw_index, "FM-Eval run index", minimum=0, maximum=1_000_000)
        projection = str(row.get("projection_state") or "").lower()
        explicit_ready = row.get("ready")
        if explicit_ready is not None and not isinstance(explicit_ready, bool):
            raise EffectAdapterError("FM-Eval ready field must be boolean")
        score_present = row.get("overall_score") is not None and row.get("validity_score") is not None
        ready = (
            explicit_ready
            if isinstance(explicit_ready, bool)
            else projection == "ready"
            or (not projection and score_present and str(row.get("outcome") or "success").lower() in {"success", "succeeded", "completed"})
        )
        validity = _finite(row.get("validity_score"), "FM-Eval validity score", nullable=True)
        if validity is not None and not 0.0 <= validity <= 1.0:
            raise EffectAdapterError("FM-Eval validity score must be between zero and one")
        overall = _finite(row.get("overall_score"), "FM-Eval overall score", nullable=True)
        selected[str(case_key)].append(
            {
                "source_index": index,
                "ready": ready,
                "extraction_status": _normalized_extraction(row.get("extraction_status")),
                "validity_score": validity,
                "overall_score": overall,
            }
        )

    _require_adapter_evidence(
        adapter_evidence,
        adapter_kind,
        allow_legacy_missing=adapter_kind == "webagent",
    )

    cases: list[dict[str, object]] = []
    for case in suite.cases:
        case_rows = selected[case.key]
        if not case_rows:
            raise EffectAdapterError(f"FM-Eval export does not contain selected case {case.key}")
        shift = 1 if any(row["source_index"] == 0 for row in case_rows) else 0
        runs = [
            {
                "run_index": int(row["source_index"]) + shift,
                "ready": row["ready"],
                "extraction_status": row["extraction_status"],
                "validity_score": row["validity_score"],
                "overall_score": row["overall_score"],
            }
            for row in case_rows
        ]
        if len({run["run_index"] for run in runs}) != len(runs):
            raise EffectAdapterError(f"FM-Eval export contains duplicate run indexes for {case.key}")
        runs.sort(key=lambda value: int(value["run_index"]))
        cases.append(
            {
                "key": case.key,
                "revision_id": case.revision_id,
                "digest": case.digest,
                "harness": case.harness.to_dict(),
                "runs": runs,
            }
        )
    baseline: dict[str, object] = {
        "schema_version": "1",
        "source": baseline_source,
        "experiment_id": experiment_id,
        "authority": authority,
        "conclusion_eligibility": conclusion_eligibility,
        "benchmark": suite.benchmark.to_dict(),
        "evaluation_profile": suite.evaluation_profile.to_dict(),
        "model": model.to_dict(),
        "provenance": BaselineProvenance(baseline_source, adapter_kind).to_dict(),
        "cases": cases,
    }
    TrialBaseline.from_dict(baseline)
    _atomic_json(Path(output_path).expanduser(), baseline, overwrite=False)
    return baseline


__all__ = [
    "EffectAdapterError",
    "benchmark_case_content_digest",
    "convert_fm_eval_baseline",
    "run_harness_adapter",
    "run_subject_adapter",
]
