"""Source-pinned candidate reachability for Feature 189 baseline startup."""

from __future__ import annotations

import hashlib
import json
from collections import deque
from pathlib import Path

from lunar_evolution.static_python_import_audit import audit_static_python_imports
from tools.static_python_fixture.profile import (
    ALIASES,
    CONFIG,
    EXPECTED_STARTUP_MODULES,
)
from tools.static_python_fixture.source_patches import (
    SOURCE_PATHS,
    prepare_static_python_sources,
)

_ROOT = Path(__file__).resolve().parents[1]
_FIXTURES = _ROOT / "tests/fixtures/static_python_source"
_GRAPH = _ROOT / "specs/189-static-python-fixture/startup-scope-graph-cpython-3.13.12-v1.json"
_ROOTS = _ROOT / "specs/189-static-python-fixture/startup-roots-cpython-3.13.12.json"
_ARCHIVE_SHA256 = "2a84cd31dd8d8ea8a8aff75de66fc1b4b0127dd5799aa50a64ae9a313885b4593"
_ROOT_SHA256 = "d1743e729bac34c5110a1d1373cc48c74a52b585034825227ed37d0178e39313"


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def test_versioned_candidate_graph_pins_source_roots_and_profile() -> None:
    graph_raw = _GRAPH.read_bytes()
    graph = json.loads(graph_raw)
    roots_raw = _ROOTS.read_bytes()
    roots = json.loads(roots_raw)

    assert graph["schema"] == "lunar-static-python-startup-scope-graph-review-v1"
    assert graph["evidence_scope"] == "pinned-source-candidate-review-only"
    assert graph["target_profile_version"] == (
        "cpython-3.13.12-linux-x86_64-musl-gil-static-startup-v1-candidate"
    )
    assert graph["target"] == {
        "cpython_version": "3.13.12",
        "source_commit": "1cbe481834751b0125e006042ffbd8cd5eaec8a8",
        "release_archive_sha256": _ARCHIVE_SHA256,
        "platform": "linux-x86_64-musl",
        "gil_enabled": True,
    }
    assert graph["profile_decision"]["status"] == (
        "retain-candidate-inventory-do-not-accept-closure"
    )
    assert graph["profile_decision"]["decision"] == (
        "no-module-inventory-expansion-from-source-observations"
    )
    assert _sha256(roots_raw) == _ROOT_SHA256
    assert graph["profile_decision"]["source_derived_roots_sha256"] == _ROOT_SHA256
    assert roots == graph["startup_roots"]
    assert roots == sorted(set(roots))
    assert set(roots) < set(EXPECTED_STARTUP_MODULES)

    expected_modules = sorted(EXPECTED_STARTUP_MODULES)
    assert graph["expected_startup_modules"] == expected_modules
    assert graph["profile_decision"]["expected_startup_modules_sha256"] == _sha256(
        json.dumps(expected_modules, sort_keys=True, separators=(",", ":")).encode()
    )
    assert graph["aliases"] == [
        {"alias": alias, "name": name}
        for name, alias in sorted(ALIASES, key=lambda pair: pair[1])
    ]
    assert graph["profile_decision"]["status"].endswith("do-not-accept-closure")
    assert all(value is False for value in graph["claims"].values())

    # All declared startup modules and alias records are reachable from the
    # source-derived roots through the retained candidate edge list.
    adjacency: dict[str, set[str]] = {}
    for edge in graph["baseline_startup_edges"]:
        adjacency.setdefault(edge["source"], set()).add(edge["target"])
        assert edge["kind"] in {
            "import", "from-import", "literal-import", "bootstrap-alias",
        }
    reached = set(roots)
    pending = deque(roots)
    while pending:
        for target in adjacency.get(pending.popleft(), ()):
            if target not in reached:
                reached.add(target)
                pending.append(target)
    alias_names = {item["alias"] for item in graph["aliases"]}
    assert reached == set(expected_modules) | alias_names

    assert graph["profile_decision"]["python_ast_import_count"] == 28
    assert graph["profile_decision"]["python_ast_unsupported_count"] == 4
    assert graph["profile_decision"]["python_ast_observation_sha256"] == (
        "d7802d7ac60202b720c30bacfb124fe8ee155298ac88ddd8facdbbc7f07dc9f5"
    )

    raw_sources = {
        path: (_FIXTURES / (path + ".source")).read_bytes()
        for path in SOURCE_PATHS
    }
    prepared, _ = prepare_static_python_sources(raw_sources)
    # Replay the v1 graph against its retained historical candidate bytes.
    # The current codec-negative source AST is reviewed separately.
    historical_main = (
        _FIXTURES / "Lunar/frozen_main-before-codec-negative.py.source"
    ).read_bytes()
    python_sources = {
        "_frozen_importlib": (_FIXTURES / "Lib/importlib/_bootstrap.py.source").read_bytes(),
        "_frozen_importlib_external": prepared["Lib/importlib/_bootstrap_external.py"],
        "abc": prepared["Lib/abc.py"],
        "codecs": (_FIXTURES / "Lib/codecs.py.source").read_bytes(),
        "encodings": prepared["Lib/encodings/__init__.py"],
        "encodings.aliases": prepared["Lib/encodings/aliases.py"],
        "encodings.utf_8": (_FIXTURES / "Lib/encodings/utf_8.py.source").read_bytes(),
        "io": (_FIXTURES / "Lib/io.py.source").read_bytes(),
        "_lunar_static_main": historical_main,
        "Python/import.c": (_FIXTURES / "Python/import.c.source").read_bytes(),
        "Python/import.c.postimage": prepared["Python/import.c"],
        "Python/pylifecycle.c": (_FIXTURES / "Python/pylifecycle.c.source").read_bytes(),
        "Python/_warnings.c": (_FIXTURES / "Python/_warnings.c.source").read_bytes(),
        "Objects/genobject.c": (_FIXTURES / "Objects/genobject.c.source").read_bytes(),
        "warnings": (_FIXTURES / "Lib/warnings.py.source").read_bytes(),
    }
    for item in graph["source_pins"]:
        source = python_sources[item["name"]]
        assert (len(source), _sha256(source)) == (item["size_bytes"], item["sha256"])
        if item["name"] == "Python/import.c":
            candidate = python_sources["Python/import.c.postimage"]
            assert (len(candidate), _sha256(candidate)) == (
                item["candidate_postimage_size_bytes"],
                item["candidate_postimage_sha256"],
            )

    ast_sources = {name: python_sources[name] for name in (
        "_frozen_importlib", "_frozen_importlib_external", "abc", "codecs",
        "encodings.aliases", "encodings.utf_8", "io", "_lunar_static_main",
    )}
    # The observer requires the explicit package-initializer source key to
    # establish package context for the relative imports in encodings.
    ast_sources["encodings.__init__"] = python_sources["encodings"]
    ast_result = audit_static_python_imports(
        ast_sources,
        expected_source_sha256={name: _sha256(raw) for name, raw in ast_sources.items()},
    )
    assert ast_result.source_count == 9
    assert ast_result.import_count == 28
    assert ast_result.unsupported_count == 4
    assert _sha256(ast_result.wire_bytes) == graph["profile_decision"][
        "python_ast_observation_sha256"
    ]

    observation = ast_result.to_dict()
    def normalize_source(name: str) -> str:
        return "encodings" if name == "encodings.__init__" else name

    observed_edges = {
        (normalize_source(item["source"]), item["target"], item["kind"])
        for item in observation["imports"]
    }
    reviewed_edges = {
        (item["source"], item["target"], item["kind"])
        for item in graph["python_source_edge_audit"]
    }
    assert len(reviewed_edges) == len(graph["python_source_edge_audit"]) == 28
    assert observed_edges == reviewed_edges

    observed_unsupported = {
        (item["source"], item["line"], item["column"], item["reason"])
        for item in observation["unsupported_import_sites"]
    }
    reviewed_unsupported = {
        (item["source"], item["line"], item["column"], item["reason"])
        for item in graph["unsupported_site_decisions"]
    }
    assert len(reviewed_unsupported) == len(graph["unsupported_site_decisions"]) == 4
    assert observed_unsupported == reviewed_unsupported
    assert observation["unresolved_imports"] == []


def test_candidate_graph_documents_literal_c_bootstrap_and_optional_edges() -> None:
    graph = json.loads(_GRAPH.read_bytes())
    bootstrap = (_FIXTURES / "Lib/importlib/_bootstrap.py.source").read_text(encoding="utf-8")
    setup_start = bootstrap.index("def _setup(sys_module, _imp_module):")
    install_start = bootstrap.index("\ndef _install(sys_module, _imp_module):", setup_start)
    setup = bootstrap[setup_start:install_start]
    assert "for builtin_name in ('_thread', '_warnings', '_weakref'):" in setup
    assert "builtin_module = _builtin_from_name(builtin_name)" in setup

    warnings_c = (_FIXTURES / "Python/_warnings.c.source").read_text(encoding="utf-8")
    warning_start = warnings_c.index("get_warnings_attr(PyInterpreterState *interp")
    warning_end = warnings_c.index("static PyObject *\nget_once_registry", warning_start)
    warning_getter = warnings_c[warning_start:warning_end]
    assert "if (try_import && !_Py_IsInterpreterFinalizing(interp))" in warning_getter
    assert "PyImport_Import(&_Py_ID(warnings))" in warning_getter
    assert "PyErr_ExceptionMatches(PyExc_ImportError)" in warning_getter
    assert "PyErr_Clear();" in warning_getter
    assert CONFIG["warnoptions"] == []
    assert CONFIG["site_import"] == 0
    assert graph["profile_decision"]["status"] == (
        "retain-candidate-inventory-do-not-accept-closure"
    )
    open_routes = {item["route"]: item for item in graph["reachability_decisions"]}
    assert "optional C import" in open_routes["warnings"]["decision"]
    assert "not proven unreachable or refused" in open_routes[
        "tokenize, importlib.readers, importlib.metadata"
    ]["limit"]
    assert "has no optional-import disposition" in open_routes["warnings"]["limit"]

    assert all(value is False for value in graph["claims"].values())
    assert "operator" not in graph["expected_startup_modules"]
    assert "warnings" not in graph["expected_startup_modules"]
    assert "site" not in graph["expected_startup_modules"]
