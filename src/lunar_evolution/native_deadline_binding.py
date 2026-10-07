"""Read-only pins for the original native attempt deadline file.

The binding is carried by an independently pinned consumption claim. A deadline's
self digest alone does not establish which deadline the controller admitted.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
from collections.abc import Mapping
from pathlib import Path

from .producer_process import ProducerProcessError, _held_directory

NATIVE_CONSUMPTION_PROTOCOL = "lunar-native-trusted-attestation-consumption-v2"
DEADLINE_NAME = "native-trusted-attempt-deadline.json"
DEADLINE_BINDING_PROTOCOL = "lunar-native-deadline-file-binding-v1"
MAX_NATIVE_DEADLINE_BYTES = 16 * 1024
MAX_NATIVE_DEADLINE_BINDING_BYTES = 4 * 1024

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FIELDS = frozenset({
    "schema_version", "protocol", "name", "deadline_sha256", "raw_sha256", "size",
    "device", "inode", "mode", "mtime_ns", "ctime_ns",
})
_STAT_FIELDS = ("device", "inode", "mode", "size", "mtime_ns", "ctime_ns")


class NativeDeadlineBindingError(ValueError):
    """Fixed-code error that excludes file paths and deadline-controlled prose."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _fail(code: str) -> None:
    raise NativeDeadlineBindingError(code)


def _canonical(value: object, maximum: int) -> bytes:
    try:
        encoder = json.JSONEncoder(
            ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
        )
        chunks: list[bytes] = []
        size = 0
        for chunk in encoder.iterencode(value):
            encoded = chunk.encode("utf-8")
            size += len(encoded)
            if size > maximum:
                _fail("native_deadline_binding_too_large")
            chunks.append(encoded)
        return b"".join(chunks)
    except (TypeError, ValueError, UnicodeError, OverflowError, RecursionError) as exc:
        if isinstance(exc, NativeDeadlineBindingError):
            raise
        raise NativeDeadlineBindingError("native_deadline_binding_invalid") from exc


def validate_native_deadline_binding(value: object) -> dict[str, object]:
    """Validate an exact bounded binding schema without accessing the filesystem."""
    if not isinstance(value, Mapping) or set(value) != _FIELDS:
        _fail("native_deadline_binding_invalid")
    binding = dict(value)
    if (binding["schema_version"] != "1"
            or binding["protocol"] != DEADLINE_BINDING_PROTOCOL
            or binding["name"] != DEADLINE_NAME):
        _fail("native_deadline_binding_invalid")
    for key in ("deadline_sha256", "raw_sha256"):
        digest = binding[key]
        if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
            _fail("native_deadline_binding_invalid")
    for key in _STAT_FIELDS:
        item = binding[key]
        if type(item) is not int or item < 0 or item > 2**64 - 1:
            _fail("native_deadline_binding_invalid")
    if (binding["mode"] != 0o600 or binding["inode"] == 0
            or not 0 < binding["size"] <= MAX_NATIVE_DEADLINE_BYTES):
        _fail("native_deadline_binding_invalid")
    _canonical(binding, MAX_NATIVE_DEADLINE_BINDING_BYTES)
    return binding


def deadline_binding_digest(binding: object) -> str:
    """Return the digest of the complete validated canonical binding."""
    validated = validate_native_deadline_binding(binding)
    return hashlib.sha256(_canonical(validated, MAX_NATIVE_DEADLINE_BINDING_BYTES)).hexdigest()


def _record_bytes(record: object) -> bytes:
    if not isinstance(record, Mapping):
        _fail("native_deadline_binding_invalid")
    digest = record.get("deadline_sha256")
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        _fail("native_deadline_binding_invalid")
    payload = dict(record)
    raw = _canonical(payload, MAX_NATIVE_DEADLINE_BYTES)
    payload.pop("deadline_sha256")
    if hashlib.sha256(_canonical(payload, MAX_NATIVE_DEADLINE_BYTES)).hexdigest() != digest:
        _fail("native_deadline_binding_mismatch")
    return raw


def verify_native_deadline_record_binding(record: object, binding: object) -> None:
    """Check canonical bytes, size and self digest against an independent original pin."""
    validated = validate_native_deadline_binding(binding)
    raw = _record_bytes(record)
    if (len(raw) != validated["size"]
            or hashlib.sha256(raw).hexdigest() != validated["raw_sha256"]
            or record["deadline_sha256"] != validated["deadline_sha256"]):
        _fail("native_deadline_binding_mismatch")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            _fail("native_deadline_binding_invalid")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    _fail("native_deadline_binding_invalid")


def _parse_record(raw: bytes) -> dict[str, object]:
    try:
        record = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                            parse_constant=_reject_constant)
    except (ValueError, UnicodeError, RecursionError) as exc:
        if isinstance(exc, NativeDeadlineBindingError):
            raise
        raise NativeDeadlineBindingError("native_deadline_binding_invalid") from exc
    if _record_bytes(record) != raw:
        _fail("native_deadline_binding_invalid")
    return record


def _stat_pin(info: os.stat_result) -> dict[str, int]:
    if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o600):
        _fail("native_deadline_binding_invalid")
    if not 0 < info.st_size <= MAX_NATIVE_DEADLINE_BYTES:
        _fail("native_deadline_binding_too_large")
    return {
        "device": info.st_dev, "inode": info.st_ino, "mode": stat.S_IMODE(info.st_mode),
        "size": info.st_size, "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns,
    }


def _directory(batch: str | Path) -> Path:
    try:
        directory = Path(batch).absolute()
        encoded = str(directory).encode("utf-8")
    except (TypeError, ValueError, OSError, UnicodeError) as exc:
        raise NativeDeadlineBindingError("native_deadline_binding_invalid") from exc
    if b"\x00" in encoded or ".." in directory.parts:
        _fail("native_deadline_binding_invalid")
    return directory


def _observe(
    batch: str | Path, *, binding: Mapping[str, object] | None,
    expected_record: Mapping[str, object] | None,
) -> tuple[dict[str, object], dict[str, object]]:
    # Freeze caller-provided material before opening the named file. Never recapture a
    # changed deadline as the expected original record.
    expected_raw = _record_bytes(expected_record) if expected_record is not None else None
    directory = _directory(batch)
    descriptor = -1
    try:
        with _held_directory(directory) as parent:
            before = _stat_pin(os.stat(DEADLINE_NAME, dir_fd=parent, follow_symlinks=False))
            if binding is not None and any(before[key] != binding[key] for key in _STAT_FIELDS):
                _fail("native_deadline_binding_mismatch")
            descriptor = os.open(
                DEADLINE_NAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                dir_fd=parent,
            )
            observed, record = _observe_opened(
                parent, descriptor, before=before, binding=binding, expected_raw=expected_raw,
            )
        return observed, record
    except (OSError, ProducerProcessError) as exc:
        raise NativeDeadlineBindingError("native_deadline_binding_unavailable") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _observe_opened(
    parent: int, descriptor: int, *, before: Mapping[str, int],
    binding: Mapping[str, object] | None, expected_raw: bytes | None,
) -> tuple[dict[str, object], dict[str, object]]:
    opened = _stat_pin(os.fstat(descriptor))
    named_before = _stat_pin(os.stat(DEADLINE_NAME, dir_fd=parent, follow_symlinks=False))
    if before != opened or named_before != opened:
        _fail("native_deadline_binding_mismatch")
    raw = bytearray()
    while True:
        chunk = os.read(descriptor, MAX_NATIVE_DEADLINE_BYTES + 1 - len(raw))
        if not chunk:
            break
        raw.extend(chunk)
        if len(raw) > MAX_NATIVE_DEADLINE_BYTES:
            _fail("native_deadline_binding_too_large")
    record = _parse_record(bytes(raw))
    if expected_raw is not None and raw != expected_raw:
        _fail("native_deadline_binding_mismatch")
    observed: dict[str, object] = {
        "schema_version": "1", "protocol": DEADLINE_BINDING_PROTOCOL,
        "name": DEADLINE_NAME, "deadline_sha256": record["deadline_sha256"],
        "raw_sha256": hashlib.sha256(raw).hexdigest(), **opened,
    }
    validate_native_deadline_binding(observed)
    if binding is not None:
        verify_native_deadline_record_binding(record, binding)
        if observed != binding:
            _fail("native_deadline_binding_mismatch")
    # Recheck the same descriptor and the current name after parsing and all
    # digest checks; the held-directory context also rechecks every ancestor.
    after = _stat_pin(os.fstat(descriptor))
    named = _stat_pin(os.stat(DEADLINE_NAME, dir_fd=parent, follow_symlinks=False))
    if opened != after or after != named or len(raw) != after["size"]:
        _fail("native_deadline_binding_mismatch")
    return observed, record


def persist_native_deadline_binding(
    batch: str | Path, *, record: Mapping[str, object],
) -> dict[str, object]:
    """Publish once and pin the original writer descriptor throughout durability checks.

    A published final name is retained after any later uncertainty. No replacement
    deadline or claim can be synthesized by retrying this create-only operation.
    """
    raw = _record_bytes(record)
    directory = _directory(batch)
    descriptor = -1
    temporary = f".native-deadline-{secrets.token_hex(16)}.tmp"
    created = False
    try:
        with _held_directory(directory, create=True) as parent:
            try:
                descriptor = os.open(
                    temporary, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                    0o600, dir_fd=parent,
                )
                created = True
                initial = os.fstat(descriptor)
                if (not stat.S_ISREG(initial.st_mode) or initial.st_nlink != 1
                        or stat.S_IMODE(initial.st_mode) != 0o600):
                    _fail("native_deadline_binding_invalid")
                view = memoryview(raw)
                while view:
                    written = os.write(descriptor, view)
                    if written <= 0:
                        _fail("native_deadline_binding_unavailable")
                    view = view[written:]
                os.fsync(descriptor)
                try:
                    os.link(temporary, DEADLINE_NAME, src_dir_fd=parent, dst_dir_fd=parent,
                            follow_symlinks=False)
                except FileExistsError as exc:
                    raise NativeDeadlineBindingError("native_deadline_binding_conflict") from exc
                os.unlink(temporary, dir_fd=parent)
                created = False
                os.fsync(parent)
                before = _stat_pin(os.fstat(descriptor))
                os.lseek(descriptor, 0, os.SEEK_SET)
                observed, _record = _observe_opened(
                    parent, descriptor, before=before, binding=None, expected_raw=raw,
                )
            finally:
                if created:
                    try:
                        os.unlink(temporary, dir_fd=parent)
                    except OSError:
                        pass
        return observed
    except (OSError, ProducerProcessError) as exc:
        raise NativeDeadlineBindingError("native_deadline_binding_unavailable") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def capture_native_deadline_binding(
    batch: str | Path, *, expected_record: Mapping[str, object],
) -> dict[str, object]:
    """Pin the named file only if its bytes equal the already frozen original record."""
    if expected_record is None:
        _fail("native_deadline_binding_invalid")
    observed, _record = _observe(batch, binding=None, expected_record=expected_record)
    return observed


def verify_native_deadline_binding(
    batch: str | Path, *, binding: object, expected_record: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Read a canonical deadline under its original bytes and file identity pins."""
    validated = validate_native_deadline_binding(binding)
    _observed, record = _observe(batch, binding=validated, expected_record=expected_record)
    return record


__all__ = [
    "DEADLINE_BINDING_PROTOCOL", "DEADLINE_NAME", "MAX_NATIVE_DEADLINE_BINDING_BYTES",
    "MAX_NATIVE_DEADLINE_BYTES", "NATIVE_CONSUMPTION_PROTOCOL", "NativeDeadlineBindingError",
    "capture_native_deadline_binding", "deadline_binding_digest",
    "persist_native_deadline_binding",
    "validate_native_deadline_binding", "verify_native_deadline_binding",
    "verify_native_deadline_record_binding",
]
