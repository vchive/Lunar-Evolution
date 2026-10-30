"""Run the fixed CPython configure script using explicit ordinary trusted tools.

This is an opt-in native build preparation, not a sandbox or configured-closure
acceptance. It never invokes make or a freezer. Generated headers require an
independent review/pin before the concrete build recipe may consume them.
"""

from __future__ import annotations

import hashlib
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from tools.static_python_fixture.configure_plan import emit_configure_plan_assets
from tools.static_python_rsi_fixture.build_dependency_consumer import _read_pin
from tools.static_python_rsi_fixture.concrete_recipe import (
    ConcreteRecipeError,
    _inventory,
    complete_zig_inventory,
)
from tools.static_python_rsi_fixture.execution_backend import (
    MAX_INPUT_FILE_BYTES,
    BuildExecutionError,
    _command,
    _finite,
    _observe,
    _write_once,
)
from tools.static_python_rsi_fixture.runtime_closure import canonical

CONFIGURE_SHA256 = "0495fd50c8441437de8df5bd681b94bda00492ad3cf0d0db07f52f928dc12f20"
CONFIGURE_BYTES = 893475
# Supply ordinary, separately pinned regular-file copies; system symlinks are
# not accepted as input files. Full helper runtime files may appear outside bin.
HELPER_PROGRAMS = frozenset({
    "sh", "sed", "grep", "expr", "basename", "dirname", "mkdir", "cat", "rm", "ln",
    "tr", "cut", "awk", "sort", "uniq", "wc", "uname", "chmod", "mv", "cp", "touch",
    "readlink", "head", "tail", "install", "true", "false", "printf", "ls", "find",
    "readelf", "python3.13", "diff",
})
MAX_HELPER_BYTES = 1024 * 1024**2
MAX_CONFIG_OUTPUT_BYTES = 16 * 1024**2
OUTPUTS = ("pyconfig.h", "Makefile", "Makefile.pre", "config.log", "config.status",
           "Modules/Setup.bootstrap", "Modules/Setup.stdlib", "Modules/config.c")
_FALSE = dict.fromkeys(("configured_closure_verified", "immutable_custody_verified",
                        "helper_implicit_inputs_verified", "installation_accepted",
                        "production_admission", "online_publication"), False)


class ConfigurationGenerationError(RuntimeError):
    """Fixed refusal; original workspace and process logs are retained."""

    def __init__(self, reason: str):
        self.code = "static_python_configuration_" + reason
        super().__init__(self.code)


@dataclass(frozen=True, slots=True)
class GeneratedConfiguration:
    """Original output bytes, not independently reviewed configuration."""

    configuration_header: bytes
    makefile: bytes
    observation_bytes: bytes
    configured_closure_verified: bool = False
    production_admission: bool = False
    online_publication: bool = False
    output_bytes: tuple[tuple[str, bytes], ...] = ()


def _fail(reason: str) -> None:
    raise ConfigurationGenerationError(reason)


def _inputs(source: bytes, source_sha256: str, helpers: bytes,
            helper_sha256: str, zig: bytes) -> dict[str, list[dict]]:
    try:
        source_records = _inventory(source, source_sha256)
        helper_records = _inventory(helpers, helper_sha256)
        toolchain_records = complete_zig_inventory(zig)
    except (ConcreteRecipeError, ValueError, TypeError, KeyError):
        _fail("inventory")
    configure = source_records.get("configure")
    if (configure is None or configure["size"] != CONFIGURE_BYTES
            or configure["sha256"] != CONFIGURE_SHA256):
        _fail("configure_source")
    if any(path in source_records for path in ("pyconfig.h", "Makefile", "config.status", "config.log")):
        _fail("source_already_configured")
    executable_helpers = {path.removeprefix("bin/") for path, row in helper_records.items()
                          if path.startswith("bin/") and row["executable"]}
    if (executable_helpers != HELPER_PROGRAMS
            or sum(row["size"] for row in helper_records.values()) > MAX_HELPER_BYTES
            or any(row["executable"] and path.startswith("bin/")
                   and path.removeprefix("bin/") not in HELPER_PROGRAMS
                   for path, row in helper_records.items())):
        _fail("helper_programs")
    if any(path.split("/")[-1] in {"make", "gmake"} for path in helper_records):
        _fail("make_refused")
    return {"source": list(source_records.values()), "helpers": list(helper_records.values()),
            "toolchain": toolchain_records}


def _dispatch(workspace: Path) -> tuple[list[str], dict[str, str], dict[str, bytes]]:
    """Fixed bindings only. No environment, shell options or cache from callers."""
    source, tools = workspace / "source", workspace / "toolchain"
    helpers, work = workspace / "helpers", workspace / "work"
    shell = str(helpers / "bin/sh")
    wrappers = {}
    for name, subcommand in (("cc", "cc -target x86_64-linux-musl"), ("ar", "ar"), ("ranlib", "ar s")):
        wrappers[name] = ("exec " + str(tools / "zig") + " " + subcommand + ' "$@"\n').encode("ascii")
    assets = emit_configure_plan_assets()
    wrappers["config.site"] = assets["config.site"]
    argv = [shell, str(source / "configure"), "--build=x86_64-linux-gnu", "--host=x86_64-linux-musl",
            "--disable-shared", "--disable-test-modules", "--without-ensurepip", "--disable-ipv6",
            "--with-computed-gotos", "--with-pymalloc", "--prefix=/lunar-static-fixture",
            "--with-build-python=" + str(helpers / "bin/python3.13")]
    environment = {
        "PATH": str(helpers / "bin"), "HOME": str(work / ".home"), "TMPDIR": str(work),
        "LANG": "C", "LC_ALL": "C", "TZ": "UTC", "SOURCE_DATE_EPOCH": "0",
        "CONFIG_SHELL": shell, "SHELL": shell, "CONFIG_SITE": str(work / "config.site"),
        "CC": shell + " " + str(work / "cc"), "AR": shell + " " + str(work / "ar"),
        "RANLIB": shell + " " + str(work / "ranlib"), "CXX": str(helpers / "bin/false"),
        "PKG_CONFIG": str(helpers / "bin/false"), "PKG_CONFIG_PATH": "", "PKG_CONFIG_LIBDIR": "",
        "CFLAGS": "-O2 -g0 -fno-strict-aliasing -fno-common", "CPPFLAGS": "", "LDFLAGS": "-static",
        "ZIG_LIB_DIR": str(tools / "lib"), "ZIG_GLOBAL_CACHE_DIR": str(work / ".zig-global-cache"),
        "ZIG_LOCAL_CACHE_DIR": str(work / ".zig-local-cache"),
        "PYTHONHOME": str(helpers), "PYTHONNOUSERSITE": "1", "PYTHONSAFEPATH": "1",
    }
    wrappers["Modules/Setup.local"] = assets["Modules/Setup.local"]
    return argv, environment, wrappers


def run_cpython_configuration(
    *, source_root: Path, toolchain_root: Path, helper_root: Path, workspace: Path,
    source_inventory_bytes: bytes, expected_source_inventory_sha256: str,
    helper_inventory_bytes: bytes, expected_helper_inventory_sha256: str,
    zig_manifest_bytes: bytes, deadline: float,
    interrupted: Callable[[], bool] | None = None,
) -> GeneratedConfiguration:
    """Actually configure once in a fresh workspace; retain the first failure.

    Native Linux x86_64 tools must be supplied explicitly. Dynamic helper/library
    dependencies are trusted ordinary build inputs; this function does not claim
    their complete runtime closure or immutable custody. No source/header bytes
    are inferred from the running Python. A successful configure does not review
    its cross defaults, optional discovery, flags or replacement objects.
    """
    inputs = _inputs(source_inventory_bytes, expected_source_inventory_sha256,
                     helper_inventory_bytes, expected_helper_inventory_sha256, zig_manifest_bytes)
    roots = {"source": source_root, "toolchain": toolchain_root, "helpers": helper_root}
    if (any(not isinstance(path, Path) for path in (*roots.values(), workspace))
            or not _finite(deadline) or deadline <= 0
            or (interrupted is not None and not callable(interrupted))):
        _fail("control")
    roots = {role: path.absolute() for role, path in roots.items()}
    workspace = workspace.absolute()
    # Configure treats several tool variables as shell words. Refuse ambiguous
    # paths before emitting wrappers or invoking the fixed pinned shell.
    if (re.fullmatch(r"/[A-Za-z0-9_./-]+", str(workspace)) is None
            or ".." in workspace.parts or workspace.parent.resolve() != workspace.parent
            or not workspace.parent.is_dir()
            or any(root.resolve() != root or not root.is_dir() for root in roots.values())
            or any(workspace == root or workspace in root.parents or root in workspace.parents
                   for root in roots.values())):
        _fail("root")

    def checkpoint() -> None:
        reason = None
        try:
            stop = False if interrupted is None else interrupted()
        except KeyboardInterrupt:
            reason, stop = "interrupted", False
        except Exception:  # noqa: BLE001 - trusted callback details stay out of errors
            reason, stop = "control", False
        if reason is not None:
            _fail(reason)
        if type(stop) is not bool:
            _fail("control")
        if stop:
            _fail("interrupted")
        if time.monotonic() >= deadline:
            _fail("deadline")

    checkpoint()
    try:
        workspace.mkdir(mode=0o700)
    except OSError:
        _fail("workspace_not_fresh")
    evidence = {"schema": "lunar-cpython-configure-observation-v1", "status": "partial",
                "source_inventory_sha256": expected_source_inventory_sha256,
                "helper_inventory_sha256": expected_helper_inventory_sha256,
                "configure_sha256": CONFIGURE_SHA256, "zig_manifest_sha256": hashlib.sha256(zig_manifest_bytes).hexdigest(),
                "outputs": [], "command": {},
                "target_execution_observation": "not-observed", **_FALSE}
    reason = None
    header = makefile = b""
    output_bytes: tuple[tuple[str, bytes], ...] = ()
    try:
        _write_once(workspace / "source-inventory.json", source_inventory_bytes)
        _write_once(workspace / "helper-inventory.json", helper_inventory_bytes)
        _write_once(workspace / "zig-manifest.json", zig_manifest_bytes)
        for role, records in inputs.items():
            snapshot = workspace / role
            snapshot.mkdir(mode=0o700)
            for record in records:
                checkpoint()
                target = snapshot / record["path"]
                if _observe(roots[role], record["path"], MAX_INPUT_FILE_BYTES, destination=target,
                            executable=record["executable"], checkpoint=checkpoint) != record:
                    _fail("input_pin")
                target.chmod(0o555 if record["executable"] else 0o444)
        work = workspace / "work"
        work.mkdir(mode=0o700)
        (work / ".home").mkdir(mode=0o700)
        (work / "Modules").mkdir(mode=0o700)
        logs = workspace / "logs"
        logs.mkdir(mode=0o700)
        argv, environment, wrappers = _dispatch(workspace)
        wrapper_records = []
        for name, raw in wrappers.items():
            _write_once(work / name, raw)
            wrapper_records.append(_observe(work, name, MAX_CONFIG_OUTPUT_BYTES, checkpoint=checkpoint))
        evidence.update(argv=argv, environment=environment, wrappers=wrapper_records)

        def verify_inputs() -> None:
            for role, records in inputs.items():
                for record in records:
                    checkpoint()
                    if any(_observe(root, record["path"], MAX_INPUT_FILE_BYTES,
                                    checkpoint=checkpoint) != record
                           for root in (roots[role], workspace / role)):
                        _fail("input_drift")
            for record in wrapper_records:
                if _observe(work, record["path"], MAX_CONFIG_OUTPUT_BYTES, checkpoint=checkpoint) != record:
                    _fail("wrapper_drift")

        verify_inputs()

        def command_checkpoint() -> None:
            # The shared process runner preserves only its own fixed refusal
            # class during kill/reap. Adapt controls instead of losing the
            # original deadline/interruption to its generic IO error branch.
            try:
                checkpoint()
            except ConfigurationGenerationError as exc:
                raise BuildExecutionError(exc.code.removeprefix("static_python_configuration_")) from None

        _command(argv, work=work, environment=environment, logs=logs,
                 checkpoint=command_checkpoint, evidence=evidence["command"])
        verify_inputs()
        output_root = workspace / "observed"
        output_root.mkdir(mode=0o700)
        for name in OUTPUTS:
            record = _observe(work, name, MAX_CONFIG_OUTPUT_BYTES, destination=output_root / name,
                              checkpoint=checkpoint)
            (output_root / name).chmod(0o555 if record["executable"] else 0o444)
            if _observe(output_root, name, MAX_CONFIG_OUTPUT_BYTES, checkpoint=checkpoint) != record:
                _fail("output_readback")
            evidence["outputs"].append(record)
        retained = {row["path"]: row for row in evidence["outputs"]}
        output_bytes = tuple((name, _read_pin(output_root, retained[name], checkpoint, retain=True))
                             for name in OUTPUTS)
        header, makefile = dict(output_bytes)["pyconfig.h"], dict(output_bytes)["Makefile"]
        verify_inputs()
        checkpoint()
        evidence["status"] = "observed"
    except ConfigurationGenerationError as exc:
        reason = exc.code.removeprefix("static_python_configuration_")
    except BuildExecutionError as exc:
        reason = exc.code.removeprefix("static_python_build_execution_")
    except KeyboardInterrupt:
        reason = "interrupted"
    except Exception:  # noqa: BLE001 - raw paths/tool details stay in original workspace
        reason = "attempt_io"
    evidence["reason"] = reason
    raw = canonical(evidence)
    write_failed = False
    try:
        _write_once(workspace / "observation.json", raw)
    except OSError:
        write_failed = True
    if write_failed:
        _fail("observation_write")
    if reason is not None:
        _fail(reason)
    return GeneratedConfiguration(header, makefile, raw, output_bytes=output_bytes)
