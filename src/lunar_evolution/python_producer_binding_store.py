"""Create-only durable binding sidecar for a local Python producer batch.

The controller retains the returned file pin independently. The sidecar cannot authenticate
itself by merely carrying a pin that is read from the same batch.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

from .producer_process import ProducerProcessError, _held_directory, _recovery_lock, _safe_root
from .python_producer_binding import (
    MAX_PYTHON_PRODUCER_BINDING_BYTES,
    PythonProducerBinding,
    PythonProducerBindingError,
    parse_python_producer_binding,
)

PYTHON_BINDING_SIDECAR_PROTOCOL = "lunar-python-producer-binding-sidecar-v1"
PYTHON_BINDING_SIDECAR_NAME = "python-producer-binding.json"
# The sidecar stores the exact canonical binding bytes.  Keep its bound coupled
# to the binding parser so a valid maximum-sized binding cannot be rejected at
# the persistence boundary (and reads cannot use a narrower truncation limit).
MAX_PYTHON_BINDING_SIDECAR_BYTES = MAX_PYTHON_PRODUCER_BINDING_BYTES
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_NOT_STARTED_ARTIFACTS = frozenset({
    "attestation-consumption.json", "process-registration.json", "execution-receipt.json",
    "recovery-receipt.json", "native-deadline-binding.json", "terminal.json",
})


class PythonProducerBindingStoreError(ValueError):
    """Fixed-code refusal for missing, replaced, or drifted binding evidence."""

    def __init__(self, code: str) -> None:
        self.code = "python_producer_binding_store_" + code
        super().__init__(self.code)


def _fail(code: str) -> NoReturn:
    raise PythonProducerBindingStoreError(code)


def _validated_binding(binding: PythonProducerBinding) -> tuple[PythonProducerBinding, bytes]:
    if type(binding) is not PythonProducerBinding:
        _fail("binding_invalid")
    try:
        raw = binding.to_json()
        if type(raw) is not bytes:
            _fail("binding_invalid")
        if len(raw) > MAX_PYTHON_BINDING_SIDECAR_BYTES:
            _fail("record_too_large")
        parsed = parse_python_producer_binding(raw)
    except PythonProducerBindingStoreError:
        raise
    except PythonProducerBindingError as exc:
        raise PythonProducerBindingStoreError("binding_invalid") from exc
    except (AttributeError, OverflowError, RecursionError, TypeError, UnicodeError, ValueError) as exc:
        raise PythonProducerBindingStoreError("binding_invalid") from exc
    return parsed, raw


def _batch_path(workspace: str | Path, binding: PythonProducerBinding) -> Path:
    try:
        root = _safe_root(workspace)
        journal_id = binding.intent.journal_id
        if type(journal_id) is not str or not journal_id or "/" in journal_id or "\\" in journal_id or ".." in journal_id:
            _fail("journal_id_invalid")
        return root / "evolution" / "producer-batches" / journal_id
    except PythonProducerBindingStoreError:
        raise
    except (ProducerProcessError, OSError, TypeError, ValueError) as exc:
        raise PythonProducerBindingStoreError("workspace_invalid") from exc


def _stat_values(info: os.stat_result) -> dict[str, int]:
    return {
        "file_device": info.st_dev, "file_inode": info.st_ino, "file_mode": stat.S_IMODE(info.st_mode),
        "file_nlink": info.st_nlink, "file_mtime_ns": info.st_mtime_ns, "file_ctime_ns": info.st_ctime_ns,
    }


@dataclass(frozen=True, slots=True)
class PythonProducerBindingSidecar:
    binding: PythonProducerBinding
    raw_sha256: str
    raw_size: int
    file_device: int
    file_inode: int
    file_mode: int
    file_nlink: int
    file_mtime_ns: int
    file_ctime_ns: int


def _create_only(parent: int, raw: bytes) -> os.stat_result:
    """Publish one regular 0600 file and return its post-publication stat.

    The temporary hard link is removed before the retained pin is captured.  While
    both names exist ``st_nlink`` is 2; retaining that transient stat would make
    every subsequent read fail the single-link gate.
    """
    temporary = ".python-binding-" + secrets.token_hex(12)
    fd = -1
    linked = False
    temporary_removed = False

    def unlink_owned(name: str) -> None:
        if fd < 0:
            return
        try:
            owned = os.fstat(fd)
            current = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if (current.st_dev, current.st_ino) == (owned.st_dev, owned.st_ino):
                os.unlink(name, dir_fd=parent)
        except OSError:
            pass

    try:
        fd = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=parent,
        )
        offset = 0
        while offset < len(raw):
            count = os.write(fd, raw[offset:])
            if count <= 0:
                _fail("write_unknown")
            offset += count
        os.fsync(fd)
        original = os.fstat(fd)
        if (
            not stat.S_ISREG(original.st_mode)
            or stat.S_IMODE(original.st_mode) != 0o600
            or original.st_nlink != 1
            or original.st_size != len(raw)
        ):
            _fail("file_identity_drift")

        os.link(
            temporary,
            PYTHON_BINDING_SIDECAR_NAME,
            src_dir_fd=parent,
            dst_dir_fd=parent,
            follow_symlinks=False,
        )
        linked = True
        linked_info = os.fstat(fd)
        named = os.stat(PYTHON_BINDING_SIDECAR_NAME, dir_fd=parent, follow_symlinks=False)
        if (
            not stat.S_ISREG(named.st_mode)
            or stat.S_IMODE(named.st_mode) != 0o600
            or (original.st_dev, original.st_ino) != (linked_info.st_dev, linked_info.st_ino)
            or (linked_info.st_dev, linked_info.st_ino, linked_info.st_size)
            != (named.st_dev, named.st_ino, named.st_size)
        ):
            _fail("file_identity_drift")
        os.fsync(parent)

        # Remove the helper link and persist that directory update before retaining
        # the independent single-link stat pin.
        os.unlink(temporary, dir_fd=parent)
        temporary_removed = True
        os.fsync(parent)
        final = os.stat(PYTHON_BINDING_SIDECAR_NAME, dir_fd=parent, follow_symlinks=False)
        if (
            not stat.S_ISREG(final.st_mode)
            or stat.S_IMODE(final.st_mode) != 0o600
            or final.st_nlink != 1
            or (final.st_dev, final.st_ino, final.st_size)
            != (original.st_dev, original.st_ino, original.st_size)
        ):
            _fail("file_identity_drift")
        return final
    except FileExistsError as exc:
        # A pre-existing sidecar makes this operation create-only.  If the
        # descriptor was opened, remove only our temporary inode; never unlink a
        # colliding name that we did not create.
        if fd >= 0 and not temporary_removed:
            unlink_owned(temporary)
        raise PythonProducerBindingStoreError("already_exists") from exc
    except (OSError, PythonProducerBindingStoreError) as exc:
        if linked:
            unlink_owned(PYTHON_BINDING_SIDECAR_NAME)
            try:
                os.fsync(parent)
            except OSError:
                pass
        if fd >= 0 and not temporary_removed:
            unlink_owned(temporary)
        if isinstance(exc, PythonProducerBindingStoreError):
            raise
        raise PythonProducerBindingStoreError("write_unknown") from exc
    finally:
        if fd >= 0:
            os.close(fd)


def persist_python_producer_binding(workspace: str | Path, *, binding: PythonProducerBinding) -> PythonProducerBindingSidecar:
    """Persist one canonical binding exactly once in an existing, not-started batch."""
    parsed, raw = _validated_binding(binding)
    batch = _batch_path(workspace, parsed)
    try:
        with _recovery_lock(batch), _held_directory(batch, create=False) as parent:
            for name in _NOT_STARTED_ARTIFACTS:
                try:
                    os.stat(name, dir_fd=parent, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                _fail("batch_already_started")
            info = _create_only(parent, raw)
    except PythonProducerBindingStoreError:
        raise
    except (OSError, ProducerProcessError) as exc:
        if isinstance(exc, ProducerProcessError) and exc.code == "producer_process_directory_missing":
            raise PythonProducerBindingStoreError("batch_missing") from exc
        raise PythonProducerBindingStoreError("batch_invalid") from exc
    values = _stat_values(info)
    return PythonProducerBindingSidecar(binding=parsed, raw_sha256=hashlib.sha256(raw).hexdigest(), raw_size=len(raw), **values)


def _validated_sidecar_pin(
    expected_sidecar: PythonProducerBindingSidecar, parsed: PythonProducerBinding,
) -> None:
    """Validate the retained pin before opening any workspace descriptor."""
    if type(expected_sidecar) is not PythonProducerBindingSidecar:
        _fail("expected_pin_invalid")
    try:
        pinned, _ = _validated_binding(expected_sidecar.binding)
    except PythonProducerBindingStoreError as exc:
        raise PythonProducerBindingStoreError("expected_pin_invalid") from exc
    if pinned != parsed:
        _fail("expected_pin_invalid")
    if (
        type(expected_sidecar.raw_sha256) is not str
        or _SHA256.fullmatch(expected_sidecar.raw_sha256) is None
        or expected_sidecar.raw_sha256 == "0" * 64
        or type(expected_sidecar.raw_size) is not int
        or isinstance(expected_sidecar.raw_size, bool)
        or not 1 <= expected_sidecar.raw_size <= MAX_PYTHON_BINDING_SIDECAR_BYTES
        or type(expected_sidecar.file_device) is not int
        or type(expected_sidecar.file_inode) is not int
        or type(expected_sidecar.file_mode) is not int
        or type(expected_sidecar.file_nlink) is not int
        or type(expected_sidecar.file_mtime_ns) is not int
        or type(expected_sidecar.file_ctime_ns) is not int
        or any(
            isinstance(value, bool) or value < 0
            for value in (
                expected_sidecar.file_device,
                expected_sidecar.file_inode,
                expected_sidecar.file_mtime_ns,
                expected_sidecar.file_ctime_ns,
            )
        )
        or expected_sidecar.file_device == 0
        or expected_sidecar.file_inode == 0
        or expected_sidecar.file_mode != 0o600
        or expected_sidecar.file_nlink != 1
    ):
        _fail("expected_pin_invalid")


def read_python_producer_binding_sidecar(
    workspace: str | Path, *, binding: PythonProducerBinding, expected_sidecar: PythonProducerBindingSidecar,
) -> PythonProducerBindingSidecar:
    """Read exact bytes and compare them with the independently retained file pin."""
    parsed, expected_raw = _validated_binding(binding)
    _validated_sidecar_pin(expected_sidecar, parsed)
    batch = _batch_path(workspace, parsed)
    try:
        with _held_directory(batch, create=False) as parent:
            try:
                before = os.stat(PYTHON_BINDING_SIDECAR_NAME, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError as exc:
                raise PythonProducerBindingStoreError("missing") from exc
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or stat.S_IMODE(before.st_mode) != 0o600:
                _fail("file_identity_invalid")
            try:
                fd = os.open(PYTHON_BINDING_SIDECAR_NAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
            except FileNotFoundError as exc:
                raise PythonProducerBindingStoreError("missing") from exc
            try:
                opened = os.fstat(fd)
                data = bytearray()
                while len(data) <= MAX_PYTHON_BINDING_SIDECAR_BYTES:
                    chunk = os.read(fd, MAX_PYTHON_BINDING_SIDECAR_BYTES + 1 - len(data))
                    if not chunk:
                        break
                    data.extend(chunk)
                after = os.fstat(fd)
            finally:
                os.close(fd)
            try:
                named = os.stat(PYTHON_BINDING_SIDECAR_NAME, dir_fd=parent, follow_symlinks=False)
            except FileNotFoundError as exc:
                raise PythonProducerBindingStoreError("missing") from exc
            if len(data) > MAX_PYTHON_BINDING_SIDECAR_BYTES or any(
                _stat_values(item) != _stat_values(before) for item in (opened, after, named)
            ):
                _fail("file_identity_drift")
            values = _stat_values(named)
    except FileNotFoundError as exc:
        raise PythonProducerBindingStoreError("missing") from exc
    except PythonProducerBindingStoreError:
        raise
    except (OSError, ProducerProcessError) as exc:
        # `_held_directory` turns a missing batch directory into a fixed native
        # code before this function can see the original FileNotFoundError.  A
        # missing batch or sidecar is the same durable binding absence to this
        # API; preserve that fact instead of collapsing it into read_unknown.
        if isinstance(exc, ProducerProcessError) and exc.code == "producer_process_directory_missing":
            raise PythonProducerBindingStoreError("batch_missing") from exc
        raise PythonProducerBindingStoreError("read_unknown") from exc
    raw = bytes(data)
    if raw != expected_raw or hashlib.sha256(raw).hexdigest() != expected_sidecar.raw_sha256 or len(raw) != expected_sidecar.raw_size:
        _fail("binding_drift")
    expected_values = {
        "file_device": expected_sidecar.file_device, "file_inode": expected_sidecar.file_inode,
        "file_mode": expected_sidecar.file_mode, "file_nlink": expected_sidecar.file_nlink,
        "file_mtime_ns": expected_sidecar.file_mtime_ns, "file_ctime_ns": expected_sidecar.file_ctime_ns,
    }
    if values != expected_values:
        _fail("file_identity_drift")
    try:
        reparsed = parse_python_producer_binding(raw)
    except PythonProducerBindingError as exc:
        raise PythonProducerBindingStoreError("record_invalid") from exc
    if reparsed != parsed:
        _fail("binding_drift")
    return expected_sidecar


__all__ = ["MAX_PYTHON_BINDING_SIDECAR_BYTES", "PYTHON_BINDING_SIDECAR_NAME", "PythonProducerBindingSidecar",
           "PythonProducerBindingStoreError", "persist_python_producer_binding", "read_python_producer_binding_sidecar"]
