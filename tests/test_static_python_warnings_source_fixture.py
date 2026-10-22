"""Pinned, inert source evidence for CPython's core ``_warnings`` initializer."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from tools.static_python_fixture.profile import BUILTINS, CONFIG, EXPECTED_STARTUP_MODULES
from tools.static_python_fixture.tables import _CORE_INITIALIZERS, emit_static_python_tables

_ROOT = Path(__file__).resolve().parents[1]
_FIXTURE_ROOT = _ROOT / "tests/fixtures/static_python_source"
_FIXTURE = _FIXTURE_ROOT / "Python/_warnings.c.source"
_PROVENANCE = _FIXTURE_ROOT / "provenance.json"
_BOOTSTRAP = _FIXTURE_ROOT / "Modules/Setup.bootstrap.in.source"
_STDLIB = _FIXTURE_ROOT / "Modules/Setup.stdlib.in.source"
_DESCRIPTOR = _ROOT / "specs/189-static-python-fixture/wire-v1-example.json"
_SIZE = 43_088
_SHA256 = "bed91ba65456a2bc1ca278a4d320be978487563a566c79a9e57b0bf46c40352d"
_STDLIB_SIZE = 8_606
_STDLIB_SHA256 = "700424110da7f19053e02642da6853035490726b1cec9c9ed99b1261e447caa7"
_ARCHIVE_SHA256 = "2a84cd31dd8d8ea8aaff75de66fc1b4b0127dd5799aa50a64ae9a313885b4593"


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def test_warnings_source_fixture_matches_pinned_release_member() -> None:
    raw = _FIXTURE.read_bytes()
    assert (len(raw), _sha256(raw)) == (_SIZE, _SHA256)

    provenance = json.loads(_PROVENANCE.read_bytes())
    archive = provenance["release_archive_fixtures"]
    assert archive["archive_sha256"] == _ARCHIVE_SHA256
    member = next(item for item in archive["members"] if item["module"] == "_warnings")
    assert member == {
        "archive_member": "Python-3.13.12/Python/_warnings.c",
        "fixture_path": "Python/_warnings.c.source",
        "module": "_warnings",
        "sha256": _SHA256,
        "size_bytes": _SIZE,
    }
    stdlib = next(item for item in archive["supporting_members"]
                  if item["archive_member"] == "Python-3.13.12/Modules/Setup.stdlib.in")
    assert stdlib == {
        "archive_member": "Python-3.13.12/Modules/Setup.stdlib.in",
        "fixture_path": "Modules/Setup.stdlib.in.source",
        "purpose": "upstream-stdlib-template-only",
        "sha256": _STDLIB_SHA256,
        "size_bytes": _STDLIB_SIZE,
    }
    assert (_STDLIB.stat().st_size, _sha256(_STDLIB.read_bytes())) == (
        _STDLIB_SIZE, _STDLIB_SHA256,
    )
    assert provenance["build_performed"] is False
    assert provenance["full_source_execution_performed"] is False


def test_warnings_source_declares_module_and_core_initializer() -> None:
    source = _FIXTURE.read_text(encoding="utf-8")
    assert '#define MODULE_NAME "_warnings"' in source
    assert ".m_name = MODULE_NAME" in source
    assert "static struct PyModuleDef warnings_module = {" in source
    assert "PyModuleDef_HEAD_INIT," in source
    assert "_PyWarnings_Init(void)" in source
    assert "return PyModuleDef_Init(&warnings_module);" in source


def test_warnings_uses_a_conditional_lazy_import_of_python_warnings() -> None:
    source = _FIXTURE.read_text(encoding="utf-8")
    start = source.index("get_warnings_attr(PyInterpreterState *interp")
    end = source.index("static PyObject *\nget_once_registry", start)
    function = source[start:end]
    assert "if (try_import && !_Py_IsInterpreterFinalizing(interp))" in function
    assert "warnings_module = PyImport_Import(&_Py_ID(warnings));" in function
    assert "if (PyErr_ExceptionMatches(PyExc_ImportError))" in function
    assert "PyErr_Clear();" in function
    assert "warnings_module = PyImport_GetModule(&_Py_ID(warnings));" in function
    assert "(void)PyObject_GetOptionalAttr(warnings_module, attr, &obj);" in function

    # Candidate startup config avoids CPython's explicit warnoptions import.
    assert CONFIG["warnoptions"] == []
    assert CONFIG["site_import"] == 0

    # The reviewed finite profile includes the C builtin but not the separate
    # Python-level warnings module. This only rules out a configured startup
    # import; it does not settle warning paths reached by the fixed workload.
    assert "_warnings" in BUILTINS
    assert "warnings" not in BUILTINS
    assert "warnings" not in EXPECTED_STARTUP_MODULES


def test_warnings_source_bounds_conditional_python_hooks_and_c_fallbacks() -> None:
    source = _FIXTURE.read_text(encoding="utf-8")
    try_import_calls = re.findall(
        r"GET_WARNINGS_ATTR\(interp,\s*([A-Za-z_]+),\s*1\)", source,
    )
    assert try_import_calls == ["_showwarnmsg", "_warn_unawaited_coroutine"]

    show_start = source.index("static int\ncall_show_warning(")
    show_end = source.index("static PyObject *\nwarn_explicit", show_start)
    show = source[show_start:show_end]
    assert "GET_WARNINGS_ATTR(interp, _showwarnmsg, 1)" in show
    assert "if (show_fn == NULL)" in show
    assert "if (PyErr_Occurred())\n            return -1;" in show
    assert "show_warning(tstate, filename, lineno, text, category, sourceline);" in show
    assert "GET_WARNINGS_ATTR(interp, WarningMessage, 0)" in show
    assert "if (!PyCallable_Check(show_fn))" in show

    explicit_start = source.index("static PyObject *\nwarn_explicit")
    decision_start = source.index(
        "if (rc == 1)  /* Already warned for this module. */", explicit_start,
    )
    decision_end = source.index("return_none:", decision_start)
    decision = source[decision_start:decision_end]
    assert "if (rc == 0) {" in decision
    assert "if (call_show_warning(tstate," in decision
    assert "else /* if (rc == -1) */" in decision

    coro_start = source.index("void\n_PyErr_WarnUnawaitedCoroutine(")
    coro_end = source.index("static PyMethodDef warnings_functions[]", coro_start)
    coroutine = source[coro_start:coro_end]
    assert "GET_WARNINGS_ATTR(interp, _warn_unawaited_coroutine, 1)" in coroutine
    assert "if (res || PyErr_ExceptionMatches(PyExc_RuntimeWarning))" in coroutine
    assert "if (PyErr_Occurred()) {\n        PyErr_WriteUnraisable(coro);" in coroutine
    assert "if (!warned) {\n        if (_PyErr_WarnFormat(" in coroutine

    # The C warning fallback may itself be displayed through call_show_warning;
    # source evidence does not prove the Python-level edge is unreachable.
    assert "_PyErr_WarnFormat(coro, PyExc_RuntimeWarning" in coroutine


def test_warnings_is_a_core_builtin_not_a_setup_or_static_module_source() -> None:
    bootstrap = _BOOTSTRAP.read_text(encoding="utf-8").splitlines()
    stdlib = _STDLIB.read_text(encoding="utf-8").splitlines()
    assert not [line for line in bootstrap + stdlib if re.match(r"^_warnings(?:\s|$)", line)]

    tables = emit_static_python_tables()
    config = tables["Modules/config.c"].decode("utf-8")
    recipe = tables["Modules/lunar-static-sources.mk"].decode("utf-8")
    initializer = ("_warnings", "_PyWarnings_Init", "Python/_warnings.c")
    assert initializer in _CORE_INITIALIZERS
    assert config.count('{"_warnings", _PyWarnings_Init}') == 1

    core_match = re.search(r"LUNAR_CORE_BUILTIN_SOURCES := \\\n(.*?)\n\n", recipe, re.DOTALL)
    static_match = re.search(r"LUNAR_STATIC_MODULE_SOURCES := \\\n(.*?)\n\n", recipe, re.DOTALL)
    assert core_match is not None and static_match is not None
    core_sources = set(re.findall(r"[A-Za-z0-9_/]+\.c", core_match[1]))
    static_sources = set(re.findall(r"Modules/[A-Za-z0-9_/]+\.c", static_match[1]))
    assert "Python/_warnings.c" in core_sources
    assert "Python/_warnings.c" not in static_sources
    assert "Modules/_warnings.c" not in static_sources

    descriptor = json.loads(_DESCRIPTOR.read_bytes())["descriptor"]
    builtin = next(item for item in descriptor["builtin_modules"]
                   if item["name"] == "_warnings")
    assert builtin["init_symbol"] == "_PyWarnings_Init"
    assert "warnings" not in {item["name"] for item in descriptor["builtin_modules"]}
    assert "warnings" not in descriptor["initialization_profile"]["expected_startup_modules"]
    assert descriptor["production_admission"] is False
