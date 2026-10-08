"""Deterministic finite CPython 3.13.12 table assets, without I/O or execution.

The generated tables use the reviewed four-field ``struct _frozen`` and
two-field ``struct _module_alias`` ABI. Header references remain pending inputs
to the pinned same-source freezer; no bytecode or placeholder arrays are made
here. The static-source make fragment is an unapplied plan and does not disable
stock Setup.stdlib, configure output, or makesetup on its own.
"""

from __future__ import annotations

from .profile import ALIASES, CORE_BUILTINS, FROZEN, STATIC_ADDITIONS

_STATIC_MODULES = tuple((name, tuple(paths.split())) for name, paths in STATIC_ADDITIONS.items())
_CORE_INITIALIZERS = (
    ("marshal", "PyMarshal_Init", "Python/marshal.c"),
    ("_imp", "PyInit__imp", "Python/import.c"),
    ("_ast", "PyInit__ast", "Python/Python-ast.c"),
    ("_tokenize", "PyInit__tokenize", "Python/Python-tokenize.c"),
    ("builtins", "NULL", "Python/bltinmodule.c"),
    ("sys", "NULL", "Python/sysmodule.c"),
    ("gc", "PyInit_gc", "Modules/gcmodule.c"),
    ("_warnings", "_PyWarnings_Init", "Python/_warnings.c"),
    ("_string", "PyInit__string", "Objects/unicodeobject.c"),
)
_PROFILE_BANNER = (
    "Generated from the fixed Lunar CPython 3.13.12 profile; plan-only. "
    "No host inventory, target execution, or runtime admission."
)


def _symbol(generator_id: str) -> str:
    # Programs/_freeze_module.c:get_varname changes each dot to one underscore.
    return "_Py_M__" + generator_id.replace(".", "_")


def _frozen_table(name: str, entries: tuple[tuple[str, str, str, bool], ...]) -> str:
    lines = [f"static const struct _frozen {name}[] = {{"]
    for module_name, generator_id, _source, package in entries:
        symbol = _symbol(generator_id)
        lines.append(
            f'    {{"{module_name}", {symbol}, (int)sizeof({symbol}), '
            + ("true" if package else "false") + "},"
        )
    lines.extend([f"    {{NULL, NULL, 0, false}} /* {name} sentinel */", "};"])
    return "\n".join(lines)


def _frozen_source() -> bytes:
    bootstrap = tuple(item for item in FROZEN if item[0] in {
        "_frozen_importlib", "_frozen_importlib_external",
    })
    stdlib = tuple(item for item in FROZEN if item[0] not in {
        "_frozen_importlib", "_frozen_importlib_external", "_lunar_static_main",
    })
    custom = tuple(item for item in FROZEN if item[0] == "_lunar_static_main")
    lines = [
        f"/* {_PROFILE_BANNER} */",
        "/* Nine real headers must later be produced by the pinned same-source freezer. */",
        '#include "Python.h"', '#include "pycore_import.h"', "#include <stdbool.h>", "",
        *(f'#include "frozen_modules/{item[1]}.h"' for item in FROZEN), "",
        _frozen_table("bootstrap_modules", bootstrap), "",
        _frozen_table("stdlib_modules", stdlib), "",
        _frozen_table("custom_modules", custom), "",
        _frozen_table("test_modules", ()), "",
        "const struct _frozen *_PyImport_FrozenBootstrap = bootstrap_modules;",
        "const struct _frozen *_PyImport_FrozenStdlib = stdlib_modules;",
        "const struct _frozen *_PyImport_FrozenTest = test_modules;",
        "const struct _frozen *PyImport_FrozenModules = custom_modules;", "",
        "static const struct _module_alias aliases[] = {",
        *(f'    {{"{alias}", "{original}"}},' for alias, original in ALIASES),
        "    {NULL, NULL} /* aliases sentinel */", "};",
        "const struct _module_alias *_PyImport_FrozenAliases = aliases;", "",
    ]
    return "\n".join(lines).encode("ascii")


def _config_source() -> bytes:
    initializers = tuple((name, initializer) for name, initializer, _source in _CORE_INITIALIZERS)
    initializers += tuple((name, "PyInit_" + name) for name, _sources in _STATIC_MODULES)
    lines = [
        f"/* {_PROFILE_BANNER} */", '#include "Python.h"', "",
        "#ifdef __cplusplus", 'extern "C" {', "#endif", "",
        *(f"extern PyObject *{initializer}(void);" for _name, initializer in initializers
          if initializer != "NULL"), "",
        "struct _inittab _PyImport_Inittab[] = {",
        *(f'    {{"{name}", {initializer}}},' for name, initializer in initializers),
        "    {NULL, NULL} /* builtin sentinel */", "};", "",
        "#ifdef __cplusplus", "}", "#endif", "",
    ]
    return "\n".join(lines).encode("ascii")


def _make_vector(name: str, values: tuple[str, ...]) -> str:
    return name + " := \\\n" + " \\\n".join("    " + value for value in values)


def _static_sources() -> bytes:
    sources = tuple("Modules/" + source for _name, paths in _STATIC_MODULES for source in paths)
    core = tuple(source for _name, _initializer, source in _CORE_INITIALIZERS)
    lines = [
        f"# {_PROFILE_BANNER}",
        "# Unapplied direct compile/link input list; no makesetup or wildcard discovery.",
        "# This does not replace the CPython core build or disable stock Setup.stdlib.",
        "# Modules/lunar_fixture_pipe.c must be supplied from the reviewed pipe.c asset.", "",
        _make_vector("LUNAR_CORE_BUILTIN_SOURCES", core), "",
        _make_vector("LUNAR_STATIC_MODULE_SOURCES", sources), "",
        _make_vector("LUNAR_STATIC_MODULE_OBJECTS", tuple(source[:-2] + ".o" for source in sources)),
        "",
    ]
    return "\n".join(lines).encode("ascii")


def _stdlib_metadata() -> bytes:
    # sys.stdlib_module_names contains top-level standard-library names only.
    # The two Lunar custom modules are not classified as Python stdlib metadata.
    names = set(CORE_BUILTINS) | {name for name, _sources in _STATIC_MODULES if name != "_lunar_fixture_pipe"}
    names |= {item[0].split(".")[0] for item in FROZEN if item[0] != "_lunar_static_main"}
    lines = [
        f"/* {_PROFILE_BANNER} */",
        "/* Finite top-level stdlib metadata; not an import or code-origin grant. */",
        "static const char * _Py_stdlib_module_names[] = {",
        *(f'    "{name}",' for name in sorted(names)), "};", "",
    ]
    return "\n".join(lines).encode("ascii")


def emit_static_python_tables() -> dict[str, bytes]:
    """Return fresh deterministic table assets for the fixed reviewed profile.

    No inventories, source paths, filesystem readers, or interpreter objects are
    accepted. The outputs are source preparation only, without compile/link,
    real frozen headers, startup, loader enforcement, or runtime observations.
    """
    return {
        "Python/frozen.c": _frozen_source(),
        "Modules/config.c": _config_source(),
        "Modules/lunar-static-sources.mk": _static_sources(),
        "Python/stdlib_module_names.h": _stdlib_metadata(),
    }


__all__ = ["emit_static_python_tables"]
