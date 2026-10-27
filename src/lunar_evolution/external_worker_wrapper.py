"""Preinstalled trusted worker wrapper: fixed command, durable intent and signed receipt.

Candidate execution must remain behind a separately provisioned native isolation
boundary. This signing account must not execute arbitrary untrusted candidate code.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import math
import os
import signal
import stat
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ._candidate_workspace_io import DirectoryChain
from .automatic_solve_lifecycle import SolveExecutionControl
from .external_worker_io import run_worker_channel
from .external_worker_origin import WorkerOriginContext, WorkerOriginKey, sign_worker_origin
from .rsi_gateway import SolverRequest

MAX_WORKER_REQUEST_BYTES = 256 * 1024
MAX_WORKER_RECEIPT_BYTES = 128 * 1024
MAX_WORKER_RESPONSE_BYTES = 256 * 1024
_SCHEMA = "lunar-external-worker-channel-v1"
_IDENTITY = ("worker_id", "host_id", "host_boot_id", "key_id")
_REQUEST_FIELDS = {
    "schema_version", "action", "context", "request", "request_sha256", "profile_sha256",
    "timeout_seconds", "deadline_unix", *_IDENTITY,
}


class WorkerWrapperError(ValueError):
    """Fixed wrapper errors without raw child output, key or private configuration."""


def worker_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise WorkerWrapperError("worker_wrapper_duplicate_key")
        result[key] = value
    return result


def parse_worker_json(raw: bytes, maximum: int) -> dict[str, Any]:
    if type(raw) is not bytes or not raw or len(raw) > maximum:
        raise WorkerWrapperError("worker_wrapper_wire_invalid")
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
        if type(value) is not dict or worker_json(value) != raw:
            raise WorkerWrapperError("worker_wrapper_wire_invalid")
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise WorkerWrapperError("worker_wrapper_wire_invalid") from None


def _digest(value: object) -> str:
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise WorkerWrapperError("worker_wrapper_digest_invalid")
    return value


def _read_private(path: Path, maximum: int) -> bytes:
    if not path.is_absolute() or ".." in path.parts:
        raise WorkerWrapperError("worker_wrapper_private_file_invalid")
    chain = None
    try:
        chain = DirectoryChain(path.parent, "worker_wrapper_private_file_invalid")
        raw = _read_at(chain.fd, path.name, maximum)
        chain.check()
        return raw
    except Exception:  # noqa: BLE001
        # Normalize private filesystem/metadata failures without revealing their paths.
        raise WorkerWrapperError("worker_wrapper_private_file_invalid") from None
    finally:
        if chain is not None:
            chain.close()


@dataclass(frozen=True, slots=True)
class WorkerWrapperConfig:
    key: WorkerOriginKey = field(repr=False)
    profile_sha256: str
    state_directory: Path
    producer_argv: tuple[str, ...]
    allowed_controllers: tuple[str, ...]
    maximum_runtime_seconds: int

    def __post_init__(self) -> None:
        if type(self.key) is not WorkerOriginKey or self.key.revoked:
            raise WorkerWrapperError("worker_wrapper_key_invalid")
        self.key.__post_init__()
        _digest(self.profile_sha256)
        if type(self.state_directory) is not Path and not isinstance(self.state_directory, Path):
            raise WorkerWrapperError("worker_wrapper_state_invalid")
        if not self.state_directory.is_absolute():
            raise WorkerWrapperError("worker_wrapper_state_invalid")
        if (type(self.producer_argv) is not tuple or not self.producer_argv
                or len(self.producer_argv) > 64
                or any(type(x) is not str or not x or "\0" in x or len(x.encode()) > 8192
                       for x in self.producer_argv)
                or not Path(self.producer_argv[0]).is_absolute()):
            raise WorkerWrapperError("worker_wrapper_command_invalid")
        if (type(self.allowed_controllers) is not tuple or not self.allowed_controllers
                or len(self.allowed_controllers) > 64):
            raise WorkerWrapperError("worker_wrapper_controllers_invalid")
        for controller in self.allowed_controllers:
            WorkerOriginContext(controller, "validation", "validation", "validation",
                                "native-claim", "0" * 64, "0" * 64, 1)
        if type(self.maximum_runtime_seconds) is not int or not 1 <= self.maximum_runtime_seconds <= 3600:
            raise WorkerWrapperError("worker_wrapper_budget_invalid")


def load_worker_wrapper_config(path: Path) -> WorkerWrapperConfig:
    """Read preinstalled private files; no key is accepted from the channel."""
    value = parse_worker_json(_read_private(path, 32768), 32768)
    fields = {"schema_version", *_IDENTITY, "profile_sha256", "key_file", "state_directory",
              "producer_argv", "allowed_controllers", "maximum_runtime_seconds"}
    if set(value) != fields or value["schema_version"] != "lunar-external-worker-wrapper-v1":
        raise WorkerWrapperError("worker_wrapper_config_invalid")
    for name in ("key_file", "state_directory"):
        if type(value[name]) is not str or not Path(value[name]).is_absolute():
            raise WorkerWrapperError("worker_wrapper_config_invalid")
    if type(value["producer_argv"]) is not list or type(value["allowed_controllers"]) is not list:
        raise WorkerWrapperError("worker_wrapper_config_invalid")
    key = WorkerOriginKey(**{name: value[name] for name in _IDENTITY},
                          secret_key=_read_private(Path(value["key_file"]), 4096))
    return WorkerWrapperConfig(
        key, value["profile_sha256"], Path(value["state_directory"]),
        tuple(value["producer_argv"]), tuple(value["allowed_controllers"]),
        value["maximum_runtime_seconds"],
    )


def worker_request_budget(request: SolverRequest) -> tuple[float, float]:
    """Require original absolute work expiry; a channel control cannot create it.

    Episode/token-only RSI budgets and relative wall limits without an original
    persisted deadline are insufficient authority to launch an external worker.
    Expiry is checked at admission, while expired intents remain inspectable.
    """
    values = dict(request.budget)
    wall = values.get("wall_timeout_seconds")
    deadline = values.get("deadline_unix")
    if any(type(item) not in {int, float} or not math.isfinite(item) or item <= 0
           for item in (wall, deadline)):
        raise WorkerWrapperError("worker_wrapper_original_budget_required")
    return float(wall), float(deadline)


def validate_worker_request(raw: bytes) -> dict[str, Any]:
    value = parse_worker_json(raw, MAX_WORKER_REQUEST_BYTES)
    if set(value) != _REQUEST_FIELDS or value["schema_version"] != _SCHEMA:
        raise WorkerWrapperError("worker_wrapper_request_fields_invalid")
    if type(value["action"]) is not str or value["action"] not in {"run", "inspect"}:
        raise WorkerWrapperError("worker_wrapper_action_invalid")
    context = WorkerOriginContext.from_dict(value["context"])
    request = SolverRequest.from_dict(value["request"])
    if request.episode_id != context.episode_id or request.digest() != value["request_sha256"]:
        raise WorkerWrapperError("worker_wrapper_request_binding_invalid")
    WorkerOriginKey(**{name: value[name] for name in _IDENTITY}, secret_key=b"\0" * 32)
    _digest(value["profile_sha256"])
    for name in ("timeout_seconds", "deadline_unix"):
        if type(value[name]) not in {int, float} or not math.isfinite(value[name]) or value[name] <= 0:
            raise WorkerWrapperError("worker_wrapper_budget_invalid")
    original_wall, original_deadline = worker_request_budget(request)
    if (value["timeout_seconds"] > min(3600, original_wall)
            or value["deadline_unix"] > original_deadline):
        raise WorkerWrapperError("worker_wrapper_budget_invalid")
    return value


def worker_response(status: str, *, origin: bytes | None = None, receipt: bytes | None = None) -> bytes:
    value = {"schema_version": _SCHEMA, "status": status}
    if status == "receipt":
        if type(origin) is not bytes or type(receipt) is not bytes or not 1 <= len(receipt) <= MAX_WORKER_RECEIPT_BYTES:
            raise WorkerWrapperError("worker_wrapper_receipt_invalid")
        value.update(origin=base64.b64encode(origin).decode(), receipt=base64.b64encode(receipt).decode())
    elif status not in {"unknown", "missing"}:
        raise WorkerWrapperError("worker_wrapper_status_invalid")
    return worker_json(value)


def parse_worker_response(raw: bytes) -> tuple[str, bytes | None, bytes | None]:
    value = parse_worker_json(raw, MAX_WORKER_RESPONSE_BYTES)
    if (value.get("schema_version") != _SCHEMA or type(value.get("status")) is not str
            or value["status"] not in {"receipt", "unknown", "missing"}):
        raise WorkerWrapperError("worker_wrapper_response_invalid")
    if value["status"] != "receipt":
        if set(value) != {"schema_version", "status"}:
            raise WorkerWrapperError("worker_wrapper_response_invalid")
        return value["status"], None, None
    if set(value) != {"schema_version", "status", "origin", "receipt"}:
        raise WorkerWrapperError("worker_wrapper_response_invalid")
    try:
        origin = base64.b64decode(value["origin"], validate=True)
        receipt = base64.b64decode(value["receipt"], validate=True)
    except (ValueError, TypeError):
        raise WorkerWrapperError("worker_wrapper_response_invalid") from None
    if worker_response("receipt", origin=origin, receipt=receipt) != raw or len(origin) > 8192:
        raise WorkerWrapperError("worker_wrapper_response_invalid")
    return "receipt", origin, receipt


@contextmanager
def _private_directory(path: Path):
    chain = None
    try:
        if not path.is_absolute() or ".." in path.parts:
            raise WorkerWrapperError("worker_wrapper_private_directory_invalid")
        chain = DirectoryChain(path, "worker_wrapper_private_directory_invalid")
        info = os.fstat(chain.fd)
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
            raise WorkerWrapperError("worker_wrapper_private_directory_invalid")
        yield chain
        chain.check()
    except OSError:
        raise WorkerWrapperError("worker_wrapper_private_directory_invalid") from None
    finally:
        if chain is not None:
            chain.close()


def _read_at(directory: int, name: str, maximum: int) -> bytes:
    before = os.stat(name, dir_fd=directory, follow_symlinks=False)
    if not stat.S_ISREG(before.st_mode):
        raise WorkerWrapperError("worker_wrapper_state_file_invalid")
    # Nonblocking admission also covers a regular-to-FIFO replacement after stat.
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
                 dir_fd=directory)
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) not in {0o400, 0o600} or info.st_size > maximum
                or (before.st_dev, before.st_ino) != (info.st_dev, info.st_ino)):
            raise WorkerWrapperError("worker_wrapper_state_file_invalid")
        chunks = bytearray()
        while len(chunks) <= maximum:
            chunk = os.read(fd, min(65536, maximum + 1 - len(chunks)))
            if not chunk:
                break
            chunks.extend(chunk)
        after = os.fstat(fd)
        named = os.stat(name, dir_fd=directory, follow_symlinks=False)
        stable = lambda item: (item.st_dev, item.st_ino, item.st_mode, item.st_uid,
                               item.st_nlink, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
        if stable(before) != stable(info) or stable(info) != stable(after) or stable(after) != stable(named) or len(chunks) != info.st_size:
            raise WorkerWrapperError("worker_wrapper_state_file_invalid")
        return bytes(chunks)
    finally:
        os.close(fd)


def _publish(directory: int, name: str, raw: bytes) -> None:
    temp = name + ".pending"
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
    try:
        offset = 0
        while offset < len(raw):
            written = os.write(fd, raw[offset:])
            if written <= 0:
                raise WorkerWrapperError("worker_wrapper_state_write_failed")
            offset += written
        os.fsync(fd)
    finally:
        os.close(fd)
    os.link(temp, name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
    os.unlink(temp, dir_fd=directory)
    os.fsync(directory)


def handle_worker_request(raw: bytes, config: WorkerWrapperConfig) -> bytes:
    """Run once or read an existing result; no channel supplies commands or keys."""
    value = validate_worker_request(raw)
    if any(value[name] != getattr(config.key, name) for name in _IDENTITY) or value["profile_sha256"] != config.profile_sha256:
        raise WorkerWrapperError("worker_wrapper_identity_mismatch")
    if value["context"]["controller_id"] not in config.allowed_controllers:
        raise WorkerWrapperError("worker_wrapper_controller_refused")
    intent = worker_json({name: item for name, item in value.items() if name != "action"})
    name = hashlib.sha256(value["context"]["episode_id"].encode()).hexdigest()
    with _private_directory(config.state_directory) as chain:
        try:
            return _handle_in_state(raw, value, intent, name, config, chain)
        except OSError:
            raise WorkerWrapperError("worker_wrapper_state_io_failed") from None


def _handle_in_state(raw, value, intent, name, config, chain):
    state = chain.fd
    job = None
    try:
        created = False
        if value["action"] == "run":
            try:
                os.mkdir(name, 0o700, dir_fd=state)
                os.fsync(state)
                created = True
            except FileExistsError:
                pass
        try:
            job = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=state)
        except FileNotFoundError:
            return worker_response("missing")
        original = os.fstat(job)
        if original.st_uid != os.geteuid() or stat.S_IMODE(original.st_mode) != 0o700:
            raise WorkerWrapperError("worker_wrapper_private_directory_invalid")

        def check() -> None:
            chain.check()
            parent = os.fstat(state)
            named = os.stat(name, dir_fd=state, follow_symlinks=False)
            opened = os.fstat(job)
            if (parent.st_uid != os.geteuid() or stat.S_IMODE(parent.st_mode) != 0o700
                    or not stat.S_ISDIR(named.st_mode) or named.st_uid != os.geteuid()
                    or stat.S_IMODE(named.st_mode) != 0o700
                    or (named.st_dev, named.st_ino) != (original.st_dev, original.st_ino)
                    or (opened.st_dev, opened.st_ino) != (original.st_dev, original.st_ino)):
                raise WorkerWrapperError("worker_wrapper_state_directory_changed")

        check()
        if not created:
            try:
                if _read_at(job, "intent.json", MAX_WORKER_REQUEST_BYTES) != intent:
                    raise WorkerWrapperError("worker_wrapper_intent_drift")
            except FileNotFoundError:
                return worker_response("unknown")
            try:
                response = _read_at(job, "response.json", MAX_WORKER_RESPONSE_BYTES)
            except FileNotFoundError:
                return worker_response("unknown")
            parse_worker_response(response)
            check()
            return response
        _publish(job, "intent.json", intent)
        check()
        remaining = min(value["timeout_seconds"], value["deadline_unix"] - time.time(),
                        config.maximum_runtime_seconds)
        if remaining <= 0:
            return worker_response("unknown")
        # The configured command is a trusted native producer launcher, never a wire argv.
        result = run_worker_channel(
            config.producer_argv, raw, control=SolveExecutionControl(remaining),
            stdout_limit=MAX_WORKER_RECEIPT_BYTES, environment={"PATH": os.defpath, "LANG": "C.UTF-8"},
        )
        if result.exit_code != 0 or not result.stdout:
            return worker_response("unknown")
        origin = sign_worker_origin(key=config.key, context=WorkerOriginContext.from_dict(value["context"]),
                                    profile_sha256=config.profile_sha256, receipt=result.stdout)
        response = worker_response("receipt", origin=origin, receipt=result.stdout)
        check()
        _publish(job, "response.json", response)
        check()
        return response
    finally:
        if job is not None:
            os.close(job)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if hasattr(signal, "SIGHUP"):
            signal.signal(signal.SIGHUP, signal.SIG_IGN)
        config = load_worker_wrapper_config(args.config)
        raw = sys.stdin.buffer.read(MAX_WORKER_REQUEST_BYTES + 1)
        response = handle_worker_request(raw, config)
        sys.stdout.buffer.write(response)
        sys.stdout.buffer.flush()
        return 0
    except Exception:  # noqa: BLE001
        # Do not display exceptions from configured commands, files or secret parsing.
        try:
            sys.stdout.buffer.write(worker_response("unknown"))
            sys.stdout.buffer.flush()
        except OSError:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
