"""Fixed, inert configure candidate assets; never configures or observes a build."""

from __future__ import annotations

import json

from .profile import BUILD_ENVIRONMENT, CORE_BUILTINS

CONFIGURE_CANDIDATE_STATE = "fixed-candidate-not-configured"

# Exact enabled source rows from the pinned CPython bootstrap template. The
# installation pipe is a separate fixture-owned direct-compile input.
_ENABLED = (
    ("atexit", ("atexitmodule.c",)),
    ("faulthandler", ("faulthandler.c",)),
    ("posix", ("posixmodule.c",)),
    ("_signal", ("signalmodule.c",)),
    ("_codecs", ("_codecsmodule.c",)),
    ("_io", ("_io/_iomodule.c", "_io/iobase.c", "_io/fileio.c", "_io/bytesio.c",
              "_io/bufferedio.c", "_io/textio.c", "_io/stringio.c")),
    ("_thread", ("_threadmodule.c",)),
    ("_weakref", ("_weakref.c",)),
    ("_abc", ("_abc.c",)),
)

# The exact complement in the pinned bootstrap/stdlib template union (103
# names). This is template coverage, not a claim about configure discovery.
_DISABLED = (
    "_asyncio", "_bisect", "_blake2", "_bz2", "_codecs_cn", "_codecs_hk",
    "_codecs_iso2022", "_codecs_jp", "_codecs_kr", "_codecs_tw", "_collections",
    "_contextvars", "_csv", "_ctypes", "_ctypes_test", "_curses", "_curses_panel",
    "_datetime", "_dbm", "_decimal", "_elementtree", "_functools", "_gdbm", "_hashlib",
    "_heapq", "_interpchannels", "_interpqueues", "_interpreters", "_json", "_locale",
    "_lsprof", "_lzma", "_md5", "_multibytecodec", "_multiprocessing", "_opcode",
    "_operator", "_pickle", "_posixshmem", "_posixsubprocess", "_queue", "_random",
    "_scproxy", "_sha1", "_sha2", "_sha3", "_socket", "_sqlite3", "_sre", "_ssl",
    "_stat", "_statistics", "_struct", "_suggestions", "_symtable", "_sysconfig",
    "_testbuffer", "_testcapi", "_testclinic", "_testclinic_limited",
    "_testexternalinspection", "_testimportmultiple", "_testinternalcapi",
    "_testlimitedcapi", "_testmultiphase", "_testsinglephase", "_tkinter", "_tracemalloc",
    "_typing", "_uuid", "_xxtestfuzz", "_zoneinfo", "array", "binascii", "cmath", "errno",
    "fcntl", "grp", "itertools", "math", "mmap", "pwd", "pyexpat", "readline", "resource",
    "select", "syslog", "termios", "time", "unicodedata", "xxlimited", "xxlimited_35",
    "xxsubtype", "zlib",
)


def emit_configure_plan_assets() -> dict[str, bytes]:
    """Return fresh plan assets without reading files, environment, or host facts.

    Tool bindings and configured closure remain unresolved. No returned text is
    executed, and no candidate hash substitutes for observed configuration.
    """
    candidate = {
        "schema": "lunar-static-python-configure-candidate-v1",
        "state": CONFIGURE_CANDIDATE_STATE,
        "supersedes": "reviewed-build-inputs.json proposed_configure_argv proposal only",
        "configure": {
            "build": "x86_64-linux-gnu",
            "host": "x86_64-linux-musl",
            "argv": [
                "--build=x86_64-linux-gnu", "--host=x86_64-linux-musl",
                "--disable-shared", "--disable-test-modules", "--without-ensurepip",
                "--disable-ipv6",
                "--with-computed-gotos", "--with-pymalloc",
            ],
            "build_python_binding": "unresolved",
            "tool_bindings": {
                "CC": "unresolved separately pinned Zig compiler binding",
                "AR": "unresolved separately pinned Zig archiver binding",
                "RANLIB": "unresolved separately pinned Zig ranlib binding",
                "shell": "unresolved separately pinned configure helper binding",
            },
        },
        "environment": {
            "inherit": False,
            "values": dict(BUILD_ENVIRONMENT),
            "path_base": "emitted plan root; no execution cwd is selected",
            "unresolved_bindings": [
                "CC", "AR", "RANLIB", "build-Python/helpers",
                "ZIG_GLOBAL_CACHE_DIR", "ZIG_LOCAL_CACHE_DIR", "pkg-config suppression",
            ],
            "state": "clean-environment-plan-not-applied",
        },
        "cache": {
            "state": "candidate-feature-disable-policy-not-observed",
            "policies": {
                "ac_cv_func_dlopen": "no",
                "ac_cv_file__dev_ptmx": "no",
                "ac_cv_file__dev_ptc": "no",
            },
            "remaining_answers": "unresolved; no other configure checks are preanswered",
        },
        "module_selection": {
            "enabled_upstream": [
                {"name": name, "sources": list(sources)} for name, sources in _ENABLED
            ],
            "disabled": list(_DISABLED),
            "template_inputs": [
                {"path": "Modules/Setup.bootstrap.in", "size": 971,
                 "sha256": "bb401f9494c2f896aa40af6a8077ff9f22b99a9d4126ce38daef759427c8df88"},
                {"path": "Modules/Setup.stdlib.in", "size": 8606,
                 "sha256": "700424110da7f19053e02642da6853035490726b1cec9c9ed99b1261e447caa7"},
            ],
            "template_union_count": 103,
            "core_builtins": list(CORE_BUILTINS),
            "fixture_pipe": "_lunar_fixture_pipe remains in the fixture direct-compile plan",
            "coverage": "pinned template names only; actual optional discovery is unobserved",
            "makesetup_consumption": "unobserved",
            "staged_setup_installation": "not-performed; retained candidate asset only",
        },
        "freezer": {
            "route": "same-source-direct-c-freezer",
            "source": "Programs/_freeze_module.c",
            "frozen_tables": "required-empty",
            "initialization": "required-disabled",
            "importlib": "required-disabled",
            "stock_cross_build_route": "refused build-Python _freeze_module.py route",
            "stock_make_regeneration": "refused",
            "host_interpreter_substitution": "refused",
        },
        "unresolved": [
            "toolchain/compiler/sysroot/CRT/libc and static library provenance",
            "separately pinned build-Python and configure helper dependencies",
            "remaining cross-cache answers and actual optional module discovery",
            "generated Makefile/pyconfig.h and actual Setup output",
            "core/builtin/freezer/target role compile flags and link flags",
            "getbuildinfo DATE/TIME/GITVERSION/GITTAG/GITBRANCH constants",
            "complete configured source/header/static-link and startup closure",
        ],
        "claims": dict.fromkeys((
            "execution_enabled", "source_archive_verified", "toolchain_verified",
            "configure_performed", "configured_closure_verified", "compile_performed",
            "frozen_headers_generated", "link_performed", "artifact_verified",
            "execution_performed", "runtime_load_protection", "production_admission",
            "general_code_origin_protection",
        ), False),
    }
    config_site = (
        "# Fixed candidate feature-disable policies, not observed platform facts.\n"
        "# This is not a complete cross-cache and is never sourced by this emitter.\n"
        "ac_cv_func_dlopen=no\n"
        "ac_cv_file__dev_ptmx=no\n"
        "ac_cv_file__dev_ptc=no\n"
    ).encode("ascii")
    setup = [
        "# Fixed candidate only; actual configure/makesetup consumption is unobserved.",
        "# Core builtins and the fixture-owned pipe retain their direct-compile plan.",
        "*static*",
        *(name + " " + " ".join(sources) for name, sources in _ENABLED),
        "*disabled*",
        *_DISABLED,
    ]
    return {
        "configure-plan.json": (json.dumps(candidate, indent=2, sort_keys=True) + "\n").encode("ascii"),
        "config.site": config_site,
        "Modules/Setup.local": ("\n".join(setup) + "\n").encode("ascii"),
    }


__all__ = ["CONFIGURE_CANDIDATE_STATE", "emit_configure_plan_assets"]
