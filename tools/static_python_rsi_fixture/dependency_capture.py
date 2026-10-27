"""Opt-in compiler depfiles and pinned input comparison; no custody authority.

The compiler emits its actual preprocessor dependencies, including system
headers (-MD, not -MMD). Comparison refuses dependencies outside the declared
source/toolchain inventories or previously generated outputs. It cannot prove
that those inputs remained immutable during compilation or enumerate implicit
linker inputs. No compiler or filesystem is accessed by this module.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import PurePosixPath

from tools.static_python_rsi_fixture.concrete_recipe import (
    ConcreteBuildRecipe,
    _inventory,
    prepare_cpython_build_recipe,
)
from tools.static_python_rsi_fixture.execution_backend import _recipe
from tools.static_python_rsi_fixture.installation_profile import RSIProfilePreparation
from tools.static_python_rsi_fixture.runtime_closure import FixedRuntimeClosure, canonical

MAX_DEPFILE_BYTES = 2 * 1024 * 1024
MAX_DEPENDENCIES = 16384


class CompilerDependencyError(ValueError):
    """A fixed reason; never compiler text or a private build path."""


def _fail(reason: str) -> None:
    raise CompilerDependencyError("compiler_dependency_" + reason)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _compilation(command: dict) -> tuple[str, str] | None:
    argv = command["argv"]
    if "-c" not in argv:
        return None
    if argv.count("-c") != 1 or argv.count("-o") != 1:
        _fail("compile_shape")
    try:
        source, target = argv[argv.index("-c") + 1], argv[argv.index("-o") + 1]
    except IndexError:
        _fail("compile_shape")
    if not source.startswith("@source/") or not target.startswith("@work/"):
        _fail("compile_shape")
    return source, target


def prepare_cpython_dependency_recipe(
    preparation: RSIProfilePreparation, *, source_inventory_bytes: bytes,
    expected_source_inventory_sha256: str, zig_manifest_bytes: bytes,
    configuration_header: bytes, expected_configuration_sha256: str,
    runtime_closure: FixedRuntimeClosure | None = None,
) -> ConcreteBuildRecipe:
    """Generate an explicit successor without changing the original recipe API."""
    base = prepare_cpython_build_recipe(
        preparation, source_inventory_bytes=source_inventory_bytes,
        expected_source_inventory_sha256=expected_source_inventory_sha256,
        zig_manifest_bytes=zig_manifest_bytes, configuration_header=configuration_header,
        expected_configuration_sha256=expected_configuration_sha256,
        runtime_closure=runtime_closure,
    )
    recipe = _recipe(base.recipe_bytes, base.sha256, version3=True)
    captures = []
    for stage in recipe["stages"]:
        for index, command in enumerate(stage["commands"]):
            compilation = _compilation(command)
            if compilation is None:
                continue
            source, target = compilation
            depfile = "dependencies/" + target.removeprefix("@work/") + ".d"
            command["argv"] += ["-MD", "-MF", "@work/" + depfile, "-MQ", target]
            command["outputs"].append({"path": depfile, "max_size": MAX_DEPFILE_BYTES,
                                        "executable": False})
            captures.append({"stage": stage["stage"], "command_index": index,
                             "source": source, "target": target, "depfile": depfile})
    raw = canonical(recipe)
    _recipe(raw, _sha(raw), version3=True)
    manifest = canonical({
        "schema": "lunar-cpython-compiler-dependency-recipe-v1",
        "recipe_sha256": _sha(raw), "base_recipe_sha256": base.sha256,
        "base_manifest_sha256": _sha(base.manifest_bytes), "captures": captures,
        "system_headers_included": True, "build_performed": False,
        "immutable_custody_verified": False, "implicit_link_inputs_verified": False,
        "configured_closure_verified": False, "production_admission": False,
    })
    return ConcreteBuildRecipe(raw, base.sources, manifest)


def parse_compiler_depfile(raw: bytes) -> tuple[str, tuple[str, ...]]:
    """Parse one clang/GCC make rule, rejecting variables and extra rules.

    Handle escaped whitespace, hash/colon/backslash, $$ and line continuation.
    -MP phony rules are deliberately unsupported; this recipe never enables it.
    """
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_DEPFILE_BYTES:
        _fail("depfile_bounds")
    try:
        text = raw.decode("utf-8", "strict")
    except UnicodeError:
        text = None
    if text is None:
        _fail("depfile_encoding")
    words: list[str] = []
    word: list[str] = []
    target = None
    index = 0
    ended = False

    def flush() -> None:
        if word:
            if len(words) >= MAX_DEPENDENCIES or len(word) > 4096:
                _fail("depfile_bounds")
            words.append("".join(word))
            word.clear()

    while index < len(text):
        char = text[index]
        index += 1
        if char == "\\":
            if index >= len(text):
                _fail("depfile_escape")
            char = text[index]
            index += 1
            if char == "\n":
                flush()
                continue
            if char == "\r" and text[index:index + 1] == "\n":
                index += 1
                flush()
                continue
            if char not in " \t#:\\":
                _fail("depfile_escape")
            if ended:
                _fail("depfile_rules")
            word.append(char)
        elif char == "$":
            if text[index:index + 1] != "$" or ended:
                _fail("depfile_variable")
            index += 1
            word.append("$")
        elif char == ":":
            if target is not None:
                _fail("depfile_rules")
            flush()
            if len(words) != 1:
                _fail("depfile_target")
            target = words.pop()
        elif char in " \t\r\n":
            flush()
            if char in "\r\n" and target is not None:
                ended = True
        elif char == "#" or ord(char) < 32 or ord(char) == 127 or ended:
            _fail("depfile_syntax")
        else:
            word.append(char)
        if len(word) > 4096:
            _fail("depfile_bounds")
    flush()
    if target is None or not words or len(words) != len(set(words)):
        _fail("depfile_shape")
    return target, tuple(words)


def _roots(source_root: str, toolchain_root: str, work_root: str) -> dict[str, str]:
    roots = {"source": source_root, "toolchain": toolchain_root, "work": work_root}
    for root in roots.values():
        if (type(root) is not str or not root.startswith("/") or root == "/"
                or len(root) > 2048 or str(PurePosixPath(root)) != root
                or any(p in {"", ".", ".."} for p in root.split("/")[1:])
                or any(ord(char) < 32 or ord(char) == 127 for char in root)):
            _fail("roots")
    for left, value in roots.items():
        if any(value == other or value.startswith(other + "/") or other.startswith(value + "/")
               for right, other in roots.items() if left != right):
            _fail("roots")
    return roots


def _current_output_root(value: str | None, roots: dict[str, str]) -> str:
    """A target-only root never adds current files to the prior-input universe."""
    if value is None:
        return roots["work"]
    checked = _roots(roots["source"], roots["toolchain"], value)["work"]
    prior = roots["work"]
    if checked == prior or checked.startswith(prior + "/") or prior.startswith(checked + "/"):
        _fail("current_output_root")
    return checked


@dataclass(frozen=True, slots=True)
class CompilerDependencyComparison:
    canonical_bytes: bytes

    def to_dict(self) -> dict:
        return json.loads(self.canonical_bytes)


def compare_compiler_dependencies(
    recipe_bytes: bytes, *, expected_recipe_sha256: str,
    output_inventory_bytes: bytes, expected_output_inventory_sha256: str,
    dependency_artifacts: dict[str, bytes], source_root: str, toolchain_root: str, work_root: str,
    current_output_root: str | None = None,
) -> CompilerDependencyComparison:
    """Compare retained compiler bytes against independently pinned inventories.

    The output inventory must be retained from actual command readback. Pins
    are comparison inputs, not evidence of acquisition or an accepted build.
    No current path is opened or inferred from ambient state.
    """
    recipe = _recipe(recipe_bytes, expected_recipe_sha256, version3=True)
    outputs = _inventory(output_inventory_bytes, expected_output_inventory_sha256)
    roots = _roots(source_root, toolchain_root, work_root)
    target_root = _current_output_root(current_output_root, roots)
    if (type(dependency_artifacts) is not dict or len(dependency_artifacts) > 1024
            or any(type(key) is not str or type(raw) is not bytes
                   or not 0 < len(raw) <= MAX_DEPFILE_BYTES
                   for key, raw in dependency_artifacts.items())
            or sum(len(raw) for raw in dependency_artifacts.values()) > 16 * 1024 * 1024):
        _fail("artifacts")
    available = {role: {record["path"]: record for record in recipe["inputs"][role]}
                 for role in ("source", "toolchain")}
    available["work"] = {}
    seen = set()
    compiled = []

    def reference(path: str) -> str:
        if not path.startswith("/"):
            path = roots["work"] + "/" + path
        if (str(PurePosixPath(path)) != path
                or any(part in {"", ".", ".."} for part in path.split("/")[1:])):
            _fail("dependency_path")
        for role, root in roots.items():
            if path.startswith(root + "/"):
                relative = path[len(root) + 1:]
                if relative not in available[role]:
                    _fail("dependency_unpinned")
                return "@" + role + "/" + relative
        _fail("dependency_external")

    for stage in recipe["stages"]:
        for index, command in enumerate(stage["commands"]):
            compilation = _compilation(command)
            if compilation is not None:
                source, target = compilation
                argv = command["argv"]
                depfile = "dependencies/" + target.removeprefix("@work/") + ".d"
                if (argv[-5:] != ["-MD", "-MF", "@work/" + depfile, "-MQ", target]
                        or any(flag in argv[:-5] for flag in ("-MD", "-MMD", "-MF", "-MT", "-MQ", "-MP"))
                        or {"path": depfile, "max_size": MAX_DEPFILE_BYTES, "executable": False}
                        not in command["outputs"]):
                    _fail("capture_missing")
                raw = dependency_artifacts.get(depfile)
                record = outputs.get(depfile)
                if (type(raw) is not bytes or record is None or record["executable"]
                        or len(raw) != record["size"] or _sha(raw) != record["sha256"]):
                    _fail("artifact_pin")
                actual_target, dependencies = parse_compiler_depfile(raw)
                expected_target = target_root + "/" + target.removeprefix("@work/")
                if actual_target != expected_target:
                    _fail("target")
                refs = [reference(path) for path in dependencies]
                if source not in refs:
                    _fail("source_missing")
                compiled.append({"stage": stage["stage"], "command_index": index,
                                 "target": target, "depfile_sha256": _sha(raw),
                                 "dependencies": sorted(set(refs))})
                seen.add(depfile)
            for output in command["outputs"]:
                record = outputs.get(output["path"])
                if (record is None or record["size"] > output["max_size"]
                        or record["executable"] is not output["executable"]):
                    _fail("output_inventory")
                available["work"][output["path"]] = record
    if set(dependency_artifacts) != seen or set(outputs) != set(available["work"]) or not compiled:
        _fail("artifact_set")
    raw = canonical({
        "schema": "lunar-cpython-compiler-dependency-comparison-v1",
        "recipe_sha256": expected_recipe_sha256,
        "output_inventory_sha256": expected_output_inventory_sha256,
        "compilations": compiled, "evidence_scope": "retained-compiler-byte-comparison",
        "immutable_custody_verified": False, "implicit_link_inputs_verified": False,
        "configured_closure_verified": False, "installation_accepted": False,
        "production_admission": False,
    })
    return CompilerDependencyComparison(raw)
