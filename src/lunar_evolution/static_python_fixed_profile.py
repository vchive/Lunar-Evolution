"""Expanded fixed-solver descriptions, never installation or process authority.

The original nine-module parsers remain unchanged. All pins are mandatory
independent comparison inputs; synthetic descriptions are not build evidence.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import NoReturn

from .static_python_elf import (
    StaticPythonELFError,
    StaticPythonELFProfile,
    inspect_static_python_elf,
)
from .static_python_installation import (
    _CONFIG,
    _PRECONFIG,
    STATIC_PYTHON_BUILTIN_NAMES,
    STATIC_PYTHON_FROZEN_NAMES,
)
from .static_python_runtime_startup import (
    StaticPythonRuntimeStartup,
    StaticPythonRuntimeStartupError,
    parse_static_python_runtime_startup,
)

FIXED_INSTALLATION_SCHEMA = "lunar-static-python-fixed-profile-installation-v1"
MAX_FIXED_INSTALLATION_BYTES = 2 * 1024 * 1024
MAX_FIXED_CLOSURE_BYTES = 2 * 1024 * 1024
MAX_FIXED_MODULE_INVENTORY_BYTES = 128 * 1024
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_LABEL = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}\Z")
_PATH = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./+-]{0,511}\Z")
_PRODUCERS = {
    "openevolve": "03266224f20d99aaef794cb8c9d8688f9ba8c1d44faf8c46b207c3780d4a6b06",
    "shinka": "5a6e716142cf71d944adbc7e1622cb1a147f7ef9eaba556e9bb1f707680ecffa",
}
_CLAIMS = frozenset({
    "configured_closure_verified", "compilation_performed", "freezer_performed",
    "runtime_execution_performed", "installation_accepted", "input_consumption_verified",
    "runtime_load_protection", "production_admission", "general_code_origin_protection",
})
_FIELDS = frozenset({
    "schema", "profile_version", "installation_version", "runtime_closure_sha256",
    "source_inventory_sha256", "configuration", "image", "frozen_modules", "native_units",
    "initialization", "claims",
})
_CLOSURE_FIELDS = frozenset({
    "schema", "solver", "cpython_inventory_sha256", "producer_manifest_sha256",
    "sqlite_inventory_sha256", "frozen", "native_units", "native_header_inputs",
    "sources", "runtime_module_aliases", "guarded_absent_imports", "guarded_call_imports",
    "interpreter_provided_modules", "excluded_imported_selftests", "fixed_platform_guards",
    "dynamic_import_closure_verified", "runtime_execution_performed", "production_admission",
})
_REASONS = frozenset({
    "invalid", "pin", "label", "path", "schema", "duplicate", "json", "structure",
    "raw", "canonical", "inventory", "record", "closure", "claims", "profile",
    "configuration", "image", "initialization", "frozen", "native", "alias",
    "installation", "elf", "startup", "module_origin",
})


class FixedPythonProfileError(ValueError):
    """Fixed codes only; caller material is not retained as parser context."""

    def __init__(self, reason: str) -> None:
        if type(reason) is not str or reason not in _REASONS:
            reason = "invalid"
        self.reason = "static_python_fixed_profile_" + reason
        super().__init__(self.reason)


class _Refusal(ValueError):
    pass


def _fail(code: str) -> NoReturn:
    raise _Refusal(code)


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _digest(value: object) -> str:
    if (type(value) is not str or not _SHA.fullmatch(value)
            or value in {"0" * 64, "f" * 64}):
        _fail("pin")
    return value


def _label(value: object) -> str:
    if type(value) is not str or not _LABEL.fullmatch(value):
        _fail("label")
    return value


def _path(value: object) -> str:
    if (type(value) is not str or not _PATH.fullmatch(value)
            or any(part in {"", ".", ".."} for part in value.split("/"))):
        _fail("path")
    return value


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _object(value: object, fields: frozenset[str] | set[str]) -> dict:
    if type(value) is not dict or set(value) != fields:
        _fail("schema")
    return value


def _pairs(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            _fail("duplicate")
        result[key] = value
    return result


def _constant(_: str) -> NoReturn:
    _fail("json")


def _scan(value: object) -> None:
    pending = [(value, 0)]
    nodes = text = 0
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if nodes > 65536 or depth > 20:
            _fail("structure")
        if type(item) is dict:
            pending.extend((key, depth + 1) for key in item)
            pending.extend((child, depth + 1) for child in item.values())
        elif type(item) is list:
            pending.extend((child, depth + 1) for child in item)
        elif type(item) is str:
            text += len(item.encode("utf-8"))
            if text > 1536 * 1024:
                _fail("structure")
        elif item is not None and type(item) not in {int, bool}:
            _fail("structure")


def _json(raw: object, maximum: int, *, closure: bool = False) -> object:
    if type(raw) is not bytes or not 0 < len(raw) <= maximum:
        _fail("raw")
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                       parse_float=_constant, parse_constant=_constant)
    _scan(value)
    canonical = ((json.dumps(value, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")
                 if closure else _canonical(value))
    if canonical != raw:
        _fail("canonical")
    return value


def _vector(value: object, maximum: int, *, empty: bool = False) -> list:
    if type(value) is not list or not (0 if empty else 1) <= len(value) <= maximum:
        _fail("inventory")
    return value


def _record(value: object, *, allow_empty: bool = False) -> dict:
    item = _object(value, {"path", "size", "sha256"})
    _path(item["path"])
    if (type(item["size"]) is not int
            or not (0 if allow_empty else 1) <= item["size"] <= 128 * 1024 * 1024):
        _fail("record")
    _digest(item["sha256"])
    return item


def _source(unit: dict) -> dict:
    return {"path": unit["source"], "size": unit["source_size"], "sha256": unit["source_sha256"]}


@dataclass(frozen=True, slots=True)
class FixedPythonInstallation:
    """Pinned immutable description usable by later build/startup composition."""

    canonical_bytes: bytes
    closure_bytes: bytes
    installation_sha256: str
    profile_version: str
    installation_version: str
    source_inventory_sha256: str
    configuration_sha256: str
    artifact_sha256: str
    frozen_inventory_sha256: str
    native_inventory_sha256: str
    frozen_names: tuple[str, ...]
    builtin_names: tuple[str, ...]
    aliases: tuple[tuple[str, str], ...]

    def to_dict(self) -> dict:
        return json.loads(self.canonical_bytes)

    def to_json(self) -> bytes:
        return self.canonical_bytes


def _parse_installation(
    raw: bytes, *, runtime_closure: bytes, expected_installation_sha256: str,
    expected_installation_version: str, expected_runtime_closure_sha256: str,
    expected_source_inventory_sha256: str, expected_configuration_sha256: str,
    expected_artifact_sha256: str, expected_frozen_inventory_sha256: str,
    expected_native_inventory_sha256: str,
) -> FixedPythonInstallation:
    pins = (expected_installation_sha256, expected_runtime_closure_sha256,
            expected_source_inventory_sha256, expected_configuration_sha256,
            expected_artifact_sha256, expected_frozen_inventory_sha256,
            expected_native_inventory_sha256)
    for pin in pins:
        _digest(pin)
    _label(expected_installation_version)
    top = _object(_json(raw, MAX_FIXED_INSTALLATION_BYTES), _FIELDS)
    closure = _object(_json(runtime_closure, MAX_FIXED_CLOSURE_BYTES, closure=True), _CLOSURE_FIELDS)
    if _sha(raw) != expected_installation_sha256 or _sha(runtime_closure) != expected_runtime_closure_sha256:
        _fail("pin")
    solver = closure["solver"]
    if (type(solver) is not str or solver not in _PRODUCERS
            or closure["schema"] != "lunar-fixed-python-runtime-source-closure-v1"
            or closure["producer_manifest_sha256"] != _PRODUCERS[solver]
            or closure["cpython_inventory_sha256"] != expected_source_inventory_sha256):
        _fail("closure")
    if any(closure[name] is not False for name in (
        "dynamic_import_closure_verified", "runtime_execution_performed", "production_admission",
    )):
        _fail("claims")
    for field in ("native_header_inputs", "guarded_absent_imports", "guarded_call_imports",
                  "interpreter_provided_modules", "excluded_imported_selftests", "fixed_platform_guards"):
        _vector(closure[field], 2048, empty=True)
    source_records = [_record(item, allow_empty=True) for item in _vector(closure["sources"], 512)]
    source_paths = [item["path"] for item in source_records]
    if (source_paths != sorted(set(source_paths))
            or not {"runtime/Modules/config.c", "runtime/Python/frozen.c",
                    "runtime/Python/stdlib_module_names.h", "runtime/frozen_main.py"} <= set(source_paths)):
        _fail("closure")
    if solver == "shinka":
        _digest(closure["sqlite_inventory_sha256"])
    elif closure["sqlite_inventory_sha256"] is not None:
        _fail("closure")
    if (top["schema"] != FIXED_INSTALLATION_SCHEMA
            or top["profile_version"] != "fixed-" + solver + "-v1"
            or top["installation_version"] != expected_installation_version
            or top["runtime_closure_sha256"] != expected_runtime_closure_sha256
            or top["source_inventory_sha256"] != expected_source_inventory_sha256):
        _fail("profile")
    claims = _object(top["claims"], _CLAIMS)
    if any(value is not False for value in claims.values()):
        _fail("claims")
    configuration = _record(top["configuration"])
    if (configuration["path"] != "configuration/pyconfig.h"
            or configuration["size"] > 128 * 1024
            or configuration["sha256"] != expected_configuration_sha256):
        _fail("configuration")
    image = _object(top["image"], {"path", "size", "sha256", "mode"})
    _record({key: image[key] for key in ("path", "size", "sha256")})
    if (image["path"] != "bin/lunar-" + solver or image["sha256"] != expected_artifact_sha256
            or type(image["mode"]) is not int or not 0 <= image["mode"] <= 0o7777
            or not image["mode"] & 0o111 or image["mode"] & 0o6000):
        _fail("image")
    initialization = _object(top["initialization"], {"preconfig", "config"})
    if _canonical(initialization) != _canonical({"preconfig": _PRECONFIG, "config": _CONFIG}):
        _fail("initialization")
    frozen = _vector(top["frozen_modules"], 256)
    expected_frozen = _vector(closure["frozen"], 256)
    if len(frozen) != len(expected_frozen):
        _fail("frozen")
    frozen_names, generator_ids, generated_paths = [], [], []
    for item, unit in zip(frozen, expected_frozen, strict=True):
        _object(item, {"name", "generator_id", "package", "source", "generated"})
        _object(unit, {"name", "generator_id", "package", "source", "source_size", "source_sha256", "output"})
        name = _label(item["name"])
        _label(item["generator_id"])
        source = _record(item["source"], allow_empty=True)
        generated = _record(item["generated"])
        if (name != unit["name"] or item["generator_id"] != unit["generator_id"]
                or type(item["package"]) is not bool or item["package"] is not unit["package"]
                or _canonical(source) != _canonical(_source(unit))
                or generated["path"] != unit["output"]
                or generated["sha256"] == source["sha256"]):
            _fail("frozen")
        if name == "_lunar_static_main" and source != next(
            record for record in source_records if record["path"] == "runtime/frozen_main.py"
        ):
            _fail("frozen")
        frozen_names.append(name)
        generator_ids.append(item["generator_id"])
        generated_paths.append(generated["path"])
    if (len(set(frozen_names)) != len(frozen_names)
            or generator_ids != sorted(set(generator_ids))
            or not set(STATIC_PYTHON_FROZEN_NAMES) <= set(frozen_names)
            or "__main__" in frozen_names
            or len(set(generated_paths)) != len(generated_paths)
            or _sha(_canonical(frozen)) != expected_frozen_inventory_sha256):
        _fail("frozen")
    native = _vector(top["native_units"], 128, empty=True)
    expected_native = _vector(closure["native_units"], 128, empty=True)
    if len(native) != len(expected_native):
        _fail("native")
    objects, modules = [], set(STATIC_PYTHON_BUILTIN_NAMES)
    for item, unit in zip(native, expected_native, strict=True):
        _object(item, {"module", "source", "object", "extra_flags"})
        _object(unit, {"module", "source", "object", "source_size", "source_sha256", "extra_flags"})
        module = _label(item["module"])
        source, obj = _record(item["source"]), _record(item["object"])
        flags = _vector(item["extra_flags"], 64, empty=True)
        if any(type(flag) is not str or not 0 < len(flag) <= 512 for flag in flags):
            _fail("native")
        if (module != unit["module"] or _canonical(source) != _canonical(_source(unit))
                or obj["path"] != "objects/" + unit["object"]
                or obj["sha256"] == source["sha256"]
                or _canonical(item["extra_flags"]) != _canonical(unit["extra_flags"])):
            _fail("native")
        objects.append(obj["path"])
        if module != "sqlite-library":
            modules.add(module)
    if len(set(objects)) != len(objects) or _sha(_canonical(native)) != expected_native_inventory_sha256:
        _fail("native")
    aliases = [("importlib._bootstrap", "_frozen_importlib"),
               ("importlib._bootstrap_external", "_frozen_importlib_external")]
    for alias in _vector(closure["runtime_module_aliases"], 16, empty=True):
        _object(alias, {"name", "parent_module", "source_module"})
        if alias["source_module"] not in frozen_names or alias["parent_module"] not in frozen_names:
            _fail("alias")
        aliases.append((_label(alias["name"]), _label(alias["source_module"])))
    if (len({a for a, _ in aliases}) != len(aliases) or set(frozen_names) & modules
            or "__main__" in modules
            or any(a in set(frozen_names) | modules or target not in frozen_names
                   for a, target in aliases)):
        _fail("inventory")
    return FixedPythonInstallation(
        raw, runtime_closure, expected_installation_sha256, top["profile_version"],
        expected_installation_version, expected_source_inventory_sha256,
        expected_configuration_sha256, expected_artifact_sha256,
        expected_frozen_inventory_sha256, expected_native_inventory_sha256,
        tuple(frozen_names), tuple(sorted(modules)), tuple(sorted(aliases)),
    )


def parse_fixed_python_installation(
    raw: bytes, *, runtime_closure: bytes, expected_installation_sha256: str,
    expected_installation_version: str, expected_runtime_closure_sha256: str,
    expected_source_inventory_sha256: str, expected_configuration_sha256: str,
    expected_artifact_sha256: str, expected_frozen_inventory_sha256: str,
    expected_native_inventory_sha256: str,
) -> FixedPythonInstallation:
    """Compare complete expanded inventories; successful descriptions grant no admission."""
    try:
        return _parse_installation(
            raw, runtime_closure=runtime_closure,
            expected_installation_sha256=expected_installation_sha256,
            expected_installation_version=expected_installation_version,
            expected_runtime_closure_sha256=expected_runtime_closure_sha256,
            expected_source_inventory_sha256=expected_source_inventory_sha256,
            expected_configuration_sha256=expected_configuration_sha256,
            expected_artifact_sha256=expected_artifact_sha256,
            expected_frozen_inventory_sha256=expected_frozen_inventory_sha256,
            expected_native_inventory_sha256=expected_native_inventory_sha256,
        )
    except _Refusal as exc:
        reason = str(exc)
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, OverflowError):
        reason = "json"
    raise FixedPythonProfileError(reason) from None


def _reparse(installation: object, expected_installation_sha256: str) -> FixedPythonInstallation:
    if type(installation) is not FixedPythonInstallation:
        _fail("installation")
    _digest(expected_installation_sha256)
    declared = _object(_json(installation.canonical_bytes, MAX_FIXED_INSTALLATION_BYTES), _FIELDS)
    if _sha(installation.canonical_bytes) != expected_installation_sha256:
        _fail("pin")
    actual = _parse_installation(
        installation.canonical_bytes, runtime_closure=installation.closure_bytes,
        expected_installation_sha256=expected_installation_sha256,
        expected_installation_version=installation.installation_version,
        expected_runtime_closure_sha256=declared["runtime_closure_sha256"],
        expected_source_inventory_sha256=installation.source_inventory_sha256,
        expected_configuration_sha256=installation.configuration_sha256,
        expected_artifact_sha256=installation.artifact_sha256,
        expected_frozen_inventory_sha256=installation.frozen_inventory_sha256,
        expected_native_inventory_sha256=installation.native_inventory_sha256,
    )
    if actual != installation:
        _fail("installation")
    return actual


def verify_fixed_python_image(
    installation: FixedPythonInstallation, image: bytes, *, expected_installation_sha256: str,
) -> StaticPythonELFProfile:
    """Observe actual byte identity and static ELF format; not custody or source consumption."""
    try:
        installed = _reparse(installation, expected_installation_sha256)
        declared = installed.to_dict()["image"]
        if (type(image) is not bytes or len(image) != declared["size"]
                or len(image) > 128 * 1024 * 1024 or _sha(image) != installed.artifact_sha256):
            _fail("image")
        return inspect_static_python_elf(image)
    except _Refusal as exc:
        reason = str(exc)
    except StaticPythonELFError:
        reason = "elf"
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, OverflowError):
        reason = "json"
    raise FixedPythonProfileError(reason) from None


@dataclass(frozen=True, slots=True)
class FixedPythonStartup:
    """Descriptions only; the pinned module subset still needs a live collector."""

    installation: FixedPythonInstallation
    startup: StaticPythonRuntimeStartup
    module_inventory_bytes: bytes
    module_inventory_sha256: str


def compare_fixed_python_startup(
    installation: FixedPythonInstallation, startup_raw: bytes, module_inventory: bytes, *,
    expected_installation_sha256: str, expected_startup_sha256: str,
    expected_module_inventory_sha256: str, expected_build_closure_sha256: str,
    expected_binding_sha256: str, expected_launch_intent_sha256: str,
    expected_sealed_material_sha256: str,
) -> FixedPythonStartup:
    """Compare pinned module-origin descriptions; live inventory completeness is unverified."""
    try:
        for pin in (expected_startup_sha256, expected_module_inventory_sha256,
                    expected_build_closure_sha256, expected_binding_sha256,
                    expected_launch_intent_sha256, expected_sealed_material_sha256):
            _digest(pin)
        installed = _reparse(installation, expected_installation_sha256)
        modules = _vector(_json(module_inventory, MAX_FIXED_MODULE_INVENTORY_BYTES), 512)
        if _sha(module_inventory) != expected_module_inventory_sha256:
            _fail("pin")
        if type(startup_raw) is not bytes or len(startup_raw) > 256 * 1024:
            _fail("raw")
        if _sha(startup_raw) != expected_startup_sha256:
            _fail("pin")
        startup = parse_static_python_runtime_startup(
            startup_raw, expected_build_closure_sha256=expected_build_closure_sha256,
            expected_binding_sha256=expected_binding_sha256,
            expected_launch_intent_sha256=expected_launch_intent_sha256,
        )
        payload = startup.to_dict()
        declared = installed.to_dict()["image"]
        if (startup.installation_version != installed.installation_version
                or payload["owner"]["executable"] != {k: declared[k] for k in ("path", "size", "sha256")}
                or payload["owner"]["mode"] != declared["mode"]
                or payload["loader"]["sealed_material_sha256"] != expected_sealed_material_sha256):
            _fail("startup")
        origins = {name: ("frozen", name) for name in installed.frozen_names}
        origins.update({name: ("built-in", name) for name in installed.builtin_names})
        origins["__main__"] = ("interpreter", "__main__")
        for alias, target in installed.aliases:
            if target not in origins:
                _fail("alias")
            origins[alias] = origins[target]
        names = []
        for module in modules:
            _object(module, {"name", "origin", "canonical_name"})
            name = _label(module["name"])
            if name not in origins or (module["origin"], module["canonical_name"]) != origins[name]:
                _fail("module_origin")
            names.append(name)
        if names != sorted(set(names)):
            _fail("module_origin")
        return FixedPythonStartup(installed, startup, module_inventory, expected_module_inventory_sha256)
    except _Refusal as exc:
        reason = str(exc)
    except StaticPythonRuntimeStartupError:
        reason = "startup"
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError, OverflowError):
        reason = "json"
    raise FixedPythonProfileError(reason) from None
