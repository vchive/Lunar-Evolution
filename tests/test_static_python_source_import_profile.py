"""Provider-free import observations over the exact emitted frozen main source."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from lunar_evolution.static_python_import_audit import audit_static_python_imports
from tools.static_python_fixture.recipe import emit_build_plan

_ROOT = Path(__file__).resolve().parents[1]
_REVIEWED_INPUTS = _ROOT / "tools/static_python_fixture/reviewed-build-inputs.json"


def test_audits_exact_emitted_expanded_static_main_bytes(tmp_path: Path) -> None:
    reviewed = json.loads(_REVIEWED_INPUTS.read_bytes())
    tasks = [task for task in reviewed["freeze_tasks"]
             if task["generator_id"] == "_lunar_static_main"]
    assert len(tasks) == 1
    task = tasks[0]
    assert task["name"] == "_lunar_static_main"
    assert task["origin"] == "expanded-fixture-asset"

    plan = emit_build_plan(tmp_path / "plan")
    emitted_source = (plan / task["source"]).read_bytes()
    assert len(emitted_source) == task["source_size"]
    assert hashlib.sha256(emitted_source).hexdigest() == task["source_sha256"]

    result = audit_static_python_imports(
        {task["name"]: emitted_source},
        expected_source_sha256={task["name"]: task["source_sha256"]},
    )
    wire = result.to_dict()
    assert wire["sources"] == [{
        "name": "_lunar_static_main",
        "source_sha256": task["source_sha256"],
    }]
    assert wire["imports"] == [
        {"source": "_lunar_static_main", "target": "_imp", "kind": "import"},
        {"source": "_lunar_static_main", "target": "_lunar_fixture_pipe", "kind": "import"},
        {"source": "_lunar_static_main", "target": "sys", "kind": "import"},
    ]
    assert wire["unresolved_imports"] == []
    assert wire["unsupported_import_sites"] == [{
        "source": "_lunar_static_main",
        "line": 68,
        "column": 47,
        "reason": "dynamic-import",
    }]
    assert wire["evidence_scope"] == "source-ast-import-observations-only"
    assert wire["claims"] == {
        "source_graph_verified": False,
        "configured_closure_verified": False,
        "build_performed": False,
        "runtime_startup_performed": False,
        "installation_accepted": False,
        "runtime_load_protection": False,
        "general_code_origin_protection": False,
        "production_admission": False,
    }


def test_audits_pinned_cpython_31312_release_import_sources() -> None:
    fixture_root = _ROOT / "tests/fixtures/static_python_source"
    provenance = json.loads((fixture_root / "provenance.json").read_bytes())
    assert provenance["official_python_org_archive_verified"] is False
    assert provenance["official_python_org_archive_verification_note"] == (
        "false means this fixture manifest does not itself contain an archive-verification "
        "receipt; see the separate release-input audit for its retained signature transcript "
        "and trust limits"
    )
    archive = provenance["release_archive_fixtures"]
    assert archive["archive_size_bytes"] == 22_926_488
    assert archive["archive_sha256"] == (
        "2a84cd31dd8d8ea8aaff75de66fc1b4b0127dd5799aa50a64ae9a313885b4593"
    )
    assert archive["signature_audit_reference"] == (
        "specs/189-static-python-fixture/release-input-audit-20261021.md"
    )
    assert "not a claim that no separate verification was performed" in (
        fixture_root / "README.md"
    ).read_text(encoding="utf-8")
    pins = {
        "_frozen_importlib": (
            "Lib/importlib/_bootstrap.py.source", 57082,
            "b84488f731914f6da30607e10f6f8d4c5c2ff7f4b0e913060aa66999c04f6252",
        ),
        "_frozen_importlib_external": (
            "Lib/importlib/_bootstrap_external.py.source", 73219,
            "a97a03ea9f9d38d90c8a50942183382ff5a479e7c4c5163c2ac5bae3561444ae",
        ),
        "abc": (
            "Lib/abc.py.source", 6538,
            "e558702a95cdce3febd289da021715d2b92bc43995b8a1bc58dfa1c3d8010287",
        ),
        "codecs": (
            "Lib/codecs.py.source", 36978,
            "2f278497548b8313580b247a1097a0a304e5087a355ebb11a92ec685fa9e63ff",
        ),
        "encodings.__init__": (
            "Lib/encodings/__init__.py.source", 5884,
            "78c4744d407690f321565488710b5aaf6486b5afa8d185637aa1e7633ab59cd8",
        ),
        "encodings.aliases": (
            "Lib/encodings/aliases.py.source", 15713,
            "cac92d68c7ea5bc0f05b448b9144e3bdf236d0b7d27ab66112e96d43aad15b3f",
        ),
        "encodings.utf_8": (
            "Lib/encodings/utf_8.py.source", 1005,
            "ba0cac060269583523ca9506473a755203037c57d466a11aa89a30a5f6756f3d",
        ),
        "io": (
            "Lib/io.py.source", 3582,
            "7cec3cb8ac004058dd0a5af246e6d950fb59c7ddd0058fda48bcb3fcb98d8822",
        ),
    }
    manifest_members = archive["members"]
    assert len(manifest_members) == len(pins)
    assert {item["module"] for item in manifest_members} == set(pins)
    sources = {}
    for name, (relative_path, expected_size, expected_sha256) in pins.items():
        raw = (fixture_root / relative_path).read_bytes()
        assert len(raw) == expected_size
        assert hashlib.sha256(raw).hexdigest() == expected_sha256
        fixture = next(
            item for item in manifest_members if item["module"] == name
        )
        assert fixture["fixture_path"] == relative_path
        assert fixture["size_bytes"] == expected_size
        assert fixture["sha256"] == expected_sha256
        sources[name] = raw

    result = audit_static_python_imports(
        sources,
        expected_source_sha256={name: pin[2] for name, pin in pins.items()},
    )
    wire = result.to_dict()
    assert result.import_count == len(wire["imports"]) == 28
    assert result.unresolved_count == len(wire["unresolved_imports"]) == 0
    assert result.unsupported_count == len(wire["unsupported_import_sites"]) == 4
    assert hashlib.sha256(result.wire_bytes).hexdigest() == (
        "9e3a0ad1fb808f703f20ed993247e732130f0ccff9b03328196153766bdd9d8f"
    )
    assert wire["unsupported_import_sites"] == [
        {
            "source": "_frozen_importlib",
            "line": 1176,
            "column": 8,
            "reason": "dynamic-code-execution",
        },
        {
            "source": "_frozen_importlib_external",
            "line": 1431,
            "column": 15,
            "reason": "dynamic-code-execution",
        },
        {"source": "codecs", "line": 16, "column": 4, "reason": "star-import"},
        {"source": "encodings", "line": 99, "column": 18, "reason": "dynamic-import"},
    ]
    assert wire["claims"] == {
        "source_graph_verified": False,
        "configured_closure_verified": False,
        "build_performed": False,
        "runtime_startup_performed": False,
        "installation_accepted": False,
        "runtime_load_protection": False,
        "general_code_origin_protection": False,
        "production_admission": False,
    }


def test_c_startup_report_archive_member_pins_have_complete_digest_shape() -> None:
    report = (_ROOT / "specs/189-static-python-fixture/c-startup-source-audit-20261021.md")
    content = report.read_text(encoding="utf-8")
    rows = re.findall(
        r"^\| `([^`]+)` \| ([0-9,]+) \| `([0-9a-f]+)` \|$",
        content,
        flags=re.MULTILINE,
    )
    assert len(rows) == 23
    assert all(len(digest) == 64 for _path, _size, digest in rows)
    freeze_module = next(row for row in rows if row[0] == "Programs/_freeze_module.c")
    assert freeze_module == (
        "Programs/_freeze_module.c",
        "6,590",
        "50b61a5efbfb6c294e7ff0ffe6a01c0964b8c954285bcbac5d99c7a5483ca9be",
    )
