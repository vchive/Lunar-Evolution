"""Bounded completion-wire comparison and an independently drained private pipe.

This is the default-off lifecycle profile's transport/comparison layer. Neither
public bytes nor this reader establish native launch, build or runtime custody.
The native attempt must separately bind the original channel before acquisition
can remove a missing-evidence boundary.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import selectors
import stat
import threading
import time
from dataclasses import dataclass

try:
    import fcntl
except ImportError:  # Native pipe acquisition is unsupported on this host.
    fcntl = None

COMPLETION_PROFILE = "fixed-producer-lifecycle-v1"
COMPLETION_PROTOCOL = "lunar-fixed-producer-completion-v1"
MAX_COMPLETION_BYTES = 16 * 1024
MAX_MATERIAL_BYTES = 16 * 1024 * 1024
_ARTIFACTS = {
    "openevolve": ("candidate.py", "result.json"),
    "shinka": ("gen_0/main.py", "programs.sqlite"),
}
_COMMON = frozenset({
    "protocol", "profile", "solver", "manifest_sha256", "target_pid",
    "deadline_monotonic_ns", "seq", "phase",
})


class FixedProducerCompletionError(ValueError):
    """Finite refusal codes, without child-controlled content."""

    def __init__(self, code: str = "fixed_producer_completion_refused") -> None:
        self.code = code
        super().__init__(code)


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False).encode("ascii")


def _digest(value: object) -> bool:
    return type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def _material(raw: bytes) -> dict:
    if type(raw) is not bytes or len(raw) > MAX_MATERIAL_BYTES:
        raise ValueError
    return {"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def _same_material(observed: object, raw: bytes) -> bool:
    return (type(observed) is dict and set(observed) == {"size", "sha256"}
            and type(observed["size"]) is int and _digest(observed["sha256"])
            and observed == _material(raw))


@dataclass(frozen=True, slots=True)
class FixedProducerCompletionBinding:
    """Expected comparison identities; constructing this DTO grants no authority."""

    solver: str
    target_pid: int
    manifest_sha256: str
    deadline_monotonic_ns: int

    def validate(self) -> None:
        if (type(self) is not FixedProducerCompletionBinding
                or type(self.solver) is not str or self.solver not in _ARTIFACTS
                or type(self.target_pid) is not int or not 0 < self.target_pid <= 2**31 - 1
                or not _digest(self.manifest_sha256)
                or type(self.deadline_monotonic_ns) is not int
                or not 0 < self.deadline_monotonic_ns < 2**64):
            raise FixedProducerCompletionError()


@dataclass(frozen=True, slots=True)
class FixedProducerCompletionComparison:
    """Only a pure comparison, including when the wire came from a real pipe."""

    binding: FixedProducerCompletionBinding
    canonical_bytes: bytes
    completion_sha256: str
    artifact_sha256s: tuple[tuple[str, str], ...]
    original_acquisition_verified: bool = False
    production_admission: bool = False
    online_publication: bool = False


def compare_fixed_producer_completion(
    raw: bytes, *, binding: FixedProducerCompletionBinding,
    request_bytes: bytes, memory_bytes: bytes, request_body_bytes: bytes,
    reply_bytes: bytes, artifacts: tuple[tuple[str, bytes], ...],
) -> FixedProducerCompletionComparison:
    """Compare both ordered phases with actual caller-retained input/output bytes.

    No paths are opened and no source-supplied digest is accepted as material.
    Broker completion and the native terminal remain independent owner checks.
    """
    try:
        if type(binding) is not FixedProducerCompletionBinding:
            raise ValueError
        binding.validate()
        if (type(raw) is not bytes or not 0 < len(raw) <= MAX_COMPLETION_BYTES
                or raw.count(b"\n") != 2 or not raw.endswith(b"\n")):
            raise ValueError
        records = []
        for line in raw[:-1].split(b"\n"):
            value = json.loads(line.decode("ascii"), object_pairs_hook=_unique_object)
            if type(value) is not dict or _canonical(value) != line:
                raise ValueError
            records.append(value)
        begun, committed = records
        if set(begun) != _COMMON or set(committed) != _COMMON | {"request", "memory", "broker", "artifacts"}:
            raise ValueError
        for seq, (record, phase) in enumerate(((begun, "begun"), (committed, "committed"))):
            if (record["protocol"] != COMPLETION_PROTOCOL or record["profile"] != COMPLETION_PROFILE
                    or type(record["solver"]) is not str or record["solver"] != binding.solver
                    or not _digest(record["manifest_sha256"])
                    or record["manifest_sha256"] != binding.manifest_sha256
                    or type(record["target_pid"]) is not int or record["target_pid"] != binding.target_pid
                    or type(record["deadline_monotonic_ns"]) is not int
                    or record["deadline_monotonic_ns"] != binding.deadline_monotonic_ns
                    or type(record["seq"]) is not int or record["seq"] != seq or record["phase"] != phase):
                raise ValueError
        broker = committed["broker"]
        if (not _same_material(committed["request"], request_bytes)
                or not _same_material(committed["memory"], memory_bytes)
                or type(broker) is not dict
                or set(broker) != {"request_id", "request_count", "request_body", "status", "reply"}
                or broker["request_id"] != "req-1" or type(broker["request_count"]) is not int
                or broker["request_count"] != 1 or type(broker["status"]) is not int or broker["status"] != 200
                or not _same_material(broker["request_body"], request_body_bytes)
                or not _same_material(broker["reply"], reply_bytes)):
            raise ValueError
        if (type(artifacts) is not tuple or len(artifacts) != 2
                or any(type(item) is not tuple or len(item) != 2 or type(item[0]) is not str for item in artifacts)
                or tuple(item[0] for item in artifacts) != _ARTIFACTS[binding.solver]
                or type(committed["artifacts"]) is not list or len(committed["artifacts"]) != 2):
            raise ValueError
        for record, (path, content) in zip(committed["artifacts"], artifacts, strict=True):
            if (type(record) is not dict or set(record) != {"path", "size", "sha256"}
                    or type(record["path"]) is not str or record["path"] != path
                    or not _same_material({k: record[k] for k in ("size", "sha256")}, content)):
                raise ValueError
        return FixedProducerCompletionComparison(
            binding, raw, hashlib.sha256(raw).hexdigest(),
            tuple((record["path"], record["sha256"]) for record in committed["artifacts"]),
        )
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, OverflowError):
        raise FixedProducerCompletionError() from None


class NativeFixedProducerCompletionCapture:
    """Owned asynchronous reader, so solver/broker progress never waits on EOF.

    The reader owns its descriptor after start. It uses only a stop event and
    the original monotonic deadline; no foreign callback runs on this thread.
    An unknown thread join is retained as a failure, never a cleanup claim.
    """

    def __init__(self, read_fd: int, *, deadline: float) -> None:
        if (type(read_fd) is not int or read_fd <= 2 or type(deadline) not in {int, float}
                or not 0 < deadline < 2**63 or not math.isfinite(deadline)
                or deadline <= time.monotonic() or fcntl is None):
            raise FixedProducerCompletionError("fixed_producer_completion_context_invalid")
        try:
            info = os.fstat(read_fd)
            flags = fcntl.fcntl(read_fd, fcntl.F_GETFL)
            if (not stat.S_ISFIFO(info.st_mode) or flags & os.O_ACCMODE != os.O_RDONLY
                    or flags & getattr(os, "O_ASYNC", 0)):
                raise ValueError
        except (OSError, ValueError):
            raise FixedProducerCompletionError("fixed_producer_completion_context_invalid") from None
        self._fd = read_fd
        self._identity = (info.st_dev, info.st_ino)
        self._deadline = float(deadline)
        self._stop = threading.Event()
        self._done = threading.Event()
        self._thread: threading.Thread | None = None
        self._result: bytes | None = None
        self._error: str | None = None
        self._partial = b""
        self._completed_monotonic: float | None = None

    @property
    def partial_bytes(self) -> bytes:
        return self._partial

    def start(self) -> NativeFixedProducerCompletionCapture:
        if self._thread is not None:
            raise FixedProducerCompletionError("fixed_producer_completion_already_started")
        try:
            info = os.fstat(self._fd)
            if (not stat.S_ISFIFO(info.st_mode) or (info.st_dev, info.st_ino) != self._identity
                    or fcntl.fcntl(self._fd, fcntl.F_GETFL) & os.O_ACCMODE != os.O_RDONLY):
                raise ValueError
        except (OSError, ValueError):
            raise FixedProducerCompletionError("fixed_producer_completion_reader_changed") from None
        self._thread = threading.Thread(target=self._read, name="lunar-fixed-completion", daemon=True)
        try:
            self._thread.start()
        except RuntimeError:
            # Transfer occurs only after successful start. The caller retains
            # and closes the original reader when no thread took ownership.
            self._error = "fixed_producer_completion_start_unknown"
            self._done.set()
            raise FixedProducerCompletionError(self._error) from None
        return self

    def _read(self) -> None:
        raw = bytearray()
        try:
            os.set_blocking(self._fd, False)
            with selectors.DefaultSelector() as selector:
                selector.register(self._fd, selectors.EVENT_READ)
                while True:
                    if self._stop.is_set():
                        raise FixedProducerCompletionError("fixed_producer_completion_cancelled")
                    remaining = self._deadline - time.monotonic()
                    if remaining <= 0:
                        raise FixedProducerCompletionError("fixed_producer_completion_wall_timeout")
                    if not selector.select(min(0.01, remaining)):
                        continue
                    try:
                        chunk = os.read(self._fd, MAX_COMPLETION_BYTES + 1 - len(raw))
                    except BlockingIOError:
                        continue
                    if not chunk:
                        if not raw:
                            raise FixedProducerCompletionError("fixed_producer_completion_empty")
                        if self._stop.is_set() or time.monotonic() >= self._deadline:
                            raise FixedProducerCompletionError("fixed_producer_completion_incomplete")
                        self._result = bytes(raw)
                        self._completed_monotonic = time.monotonic()
                        break
                    raw.extend(chunk)
                    self._partial = bytes(raw)
                    if len(raw) > MAX_COMPLETION_BYTES:
                        raise FixedProducerCompletionError("fixed_producer_completion_limit_exceeded")
        except FixedProducerCompletionError as exc:
            self._error = exc.code
        except (OSError, ValueError):
            self._error = "fixed_producer_completion_read_unknown"
        finally:
            try:
                os.close(self._fd)
            except OSError:
                self._error = "fixed_producer_completion_close_unknown"
            self._done.set()

    def _join(self) -> None:
        if self._thread is None:
            raise FixedProducerCompletionError("fixed_producer_completion_not_started")
        if self._thread.ident is None and self._done.is_set():
            raise FixedProducerCompletionError(self._error or "fixed_producer_completion_start_unknown")
        self._thread.join(max(0.0, self._deadline - time.monotonic()))
        if self._thread.is_alive():
            self._stop.set()
            raise FixedProducerCompletionError("fixed_producer_completion_join_unknown")

    def cancel(self) -> None:
        self._stop.set()
        self._join()

    def finish(self) -> bytes:
        self._join()
        if self._error is not None:
            raise FixedProducerCompletionError(self._error)
        if self._result is None or time.monotonic() >= self._deadline:
            raise FixedProducerCompletionError("fixed_producer_completion_wall_timeout")
        return self._result


def _original_completion_reader_pin(capture: NativeFixedProducerCompletionCapture, raw: bytes) -> tuple:
    """Retain this reader's actual successful EOF material, never supplied bytes.

    Historical revalidation does not create a new allowance. Successful bounded
    acquisition must already have ended within the reader's original deadline.
    This transport pin alone supplies no native attempt or computation claim.
    """
    if (type(capture) is not NativeFixedProducerCompletionCapture
            or capture._thread is None or capture._thread.is_alive() or not capture._done.is_set()
            or capture._error is not None or capture._result is not raw
            or type(raw) is not bytes or not 0 < len(raw) <= MAX_COMPLETION_BYTES
            or type(capture._completed_monotonic) is not float
            or not capture._completed_monotonic < capture._deadline):
        raise FixedProducerCompletionError("fixed_producer_completion_original_reader_changed")
    return (capture, id(capture), raw, id(raw), capture._thread, id(capture._thread),
            capture._identity, capture._deadline, capture._completed_monotonic,
            hashlib.sha256(raw).hexdigest())
