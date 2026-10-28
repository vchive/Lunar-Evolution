"""Actual fixed Zig support generation and explicit subsequent link inputs.

The original trusted-tool runner executes the fixed seed once and never executes
its ELF. Generated cache artifacts are observations, not independent acquisition
or immutable-generation authority. Final builds retain their separate custody,
configuration, image and runtime acceptance obligations.
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
from tools.static_python_rsi_fixture.link_dependency_capture import (
    _capture_plan,
    parse_linker_depfile,
    prepare_cpython_link_dependency_recipe,
)
from tools.static_python_rsi_fixture.runtime_closure import FixedRuntimeClosure, canonical

_MAX_CACHE_ENTRIES = 32768
_MAX_SUPPORT_BYTES = 512 * 1024 * 1024
_MAX_SUPPORT_FILE_BYTES = 128 * 1024 * 1024
_SUPPORT_NAMES = frozenset({"crt1.o", "crti.o", "crtn.o", "libc.a", "libcompiler_rt.a"})
_BUNDLE_SCHEMA = "lunar-zig-musl-support-observation-v1"
_RECIPE_SCHEMA = "lunar-cpython-explicit-support-link-recipe-v1"
_SOURCE = {
    "support/probe.c": b'''#if !defined(__linux__) || !defined(__x86_64__)
#error fixed_linux_x86_64_required
#endif
_Static_assert(sizeof(void *) == 8, "pointer_width");
int lunar_support_target_probe(void) { return 0; }
''',
    "support/main.c": b'''#include <math.h>
#include <pthread.h>
extern __int128 lunar_support_div(__int128, __int128);
static void *worker(void *p) { return p; }
int main(void) {
    volatile double v = 0.5;
    volatile __int128 a = 13, b = 3;
    pthread_t t;
    int r = pthread_create(&t, 0, worker, 0);
    if (!r) r = pthread_join(t, 0);
    return r + (int)sin(v) + (int)lunar_support_div(a, b);
}
''',
    "support/div.c": b'''__int128 lunar_support_div(__int128 a, __int128 b) { return a / b; }
''',
}
_FALSE = {"immutable_generation_verified": False, "driver_inputs_verified": False,
          "configured_closure_verified": False, "installation_accepted": False,
          "production_admission": False, "online_publication": False}


class ZigSupportError(RuntimeError):
    """Fixed errors; original attempts and partial artifacts are retained."""


def _fail(reason: str) -> None:
    raise ZigSupportError("zig_support_" + reason)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class ZigSupportBundle:
    """Observed bootstrap products, without build or admission authority."""

    manifest_bytes: bytes
    files: tuple[tuple[str, bytes], ...]

    @property
    def sha256(self) -> str:
        return _sha(self.manifest_bytes)


@dataclass(frozen=True, slots=True)
class ExplicitSupportBuildRecipe:
    recipe_bytes: bytes
    sources: tuple[tuple[str, bytes], ...]
    manifest_bytes: bytes
    toolchain_additions: tuple[tuple[str, bytes], ...]

    @property
    def sha256(self) -> str:
        return _sha(self.recipe_bytes)


def prepare_zig_support_recipe(preparation: RSIProfilePreparation, *,
                               zig_manifest_bytes: bytes) -> ConcreteBuildRecipe:
    """A fixed source/target recipe; caller stages only these three C sources."""
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
                 "-lm", "-lpthread", "-lc", "-Xlinker", "--dependency-file", "-Xlinker",
                 "@work/support/seed.d"],
        "outputs": [{"path": "support/seed", "max_size": 16 * 1024 * 1024, "executable": True},
                    {"path": "support/seed.d", "max_size": 2 * 1024 * 1024, "executable": False}],
    }]})
    raw = canonical({"schema": RECIPE_V3_SCHEMA, "preparation_sha256": preparation.sha256,
                     "inputs": {"source": [_record(name, data) for name, data in sorted(_SOURCE.items())],
                                "toolchain": tools},
                     "environment": {"LANG": "C", "LC_ALL": "C", "TZ": "UTC",
                                     "SOURCE_DATE_EPOCH": "0"}, "stages": stages})
    _recipe(raw, _sha(raw), version3=True)
    manifest = canonical({"schema": "lunar-zig-musl-support-seed-recipe-v1",
                          "recipe_sha256": _sha(raw), "target": "x86_64-linux-musl",
                          "seed_executed": False, **_FALSE})
    return ConcreteBuildRecipe(raw, tuple(sorted(_SOURCE.items())), manifest)


def _cache_inventory(root: Path, checkpoint: Callable[[], None]) -> dict[str, dict]:
    """Bound every entry; never follow a cache link or learn executable authority."""
    pending, records, count, total = [""], {}, 0, 0
    while pending:
        checkpoint()
        relative = pending.pop()
        # Hold each directory through a no-follow FD; os.scandir accepts that FD.
        fd = os.open(root.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            for part in (*root.parts[1:], *(() if not relative else relative.split("/"))):
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                dir_fd=fd)
                os.close(fd)
                fd = child
        except BaseException:
            os.close(fd)
            raise
        try:
            with os.scandir(fd) as entries:
                for entry in entries:
                    checkpoint()
                    count += 1
                    if count > _MAX_CACHE_ENTRIES:
                        _fail("cache_bounds")
                    name = relative + "/" + entry.name if relative else entry.name
                    if (str(PurePosixPath(name)) != name or any(
                            part in {"", ".", ".."} for part in name.split("/"))):
                        _fail("cache_path")
                    info = entry.stat(follow_symlinks=False)
                    if stat.S_ISDIR(info.st_mode):
                        pending.append(name)
                    elif stat.S_ISREG(info.st_mode):
                        total += info.st_size
                        if total > _MAX_SUPPORT_BYTES or info.st_size > _MAX_SUPPORT_FILE_BYTES:
                            _fail("cache_bounds")
                        records[name] = _observe(root, name, _MAX_SUPPORT_FILE_BYTES,
                                                 checkpoint=checkpoint)
                    else:
                        _fail("cache_entry")
        finally:
            os.close(fd)
    return records


def run_zig_support_preparation(
    preparation: RSIProfilePreparation, *, zig_manifest_bytes: bytes, toolchain_root: Path,
    workspace: Path, deadline: float, interrupted: Callable[[], bool] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
) -> ZigSupportBundle:
    """Execute the sole seed link, seal actual support bytes, and retain evidence.

    The absolute deadline spans staging, execution, bounded cache observation and
    readback. This version uses the original local trusted-tool runner; it cannot
    export Podman's ephemeral /tmp cache and supplies no isolated-generation claim.
    """
    if (not _finite(deadline) or deadline <= 0 or not callable(monotonic)
            or (interrupted is not None and not callable(interrupted))):
        _fail("control")

    def checkpoint():
        try:
            now = monotonic()
            stop = False if interrupted is None else interrupted()
        except Exception:  # noqa: BLE001 - no arbitrary callback data in refusals
            _fail("control")
        if not _finite(now) or type(stop) is not bool:
            _fail("control")
        if stop:
            _fail("interrupted")
        if now >= deadline:
            _fail("deadline")

    checkpoint()
    build = prepare_zig_support_recipe(preparation, zig_manifest_bytes=zig_manifest_bytes)
    parsed = _recipe(build.recipe_bytes, build.sha256, version3=True)
    root = workspace.absolute()
    if (root.parent.resolve() != root.parent or not root.parent.is_dir()
            or toolchain_root.absolute().resolve() != toolchain_root.absolute()
            or root == toolchain_root.absolute() or root in toolchain_root.absolute().parents
            or toolchain_root.absolute() in root.parents):
        _fail("workspace")
    try:
        root.mkdir(mode=0o700)
    except OSError:
        _fail("workspace_not_fresh")
    source = root / "seed-source"
    source.mkdir(mode=0o700)
    for name, data in build.sources:
        checkpoint()
        (source / name).parent.mkdir(parents=True, exist_ok=True)
        with (source / name).open("xb") as stream:
            stream.write(data)
    attempt = root / "attempt"
    report = run_pinned_build_v3(
        preparation, recipe_bytes=build.recipe_bytes, expected_recipe_sha256=build.sha256,
        source_root=source, toolchain_root=toolchain_root, workspace=attempt,
        deadline=deadline, interrupted=interrupted, monotonic=monotonic,
    )
    checkpoint()
    report_raw, outputs = _report_outputs(report, parsed)
    report_record = _record("report.json", report_raw)
    _read_pin(attempt, report_record, checkpoint)
    work = attempt / "work"
    retained = {record["path"]: _read_pin(work, record, checkpoint, retain=True)
                for record in outputs}
    target, dependencies = parse_linker_depfile(retained["support/seed.d"])
    if target != str(work / "support/seed"):
        _fail("seed_target")
    cache = work / ".zig-global-cache"
    before = _cache_inventory(cache, checkpoint)
    cache_inventory = canonical(sorted(before.values(), key=lambda r: r["path"]))
    _write_once(root, "cache-inventory.json", cache_inventory, checkpoint)
    explicit = {str(work / name) for name in ("support/probe.o", "support/main.o", "support/div.o")}
    generated, consumed = {}, set()
    for path in dependencies:
        if path in explicit:
            consumed.add(path)
            continue
        prefix = str(cache) + "/"
        if not path.startswith(prefix) or str(PurePosixPath(path)) != path:
            _fail("seed_dependency")
        relative = path[len(prefix):]
        if any(part in {"", ".", ".."} for part in relative.split("/")):
            _fail("seed_dependency")
        name = PurePosixPath(relative).name
        if name not in _SUPPORT_NAMES or name in generated or relative not in before:
            _fail("support_set")
        record = before[relative]
        if record["executable"] or record["size"] <= 0:
            _fail("support_record")
        raw = _read_pin(cache, record, checkpoint, retain=True)
        generated[name] = (relative, raw)
    if set(generated) != _SUPPORT_NAMES or consumed != explicit:
        _fail("support_set")
    seal = root / "sealed"
    seal.mkdir(mode=0o700)
    files, records = [], []
    for name, (relative, raw) in sorted(generated.items()):
        checkpoint()
        destination = "lunar-support/" + name
        (seal / "lunar-support").mkdir(exist_ok=True, mode=0o700)
        _write_once(seal / "lunar-support", name, raw, checkpoint)
        (seal / destination).chmod(0o400)
        record = _record(destination, raw)
        _read_pin(seal, record, checkpoint)
        records.append({**record, "generated_cache_path": relative})
        files.append((destination, raw))
    if _cache_inventory(cache, checkpoint) != before:
        _fail("cache_drift")
    for record in outputs:
        _read_pin(work, record, checkpoint)
    _read_pin(attempt, report_record, checkpoint)
    for role, original in (("source", source), ("toolchain", toolchain_root.absolute())):
        for record in parsed["inputs"][role]:
            _read_pin(original, record, checkpoint)
            _read_pin(attempt / role, record, checkpoint)
    for record in records:
        _read_pin(seal, record, checkpoint)
    _read_pin(root, _record("cache-inventory.json", cache_inventory), checkpoint)
    manifest = canonical({"schema": _BUNDLE_SCHEMA, "target": "x86_64-linux-musl",
                          "preparation_sha256": preparation.sha256,
                          "seed_recipe_sha256": build.sha256, "seed_report_sha256": _sha(report_raw),
                          "seed_depfile_sha256": _sha(retained["support/seed.d"]),
                          "zig_inventory_sha256": _sha(canonical(parsed["inputs"]["toolchain"])),
                          "cache_inventory_sha256": _sha(cache_inventory),
                          "support": records, "seed_executed": False, **_FALSE})
    _write_once(root, "support-observation.json", manifest, checkpoint)
    checkpoint()
    return ZigSupportBundle(manifest, tuple(files))


def _bundle(bundle: ZigSupportBundle, preparation_sha: str, tools: list[dict]) -> dict:
    try:
        if (type(bundle) is not ZigSupportBundle or type(bundle.manifest_bytes) is not bytes
                or not 0 < len(bundle.manifest_bytes) <= 32768 or type(bundle.files) is not tuple
                or len(bundle.files) != len(_SUPPORT_NAMES)):
            _fail("bundle")
    except AttributeError:
        # Exact-type instances created without initialized frozen slots are
        # still malformed input, not an exception-data or authority route.
        _fail("bundle")
    try:
        facts = json.loads(bundle.manifest_bytes)
        expected = {"schema", "target", "preparation_sha256", "seed_recipe_sha256", "seed_report_sha256",
                    "seed_depfile_sha256", "zig_inventory_sha256", "cache_inventory_sha256", "support",
                    "seed_executed", *_FALSE}
        if (type(facts) is not dict or set(facts) != expected
                or canonical(facts) != bundle.manifest_bytes or facts["schema"] != _BUNDLE_SCHEMA
                or facts["target"] != "x86_64-linux-musl" or facts["preparation_sha256"] != preparation_sha
                or facts["zig_inventory_sha256"] != _sha(canonical(tools))
                or facts["seed_executed"] is not False
                or any(facts[key] is not value for key, value in _FALSE.items())):
            _fail("bundle")
        for key in ("seed_recipe_sha256", "seed_report_sha256", "seed_depfile_sha256", "cache_inventory_sha256"):
            value = facts[key]
            if type(value) is not str or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
                _fail("bundle")
        if any(type(pair) is not tuple or len(pair) != 2 or type(pair[0]) is not str
               or type(pair[1]) is not bytes for pair in bundle.files):
            _fail("bundle")
        files = dict(bundle.files)
        if (len(files) != len(bundle.files) or set(files) != {"lunar-support/" + name for name in _SUPPORT_NAMES}
                or len(facts["support"]) != len(_SUPPORT_NAMES)):
            _fail("bundle")
        expected_records = []
        for item in facts["support"]:
            if type(item) is not dict or set(item) != {"path", "size", "sha256", "executable", "generated_cache_path"}:
                _fail("bundle")
            path, cache_path = item["path"], item["generated_cache_path"]
            if (type(item["size"]) is not int or item["executable"] is not False
                    or type(item["sha256"]) is not str or len(item["sha256"]) != 64
                    or any(c not in "0123456789abcdef" for c in item["sha256"])):
                _fail("bundle")
            if (type(path) is not str or path not in files or type(files[path]) is not bytes
                    or not 0 < len(files[path]) <= _MAX_SUPPORT_FILE_BYTES
                    or type(cache_path) is not str or str(PurePosixPath(cache_path)) != cache_path
                    or cache_path.startswith("/") or any(p in {"", ".", ".."} for p in cache_path.split("/"))
                    or PurePosixPath(cache_path).name != PurePosixPath(path).name):
                _fail("bundle")
            expected_records.append({**_record(path, files[path]), "generated_cache_path": cache_path})
        if (expected_records != facts["support"]
                or [r["path"] for r in facts["support"]] != sorted(files)
                or tuple(files) != tuple(sorted(files))
                or sum(len(raw) for raw in files.values()) > _MAX_SUPPORT_BYTES):
            _fail("bundle")
        return facts
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        _fail("bundle")


def prepare_cpython_explicit_support_recipe(
    preparation: RSIProfilePreparation, *, support_bundle: ZigSupportBundle,
    source_inventory_bytes: bytes, expected_source_inventory_sha256: str, zig_manifest_bytes: bytes,
    configuration_header: bytes, expected_configuration_sha256: str,
    runtime_closure: FixedRuntimeClosure | None = None,
    producer_lifecycle_profile: str | None = None,
) -> ExplicitSupportBuildRecipe:
    """Use observed prior bootstrap artifacts in both real subsequent links.

    Caller stages returned toolchain additions beside the same pinned Zig tree.
    They are output-derived build inputs; their digests do not approve generation
    custody. Actual consumer and Podman opt-in still verify their snapshot bytes.
    """
    base = prepare_cpython_link_dependency_recipe(
        preparation, source_inventory_bytes=source_inventory_bytes,
        expected_source_inventory_sha256=expected_source_inventory_sha256,
        zig_manifest_bytes=zig_manifest_bytes, configuration_header=configuration_header,
        expected_configuration_sha256=expected_configuration_sha256, runtime_closure=runtime_closure,
        **({"producer_lifecycle_profile": producer_lifecycle_profile}
           if producer_lifecycle_profile is not None else {}),
    )
    wire = _recipe(base.recipe_bytes, base.sha256, version3=True)
    _bundle(support_bundle, preparation.sha256, wire["inputs"]["toolchain"])
    files = dict(support_bundle.files)
    if any(item["path"] in files for item in wire["inputs"]["toolchain"]):
        _fail("support_overlap")
    wire["inputs"]["toolchain"] += [_record(path, raw) for path, raw in sorted(files.items())]
    wire["inputs"]["toolchain"].sort(key=lambda row: row["path"])
    for stage in wire["stages"]:
        for command in stage["commands"]:
            argv = command["argv"]
            if argv[:2] != ["@toolchain/zig", "cc"] or "-c" in argv:
                continue
            end = argv.index("-lm")
            target_index = argv.index("-o") + 1
            command["argv"] = [*argv[:target_index - 1], "-nostdlib", "-o", argv[target_index],
                               "@toolchain/lunar-support/crt1.o", "@toolchain/lunar-support/crti.o",
                               *argv[target_index + 1:end], "-Xlinker", "--start-group",
                               "@toolchain/lunar-support/libc.a", "@toolchain/lunar-support/libcompiler_rt.a",
                               "-Xlinker", "--end-group", "@toolchain/lunar-support/crtn.o", *argv[end + 3:]]
    raw = canonical(wire)
    _recipe(raw, _sha(raw), version3=True)
    compilations, links = _capture_plan(wire, instrumented=True)
    manifest = json.loads(base.manifest_bytes)
    manifest.update(schema=_RECIPE_SCHEMA, recipe_sha256=_sha(raw), base_recipe_sha256=base.sha256,
                    base_manifest_sha256=_sha(base.manifest_bytes), compilations=compilations,
                    links=links, support_bundle_sha256=support_bundle.sha256)
    return ExplicitSupportBuildRecipe(raw, base.sources, canonical(manifest), support_bundle.files)
