"""Independent finite C inventories, without a compiler or runtime startup."""

from __future__ import annotations

import hashlib
import inspect
import re
import subprocess
import sys
from pathlib import Path

import pytest

from tools.static_python_fixture import tables

# Reviewed against CPython 3.13.12's frozen/config ABI, independently from the
# emitter's profile iteration and symbol transformation.
FROZEN_ROWS = (
    ("bootstrap_modules", "_frozen_importlib", "importlib._bootstrap.h", "_Py_M__importlib__bootstrap", False),
    ("bootstrap_modules", "_frozen_importlib_external", "importlib._bootstrap_external.h", "_Py_M__importlib__bootstrap_external", False),
    ("stdlib_modules", "abc", "abc.h", "_Py_M__abc", False),
    ("stdlib_modules", "codecs", "codecs.h", "_Py_M__codecs", False),
    ("stdlib_modules", "io", "io.h", "_Py_M__io", False),
    ("stdlib_modules", "encodings", "encodings.h", "_Py_M__encodings", True),
    ("stdlib_modules", "encodings.aliases", "encodings.aliases.h", "_Py_M__encodings_aliases", False),
    ("stdlib_modules", "encodings.utf_8", "encodings.utf_8.h", "_Py_M__encodings_utf_8", False),
    ("custom_modules", "_lunar_static_main", "_lunar_static_main.h", "_Py_M___lunar_static_main", False),
)
BUILTIN_ROWS = (
    ("marshal", "PyMarshal_Init"), ("_imp", "PyInit__imp"), ("_ast", "PyInit__ast"),
    ("_tokenize", "PyInit__tokenize"), ("builtins", "NULL"), ("sys", "NULL"),
    ("gc", "PyInit_gc"), ("_warnings", "_PyWarnings_Init"), ("_string", "PyInit__string"),
    ("atexit", "PyInit_atexit"), ("faulthandler", "PyInit_faulthandler"),
    ("posix", "PyInit_posix"), ("_signal", "PyInit__signal"), ("_codecs", "PyInit__codecs"),
    ("_io", "PyInit__io"), ("_thread", "PyInit__thread"), ("_weakref", "PyInit__weakref"),
    ("_abc", "PyInit__abc"), ("_lunar_fixture_pipe", "PyInit__lunar_fixture_pipe"),
)
STATIC_SOURCES = (
    "Modules/atexitmodule.c", "Modules/faulthandler.c", "Modules/posixmodule.c",
    "Modules/signalmodule.c", "Modules/_codecsmodule.c", "Modules/_io/_iomodule.c",
    "Modules/_io/iobase.c", "Modules/_io/fileio.c", "Modules/_io/bytesio.c",
    "Modules/_io/bufferedio.c", "Modules/_io/textio.c", "Modules/_io/stringio.c",
    "Modules/_threadmodule.c", "Modules/_weakref.c", "Modules/_abc.c", "Modules/lunar_fixture_pipe.c",
)
STDLIB_NAMES = (
    "_abc", "_ast", "_codecs", "_frozen_importlib", "_frozen_importlib_external", "_imp",
    "_io", "_signal", "_string", "_thread", "_tokenize", "_warnings", "_weakref", "abc",
    "atexit", "builtins", "codecs", "encodings", "faulthandler", "gc", "io", "marshal", "posix", "sys",
)


@pytest.fixture
def assets():
    return tables.emit_static_python_tables()


def _table(source: str, name: str) -> str:
    found = re.search(r"static const struct _frozen " + name + r"\[\] = \{\n(.*?)\n\};", source, re.DOTALL)
    assert found is not None
    return found[1]


def test_output_is_a_fresh_deterministic_fixed_mapping():
    first, second = tables.emit_static_python_tables(), tables.emit_static_python_tables()
    assert first == second and first is not second
    assert tuple(first) == (
        "Python/frozen.c", "Modules/config.c", "Modules/lunar-static-sources.mk", "Python/stdlib_module_names.h",
    )
    assert all(type(value) is bytes and value.endswith(b"\n") for value in first.values())
    assert {path: hashlib.sha256(data).hexdigest() for path, data in first.items()} == {
        path: hashlib.sha256(data).hexdigest() for path, data in second.items()
    }
    first["Python/frozen.c"] = b"caller mutation"
    assert tables.emit_static_python_tables() == second
    assert str(inspect.signature(tables.emit_static_python_tables)) == "() -> 'dict[str, bytes]'"


@pytest.mark.parametrize("table,module,header,symbol,package", FROZEN_ROWS)
def test_each_frozen_name_header_symbol_size_and_package_bit(assets, table, module, header, symbol, package):
    source = assets["Python/frozen.c"].decode()
    assert source.count(f'#include "frozen_modules/{header}"') == 1
    row = f'    {{"{module}", {symbol}, (int)sizeof({symbol}), ' + ("true" if package else "false") + "},"
    assert _table(source, table).count(row) == 1
    assert source.count(f'{{"{module}", {symbol},') == 1


@pytest.mark.parametrize("table,count", [("bootstrap_modules", 2), ("stdlib_modules", 6), ("custom_modules", 1), ("test_modules", 0)])
def test_four_field_sentinels_and_exact_group_counts(assets, table, count):
    body = _table(assets["Python/frozen.c"].decode(), table)
    assert len(re.findall(r'\{"[^"\n]+",', body)) == count
    assert body.endswith(f"    {{NULL, NULL, 0, false}} /* {table} sentinel */")


def test_only_nine_pending_headers_and_two_aliases_are_referenced(assets):
    source = assets["Python/frozen.c"].decode()
    headers = re.findall(r'#include "frozen_modules/(.*?)"', source)
    assert headers == [row[2] for row in FROZEN_ROWS]
    assert re.findall(r'\{"(_frozen_importlib(?:_external)?)", "([^"]+)"\}', source) == [
        ("_frozen_importlib", "importlib._bootstrap"),
        ("_frozen_importlib_external", "importlib._bootstrap_external"),
    ]
    assert "{NULL, NULL} /* aliases sentinel */" in source
    assert "const struct _module_alias *_PyImport_FrozenAliases = aliases;" in source
    assert "const struct _frozen *_PyImport_FrozenBootstrap = bootstrap_modules;" in source
    assert "const struct _frozen *_PyImport_FrozenStdlib = stdlib_modules;" in source
    assert "const struct _frozen *_PyImport_FrozenTest = test_modules;" in source
    assert "const struct _frozen *PyImport_FrozenModules = custom_modules;" in source
    assert "const unsigned char" not in source
    assert "Nine real headers must later be produced" in source


@pytest.mark.parametrize("name,initializer", BUILTIN_ROWS)
def test_each_builtin_name_has_its_exact_initializer(assets, name, initializer):
    source = assets["Modules/config.c"].decode()
    assert source.count(f'{{"{name}", {initializer}}}') == 1
    if initializer == "NULL":
        assert f"extern PyObject *PyInit_{name}(void);" not in source
    else:
        assert source.count(f"extern PyObject *{initializer}(void);") == 1


def test_exact_builtin_inventory_and_two_field_sentinel(assets):
    source = assets["Modules/config.c"].decode()
    assert tuple(re.findall(r'\{"([^"]+)", ([A-Za-z_]+)\}', source)) == BUILTIN_ROWS
    assert "struct _inittab _PyImport_Inittab[] = {" in source
    assert "{NULL, NULL} /* builtin sentinel */" in source
    assert source.count("extern PyObject *") == 17
    assert 'extern "C" {' in source


def test_static_recipe_lists_only_explicit_sources_and_objects(assets):
    source = assets["Modules/lunar-static-sources.mk"].decode()
    sources = re.search(r"LUNAR_STATIC_MODULE_SOURCES := (.*?)\n\n", source, re.DOTALL)
    objects = re.search(r"LUNAR_STATIC_MODULE_OBJECTS := (.*)\n", source, re.DOTALL)
    assert sources is not None and objects is not None
    assert tuple(re.findall(r"Modules/[A-Za-z0-9_/]+\.c", sources[1])) == STATIC_SOURCES
    assert tuple(re.findall(r"Modules/[A-Za-z0-9_/]+\.o", objects[1])) == tuple(path[:-2] + ".o" for path in STATIC_SOURCES)
    assert "$(wildcard" not in source and "$(shell" not in source and "_MODOBJS_" not in source
    assert "Unapplied direct compile/link input list" in source
    assert "does not replace the CPython core build or disable stock Setup.stdlib" in source
    assert "Modules/lunar_fixture_pipe.c must be supplied from the reviewed pipe.c asset" in source


def test_stdlib_metadata_is_finite_top_level_and_excludes_lunar_custom_names(assets):
    source = assets["Python/stdlib_module_names.h"].decode()
    assert tuple(re.findall(r'^    "([^"]+)",$', source, re.MULTILINE)) == STDLIB_NAMES
    assert "static const char * _Py_stdlib_module_names[] = {" in source
    assert "encodings.aliases" not in source and "encodings.utf_8" not in source
    assert "_lunar_static_main" not in source and "_lunar_fixture_pipe" not in source


@pytest.mark.parametrize("stock_name", ["zipimport", "site", "runpy", "__hello__", "__phello__", "_ctypes", "_socket", "errno"])
def test_stock_test_and_optional_module_discovery_cannot_expand_the_tables(assets, stock_name):
    assert all(stock_name.encode() not in data for data in assets.values())


def test_no_host_inventory_filesystem_or_process_is_consulted(monkeypatch):
    expected = tables.emit_static_python_tables()
    monkeypatch.setattr(sys, "builtin_module_names", ("host_inventory_must_not_load",))
    monkeypatch.setattr(sys, "stdlib_module_names", frozenset({"host_stdlib_must_not_load"}))
    monkeypatch.setattr(Path, "read_bytes", lambda _self: pytest.fail("pure table emitter cannot read files"))
    monkeypatch.setattr(Path, "read_text", lambda _self, **_kwargs: pytest.fail("pure table emitter cannot read files"))
    monkeypatch.setattr(subprocess, "run", lambda *_args, **_kwargs: pytest.fail("pure table emitter cannot run a process"))
    monkeypatch.setattr(subprocess, "Popen", lambda *_args, **_kwargs: pytest.fail("pure table emitter cannot start a process"))
    assert tables.emit_static_python_tables() == expected
    with pytest.raises(TypeError):
        tables.emit_static_python_tables({"host": "inventory"})
