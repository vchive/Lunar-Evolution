"""Bounded installation descriptions, never a live owner or runtime admission.

Parsing compares mandatory external pins. It does not inspect missing source,
toolchain or executable bytes, build an image, or establish runtime observations.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import NoReturn

MAX_DESCRIPTOR_BYTES = 256 * 1024
MAX_ARTIFACT_BYTES = 128 * 1024 * 1024
_MAX_INPUT_BYTES = 1024 * 1024 * 1024
_MAX_NODES = 8192
_MAX_TEXT_BYTES = 192 * 1024
_SOURCE_COMMIT = "1cbe481834751b0125e006042ffbd8cd5eaec8a8"
_SOURCE_TREE = "1e5e19e950c3499dcd7df46f5a87aa05f6434e8e"
_TAG_OBJECT = "c3024299e68ff061b197b711368c3e1d74beb4c7"
_SOURCE_URL = "https://www.python.org/ftp/python/3.13.12/Python-3.13.12.tar.xz"
_SOURCE_SHA = "2a84cd31dd8d8ea8aaff75de66fc1b4b0127dd5799aa50a64ae9a313885b4593"
_ZIG_URL = "https://ziglang.org/download/0.16.0/zig-x86_64-linux-0.16.0.tar.xz"
_ZIG_SHA = "70e49664a74374b48b51e6f3fdfbf437f6395d42509050588bd49abe52ba3d00"
_PROGRAM = "lunar-static-python-fixture"
_HOME = "/lunar-static-fixture"
_CLAIMS = {
    "execution_performed", "runtime_load_protection", "production_admission",
    "general_code_origin_protection",
}
_FIXED = {
    "schema_version": "1", "protocol": "lunar-static-python-installation-v1",
    "scope": "installation-owned-static-frozen-fixture-only", "platform": "linux",
    "architecture": "x86_64", "python_version": "3.13.12", "cache_tag": "cpython-313",
    "abi_profile": "cp313-release-gil", "frozen_main": "_lunar_static_main",
    "source_tag": "v3.13.12", "source_commit": _SOURCE_COMMIT,
    "source_archive_sha256": _SOURCE_SHA,
}
_DIGEST_FIELDS = {
    "source_tree_sha256", "patch_set_sha256", "recipe_sha256",
    "toolchain_manifest_sha256", "link_manifest_sha256", "initialization_profile_sha256",
    "frozen_inventory_sha256", "builtin_inventory_sha256", "alias_inventory_sha256",
    "artifact_sha256",
}
_NESTED_FIELDS = {
    "source_provenance", "toolchain", "recipe", "generator", "embedded_startup_arrays",
    "frozen_modules", "builtin_modules", "aliases", "initialization_profile", "elf_profile",
}
_FIELDS = set(_FIXED) | _DIGEST_FIELDS | _NESTED_FIELDS | _CLAIMS | {
    "installation_version", "artifact_size", "artifact_mode",
}
_FROZEN = {
    "_frozen_importlib": (False, "bootstrap"),
    "_frozen_importlib_external": (False, "bootstrap"),
    "_lunar_static_main": (False, "custom"),
    "abc": (False, "stdlib"), "codecs": (False, "stdlib"),
    "encodings": (True, "stdlib"), "encodings.aliases": (False, "stdlib"),
    "encodings.utf_8": (False, "stdlib"), "io": (False, "stdlib"),
}
_BUILTINS = {
    "marshal": "PyMarshal_Init", "_imp": "PyInit__imp", "_ast": "PyInit__ast",
    "_tokenize": "PyInit__tokenize", "builtins": "NULL", "sys": "NULL",
    "gc": "PyInit_gc", "_warnings": "_PyWarnings_Init", "_string": "PyInit__string",
    **{name: "PyInit_" + name for name in (
        "atexit", "faulthandler", "posix", "_signal", "_codecs", "_io",
        "_thread", "_weakref", "_abc", "_lunar_fixture_pipe",
    )},
}
_ALIASES = {
    "importlib._bootstrap": "_frozen_importlib",
    "importlib._bootstrap_external": "_frozen_importlib_external",
}
_STARTUP_MODULES = sorted((
    "sys", "builtins", "_frozen_importlib", "_imp", "_thread", "_warnings",
    "_weakref", "_frozen_importlib_external", "_io", "marshal", "posix",
    "encodings", "codecs", "_codecs", "encodings.aliases", "encodings.utf_8",
    "io", "abc", "_abc", "__main__", "_lunar_static_main", "_lunar_fixture_pipe",
))
# Immutable projections of the reviewed finite profile, shared by observation
# adapters. Available builtins and modules imported at startup are different
# sets: exposing these separately prevents treating availability as execution.
STATIC_PYTHON_BUILTIN_NAMES = tuple(sorted(_BUILTINS))
STATIC_PYTHON_FROZEN_NAMES = tuple(sorted(_FROZEN))
STATIC_PYTHON_STARTUP_MODULES = tuple(_STARTUP_MODULES)
_PRECONFIG = {
    "_config_init": 3, "parse_argv": 0, "isolated": 1, "use_environment": 0,
    "configure_locale": 0, "coerce_c_locale": 0, "coerce_c_locale_warn": 0,
    "utf8_mode": 1, "dev_mode": 0, "allocator": 5,
}
_CONFIG = {
    "_config_init": 3, "isolated": 1, "use_environment": 0, "dev_mode": 0,
    "install_signal_handlers": 0, "use_hash_seed": 1, "hash_seed": 0,
    "faulthandler": 0, "tracemalloc": 0, "perf_profiling": 0, "import_time": 0,
    "code_debug_ranges": 1, "show_ref_count": 0, "dump_refs": 0,
    "dump_refs_file": "NULL", "malloc_stats": 0, "filesystem_encoding": "utf-8",
    "filesystem_errors": "surrogateescape", "pycache_prefix": "NULL", "parse_argv": 0,
    "orig_argv": [_PROGRAM], "argv": [_PROGRAM], "xoptions": [], "warnoptions": [],
    "site_import": 0, "bytes_warning": 0, "warn_default_encoding": 0, "inspect": 0,
    "interactive": 0, "optimization_level": 0, "parser_debug": 0, "write_bytecode": 0,
    "verbose": 0, "quiet": 0, "user_site_directory": 0, "configure_c_stdio": 1,
    "buffered_stdio": 1, "stdio_encoding": "utf-8", "stdio_errors": "strict",
    "check_hash_pycs_mode": "always", "use_frozen_modules": 1, "safe_path": 1,
    "int_max_str_digits": 4300, "cpu_count": 1, "pathconfig_warnings": 0,
    "program_name": _PROGRAM, "pythonpath_env": "NULL", "home": _HOME,
    "platlibdir": "lib", "module_search_paths_set": 1, "module_search_paths": [],
    "stdlib_dir": _HOME, "executable": "/" + _PROGRAM, "base_executable": "/" + _PROGRAM,
    "prefix": _HOME, "base_prefix": _HOME, "exec_prefix": _HOME, "base_exec_prefix": _HOME,
    "skip_source_first_line": 0, "run_command": "NULL", "run_module": "NULL",
    "run_filename": "NULL", "sys_path_0": "NULL", "_install_importlib": 1,
    "_init_main": 1, "_is_python_build": 0,
}
_BUILD_ENVIRONMENT = {
    "PATH", "LC_ALL", "LANG", "TZ", "SOURCE_DATE_EPOCH", "PYTHONHASHSEED",
    "PYTHONNOUSERSITE", "CC", "AR", "RANLIB", "CFLAGS", "CPPFLAGS", "LDFLAGS",
    "ac_cv_func_dlopen", "ZIG_GLOBAL_CACHE_DIR", "ZIG_LOCAL_CACHE_DIR",
    "CONFIG_SITE", "LUNAR_STATIC_CLEAN_ENV",
}
_ELF_FIELDS = {
    "sha256", "size", "elf_class", "byte_order", "machine", "elf_type", "osabi",
    "entry_point", "program_header_count", "section_header_count", "load_segment_count",
    "executable_load_segment_count", "dynamic_table_count", "dynamic_entry_count",
    "has_pt_interp", "has_dt_needed", "runtime_load_protection", "production_admission",
    "general_code_origin_protection",
}


class StaticPythonInstallationError(ValueError):
    """A fixed refusal reason without caller material or path disclosure."""

    def __init__(self, reason: str) -> None:
        if type(reason) is not str or re.fullmatch(r"[a-z_]{1,48}", reason) is None:
            reason = "invalid"
        self.reason = "static_python_installation_" + reason
        super().__init__(self.reason)


def _fail(reason: str) -> NoReturn:
    raise StaticPythonInstallationError(reason)


def _canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _sha(value: object) -> str:
    if type(value) is not str or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        _fail("digest")
    if value in ("0" * 64, "f" * 64):
        _fail("digest")
    return value


def _integer(value: object, maximum: int, minimum: int = 0) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        _fail("integer")
    return value


def _text(value: object, maximum: int = 4096) -> str:
    if type(value) is not str or not value or len(value) > maximum:
        _fail("text")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        _fail("text")
    if len(value.encode("utf-8")) > maximum:
        _fail("text")
    return value


def _label(value: object) -> str:
    result = _text(value, 128)
    if re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]*", result) is None:
        _fail("label")
    return result


def _object(value: object, fields: set[str]) -> dict:
    if type(value) is not dict or set(value) != fields:
        _fail("schema")
    return value


def _vector(value: object, maximum: int, *, empty: bool = False) -> list:
    if type(value) is not list or not (0 if empty else 1) <= len(value) <= maximum:
        _fail("collection")
    return value


def _ordered(values: list[str]) -> None:
    if values != sorted(set(values)):
        _fail("ordering")


def _file(value: object) -> str:
    item = _object(value, {"path", "sha256", "size"})
    path = _text(item["path"])
    if "\\" in path or any(part in ("", ".", "..") for part in path.split("/")):
        _fail("path")
    if len(path.split("/")) > 64:
        _fail("path")
    _sha(item["sha256"])
    _integer(item["size"], _MAX_INPUT_BYTES, 1)
    return path


def _files(value: object, maximum: int) -> None:
    _ordered([_file(item) for item in _vector(value, maximum)])


def _pairs(pairs: list[tuple[str, object]]) -> dict:
    value: dict = {}
    for key, item in pairs:
        if key in value:
            _fail("duplicate_key")
        value[key] = item
    return value


def _constant(_: str) -> NoReturn:
    _fail("json")


def _scan(value: object) -> None:
    nodes = text_size = 0
    pending = [(value, 0)]
    while pending:
        item, depth = pending.pop()
        nodes += 1
        if nodes > _MAX_NODES or depth > 12:
            _fail("aggregate")
        if type(item) is dict:
            pending.extend((child, depth + 1) for child in item.values())
            pending.extend((key, depth + 1) for key in item)
        elif type(item) is list:
            pending.extend((child, depth + 1) for child in item)
        elif type(item) is str:
            try:
                text_size += len(item.encode("utf-8"))
            except UnicodeError:
                _fail("text")
            if text_size > _MAX_TEXT_BYTES:
                _fail("aggregate")
        elif type(item) not in (int, bool):
            _fail("json_type")


def _same_typed(value: object, expected: object) -> bool:
    # JSON true compares equal to integer1; recursive type identity is mandatory.
    if type(value) is not type(expected):
        return False
    if type(expected) is dict:
        return set(value) == set(expected) and all(
            _same_typed(value[key], item) for key, item in expected.items()
        )
    if type(expected) is list:
        return len(value) == len(expected) and all(
            _same_typed(left, right) for left, right in zip(value, expected, strict=True)
        )
    return value == expected


def _source(value: object, top: dict) -> None:
    item = _object(value, {
        "upstream_url", "source_tag", "source_commit", "source_git_tree",
        "annotated_tag_object", "archive_url", "acquisition", "signature_verification",
        "source_archive_sha256", "source_tree_sha256", "patches",
    })
    expected = {
        "upstream_url": "https://github.com/python/cpython.git", "source_tag": "v3.13.12",
        "source_commit": _SOURCE_COMMIT, "source_git_tree": _SOURCE_TREE,
        "annotated_tag_object": _TAG_OBJECT, "archive_url": _SOURCE_URL,
        "acquisition": "sha256-pinned-public-archive", "signature_verification": "not-performed",
        "source_archive_sha256": _SOURCE_SHA, "source_tree_sha256": top["source_tree_sha256"],
    }
    if any(not _same_typed(item[key], wanted) for key, wanted in expected.items()):
        _fail("source")
    _files(item["patches"], 32)


def _toolchain(value: object) -> None:
    item = _object(value, {
        "profile", "archive_url", "archive_sha256", "version", "target", "llvm_version",
        "musl_version", "libc_disposition", "executables", "sysroot_manifest_sha256",
        "archives", "patch_manifest_sha256",
    })
    fixed = {
        "profile": "zig-0.16.0-linux-x86_64-musl", "archive_url": _ZIG_URL,
        "archive_sha256": _ZIG_SHA, "version": "0.16.0", "target": "x86_64-linux-musl",
        "llvm_version": "21.1.0", "musl_version": "1.2.5+zig-backports",
        "libc_disposition": "zig-musl-and-zig-libc",
    }
    if any(not _same_typed(item[key], wanted) for key, wanted in fixed.items()):
        _fail("toolchain")
    _files(item["executables"], 16)
    _files(item["archives"], 256)
    for name in ("sysroot_manifest_sha256", "patch_manifest_sha256"):
        _sha(item[name])


def _recipe(value: object) -> None:
    item = _object(value, {
        "configure_flags", "compile_flags", "link_flags", "environment",
        "generated_config_sha256", "module_config_sha256", "link_inputs",
        "link_map_sha256", "reproducibility",
    })
    for name in ("configure_flags", "compile_flags", "link_flags"):
        for flag in _vector(item[name], 128):
            _text(flag)
    for name in ("generated_config_sha256", "module_config_sha256", "link_map_sha256"):
        _sha(item[name])
    _files(item["link_inputs"], 256)
    names = []
    for env in _vector(item["environment"], 32):
        env = _object(env, {"name", "value"})
        name = _label(env["name"])
        if name not in _BUILD_ENVIRONMENT:
            _fail("environment")
        _text(env["value"])
        names.append(name)
    _ordered(names)
    if item["reproducibility"] not in ("not-tested", "byte-identical"):
        _fail("recipe")


def _inventories(top: dict) -> None:
    names = []
    for item in _vector(top["frozen_modules"], 128):
        item = _object(item, {"name", "is_package", "table", "source", "generated"})
        name = _label(item["name"])
        if name not in _FROZEN or not _same_typed(
            [item["is_package"], item["table"]], list(_FROZEN[name])
        ):
            _fail("frozen_inventory")
        _file(item["source"])
        _file(item["generated"])
        names.append(name)
    if names != sorted(_FROZEN):
        _fail("frozen_inventory")
    names = []
    for item in _vector(top["builtin_modules"], 128):
        item = _object(item, {"name", "init_symbol", "source", "object"})
        name = _label(item["name"])
        if name not in _BUILTINS or item["init_symbol"] != _BUILTINS[name]:
            _fail("builtin_inventory")
        _file(item["source"])
        _file(item["object"])
        names.append(name)
    if names != sorted(_BUILTINS):
        _fail("builtin_inventory")
    names = []
    for item in _vector(top["aliases"], 128):
        item = _object(item, {"alias", "name"})
        alias = _label(item["alias"])
        if alias not in _ALIASES or item["name"] != _ALIASES[alias]:
            _fail("alias_inventory")
        names.append(alias)
    if names != sorted(_ALIASES):
        _fail("alias_inventory")
    # The chosen recipe replaces getpath.o; no separate embedded startup code remains.
    if top["embedded_startup_arrays"] != []:
        _fail("startup_arrays")


def _initialization(value: object) -> None:
    item = _object(value, {
        "preconfig", "config", "expected_startup_modules", "external_loader_policy",
        "dynamic_loader_policy", "separate_startup_code",
    })
    expected = {
        "preconfig": _PRECONFIG, "config": _CONFIG, "expected_startup_modules": _STARTUP_MODULES,
        "external_loader_policy": "source-patched-builtin-frozen-only",
        "dynamic_loader_policy": "dynload-stub-no-dlopen", "separate_startup_code": "none",
    }
    if not _same_typed(item, expected):
        _fail("initialization")


def _elf(value: object, top: dict) -> None:
    item = _object(value, _ELF_FIELDS)
    fixed = {
        "sha256": top["artifact_sha256"], "size": top["artifact_size"], "elf_class": 64,
        "byte_order": "little", "machine": "x86_64", "elf_type": "ET_EXEC",
        "has_pt_interp": False, "has_dt_needed": False, "runtime_load_protection": False,
        "production_admission": False, "general_code_origin_protection": False,
    }
    if any(not _same_typed(item[key], wanted) for key, wanted in fixed.items()):
        _fail("elf_profile")
    if type(item["osabi"]) is not int or item["osabi"] not in (0, 3):
        _fail("elf_profile")
    _integer(item["entry_point"], 2**64 - 1, 1)
    ph = _integer(item["program_header_count"], 256, 1)
    _integer(item["section_header_count"], 4096)
    loads = _integer(item["load_segment_count"], ph, 1)
    _integer(item["executable_load_segment_count"], loads, 1)
    tables = _integer(item["dynamic_table_count"], 4096 + 256)
    entries = _integer(item["dynamic_entry_count"], 4096, 1 if tables else 0)
    if not tables and entries:
        _fail("elf_profile")


def _validate(top: object) -> dict:
    top = _object(top, _FIELDS)
    if any(not _same_typed(top[key], wanted) for key, wanted in _FIXED.items()):
        _fail("profile")
    if any(top[key] is not False for key in _CLAIMS):
        _fail("claims")
    _label(top["installation_version"])
    for name in _DIGEST_FIELDS:
        _sha(top[name])
    _integer(top["artifact_size"], MAX_ARTIFACT_BYTES, 1)
    if type(top["artifact_mode"]) is not int or top["artifact_mode"] != 0o555:
        _fail("artifact_mode")
    _source(top["source_provenance"], top)
    _toolchain(top["toolchain"])
    _recipe(top["recipe"])
    generator = _object(top["generator"], {
        "python_version", "host_architecture", "source_sha256", "recipe_sha256",
        "executable_sha256", "marshal_version", "generated_manifest_sha256",
    })
    if generator["python_version"] != "3.13.12" or generator["host_architecture"] != "x86_64":
        _fail("generator")
    if type(generator["marshal_version"]) is not int or generator["marshal_version"] != 4:
        _fail("generator")
    for name in ("source_sha256", "recipe_sha256", "executable_sha256", "generated_manifest_sha256"):
        _sha(generator[name])
    _inventories(top)
    _initialization(top["initialization_profile"])
    _elf(top["elf_profile"], top)
    manifests = {
        "patch_set_sha256": top["source_provenance"]["patches"],
        "recipe_sha256": top["recipe"], "toolchain_manifest_sha256": top["toolchain"],
        "link_manifest_sha256": top["recipe"]["link_inputs"],
        "initialization_profile_sha256": top["initialization_profile"],
        "frozen_inventory_sha256": top["frozen_modules"],
        "builtin_inventory_sha256": top["builtin_modules"], "alias_inventory_sha256": top["aliases"],
    }
    if any(hashlib.sha256(_canonical(value)).hexdigest() != top[name]
           for name, value in manifests.items()):
        _fail("manifest_pin")
    return top


@dataclass(frozen=True, slots=True)
class StaticPythonInstallationDescriptor:
    """Detached immutable description; its presence conveys no execution authority."""

    canonical_bytes: bytes
    descriptor_sha256: str
    installation_version: str
    artifact_sha256: str
    artifact_size: int

    def to_json(self) -> bytes:
        return self.canonical_bytes

    def to_dict(self) -> dict:
        return json.loads(self.canonical_bytes)


def parse_static_python_installation_descriptor(
    raw: bytes, *, expected_descriptor_sha256: str,
    expected_installation_version: str, expected_artifact_sha256: str,
) -> StaticPythonInstallationDescriptor:
    """Check exact canonical bytes and mandatory independently supplied pins.

    This pure parser never opens files, resolves paths, calls a builder or grants
    runtime authority. Described source/generated/ELF facts still need byte checks.
    """
    _sha(expected_descriptor_sha256)
    _label(expected_installation_version)
    _sha(expected_artifact_sha256)
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_DESCRIPTOR_BYTES:
        _fail("wire")
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs, parse_constant=_constant)
    except (UnicodeError, ValueError, RecursionError) as exc:
        if isinstance(exc, StaticPythonInstallationError):
            raise
        raise StaticPythonInstallationError("json") from None
    _scan(payload)
    top = _validate(payload)
    if _canonical(top) != raw:
        _fail("canonical")
    actual_sha = hashlib.sha256(raw).hexdigest()
    if (actual_sha != expected_descriptor_sha256
            or top["installation_version"] != expected_installation_version
            or top["artifact_sha256"] != expected_artifact_sha256):
        _fail("external_pin")
    return StaticPythonInstallationDescriptor(
        raw, actual_sha, top["installation_version"], top["artifact_sha256"], top["artifact_size"],
    )
