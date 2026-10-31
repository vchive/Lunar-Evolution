"""Explicit candidate selection and a separate actual direct-LLD seed capture.

Observed cache bytes never select their own profile. This trusted-local path
retains the original absolute deadline and never executes the generated ELF.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from lunar_evolution.static_python_elf import (
    StaticPythonELFError,
    inspect_static_python_relocatable_elf,
)
from lunar_evolution.static_python_link_objects import (
    StaticPythonLinkObjectError,
    inspect_static_python_link_archive,
)
from tools.static_python_rsi_fixture.build_dependency_consumer import (
    _read_pin,
    _report_outputs,
    _write_once,
)
from tools.static_python_rsi_fixture.concrete_recipe import _record, complete_zig_inventory
from tools.static_python_rsi_fixture.execution_backend import (
    _finite,
    _open_beneath,
    _recipe,
    run_pinned_build_v3,
)
from tools.static_python_rsi_fixture.installation_profile import RSIProfilePreparation
from tools.static_python_rsi_fixture.link_dependency_capture import parse_linker_depfile
from tools.static_python_rsi_fixture.podman_custody import _static_executable
from tools.static_python_rsi_fixture.runtime_closure import canonical
from tools.static_python_rsi_fixture.zig_lld_linker import _PREFIX, _profile, _support_refs
from tools.static_python_rsi_fixture.zig_support import _FALSE, _SOURCE
from tools.static_python_rsi_fixture.zig_support_candidates import (
    ZigSupportCandidateBundle,
    prepare_zig_support_candidate_recipe,
    validate_zig_support_candidate_bundle,
)

_SCHEMA = "lunar-zig-lld-support-selection-v1"
_SEED_OBJECTS = tuple(name.removesuffix(".c") + ".o" for name in _SOURCE)


class ZigSupportSelectionError(ValueError):
    """Finite errors without paths, arbitrary callback data or tool output."""


def _fail(reason: str) -> None:
    raise ZigSupportSelectionError("zig_support_selection_" + reason)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _pin(value: object) -> bool:
    return type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _checkpoint(deadline, interrupted, monotonic):
    if (not _finite(deadline) or deadline <= 0 or not callable(monotonic)
            or interrupted is not None and not callable(interrupted)):
        _fail("control")

    def check():
        try:
            now = monotonic()
            stop = False if interrupted is None else interrupted()
        except Exception:  # noqa: BLE001 - callbacks cannot supply refusal prose
            _fail("control")
        if not _finite(now) or type(stop) is not bool:
            _fail("control")
        if stop:
            _fail("interrupted")
        if now >= deadline:
            _fail("deadline")

    check()
    return check


@dataclass(frozen=True, slots=True)
class ZigLLDSupportSelection:
    """Observed mappings and bytes; no immutable-generation authority."""

    manifest_bytes: bytes
    files: tuple[tuple[str, bytes], ...]

    @property
    def sha256(self) -> str:
        return _sha(self.manifest_bytes)


def prepare_zig_lld_support_selection(
    preparation: RSIProfilePreparation, *, bundle: ZigSupportCandidateBundle,
    expected_bundle_sha256: str, zig_manifest_bytes: bytes,
    zig_lld_profile_bytes: bytes, expected_zig_lld_profile_sha256: str,
    selections: tuple[tuple[str, str], ...],
) -> ZigLLDSupportSelection:
    """Select every independently pinned role by a caller-supplied full path."""
    tools = complete_zig_inventory(zig_manifest_bytes)
    inventory_sha = _sha(canonical(tools))
    observed = validate_zig_support_candidate_bundle(
        bundle, expected_bundle_sha256=expected_bundle_sha256,
        preparation_sha256=preparation.sha256, zig_inventory_sha256=inventory_sha,
    )
    profile = _profile(zig_lld_profile_bytes, expected_zig_lld_profile_sha256)
    if ([r for r in tools if r["path"] == "zig"]
            != [r for r in profile["inputs"] if r["path"] == "zig"]):
        _fail("original_zig_pin")
    expected = {r["path"]: r for r in profile["inputs"] if r["path"] != "zig"}
    candidates = {r["path"]: r for r in observed["candidates"]}
    if (type(selections) is not tuple or len(selections) != len(expected)
            or any(type(pair) is not tuple or len(pair) != 2
                   or any(type(item) is not str for item in pair) for pair in selections)):
        _fail("mapping")
    mapping = dict(selections)
    if (len(mapping) != len(selections) or set(mapping) != set(expected)
            or len(set(mapping.values())) != len(mapping)):
        _fail("mapping")
    files, records = dict(bundle.files), []
    for path, source in sorted(mapping.items()):
        candidate = candidates.get(source)
        if (candidate is None or PurePosixPath(candidate["cache_path"]).name != PurePosixPath(path).name
                or {**expected[path], "path": source}
                != {key: candidate[key] for key in ("path", "size", "sha256", "executable")}):
            _fail("candidate_pin")
        records.append({**expected[path], "candidate_path": source})
    manifest = canonical({"schema": _SCHEMA, "preparation_sha256": preparation.sha256,
                          "candidate_bundle_sha256": expected_bundle_sha256,
                          "zig_inventory_sha256": inventory_sha,
                          "zig_lld_profile_sha256": expected_zig_lld_profile_sha256,
                          "support": records, "seed_executed": False, **_FALSE})
    return ZigLLDSupportSelection(manifest, tuple((path, files[source]) for path, source in sorted(mapping.items())))


def _selection(selection, expected_sha, *, preparation_sha, tools, profile, profile_sha) -> dict:
    try:
        if (type(selection) is not ZigLLDSupportSelection or type(selection.manifest_bytes) is not bytes
                or not 0 < len(selection.manifest_bytes) <= 32768
                or not _pin(expected_sha) or _sha(selection.manifest_bytes) != expected_sha
                or type(selection.files) is not tuple):
            _fail("pin")
        facts = json.loads(selection.manifest_bytes)
        if (type(facts) is not dict or canonical(facts) != selection.manifest_bytes
                or set(facts) != {"schema", "preparation_sha256", "candidate_bundle_sha256",
                                  "zig_inventory_sha256", "zig_lld_profile_sha256", "support", "seed_executed", *_FALSE}
                or facts["schema"] != _SCHEMA or facts["preparation_sha256"] != preparation_sha
                or facts["zig_inventory_sha256"] != _sha(canonical(tools))
                or facts["zig_lld_profile_sha256"] != profile_sha
                or not _pin(facts["candidate_bundle_sha256"]) or facts["seed_executed"] is not False
                or any(facts[key] is not value for key, value in _FALSE.items())
                or type(facts["support"]) is not list
                or any(type(pair) is not tuple or len(pair) != 2 or type(pair[0]) is not str
                       or type(pair[1]) is not bytes for pair in selection.files)):
            _fail("selection")
        expected = [r for r in profile["inputs"] if r["path"] != "zig"]
        files = dict(selection.files)
        if (len(files) != len(selection.files) or list(files) != [r["path"] for r in expected]
                or len(facts["support"]) != len(expected)
                or [r for r in tools if r["path"] == "zig"]
                != [r for r in profile["inputs"] if r["path"] == "zig"]):
            _fail("selection")
        source_paths = set()
        for row, original in zip(facts["support"], expected, strict=True):
            if (type(row) is not dict or set(row) != {*original, "candidate_path"}
                    or type(row["size"]) is not int or row["executable"] is not False
                    or type(row["sha256"]) is not str or type(row["path"]) is not str):
                _fail("selection")
            source = row["candidate_path"]
            if (type(source) is not str or str(PurePosixPath(source)) != source
                    or any(p in {"", ".", ".."} for p in source.split("/"))
                    or len(source.split("/")) < 4 or source.split("/")[:2]
                    not in (["candidates", "global"], ["candidates", "local"])
                    or PurePosixPath(source).name != PurePosixPath(row["path"]).name
                    or source in source_paths or row != {**original, "candidate_path": source}
                    or _record(row["path"], files[row["path"]]) != original):
                _fail("selection")
            source_paths.add(source)
        return facts
    except ZigSupportSelectionError:
        raise
    except (AttributeError, ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        _fail("selection")


def stage_zig_lld_support_selection(
    preparation: RSIProfilePreparation, *, selection: ZigLLDSupportSelection,
    expected_selection_sha256: str, zig_manifest_bytes: bytes, zig_lld_profile_bytes: bytes,
    expected_zig_lld_profile_sha256: str, toolchain_root: Path, deadline: float,
    interrupted: Callable[[], bool] | None = None, monotonic: Callable[[], float] = time.monotonic,
) -> None:
    """Create only a fresh support namespace; retain any partial failure."""
    check = _checkpoint(deadline, interrupted, monotonic)
    tools = complete_zig_inventory(zig_manifest_bytes)
    profile = _profile(zig_lld_profile_bytes, expected_zig_lld_profile_sha256)
    _selection(selection, expected_selection_sha256, preparation_sha=preparation.sha256,
               tools=tools, profile=profile, profile_sha=expected_zig_lld_profile_sha256)
    root = toolchain_root.absolute()
    for row in tools:
        _read_pin(root, row, check)
    # mkdirat and the original root FD avoid following a substituted parent.
    fd = _open_beneath(root, ".")
    try:
        check()
        os.mkdir("zig-lld", 0o700, dir_fd=fd)
        child = os.open("zig-lld", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
        try:
            os.mkdir("support", 0o700, dir_fd=child)
        finally:
            os.close(child)
    finally:
        os.close(fd)
    for path, raw in selection.files:
        _write_once(root / "zig-lld/support", PurePosixPath(path).name, raw, check)
        _read_pin(root, _record(path, raw), check)
    for row in tools + [r for r in profile["inputs"] if r["path"] != "zig"]:
        _read_pin(root, row, check)
    check()


def stage_zig_lld_support_selection_object_format(
    preparation: RSIProfilePreparation, *, selection: ZigLLDSupportSelection,
    expected_selection_sha256: str, zig_manifest_bytes: bytes, zig_lld_profile_bytes: bytes,
    expected_zig_lld_profile_sha256: str, toolchain_root: Path, deadline: float,
    interrupted: Callable[[], bool] | None = None, monotonic: Callable[[], float] = time.monotonic,
) -> None:
    """Opt in to inline ar/ET_REL checks before the original fresh staging path.

    Pins, selection bytes and the stage API retain their original format. This
    function does not run a generator or certify support generation/custody.
    """
    check = _checkpoint(deadline, interrupted, monotonic)
    tools = complete_zig_inventory(zig_manifest_bytes)
    profile = _profile(zig_lld_profile_bytes, expected_zig_lld_profile_sha256)
    _selection(selection, expected_selection_sha256, preparation_sha=preparation.sha256,
               tools=tools, profile=profile, profile_sha=expected_zig_lld_profile_sha256)
    try:
        for path, raw in selection.files:
            check()
            if path.endswith(".a"):
                inspect_static_python_link_archive(raw, checkpoint=check)
            else:
                inspect_static_python_relocatable_elf(raw, checkpoint=check)
    except (StaticPythonELFError, StaticPythonLinkObjectError):
        _fail("object_format")
    stage_zig_lld_support_selection(
        preparation, selection=selection, expected_selection_sha256=expected_selection_sha256,
        zig_manifest_bytes=zig_manifest_bytes, zig_lld_profile_bytes=zig_lld_profile_bytes,
        expected_zig_lld_profile_sha256=expected_zig_lld_profile_sha256,
        toolchain_root=toolchain_root, deadline=deadline, interrupted=interrupted, monotonic=monotonic,
    )


def run_selected_zig_lld_seed_capture(
    preparation: RSIProfilePreparation, *, selection: ZigLLDSupportSelection,
    expected_selection_sha256: str, zig_manifest_bytes: bytes, zig_lld_profile_bytes: bytes,
    expected_zig_lld_profile_sha256: str, toolchain_root: Path, workspace: Path, deadline: float,
    interrupted: Callable[[], bool] | None = None, monotonic: Callable[[], float] = time.monotonic,
) -> bytes:
    """Retain genuine seed link capture; no retry, fallback or ELF execution."""
    check = _checkpoint(deadline, interrupted, monotonic)
    tools = complete_zig_inventory(zig_manifest_bytes)
    profile = _profile(zig_lld_profile_bytes, expected_zig_lld_profile_sha256)
    _selection(selection, expected_selection_sha256, preparation_sha=preparation.sha256,
               tools=tools, profile=profile, profile_sha=expected_zig_lld_profile_sha256)
    build = prepare_zig_support_candidate_recipe(preparation, zig_manifest_bytes=zig_manifest_bytes)
    parsed = _recipe(build.recipe_bytes, build.sha256, version3=True)
    if parsed["inputs"]["toolchain"] != tools:
        _fail("original_inventory")
    parsed["inputs"]["toolchain"] = sorted(tools + [r for r in profile["inputs"] if r["path"] != "zig"],
                                           key=lambda row: row["path"])
    head, archives, tail = _support_refs(profile)
    parsed["stages"][-1]["commands"] = [{
        "argv": [*_PREFIX, "@work/support/seed", *head, *("@work/" + name for name in _SEED_OBJECTS),
                 "--start-group", *archives, "--end-group", *tail,
                 "--dependency-file", "@work/support/seed.d"],
        "outputs": [{"path": "support/seed", "max_size": 16 * 1024 * 1024, "executable": True},
                    {"path": "support/seed.d", "max_size": 2 * 1024 * 1024, "executable": False}],
    }]
    raw = canonical(parsed)
    parsed = _recipe(raw, _sha(raw), version3=True)
    root, tool_root = workspace.absolute(), toolchain_root.absolute()
    if (root.parent.resolve() != root.parent or not root.parent.is_dir()
            or tool_root.resolve() != tool_root or root == tool_root
            or root in tool_root.parents or tool_root in root.parents):
        _fail("workspace")
    for row in parsed["inputs"]["toolchain"]:
        _read_pin(tool_root, row, check)
    _static_executable(tool_root, next(r for r in tools if r["path"] == "zig"), check)
    check()
    root.mkdir(mode=0o700)
    source = root / "seed-source"
    source.mkdir(mode=0o700)
    (source / "support").mkdir(mode=0o700)
    for name, data in build.sources:
        _write_once(source / "support", PurePosixPath(name).name, data, check)
    _write_once(root, "selection.json", selection.manifest_bytes, check)
    _write_once(root, "profile.json", zig_lld_profile_bytes, check)
    attempt = root / "attempt"
    report = run_pinned_build_v3(
        preparation, recipe_bytes=raw, expected_recipe_sha256=_sha(raw), source_root=source,
        toolchain_root=tool_root, workspace=attempt, deadline=deadline,
        interrupted=interrupted, monotonic=monotonic,
    )
    check()
    report_raw, outputs = _report_outputs(report, parsed)
    _read_pin(attempt, _record("report.json", report_raw), check)
    work = attempt / "work"
    retained = {r["path"]: _read_pin(work, r, check, retain=True) for r in outputs}
    target, dependencies = parse_linker_depfile(retained["support/seed.d"])
    explicit = {str(work / name) for name in _SEED_OBJECTS} | {
        str(attempt / "toolchain" / r["path"]) for r in profile["inputs"] if r["path"] != "zig"}
    if target != str(work / "support/seed") or set(dependencies) != explicit:
        _fail("actual_dependencies")
    seed = next(r for r in outputs if r["path"] == "support/seed")
    _static_executable(work, seed, check)
    for role, original in (("source", source), ("toolchain", tool_root)):
        for row in parsed["inputs"][role]:
            _read_pin(original, row, check)
            _read_pin(attempt / role, row, check)
    for row in outputs:
        _read_pin(work, row, check)
    _read_pin(attempt, _record("report.json", report_raw), check)
    _read_pin(root, _record("selection.json", selection.manifest_bytes), check)
    _read_pin(root, _record("profile.json", zig_lld_profile_bytes), check)
    evidence = canonical({"schema": "lunar-zig-lld-selected-seed-capture-v1",
                          "preparation_sha256": preparation.sha256,
                          "selection_sha256": expected_selection_sha256,
                          "zig_lld_profile_sha256": expected_zig_lld_profile_sha256,
                          "recipe_sha256": _sha(raw), "report_sha256": _sha(report_raw),
                          "outputs": outputs, "actual_link_dependencies": sorted(dependencies),
                          "seed_executed": False, **_FALSE})
    _write_once(root, "selected-seed-capture.json", evidence, check)
    _read_pin(root, _record("selected-seed-capture.json", evidence), check)
    return evidence
