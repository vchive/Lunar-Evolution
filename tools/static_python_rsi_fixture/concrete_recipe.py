"""Concrete Zig/musl CPython object, same-source freezer and static-link recipe.

Generation is pure and never runs configure, a host Python, compiler or target.
It consumes independently pinned configured-header/source inputs. The configure
stage compiles a configuration probe; it does not fabricate an Autoconf result.
Installation/custody, ELF and sealed startup require subsequent acceptance.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from lunar_evolution.static_python_fixed_live_modules import (
    FIXED_LIVE_COLLECTOR_SOURCE_BYTES,
    FIXED_LIVE_RUNTIME_SOURCE_BYTES,
    FIXED_LIVE_RUNTIME_SOURCE_SHA256,
    FIXED_LIVE_SINK_LAUNCHER_PATH,
    FIXED_LIVE_SINK_LAUNCHER_SOURCE_BYTES,
    FIXED_LIVE_SINK_LAUNCHER_SOURCE_SHA256,
    compose_fixed_python_live_main,
)
from lunar_evolution.static_python_producer_completion_source import (
    COMPLETION_ENTRYPOINT_PINS,
    COMPLETION_LAUNCHER_PATH,
    FIXED_PRODUCER_COMPLETION_LAUNCHER_SOURCE_BYTES,
    FIXED_PRODUCER_COMPLETION_LAUNCHER_SOURCE_SHA256,
    FIXED_PRODUCER_LIFECYCLE_PROFILE,
    compose_fixed_producer_completion_main,
)
from lunar_evolution.static_python_producer_envelope_source import (
    ENVELOPE_ENTRYPOINT_PINS,
    ENVELOPE_LAUNCHER_PATH,
    FIXED_PRODUCER_ENVELOPE_PROFILE,
    compose_fixed_producer_envelope_main,
)
from lunar_evolution.static_python_producer_envelope_source import (
    SOURCE_PINS as ENVELOPE_SOURCE_PINS,
)
from tools.static_python_fixture.profile import ALIASES, CORE_BUILTINS, STATIC_ADDITIONS
from tools.static_python_fixture.tables import emit_static_python_tables
from tools.static_python_rsi_fixture.build_driver import _preparation_wire
from tools.static_python_rsi_fixture.configuration_review_v2 import (
    bind_selected_cpython_configuration as bind_reviewed_cpython_configuration,
)
from tools.static_python_rsi_fixture.configuration_review_v2 import selects_v2_review
from tools.static_python_rsi_fixture.execution_backend import RECIPE_V3_SCHEMA, _recipe
from tools.static_python_rsi_fixture.installation_profile import RSIProfilePreparation
from tools.static_python_rsi_fixture.runtime_closure import (
    _POSIXSUBPROCESS_INPUTS,
    _RUNTIME_ALIASES,
    _SOCKET_INPUTS,
    FixedRuntimeClosure,
    canonical,
)

ZIG_MANIFEST_BYTES = 3_926_082
ZIG_MANIFEST_SHA256 = "b988925aa63b672f26871f06b3e9585ced9f16154b41fcf22ca7fb3a9bc93b90"
ZIG_ARCHIVE_SHA256 = "70e49664a74374b48b51e6f3fdfbf437f6395d42509050588bd49abe52ba3d00"
ZIG_ROOT = "zig-x86_64-linux-0.16.0"
MAX_SOURCE_INVENTORY_BYTES = 4 * 1024 * 1024
MAX_CONFIGURATION_BYTES = 128 * 1024


class ConcreteRecipeError(ValueError):
    """Fixed reason without source content or caller paths."""


def _fail(code: str) -> None:
    raise ConcreteRecipeError("static_python_concrete_recipe_" + code)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _pin(raw: bytes, expected: str, maximum: int) -> None:
    if (type(raw) is not bytes or not 0 < len(raw) <= maximum
            or type(expected) is not str or _sha(raw) != expected):
        _fail("input_pin_mismatch")


def _path(path: object) -> str:
    if (type(path) is not str or not 0 < len(path) <= 512
            or any(p in {"", ".", ".."} for p in path.split("/"))
            or any(ord(c) < 32 or ord(c) > 126 or c in "\\:" for c in path)):
        _fail("path_invalid")
    return path


def _pairs(items: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in items:
        if key in result:
            _fail("duplicate_key")
        result[key] = value
    return result


def _inventory(raw: bytes, expected: str) -> dict[str, dict]:
    _pin(raw, expected, MAX_SOURCE_INVENTORY_BYTES)
    try:
        records = json.loads(raw, object_pairs_hook=_pairs)
        if canonical(records) != raw or type(records) is not list or not 0 < len(records) <= 16384:
            _fail("inventory_invalid")
        result = {}
        for item in records:
            if (type(item) is not dict or set(item) != {"path", "size", "sha256", "executable"}
                    or type(item["size"]) is not int or not 0 <= item["size"] <= 4 * 1024**3
                    or type(item["executable"]) is not bool
                    or type(item["sha256"]) is not str or len(item["sha256"]) != 64
                    or any(c not in "0123456789abcdef" for c in item["sha256"])):
                _fail("inventory_record_invalid")
            path = _path(item["path"])
            if path in result:
                _fail("inventory_duplicate")
            result[path] = item.copy()
        if list(result) != sorted(result):
            _fail("inventory_order_invalid")
        return result
    except ConcreteRecipeError:
        raise
    except (ValueError, TypeError, RecursionError, UnicodeError):
        _fail("inventory_invalid")


def complete_zig_inventory(manifest_bytes: bytes) -> list[dict]:
    """Project every regular file from the independently fixed archive manifest.

    No caller subset, discovered executable list or toolchain truncation route is
    accepted. The pinned archive includes all bundled musl, CRT and Zig sources.
    """
    _pin(manifest_bytes, ZIG_MANIFEST_SHA256, ZIG_MANIFEST_BYTES)
    if len(manifest_bytes) != ZIG_MANIFEST_BYTES:
        _fail("zig_manifest_invalid")
    facts = json.loads(manifest_bytes, object_pairs_hook=_pairs)
    if (facts.get("root") != ZIG_ROOT or facts.get("archive") != "zig"
            or facts.get("schema") != "lunar-static-python-extraction-manifest-v1"
            or facts.get("archive_sha256") != ZIG_ARCHIVE_SHA256):
        _fail("zig_manifest_invalid")
    result = []
    for item in facts["members"]:
        if item["kind"] == "directory":
            continue
        if item["kind"] != "file" or not item["path"].startswith(ZIG_ROOT + "/"):
            _fail("zig_member_invalid")
        path = _path(item["path"][len(ZIG_ROOT) + 1:])
        result.append({"path": path, "size": item["size"], "sha256": item["sha256"],
                       "executable": bool(item["mode"] & 0o111)})
    result.sort(key=lambda r: r["path"])
    if (len(result) != 19546 or sum(r["size"] for r in result) != 357913169
            or [r["path"] for r in result if r["executable"]] != ["zig"]):
        _fail("zig_inventory_incomplete")
    return result


@dataclass(frozen=True, slots=True)
class ConcreteBuildRecipe:
    recipe_bytes: bytes
    sources: tuple[tuple[str, bytes], ...]
    manifest_bytes: bytes

    @property
    def sha256(self) -> str:
        return _sha(self.recipe_bytes)


def _record(path: str, raw: bytes) -> dict:
    return {"path": path, "size": len(raw), "sha256": _sha(raw), "executable": False}


def _command(argv: list[str], output: str, *, executable: bool = False) -> dict:
    return {"argv": argv, "outputs": [{"path": output, "max_size": 128 * 1024**2,
                                       "executable": executable}]}


def _completion_sources(solver: str, facts: dict, sources: dict[str, bytes]) -> None:
    """Verify the explicitly selected successor without reading or executing source."""
    if FIXED_LIVE_SINK_LAUNCHER_PATH in sources or ENVELOPE_LAUNCHER_PATH in sources:
        _fail("completion_profile_mismatch")
    pins = {
        COMPLETION_LAUNCHER_PATH: (
            FIXED_PRODUCER_COMPLETION_LAUNCHER_SOURCE_BYTES,
            FIXED_PRODUCER_COMPLETION_LAUNCHER_SOURCE_SHA256,
        ),
        "producer/" + solver + "/lunar_fixed.py": COMPLETION_ENTRYPOINT_PINS[solver],
    }
    for path, (size, digest) in pins.items():
        raw = sources.get(path)
        if type(raw) is not bytes or len(raw) != size or _sha(raw) != digest:
            _fail("completion_source_drift")
    try:
        tasks = facts["frozen"]
        for name, path in (("_lunar_static_main", "runtime/frozen_main.py"),
                           (solver + ".lunar_fixed", "producer/" + solver + "/lunar_fixed.py")):
            selected = [task for task in tasks if task["name"] == name]
            if (len(selected) != 1 or selected[0]["source"] != path
                    or selected[0]["generator_id"] != name or selected[0]["package"] is not False):
                _fail("completion_source_drift")
        runtime_aliases = facts.get("runtime_module_aliases", [])
        for alias in runtime_aliases:
            name = alias["name"]
            if alias != {"name": name, "source_module": _RUNTIME_ALIASES[name],
                         "parent_module": name.rpartition(".")[0]}:
                _fail("completion_source_drift")
        arguments = {
            "frozen_names": tuple(sorted(task["name"] for task in tasks)),
            "builtin_names": tuple(sorted(set(CORE_BUILTINS) | set(STATIC_ADDITIONS) | {
                unit["module"] for unit in facts["native_units"] if unit["module"] != "sqlite-library"
            })),
            "aliases": tuple(sorted((*((target, name) for name, target in ALIASES),
                                     *((item["name"], item["source_module"]) for item in runtime_aliases)))),
            "frozen_packages": tuple(sorted(task["name"] for task in tasks if task["package"])),
        }
        main = sources["runtime/frozen_main.py"]
        separator = f"\n_LUNAR_LIVE_RUNTIME_SHA256 = {FIXED_LIVE_RUNTIME_SOURCE_SHA256!r}\n\n".encode("ascii")
        offset = FIXED_LIVE_COLLECTOR_SOURCE_BYTES + len(separator) + FIXED_LIVE_RUNTIME_SOURCE_BYTES
        if type(main) is not bytes or not offset < len(main) <= 64 * 1024:
            _fail("completion_source_drift")
        startup = compose_fixed_python_live_main(
            solver, **arguments, collector_source=main[-offset:][:FIXED_LIVE_COLLECTOR_SOURCE_BYTES],
            runtime_observation_source=main[-FIXED_LIVE_RUNTIME_SOURCE_BYTES:],
        )
        expected = compose_fixed_producer_completion_main(
            solver, startup_main_source=startup, **arguments, profile=FIXED_PRODUCER_LIFECYCLE_PROFILE,
        )
        if main != expected:
            _fail("completion_source_drift")
    except (KeyError, TypeError, ValueError):
        _fail("completion_source_drift")


def _envelope_sources(solver: str, facts: dict, sources: dict[str, bytes]) -> None:
    """Validate only v2 bytes; a v1 image cannot select v2 through metadata."""
    if FIXED_LIVE_SINK_LAUNCHER_PATH in sources or COMPLETION_LAUNCHER_PATH in sources:
        _fail("envelope_profile_mismatch")
    pins = {
        ENVELOPE_LAUNCHER_PATH: ENVELOPE_SOURCE_PINS[
            "tools/static_python_rsi_fixture/assets/launcher_producer_envelope.c"
        ],
        "producer/" + solver + "/lunar_fixed.py": ENVELOPE_ENTRYPOINT_PINS[solver],
    }
    for path, (size, digest) in pins.items():
        raw = sources.get(path)
        if type(raw) is not bytes or len(raw) != size or _sha(raw) != digest:
            _fail("envelope_source_drift")
    try:
        tasks = facts["frozen"]
        for name, path in (("_lunar_static_main", "runtime/frozen_main.py"),
                           (solver + ".lunar_fixed", "producer/" + solver + "/lunar_fixed.py")):
            selected = [task for task in tasks if task["name"] == name]
            if (len(selected) != 1 or selected[0]["source"] != path
                    or selected[0]["generator_id"] != name or selected[0]["package"] is not False):
                _fail("envelope_source_drift")
        runtime_aliases = facts.get("runtime_module_aliases", [])
        for alias in runtime_aliases:
            name = alias["name"]
            if alias != {"name": name, "source_module": _RUNTIME_ALIASES[name],
                         "parent_module": name.rpartition(".")[0]}:
                _fail("envelope_source_drift")
        arguments = {
            "frozen_names": tuple(sorted(task["name"] for task in tasks)),
            "builtin_names": tuple(sorted(set(CORE_BUILTINS) | set(STATIC_ADDITIONS) | {
                unit["module"] for unit in facts["native_units"] if unit["module"] != "sqlite-library"
            })),
            "aliases": tuple(sorted((*((target, name) for name, target in ALIASES),
                                     *((item["name"], item["source_module"]) for item in runtime_aliases)))),
            "frozen_packages": tuple(sorted(task["name"] for task in tasks if task["package"])),
        }
        main = sources["runtime/frozen_main.py"]
        separator = f"\n_LUNAR_LIVE_RUNTIME_SHA256 = {FIXED_LIVE_RUNTIME_SOURCE_SHA256!r}\n\n".encode("ascii")
        offset = FIXED_LIVE_COLLECTOR_SOURCE_BYTES + len(separator) + FIXED_LIVE_RUNTIME_SOURCE_BYTES
        if type(main) is not bytes or not offset < len(main) <= 64 * 1024:
            _fail("envelope_source_drift")
        startup = compose_fixed_python_live_main(
            solver, **arguments, collector_source=main[-offset:][:FIXED_LIVE_COLLECTOR_SOURCE_BYTES],
            runtime_observation_source=main[-FIXED_LIVE_RUNTIME_SOURCE_BYTES:],
        )
        expected = compose_fixed_producer_envelope_main(
            solver, startup_main_source=startup, **arguments, profile=FIXED_PRODUCER_ENVELOPE_PROFILE,
        )
        if main != expected:
            _fail("envelope_source_drift")
    except (KeyError, TypeError, ValueError):
        _fail("envelope_source_drift")


def prepare_cpython_build_recipe(
    preparation: RSIProfilePreparation, *, source_inventory_bytes: bytes,
    expected_source_inventory_sha256: str, zig_manifest_bytes: bytes,
    configuration_header: bytes, expected_configuration_sha256: str,
    runtime_closure: FixedRuntimeClosure | None = None,
    producer_lifecycle_profile: str | None = None,
    configuration_outputs: tuple[tuple[str, bytes], ...] | None = None,
    review_manifest_bytes: bytes | None = None,
    expected_review_manifest_sha256: str | None = None,
) -> ConcreteBuildRecipe:
    """Emit executable commands; caller stages returned sources in a fresh root.

    The caller provides an independently pinned, reviewed pyconfig.h generated
    for this exact CPython/Zig/musl target. No host config, interpreter freezer,
    configure script, make or ambient library is substituted. The recipe carries
    the original preparation as a base binding; new solver tables/main are an
    explicit source-profile version and cannot pass legacy runtime DTO gates.
    """
    review_selected = (configuration_outputs is not None, review_manifest_bytes is not None,
                       expected_review_manifest_sha256 is not None)
    if any(review_selected) and not all(review_selected):
        _fail("configuration_review_incomplete")
    v2_review_selected = all(review_selected) and selects_v2_review(
        review_manifest_bytes=review_manifest_bytes,
        expected_review_manifest_sha256=expected_review_manifest_sha256,
    )
    if (producer_lifecycle_profile is not None
            and (type(producer_lifecycle_profile) is not str
                 or producer_lifecycle_profile not in {FIXED_PRODUCER_LIFECYCLE_PROFILE,
                                                       FIXED_PRODUCER_ENVELOPE_PROFILE}
                 or runtime_closure is None)):
        _fail("completion_profile_invalid")
    plan = _preparation_wire(preparation)["candidate_build_inputs"]
    inventory = _inventory(source_inventory_bytes, expected_source_inventory_sha256)
    zig = complete_zig_inventory(zig_manifest_bytes)
    _pin(configuration_header, expected_configuration_sha256, MAX_CONFIGURATION_BYTES)
    sources = {"configuration/pyconfig.h": configuration_header}
    baseline_metadata = emit_static_python_tables()["Python/stdlib_module_names.h"]
    metadata_pin = next(r for r in plan["generated_sources"]
                        if r["path"] == "generated-sources/Python/stdlib_module_names.h")
    if (len(baseline_metadata) != metadata_pin["source_size"]
            or _sha(baseline_metadata) != metadata_pin["sha256"]):
        _fail("baseline_metadata_drift")
    sources["Python/stdlib_module_names.h"] = baseline_metadata
    units = [dict(u) for u in plan["shared_units"]]
    freezer = [dict(u) for u in plan["freezer_units"]]
    target = [dict(u) for u in plan["target_units"]]
    tasks = [dict(t) for t in plan["freeze_tasks"]]
    solver = "marker-fixture"
    closure_sha = None
    native = []
    if runtime_closure is not None:
        if (type(runtime_closure) is not FixedRuntimeClosure
                or type(runtime_closure.wire_bytes) is not bytes
                or not 0 < len(runtime_closure.wire_bytes) <= 2 * 1024**2
                or type(runtime_closure.sources) is not tuple
                or not 0 < len(runtime_closure.sources) <= 512):
            _fail("runtime_closure_invalid")
        facts = json.loads(runtime_closure.wire_bytes, object_pairs_hook=_pairs)
        if (canonical(facts) != runtime_closure.wire_bytes
                or facts.get("schema") != "lunar-fixed-python-runtime-source-closure-v1"
                or facts.get("solver") not in {"openevolve", "shinka"}
                or facts.get("production_admission") is not False
                or facts.get("runtime_execution_performed") is not False):
            _fail("runtime_closure_invalid")
        solver = facts["solver"]
        closure_sha = runtime_closure.sha256
        sources.update(runtime_closure.sources)
        if len(dict(runtime_closure.sources)) != len(runtime_closure.sources):
            _fail("runtime_sources_duplicate")
        if {r["path"] for r in facts["sources"]} != set(dict(runtime_closure.sources)):
            _fail("runtime_source_inventory_invalid")
        for record in facts["sources"]:
            raw = sources.get(record["path"])
            if (type(raw) is not bytes or len(raw) != record["size"]
                    or _sha(raw) != record["sha256"]):
                _fail("runtime_source_drift")
        tasks = facts["frozen"]
        native = facts["native_units"]
        completion_selected = producer_lifecycle_profile == FIXED_PRODUCER_LIFECYCLE_PROFILE
        envelope_selected = producer_lifecycle_profile == FIXED_PRODUCER_ENVELOPE_PROFILE
        if completion_selected:
            _completion_sources(solver, facts, sources)
        elif envelope_selected:
            _envelope_sources(solver, facts, sources)
        elif (COMPLETION_LAUNCHER_PATH in sources
              or (len(sources.get("producer/" + solver + "/lunar_fixed.py", b"")),
                  _sha(sources.get("producer/" + solver + "/lunar_fixed.py", b"")))
              == COMPLETION_ENTRYPOINT_PINS[solver]):
            _fail("completion_profile_required")
        elif (ENVELOPE_LAUNCHER_PATH in sources
              or (len(sources.get("producer/" + solver + "/lunar_fixed.py", b"")),
                  _sha(sources.get("producer/" + solver + "/lunar_fixed.py", b"")))
              == ENVELOPE_ENTRYPOINT_PINS[solver]):
            _fail("envelope_profile_required")
        posix_units = [unit for unit in native if unit["module"] == "_posixsubprocess"]
        if posix_units:
            size, digest = _POSIXSUBPROCESS_INPUTS["Modules/_posixsubprocess.c"]
            if (len(posix_units) != 1
                    or posix_units[0] != {"module": "_posixsubprocess", "source": "Modules/_posixsubprocess.c",
                                          "object": "Modules/_posixsubprocess.o", "source_size": size,
                                          "source_sha256": digest, "extra_flags": []}):
                _fail("posixsubprocess_input_pin_mismatch")
            for path, (size, digest) in _POSIXSUBPROCESS_INPUTS.items():
                entry = inventory.get(path)
                if (entry is None or entry["size"] != size or entry["sha256"] != digest
                        or entry["executable"] is not False):
                    _fail("posixsubprocess_input_pin_mismatch")
        socket_units = [unit for unit in native if unit["module"] == "_socket"]
        if socket_units:
            size, digest = _SOCKET_INPUTS["Modules/socketmodule.c"]
            if (len(socket_units) != 1
                    or socket_units[0] != {"module": "_socket", "source": "Modules/socketmodule.c",
                                           "object": "Modules/socketmodule.o", "source_size": size,
                                           "source_sha256": digest, "extra_flags": []}):
                _fail("socket_input_pin_mismatch")
            for path, (size, digest) in _SOCKET_INPUTS.items():
                entry = inventory.get(path)
                if (entry is None or entry["size"] != size or entry["sha256"] != digest
                        or entry["executable"] is not False):
                    _fail("socket_input_pin_mismatch")
        for unit in units + target:
            if (unit["source"] == "tools/static_python_rsi_fixture/assets/launcher.c"
                    and envelope_selected):
                unit["source"] = ENVELOPE_LAUNCHER_PATH
            elif (unit["source"] == "tools/static_python_rsi_fixture/assets/launcher.c"
                    and completion_selected):
                unit["source"] = COMPLETION_LAUNCHER_PATH
            elif (unit["source"] == "tools/static_python_rsi_fixture/assets/launcher.c"
                    and FIXED_LIVE_SINK_LAUNCHER_PATH in sources):
                selected_launcher = sources[FIXED_LIVE_SINK_LAUNCHER_PATH]
                if (len(selected_launcher) != FIXED_LIVE_SINK_LAUNCHER_SOURCE_BYTES
                        or _sha(selected_launcher) != FIXED_LIVE_SINK_LAUNCHER_SOURCE_SHA256):
                    _fail("live_sink_launcher_source_drift")
                unit["source"] = FIXED_LIVE_SINK_LAUNCHER_PATH
            if unit["source"] == "generated-sources/Modules/config.c":
                unit["source"] = "runtime/Modules/config.c"
            elif unit["source"] == "generated-sources/Python/frozen.c":
                unit["source"] = "runtime/Python/frozen.c"
            if unit["source"] in sources:
                unit["source_size"] = len(sources[unit["source"]])
                unit["source_sha256"] = _sha(sources[unit["source"]])
        # sysmodule.c includes this header using a quoted source-local include.
        # Overlay its actual source path, rather than trusting -I precedence.
        sources["Python/stdlib_module_names.h"] = sources["runtime/Python/stdlib_module_names.h"]
        sources["runtime/closure.json"] = runtime_closure.wire_bytes
    probe = b'''#include "Python.h"
#include <stdint.h>
#if !defined(__linux__) || !defined(__x86_64__)
#error fixed_linux_x86_64_required
#endif
#ifdef Py_ENABLE_SHARED
#error shared_python_refused
#endif
#ifdef HAVE_DLOPEN
#error dynamic_loader_refused
#endif
_Static_assert(sizeof(void *) == 8, "pointer_width");
_Static_assert(PY_MAJOR_VERSION == 3 && PY_MINOR_VERSION == 13 && PY_MICRO_VERSION == 12,
               "cpython_version");
int lunar_configuration_probe(void) { return 0; }
'''
    if solver == "shinka":
        probe += b'''#include "sqlite3.h"
#if SQLITE_VERSION_NUMBER < 3035000
#error sqlite_serialization_version_required
#endif
#ifdef SQLITE_OMIT_DESERIALIZE
#error sqlite_serialization_required
#endif
#ifdef PY_SQLITE_ENABLE_LOAD_EXTENSION
#error sqlite_extension_loading_refused
#endif
void *lunar_sqlite_serialization_probe(void) { return (void *)&sqlite3_serialize; }
'''
    sources["configuration/probe.c"] = probe
    for path, raw in sources.items():
        _path(path)
        if type(raw) is not bytes or len(raw) > 16 * 1024**2:
            _fail("generated_source_invalid")
        inventory[path] = _record(path, raw)
    for unit in units + freezer + target + native:
        path = unit["source"]
        if (path not in inventory or inventory[path]["size"] != unit["source_size"]
                or inventory[path]["sha256"] != unit["source_sha256"]):
            _fail("translation_unit_pin_mismatch")
    for task in tasks:
        path = task["source"]
        if (path not in inventory or inventory[path]["size"] != task["source_size"]
                or inventory[path]["sha256"] != task["source_sha256"]):
            _fail("freezer_source_pin_mismatch")
    compiler = ["@toolchain/zig", "cc", "-target", "x86_64-linux-musl",
                "-std=c11", "-O2", "-g0",
                "-fno-strict-overflow", "-fno-strict-aliasing", "-fno-common",
                "-fvisibility=hidden", "-Werror=implicit-function-declaration",
                "-D_GNU_SOURCE", "-DNDEBUG",
                "-DPy_BUILD_CORE", "-I", "@source-dir/configuration",
                "-I", "@source-dir/Include", "-I", "@source-dir/Include/internal",
                "-I", "@source-dir/Include/internal/mimalloc"]
    if v2_review_selected:
        compiler += ["-I", "@source-dir/Objects", "-I", "@source-dir/Python"]
    if native:
        compiler += ["-I", "@source-dir/Modules/_hacl/include", "-I", "@source-dir/Modules/_hacl"]
    if solver == "shinka":
        compiler += ["-I", "@source-dir/sqlite"]
    configure_commands = [_command(compiler + ["-c", "@source/configuration/probe.c", "-o",
                                                "@work/configuration/probe.o"],
                                    "configuration/probe.o")]
    freeze_commands = []
    for unit in units + native + freezer:
        flags = list(unit.get("extra_flags", []))
        if unit.get("compile_role") == "builtin" or "module" in unit:
            flags += ["-DPy_BUILD_CORE_BUILTIN"]
        if unit["source"] == "Modules/getbuildinfo.c":
            flags += ['-DDATE="Jan 01 1970"', '-DTIME="00:00:00"', '-DGITVERSION=""',
                      '-DGITTAG=""', '-DGITBRANCH=""']
        obj = "objects/" + unit["object"]
        freeze_commands.append(_command(compiler + flags + ["-c", "@source/" + unit["source"],
                                                            "-o", "@work/" + obj], obj))
    shared_objects = ["@work/objects/" + u["object"] for u in units + native]
    freezer_objects = shared_objects + ["@work/objects/" + u["object"] for u in freezer]
    freeze_commands.append(_command(
        ["@toolchain/zig", "cc", "-target", "x86_64-linux-musl", "-static", "-o", "@work/bin/lunar-freeze-module",
         *freezer_objects, "-lm", "-lpthread", "-lc"], "bin/lunar-freeze-module", executable=True))
    for task in tasks:
        freeze_commands.append(_command(
            ["@work/bin/lunar-freeze-module", task["generator_id"],
             "@source/" + task["source"], "@work/" + task["output"]], task["output"]))
    compile_commands = []
    for unit in target:
        obj = "objects/" + unit["object"]
        compile_commands.append(_command(
            compiler + ["-I", "@source-dir/assets", "-I", "@work-dir/generated-sources/Python",
                        "-c", "@source/" + unit["source"], "-o", "@work/" + obj], obj))
    library = "libraries/liblunarpython.a"
    executable = "bin/lunar-" + solver
    link_commands = [
        _command(["@toolchain/zig", "ar", "rcsD", "@work/" + library, *shared_objects], library),
        _command(["@toolchain/zig", "cc", "-target", "x86_64-linux-musl", "-static", "-o", "@work/" + executable,
                  *("@work/objects/" + u["object"] for u in target), "@work/" + library,
                  "-lm", "-lpthread", "-lc"], executable, executable=True),
    ]
    stages = [{"stage": name, "commands": commands} for name, commands in (
        ("configure", configure_commands), ("freeze", freeze_commands),
        ("compile", compile_commands), ("link", link_commands))]
    review_metadata = {}
    if all(review_selected):
        compile_roles = {"@source/configuration/probe.c": "configuration"}
        for group, role in ((units, "core"), (native, "builtin"),
                            (freezer, "freezer"), (target, "target")):
            for unit in group:
                compile_roles["@source/" + unit["source"]] = (
                    "builtin" if unit.get("compile_role") == "builtin" or "module" in unit else role
                )
        binding = bind_reviewed_cpython_configuration(
            configuration_outputs=configuration_outputs,
            review_manifest_bytes=review_manifest_bytes,
            expected_review_manifest_sha256=expected_review_manifest_sha256,
            source_inventory_sha256=expected_source_inventory_sha256,
            zig_manifest_sha256=_sha(zig_manifest_bytes), configuration_header=configuration_header,
            stages=stages, compile_roles=compile_roles,
        )
        for path, raw in binding.sources:
            if path in sources or path in inventory:
                _fail("configuration_review_overlap")
            sources[path] = raw
            inventory[path] = _record(path, raw)
        review_metadata = {"configuration_review_manifest_sha256": binding.manifest_sha256,
                           "reviewed_concrete_stages_sha256": binding.concrete_stages_sha256}
    recipe = canonical({"schema": RECIPE_V3_SCHEMA, "preparation_sha256": preparation.sha256,
                        "inputs": {"source": sorted(inventory.values(), key=lambda r: r["path"]),
                                   "toolchain": zig},
                        "environment": {"LANG": "C", "LC_ALL": "C", "TZ": "UTC",
                                        "SOURCE_DATE_EPOCH": "0"},
                        "stages": stages})
    # Reuse the execution mechanism's complete prospective dependency validator.
    _recipe(recipe, _sha(recipe), version3=True)
    manifest = canonical({"schema": "lunar-cpython-zig-concrete-build-recipe-v1", "solver": solver,
                          "recipe_sha256": _sha(recipe), "base_preparation_sha256": preparation.sha256,
                          "source_inventory_sha256": expected_source_inventory_sha256,
                          "configuration_header_sha256": expected_configuration_sha256,
                          "zig_manifest_sha256": ZIG_MANIFEST_SHA256, "runtime_closure_sha256": closure_sha,
                          **({"producer_lifecycle_profile": producer_lifecycle_profile}
                             if producer_lifecycle_profile is not None else {}),
                          "configuration_route": ("independent-eight-output-review-and-compiled-probe"
                                                  if review_metadata else
                                                  "independently-pinned-config-header-and-compiled-probe"),
                          **review_metadata,
                          "autoconf_executed": False, "host_python_used": False,
                          "toolchain_files": len(zig), "freezer_jobs": len(tasks),
                          "core_objects": len(units), "native_objects": len(native),
                          "freezer_objects": len(freezer), "target_objects": len(target),
                          "library": library, "executable": executable,
                          "build_performed": False, "configured_closure_verified": False,
                          "installation_accepted": False, "runtime_execution_performed": False,
                          "production_admission": False})
    return ConcreteBuildRecipe(recipe, tuple(sorted(sources.items())), manifest)


def _source_data_successor(base: ConcreteBuildRecipe) -> tuple[bytes, dict]:
    """Version only a freshly generated recipe; public legacy parsers stay strict."""
    from tools.static_python_rsi_fixture.execution_backend import (
        INPUT_PROJECTION_V4,
        RECIPE_V4_SCHEMA,
    )

    recipe = _recipe(base.recipe_bytes, base.sha256, version3=True)
    recipe["schema"] = RECIPE_V4_SCHEMA
    recipe["input_projection"] = INPUT_PROJECTION_V4
    raw = canonical(recipe)
    _recipe(raw, _sha(raw), version4=True)
    return raw, recipe


def prepare_cpython_build_recipe_v4(
    preparation: RSIProfilePreparation, *, source_inventory_bytes: bytes,
    expected_source_inventory_sha256: str, zig_manifest_bytes: bytes,
    configuration_header: bytes, expected_configuration_sha256: str,
    runtime_closure: FixedRuntimeClosure | None = None,
    producer_lifecycle_profile: str | None = None,
    configuration_outputs: tuple[tuple[str, bytes], ...] | None = None,
    review_manifest_bytes: bytes | None = None,
    expected_review_manifest_sha256: str | None = None,
) -> ConcreteBuildRecipe:
    """Explicit data-source successor, retaining every generated input pin/xbit.

    Original configured-source overlays retain the generator's existing contract;
    the complete original source inventory remains separately pinned in the
    manifest. No caller-supplied old recipe is accepted by this emitter.
    """
    base = prepare_cpython_build_recipe(
        preparation, source_inventory_bytes=source_inventory_bytes,
        expected_source_inventory_sha256=expected_source_inventory_sha256,
        zig_manifest_bytes=zig_manifest_bytes, configuration_header=configuration_header,
        expected_configuration_sha256=expected_configuration_sha256, runtime_closure=runtime_closure,
        producer_lifecycle_profile=producer_lifecycle_profile,
        configuration_outputs=configuration_outputs, review_manifest_bytes=review_manifest_bytes,
        expected_review_manifest_sha256=expected_review_manifest_sha256,
    )
    raw, recipe = _source_data_successor(base)
    facts = json.loads(base.manifest_bytes)
    original_source_pin = facts.pop("source_inventory_sha256")
    facts.update(schema="lunar-cpython-zig-data-source-concrete-build-recipe-v1",
                 recipe_sha256=_sha(raw), base_recipe_sha256=base.sha256,
                 base_manifest_sha256=_sha(base.manifest_bytes),
                 input_projection=recipe["input_projection"],
                 original_source_inventory_sha256=original_source_pin,
                 source_inventory_sha256=_sha(canonical(recipe["inputs"]["source"])),
                 toolchain_inventory_sha256=_sha(canonical(recipe["inputs"]["toolchain"])),
                 inputs_sha256=_sha(canonical(recipe["inputs"])))
    return ConcreteBuildRecipe(raw, base.sources, canonical(facts))
