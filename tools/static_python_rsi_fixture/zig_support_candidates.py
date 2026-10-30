"""Trusted-local Zig support candidates, never automatic support acceptance.

One fresh source-fixed seed generates cache data without requesting the broken
Zig cc linker-depfile route. Every finite candidate keeps its cache identity;
selection, direct-LLD capture and isolated generation remain separate contracts.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
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
    ConcreteRecipeError,
    _inventory,
    _record,
    complete_zig_inventory,
)
from tools.static_python_rsi_fixture.execution_backend import (
    RECIPE_V3_SCHEMA,
    _finite,
    _observe,
    _recipe,
    run_pinned_build_v3,
)
from tools.static_python_rsi_fixture.installation_profile import RSIProfilePreparation
from tools.static_python_rsi_fixture.runtime_closure import canonical
from tools.static_python_rsi_fixture.zig_support import _SOURCE

_SCHEMA = "lunar-zig-musl-support-candidates-v1"
_MAX_CACHE_ENTRIES = 32768
_MAX_CACHE_BYTES = 512 * 1024 * 1024
_MAX_FILE_BYTES = 128 * 1024 * 1024
_MAX_MANIFEST_BYTES = 16 * 1024 * 1024
_CACHES = {"global": ".zig-global-cache", "local": ".zig-local-cache"}
_NAMES = frozenset({"crt1.o", "crti.o", "crtn.o", "libc.a", "libzigc.a",
                    "libubsan_rt.a", "libcompiler_rt.a"})
_OBJECTS = frozenset(source.removesuffix(".c") + ".o" for source in _SOURCE)
_FALSE = {"immutable_generation_verified": False, "driver_inputs_verified": False,
          "configured_closure_verified": False, "installation_accepted": False,
          "production_admission": False, "online_publication": False,
          "support_selection_accepted": False}


class ZigSupportCandidateError(RuntimeError):
    """Fixed refusals; original workspace and failed attempts remain retained."""


def _fail(reason: str) -> None:
    raise ZigSupportCandidateError("zig_support_candidate_" + reason)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digest(value: object) -> bool:
    return (type(value) is str and len(value) == 64
            and all(char in "0123456789abcdef" for char in value))


def _cache_path(value: object) -> str:
    if (type(value) is not str or not 0 < len(value) <= 480
            or any(part in {"", ".", ".."} for part in value.split("/"))
            or str(PurePosixPath(value)) != value
            or any(ord(char) < 32 or ord(char) > 126 or char in "\\:" for char in value)):
        _fail("cache_path")
    return value


@dataclass(frozen=True, slots=True)
class ZigSupportCandidateBundle:
    """Observed export bytes; no candidate is selected as a link authority."""

    manifest_bytes: bytes
    files: tuple[tuple[str, bytes], ...]

    @property
    def sha256(self) -> str:
        return _sha(self.manifest_bytes)


def prepare_zig_support_candidate_recipe(
    preparation: RSIProfilePreparation, *, zig_manifest_bytes: bytes,
) -> ConcreteBuildRecipe:
    """Preserve the three original sources/compiles; do not request a depfile."""
    tools = complete_zig_inventory(zig_manifest_bytes)
    prefix = ["@toolchain/zig", "cc", "-target", "x86_64-linux-musl", "-std=c11", "-O0", "-g0"]
    stages = []
    for stage, source in zip(("configure", "freeze", "compile"), _SOURCE, strict=True):
        target = source.removesuffix(".c") + ".o"
        stages.append({"stage": stage, "commands": [{
            "argv": [*prefix, "-c", "@source/" + source, "-o", "@work/" + target],
            "outputs": [{"path": target, "max_size": 1024 * 1024, "executable": False}],
        }]})
    stages.append({"stage": "link", "commands": [{
        "argv": ["@toolchain/zig", "cc", "-target", "x86_64-linux-musl", "-static", "-o", "@work/support/seed",
                 "@work/support/probe.o", "@work/support/main.o", "@work/support/div.o",
                 "-lm", "-lpthread", "-lc"],
        "outputs": [{"path": "support/seed", "max_size": 16 * 1024 * 1024, "executable": True}],
    }]})
    raw = canonical({"schema": RECIPE_V3_SCHEMA, "preparation_sha256": preparation.sha256,
                     "inputs": {"source": [_record(name, data) for name, data in sorted(_SOURCE.items())],
                                "toolchain": tools},
                     "environment": {"LANG": "C", "LC_ALL": "C", "TZ": "UTC",
                                     "SOURCE_DATE_EPOCH": "0"}, "stages": stages})
    _recipe(raw, _sha(raw), version3=True)
    manifest = canonical({"schema": "lunar-zig-musl-support-candidate-seed-recipe-v1",
                          "recipe_sha256": _sha(raw), "target": "x86_64-linux-musl",
                          "seed_executed": False, **_FALSE})
    return ConcreteBuildRecipe(raw, tuple(sorted(_SOURCE.items())), manifest)


def _scan_cache(root: Path, checkpoint: Callable[[], None], budget: dict[str, int]) -> dict[str, dict]:
    """Bound both caches together, refuse every link/special file, follow no FD."""
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    parent = os.open(root.anchor, flags)
    try:
        for part in root.parts[1:-1]:
            child = os.open(part, flags, dir_fd=parent)
            os.close(parent)
            parent = child
        try:
            cache_fd = os.open(root.name, flags, dir_fd=parent)
        except FileNotFoundError:
            # Zig may leave the unused local cache absent. Absence grants no
            # file authority, and the second inventory must still match.
            return {}
        original_root = os.fstat(cache_fd)
        records, pending = {}, [""]
        try:
            while pending:
                checkpoint()
                relative = pending.pop()
                directory = os.dup(cache_fd)
                try:
                    for part in relative.split("/") if relative else ():
                        child = os.open(part, flags, dir_fd=directory)
                        os.close(directory)
                        directory = child
                    with os.scandir(directory) as entries:
                        for entry in entries:
                            checkpoint()
                            budget["entries"] += 1
                            if budget["entries"] > _MAX_CACHE_ENTRIES:
                                _fail("cache_bounds")
                            path = _cache_path((relative + "/" if relative else "") + entry.name)
                            info = entry.stat(follow_symlinks=False)
                            if stat.S_ISDIR(info.st_mode):
                                pending.append(path)
                            elif stat.S_ISREG(info.st_mode):
                                if info.st_size > _MAX_FILE_BYTES:
                                    _fail("cache_bounds")
                                records[path] = _observe(root, path, _MAX_FILE_BYTES, checkpoint=checkpoint)
                                budget["bytes"] += records[path]["size"]
                                if budget["bytes"] > _MAX_CACHE_BYTES:
                                    _fail("cache_bounds")
                            else:
                                _fail("cache_entry")
                finally:
                    os.close(directory)
            repeated_root = os.stat(root.name, dir_fd=parent, follow_symlinks=False)
            if ((original_root.st_dev, original_root.st_ino, original_root.st_mode)
                    != (repeated_root.st_dev, repeated_root.st_ino, repeated_root.st_mode)):
                _fail("cache_drift")
            return records
        finally:
            os.close(cache_fd)
    finally:
        os.close(parent)


def _cache_inventories(roots: dict[str, Path], checkpoint: Callable[[], None]) -> dict[str, dict]:
    budget = {"entries": 0, "bytes": 0}
    return {name: _scan_cache(root, checkpoint, budget) for name, root in roots.items()}


def validate_zig_support_candidate_bundle(
    bundle: ZigSupportCandidateBundle, *, expected_bundle_sha256: str,
    preparation_sha256: str, zig_inventory_sha256: str,
) -> dict:
    """Compare a separately pinned observation and its exact supplied exports.

    Cache/recipe/report digests bind the generator's recorded provenance. This
    detached validator does not reacquire those originals, authenticate the
    generating tool or turn any current filesystem digest into input authority.
    """
    try:
        if (type(bundle) is not ZigSupportCandidateBundle
                or type(bundle.manifest_bytes) is not bytes
                or not 0 < len(bundle.manifest_bytes) <= _MAX_MANIFEST_BYTES
                or not _digest(expected_bundle_sha256) or bundle.sha256 != expected_bundle_sha256
                or not _digest(preparation_sha256) or not _digest(zig_inventory_sha256)
                or type(bundle.files) is not tuple or len(bundle.files) > _MAX_CACHE_ENTRIES):
            _fail("bundle")
        facts = json.loads(bundle.manifest_bytes)
        if (type(facts) is not dict or canonical(facts) != bundle.manifest_bytes
                or set(facts) != {"schema", "target", "preparation_sha256", "seed_recipe_sha256",
                                  "seed_report_sha256", "seed", "objects", "zig_inventory_sha256",
                                  "cache_inventories", "candidates", "seed_executed", *_FALSE}
                or facts["schema"] != _SCHEMA or facts["target"] != "x86_64-linux-musl"
                or facts["preparation_sha256"] != preparation_sha256
                or facts["zig_inventory_sha256"] != zig_inventory_sha256
                or not _digest(facts["seed_recipe_sha256"]) or not _digest(facts["seed_report_sha256"])
                or facts["seed_executed"] is not False
                or any(facts[key] is not value for key, value in _FALSE.items())):
            _fail("bundle")
        objects_raw = canonical(facts["objects"])
        objects = _inventory(objects_raw, _sha(objects_raw))
        seed_raw = canonical([facts["seed"]])
        seed = _inventory(seed_raw, _sha(seed_raw))
        if (set(objects) != _OBJECTS
                or any(row["executable"] or not 0 < row["size"] <= 1024 * 1024 for row in objects.values())
                or set(seed) != {"support/seed"} or seed["support/seed"]["executable"] is not True
                or not 0 < seed["support/seed"]["size"] <= 16 * 1024 * 1024):
            _fail("bundle_outputs")
        caches = facts["cache_inventories"]
        if (type(caches) is not dict or set(caches) != set(_CACHES)
                or any(type(row) is not dict or set(row) != {"sha256", "files", "bytes"}
                       or not _digest(row["sha256"])
                       or type(row["files"]) is not int or not 0 <= row["files"] <= _MAX_CACHE_ENTRIES
                       or type(row["bytes"]) is not int or not 0 <= row["bytes"] <= _MAX_CACHE_BYTES
                       for row in caches.values())
                or sum(row["files"] for row in caches.values()) > _MAX_CACHE_ENTRIES
                or sum(row["bytes"] for row in caches.values()) > _MAX_CACHE_BYTES):
            _fail("bundle_cache")
        if (type(facts["candidates"]) is not list or len(facts["candidates"]) != len(bundle.files)
                or any(type(pair) is not tuple or len(pair) != 2 or type(pair[0]) is not str
                       or type(pair[1]) is not bytes for pair in bundle.files)):
            _fail("bundle_files")
        expected = []
        counts = {name: 0 for name in _CACHES}
        sizes = {name: 0 for name in _CACHES}
        for row, (path, raw) in zip(facts["candidates"], bundle.files, strict=True):
            if (type(row) is not dict
                    or set(row) != {"path", "size", "sha256", "executable", "cache", "cache_path"}
                    or type(row["path"]) is not str or type(row["size"]) is not int
                    or not 0 < row["size"] <= _MAX_FILE_BYTES or not _digest(row["sha256"])
                    or row["executable"] is not False
                    or type(row["cache"]) is not str or row["cache"] not in _CACHES):
                _fail("bundle_candidate")
            relative = _cache_path(row["cache_path"])
            if (path != "candidates/" + row["cache"] + "/" + relative
                    or PurePosixPath(relative).name not in _NAMES or not 0 < len(raw) <= _MAX_FILE_BYTES):
                _fail("bundle_candidate")
            expected.append({**_record(path, raw), "cache": row["cache"], "cache_path": relative})
            counts[row["cache"]] += 1
            sizes[row["cache"]] += len(raw)
        if (expected != facts["candidates"]
                or [path for path, _ in bundle.files] != sorted({path for path, _ in bundle.files})
                or sum(sizes.values()) > _MAX_CACHE_BYTES
                or any(counts[name] > caches[name]["files"] or sizes[name] > caches[name]["bytes"]
                       for name in _CACHES)):
            _fail("bundle_files")
        return facts
    except ZigSupportCandidateError:
        raise
    except (AttributeError, ConcreteRecipeError, ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        _fail("bundle")


def run_zig_support_candidate_preparation(
    preparation: RSIProfilePreparation, *, zig_manifest_bytes: bytes, toolchain_root: Path,
    workspace: Path, deadline: float, interrupted: Callable[[], bool] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> ZigSupportCandidateBundle:
    """Run once, export all finite candidates, and preserve original evidence.

    This trusted-local path does not invoke Podman, execute the generated seed,
    select a support role or construct a direct-link profile. All staging,
    original execution, inventory scans and reads share the caller's deadline.
    """
    if (not _finite(deadline) or deadline <= 0 or not callable(monotonic)
            or interrupted is not None and not callable(interrupted)):
        _fail("control")

    def checkpoint():
        try:
            now = monotonic()
            stop = False if interrupted is None else interrupted()
        except Exception:  # noqa: BLE001 - callbacks cannot leak caller material
            _fail("control")
        if not _finite(now) or type(stop) is not bool:
            _fail("control")
        if stop:
            _fail("interrupted")
        if now >= deadline:
            _fail("deadline")

    checkpoint()
    build = prepare_zig_support_candidate_recipe(preparation, zig_manifest_bytes=zig_manifest_bytes)
    parsed = _recipe(build.recipe_bytes, build.sha256, version3=True)
    root = workspace.absolute()
    tools = toolchain_root.absolute()
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
        checkpoint()
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(raw)
    attempt = root / "attempt"
    report = run_pinned_build_v3(
        preparation, recipe_bytes=build.recipe_bytes, expected_recipe_sha256=build.sha256,
        source_root=source, toolchain_root=toolchain_root, workspace=attempt,
        deadline=deadline, interrupted=interrupted, monotonic=monotonic,
    )
    checkpoint()
    report_raw, outputs = _report_outputs(report, parsed)
    report_pin = _record("report.json", report_raw)
    _read_pin(attempt, report_pin, checkpoint)
    work = attempt / "work"
    for row in outputs:
        _read_pin(work, row, checkpoint)
    by_path = {row["path"]: row for row in outputs}
    if set(by_path) != {*_OBJECTS, "support/seed"}:
        _fail("seed_outputs")
    roots = {name: work / relative for name, relative in _CACHES.items()}
    before = _cache_inventories(roots, checkpoint)
    cache_pins = {}
    for name, rows in before.items():
        raw = canonical(sorted(rows.values(), key=lambda row: row["path"]))
        _write_once(root, "cache-" + name + "-inventory.json", raw, checkpoint)
        cache_pins[name] = {"sha256": _sha(raw), "files": len(rows),
                            "bytes": sum(row["size"] for row in rows.values())}
    seal = root / "sealed"
    seal.mkdir(mode=0o700)
    records, files = [], []
    for name, rows in before.items():
        for relative, row in sorted(rows.items()):
            if PurePosixPath(relative).name not in _NAMES:
                continue
            if row["executable"] or row["size"] <= 0:
                _fail("candidate_record")
            raw = _read_pin(roots[name], row, checkpoint, retain=True)
            path = "candidates/" + name + "/" + relative
            target = seal / path
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            _write_once(target.parent, target.name, raw, checkpoint)
            target.chmod(0o400)
            exported = _record(path, raw)
            _read_pin(seal, exported, checkpoint)
            records.append({**exported, "cache": name, "cache_path": relative})
            files.append((path, raw))
    records.sort(key=lambda row: row["path"])
    files.sort()
    if _cache_inventories(roots, checkpoint) != before:
        _fail("cache_drift")
    for row in outputs:
        _read_pin(work, row, checkpoint)
    _read_pin(attempt, report_pin, checkpoint)
    for role, original in (("source", source), ("toolchain", tools)):
        for row in parsed["inputs"][role]:
            _read_pin(original, row, checkpoint)
            _read_pin(attempt / role, row, checkpoint)
    for row in records:
        _read_pin(seal, {key: row[key] for key in ("path", "size", "sha256", "executable")}, checkpoint)
    for name, rows in before.items():
        raw = canonical(sorted(rows.values(), key=lambda row: row["path"]))
        _read_pin(root, _record("cache-" + name + "-inventory.json", raw), checkpoint)
    manifest = canonical({"schema": _SCHEMA, "target": "x86_64-linux-musl",
                          "preparation_sha256": preparation.sha256,
                          "seed_recipe_sha256": build.sha256, "seed_report_sha256": _sha(report_raw),
                          "seed": by_path["support/seed"],
                          "objects": sorted((by_path[path] for path in _OBJECTS), key=lambda row: row["path"]),
                          "zig_inventory_sha256": _sha(canonical(parsed["inputs"]["toolchain"])),
                          "cache_inventories": cache_pins, "candidates": records,
                          "seed_executed": False, **_FALSE})
    bundle = ZigSupportCandidateBundle(manifest, tuple(files))
    validate_zig_support_candidate_bundle(
        bundle, expected_bundle_sha256=bundle.sha256, preparation_sha256=preparation.sha256,
        zig_inventory_sha256=_sha(canonical(parsed["inputs"]["toolchain"])),
    )
    _write_once(root, "support-candidates.json", manifest, checkpoint)
    _read_pin(root, _record("support-candidates.json", manifest), checkpoint)
    checkpoint()
    return bundle
