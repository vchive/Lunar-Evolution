"""Opt-in fixed SSH byte channel with durable, once-only launch intent.

SSH exit and authenticated origin never establish native success, remote cleanup
or publication authority. Recovery reads only an existing remote sealed result.
"""

from __future__ import annotations

import re
import shlex
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .automatic_solve_lifecycle import SolveExecutionControl
from .external_worker_assignment import ExternalWorkerAssignments
from .external_worker_io import run_worker_channel
from .external_worker_wrapper import (
    MAX_WORKER_RESPONSE_BYTES,
    _read_private,
    parse_worker_json,
    parse_worker_response,
    validate_worker_request,
    worker_json,
    worker_request_budget,
)
from .rsi_callbacks import DurableCallbackJournal
from .rsi_gateway import SolverRequest

_SCOPE = "external-worker-ssh-transport-v1"
_SCHEMA = "lunar-external-worker-ssh-v1"
_IDENTITY = ("worker_id", "host_id", "host_boot_id", "key_id")
_HOST = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.@:-]{0,254}\Z")


class WorkerTransportError(ValueError):
    """Fixed errors that do not reveal private files or channel output."""


@dataclass(frozen=True, slots=True)
class SSHWorkerConfig:
    ssh_executable: str
    host: str
    remote_argv: tuple[str, ...]
    worker_id: str

    def __post_init__(self) -> None:
        if (type(self.ssh_executable) is not str or not self.ssh_executable
                or not Path(self.ssh_executable).is_absolute() or "\0" in self.ssh_executable
                or type(self.host) is not str or _HOST.fullmatch(self.host) is None
                or type(self.worker_id) is not str or not self.worker_id.strip()
                or len(self.worker_id.encode()) > 256 or any(c in self.worker_id for c in "\0\r\n")):
            raise WorkerTransportError("worker_transport_config_invalid")
        if (type(self.remote_argv) is not tuple or not self.remote_argv
                or len(self.remote_argv) > 64
                or any(type(x) is not str or not x or "\0" in x or len(x.encode()) > 8192
                       for x in self.remote_argv)
                or not Path(self.remote_argv[0]).is_absolute()):
            raise WorkerTransportError("worker_transport_command_invalid")

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": _SCHEMA, "ssh_executable": self.ssh_executable,
                "host": self.host, "remote_argv": list(self.remote_argv), "worker_id": self.worker_id}

    @classmethod
    def from_dict(cls, value: object) -> SSHWorkerConfig:
        if (type(value) is not dict or set(value) != {
                "schema_version", "ssh_executable", "host", "remote_argv", "worker_id"}
                or value["schema_version"] != _SCHEMA or type(value["remote_argv"]) is not list):
            raise WorkerTransportError("worker_transport_config_invalid")
        return cls(value["ssh_executable"], value["host"], tuple(value["remote_argv"]), value["worker_id"])


def load_ssh_worker_config(path: Path) -> SSHWorkerConfig:
    try:
        raw = _read_private(path, 65536)
        return SSHWorkerConfig.from_dict(parse_worker_json(raw, 65536))
    except Exception:  # noqa: BLE001
        # Normalize private file/configuration errors without exposing their details.
        raise WorkerTransportError("worker_transport_config_invalid") from None


class SSHWorkerTransport:
    def __init__(self, assignments: ExternalWorkerAssignments, config: SSHWorkerConfig):
        if type(assignments) is not ExternalWorkerAssignments or type(config) is not SSHWorkerConfig:
            raise WorkerTransportError("worker_transport_authority_invalid")
        self.assignments = assignments
        self.config = config
        self.journal = DurableCallbackJournal(assignments.ledger)

    @staticmethod
    def _ids(episode_id: str) -> tuple[str, str]:
        digest = DurableCallbackJournal.digest({"episode_id": episode_id})
        return "transport:" + digest, "external-worker-transport-guard:" + digest

    def _argv(self) -> tuple[str, ...]:
        return (self.config.ssh_executable, "-T", "-oBatchMode=yes",
                "-oStrictHostKeyChecking=yes", "-oClearAllForwardings=yes",
                "-oForwardAgent=no", "-oPermitLocalCommand=no", "-oRequestTTY=no",
                self.config.host, shlex.join(self.config.remote_argv))

    def _assignment(self, request, plan_sha256, expected):
        claim = self.assignments._guard(expected, request, plan_sha256)
        assignment = self.assignments.inspect(request.episode_id)
        if assignment is None or assignment["context"] is None:
            raise WorkerTransportError("worker_transport_assignment_required")
        binding = assignment["binding"]
        if (binding["request_sha256"] != request.digest() or binding["plan_sha256"] != plan_sha256
                or binding["claim_sha256"] != claim.claim_sha256
                or binding["worker_id"] != self.config.worker_id
                or self.assignments.registry.worker_identity(self.config.worker_id) != {
                    name: binding[name] for name in _IDENTITY}):
            raise WorkerTransportError("worker_transport_assignment_drift")
        return assignment

    def _entry(self, episode_id: str, assignment):
        callback_id, _guard_id = self._ids(episode_id)
        entry = self.journal.inspect(_SCOPE, callback_id)
        if entry is None:
            return None
        _digest, state = entry
        binding = state["binding"]
        if (set(binding) != {"config", "assignment_checkpoint_sha256", "invocation"}
                or binding["config"] != self.config.to_dict() or assignment is None
                or binding["assignment_checkpoint_sha256"] != assignment["assignment_checkpoint_sha256"]):
            raise WorkerTransportError("worker_transport_binding_drift")
        invocation = validate_worker_request(worker_json(binding["invocation"]))
        if (invocation["action"] != "run" or invocation["context"] != assignment["context"]
                or invocation["request_sha256"] != assignment["binding"]["request_sha256"]
                or invocation["profile_sha256"] != assignment["binding"]["profile_sha256"]
                or any(invocation[name] != assignment["binding"][name] for name in _IDENTITY)):
            raise WorkerTransportError("worker_transport_binding_drift")
        if state["status"] == "completed":
            self._validate_result(state["result"])
        return entry

    @staticmethod
    def _validate_result(result):
        if (type(result) is not dict or set(result) != {"status"} or type(result["status"]) is not str
                or result["status"] not in {"receipt_authenticated", "unknown"}):
            raise WorkerTransportError("worker_transport_result_invalid")

    def inspect(self, episode_id: str) -> dict[str, Any]:
        assignment = self.assignments.inspect(episode_id)
        entry = self._entry(episode_id, assignment)
        transport = {"status": "not_started", "checkpoint_sha256": None}
        if entry is not None:
            digest, state = entry
            status = "recovery_required" if state["status"] == "started" else state["result"]["status"]
            if assignment["status"] in {"receipt_authenticated", "receipt_authenticated_after_unknown"}:
                status = assignment["status"]
            transport = {"status": status, "checkpoint_sha256": digest,
                         "config_sha256": DurableCallbackJournal.digest(state["binding"]["config"]),
                         "request_sha256": state["binding"]["invocation"]["request_sha256"]}
        return {"assignment": assignment, "transport": transport, "native_success": False,
                "remote_cleanup_verified": False, "publication_authority": False}

    def dispatch(self, request: SolverRequest, *, plan_sha256: str,
                 expected_controller_checkpoint_sha256: str,
                 control: SolveExecutionControl) -> dict[str, Any]:
        control.check("external_worker_dispatch")
        callback_id, guard_id = self._ids(request.episode_id)
        with self.assignments.ledger.controller_lock(guard_id):
            assignment = self._assignment(request, plan_sha256, expected_controller_checkpoint_sha256)
            if assignment["status"] != "assigned" or self._entry(request.episode_id, assignment) is not None:
                raise WorkerTransportError("worker_transport_once_only_gate")
            original_wall, original_deadline = worker_request_budget(request)
            local_started = time.monotonic()
            unix_started = time.time()
            remaining = min(control.check("external_worker_dispatch_intent"), 3600.0,
                            original_wall, original_deadline - unix_started)
            if remaining <= 0:
                raise WorkerTransportError("worker_transport_original_deadline_expired")
            channel_control = SolveExecutionControl(remaining, started_at=local_started,
                                                     cancelled=control.is_cancelled)
            invocation = {"schema_version": "lunar-external-worker-channel-v1", "action": "run",
                          "context": assignment["context"], "request": request.to_dict(),
                          "request_sha256": request.digest(), "profile_sha256": assignment["binding"]["profile_sha256"],
                          "timeout_seconds": remaining,
                          "deadline_unix": min(original_deadline, unix_started + remaining),
                          **{name: assignment["binding"][name] for name in _IDENTITY}}
            raw_request = worker_json(invocation)
            validate_worker_request(raw_request)

            def execute():
                try:
                    output = run_worker_channel(self._argv(), raw_request, control=channel_control,
                                                stdout_limit=MAX_WORKER_RESPONSE_BYTES)
                    if output.exit_code != 0:
                        raise WorkerTransportError("worker_transport_channel_failed")
                    status, origin, receipt = parse_worker_response(output.stdout)
                    if status != "receipt":
                        raise WorkerTransportError("worker_transport_receipt_unavailable")
                    self.assignments.record_origin_receipt(
                        request, plan_sha256=plan_sha256,
                        expected_controller_checkpoint_sha256=expected_controller_checkpoint_sha256,
                        raw=origin, receipt=receipt)
                    return {"status": "receipt_authenticated"}
                except Exception:  # noqa: BLE001
                    # Every channel failure retains unknown without revealing private output.
                    self.assignments.mark_unknown(
                        request, plan_sha256=plan_sha256,
                        expected_controller_checkpoint_sha256=expected_controller_checkpoint_sha256,
                        reason_code="worker_transport_channel_unknown")
                    return {"status": "unknown"}

            def before():
                channel_control.check("external_worker_dispatch_admission")
                current = self._assignment(request, plan_sha256, expected_controller_checkpoint_sha256)
                if current != assignment:
                    raise WorkerTransportError("worker_transport_assignment_drift")

            self.journal.invoke(_SCOPE, callback_id,
                                binding={"config": self.config.to_dict(), "invocation": invocation,
                                         "assignment_checkpoint_sha256": assignment["assignment_checkpoint_sha256"]},
                                call=execute, validate=self._validate_result, before_call=before)
            return self.inspect(request.episode_id)

    def reconcile(self, request: SolverRequest, *, plan_sha256: str,
                  expected_controller_checkpoint_sha256: str,
                  control: SolveExecutionControl) -> dict[str, Any]:
        _callback_id, guard_id = self._ids(request.episode_id)
        with self.assignments.ledger.controller_lock(guard_id):
            assignment = self._assignment(request, plan_sha256, expected_controller_checkpoint_sha256)
            entry = self._entry(request.episode_id, assignment)
            if entry is None:
                raise WorkerTransportError("worker_transport_original_intent_required")
            if assignment["status"] in {"receipt_authenticated", "receipt_authenticated_after_unknown"}:
                return self.inspect(request.episode_id)
            if assignment["status"] == "assigned":
                self.assignments.mark_unknown(request, plan_sha256=plan_sha256,
                    expected_controller_checkpoint_sha256=expected_controller_checkpoint_sha256,
                    reason_code="worker_transport_interrupted")
                assignment = self.assignments.inspect(request.episode_id)
            if assignment["status"] != "unknown":
                raise WorkerTransportError("worker_transport_reconciliation_gate")
            invocation = {**entry[1]["binding"]["invocation"], "action": "inspect"}
            # Recovery control bounds only this read; original remote deadline remains unchanged.
            control.check("external_worker_reconcile_inspect")
            try:
                output = run_worker_channel(self._argv(), worker_json(invocation), control=control,
                                            stdout_limit=MAX_WORKER_RESPONSE_BYTES)
                if output.exit_code != 0:
                    return self.inspect(request.episode_id)
                status, origin, receipt = parse_worker_response(output.stdout)
                if status == "receipt":
                    self.assignments.reconcile_origin_receipt(request, plan_sha256=plan_sha256,
                        expected_controller_checkpoint_sha256=expected_controller_checkpoint_sha256,
                        raw=origin, receipt=receipt)
            except Exception:  # noqa: BLE001, S110
                # Retain unknown silently: private channel failures cannot reopen work.
                pass
            return self.inspect(request.episode_id)
