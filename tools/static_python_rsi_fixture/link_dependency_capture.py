"""Explicit linker depfile outputs and comparison, without build/custody authority.

The successor retains every original compiler capture and instruments the two
Zig/LLD static links. LLD's reported inputs are compared, not promoted to a proof
of every file opened by the compiler driver, an immutable build, or installation.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from tools.static_python_rsi_fixture.concrete_recipe import (
    ConcreteBuildRecipe,
    _inventory,
    _source_data_successor,
)
from tools.static_python_rsi_fixture.dependency_capture import (
    MAX_DEPENDENCIES,
    MAX_DEPFILE_BYTES,
    CompilerDependencyError,
    _compilation,
    _current_output_root,
    _roots,
    parse_compiler_depfile,
    prepare_cpython_dependency_recipe,
)
from tools.static_python_rsi_fixture.execution_backend import _recipe
from tools.static_python_rsi_fixture.installation_profile import RSIProfilePreparation
from tools.static_python_rsi_fixture.runtime_closure import FixedRuntimeClosure, canonical
from tools.static_python_rsi_fixture.standalone_linker import (
    RECIPE_SCHEMA as STANDALONE_RECIPE_SCHEMA,
)
from tools.static_python_rsi_fixture.standalone_linker import (
    StandaloneLinkerError,
    _standalone_link,
    validate_standalone_recipe_profile,
)
from tools.static_python_rsi_fixture.zig_lld_linker import (
    ZigLLDLinkerError,
    _zig_lld_link,
    validate_zig_lld_recipe_profile,
)

_SCHEMA = "lunar-cpython-compiler-linker-dependency-recipe-v1"
DATA_SOURCE_CAPTURE_SCHEMA = "lunar-cpython-data-source-dependency-recipe-v1"
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


def _explicit_support_link(command: dict) -> bool:
    return command["argv"][:6] == [
        "@toolchain/zig", "cc", "-target", "x86_64-linux-musl", "-static", "-nostdlib",
    ]


def _link(command: dict) -> tuple[str, list[str]] | None:
    argv = command["argv"]
    try:
        direct = _standalone_link(command)
    except StandaloneLinkerError:
        _fail("standalone_shape")
    if direct is not None:
        return direct
    try:
        direct = _zig_lld_link(command)
    except ZigLLDLinkerError:
        _fail("zig_lld_shape")
    if direct is not None:
        return direct
    if argv[:2] != ["@toolchain/zig", "cc"] or "-c" in argv:
        return None
    prefix = ["@toolchain/zig", "cc", "-target", "x86_64-linux-musl", "-static", "-o"]
    explicit = _explicit_support_link(command)
    if explicit:
        prefix = prefix[:-1] + ["-nostdlib", "-o"]
    if argv[:len(prefix)] != prefix or argv.count("-o") != 1 or len(argv) < len(prefix) + 5:
        _fail("link_shape")
    target = argv[len(prefix)]
    if not target.startswith("@work/bin/lunar-"):
        _fail("link_target")
    if explicit:
        head = ["@toolchain/lunar-support/crt1.o", "@toolchain/lunar-support/crti.o"]
        tail = ["-Xlinker", "--start-group", "@toolchain/lunar-support/libc.a",
                "@toolchain/lunar-support/libcompiler_rt.a", "-Xlinker", "--end-group",
                "@toolchain/lunar-support/crtn.o"]
        body = argv[len(prefix) + 1:]
        suffix = ["-Xlinker", "--dependency-file", "-Xlinker",
                  "@work/link-dependencies/" + target.removeprefix("@work/") + ".d"]
        if body[-4:] == suffix:
            body = body[:-4]
        if body[:2] != head or body[-7:] != tail:
            _fail("explicit_support_shape")
        inputs = body[2:-7]
    else:
        end = argv.index("-lm") if "-lm" in argv else -1
        if end < len(prefix) + 2 or argv[end:end + 3] != ["-lm", "-lpthread", "-lc"]:
            _fail("link_shape")
        inputs = argv[len(prefix) + 1:end]
    if (not inputs or len(inputs) != len(set(inputs))
            or any(not path.startswith("@work/") or not path.endswith((".o", ".a"))
                   for path in inputs)):
        _fail("link_inputs")
    if explicit:
        inputs = [*head, *inputs, "@toolchain/lunar-support/libc.a",
                  "@toolchain/lunar-support/libcompiler_rt.a", "@toolchain/lunar-support/crtn.o"]
    return target, inputs


def _link_mode(command: dict) -> str:
    if _standalone_link(command) is not None:
        return "standalone"
    if _zig_lld_link(command) is not None:
        return "zig-lld"
    return "explicit" if _explicit_support_link(command) else "implicit"


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
            direct = _link_mode(command) in {"standalone", "zig-lld"}
            suffix = (["--dependency-file", "@work/" + depfile] if direct else
                      ["-Xlinker", "--dependency-file", "-Xlinker", "@work/" + depfile])
            expected = {"path": depfile, "max_size": MAX_DEPFILE_BYTES, "executable": False}
            if instrumented:
                if command["argv"][-len(suffix):] != suffix or expected not in command["outputs"]:
                    _fail("link_capture_missing")
                tail = ([] if direct or _explicit_support_link(command) else
                        command["argv"][command["argv"].index("-lm") + 3:-4])
            else:
                if direct:
                    _fail("standalone_requires_capture")
                tail = [] if _explicit_support_link(command) else command["argv"][command["argv"].index("-lm") + 3:]
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
    producer_lifecycle_profile: str | None = None,
    configuration_outputs: tuple[tuple[str, bytes], ...] | None = None,
    review_manifest_bytes: bytes | None = None,
    expected_review_manifest_sha256: str | None = None,
) -> ConcreteBuildRecipe:
    """Explicit opt-in successor; default concrete/compiler recipes stay unchanged."""
    base = prepare_cpython_dependency_recipe(
        preparation, source_inventory_bytes=source_inventory_bytes,
        expected_source_inventory_sha256=expected_source_inventory_sha256,
        zig_manifest_bytes=zig_manifest_bytes, configuration_header=configuration_header,
        expected_configuration_sha256=expected_configuration_sha256,
        runtime_closure=runtime_closure,
        **({"producer_lifecycle_profile": producer_lifecycle_profile}
           if producer_lifecycle_profile is not None else {}),
        **({"configuration_outputs": configuration_outputs} if configuration_outputs is not None else {}),
        **({"review_manifest_bytes": review_manifest_bytes} if review_manifest_bytes is not None else {}),
        **({"expected_review_manifest_sha256": expected_review_manifest_sha256}
           if expected_review_manifest_sha256 is not None else {}),
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
    standalone_profile_bytes: bytes | None = None,
    expected_standalone_profile_sha256: str | None = None,
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
        explicit_schema = "lunar-cpython-explicit-support-link-recipe-v1"
        explicit = type(manifest) is dict and manifest.get("schema") == explicit_schema
        standalone = type(manifest) is dict and manifest.get("schema") == STANDALONE_RECIPE_SCHEMA
        expected_keys = {"schema", "recipe_sha256", "base_recipe_sha256", "base_manifest_sha256",
                         "compilations", "links", *_FALSE_CLAIMS}
        if explicit:
            expected_keys.add("support_bundle_sha256")
        if standalone:
            expected_keys.add("standalone_profile_sha256")
        actual_modes = [_link_mode(command)
                        for stage in recipe["stages"]
                        for command in stage["commands"] if _link(command) is not None]
        expected_mode = "standalone" if standalone else "explicit" if explicit else "implicit"
        invalid = (type(manifest) is not dict or set(manifest) != expected_keys
                   or canonical(manifest) != manifest_bytes
                   or manifest["schema"] not in {_SCHEMA, explicit_schema, STANDALONE_RECIPE_SCHEMA}
                   or actual_modes != [expected_mode, expected_mode]
                   or manifest["recipe_sha256"] != expected_recipe_sha256
                   or canonical(manifest["compilations"]) != canonical(compilations)
                   or canonical(manifest["links"]) != canonical(links)
                   or any(manifest[key] is not value for key, value in _FALSE_CLAIMS.items())
                   or any(type(manifest[key]) is not str or len(manifest[key]) != 64
                          or any(c not in "0123456789abcdef" for c in manifest[key])
                          for key in ("base_recipe_sha256", "base_manifest_sha256",
                                      *(["support_bundle_sha256"] if explicit else []),
                                      *(["standalone_profile_sha256"] if standalone else []))))
        if not invalid and standalone:
            if manifest["standalone_profile_sha256"] != expected_standalone_profile_sha256:
                invalid = True
            else:
                validate_standalone_recipe_profile(
                    recipe, profile_bytes=standalone_profile_bytes,
                    expected_profile_sha256=expected_standalone_profile_sha256,
                )
        elif standalone_profile_bytes is not None or expected_standalone_profile_sha256 is not None:
            invalid = True
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
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


def _compare_linker_dependencies(
    recipe: dict, depfiles: tuple[str, ...], *, expected_recipe_sha256: str,
    expected_manifest_sha256: str,
    output_inventory_bytes: bytes, expected_output_inventory_sha256: str,
    dependency_artifacts: dict[str, bytes], source_root: str, toolchain_root: str, work_root: str,
    current_output_root: str | None = None,
    comparison_binding: dict | None = None,
) -> LinkerDependencyComparison:
    """Compare retained linker reports; unresolved driver/cache inputs refuse."""
    outputs = _inventory(output_inventory_bytes, expected_output_inventory_sha256)
    roots = _roots(source_root, toolchain_root, work_root)
    target_root = _current_output_root(current_output_root, roots)
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
                if actual_target != target_root + "/" + target.removeprefix("@work/"):
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
                if (_link_mode(command) in {"explicit", "standalone", "zig-lld"}
                        and set(explicit) != set(refs)):
                    _fail("explicit_support_input_set")
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
                     **_FALSE_CLAIMS, **(comparison_binding or {})})
    return LinkerDependencyComparison(raw)


def _data_source_capture_successor(
    base: ConcreteBuildRecipe, *, original_source_inventory_sha256: str,
    standalone_profile_bytes: bytes | None = None,
    expected_standalone_profile_sha256: str | None = None,
    zig_lld_profile_bytes: bytes | None = None,
    expected_zig_lld_profile_sha256: str | None = None,
) -> ConcreteBuildRecipe:
    """Bind a freshly emitted complete legacy capture to the explicit new view.

    Original inventory/base-manifest digests are generation-stage provenance
    assertions under the caller's independent manifest pin. The consumer cannot
    reconstruct the pre-overlay inventory or independently reacquire its origin.
    """
    raw, recipe = _source_data_successor(base)
    compilations, links = _capture_plan(recipe, instrumented=True)
    modes = [_link_mode(command)
             for stage in recipe["stages"] for command in stage["commands"]
             if _link(command) is not None]
    if len(set(modes)) != 1:
        _fail("capture_modes")
    manifest = canonical({
        "schema": DATA_SOURCE_CAPTURE_SCHEMA, "recipe_sha256": _sha(raw),
        "base_recipe_sha256": base.sha256, "base_manifest_sha256": _sha(base.manifest_bytes),
        "original_source_inventory_sha256": original_source_inventory_sha256,
        "source_inventory_sha256": _sha(canonical(recipe["inputs"]["source"])),
        "toolchain_inventory_sha256": _sha(canonical(recipe["inputs"]["toolchain"])),
        "inputs_sha256": _sha(canonical(recipe["inputs"])),
        "input_projection": recipe["input_projection"], "link_mode": modes[0],
        **({"standalone_profile_sha256": expected_standalone_profile_sha256}
           if modes[0] == "standalone" else {}),
        **({"zig_lld_profile_sha256": expected_zig_lld_profile_sha256}
           if modes[0] == "zig-lld" else {}),
        "compilations": compilations, "links": links, **_FALSE_CLAIMS,
    })
    validate_dependency_capture_plan_v4(
        raw, expected_recipe_sha256=_sha(raw), manifest_bytes=manifest,
        expected_manifest_sha256=_sha(manifest), standalone_profile_bytes=standalone_profile_bytes,
        expected_standalone_profile_sha256=expected_standalone_profile_sha256,
        zig_lld_profile_bytes=zig_lld_profile_bytes,
        expected_zig_lld_profile_sha256=expected_zig_lld_profile_sha256,
    )
    return ConcreteBuildRecipe(raw, base.sources, manifest)


def prepare_cpython_link_dependency_recipe_v4(
    preparation: RSIProfilePreparation, *, source_inventory_bytes: bytes,
    expected_source_inventory_sha256: str, zig_manifest_bytes: bytes,
    configuration_header: bytes, expected_configuration_sha256: str,
    runtime_closure: FixedRuntimeClosure | None = None,
    producer_lifecycle_profile: str | None = None,
    configuration_outputs: tuple[tuple[str, bytes], ...] | None = None,
    review_manifest_bytes: bytes | None = None,
    expected_review_manifest_sha256: str | None = None,
) -> ConcreteBuildRecipe:
    """Emit a new v4 recipe with the original complete compiler/linker plan."""
    base = prepare_cpython_link_dependency_recipe(
        preparation, source_inventory_bytes=source_inventory_bytes,
        expected_source_inventory_sha256=expected_source_inventory_sha256,
        zig_manifest_bytes=zig_manifest_bytes, configuration_header=configuration_header,
        expected_configuration_sha256=expected_configuration_sha256, runtime_closure=runtime_closure,
        producer_lifecycle_profile=producer_lifecycle_profile,
        configuration_outputs=configuration_outputs, review_manifest_bytes=review_manifest_bytes,
        expected_review_manifest_sha256=expected_review_manifest_sha256,
    )
    return _data_source_capture_successor(
        base, original_source_inventory_sha256=expected_source_inventory_sha256,
    )


def validate_dependency_capture_plan_v4(
    recipe_bytes: bytes, *, expected_recipe_sha256: str,
    manifest_bytes: bytes, expected_manifest_sha256: str,
    standalone_profile_bytes: bytes | None = None,
    expected_standalone_profile_sha256: str | None = None,
    zig_lld_profile_bytes: bytes | None = None,
    expected_zig_lld_profile_sha256: str | None = None,
) -> tuple[dict, tuple[str, ...], tuple[str, ...]]:
    """Bind every v4 input and finite capture, never accept a legacy schema.

    Final source/toolchain/combined inventories and the complete prior v3 recipe
    are reconstructed and compared. Original source inventory/base-manifest
    digests remain pinned emitter provenance assertions, not independently
    revalidated original-source or custody authority.
    """
    from tools.static_python_rsi_fixture.command_input_graph import (
        validate_dependency_command_graph_v4,
    )
    from tools.static_python_rsi_fixture.execution_backend import (
        INPUT_PROJECTION_V4,
        RECIPE_V3_SCHEMA,
    )

    recipe = _recipe(recipe_bytes, expected_recipe_sha256, version4=True)
    validate_dependency_command_graph_v4(recipe)
    compilations, links = _capture_plan(recipe, instrumented=True)
    if (type(manifest_bytes) is not bytes or not 0 < len(manifest_bytes) <= 1024 * 1024
            or type(expected_manifest_sha256) is not str
            or _sha(manifest_bytes) != expected_manifest_sha256):
        _fail("manifest_pin")
    invalid = False
    try:
        manifest = json.loads(manifest_bytes)
        modes = [_link_mode(command)
                 for stage in recipe["stages"] for command in stage["commands"]
                 if _link(command) is not None]
        standalone = modes == ["standalone", "standalone"]
        zig_lld = modes == ["zig-lld", "zig-lld"]
        expected_keys = {
            "schema", "recipe_sha256", "base_recipe_sha256", "base_manifest_sha256",
            "original_source_inventory_sha256", "source_inventory_sha256",
            "toolchain_inventory_sha256", "inputs_sha256", "input_projection", "link_mode",
            "compilations", "links", *_FALSE_CLAIMS,
            *({"standalone_profile_sha256"} if standalone else set()),
            *({"zig_lld_profile_sha256"} if zig_lld else set()),
        }
        original = {key: value for key, value in recipe.items() if key != "input_projection"}
        original["schema"] = RECIPE_V3_SCHEMA
        digest_keys = ("base_recipe_sha256", "base_manifest_sha256", "original_source_inventory_sha256",
                       "source_inventory_sha256", "toolchain_inventory_sha256", "inputs_sha256",
                       *(("standalone_profile_sha256",) if standalone else ()),
                       *(("zig_lld_profile_sha256",) if zig_lld else ()))
        invalid = (type(manifest) is not dict or set(manifest) != expected_keys
                   or canonical(manifest) != manifest_bytes
                   or manifest["schema"] != DATA_SOURCE_CAPTURE_SCHEMA
                   or manifest["input_projection"] != INPUT_PROJECTION_V4
                   or modes != [manifest["link_mode"], manifest["link_mode"]]
                   or manifest["recipe_sha256"] != expected_recipe_sha256
                   or manifest["base_recipe_sha256"] != _sha(canonical(original))
                   or manifest["source_inventory_sha256"] != _sha(canonical(recipe["inputs"]["source"]))
                   or manifest["toolchain_inventory_sha256"] != _sha(canonical(recipe["inputs"]["toolchain"]))
                   or manifest["inputs_sha256"] != _sha(canonical(recipe["inputs"]))
                   or canonical(manifest["compilations"]) != canonical(compilations)
                   or canonical(manifest["links"]) != canonical(links)
                   or any(manifest[key] is not value for key, value in _FALSE_CLAIMS.items())
                   or any(type(manifest[key]) is not str or len(manifest[key]) != 64
                          or any(c not in "0123456789abcdef" for c in manifest[key])
                          for key in digest_keys))
        if not invalid and standalone:
            if manifest["standalone_profile_sha256"] != expected_standalone_profile_sha256:
                invalid = True
            else:
                validate_standalone_recipe_profile(
                    recipe, profile_bytes=standalone_profile_bytes,
                    expected_profile_sha256=expected_standalone_profile_sha256,
                )
        elif standalone_profile_bytes is not None or expected_standalone_profile_sha256 is not None:
            invalid = True
        if not invalid and zig_lld:
            if manifest["zig_lld_profile_sha256"] != expected_zig_lld_profile_sha256:
                invalid = True
            else:
                validate_zig_lld_recipe_profile(
                    recipe, profile_bytes=zig_lld_profile_bytes,
                    expected_profile_sha256=expected_zig_lld_profile_sha256,
                )
        elif zig_lld_profile_bytes is not None or expected_zig_lld_profile_sha256 is not None:
            invalid = True
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        invalid = True
    if invalid:
        _fail("manifest")
    return (recipe, tuple(row["depfile"] for row in compilations),
            tuple(row["depfile"] for row in links))


def compare_linker_dependencies(
    recipe_bytes: bytes, *, expected_recipe_sha256: str,
    manifest_bytes: bytes, expected_manifest_sha256: str,
    output_inventory_bytes: bytes, expected_output_inventory_sha256: str,
    dependency_artifacts: dict[str, bytes], source_root: str, toolchain_root: str, work_root: str,
    current_output_root: str | None = None,
    standalone_profile_bytes: bytes | None = None,
    expected_standalone_profile_sha256: str | None = None,
) -> LinkerDependencyComparison:
    """Compare only the original v3 retained linker evidence."""
    recipe, _, depfiles = validate_dependency_capture_plan(
        recipe_bytes, expected_recipe_sha256=expected_recipe_sha256,
        manifest_bytes=manifest_bytes, expected_manifest_sha256=expected_manifest_sha256,
        standalone_profile_bytes=standalone_profile_bytes,
        expected_standalone_profile_sha256=expected_standalone_profile_sha256,
    )
    return _compare_linker_dependencies(
        recipe, depfiles, expected_recipe_sha256=expected_recipe_sha256,
        expected_manifest_sha256=expected_manifest_sha256, output_inventory_bytes=output_inventory_bytes,
        expected_output_inventory_sha256=expected_output_inventory_sha256,
        dependency_artifacts=dependency_artifacts, source_root=source_root,
        toolchain_root=toolchain_root, work_root=work_root, current_output_root=current_output_root,
    )


def compare_linker_dependencies_v4(
    recipe_bytes: bytes, *, expected_recipe_sha256: str,
    manifest_bytes: bytes, expected_manifest_sha256: str,
    output_inventory_bytes: bytes, expected_output_inventory_sha256: str,
    dependency_artifacts: dict[str, bytes], source_root: str, toolchain_root: str, work_root: str,
    current_output_root: str | None = None,
    standalone_profile_bytes: bytes | None = None,
    expected_standalone_profile_sha256: str | None = None,
    zig_lld_profile_bytes: bytes | None = None,
    expected_zig_lld_profile_sha256: str | None = None,
) -> LinkerDependencyComparison:
    """Use the original complete-prior-output comparator for the v4 view."""
    recipe, _, depfiles = validate_dependency_capture_plan_v4(
        recipe_bytes, expected_recipe_sha256=expected_recipe_sha256,
        manifest_bytes=manifest_bytes, expected_manifest_sha256=expected_manifest_sha256,
        standalone_profile_bytes=standalone_profile_bytes,
        expected_standalone_profile_sha256=expected_standalone_profile_sha256,
        zig_lld_profile_bytes=zig_lld_profile_bytes,
        expected_zig_lld_profile_sha256=expected_zig_lld_profile_sha256,
    )
    return _compare_linker_dependencies(
        recipe, depfiles, expected_recipe_sha256=expected_recipe_sha256,
        expected_manifest_sha256=expected_manifest_sha256, output_inventory_bytes=output_inventory_bytes,
        expected_output_inventory_sha256=expected_output_inventory_sha256,
        dependency_artifacts=dependency_artifacts, source_root=source_root,
        toolchain_root=toolchain_root, work_root=work_root, current_output_root=current_output_root,
        comparison_binding={"schema": "lunar-cpython-linker-dependency-comparison-v2",
                            "input_projection": recipe["input_projection"],
                            "inputs_sha256": _sha(canonical(recipe["inputs"]))},
    )
