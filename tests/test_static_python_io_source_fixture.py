"""Pinned, inert source evidence for CPython's ``_io`` builtin."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from tools.static_python_fixture.tables import emit_static_python_tables

_ROOT = Path(__file__).resolve().parents[1]
_FIXTURE_ROOT = _ROOT / "tests/fixtures/static_python_source"
_FIXTURE = _FIXTURE_ROOT / "Modules/_iomodule.c.source"
_PROVENANCE = _FIXTURE_ROOT / "provenance.json"
_SETUP = _FIXTURE_ROOT / "Modules/Setup.bootstrap.in.source"
_DESCRIPTOR = _ROOT / "specs/189-static-python-fixture/wire-v1-example.json"
_SIZE = 24_972
_SHA256 = "9d04adc6fd2b493f3a7de3b519abbfd60476b209ccd3428eff4ed1cdf06cbaf2"
_SETUP_LINE = (
    "_io _io/_iomodule.c _io/iobase.c _io/fileio.c _io/bytesio.c "
    "_io/bufferedio.c _io/textio.c _io/stringio.c"
)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def test_io_module_source_fixture_matches_release_member_pin() -> None:
    raw = _FIXTURE.read_bytes()
    assert (len(raw), _sha256(raw)) == (_SIZE, _SHA256)

    provenance = json.loads(_PROVENANCE.read_bytes())
    member = next(
        item for item in provenance["release_archive_fixtures"]["members"]
        if item["module"] == "_io"
    )
    assert member == {
        "archive_member": "Python-3.13.12/Modules/_io/_iomodule.c",
        "fixture_path": "Modules/_iomodule.c.source",
        "module": "_io",
        "sha256": _SHA256,
        "size_bytes": _SIZE,
    }


def test_io_module_source_declares_the_expected_initializer() -> None:
    source = _FIXTURE.read_text(encoding="utf-8")
    assert '.m_name = "io"' in source
    assert "PyInit__io(void)" in source
    assert "return PyModuleDef_Init(&_PyIO_Module);" in source


def test_io_source_list_matches_template_candidate_tables_and_descriptor() -> None:
    setup_line = next(
        line for line in _SETUP.read_text(encoding="utf-8").splitlines()
        if line.startswith("_io ")
    )
    assert setup_line == _SETUP_LINE

    candidate_tables = emit_static_python_tables()
    config = candidate_tables["Modules/config.c"].decode("utf-8")
    static_recipe = candidate_tables["Modules/lunar-static-sources.mk"].decode("utf-8")
    assert config.count('{"_io", PyInit__io}') == 1
    sources_block = re.search(
        r"LUNAR_STATIC_MODULE_SOURCES := \\\n(.*?)\n\n", static_recipe, re.DOTALL
    )
    assert sources_block is not None
    objects_marker = "LUNAR_STATIC_MODULE_OBJECTS := \\\n"
    assert objects_marker in static_recipe
    objects_tail = static_recipe.split(objects_marker, 1)[1]
    candidate_sources = set(re.findall(r"Modules/[A-Za-z0-9_/]+\.c", sources_block[1]))
    candidate_objects = set(re.findall(r"Modules/[A-Za-z0-9_/]+\.o", objects_tail))
    assert {f"Modules/{path}" for path in _SETUP_LINE.split()[1:]} <= candidate_sources
    assert "Modules/_io/_iomodule.o" in candidate_objects

    descriptor = json.loads(_DESCRIPTOR.read_bytes())["descriptor"]
    builtin = next(item for item in descriptor["builtin_modules"] if item["name"] == "_io")
    assert builtin["init_symbol"] == "PyInit__io"
    assert descriptor["production_admission"] is False
