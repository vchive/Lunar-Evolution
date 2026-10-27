"""Explicit local CLI over the existing SSH assignment and recovery boundaries."""

from __future__ import annotations

import argparse
import hashlib
import math
import os
import sqlite3
import stat
from contextlib import contextmanager
from pathlib import Path

from ._candidate_workspace_io import DirectoryChain
from .automatic_solve_lifecycle import SolveExecutionControl
from .candidate_workspace_plan import CandidateWorkspaceError
from .external_worker_assignment import ExternalWorkerAssignments
from .external_worker_origin import WorkerOriginKey, WorkerOriginRegistry
from .external_worker_wrapper import parse_worker_json
from .rsi_gateway import SolverRequest
from .rsi_store import RSILedger

_REGISTRY_SCHEMA = "lunar-external-worker-registry-v1"
_MAX_REGISTRY = 256 * 1024


def _fail(code: str) -> None:
    raise ValueError("worker_cli_" + code)


def _path(value: object) -> Path:
    if type(value) not in {str, Path} and not isinstance(value, Path):
        _fail("path_invalid")
    text = str(value)
    if (not text.startswith("/") or len(text) > 4096 or "\x00" in text
            or "//" in text or any(part in {".", ".."} for part in text.split("/")[1:])):
        _fail("path_invalid")
    return Path(text)


def _metadata(info: os.stat_result) -> tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _read(path: Path, maximum: int, *, private: bool = False) -> bytes:
    """Read stable bounded bytes without following a parent or leaf symlink."""
    path = _path(path)
    chain = None
    descriptor = -1
    try:
        chain = DirectoryChain(path.parent, "worker_cli_file_invalid")
        before = os.stat(path.name, dir_fd=chain.fd, follow_symlinks=False)
        if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                or not 0 < before.st_size <= maximum
                or private and (before.st_uid != os.geteuid() or before.st_mode & 0o077)):
            _fail("file_invalid")
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                             dir_fd=chain.fd)
        if _metadata(os.fstat(descriptor)) != _metadata(before):
            _fail("file_changed")
        result = bytearray()
        while len(result) <= maximum:
            chunk = os.read(descriptor, min(65536, maximum + 1 - len(result)))
            if not chunk:
                break
            result.extend(chunk)
        if (len(result) != before.st_size or len(result) > maximum
                or _metadata(os.fstat(descriptor)) != _metadata(before)
                or _metadata(os.stat(path.name, dir_fd=chain.fd, follow_symlinks=False))
                != _metadata(before)):
            _fail("file_changed")
        chain.check()
        return bytes(result)
    except (OSError, CandidateWorkspaceError):
        _fail("file_invalid")
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if chain is not None:
            chain.close()


def load_worker_registry(path: Path) -> tuple[WorkerOriginRegistry, dict[str, WorkerOriginKey]]:
    """Load a local private registry; secrets never enter a serialized result."""
    value = parse_worker_json(_read(path, _MAX_REGISTRY, private=True), _MAX_REGISTRY)
    if (set(value) != {"schema_version", "workers"}
            or value["schema_version"] != _REGISTRY_SCHEMA
            or type(value["workers"]) is not list or not 1 <= len(value["workers"]) <= 64):
        _fail("registry_invalid")
    keys = []
    for item in value["workers"]:
        if type(item) is not dict or set(item) != {
            "worker_id", "host_id", "host_boot_id", "key_id", "key_file", "revoked",
        }:
            _fail("registry_invalid")
        keys.append(WorkerOriginKey(
            **{name: item[name] for name in ("worker_id", "host_id", "host_boot_id", "key_id")},
            secret_key=_read(_path(item["key_file"]), 4096, private=True), revoked=item["revoked"],
        ))
    registry = WorkerOriginRegistry(keys)
    return registry, {key.worker_id: key for key in keys}


def add_external_worker_parser(subparsers) -> None:
    parser = subparsers.add_parser("external-worker", help="explicit SSH worker assignment and recovery")
    commands = parser.add_subparsers(dest="external_worker_command", required=True)
    for name in ("reserve", "dispatch", "inspect", "reconcile"):
        child = commands.add_parser(name)
        child.add_argument("--ledger", type=Path, required=True, help="existing local RSI SQLite ledger")
        child.add_argument("--registry", type=Path, required=True, help="private installed worker registry")
        child.add_argument("--ssh-config", type=Path, required=True, help="fixed installed SSH worker configuration")
        child.add_argument("--controller-id", required=True)
        child.add_argument("--run-id", required=True)
        child.add_argument("--task-id", required=True)
        child.add_argument("--json", action="store_true")
        if name == "inspect":
            child.add_argument("--episode-id", required=True)
        else:
            child.add_argument("--request", type=Path, required=True)
            child.add_argument("--request-sha256", required=True, help="independent request byte digest")
            child.add_argument("--plan-sha256", required=True)
            child.add_argument("--checkpoint-sha256", required=True)
            if name == "reserve":
                child.add_argument("--claim-sha256", required=True)
                child.add_argument("--profile-sha256", required=True)
            else:
                child.add_argument("--channel-timeout", type=float, default=30.0)


def _sha(value: object) -> str:
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        _fail("digest_invalid")
    return value


def _summary(snapshot: dict, *, episode_id: str) -> dict:
    assignment = snapshot.get("assignment")
    status = snapshot.get("status", snapshot.get("transport", {}).get("status", "unassigned"))
    if status == "not_started":
        status = assignment["status"] if assignment is not None else "unassigned"
    result = {
        "status": status, "episode_id": episode_id,
        "evidence_scope": "authenticated_external_worker_transport",
        "production_admission": False, "online_publication": False,
        "native_result_published": False, "remote_cleanup_verified": False,
    }
    if assignment is not None:
        for name in ("assignment_checkpoint_sha256", "settlement_checkpoint_sha256",
                     "reconciliation_checkpoint_sha256"):
            if assignment.get(name) is not None:
                result[name] = assignment[name]
    return result


@contextmanager
def _existing_ledger(database: Path):
    database = _path(database)
    chain = None
    descriptor = -1
    try:
        chain = DirectoryChain(database.parent, "worker_cli_ledger_invalid")
        before = os.stat(database.name, dir_fd=chain.fd, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            _fail("ledger_invalid")
        descriptor = os.open(database.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                             dir_fd=chain.fd)
        identity = lambda info: (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_nlink)

        def check():
            chain.check()
            if (identity(os.fstat(descriptor)) != identity(before)
                    or identity(os.stat(database.name, dir_fd=chain.fd, follow_symlinks=False))
                    != identity(before)):
                _fail("ledger_changed")

        check()
        ledger = RSILedger(database, create=False)
        check()
        yield ledger
        check()
    except FileNotFoundError:
        _fail("ledger_missing")
    except (OSError, CandidateWorkspaceError, sqlite3.Error):
        _fail("ledger_invalid")
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        if chain is not None:
            chain.close()


def external_worker_payload(args: argparse.Namespace) -> tuple[dict, int]:
    """Execute an explicit command without model runtime/config initialization."""
    from .external_worker_transport import SSHWorkerTransport, load_ssh_worker_config

    action = args.external_worker_command
    if action not in {"reserve", "dispatch", "inspect", "reconcile"}:
        _fail("action_invalid")
    request = None
    if action != "inspect":
        for value in (args.request_sha256, args.plan_sha256, args.checkpoint_sha256):
            _sha(value)
        if action == "reserve":
            _sha(args.claim_sha256)
            _sha(args.profile_sha256)
        elif (type(args.channel_timeout) not in {int, float}
                or not math.isfinite(args.channel_timeout) or not 0 < args.channel_timeout <= 3600):
            _fail("channel_timeout_invalid")
        raw = _read(args.request, 1024 * 1024)
        if hashlib.sha256(raw).hexdigest() != args.request_sha256:
            _fail("request_digest_mismatch")
        request = SolverRequest.from_dict(parse_worker_json(raw, 1024 * 1024))
    registry, keys = load_worker_registry(args.registry)
    config = load_ssh_worker_config(args.ssh_config)
    if config.worker_id not in keys:
        _fail("worker_unregistered")
    # Do not create an empty database when a caller misspells the original path.
    with _existing_ledger(args.ledger) as ledger:
        return _operate(args, action, request, registry, keys, config, ledger, SSHWorkerTransport)


def _operate(args, action, request, registry, keys, config, ledger, transport_type):
    assignments = ExternalWorkerAssignments(
        ledger, controller_id=args.controller_id, run_id=args.run_id, task_id=args.task_id,
        registry=registry,
    )
    transport = transport_type(assignments, config)
    if action == "inspect":
        snapshot = transport.inspect(args.episode_id)
        episode_id = args.episode_id
    else:
        episode_id = request.episode_id
        with ledger.controller_lock(args.run_id):
            if action == "reserve":
                claim = ledger.inspect_native_episode_claim(request, plan_sha256=args.plan_sha256)
                if claim is None or claim.claim_sha256 != args.claim_sha256:
                    _fail("original_claim_required")
                assignment = assignments.reserve_assignment(
                    request, plan_sha256=args.plan_sha256, profile_sha256=args.profile_sha256,
                    worker=keys[config.worker_id], expected_native_claim=claim,
                    expected_controller_checkpoint_sha256=args.checkpoint_sha256,
                )
                snapshot = {"status": assignment["status"], "assignment": assignment}
            else:
                operation = transport.dispatch if action == "dispatch" else transport.reconcile
                snapshot = operation(
                    request, plan_sha256=args.plan_sha256,
                    expected_controller_checkpoint_sha256=args.checkpoint_sha256,
                    control=SolveExecutionControl(args.channel_timeout),
                )
    payload = _summary(snapshot, episode_id=episode_id)
    return payload, 0 if payload["status"] in {
        "assigned", "receipt_authenticated", "receipt_authenticated_after_unknown",
    } else 1
