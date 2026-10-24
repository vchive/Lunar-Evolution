"""Pinned, inert CPython startup-lifecycle source evidence."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tools.static_python_fixture.profile import CONFIG, EXPECTED_STARTUP_MODULES

_ROOT = Path(__file__).resolve().parents[1]
_FIXTURE_ROOT = _ROOT / "tests/fixtures/static_python_source"
_FIXTURE = _FIXTURE_ROOT / "Python/pylifecycle.c.source"
_PROVENANCE = _FIXTURE_ROOT / "provenance.json"
_ARCHIVE_SHA256 = "2a84cd31dd8d8ea8aaff75de66fc1b4b0127dd5799aa50a64ae9a313885b4593"
_SIZE = 106_247
_SHA256 = "21296f86275077e4f19234a2c32691ee087fea961c28745770373a6c4ef70789"


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def test_pylifecycle_fixture_matches_pinned_supporting_release_member() -> None:
    raw = _FIXTURE.read_bytes()
    assert (len(raw), _sha256(raw)) == (_SIZE, _SHA256)

    provenance = json.loads(_PROVENANCE.read_bytes())
    archive = provenance["release_archive_fixtures"]
    assert archive["archive_sha256"] == _ARCHIVE_SHA256
    assert archive["archive_size_bytes"] == 22_926_488
    supporting = [
        item for item in archive["supporting_members"]
        if item["archive_member"] == "Python-3.13.12/Python/pylifecycle.c"
    ]
    assert supporting == [{
        "archive_member": "Python-3.13.12/Python/pylifecycle.c",
        "fixture_path": "Python/pylifecycle.c.source",
        "purpose": "upstream-startup-lifecycle-source-only",
        "sha256": _SHA256,
        "size_bytes": _SIZE,
    }]
    assert all(item["module"] != "pylifecycle" for item in archive["members"])
    assert provenance["build_performed"] is False
    assert provenance["full_source_execution_performed"] is False


def test_pylifecycle_warning_and_site_imports_follow_pinned_config_guards() -> None:
    source = _FIXTURE.read_text(encoding="utf-8")

    warning_start = source.index(
        "if (is_main_interp) {\n        /* Initialize warnings. */"
    )
    site_start = source.index("if (config->site_import) {", warning_start)
    warning_branch = source[warning_start:site_start]
    assert "if (warnoptions != NULL && PyList_Check(warnoptions) &&\n            PyList_Size(warnoptions) > 0)" in warning_branch
    assert 'PyImport_ImportModule("warnings")' in warning_branch
    assert "Py_XDECREF(warnoptions);" in warning_branch

    site_end = source.index("\n    }", site_start) + len("\n    }")
    site_branch = source[site_start:site_end]
    assert "status = init_import_site();" in site_branch
    helper_start = source.index("init_import_site(void)", site_end)
    helper_end = source.index("\n}", helper_start)
    site_helper = source[helper_start:helper_end]
    assert 'PyImport_ImportModule("site")' in site_helper

    # These are candidate metadata pins only; they do not establish runtime config.
    assert CONFIG["warnoptions"] == []
    assert CONFIG["site_import"] == 0
    assert "warnings" not in EXPECTED_STARTUP_MODULES
    assert "site" not in EXPECTED_STARTUP_MODULES
