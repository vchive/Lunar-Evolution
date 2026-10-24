"""Pinned, inert source evidence for CPython's ``_abc`` builtin."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from tools.static_python_fixture.tables import emit_static_python_tables

_ROOT = Path(__file__).resolve().parents[1]
_FIXTURE_ROOT = _ROOT / "tests/fixtures/static_python_source"
_FIXTURE = _FIXTURE_ROOT / "Modules/_abc.c.source"
_PROVENANCE = _FIXTURE_ROOT / "provenance.json"
_SETUP = _FIXTURE_ROOT / "Modules/Setup.bootstrap.in.source"
_DESCRIPTOR = _ROOT / "specs/189-static-python-fixture/wire-v1-example.json"
_SIZE = 27_112
_SHA256 = "a4abd74e245af77f5a8c40ac8d443153ff8636e4e10a8578e9dddecaa3d0b9e8"


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def test_abc_source_fixture_matches_release_member_pin() -> None:
    raw = _FIXTURE.read_bytes()
    assert (len(raw), _sha256(raw)) == (_SIZE, _SHA256)

    provenance = json.loads(_PROVENANCE.read_bytes())
    archive = provenance["release_archive_fixtures"]
    assert archive["archive_sha256"] == (
        "2a84cd31dd8d8ea8aaff75de66fc1b4b0127dd5799aa50a64ae9a313885b4593"
    )
    member = next(item for item in archive["members"] if item["module"] == "_abc")
    assert member == {
        "archive_member": "Python-3.13.12/Modules/_abc.c",
        "fixture_path": "Modules/_abc.c.source",
        "module": "_abc",
        "sha256": _SHA256,
        "size_bytes": _SIZE,
    }
    assert provenance["build_performed"] is False
    assert provenance["full_source_execution_performed"] is False


def test_abc_source_declaration_and_bootstrap_row_are_consistent() -> None:
    source = _FIXTURE.read_text(encoding="utf-8")
    assert '.m_name = "_abc"' in source
    assert "PyInit__abc(void)" in source
    assert "return PyModuleDef_Init(&_abcmodule);" in source

    rows = [line for line in _SETUP.read_text(encoding="utf-8").splitlines()
            if line.startswith("_abc ")]
    assert rows == ["_abc _abc.c"]


def test_abc_candidate_tables_and_synthetic_descriptor_are_separate_metadata() -> None:
    tables = emit_static_python_tables()
    config = tables["Modules/config.c"].decode("utf-8")
    static_plan = tables["Modules/lunar-static-sources.mk"].decode("utf-8")
    assert config.count('{"_abc", PyInit__abc}') == 1

    source_block = re.search(
        r"LUNAR_STATIC_MODULE_SOURCES := \\\n(.*?)\n\n", static_plan, re.DOTALL
    )
    assert source_block is not None
    objects_marker = "LUNAR_STATIC_MODULE_OBJECTS := \\\n"
    assert objects_marker in static_plan
    objects_tail = static_plan.split(objects_marker, 1)[1]
    candidate_sources = set(re.findall(r"Modules/[A-Za-z0-9_/]+\.c", source_block[1]))
    candidate_objects = set(re.findall(r"Modules/[A-Za-z0-9_/]+\.o", objects_tail))
    assert "Modules/_abc.c" in candidate_sources
    assert "Modules/_abc.o" in candidate_objects

    descriptor = json.loads(_DESCRIPTOR.read_bytes())["descriptor"]
    builtin = next(item for item in descriptor["builtin_modules"] if item["name"] == "_abc")
    assert builtin["init_symbol"] == "PyInit__abc"
    assert builtin["source"] == {
        "path": "source/_abc.c",
        "sha256": "352287d358cf86a12de903e6ecf91454b2640023ce2b206f3c73e2bd0524ecec",
        "size": 36,
    }
    assert builtin["object"] == {
        "path": "objects/_abc.o",
        "sha256": "102000979b958048c3315484b13b568ca84f78efff619a2f91ee35cf5625ff00",
        "size": 37,
    }
    assert descriptor["production_admission"] is False
