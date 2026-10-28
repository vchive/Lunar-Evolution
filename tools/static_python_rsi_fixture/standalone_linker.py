"""Finite opt-in static standalone linker inputs, never build admission.

The profile pins explicit files independently of the generated recipe. It does
not authenticate their origin or prove all reads by the trusted executable.
Dynamic linkers and an external loader/shared-library closure are unsupported.
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

PROFILE_SCHEMA = "lunar-standalone-musl-link-profile-v1"
RECIPE_SCHEMA = "lunar-cpython-standalone-link-capture-recipe-v1"
LINKER_PATH = "standalone-linker/bin/ld.lld"
_SUPPORT = "standalone-linker/support/"
_ARCHIVES = ("libc.a", "libzigc.a", "libubsan_rt.a", "libcompiler_rt.a")
_CRT = {"crt1": (("crt1.o",), ()),
        "crt1-crti-crtn": (("crt1.o", "crti.o"), ("crtn.o",))}
_PREFIX = ["@toolchain/" + LINKER_PATH, "-m", "elf_x86_64", "-static",
           "--no-dynamic-linker", "-o"]


class StandaloneLinkerError(ValueError):
    """Fixed profile errors without commands, input prose or private paths."""


def _fail(reason: str) -> None:
    raise StandaloneLinkerError("standalone_linker_" + reason)


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
    except StandaloneLinkerError:
        raise
    except (ConcreteRecipeError, ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        pass
    _fail("profile")


def _support_refs(profile: dict) -> tuple[list[str], list[str], list[str]]:
    head, tail = _CRT[profile["crt_mode"]]
    return (["@toolchain/" + _SUPPORT + name for name in head],
            ["@toolchain/" + _SUPPORT + name for name in profile["archives"]],
            ["@toolchain/" + _SUPPORT + name for name in tail])


def _standalone_link(command: dict) -> tuple[str, list[str]] | None:
    """Recognize only the finite static command, including its real depfile."""
    argv = command["argv"]
    if argv[0] != _PREFIX[0]:
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


def validate_standalone_recipe_profile(recipe: dict, *, profile_bytes: bytes,
                                       expected_profile_sha256: str) -> dict:
    """Compare the separately pinned profile with exact recipe inputs/commands."""
    profile = _profile(profile_bytes, expected_profile_sha256)
    rows = [row for row in recipe["inputs"]["toolchain"]
            if row["path"].startswith("standalone-linker/")]
    if rows != profile["inputs"]:
        _fail("recipe_inputs")
    head, archives, tail = _support_refs(profile)
    expected_support = [*head, *archives, *tail]
    links = 0
    for stage in recipe["stages"]:
        for command in stage["commands"]:
            link = _standalone_link(command)
            if link is not None:
                links += 1
                if [ref for ref in link[1] if ref.startswith("@toolchain/")] != expected_support:
                    _fail("recipe_support")
    if links != 2:
        _fail("recipe_links")
    return profile


def verify_standalone_linker_input(profile_bytes: bytes, *, expected_profile_sha256: str,
                                   toolchain_root: Path, checkpoint: Callable[[], None]) -> None:
    """Use existing FD pin reads and static ELF gate before any build process."""
    # These local imports keep the pure finite grammar independent of consumers.
    from tools.static_python_rsi_fixture.build_dependency_consumer import _read_pin
    from tools.static_python_rsi_fixture.podman_custody import _static_executable

    profile = _profile(profile_bytes, expected_profile_sha256)
    linker = next(row for row in profile["inputs"] if row["path"] == LINKER_PATH)
    root = toolchain_root.absolute()
    _read_pin(root, linker, checkpoint)
    _static_executable(root, linker, checkpoint)
    _read_pin(root, linker, checkpoint)


def prepare_cpython_standalone_link_recipe(
    preparation: RSIProfilePreparation, *, standalone_profile_bytes: bytes,
    expected_standalone_profile_sha256: str,
    source_inventory_bytes: bytes, expected_source_inventory_sha256: str, zig_manifest_bytes: bytes,
    configuration_header: bytes, expected_configuration_sha256: str,
    runtime_closure: FixedRuntimeClosure | None = None,
    producer_lifecycle_profile: str | None = None,
    configuration_outputs: tuple[tuple[str, bytes], ...] | None = None,
    review_manifest_bytes: bytes | None = None,
    expected_review_manifest_sha256: str | None = None,
) -> ConcreteBuildRecipe:
    """Preserve original compilation; replace only both links, with no fallback.

    The caller separately stages every profile input beside the complete pinned
    Zig tree. No support generation, tool acquisition or target execution occurs.
    """
    from tools.static_python_rsi_fixture import link_dependency_capture as capture
    from tools.static_python_rsi_fixture.dependency_capture import MAX_DEPFILE_BYTES

    profile = _profile(standalone_profile_bytes, expected_standalone_profile_sha256)
    base = capture.prepare_cpython_dependency_recipe(
        preparation, source_inventory_bytes=source_inventory_bytes,
        expected_source_inventory_sha256=expected_source_inventory_sha256,
        zig_manifest_bytes=zig_manifest_bytes, configuration_header=configuration_header,
        expected_configuration_sha256=expected_configuration_sha256, runtime_closure=runtime_closure,
        **({"producer_lifecycle_profile": producer_lifecycle_profile}
           if producer_lifecycle_profile is not None else {}),
        **({"configuration_outputs": configuration_outputs} if configuration_outputs is not None else {}),
        **({"review_manifest_bytes": review_manifest_bytes} if review_manifest_bytes is not None else {}),
        **({"expected_review_manifest_sha256": expected_review_manifest_sha256}
           if expected_review_manifest_sha256 is not None else {}),
    )
    recipe = _recipe(base.recipe_bytes, base.sha256, version3=True)
    _, links = capture._capture_plan(recipe, instrumented=False)
    if any(row["path"].startswith("standalone-linker/") for row in recipe["inputs"]["toolchain"]):
        _fail("input_overlap")
    recipe["inputs"]["toolchain"] += profile["inputs"]
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
    _recipe(raw, _sha(raw), version3=True)
    compilations, links = capture._capture_plan(recipe, instrumented=True)
    manifest = canonical({"schema": RECIPE_SCHEMA, "recipe_sha256": _sha(raw),
                          "base_recipe_sha256": base.sha256,
                          "base_manifest_sha256": _sha(base.manifest_bytes),
                          "standalone_profile_sha256": expected_standalone_profile_sha256,
                          "compilations": compilations, "links": links, **capture._FALSE_CLAIMS})
    capture.validate_dependency_capture_plan(
        raw, expected_recipe_sha256=_sha(raw), manifest_bytes=manifest,
        expected_manifest_sha256=_sha(manifest), standalone_profile_bytes=standalone_profile_bytes,
        expected_standalone_profile_sha256=expected_standalone_profile_sha256,
    )
    return ConcreteBuildRecipe(raw, base.sources, manifest)


def prepare_cpython_standalone_link_recipe_v4(
    preparation: RSIProfilePreparation, *, standalone_profile_bytes: bytes,
    expected_standalone_profile_sha256: str,
    source_inventory_bytes: bytes, expected_source_inventory_sha256: str, zig_manifest_bytes: bytes,
    configuration_header: bytes, expected_configuration_sha256: str,
    runtime_closure: FixedRuntimeClosure | None = None,
    producer_lifecycle_profile: str | None = None,
    configuration_outputs: tuple[tuple[str, bytes], ...] | None = None,
    review_manifest_bytes: bytes | None = None,
    expected_review_manifest_sha256: str | None = None,
) -> ConcreteBuildRecipe:
    """Explicit source-data successor with the original standalone-link profile."""
    from tools.static_python_rsi_fixture.link_dependency_capture import (
        _data_source_capture_successor,
    )

    base = prepare_cpython_standalone_link_recipe(
        preparation, standalone_profile_bytes=standalone_profile_bytes,
        expected_standalone_profile_sha256=expected_standalone_profile_sha256,
        source_inventory_bytes=source_inventory_bytes,
        expected_source_inventory_sha256=expected_source_inventory_sha256,
        zig_manifest_bytes=zig_manifest_bytes, configuration_header=configuration_header,
        expected_configuration_sha256=expected_configuration_sha256, runtime_closure=runtime_closure,
        producer_lifecycle_profile=producer_lifecycle_profile,
        configuration_outputs=configuration_outputs, review_manifest_bytes=review_manifest_bytes,
        expected_review_manifest_sha256=expected_review_manifest_sha256,
    )
    return _data_source_capture_successor(
        base, original_source_inventory_sha256=expected_source_inventory_sha256,
        standalone_profile_bytes=standalone_profile_bytes,
        expected_standalone_profile_sha256=expected_standalone_profile_sha256,
    )
