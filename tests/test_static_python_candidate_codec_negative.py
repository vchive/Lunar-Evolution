"""Synthetic checks of repository-owned codec workload functions, never a target run."""

from __future__ import annotations

import ast
import codecs
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from lunar_evolution.static_python_import_audit import audit_static_python_imports
from tools.static_python_fixture.recipe import emit_build_plan
from tools.static_python_fixture.source_patches import SOURCE_PATHS, prepare_static_python_sources

_ROOT = Path(__file__).resolve().parents[1]
_ASSET = _ROOT / "tools/static_python_fixture/assets/frozen_main.py"
_NAMES = ("utf-8", "cp65001", "u8", "utf", "utf8", "utf8_ucs2", "utf8_ucs4")
_UNKNOWN = "lunar_only_unavailable_codec"
_UTF8 = codecs.lookup("utf-8")


def _helper(lookup=None):
    calls = []

    def finite_lookup(name):
        calls.append(name)
        if lookup is not None:
            return lookup(name)
        if name in _NAMES:
            return _UTF8
        raise LookupError("synthetic finite codec miss")

    fake_sys = SimpleNamespace(
        modules={"sys": object(), "codecs": SimpleNamespace(lookup=finite_lookup)},
        path=[], path_hooks=[],
    )
    tree = ast.parse(_ASSET.read_text(encoding="utf-8"))
    function = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == "_codec_negative")
    namespace = {"sys": fake_sys}
    # Only this repository-owned function runs against a finite synthetic map.
    # No CPython archive member, frozen target, loader or broker is executed.
    exec(compile(ast.Module(body=[function], type_ignores=[]),  # noqa: S102
                 "<synthetic-candidate-codec-check>", "exec"), namespace)
    return namespace["_codec_negative"], fake_sys, calls


def test_fixed_codec_workload_checks_all_aliases_and_preserves_synthetic_profile():
    helper, fake_sys, calls = _helper()
    modules = fake_sys.modules.copy()
    path = fake_sys.path.copy()
    hooks = fake_sys.path_hooks.copy()
    assert helper() is None
    assert calls == [*_NAMES, _UNKNOWN]
    assert fake_sys.modules == modules
    assert fake_sys.path == path
    assert fake_sys.path_hooks == hooks


@pytest.mark.parametrize("changed_alias", _NAMES)
def test_each_supported_alias_must_identify_utf8(changed_alias):
    def lookup(name):
        return SimpleNamespace(name="latin-1") if name == changed_alias else _UTF8

    helper, _fake_sys, calls = _helper(lookup)
    with pytest.raises(RuntimeError, match="^fixed UTF-8 codec profile mismatch$"):
        helper()
    assert calls == list(_NAMES[:_NAMES.index(changed_alias) + 1])


@pytest.mark.parametrize("field,result", [
    ("encode", (b"wrong", 7)), ("encode", (b"Lunar \xe6\x9c\x88", 6)),
    ("decode", ("wrong", 9)), ("decode", ("Lunar \u6708", 8)),
])
def test_fixed_utf8_roundtrip_requires_exact_bytes_text_and_consumed_counts(field, result):
    codec = SimpleNamespace(name="utf-8", encode=_UTF8.encode, decode=_UTF8.decode)
    setattr(codec, field, lambda *_args: result)
    helper, _fake_sys, calls = _helper(lambda _name: codec)
    with pytest.raises(RuntimeError, match="^fixed UTF-8 codec profile mismatch$"):
        helper()
    assert calls == ["utf-8"]


def test_fixed_unknown_codec_must_raise_lookup_error():
    helper, _fake_sys, calls = _helper(lambda _name: _UTF8)
    with pytest.raises(RuntimeError, match="^unsupported codec was admitted$"):
        helper()
    assert calls == [*_NAMES, _UNKNOWN]


def test_unknown_codec_preserves_an_unexpected_first_error():
    first = ImportError("synthetic unexpected codec import")

    def lookup(name):
        if name == _UNKNOWN:
            raise first
        return _UTF8

    helper, _fake_sys, _calls = _helper(lookup)
    with pytest.raises(ImportError) as caught:
        helper()
    assert caught.value is first


@pytest.mark.parametrize("change", ["module-add", "module-remove", "module-replace",
                                     "path-add", "hooks-add"])
def test_codec_lookup_cannot_report_success_after_synthetic_profile_drift(change):
    def lookup(name):
        if name != _UNKNOWN:
            return _UTF8
        if change == "module-add":
            fake_sys.modules["unreviewed_codec"] = object()
        elif change == "module-remove":
            del fake_sys.modules["sys"]
        elif change == "module-replace":
            fake_sys.modules["sys"] = object()
        elif change == "path-add":
            fake_sys.path.append("/unreviewed")
        else:
            fake_sys.path_hooks.append(object())
        raise LookupError("synthetic finite codec miss")

    helper, fake_sys, calls = _helper(lookup)
    with pytest.raises(RuntimeError, match="^codec lookup changed startup profile$"):
        helper()
    assert calls == [*_NAMES, _UNKNOWN]


def test_helper_has_no_import_or_dynamic_module_selection():
    tree = ast.parse(_ASSET.read_text(encoding="utf-8"))
    helper = next(node for node in tree.body
                  if isinstance(node, ast.FunctionDef) and node.name == "_codec_negative")
    assert not any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in ast.walk(helper))
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                   and node.func.id in {"__import__", "eval", "exec", "open"}
                   for node in ast.walk(helper))
    assert [node.slice.value for node in ast.walk(helper)
            if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Attribute)
            and isinstance(node.value.value, ast.Name) and node.value.value.id == "sys"
            and node.value.attr == "modules" and isinstance(node.slice, ast.Constant)] == ["codecs"]


def test_existing_loader_negative_routes_to_codec_check_before_any_loader():
    tree = ast.parse(_ASSET.read_text(encoding="utf-8"))
    loader = next(node for node in tree.body
                  if isinstance(node, ast.FunctionDef) and node.name == "_loader_negative")
    first = loader.body[0]
    assert isinstance(first, ast.Expr) and isinstance(first.value, ast.Call)
    assert isinstance(first.value.func, ast.Name) and first.value.func.id == "_codec_negative"
    assert first.value.args == [] and first.value.keywords == []
    main = next(node for node in tree.body
                if isinstance(node, ast.FunctionDef) and node.name == "_main")
    assert not any(isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                   and node.func.id == "_codec_negative" for node in ast.walk(main))


def test_historical_codec_candidate_replays_its_pinned_bounded_ast_observation(tmp_path):
    fixtures = _ROOT / "tests/fixtures/static_python_source"
    prepared, _ = prepare_static_python_sources({
        path: (fixtures / (path + ".source")).read_bytes() for path in SOURCE_PATHS
    })
    plan = emit_build_plan(tmp_path / "plan")
    main = (plan / "assets/frozen_main.py").read_bytes()
    assert (len(main), hashlib.sha256(main).hexdigest()) == (
        7900, "8f93ce3c74a2fac6d04d9f18da714101801b8d37931a99d0aa395eb3c24c82e5",
    )
    sources = {
        "_frozen_importlib": (fixtures / "Lib/importlib/_bootstrap.py.source").read_bytes(),
        "_frozen_importlib_external": (
            fixtures / "Lunar/bootstrap_external-before-deferred-refusal.py.source"
        ).read_bytes(),
        "abc": prepared["Lib/abc.py"],
        "codecs": (fixtures / "Lib/codecs.py.source").read_bytes(),
        "encodings.__init__": prepared["Lib/encodings/__init__.py"],
        "encodings.aliases": prepared["Lib/encodings/aliases.py"],
        "encodings.utf_8": (fixtures / "Lib/encodings/utf_8.py.source").read_bytes(),
        "io": (fixtures / "Lib/io.py.source").read_bytes(),
        "_lunar_static_main": main,
    }
    old_graph = json.loads((
        _ROOT / "specs/189-static-python-fixture/startup-scope-graph-cpython-3.13.12-v1.json"
    ).read_bytes())
    pins = {item["name"]: item["sha256"] for item in old_graph["source_pins"]}
    pins["encodings.__init__"] = pins.pop("encodings")
    pins["_lunar_static_main"] = "8f93ce3c74a2fac6d04d9f18da714101801b8d37931a99d0aa395eb3c24c82e5"
    result = audit_static_python_imports(
        sources, expected_source_sha256={name: pins[name] for name in sources},
    )
    retained = (
        _ROOT / "specs/189-static-python-fixture/candidate-codec-negative-source-imports.json"
    ).read_bytes()
    assert result.wire_bytes == retained
    assert (len(retained), hashlib.sha256(retained).hexdigest()) == (
        3636, "bbec89a8aec4c354c3f8556ef0be07b2725b668489e23531855cb75ae9868497",
    )
    assert (result.source_count, result.import_count, result.unresolved_count,
            result.unsupported_count) == (9, 28, 0, 4)
    wire = result.to_dict()
    assert {
        ("encodings" if item["source"] == "encodings.__init__" else item["source"],
         item["target"], item["kind"])
        for item in wire["imports"]
    } == {
        (item["source"], item["target"], item["kind"])
        for item in old_graph["python_source_edge_audit"]
    }
    assert [
        (item["source"], item["line"], item["column"], item["reason"])
        for item in wire["unsupported_import_sites"]
    ] == [
        ("_frozen_importlib", 1176, 8, "dynamic-code-execution"),
        ("_frozen_importlib_external", 1323, 15, "dynamic-code-execution"),
        ("_lunar_static_main", 94, 47, "dynamic-import"),
        ("codecs", 16, 4, "star-import"),
    ]
    assert all(value is False for value in wire["claims"].values())
