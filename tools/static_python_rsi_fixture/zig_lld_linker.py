"""Explicit pinned-Zig ELF LLD entry for the v4 source-data capture profile.

This profile selects a fixed subcommand, not a generic executable prefix. It
neither acquires support bytes nor changes the original Zig support contract.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

from tools.static_python_rsi_fixture.concrete_recipe import (
    ConcreteBuildRecipe,
    ConcreteRecipeError,
    _inventory,
)
from tools.static_python_rsi_fixture.execution_backend import _recipe
from tools.static_python_rsi_fixture.installation_profile import RSIProfilePreparation
from tools.static_python_rsi_fixture.runtime_closure import FixedRuntimeClosure, canonical

PROFILE_SCHEMA = "lunar-zig-lld-musl-link-profile-v1"
LINKER_PATH = "zig"
_SUPPORT = "zig-lld/support/"
_ARCHIVES = ("libc.a", "libzigc.a", "libubsan_rt.a", "libcompiler_rt.a")
_CRT = {"crt1": (("crt1.o",), ()),
        "crt1-crti-crtn": (("crt1.o", "crti.o"), ("crtn.o",))}
_PREFIX = ["@toolchain/zig", "ld.lld", "-m", "elf_x86_64", "-static",
           "--no-dynamic-linker", "-o"]


class ZigLLDLinkerError(ValueError):
    """Finite refusals without private paths, tool output or source prose."""


def _fail(reason: str) -> None:
    raise ZigLLDLinkerError("zig_lld_linker_" + reason)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _profile(raw: bytes, expected: str) -> dict:
    if (type(raw) is not bytes or not 0 < len(raw) <= 32768
            or type(expected) is not str or _sha(raw) != expected):
        _fail("profile_pin")
    try:
        facts = json.loads(raw)
        if (type(facts) is not dict or canonical(facts) != raw
                or set(facts) != {"schema", "target", "linker_execution", "crt_mode", "archives", "inputs"}
                or facts["schema"] != PROFILE_SCHEMA or facts["target"] != "x86_64-linux-musl"
                or facts["linker_execution"] != "static-x86_64-elf"
                or type(facts["crt_mode"]) is not str or facts["crt_mode"] not in _CRT
                or type(facts["archives"]) is not list
                or any(type(name) is not str or name not in _ARCHIVES for name in facts["archives"])
                or facts["archives"] != [name for name in _ARCHIVES if name in facts["archives"]]
                or not {"libc.a", "libcompiler_rt.a"}.issubset(facts["archives"])):
            _fail("profile")
        encoded = canonical(facts["inputs"])
        records = _inventory(encoded, _sha(encoded))
        head, tail = _CRT[facts["crt_mode"]]
        expected_paths = {LINKER_PATH, *(_SUPPORT + name for name in (*head, *facts["archives"], *tail))}
        if (set(records) != expected_paths
                or any(row["executable"] is not (path == LINKER_PATH)
                       or not 0 < row["size"] <= 512 * 1024 * 1024
                       for path, row in records.items())
                or sum(row["size"] for row in records.values()) > 1024 * 1024 * 1024):
            _fail("profile_inputs")
        return facts
    except ZigLLDLinkerError:
        raise
    except (ConcreteRecipeError, ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        pass
    _fail("profile")


def _support_refs(profile: dict) -> tuple[list[str], list[str], list[str]]:
    head, tail = _CRT[profile["crt_mode"]]
    return (["@toolchain/" + _SUPPORT + name for name in head],
            ["@toolchain/" + _SUPPORT + name for name in profile["archives"]],
            ["@toolchain/" + _SUPPORT + name for name in tail])


def _zig_lld_link(command: dict) -> tuple[str, list[str]] | None:
    """Recognize only the reviewed explicit Zig ELF LLD command and depfile."""
    argv = command["argv"]
    if argv[:2] != _PREFIX[:2]:
        return None
    if argv[:len(_PREFIX)] != _PREFIX or len(argv) < len(_PREFIX) + 9 or argv.count("-o") != 1:
        _fail("command")
    target = argv[len(_PREFIX)]
    depfile = "@work/link-dependencies/" + target.removeprefix("@work/") + ".d"
    if (not target.startswith("@work/bin/lunar-")
            or argv[-2:] != ["--dependency-file", depfile]
            or argv.count("--start-group") != 1 or argv.count("--end-group") != 1):
        _fail("command")
    start, end = argv.index("--start-group"), argv.index("--end-group")
    body, archives, tail = argv[len(_PREFIX) + 1:start], argv[start + 1:end], argv[end + 1:-2]
    selected = [name for name in _ARCHIVES if "@toolchain/" + _SUPPORT + name in archives]
    if (archives != ["@toolchain/" + _SUPPORT + name for name in selected]
            or not {"libc.a", "libcompiler_rt.a"}.issubset(selected)):
        _fail("archives")
    head = ["@toolchain/" + _SUPPORT + "crt1.o"]
    if body[:2] == [*head, "@toolchain/" + _SUPPORT + "crti.o"]:
        head.append("@toolchain/" + _SUPPORT + "crti.o")
        expected_tail = ["@toolchain/" + _SUPPORT + "crtn.o"]
    else:
        expected_tail = []
    work = body[len(head):]
    refs = [*head, *work, *archives, *tail]
    if (body[:len(head)] != head or tail != expected_tail or not work
            or any(not ref.startswith("@work/") or not ref.endswith((".o", ".a")) for ref in work)
            or len(refs) != len(set(refs))):
        _fail("inputs")
    return target, refs


def validate_zig_lld_recipe_profile(recipe: dict, *, profile_bytes: bytes,
                                    expected_profile_sha256: str) -> dict:
    """Bind the separate profile to the original Zig row and both direct links."""
    profile = _profile(profile_bytes, expected_profile_sha256)
    rows = [row for row in recipe["inputs"]["toolchain"]
            if row["path"] == LINKER_PATH or row["path"].startswith("zig-lld/")]
    if rows != profile["inputs"]:
        _fail("recipe_inputs")
    head, archives, tail = _support_refs(profile)
    expected_support = [*head, *archives, *tail]
    links = 0
    for stage in recipe["stages"]:
        for command in stage["commands"]:
            link = _zig_lld_link(command)
            if link is not None:
                links += 1
                if [ref for ref in link[1] if ref.startswith("@toolchain/")] != expected_support:
                    _fail("recipe_support")
    if links != 2:
        _fail("recipe_links")
    return profile


def verify_zig_lld_linker_input(profile_bytes: bytes, *, expected_profile_sha256: str,
                                toolchain_root: Path, checkpoint: Callable[[], None]) -> None:
    """Recheck the independently pinned original Zig around its static ELF gate."""
    from tools.static_python_rsi_fixture.build_dependency_consumer import _read_pin
    from tools.static_python_rsi_fixture.podman_custody import _static_executable

    profile = _profile(profile_bytes, expected_profile_sha256)
    linker = next(row for row in profile["inputs"] if row["path"] == LINKER_PATH)
    root = toolchain_root.absolute()
    _read_pin(root, linker, checkpoint)
    _static_executable(root, linker, checkpoint)
    _read_pin(root, linker, checkpoint)


def prepare_cpython_zig_lld_link_recipe_v4(
    preparation: RSIProfilePreparation, *, zig_lld_profile_bytes: bytes,
    expected_zig_lld_profile_sha256: str,
    source_inventory_bytes: bytes, expected_source_inventory_sha256: str, zig_manifest_bytes: bytes,
    configuration_header: bytes, expected_configuration_sha256: str,
    runtime_closure: FixedRuntimeClosure | None = None,
    producer_lifecycle_profile: str | None = None,
    configuration_outputs: tuple[tuple[str, bytes], ...] | None = None,
    review_manifest_bytes: bytes | None = None,
    expected_review_manifest_sha256: str | None = None,
) -> ConcreteBuildRecipe:
    """Select direct LLD before dispatch; no support generation or fallback.

    The complete original Zig inventory is generated by the unchanged compiler
    recipe. Its executable row must already match the separate profile exactly.
    Only declared non-executable support records are added to that inventory.
    """
    from tools.static_python_rsi_fixture import link_dependency_capture as capture
    from tools.static_python_rsi_fixture.dependency_capture import MAX_DEPFILE_BYTES

    profile = _profile(zig_lld_profile_bytes, expected_zig_lld_profile_sha256)
    base = capture.prepare_cpython_dependency_recipe(
        preparation, source_inventory_bytes=source_inventory_bytes,
        expected_source_inventory_sha256=expected_source_inventory_sha256,
        zig_manifest_bytes=zig_manifest_bytes, configuration_header=configuration_header,
        expected_configuration_sha256=expected_configuration_sha256, runtime_closure=runtime_closure,
        producer_lifecycle_profile=producer_lifecycle_profile,
        configuration_outputs=configuration_outputs, review_manifest_bytes=review_manifest_bytes,
        expected_review_manifest_sha256=expected_review_manifest_sha256,
    )
    recipe = _recipe(base.recipe_bytes, base.sha256, version3=True)
    _, links = capture._capture_plan(recipe, instrumented=False)
    original = [row for row in recipe["inputs"]["toolchain"] if row["path"] == LINKER_PATH]
    expected = [row for row in profile["inputs"] if row["path"] == LINKER_PATH]
    if original != expected:
        _fail("original_zig_pin")
    if any(row["path"].startswith("zig-lld/") for row in recipe["inputs"]["toolchain"]):
        _fail("input_overlap")
    recipe["inputs"]["toolchain"] += [row for row in profile["inputs"] if row["path"] != LINKER_PATH]
    recipe["inputs"]["toolchain"].sort(key=lambda row: row["path"])
    head, archives, tail = _support_refs(profile)
    for link in links:
        command = next(stage for stage in recipe["stages"] if stage["stage"] == link["stage"])[
            "commands"][link["command_index"]]
        command["argv"] = [*_PREFIX, link["target"], *head, *link["explicit_inputs"],
                           "--start-group", *archives, "--end-group", *tail,
                           "--dependency-file", "@work/" + link["depfile"]]
        command["outputs"].append({"path": link["depfile"], "max_size": MAX_DEPFILE_BYTES,
                                   "executable": False})
    raw = canonical(recipe)
    manifest = canonical({"schema": "lunar-cpython-zig-lld-direct-capture-base-v1",
                          "recipe_sha256": _sha(raw), "base_recipe_sha256": base.sha256,
                          "base_manifest_sha256": _sha(base.manifest_bytes),
                          "zig_lld_profile_sha256": expected_zig_lld_profile_sha256,
                          **capture._FALSE_CLAIMS})
    return capture._data_source_capture_successor(
        ConcreteBuildRecipe(raw, base.sources, manifest),
        original_source_inventory_sha256=expected_source_inventory_sha256,
        zig_lld_profile_bytes=zig_lld_profile_bytes,
        expected_zig_lld_profile_sha256=expected_zig_lld_profile_sha256,
    )
