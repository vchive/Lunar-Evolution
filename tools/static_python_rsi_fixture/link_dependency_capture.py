"""Explicit linker depfile outputs and comparison, without build/custody authority.

The successor retains every original compiler capture and instruments the two
Zig/LLD static links. LLD's reported inputs are compared, not promoted to a proof
of every file opened by the compiler driver, an immutable build, or installation.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from tools.static_python_rsi_fixture.concrete_recipe import ConcreteBuildRecipe, _inventory
from tools.static_python_rsi_fixture.dependency_capture import (
    MAX_DEPENDENCIES,
    MAX_DEPFILE_BYTES,
    CompilerDependencyError,
    _compilation,
    _roots,
    parse_compiler_depfile,
    prepare_cpython_dependency_recipe,
)
from tools.static_python_rsi_fixture.execution_backend import _recipe
from tools.static_python_rsi_fixture.installation_profile import RSIProfilePreparation
from tools.static_python_rsi_fixture.runtime_closure import FixedRuntimeClosure, canonical

_SCHEMA = "lunar-cpython-compiler-linker-dependency-recipe-v1"
_FALSE_CLAIMS = {
    "build_performed": False, "immutable_custody_verified": False,
    "implicit_link_inputs_verified": False, "driver_inputs_verified": False,
    "configured_closure_verified": False, "installation_accepted": False,
    "production_admission": False, "online_publication": False,
}


class LinkDependencyError(ValueError):
    """Fixed refusals, without linker prose or private paths."""


def _fail(reason: str) -> None:
    raise LinkDependencyError("link_dependency_" + reason)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _link(command: dict) -> tuple[str, list[str]] | None:
    argv = command["argv"]
    if argv[:2] != ["@toolchain/zig", "cc"] or "-c" in argv:
        return None
    prefix = ["@toolchain/zig", "cc", "-target", "x86_64-linux-musl", "--zig-lib-dir",
              "@toolchain-dir/lib", "-static", "-o"]
    if argv[:8] != prefix or argv.count("-o") != 1 or len(argv) < 13:
        _fail("link_shape")
    target = argv[8]
    if not target.startswith("@work/bin/lunar-"):
        _fail("link_target")
    end = argv.index("-lm") if "-lm" in argv else -1
    if end < 10 or argv[end:end + 3] != ["-lm", "-lpthread", "-lc"]:
        _fail("link_shape")
    inputs = argv[9:end]
    if (len(inputs) != len(set(inputs))
            or any(not path.startswith("@work/") or not path.endswith((".o", ".a"))
                   for path in inputs)):
        _fail("link_inputs")
    return target, inputs


def _capture_plan(recipe: dict, *, instrumented: bool) -> tuple[list[dict], list[dict]]:
    compilations, links = [], []
    for stage in recipe["stages"]:
        for index, command in enumerate(stage["commands"]):
            compilation = _compilation(command)
            if compilation is not None:
                source, target = compilation
                depfile = "dependencies/" + target.removeprefix("@work/") + ".d"
                if (command["argv"][-5:] != ["-MD", "-MF", "@work/" + depfile, "-MQ", target]
                        or {"path": depfile, "max_size": MAX_DEPFILE_BYTES, "executable": False}
                        not in command["outputs"]):
                    _fail("compiler_capture_missing")
                compilations.append({"stage": stage["stage"], "command_index": index,
                                     "source": source, "target": target, "depfile": depfile})
            link = _link(command)
            if link is None:
                continue
            target, inputs = link
            depfile = "link-dependencies/" + target.removeprefix("@work/") + ".d"
            suffix = ["-Xlinker", "--dependency-file", "-Xlinker", "@work/" + depfile]
            expected = {"path": depfile, "max_size": MAX_DEPFILE_BYTES, "executable": False}
            if instrumented:
                if command["argv"][-4:] != suffix or expected not in command["outputs"]:
                    _fail("link_capture_missing")
                tail = command["argv"][command["argv"].index("-lm") + 3:-4]
            else:
                tail = command["argv"][command["argv"].index("-lm") + 3:]
            if tail:
                _fail("link_shape")
            links.append({"stage": stage["stage"], "command_index": index, "target": target,
                          "explicit_inputs": inputs, "depfile": depfile})
    if (not compilations or len(links) != 2 or links[0]["stage"] != "freeze"
            or links[0]["target"] != "@work/bin/lunar-freeze-module"
            or links[1]["stage"] != "link"
            or links[1]["target"] not in {"@work/bin/lunar-marker-fixture",
                                           "@work/bin/lunar-openevolve", "@work/bin/lunar-shinka"}):
        _fail("capture_set")
    return compilations, links


def prepare_cpython_link_dependency_recipe(
    preparation: RSIProfilePreparation, *, source_inventory_bytes: bytes,
    expected_source_inventory_sha256: str, zig_manifest_bytes: bytes,
    configuration_header: bytes, expected_configuration_sha256: str,
    runtime_closure: FixedRuntimeClosure | None = None,
) -> ConcreteBuildRecipe:
    """Explicit opt-in successor; default concrete/compiler recipes stay unchanged."""
    base = prepare_cpython_dependency_recipe(
        preparation, source_inventory_bytes=source_inventory_bytes,
        expected_source_inventory_sha256=expected_source_inventory_sha256,
        zig_manifest_bytes=zig_manifest_bytes, configuration_header=configuration_header,
        expected_configuration_sha256=expected_configuration_sha256,
        runtime_closure=runtime_closure,
    )
    recipe = _recipe(base.recipe_bytes, base.sha256, version3=True)
    _, links = _capture_plan(recipe, instrumented=False)
    for link in links:
        command = next(stage for stage in recipe["stages"] if stage["stage"] == link["stage"])[
            "commands"][link["command_index"]]
        command["argv"] += ["-Xlinker", "--dependency-file", "-Xlinker", "@work/" + link["depfile"]]
        command["outputs"].append({"path": link["depfile"], "max_size": MAX_DEPFILE_BYTES,
                                    "executable": False})
    raw = canonical(recipe)
    _recipe(raw, _sha(raw), version3=True)
    compilations, links = _capture_plan(recipe, instrumented=True)
    manifest = canonical({"schema": _SCHEMA, "recipe_sha256": _sha(raw),
                          "base_recipe_sha256": base.sha256,
                          "base_manifest_sha256": _sha(base.manifest_bytes),
                          "compilations": compilations, "links": links, **_FALSE_CLAIMS})
    return ConcreteBuildRecipe(raw, base.sources, manifest)


def validate_dependency_capture_plan(
    recipe_bytes: bytes, *, expected_recipe_sha256: str,
    manifest_bytes: bytes, expected_manifest_sha256: str,
) -> tuple[dict, tuple[str, ...], tuple[str, ...]]:
    """Bind the exact capture commands and declared outputs before dispatch."""
    recipe = _recipe(recipe_bytes, expected_recipe_sha256, version3=True)
    compilations, links = _capture_plan(recipe, instrumented=True)
    if (type(manifest_bytes) is not bytes or not 0 < len(manifest_bytes) <= 1024 * 1024
            or type(expected_manifest_sha256) is not str
            or _sha(manifest_bytes) != expected_manifest_sha256):
        _fail("manifest_pin")
    invalid = False
    try:
        manifest = json.loads(manifest_bytes)
        expected_keys = {"schema", "recipe_sha256", "base_recipe_sha256", "base_manifest_sha256",
                         "compilations", "links", *_FALSE_CLAIMS}
        invalid = (type(manifest) is not dict or set(manifest) != expected_keys
                   or canonical(manifest) != manifest_bytes or manifest["schema"] != _SCHEMA
                   or manifest["recipe_sha256"] != expected_recipe_sha256
                   or canonical(manifest["compilations"]) != canonical(compilations)
                   or canonical(manifest["links"]) != canonical(links)
                   or any(manifest[key] is not value for key, value in _FALSE_CLAIMS.items())
                   or any(type(manifest[key]) is not str or len(manifest[key]) != 64
                          or any(c not in "0123456789abcdef" for c in manifest[key])
                          for key in ("base_recipe_sha256", "base_manifest_sha256")))
    except (ValueError, TypeError, UnicodeError, RecursionError):
        invalid = True
    if invalid:
        _fail("manifest")
    return (recipe, tuple(row["depfile"] for row in compilations),
            tuple(row["depfile"] for row in links))


def parse_linker_depfile(raw: bytes) -> tuple[str, tuple[str, ...]]:
    """Read LLD's main rule and optional exact empty rules for its prerequisites."""
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_DEPFILE_BYTES:
        _fail("depfile_bounds")
    rules, current = [], bytearray()
    index = 0
    while index < len(raw):
        char = raw[index:index + 1]
        current += char
        index += 1
        if char == b"\\" and index < len(raw):
            current += raw[index:index + 1]
            if raw[index:index + 2] == b"\r\n":
                current += b"\n"
                index += 1
            index += 1
        elif char in {b"\n", b"\r"}:
            if current.strip():
                rules.append(bytes(current))
                if len(rules) > MAX_DEPENDENCIES + 1:
                    _fail("depfile_bounds")
            current.clear()
    if current.strip():
        rules.append(bytes(current))
    if len(rules) > MAX_DEPENDENCIES + 1:
        _fail("depfile_bounds")
    if not rules:
        _fail("depfile_shape")
    invalid = False
    try:
        target, dependencies = parse_compiler_depfile(rules[0])
        phony = []
        for rule in rules[1:]:
            name, values = parse_compiler_depfile(rule.rstrip(b"\r\n") + b" __lunar_phony_marker__\n")
            if values != ("__lunar_phony_marker__",):
                invalid = True
            phony.append(name)
        if phony and (len(phony) != len(set(phony)) or set(phony) != set(dependencies)):
            invalid = True
    except CompilerDependencyError:
        invalid = True
    if invalid:
        _fail("depfile_syntax")
    return target, dependencies


@dataclass(frozen=True, slots=True)
class LinkerDependencyComparison:
    canonical_bytes: bytes

    def to_dict(self) -> dict:
        return json.loads(self.canonical_bytes)


def compare_linker_dependencies(
    recipe_bytes: bytes, *, expected_recipe_sha256: str,
    manifest_bytes: bytes, expected_manifest_sha256: str,
    output_inventory_bytes: bytes, expected_output_inventory_sha256: str,
    dependency_artifacts: dict[str, bytes], source_root: str, toolchain_root: str, work_root: str,
) -> LinkerDependencyComparison:
    """Compare retained linker reports; unresolved driver/cache inputs refuse."""
    recipe, _, depfiles = validate_dependency_capture_plan(
        recipe_bytes, expected_recipe_sha256=expected_recipe_sha256,
        manifest_bytes=manifest_bytes, expected_manifest_sha256=expected_manifest_sha256,
    )
    outputs = _inventory(output_inventory_bytes, expected_output_inventory_sha256)
    roots = _roots(source_root, toolchain_root, work_root)
    if (type(dependency_artifacts) is not dict or set(dependency_artifacts) != set(depfiles)
            or any(type(raw) is not bytes or not 0 < len(raw) <= MAX_DEPFILE_BYTES
                   for raw in dependency_artifacts.values())):
        _fail("artifact_set")
    available = {role: {r["path"]: r for r in recipe["inputs"][role]}
                 for role in ("source", "toolchain")}
    available["work"] = {}
    captures = {row["target"]: row for row in _capture_plan(recipe, instrumented=True)[1]}
    compared = []
    for stage in recipe["stages"]:
        for index, command in enumerate(stage["commands"]):
            link = _link(command)
            if link is not None:
                target, explicit = link
                depfile = captures[target]["depfile"]
                raw, record = dependency_artifacts[depfile], outputs.get(depfile)
                if (record is None or record["executable"] or len(raw) != record["size"]
                        or _sha(raw) != record["sha256"]):
                    _fail("artifact_pin")
                actual_target, dependencies = parse_linker_depfile(raw)
                if actual_target != roots["work"] + "/" + target.removeprefix("@work/"):
                    _fail("target")
                refs = []
                for path in dependencies:
                    # LLD records relative names relative to its original cwd.
                    if not path.startswith("/"):
                        path = roots["work"] + "/" + path
                    if any(part in {"", ".", ".."} for part in path.split("/")[1:]):
                        _fail("dependency_path")
                    matches = [(role, path[len(root) + 1:]) for role, root in roots.items()
                               if path.startswith(root + "/")]
                    if not matches:
                        _fail("dependency_external")
                    role, relative = matches[0]
                    if relative not in available[role]:
                        _fail("dependency_unpinned")
                    refs.append("@" + role + "/" + relative)
                if not set(explicit).issubset(refs):
                    _fail("explicit_input_missing")
                compared.append({"stage": stage["stage"], "command_index": index,
                                 "target": target, "depfile_sha256": _sha(raw),
                                 "dependencies": sorted(refs)})
            for output in command["outputs"]:
                record = outputs.get(output["path"])
                if (record is None or record["size"] > output["max_size"]
                        or record["executable"] is not output["executable"]):
                    _fail("output_inventory")
                available["work"][output["path"]] = record
    if set(outputs) != set(available["work"]):
        _fail("output_inventory")
    raw = canonical({"schema": "lunar-cpython-linker-dependency-comparison-v1",
                     "recipe_sha256": expected_recipe_sha256,
                     "manifest_sha256": expected_manifest_sha256,
                     "output_inventory_sha256": expected_output_inventory_sha256,
                     "links": compared, "evidence_scope": "retained-linker-byte-comparison",
                     **_FALSE_CLAIMS})
    return LinkerDependencyComparison(raw)
