"""Typed foreground continuation seam for lifecycle-enabled automatic solves.

The continuation is an admission snapshot.  Native CLI orchestration remains the only execution
implementation; this module only verifies the snapshot immediately before delegating to it.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .automatic_solve_lifecycle import (
    AutomaticSolveExecutionOwner,
    SolveExecutionControl,
    _positive_timeout,
    own_automatic_solve,
)
from .candidate_evaluation_spec import canonical_json
from .config import Config


def _digest(value: object) -> str:
    return hashlib.sha256(canonical_json(value, maximum=512 * 1024)).hexdigest()


@dataclass(frozen=True, slots=True)
class AutomaticSolveContinuation:
    """Immutable native request/runtime pins for one synchronous continuation."""

    run_id: str
    workspace: str
    request_json: str
    request_sha256: str
    runtime_fingerprint: str
    manifest_sha256: str | None = None

    def __post_init__(self) -> None:
        if type(self.run_id) is not str or not self.run_id.strip() or "\x00" in self.run_id:
            raise ValueError("automatic continuation run_id is invalid")
        workspace = Path(self.workspace)
        if not workspace.is_absolute() or workspace.is_symlink():
            raise ValueError("automatic continuation workspace is invalid")
        request = self.request
        if (type(request) is not dict or request.get("automatic_lifecycle_version") != 1
                or request.get("bundle_mode") != "compiled"):
            raise ValueError("automatic continuation request is not lifecycle-enabled")
        expected = _digest(request)
        if self.request_sha256 != expected or len(expected) != 64:
            raise ValueError("automatic continuation request digest is invalid")
        for value, name in ((self.runtime_fingerprint, "runtime_fingerprint"), (self.manifest_sha256, "manifest_sha256")):
            if value is not None and (type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value)):
                raise ValueError(f"automatic continuation {name} is invalid")
        # Keep canonical bytes as the immutable authority; `request` is a fresh projection.
        object.__setattr__(self, "request_json", canonical_json(request, maximum=512 * 1024).decode("utf-8"))

    @property
    def request(self) -> dict[str, object]:
        if type(self.request_json) is not str or len(self.request_json.encode("utf-8")) > 512 * 1024:
            raise ValueError("automatic continuation request is invalid")
        return json.loads(self.request_json)

    @classmethod
    def capture(cls, controller: Any, run: Any) -> AutomaticSolveContinuation:
        from .cli import _compiler_fingerprint, _conversation_manifest, _latest_evolution_request

        request = _latest_evolution_request(controller.store, run.id)
        if (not isinstance(request, dict) or request.get("automatic_lifecycle_version") != 1
                or request.get("bundle_mode") != "compiled"):
            raise ValueError("automatic solve is not lifecycle-enabled")
        manifest = _conversation_manifest(run)
        manifest_sha256 = _digest(manifest) if manifest is not None else None
        return cls(
            run_id=run.id,
            workspace=str(Path(run.workspace).expanduser().resolve(strict=False)),
            request_json=canonical_json(request, maximum=512 * 1024).decode("utf-8"),
            request_sha256=_digest(request),
            runtime_fingerprint=_compiler_fingerprint(controller.runtime),
            manifest_sha256=manifest_sha256,
        )

    def verify(self, controller: Any, run: Any) -> None:
        from .cli import _compiler_fingerprint, _conversation_manifest, _latest_evolution_request

        if run.id != self.run_id or str(Path(run.workspace).expanduser().resolve(strict=False)) != self.workspace:
            raise ValueError("automatic continuation run identity changed")
        request = _latest_evolution_request(controller.store, run.id)
        if not isinstance(request, dict) or _digest(request) != self.request_sha256 or request != self.request:
            raise ValueError("automatic continuation request changed")
        if _compiler_fingerprint(controller.runtime) != self.runtime_fingerprint:
            raise ValueError("automatic continuation runtime changed")
        manifest = _conversation_manifest(run)
        current_manifest = _digest(manifest) if manifest is not None else None
        if current_manifest != self.manifest_sha256:
            raise ValueError("automatic continuation manifest changed")
        if manifest is not None and manifest.get("runtime_fingerprint") not in {None, self.runtime_fingerprint}:
            raise ValueError("automatic continuation compiler runtime changed")


def continue_automatic_solve(
    config: Config,
    controller: Any,
    continuation: AutomaticSolveContinuation,
    *,
    execution_control: SolveExecutionControl | None = None,
    owner: Any | None = None,
    parent_control: SolveExecutionControl | None = None,
    active_timeout: float | None = None,
) -> dict[str, object]:
    """Validate and continue one lifecycle Run through the existing CLI implementation."""

    if not isinstance(continuation, AutomaticSolveContinuation):
        raise TypeError("continuation must be AutomaticSolveContinuation")
    if execution_control is not None and not isinstance(execution_control, SolveExecutionControl):
        raise TypeError("execution_control must be SolveExecutionControl")
    if parent_control is not None and not isinstance(parent_control, SolveExecutionControl):
        raise TypeError("parent_control must be SolveExecutionControl")
    if active_timeout is not None:
        _positive_timeout(active_timeout, "worker active timeout")
    if owner is not None and (
        not isinstance(owner, AutomaticSolveExecutionOwner)
        or owner.parent_id != continuation.run_id
        or not getattr(owner, "_held", False)
        or owner.lock_fd is None
    ):
        raise ValueError("automatic continuation owner is not admitted")
    run = controller.store.get_run(continuation.run_id)
    if run is None:
        raise ValueError("automatic continuation run no longer exists")
    continuation.verify(controller, run)
    if owner is not None:
        retained = os.fstat(owner.lock_fd)
        named = (Path(run.workspace) / ".automatic-solve.lock").lstat()
        if (not stat.S_ISREG(named.st_mode) or retained.st_nlink != 1
                or (retained.st_dev, retained.st_ino) != (named.st_dev, named.st_ino)):
            raise ValueError("automatic continuation owner workspace changed")
    # Only native parser defaults and persisted policy reach private orchestration. There is
    # no public mutable namespace, detached flag, alternate model or internal bypass fields.
    from .cli import _evolution_args, _validate_evolution_override, build_parser
    args = build_parser().parse_args(["solve", "--resume", "--run-id", continuation.run_id])
    _validate_evolution_override(args, continuation.request)
    effective_args = _evolution_args(args, continuation.request)
    effective_args.detach = False
    effective_args._automatic_owner = owner
    if execution_control is not None:
        effective_args._solve_execution_control = execution_control
    effective_args._solve_parent_control = parent_control
    effective_args._solve_active_timeout = active_timeout
    from .cli import _continue_automatic_solve, _conversation_manifest

    with (nullcontext(owner) if owner is not None else own_automatic_solve(run.id, Path(run.workspace))) as held:
        run = controller.store.get_run(continuation.run_id)
        if run is None:
            raise ValueError("automatic continuation run no longer exists")
        continuation.verify(controller, run)
        for control in (execution_control, parent_control):
            if control is not None:
                control.check("contract")
        effective_args._automatic_owner = held
        return _continue_automatic_solve(config, effective_args, controller, run, _conversation_manifest(run))


__all__ = ["AutomaticSolveContinuation", "continue_automatic_solve"]
