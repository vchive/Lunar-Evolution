"""Pinned source transitions and bounded audits, never archived module execution."""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import pytest

from lunar_evolution.static_python_import_audit import audit_static_python_imports
from tools.static_python_fixture.recipe import emit_build_plan
from tools.static_python_fixture.source_patches import SOURCE_PATHS, prepare_static_python_sources
from tools.static_python_rsi_fixture.installation_profile import prepare_rsi_installation_profile
from tools.static_python_rsi_fixture.recipe import emit_rsi_launch_source_plan

_ROOT = Path(__file__).resolve().parents[1]
_FIXTURES = _ROOT / "tests/fixtures/static_python_source"
_SPEC = _ROOT / "specs/189-static-python-fixture"
_EXTERNAL = "Lib/importlib/_bootstrap_external.py"
_OLD_PIN = (64722, "2928843477aef234477ac1968447370798e933c6dad39b9e5131e581b8c84eab")
_NEW_PIN = (63208, "3269c01134c03bf8196306ce6aa89e24da41430ccf3bef7eb43afe362ec1bf1e")
_OPERATIONS = (
    "FileLoader.get_resource_reader", "NamespaceLoader.get_resource_reader",
    "PathFinder.invalidate_caches", "PathFinder.find_distributions", "decode_source",
)


def _pin(raw):
    return len(raw), hashlib.sha256(raw).hexdigest()


@pytest.fixture
def candidate():
    raw = {name: (_FIXTURES / (name + ".source")).read_bytes() for name in SOURCE_PATHS}
    prepared, manifest = prepare_static_python_sources(raw)
    return raw, prepared, manifest


def _history():
    return (_FIXTURES / "Lunar/bootstrap_external-before-deferred-refusal.py.source").read_bytes()


def _node(raw, owner, name):
    tree = ast.parse(raw)
    body = tree.body if owner is None else next(
        node.body for node in tree.body if isinstance(node, ast.ClassDef) and node.name == owner
    )
    return next(node for node in body if isinstance(node, ast.FunctionDef) and node.name == name)


def test_exact_source_identity_transition_preserves_historical_prepared_bytes(candidate):
    raw, prepared, manifest = candidate
    assert _pin(raw[_EXTERNAL]) == (
        73219, "a97a03ea9f9d38d90c8a50942183382ff5a479e7c4c5163c2ac5bae3561444ae",
    )
    assert _pin(_history()) == _OLD_PIN
    assert _pin(prepared[_EXTERNAL]) == _NEW_PIN
    assert manifest["patch_set_sha256"] == (
        "8ccdc0541b2e0c6e9c2bf251d9dd502d51bdaf27543ceaccccf59df41e10348e"
    )
    assert sum(len(item["operations"]) for item in manifest["files"]) == 18
    external = next(item for item in manifest["files"] if item["path"] == _EXTERNAL)
    assert [operation["label"] for operation in external["operations"][-5:]] == list(_OPERATIONS)
    assert all(operation["required_occurrences"] == 1 for operation in external["operations"])
    assert all(manifest[key] is False for key in (
        "source_execution_performed", "build_performed", "execution_performed",
        "runtime_load_protection", "production_admission", "general_code_origin_protection",
    ))


@pytest.mark.parametrize("owner,name,target", [
    ("FileLoader", "get_resource_reader", "importlib.readers"),
    ("NamespaceLoader", "get_resource_reader", "importlib.readers"),
    ("PathFinder", "invalidate_caches", "importlib.metadata"),
    ("PathFinder", "find_distributions", "importlib.metadata"),
    (None, "decode_source", "tokenize"),
])
def test_each_retained_historical_route_is_replaced_as_a_complete_function(candidate, owner, name,
                                                                         target):
    # Compare ASTs only: historical reader/cache/decoder code is never executed.
    historical = _node(_history(), owner, name)
    original_imports = {
        node.module if isinstance(node, ast.ImportFrom) else alias.name
        for node in ast.walk(historical) if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert target in original_imports
    actual = _node(candidate[1][_EXTERNAL], owner, name)
    expected = ast.parse("raise ImportError('lunar_static_external_loader_refused')").body
    assert [ast.dump(node) for node in actual.body] == [ast.dump(node) for node in expected]
    assert ast.dump(actual.args) == ast.dump(historical.args)
    decorators = ["staticmethod"] if owner == "PathFinder" else []
    assert [node.id for node in actual.decorator_list] == decorators


def test_source_loader_preliminary_file_reads_remain_an_explicit_open_route(candidate):
    method = _node(candidate[1][_EXTERNAL], "SourceLoader", "get_source")
    calls = [
        (node.lineno, node.col_offset, node.func.attr if isinstance(node.func, ast.Attribute)
         else node.func.id)
        for node in ast.walk(method) if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Attribute, ast.Name))
    ]
    ordered = [name for _line, _column, name in sorted(calls)]
    assert ordered.index("get_filename") < ordered.index("get_data") < ordered.index("decode_source")
    assert ast.dump(method) == ast.dump(_node(_history(), "SourceLoader", "get_source"))


def test_current_nine_sources_have_separate_25_edge_observation_with_open_sites(candidate, tmp_path):
    prepared = candidate[1]
    plan = emit_build_plan(tmp_path / "base-plan")
    sources = {
        "_frozen_importlib": (_FIXTURES / "Lib/importlib/_bootstrap.py.source").read_bytes(),
        "_frozen_importlib_external": prepared[_EXTERNAL],
        "abc": prepared["Lib/abc.py"],
        "codecs": (_FIXTURES / "Lib/codecs.py.source").read_bytes(),
        "encodings.__init__": prepared["Lib/encodings/__init__.py"],
        "encodings.aliases": prepared["Lib/encodings/aliases.py"],
        "encodings.utf_8": (_FIXTURES / "Lib/encodings/utf_8.py.source").read_bytes(),
        "io": (_FIXTURES / "Lib/io.py.source").read_bytes(),
        "_lunar_static_main": (plan / "assets/frozen_main.py").read_bytes(),
    }
    observation = audit_static_python_imports(
        sources, expected_source_sha256={name: _pin(raw)[1] for name, raw in sources.items()},
    )
    retained = (_SPEC / "candidate-deferred-import-refusal-source-imports.json").read_bytes()
    assert observation.wire_bytes == retained
    assert _pin(retained) == (
        3379, "50bd394683a86dc0e0421d1e9ab592d153650456c54a23606e166db0c625e7ff",
    )
    assert (observation.source_count, observation.import_count, observation.unresolved_count,
            observation.unsupported_count) == (9, 25, 0, 4)
    wire = observation.to_dict()
    historical = json.loads((_SPEC / "candidate-codec-negative-source-imports.json").read_bytes())
    def edge(item):
        return item["source"], item["target"], item["kind"]

    assert set(map(edge, historical["imports"])) - set(map(edge, wire["imports"])) == {
        ("_frozen_importlib_external", "importlib.readers", "from-import"),
        ("_frozen_importlib_external", "importlib.metadata", "from-import"),
        ("_frozen_importlib_external", "tokenize", "import"),
    }
    assert not set(map(edge, wire["imports"])) - set(map(edge, historical["imports"]))
    assert wire["unsupported_import_sites"] == [
        {"source": "_frozen_importlib", "line": 1176, "column": 8,
         "reason": "dynamic-code-execution"},
        {"source": "_frozen_importlib_external", "line": 1313, "column": 15,
         "reason": "dynamic-code-execution"},
        {"source": "_lunar_static_main", "line": 94, "column": 47, "reason": "dynamic-import"},
        {"source": "codecs", "line": 16, "column": 4, "reason": "star-import"},
    ]
    descriptor = json.loads((_SPEC / "wire-v1-example.json").read_bytes())["descriptor"]
    declared = {item["name"] for section in ("builtin_modules", "frozen_modules")
                for item in descriptor[section]}
    assert {item["target"] for item in wire["imports"]} - declared == {"nt", "winreg"}
    assert all(value is False for value in wire["claims"].values())


def test_active_base_rsi_and_preparation_pin_chain_commits_to_new_external(candidate, tmp_path):
    base = (_ROOT / "tools/static_python_fixture/reviewed-build-inputs.json").read_bytes()
    overlay = (_ROOT / "tools/static_python_rsi_fixture/reviewed-profile-overlay.json").read_bytes()
    manifest = emit_rsi_launch_source_plan(tmp_path / "rsi-plan")
    plan = manifest.read_bytes()
    assert _pin(base) == (
        80050, "7d1660a9166208c412626fcd8f60cb60124060595643064b353926381565171d",
    )
    assert _pin(plan) == (
        6706, "6018846ffcfdaf1d578516043e690cdd01da413d5b885d16d18d537219d79058",
    )
    assert _pin(overlay) == (
        2456, "831d9e4625f5e9f6d7b662505bbd811d9ce23b6804a7e9c4172ddbafb77888e6",
    )
    policy = json.loads(base)["source_preparation"]
    assert set(policy) == {"files", "patch_set_sha256"}
    assert policy["patch_set_sha256"] == candidate[2]["patch_set_sha256"]
    assert policy["files"] == [{
        key: record[key] for key in (
            "path", "before_size", "before_sha256", "after_size", "after_sha256",
        )
    } for record in candidate[2]["files"]]
    result = prepare_rsi_installation_profile(
        reviewed_build_inputs=base, reviewed_overlay=overlay, source_plan=plan,
        expected_source_plan_sha256=_pin(plan)[1],
        source_assets={path.name: path.read_bytes() for path in (manifest.parent / "assets").iterdir()},
    )
    assert _pin(result.wire_bytes) == (
        73802, "cb82e14008c30b3f95c7769f52b7a4005f46d897d93397fc2ae4320fab30a62d",
    )
    wire = json.loads(result.wire_bytes)
    frozen = wire["candidate_build_inputs"]["freeze_tasks"]
    external = next(task for task in frozen if task["name"] == "_frozen_importlib_external")
    assert (external["source_size"], external["source_sha256"]) == _NEW_PIN
    assert len(frozen) == 9
    assert all(value is False for value in wire["claims"].values())
