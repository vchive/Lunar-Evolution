"""Fixed Feature189 recipe values, independent of the running host interpreter."""

from __future__ import annotations

CPYTHON_ARCHIVE = {
    "url": "https://www.python.org/ftp/python/3.13.12/Python-3.13.12.tar.xz",
    "sha256": "2a84cd31dd8d8ea8aaff75de66fc1b4b0127dd5799aa50a64ae9a313885b4593",
    "size": 22926488,
    "root": "Python-3.13.12",
    "commit": "1cbe481834751b0125e006042ffbd8cd5eaec8a8",
    "tag": "v3.13.12",
    "tag_signature_verified": False,
}
ZIG_ARCHIVE = {
    "url": "https://ziglang.org/download/0.16.0/zig-x86_64-linux-0.16.0.tar.xz",
    "sha256": "70e49664a74374b48b51e6f3fdfbf437f6395d42509050588bd49abe52ba3d00",
    "size": 55478392,
    "root": "zig-x86_64-linux-0.16.0",
    "llvm_version": "21.1.0",
    "libc": "Zig bundled musl 1.2.5 with backports and Zig replacements",
}
MAX_IMAGE_BYTES = 134217728
IMAGE_MODE = 0o555
TARGET = "x86_64-linux-musl"
PROFILE_TRIPLE = "x86_64-unknown-linux-musl"
BUILD_ENVIRONMENT = {
    "PATH": "/usr/bin:/bin",
    "LC_ALL": "C",
    "TZ": "UTC",
    "SOURCE_DATE_EPOCH": "0",
    "CONFIG_SITE": "/dev/null",
    "ac_cv_func_dlopen": "no",
    "LUNAR_STATIC_CLEAN_ENV": "1",
}

# Initializers set the private _config_init via the public isolated init APIs.
# "NULL" is the explicit descriptor spelling of a null C pointer, not JSON null.
PRECONFIG = {
    "_config_init": 3, "parse_argv": 0, "isolated": 1, "use_environment": 0,
    "configure_locale": 0, "coerce_c_locale": 0, "coerce_c_locale_warn": 0,
    "utf8_mode": 1, "dev_mode": 0, "allocator": 5,
}
CONFIG = {
    "_config_init": 3, "isolated": 1, "use_environment": 0, "dev_mode": 0,
    "install_signal_handlers": 0, "use_hash_seed": 1, "hash_seed": 0,
    "faulthandler": 0, "tracemalloc": 0, "perf_profiling": 0, "import_time": 0,
    "code_debug_ranges": 1, "show_ref_count": 0, "dump_refs": 0,
    "dump_refs_file": "NULL", "malloc_stats": 0, "filesystem_encoding": "utf-8",
    "filesystem_errors": "surrogateescape", "pycache_prefix": "NULL", "parse_argv": 0,
    "orig_argv": ["lunar-static-python-fixture"], "argv": ["lunar-static-python-fixture"],
    "xoptions": [], "warnoptions": [], "site_import": 0, "bytes_warning": 0,
    "warn_default_encoding": 0, "inspect": 0, "interactive": 0, "optimization_level": 0,
    "parser_debug": 0, "write_bytecode": 0, "verbose": 0, "quiet": 0,
    "user_site_directory": 0, "configure_c_stdio": 1, "buffered_stdio": 1,
    "stdio_encoding": "utf-8", "stdio_errors": "strict", "check_hash_pycs_mode": "always",
    "use_frozen_modules": 1, "safe_path": 1, "int_max_str_digits": 4300, "cpu_count": 1,
    "pathconfig_warnings": 0, "program_name": "lunar-static-python-fixture",
    "pythonpath_env": "NULL", "home": "/lunar-static-fixture", "platlibdir": "lib",
    "module_search_paths_set": 1, "module_search_paths": [],
    "stdlib_dir": "/lunar-static-fixture", "executable": "/lunar-static-python-fixture",
    "base_executable": "/lunar-static-python-fixture", "prefix": "/lunar-static-fixture",
    "base_prefix": "/lunar-static-fixture", "exec_prefix": "/lunar-static-fixture",
    "base_exec_prefix": "/lunar-static-fixture", "skip_source_first_line": 0,
    "run_command": "NULL", "run_module": "NULL", "run_filename": "NULL",
    "sys_path_0": "NULL", "_install_importlib": 1, "_init_main": 1, "_is_python_build": 0,
}

# name, generator ID (therefore co_filename and C symbol), input, package bit.
FROZEN = (
    ("_frozen_importlib", "importlib._bootstrap", "Lib/importlib/_bootstrap.py", False),
    ("_frozen_importlib_external", "importlib._bootstrap_external",
     "Lib/importlib/_bootstrap_external.py", False),
    ("abc", "abc", "Lib/abc.py", False),
    ("codecs", "codecs", "Lib/codecs.py", False),
    ("io", "io", "Lib/io.py", False),
    ("encodings", "encodings", "Lib/encodings/__init__.py", True),
    ("encodings.aliases", "encodings.aliases", "Lib/encodings/aliases.py", False),
    ("encodings.utf_8", "encodings.utf_8", "Lib/encodings/utf_8.py", False),
    ("_lunar_static_main", "_lunar_static_main", "Lib/_lunar_static_main.py", False),
)
ALIASES = (
    ("_frozen_importlib", "importlib._bootstrap"),
    ("_frozen_importlib_external", "importlib._bootstrap_external"),
)
CORE_BUILTINS = (
    "marshal", "_imp", "_ast", "_tokenize", "builtins", "sys", "gc", "_warnings", "_string",
)
STATIC_ADDITIONS = {
    "atexit": "atexitmodule.c",
    "faulthandler": "faulthandler.c",
    "posix": "posixmodule.c",
    "_signal": "signalmodule.c",
    "_codecs": "_codecsmodule.c",
    "_io": "_io/_iomodule.c _io/iobase.c _io/fileio.c _io/bytesio.c "
           "_io/bufferedio.c _io/textio.c _io/stringio.c",
    "_thread": "_threadmodule.c",
    "_weakref": "_weakref.c",
    "_abc": "_abc.c",
    "_lunar_fixture_pipe": "lunar_fixture_pipe.c",
}
BUILTINS = CORE_BUILTINS + tuple(STATIC_ADDITIONS)
CODEC_ALIASES = ("u8", "utf", "utf8", "utf8_ucs2", "utf8_ucs4", "cp65001")
EXPECTED_STARTUP_MODULES = (
    "sys", "builtins", "_frozen_importlib", "_imp", "_thread", "_warnings", "_weakref",
    "_frozen_importlib_external", "_io", "marshal", "posix", "encodings", "codecs",
    "_codecs", "encodings.aliases", "encodings.utf_8", "io", "abc", "_abc", "__main__",
    "_lunar_static_main", "_lunar_fixture_pipe",
)


def manifest() -> dict[str, object]:
    """Only recipe/source facts; no claimed artifact digest or execution success."""
    return {
        "schema": "lunar-static-python-build-plan-v1",
        "preconfig": dict(PRECONFIG),
        "config": {k: list(v) if isinstance(v, list) else v for k, v in CONFIG.items()},
        "cpython": dict(CPYTHON_ARCHIVE), "toolchain": dict(ZIG_ARCHIVE),
        "target": TARGET, "profile_triple": PROFILE_TRIPLE,
        "build_environment": dict(BUILD_ENVIRONMENT), "image_mode": IMAGE_MODE,
        "max_image_bytes": MAX_IMAGE_BYTES, "builtins": sorted(BUILTINS),
        "frozen": [{"name": n, "generator_id": g, "source": s, "package": p}
                   for n, g, s, p in sorted(FROZEN)],
        "aliases": [list(a) for a in ALIASES], "codec_aliases": list(CODEC_ALIASES),
        "startup_module_expectation": sorted(EXPECTED_STARTUP_MODULES),
        "startup_expectation_observed": False,
        "artifact_state": "pending-builder", "startup_state": "not-executed",
        "production_admission": False, "runtime_load_protection": False,
        "general_code_origin_protection": False,
    }
