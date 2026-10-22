"""Pinned source-only callsite evidence for unawaited-coroutine warnings."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from lunar_evolution.static_python_import_audit import audit_static_python_imports

_ROOT = Path(__file__).resolve().parents[1]
_FIXTURE_ROOT = _ROOT / "tests/fixtures/static_python_source"
_WARNINGS = _FIXTURE_ROOT / "Lib/warnings.py.source"
_GENOBJECT = _FIXTURE_ROOT / "Objects/genobject.c.source"
_WARNINGS_C = _FIXTURE_ROOT / "Python/_warnings.c.source"
_PROVENANCE = _FIXTURE_ROOT / "provenance.json"
_ARCHIVE_SHA256 = "2a84cd31dd8d8ea8aaff75de66fc1b4b0127dd5799aa50a64ae9a313885b4593"
_PINS = {
    "Python-3.13.12/Lib/warnings.py": (
        "Lib/warnings.py.source",
        "upstream-warning-source-only",
        27_071,
        "e040f52be0199c69fa8c0d35428ba64e6f9b6412691a689ccbd7c23e07c6ed3f",
    ),
    "Python-3.13.12/Objects/genobject.c": (
        "Objects/genobject.c.source",
        "upstream-coroutine-finalization-source-only",
        80_432,
        "f8acbdbdf76b13b68d36c741437a34e3b50e3f41d42770ba69b20d5455fb7e25",
    ),
}


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def test_callsite_sources_match_pinned_release_archive_members() -> None:
    provenance = json.loads(_PROVENANCE.read_bytes())
    archive = provenance["release_archive_fixtures"]
    assert archive["archive_sha256"] == _ARCHIVE_SHA256
    assert archive["archive_size_bytes"] == 22_926_488

    supporting = {item["archive_member"]: item for item in archive["supporting_members"]}
    for archive_member, (fixture_path, purpose, expected_size, expected_sha256) in _PINS.items():
        raw = (_FIXTURE_ROOT / fixture_path).read_bytes()
        assert (len(raw), _sha256(raw)) == (expected_size, expected_sha256)
        assert supporting[archive_member] == {
            "archive_member": archive_member,
            "fixture_path": fixture_path,
            "purpose": purpose,
            "sha256": expected_sha256,
            "size_bytes": expected_size,
        }

    module_sources = {item["module"] for item in archive["members"]}
    assert "warnings" not in module_sources
    assert "genobject" not in module_sources
    assert provenance["build_performed"] is False
    assert provenance["full_source_execution_performed"] is False


def test_generator_finalizer_warns_only_for_a_never_started_coroutine() -> None:
    source = _GENOBJECT.read_text(encoding="utf-8")
    start = source.index("void\n_PyGen_Finalize(")
    end = source.index("\nstatic void\ngen_clear_frame", start)
    finalize = source[start:end]

    assert "_PyGen_GetCode(gen)->co_flags & CO_COROUTINE &&\n        gen->gi_frame_state == FRAME_CREATED" in finalize
    assert "_PyErr_WarnUnawaitedCoroutine((PyObject *)gen);" in finalize
    assert "else {\n        PyObject *res = gen_close(gen, NULL);" in finalize
    # The shared finalizer is wired into generator, coroutine, and async-generator types.
    assert source.count("_PyGen_Finalize,                            /* tp_finalize */") == 3


def test_python_warning_helper_and_core_c_hook_share_the_call_contract() -> None:
    warnings = _WARNINGS.read_text(encoding="utf-8")
    helper_start = warnings.index("# Private utility function called by _PyErr_WarnUnawaitedCoroutine")
    helper_end = warnings.index("\n\n# filters contains", helper_start)
    helper = warnings[helper_start:helper_end]
    assert "def _warn_unawaited_coroutine(coro):" in helper
    assert "if coro.cr_origin is not None:\n        import linecache, traceback" in helper
    assert "warn(msg, category=RuntimeWarning, stacklevel=2, source=coro)" in helper

    format_start = warnings.index("def _formatwarnmsg_impl(msg):")
    format_end = warnings.index("# Keep a reference to check if the function was replaced", format_start)
    formatting = warnings[format_start:format_end]
    assert "if msg.line is None:\n        try:\n            import linecache" in formatting
    assert "if msg.source is not None:\n        try:\n            import tracemalloc" in formatting
    assert "import linecache\n    linecache.getlines(filename, module_globals)" in warnings

    imports_start = warnings.index("try:\n    from _warnings import (")
    imports_end = warnings.index("\n\n# Module initialization", imports_start)
    warning_imports = warnings[imports_start:imports_end]
    assert "warn, warn_explicit, _filters_mutated" in warning_imports
    assert "except ImportError:" in warning_imports

    warnings_c = _WARNINGS_C.read_text(encoding="utf-8")
    c_start = warnings_c.index("void\n_PyErr_WarnUnawaitedCoroutine(")
    c_end = warnings_c.index("\nstatic PyMethodDef warnings_functions[]", c_start)
    c_hook = warnings_c[c_start:c_end]
    assert "GET_WARNINGS_ATTR(interp, _warn_unawaited_coroutine, 1)" in c_hook
    assert "PyObject_CallOneArg(fn, coro)" in c_hook
    assert "_PyErr_WarnFormat(coro, PyExc_RuntimeWarning" in c_hook

    # warn_explicit returns for the ignore action before its local linecache
    # import. This is source ordering evidence, not proof of runtime reachability.
    explicit_start = warnings.index("def warn_explicit(")
    ignore_action = 'if action == "ignore":\n        return'
    ignore_return = warnings.index(ignore_action, explicit_start)
    linecache_import = warnings.index(
        "\n    import linecache\n    linecache.getlines(filename, module_globals)",
        explicit_start,
    )
    assert ignore_return < linecache_import


def test_warning_python_source_ast_imports_remain_supporting_observations() -> None:
    raw = _WARNINGS.read_bytes()
    expected_sha256 = _PINS["Python-3.13.12/Lib/warnings.py"][3]
    observation = audit_static_python_imports(
        {"warnings": raw},
        expected_source_sha256={"warnings": expected_sha256},
    )
    wire = observation.to_dict()

    assert wire["sources"] == [{"name": "warnings", "source_sha256": expected_sha256}]
    assert {
        (edge["target"], edge["kind"])
        for edge in wire["imports"]
    } == {
        ("_warnings", "from-import"),
        ("builtins", "import"),
        ("functools", "import"),
        ("inspect", "import"),
        ("linecache", "import"),
        ("re", "import"),
        ("sys", "import"),
        ("traceback", "import"),
        ("tracemalloc", "import"),
        ("types", "from-import"),
    }
    assert wire["unresolved_imports"] == []
    assert wire["unsupported_import_sites"] == [{
        "source": "warnings",
        "line": 267,
        "column": 16,
        "reason": "dynamic-import",
    }]
    assert wire["evidence_scope"] == "source-ast-import-observations-only"
    assert all(value is False for value in wire["claims"].values())
