"""Pinned, inert source evidence for CPython's ``_codecs`` builtin."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from tools.static_python_fixture.tables import emit_static_python_tables

_ROOT = Path(__file__).resolve().parents[1]
_FIXTURE = _ROOT / "tests/fixtures/static_python_source/Modules/_codecsmodule.c.source"
_SETUP_FIXTURE = _ROOT / "tests/fixtures/static_python_source/Modules/Setup.bootstrap.in.source"
_PROVENANCE = _ROOT / "tests/fixtures/static_python_source/provenance.json"
_DESCRIPTOR = _ROOT / "specs/189-static-python-fixture/wire-v1-example.json"
_SIZE = 33_553
_SHA256 = "149a20c2d7aee22281ddd8756ae7eae685ae0ef21764138d41f367443182041e"
_SETUP_SIZE = 971
_SETUP_SHA256 = "bb401f9494c2f896aa40af6a8077ff9f22b99a9d4126ce38daef759427c8df88"


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def test_codec_source_fixture_is_pinned_in_release_member_manifest() -> None:
    raw = _FIXTURE.read_bytes()
    assert (len(raw), _sha256(raw)) == (_SIZE, _SHA256)

    provenance = json.loads(_PROVENANCE.read_bytes())
    members = provenance["release_archive_fixtures"]["members"]
    assert {
        (item["archive_member"], item["fixture_path"], item["size_bytes"], item["sha256"])
        for item in members
    } >= {
        (
            "Python-3.13.12/Modules/_codecsmodule.c",
            "Modules/_codecsmodule.c.source",
            _SIZE,
            _SHA256,
        )
    }
    assert provenance["build_performed"] is False
    assert provenance["full_source_execution_performed"] is False


def test_codec_source_declares_module_and_initializer_without_executing() -> None:
    source = _FIXTURE.read_text(encoding="utf-8")
    assert '#include "Python.h"' in source
    assert '#include "pycore_codecs.h"' in source
    assert "static PyMethodDef _codecs_functions[]" in source
    assert 'PyModuleDef_HEAD_INIT,\n        "_codecs"' in source
    assert "PyInit__codecs(void)" in source
    assert "return PyModuleDef_Init(&codecsmodule);" in source


def test_codec_source_has_a_fixed_direct_include_set() -> None:
    source = _FIXTURE.read_text(encoding="utf-8")
    includes = re.findall(r'^#include\s+["<]([^">]+)[">]', source, re.MULTILINE)
    assert includes == [
        "Python.h",
        "pycore_codecs.h",
        "windows.h",
        "pycore_runtime.h",
        "clinic/_codecsmodule.c.h",
    ]
    assert '#ifdef MS_WINDOWS\n#include <windows.h>\n#endif' in source


def test_bootstrap_template_declares_codec_source_but_is_not_generated_setup() -> None:
    raw = _SETUP_FIXTURE.read_bytes()
    assert (len(raw), _sha256(raw)) == (_SETUP_SIZE, _SETUP_SHA256)

    provenance = json.loads(_PROVENANCE.read_bytes())
    members = provenance["release_archive_fixtures"]["supporting_members"]
    assert members == [{
        "archive_member": "Python-3.13.12/Modules/Setup.bootstrap.in",
        "fixture_path": "Modules/Setup.bootstrap.in.source",
        "purpose": "upstream-bootstrap-template-only",
        "sha256": _SETUP_SHA256,
        "size_bytes": _SETUP_SIZE,
    }]
    assert b"_codecs _codecsmodule.c" in raw


def test_synthetic_descriptor_is_only_a_separate_metadata_cross_check() -> None:
    descriptor = json.loads(_DESCRIPTOR.read_bytes())["descriptor"]
    builtin = next(item for item in descriptor["builtin_modules"] if item["name"] == "_codecs")
    assert builtin["init_symbol"] == "PyInit__codecs"
    # The descriptor intentionally does not pin this fixture's bytes. Keeping
    # these synthetic values distinct prevents a metadata comparison from
    # being mistaken for object compilation or link evidence.
    assert builtin["source"] == {
        "path": "source/_codecs.c",
        "sha256": "b5a0e6c9a79e5ff802a5fc8539490ca64f07a2055e393d7f86a5e238adbfc3ce",
        "size": 39,
    }
    assert builtin["object"] == {
        "path": "objects/_codecs.o",
        "sha256": "e33813be012e94c746de0f57caf6aa591357d3b728eda5820a062ef9e73d96d7",
        "size": 40,
    }
    assert descriptor["production_admission"] is False

    # Cross-check the separate candidate table plan; these emitted bytes are
    # still synthetic and do not establish what any configured build used.
    tables = emit_static_python_tables()
    config = tables["Modules/config.c"].decode("utf-8")
    static_sources = tables["Modules/lunar-static-sources.mk"].decode("utf-8")
    assert config.count('{"_codecs", PyInit__codecs}') == 1
    assert "Modules/_codecsmodule.c" in static_sources
    assert "Modules/_codecsmodule.o" in static_sources

