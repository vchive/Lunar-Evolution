"""Deterministic source preparation for one pinned, unaccepted OpenEvolve profile.

Explicit input bytes and fixed pinned assets are parsed/copied without imports,
execution or filesystem writes. The result is preparation evidence, never runtime or publication authority.
"""

from __future__ import annotations

import ast
import hashlib
import io
import json
import tarfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

PROFILE = "lunar-openevolve-v040-one-diff-source-v1"
ARCHIVE_BYTES = 3_240_457
ARCHIVE_SHA256 = "1e461e7c231e45f7f1b0ce1446fac29ec27e415b3468f29079ec5d3c1826db63"
ARCHIVE_ROOT = "algorithmicsuperintelligence-openevolve-f7b6339"
ARCHIVE_FILES = 501
ARCHIVE_CONTENT_BYTES = 7_798_021
BROKER_BYTES = 29_029
BROKER_SHA256 = "ab9d1f33200b2fd95dfa27816a01ac3eabe2523159fd45c53c32a2930bfddfe7"
TRANSPORT_BYTES = 25_870
TRANSPORT_SHA256 = "75aeba263dbcfc5ca3016728569ac1df517159e23ebd72e25887b6b9fbfe4d6c"
_ASSETS = Path(__file__).parent / "assets"
_ASSET_PINS = {
    "fixed_entrypoint.py": (16_734, "d5b2009c225c68f06a4cea0d12a580a2b3619e905ab70b5a14cc4d6df9ab3c72"),
    "LICENSE.lunar": (1_063, "360689238ecd6c5940cb7abc450a749cbe4d8556e3bcac1a97694ccfce2d11c8"),
    "package_init.py": (94, "e554e63bec7c39b95793ff8ffe5701b4eb6a90026e41c06a459c4677d077e10e"),
}
_ORIGINAL_PINS = {
    "LICENSE": (11_357, "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4"),
    "openevolve/__init__.py": (499, "61c38925fb14fc9d968b36a84cfc67d0aaa991e2b723211b2447af6c1f26fda8"),
    "openevolve/prompt/__init__.py": (194, "a6570bd339fb6acbdd4e903dcdb43ab109bf2f19dcc2ad90c95e1bf83cf8a22b"),
    "openevolve/utils/__init__.py": (964, "e235ee9a3cf14becf01868ce356067d73abb7b63b9b39b14c2e4c88eb8c77ae0"),
    "openevolve/prompt/templates.py": (7_303, "2a6f2ae941f5eeabf02c5de0c49bd3eac7c5eb9e215c221c965c1cc2d430d212"),
    "openevolve/utils/code_utils.py": (14_180, "d9e208da50f55a564a73901a8f78d46046317a14d16a1f0868a6f80733e26b65"),
}
PREPARED_PATHS = frozenset({
    "LICENSE", "LICENSE.lunar", "openevolve/__init__.py", "openevolve/lunar_fixed.py",
    "openevolve/lunar_fixed_broker.py", "openevolve/prompt/__init__.py",
    "openevolve/prompt/templates.py", "openevolve/utils/__init__.py",
    "openevolve/utils/code_utils.py",
})
BROKER_DEFINITIONS = (
    "ProducerBrokerIpcError", "_encode", "_decode", "_invalid", "_unique", "_body",
    "_check_stop", "_read_line", "_write_line", "_target_pipe", "brokered_producer_post",
)
_BROKER_CONSTANTS = (
    "_MAX_FRAME_BYTES", "_MAX_RESPONSE_FRAME_BYTES", "_REQUEST_ID", "_STOP_POLL_SECONDS",
)
_TRANSPORT_CONSTANTS = ("MAX_REQUEST_BYTES", "MAX_RESULT_BYTES")
_BROKER_HEADER = '''"""Generated exact source subset of Lunar's pinned anonymous-pipe client.

The host owns destination, credentials and request accounting. Only the existing
anonymous-pipe FD handoffs are read here. No Lunar package is imported.
"""
from __future__ import annotations

import base64
import binascii
import json
import os
import re
import selectors
import stat
import threading
import time
'''


class OpenEvolvePreparationError(ValueError):
    """Fixed code without source bytes, caller paths or original error prose."""


def _fail(code: str) -> None:
    raise OpenEvolvePreparationError("openevolve_source_" + code)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _identity(raw: bytes) -> dict[str, object]:
    return {"bytes": len(raw), "sha256": _sha(raw)}


def _pinned(raw: bytes, size: int, digest: str, code: str) -> None:
    if type(raw) is not bytes or len(raw) != size or _sha(raw) != digest:
        _fail(code)


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class PreparedSource:
    path: str
    data: bytes


@dataclass(frozen=True, slots=True)
class OpenEvolvePreparedProfile:
    sources: tuple[PreparedSource, ...]
    manifest: bytes

    @property
    def manifest_sha256(self) -> str:
        return _sha(self.manifest)


def _read_archive_members(
    archive: bytes, *, expected_files: int, expected_bytes: int, selected: set[str],
) -> dict[str, bytes]:
    """Bounded all-member walk, with no filesystem extraction or code execution.

    Caller must verify the complete archive pin first. The separate arguments
    permit synthetic malformed-archive fixtures without loosening that public pin.
    """
    seen: set[str] = set()
    found: dict[str, bytes] = {}
    files = total = members = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as source:
            for member in source:
                members += 1
                if members > 1024:
                    _fail("archive_bounds")
                name = member.name.rstrip("/") if member.isdir() else member.name
                parts = name.split("/")
                if (not name or "\\" in name or "\x00" in name or name.startswith("/")
                        or any(part in {"", ".", ".."} for part in parts)
                        or parts[0] != ARCHIVE_ROOT or name in seen):
                    _fail("archive_path_invalid")
                seen.add(name)
                if member.isdir():
                    if member.size != 0 or member.mode not in {0o755, 0o775}:
                        _fail("archive_member_invalid")
                    continue
                # The pinned GitHub tar keeps group-write bits (0664/0775);
                # the reviewed Git tree projects only the executable bit.
                if (not member.isreg() or len(parts) < 2
                        or member.mode not in {0o644, 0o664, 0o755, 0o775}
                        or not 0 <= member.size <= expected_bytes):
                    _fail("archive_member_invalid")
                files += 1
                total += member.size
                if files > expected_files or total > expected_bytes:
                    _fail("archive_bounds")
                path = str(PurePosixPath(*parts[1:]))
                handle = source.extractfile(member)
                if handle is None:
                    _fail("archive_member_invalid")
                with handle:
                    data = handle.read(member.size + 1)
                if len(data) != member.size:
                    _fail("archive_truncated")
                if path in selected:
                    found[path] = data
    except OpenEvolvePreparationError:
        raise
    except (tarfile.TarError, OSError, EOFError, ValueError, OverflowError):
        _fail("archive_invalid")
    if files != expected_files or total != expected_bytes or set(found) != selected:
        _fail("archive_inventory_mismatch")
    return found


def _segments(source: bytes, names: tuple[str, ...], *, definitions: bool) -> list[str]:
    text = source.decode("utf-8")
    tree = ast.parse(text)
    selected: dict[str, str] = {}
    for node in tree.body:
        name = None
        if definitions and isinstance(node, (ast.ClassDef, ast.FunctionDef)):
            name = node.name
        elif (not definitions and isinstance(node, ast.Assign) and len(node.targets) == 1
              and isinstance(node.targets[0], ast.Name)):
            name = node.targets[0].id
        if name in names:
            segment = ast.get_source_segment(text, node)
            if name in selected or segment is None:
                _fail("broker_source_invalid")
            if definitions and bool(getattr(node, "decorator_list", [])):
                _fail("broker_source_invalid")
            selected[name] = segment
    if set(selected) != set(names):
        _fail("broker_source_invalid")
    return [selected[name] for name in names]


def generate_target_broker(
    broker_source_bytes: bytes, transport_source_bytes: bytes,
) -> tuple[bytes, tuple[dict[str, object], ...]]:
    """Generate only reviewed segments after binding complete current sources."""
    _pinned(broker_source_bytes, BROKER_BYTES, BROKER_SHA256, "broker_source_drift")
    _pinned(transport_source_bytes, TRANSPORT_BYTES, TRANSPORT_SHA256, "transport_source_drift")
    transport = _segments(transport_source_bytes, _TRANSPORT_CONSTANTS, definitions=False)
    constants = _segments(broker_source_bytes, _BROKER_CONSTANTS, definitions=False)
    definitions = _segments(broker_source_bytes, BROKER_DEFINITIONS, definitions=True)
    segments = transport + constants + definitions
    names = _TRANSPORT_CONSTANTS + _BROKER_CONSTANTS + BROKER_DEFINITIONS
    origins = ("http_transport.py",) * len(transport) + ("producer_broker_ipc.py",) * (
        len(constants) + len(definitions)
    )
    records = tuple(
        {"name": name, "source": origin, **_identity(segment.encode("utf-8"))}
        for name, origin, segment in zip(names, origins, segments, strict=True)
    )
    return (_BROKER_HEADER + "\n\n" + "\n\n\n".join(segments) + "\n").encode("utf-8"), records


def _asset(name: str) -> bytes:
    size, digest = _ASSET_PINS[name]
    try:
        with (_ASSETS / name).open("rb") as source:
            raw = source.read(size + 1)
    except OSError:
        _fail("asset_unavailable")
    _pinned(raw, size, digest, "asset_drift")
    return raw


def _stdlib_imports(sources: tuple[PreparedSource, ...]) -> list[str]:
    imports = set()
    for source in sources:
        if not source.path.endswith(".py"):
            continue
        for node in ast.walk(ast.parse(source.data)):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".")[0])
    return sorted(imports - {"__future__", "openevolve"})


def prepare_openevolve_sources(
    archive_bytes: bytes, *, broker_source_bytes: bytes, transport_source_bytes: bytes,
) -> OpenEvolvePreparedProfile:
    """Prepare exactly seven modules and two license notices, never importing them."""
    _pinned(archive_bytes, ARCHIVE_BYTES, ARCHIVE_SHA256, "archive_pin_mismatch")
    original = _read_archive_members(
        archive_bytes, expected_files=ARCHIVE_FILES, expected_bytes=ARCHIVE_CONTENT_BYTES,
        selected=set(_ORIGINAL_PINS),
    )
    for path, (size, digest) in _ORIGINAL_PINS.items():
        _pinned(original[path], size, digest, "upstream_source_mismatch")
    broker, segments = generate_target_broker(broker_source_bytes, transport_source_bytes)
    initializer = _asset("package_init.py")
    entrypoint = _asset("fixed_entrypoint.py")
    lunar_license = _asset("LICENSE.lunar")
    added = {
        "openevolve/lunar_fixed.py": entrypoint, "openevolve/lunar_fixed_broker.py": broker,
        "LICENSE.lunar": lunar_license,
    }
    replaced = {path for path in original if path.endswith("/__init__.py")}
    prepared = {**original, **dict.fromkeys(replaced, initializer), **added}
    sources = tuple(PreparedSource(path, prepared[path]) for path in sorted(prepared))
    source_records = []
    for source in sources:
        if source.path in {"LICENSE", "LICENSE.lunar"}:
            continue
        old = original.get(source.path)
        source_records.append({
            "path": source.path,
            "module": (source.path.removesuffix("/__init__.py") if source.path.endswith("/__init__.py")
                       else source.path.removesuffix(".py")).replace("/", "."),
            "package": source.path.endswith("/__init__.py"),
            "kind": "added" if old is None else "replaced" if source.path in replaced else "unchanged",
            "original": None if old is None else {"path": source.path, **_identity(old)},
            "result": _identity(source.data),
            "asset": ({"path": "assets/fixed_entrypoint.py", **_identity(entrypoint)}
                      if source.path == "openevolve/lunar_fixed.py" else
                      {"path": "assets/package_init.py", **_identity(initializer)}
                      if source.path in replaced else None),
        })
    manifest = {
        "schema": "lunar-openevolve-fixed-source-v1", "profile": PROFILE,
        "upstream": {
            "release": "v0.4.0", "commit": "f7b633986c0b3dbd0a171f6eb0cb0f0ba4fdfb0c",
            "tree": "3b969ae24962dd8aeb379d674d688824adc88508",
            "archive": _identity(archive_bytes), "archive_regular_files": ARCHIVE_FILES,
            "archive_content_bytes": ARCHIVE_CONTENT_BYTES,
        },
        "broker": {
            "source": {"path": "src/lunar_evolution/producer_broker_ipc.py", **_identity(broker_source_bytes)},
            "transport": {"path": "src/lunar_evolution/http_transport.py", **_identity(transport_source_bytes)},
            "segments": list(segments),
            "environment": ["LUNAR_PRODUCER_REQUEST_FD", "LUNAR_PRODUCER_RESPONSE_FD"],
        },
        "entrypoint": {
            "module": "openevolve.lunar_fixed", "function": "main",
            "marker": "--lunar-rsi-input-v1", "inputs": ["request.json", "memory.json"],
            "settings": ["initial_program", "model", "task"], "max_requests": 1,
            "outputs": ["candidate.py", "result.json"], "new_grants": [],
            "result_kind": "candidate_path_wrapper_not_producer_result_envelope",
        },
        "sources": source_records,
        "license": {
            "upstream": {"path": "LICENSE", "kind": "unchanged", "spdx": "Apache-2.0",
                         "original": _identity(original["LICENSE"]), "result": _identity(prepared["LICENSE"])},
            "lunar": {"path": "LICENSE.lunar", "kind": "unchanged", "spdx": "MIT",
                      "source": {"path": "LICENSE", **_identity(lunar_license)},
                      "asset": {"path": "assets/LICENSE.lunar", **_identity(lunar_license)},
                      "result": _identity(lunar_license)},
        },
        "resources": [], "stdlib_direct_imports": _stdlib_imports(sources),
        "claims": {
            "source_only": True, "closure_verified": False, "upstream_imported": False,
            "source_execution_performed": False, "build_performed": False,
            "runtime_execution_performed": False, "production_admission": False,
            "online_publication": False,
        },
    }
    return OpenEvolvePreparedProfile(sources, _canonical(manifest))
