"""One bounded sealed data frame, without Python execution or admission authority.

The public FD is borrowed. Only the creating context retains cleanup authority;
detached descriptors, copied handles and numeric FD values cannot recreate it.
Deadline checks surround synchronous calls and cannot preempt a blocked syscall.
"""

from __future__ import annotations

import hashlib
import math
import os
import stat
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from . import producer_python_runtime as declared
from . import producer_python_runtime_tree as source
from ._python_runtime_material_format import (
    HEADER_SIZE,
    PythonRuntimeMaterialDescriptor,
    PythonRuntimeMaterialError,
    _label,
    descriptor_from_table,
    pack_header,
    parse_python_runtime_material_descriptor,
    parse_table,
    table_from_tree,
    unpack_header,
)
from ._python_runtime_material_io import copy_payload, verify_source

try:
    import fcntl
except ImportError:  # pragma: no cover - unavailable on Windows
    fcntl = None

_CHUNK_SIZE = 65536
_SEAL_NAMES = ("F_SEAL_WRITE", "F_SEAL_GROW", "F_SEAL_SHRINK", "F_SEAL_SEAL")


@dataclass(frozen=True, slots=True, eq=False)
class SealedPythonRuntimeMaterial:
    """Borrowed CLOEXEC FD and detached evidence; construction grants no authority."""

    fd: int
    descriptor: PythonRuntimeMaterialDescriptor


@dataclass(slots=True)
class _Owner:
    deadline: float
    anchor: int = -1
    borrowed: int = -1
    identity: tuple[int, int, int] | None = None
    table_bytes: bytes = b""
    descriptor_bytes: bytes = b""
    seals: int = 0

    def checkpoint(self) -> None:
        if time.monotonic() >= self.deadline:
            raise PythonRuntimeMaterialError("deadline_exceeded")


# Entries exist only for the duration of their creating context. Identity, rather
# than dataclass equality, binds a live handle to its original private owner.
_OWNERS: dict[int, tuple[SealedPythonRuntimeMaterial, _Owner]] = {}


def _identity(info: os.stat_result) -> tuple[int, int, int]:
    if not stat.S_ISREG(info.st_mode):
        raise PythonRuntimeMaterialError("object_invalid")
    return info.st_dev, info.st_ino, stat.S_IFMT(info.st_mode)


def _sha(value: object) -> str:
    if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        raise PythonRuntimeMaterialError("digest_invalid")
    return value


def _target(value: object) -> bytes:
    if type(value) is not declared.PythonRuntimeTarget:
        raise PythonRuntimeMaterialError("target_invalid")
    source._target_text(value)
    value.__post_init__()
    return value.to_json()


def _support() -> int:
    if (not sys.platform.startswith("linux")
            or not callable(getattr(os, "memfd_create", None))
            or not callable(getattr(os, "pread", None))
            or any(not hasattr(os, name) for name in ("MFD_ALLOW_SEALING", "MFD_CLOEXEC"))
            or any(not hasattr(fcntl, name) for name in ("F_ADD_SEALS", "F_GET_SEALS", "F_DUPFD_CLOEXEC",
                                                       "F_GETFD", "FD_CLOEXEC", *_SEAL_NAMES))):
        raise PythonRuntimeMaterialError("unsupported")
    seals = 0
    for name in _SEAL_NAMES:
        seals |= getattr(fcntl, name)
    return seals


def _owned_info(owner: _Owner, descriptor: int) -> os.stat_result:
    owner.checkpoint()
    info = os.fstat(descriptor)
    owner.checkpoint()
    if _identity(info) != owner.identity:
        raise PythonRuntimeMaterialError("ownership_invalid")
    owner.checkpoint()
    flags = fcntl.fcntl(descriptor, fcntl.F_GETFD)
    owner.checkpoint()
    if not flags & fcntl.FD_CLOEXEC:
        raise PythonRuntimeMaterialError("ownership_invalid")
    return info


def _write(owner: _Owner, value: bytes) -> None:
    view, offset = memoryview(value), 0
    while offset < len(view):
        owner.checkpoint()
        written = os.write(owner.anchor, view[offset:offset + _CHUNK_SIZE])
        owner.checkpoint()
        if type(written) is not int or not 0 < written <= min(_CHUNK_SIZE, len(view) - offset):
            raise PythonRuntimeMaterialError("write_failed")
        offset += written


def _read(owner: _Owner, descriptor: int, offset: int, size: int) -> bytes:
    chunks, received = [], 0
    while received < size:
        owner.checkpoint()
        chunk = os.pread(descriptor, min(_CHUNK_SIZE, size - received), offset + received)
        owner.checkpoint()
        if not chunk:
            raise PythonRuntimeMaterialError("frame_truncated")
        chunks.append(chunk)
        received += len(chunk)
    return b"".join(chunks)


def _inspect(owner: _Owner, descriptor: int, *, sealed: bool) -> PythonRuntimeMaterialDescriptor:
    """Read independently, with no source path observations or public DTO trust."""
    before = _owned_info(owner, descriptor)
    if sealed:
        owner.checkpoint()
        actual_seals = fcntl.fcntl(descriptor, fcntl.F_GET_SEALS)
        owner.checkpoint()
        if actual_seals & owner.seals != owner.seals:
            raise PythonRuntimeMaterialError("seals_invalid")
    header = _read(owner, descriptor, 0, HEADER_SIZE)
    table_size, payload_size = unpack_header(header, before.st_size)
    table_bytes = _read(owner, descriptor, HEADER_SIZE, table_size)
    if table_bytes != owner.table_bytes:
        raise PythonRuntimeMaterialError("table_binding_mismatch")
    owner.checkpoint()
    table = parse_table(table_bytes)
    owner.checkpoint()
    if table.payload_size != payload_size:
        raise PythonRuntimeMaterialError("payload_size_mismatch")
    frame_hash, payload_hash = hashlib.sha256(), hashlib.sha256()
    frame_hash.update(header)
    frame_hash.update(table_bytes)
    for file in table.files:
        file_hash, read = hashlib.sha256(), 0
        while read < file.size:
            chunk = _read(owner, descriptor, HEADER_SIZE + table_size + file.offset + read,
                          min(_CHUNK_SIZE, file.size - read))
            owner.checkpoint()
            file_hash.update(chunk)
            payload_hash.update(chunk)
            frame_hash.update(chunk)
            owner.checkpoint()
            read += len(chunk)
        if file_hash.hexdigest() != file.sha256:
            raise PythonRuntimeMaterialError("file_digest_mismatch")
    after = _owned_info(owner, descriptor)
    if before.st_size != after.st_size:
        raise PythonRuntimeMaterialError("frame_changed")
    owner.checkpoint()
    observation = descriptor_from_table(
        table, table_size, hashlib.sha256(table_bytes).hexdigest(),
        payload_hash.hexdigest(), frame_hash.hexdigest(),
    )
    owner.checkpoint()
    if owner.descriptor_bytes and observation.to_json() != owner.descriptor_bytes:
        raise PythonRuntimeMaterialError("descriptor_binding_mismatch")
    return observation


def _cleanup(owner: _Owner, primary: BaseException | None) -> None:
    """Deadline expiry must not prevent release of descriptors still owned here."""
    uncertain = False
    for field in ("borrowed", "anchor"):
        descriptor = getattr(owner, field)
        setattr(owner, field, -1)
        if descriptor < 0:
            continue
        try:
            current = _identity(os.fstat(descriptor))
            # Identity acquisition can fail immediately after private creation.
            # This number was never exposed. A final successful fstat permits
            # releasing that original acquisition; no public pins are consulted.
            if owner.identity is None and field == "anchor":
                owner.identity = current
            if current != owner.identity:
                uncertain = True
                continue
            os.close(descriptor)
        except BaseException:  # noqa: BLE001 - release all remaining owners, preserve primary
            uncertain = True
    if uncertain:
        if primary is not None:
            primary.add_note("python_runtime_material_cleanup_unknown")
        else:
            raise PythonRuntimeMaterialError("cleanup_unknown")


@contextmanager
def materialize_sealed_python_runtime_material(
    manifest: source.PythonRuntimeTreeManifest, *, expected_tree_sha256: str,
    expected_manifest_sha256: str, expected_target: declared.PythonRuntimeTarget,
    material_version: str, deadline: float,
) -> Iterator[SealedPythonRuntimeMaterial]:
    """Copy only the externally pinned tree; seal and verify before yielding."""
    owner, live, primary = None, None, None
    try:
        tree_pin, manifest_pin = _sha(expected_tree_sha256), _sha(expected_manifest_sha256)
        target_bytes = _target(expected_target)
        _label(material_version)
        if type(deadline) not in (float, int) or not math.isfinite(deadline):
            raise PythonRuntimeMaterialError("deadline_invalid")
        if type(manifest) is not source.PythonRuntimeTreeManifest:
            raise PythonRuntimeMaterialError("manifest_invalid")
        # Historical validators here are pure. Do not call their filesystem
        # scanner: all source IO below uses guarded per-operation checkpoints.
        manifest.__post_init__()
        original = source.parse_python_runtime_tree_manifest(manifest.to_json())
        if (original.tree_sha256 != tree_pin
                or original.declared_manifest.manifest_sha256 != manifest_pin
                or original.declared_manifest.target.to_json() != target_bytes):
            raise PythonRuntimeMaterialError("external_pin_mismatch")
        table = table_from_tree(original, material_version)
        table_bytes = table.to_json()
        header = pack_header(len(table_bytes), table.payload_size)
        owner = _Owner(float(deadline), table_bytes=table_bytes, seals=_support())
        owner.checkpoint()
        owner.anchor = os.memfd_create("lunar-python-material", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
        owner.checkpoint()
        owner.identity = _identity(os.fstat(owner.anchor))
        owner.checkpoint()
        # This preflight uses the sole object, before any source observations.
        initial_seals = fcntl.fcntl(owner.anchor, fcntl.F_GET_SEALS)
        owner.checkpoint()
        if initial_seals != 0:
            raise PythonRuntimeMaterialError("seals_invalid")
        verify_source(original, checkpoint=owner.checkpoint)
        _write(owner, header)
        _write(owner, table_bytes)
        payload_sha256 = copy_payload(original, owner.anchor, checkpoint=owner.checkpoint)
        verify_source(original, checkpoint=owner.checkpoint)
        unsealed = _inspect(owner, owner.anchor, sealed=False)
        if unsealed.payload_sha256 != payload_sha256:
            raise PythonRuntimeMaterialError("payload_digest_mismatch")
        owner.descriptor_bytes = unsealed.to_json()
        owner.checkpoint()
        fcntl.fcntl(owner.anchor, fcntl.F_ADD_SEALS, owner.seals)
        owner.checkpoint()
        _inspect(owner, owner.anchor, sealed=True)
        owner.checkpoint()
        os.lseek(owner.anchor, 0, os.SEEK_SET)
        owner.checkpoint()
        owner.borrowed = fcntl.fcntl(owner.anchor, fcntl.F_DUPFD_CLOEXEC, 0)
        owner.checkpoint()
        _inspect(owner, owner.borrowed, sealed=True)
        live = SealedPythonRuntimeMaterial(
            owner.borrowed, parse_python_runtime_material_descriptor(owner.descriptor_bytes),
        )
        _OWNERS[id(live)] = live, owner
    except (source.PythonRuntimeTreeError, declared.PythonRuntimeError,
            OSError, TypeError, ValueError, AttributeError, OverflowError, RecursionError) as exc:
        primary = exc if isinstance(exc, PythonRuntimeMaterialError) else PythonRuntimeMaterialError("materialization_failed")
        if primary is exc:
            raise
        if "python_runtime_material_cleanup_unknown" in getattr(exc, "__notes__", ()):
            primary.add_note("python_runtime_material_cleanup_unknown")
        raise primary from exc
    except BaseException as exc:
        primary = exc
        raise
    else:
        try:
            yield live
        except BaseException as exc:
            primary = exc
            raise
    finally:
        if live is not None:
            _OWNERS.pop(id(live), None)
        if owner is not None:
            _cleanup(owner, primary)


def verify_sealed_python_runtime_material(
    live: SealedPythonRuntimeMaterial, *, expected_frame_sha256: str,
    expected_tree_sha256: str, expected_manifest_sha256: str,
    expected_target: declared.PythonRuntimeTarget, expected_material_version: str,
) -> PythonRuntimeMaterialDescriptor:
    """Reobserve the original sealed object using its original absolute deadline."""
    try:
        frame, tree, manifest = (_sha(value) for value in (
            expected_frame_sha256, expected_tree_sha256, expected_manifest_sha256,
        ))
        target_bytes = _target(expected_target)
        _label(expected_material_version)
        if type(live) is not SealedPythonRuntimeMaterial:
            raise PythonRuntimeMaterialError("ownership_invalid")
        entry = _OWNERS.get(id(live))
        if entry is None or entry[0] is not live:
            raise PythonRuntimeMaterialError("ownership_invalid")
        owner = entry[1]
        owner.checkpoint()
        if (type(live.fd) is not int or live.fd != owner.borrowed
                or type(live.descriptor) is not PythonRuntimeMaterialDescriptor
                or live.descriptor.to_json() != owner.descriptor_bytes):
            raise PythonRuntimeMaterialError("ownership_invalid")
        retained = parse_python_runtime_material_descriptor(owner.descriptor_bytes)
        if (retained.frame_sha256 != frame or retained.tree_sha256 != tree
                or retained.declared_manifest_sha256 != manifest or retained.target.to_json() != target_bytes
                or retained.material_version != expected_material_version):
            raise PythonRuntimeMaterialError("external_pin_mismatch")
        _owned_info(owner, owner.anchor)
        return _inspect(owner, owner.borrowed, sealed=True)
    except PythonRuntimeMaterialError:
        raise
    except (declared.PythonRuntimeError, source.PythonRuntimeTreeError, OSError, TypeError,
            ValueError, AttributeError, OverflowError, RecursionError) as exc:
        raise PythonRuntimeMaterialError("verification_failed") from exc


__all__ = [
    "PythonRuntimeMaterialDescriptor", "PythonRuntimeMaterialError", "SealedPythonRuntimeMaterial",
    "materialize_sealed_python_runtime_material", "parse_python_runtime_material_descriptor",
    "verify_sealed_python_runtime_material",
]
