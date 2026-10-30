"""Same-command native cache export through the original isolated build loop.

The native helper links one fixed seed and exports its own still-live caches.
A successful export observes bytes; it does not authenticate tool acquisition,
prove complete driver reads, accept an installation or execute the seed.
"""

from __future__ import annotations

import hashlib
import stat
import struct
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from tools.static_python_rsi_fixture.build_dependency_consumer import (
    _read_pin,
    _report_outputs,
    _write_once,
)
from tools.static_python_rsi_fixture.concrete_recipe import (
    ConcreteBuildRecipe,
    _record,
    complete_zig_inventory,
)
from tools.static_python_rsi_fixture.execution_backend import (
    MAX_OUTPUT_BYTES,
    RECIPE_V3_SCHEMA,
    _recipe,
    run_pinned_build_v3,
)
from tools.static_python_rsi_fixture.installation_profile import RSIProfilePreparation
from tools.static_python_rsi_fixture.podman_custody import SNAPSHOT_BACKEND, _static_executable
from tools.static_python_rsi_fixture.runtime_closure import canonical
from tools.static_python_rsi_fixture.zig_support import _SOURCE
from tools.static_python_rsi_fixture.zig_support_candidates import (
    _FALSE,
    _NAMES,
    _SCHEMA,
    ZigSupportCandidateBundle,
    validate_zig_support_candidate_bundle,
)
from tools.static_python_rsi_fixture.zig_support_selection import _checkpoint

MAGIC = b"LZSUP01\n"
MAX_ENTRIES = 32768
MAX_CACHE_BYTES = 512 * 1024**2
MAX_FILE_BYTES = 128 * 1024**2
MAX_PATH_BYTES = 480
COMMAND_PROFILE = "native-support-export-v1"
HELPER_SOURCE_PATH = "native/native_support_export.c"
HELPER_SOURCE_SHA256 = "05ca88764aec87a07fda17159735b1348b2e388f0624d9a52e76b0e614deb85a"
_ASSET = Path(__file__).with_name("assets") / "native_support_export.c"
_HELPER = "bin/lunar-native-support-export"
_SEED = "support/seed"
_EXPORT = "support/native-cache-export.bin"
_CACHES = ("global", "local")
_ROW = struct.Struct(">BBHIQ32s")


class NativeSupportExportError(ValueError):
    """Fixed refusal retaining any original execution and partial output."""


def _fail(reason: str) -> None:
    raise NativeSupportExportError("native_support_export_" + reason)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class NativeSupportExportWire:
    entries: tuple[dict, ...]
    inventories: dict[str, list[dict]]
    candidates: tuple[tuple[str, bytes], ...]


@dataclass(frozen=True, slots=True)
class NativeSupportExportResult:
    observation_bytes: bytes
    candidates: ZigSupportCandidateBundle

    @property
    def sha256(self) -> str:
        return _sha(self.observation_bytes)


def parse_native_support_export(raw: bytes) -> NativeSupportExportWire:
    """Read finite native bytes, never filesystem paths or claimed authority."""
    if type(raw) is not bytes or not 26 <= len(raw) <= MAX_OUTPUT_BYTES or raw[:8] != MAGIC:
        _fail("wire")
    count, candidate_count = struct.unpack_from(">II", raw, 8)
    if count > MAX_ENTRIES or candidate_count > count:
        _fail("bounds")
    offset = 16
    for _ in _CACHES:
        present, mode = struct.unpack_from(">BI", raw, offset)
        offset += 5
        if present != 1 or mode != stat.S_IFDIR | 0o700:
            _fail("root")
    entries, candidates = [], []
    inventories = {cache: [] for cache in _CACHES}
    seen: dict[tuple[int, str], str] = {}
    previous = None
    total = 0
    for _ in range(count):
        if len(raw) - offset < _ROW.size:
            _fail("truncated")
        cache_id, kind_id, length, mode, size, digest = _ROW.unpack_from(raw, offset)
        offset += _ROW.size
        if cache_id >= len(_CACHES) or kind_id not in {1, 2} or not 0 < length <= MAX_PATH_BYTES:
            _fail("entry")
        path_raw = raw[offset:offset + length]
        offset += length
        if (len(path_raw) != length or any(c < 33 or c > 126 or c in b"\\:" for c in path_raw)):
            _fail("path")
        path = path_raw.decode("ascii")
        parts = path.split("/")
        if (any(part in {"", ".", ".."} for part in parts)
                or str(PurePosixPath(path)) != path):
            _fail("path")
        key = (cache_id, path)
        if previous is not None and key <= previous:
            _fail("order")
        previous = key
        for end in range(1, len(parts)):
            if seen.get((cache_id, "/".join(parts[:end]))) != "directory":
                _fail("parent")
        kind = "directory" if kind_id == 1 else "file"
        if mode & ~0o177777 or stat.S_IFMT(mode) != (stat.S_IFDIR if kind_id == 1 else stat.S_IFREG):
            _fail("mode")
        if kind_id == 1:
            if size or digest != b"\0" * 32:
                _fail("directory")
        else:
            if size > MAX_FILE_BYTES:
                _fail("bounds")
            total += size
            if total > MAX_CACHE_BYTES:
                _fail("bounds")
            inventories[_CACHES[cache_id]].append({"path": path, "size": size,
                "sha256": digest.hex(), "executable": bool(mode & 0o111)})
            if parts[-1] in _NAMES:
                if not size or mode & 0o111 or len(raw) - offset < size:
                    _fail("candidate")
                value = raw[offset:offset + size]
                offset += size
                if _sha(value) != digest.hex():
                    _fail("candidate_pin")
                candidates.append(("candidates/" + _CACHES[cache_id] + "/" + path, value))
        seen[key] = kind
        entries.append({"cache": _CACHES[cache_id], "kind": kind, "path": path,
                        "mode": mode, "size": size, "sha256": digest.hex()})
    if offset != len(raw) or len(candidates) != candidate_count:
        _fail("length")
    return NativeSupportExportWire(tuple(entries), inventories, tuple(candidates))


def _helper_source() -> bytes:
    raw = _ASSET.read_bytes()
    if not 0 < len(raw) <= 256 * 1024 or _sha(raw) != HELPER_SOURCE_SHA256:
        _fail("helper_source_pin")
    return raw


def _stages() -> list[dict]:
    compiler = ["@toolchain/zig", "cc", "-target", "x86_64-linux-musl",
                "-std=c11", "-O2", "-g0", "-static"]
    prefix = ["@toolchain/zig", "cc", "-target", "x86_64-linux-musl", "-std=c11", "-O0", "-g0"]
    stages = [{"stage": "configure", "commands": [{
        "argv": [*compiler, "@source/" + HELPER_SOURCE_PATH, "-o", "@work/" + _HELPER],
        "outputs": [{"path": _HELPER, "max_size": 2 * 1024**2, "executable": True}],
    }]}]
    for stage, names in (("freeze", ("support/probe.c",)),
                         ("compile", ("support/main.c", "support/div.c"))):
        commands = []
        for name in names:
            target = name.removesuffix(".c") + ".o"
            commands.append({"argv": [*prefix, "-c", "@source/" + name, "-o", "@work/" + target],
                             "outputs": [{"path": target, "max_size": 1024**2, "executable": False}]})
        stages.append({"stage": stage, "commands": commands})
    stages.append({"stage": "link", "commands": [{
        "argv": ["@work/" + _HELPER, "@toolchain/zig",
                 "/tmp/zig-global/native-support", "/tmp/zig-local/native-support",
                 "@work/" + _SEED, "@work/" + _EXPORT,
                 "@work/support/probe.o", "@work/support/main.o", "@work/support/div.o"],
        "outputs": [{"path": _SEED, "max_size": 16 * 1024**2, "executable": True},
                    {"path": _EXPORT, "max_size": MAX_OUTPUT_BYTES, "executable": False}],
    }]})
    return stages


def prepare_native_support_export_recipe(
    preparation: RSIProfilePreparation, *, zig_manifest_bytes: bytes,
) -> ConcreteBuildRecipe:
    """Compile the fixed helper, then export inside the sole link container."""
    helper = _helper_source()
    tools = complete_zig_inventory(zig_manifest_bytes)
    stages = _stages()
    sources = {**_SOURCE, HELPER_SOURCE_PATH: helper}
    raw = canonical({"schema": RECIPE_V3_SCHEMA, "preparation_sha256": preparation.sha256,
        "inputs": {"source": [_record(name, value) for name, value in sorted(sources.items())],
                   "toolchain": tools},
        "environment": {"LANG": "C", "LC_ALL": "C", "TZ": "UTC", "SOURCE_DATE_EPOCH": "0"},
        "stages": stages})
    _recipe(raw, _sha(raw), version3=True)
    manifest = canonical({"schema": "lunar-native-zig-support-export-recipe-v1",
        "recipe_sha256": _sha(raw), "helper_source_sha256": HELPER_SOURCE_SHA256,
        "custody_backend": SNAPSHOT_BACKEND, "seed_executed": False, **_FALSE})
    return ConcreteBuildRecipe(raw, tuple(sorted(sources.items())), manifest)


def validate_native_support_export_graph(recipe: dict) -> None:
    """A separately selected exact graph, never a relaxed capture validator."""
    sources = {**_SOURCE, HELPER_SOURCE_PATH: _helper_source()}
    expected_source = [_record(name, value) for name, value in sorted(sources.items())]
    if (type(recipe) is not dict or recipe.get("schema") != RECIPE_V3_SCHEMA
            or set(recipe) != {"schema", "preparation_sha256", "inputs", "environment", "stages"}
            or type(recipe.get("inputs")) is not dict
            or set(recipe["inputs"]) != {"source", "toolchain"}
            or canonical(recipe["inputs"]["source"]) != canonical(expected_source)
            or canonical(recipe["stages"]) != canonical(_stages())
            or recipe["environment"] != {"LANG": "C", "LC_ALL": "C", "TZ": "UTC", "SOURCE_DATE_EPOCH": "0"}):
        _fail("command_graph")


def run_native_support_export(
    preparation: RSIProfilePreparation, *, zig_manifest_bytes: bytes, toolchain_root: Path,
    workspace: Path, deadline: float, interrupted: Callable[[], bool] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> NativeSupportExportResult:
    """Execute once with fixed Podman snapshots; no local fallback or admission."""
    check = _checkpoint(deadline, interrupted, monotonic)
    build = prepare_native_support_export_recipe(preparation, zig_manifest_bytes=zig_manifest_bytes)
    parsed = _recipe(build.recipe_bytes, build.sha256, version3=True)
    root, tools = workspace.absolute(), toolchain_root.absolute()
    if (root.parent.resolve() != root.parent or not root.parent.is_dir()
            or tools.resolve() != tools or root == tools or root in tools.parents or tools in root.parents):
        _fail("workspace")
    try:
        root.mkdir(mode=0o700)
    except OSError:
        _fail("workspace_not_fresh")
    source = root / "seed-source"
    source.mkdir(mode=0o700)
    for name, raw in build.sources:
        check()
        path = source / name
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        _write_once(path.parent, path.name, raw, check)
    attempt = root / "attempt"
    report = run_pinned_build_v3(preparation, recipe_bytes=build.recipe_bytes,
        expected_recipe_sha256=build.sha256, source_root=source, toolchain_root=tools,
        workspace=attempt, deadline=deadline, interrupted=interrupted, monotonic=monotonic,
        custody_backend=SNAPSHOT_BACKEND, command_profile=COMMAND_PROFILE)
    check()
    report_raw, outputs = _report_outputs(report, parsed, custody_backend=SNAPSHOT_BACKEND)
    report_pin = _record("report.json", report_raw)
    _read_pin(attempt, report_pin, check)
    work = attempt / "work"
    by_path = {row["path"]: row for row in outputs}
    if set(by_path) != {_HELPER, _SEED, _EXPORT, *(name.removesuffix(".c") + ".o" for name in _SOURCE)}:
        _fail("output_set")
    for row in outputs:
        _read_pin(work, row, check)
    _static_executable(work, by_path[_HELPER], check)
    _static_executable(work, by_path[_SEED], check)
    wire_raw = _read_pin(work, by_path[_EXPORT], check, retain=True)
    wire = parse_native_support_export(wire_raw)
    cache_pins, cache_records = {}, []
    for cache, rows in wire.inventories.items():
        raw = canonical(rows)
        cache_pins[cache] = {"sha256": _sha(raw), "files": len(rows),
                             "bytes": sum(row["size"] for row in rows)}
        _write_once(root, "cache-" + cache + "-inventory.json", raw, check)
        cache_records.append(_record("cache-" + cache + "-inventory.json", raw))
    sealed = root / "sealed"
    sealed.mkdir(mode=0o700)
    candidates = []
    for path, raw in wire.candidates:
        check()
        cache, relative = path.removeprefix("candidates/").split("/", 1)
        target = sealed / path
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        _write_once(target.parent, target.name, raw, check)
        target.chmod(0o400)
        row = _record(path, raw)
        _read_pin(sealed, row, check)
        candidates.append({**row, "cache": cache, "cache_path": relative})
    candidate_facts = {"schema": _SCHEMA, "target": "x86_64-linux-musl",
        "preparation_sha256": preparation.sha256, "seed_recipe_sha256": build.sha256,
        "seed_report_sha256": _sha(report_raw), "seed": by_path[_SEED],
        "objects": sorted((by_path[name.removesuffix('.c') + '.o'] for name in _SOURCE), key=lambda r: r['path']),
        "zig_inventory_sha256": _sha(canonical(parsed["inputs"]["toolchain"])),
        "cache_inventories": cache_pins, "candidates": candidates, "seed_executed": False, **_FALSE}
    bundle = ZigSupportCandidateBundle(canonical(candidate_facts), wire.candidates)
    validate_zig_support_candidate_bundle(bundle, expected_bundle_sha256=bundle.sha256,
        preparation_sha256=preparation.sha256,
        zig_inventory_sha256=candidate_facts["zig_inventory_sha256"])
    _write_once(root, "support-candidates.json", bundle.manifest_bytes, check)
    observation = canonical({"schema": "lunar-native-zig-support-export-observation-v1",
        "preparation_sha256": preparation.sha256, "recipe_sha256": build.sha256,
        "report_sha256": _sha(report_raw), "helper_source_sha256": HELPER_SOURCE_SHA256,
        "helper": by_path[_HELPER], "native_export": by_path[_EXPORT],
        "candidate_bundle_sha256": bundle.sha256, "cache_entries": list(wire.entries),
        "custody_backend": SNAPSHOT_BACKEND, "seed_executed": False, **_FALSE})
    _write_once(root, "native-support-export.json", observation, check)
    for role, original in (("source", source), ("toolchain", tools)):
        for row in parsed["inputs"][role]:
            _read_pin(original, row, check)
            _read_pin(attempt / role, row, check)
    for row in outputs:
        _read_pin(work, row, check)
    _read_pin(attempt, report_pin, check)
    _read_pin(root, _record("support-candidates.json", bundle.manifest_bytes), check)
    _read_pin(root, _record("native-support-export.json", observation), check)
    for row in cache_records:
        _read_pin(root, row, check)
    for row in candidates:
        _read_pin(sealed, {key: row[key] for key in ("path", "size", "sha256", "executable")}, check)
    check()
    return NativeSupportExportResult(observation, bundle)
