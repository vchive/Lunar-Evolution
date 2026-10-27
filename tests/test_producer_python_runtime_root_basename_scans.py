"""Pure root/basename computations match the actual frozen 4e1847dd function ASTs.

The ordinary POSIX Path backend is part of this contract. Arbitrarily replacing
that backend and its extra constructor/equality/parents callbacks is outside the
existing lexical-path SDD; real input Mapping/str/pathlike callbacks remain covered.
"""

from __future__ import annotations

import ast
import hashlib
from collections.abc import Mapping
from pathlib import Path

import pytest

from lunar_evolution import producer_python_runtime as runtime

# Extracted with git show 4e1847dda1bb0a1fc3d37037b23b6be2863a61fb:
# src/lunar_evolution/producer_python_runtime.py, 35,258 bytes, SHA256
# 3c3f6039da6c8ab4c5548ca6796555377efb6632aacc24bb19cb739b7ffe2f6e.
# The source segments below are the original function ASTs, not rewritten oracles.
_ORIGINAL_ROOT = '''def _root_paths(value: object) -> dict[str, Path]:
    if not isinstance(value, Mapping) or not 1 <= len(value) <= MAX_PYTHON_RUNTIME_ROOTS:
        _fail("roots_invalid")
    result = {}
    for index, (label, raw) in enumerate(value.items()):
        if index >= MAX_PYTHON_RUNTIME_ROOTS:
            _fail("roots_invalid")
        _label(label)
        if not isinstance(raw, (str, Path)):
            _fail("path_invalid")
        path = Path(_path(str(raw), absolute=True))
        if label in result:
            _fail("root_duplicate")
        result[label] = path
    values = list(result.values())
    for index, path in enumerate(values):
        for other in values[index + 1:]:
            if path == other or path in other.parents or other in path.parents:
                _fail("roots_overlap")
    return dict(sorted(result.items()))'''

_ORIGINAL_DECLARATION = '''def __post_init__(self) -> None:
        _label(self.root_label)
        _path(self.relative_path, absolute=False)
        if type(self.role) is not str or self.role not in _ROLE_SLOTS:
            _fail("role_invalid")
        basename = Path(self.relative_path).name.casefold()
        if basename.endswith(".pth") or basename in {"sitecustomize.py", "usercustomize.py"}:
            _fail("listed_import_hook")'''


def _oracles():
    namespace = dict(vars(runtime))
    for text in (_ORIGINAL_ROOT, _ORIGINAL_DECLARATION):
        tree = ast.parse(text)
        assert len(tree.body) == 1 and isinstance(tree.body[0], ast.FunctionDef)
        exec(compile(tree, "<frozen-4e1847dd-runtime-function>", "exec"), namespace)  # noqa: S102 - fixed original function AST
    return namespace


def _outcome(call, *args):
    try:
        value = call(*args)
        if type(value) is dict:
            value = tuple((label, type(path), path.as_posix()) for label, path in value.items())
        return "ok", value
    except (runtime.PythonRuntimeError, TypeError, RuntimeError) as error:
        return "error", type(error), getattr(error, "code", None), error.args


def _declaration(label="root", path="safe.py", role="project_source"):
    value = object.__new__(runtime.PythonRuntimeFileDeclaration)
    for name, field in (("root_label", label), ("relative_path", path), ("role", role)):
        object.__setattr__(value, name, field)
    return value


def test_retained_oracles_are_exact_pinned_source_segments():
    assert hashlib.sha256(_ORIGINAL_ROOT.encode()).hexdigest() == (
        "3be03fb23e5e7489a8b73d1c0696d93b7dc6c06437de9f78cd5df14d10eee56f")
    assert hashlib.sha256(_ORIGINAL_DECLARATION.encode()).hexdigest() == (
        "31fee42bfcfdcf3b4bc9b2cef23c9a89bda6fe249483bab0f8cd3191804557e6")


@pytest.mark.parametrize("paths,overlap", [
    (("/a",), False), (("/",), False), (("/a", "/a"), True),
    (("/a", "/a/b"), True), (("/a/b", "/a"), True),
    (("/a", "/ab"), False), (("/a/b", "/a/bc"), False),
    (("/a/first", "/a/second"), False), (("/", "/a"), True),
    (("/a", "/"), True), (("/字", "/字/🙂"), True),
    (("/字", "/字🙂"), False), (("/é", "/e\u0301"), False),
    (("/Root", "/root"), False), (("/root/.hidden", "/root/..name"), False),
    (("/a/b", "/other", "/a"), True),
])
def test_root_relationships_match_original_pathlib_ast(paths, overlap):
    roots = {f"root{index}": path for index, path in enumerate(paths)}
    actual = _outcome(runtime._root_paths, roots)
    assert actual == _outcome(_oracles()["_root_paths"], roots)
    if overlap:
        assert actual[2] == "python_runtime_roots_overlap"
    else:
        assert actual[0] == "ok"


@pytest.mark.parametrize("count", [0, 1, 15, 16, 17])
def test_root_cardinality_preserves_original_limit(count):
    roots = {f"root{index}": f"/independent-{index}" for index in range(count)}
    actual = _outcome(runtime._root_paths, roots)
    assert actual == _outcome(_oracles()["_root_paths"], roots)
    assert (actual[0] == "ok") is (1 <= count <= 16)


@pytest.mark.parametrize("roots,code", [
    ({"bad label": "/a"}, "root_label_invalid"),
    ({"good": "relative"}, "path_invalid"), ({"good": "/a/"}, "path_invalid"),
    ({"good": "/a/./b"}, "path_invalid"), ({"good": "/a/../b"}, "path_invalid"),
    ({"good": "//a"}, "path_invalid"), ({"good": "/a//b"}, "path_invalid"),
    ({"good": "/\ud800"}, "path_invalid"), ({"good": None}, "path_invalid"),
    ({"good": b"/a"}, "path_invalid"), ({"good": "/" + "a" * 4096}, "path_invalid"),
    ({"good": "/" + "/".join(["a"] * 128)}, "path_invalid"),
])
def test_root_refusals_keep_original_order_and_codes(roots, code):
    actual = _outcome(runtime._root_paths, roots)
    assert actual == _outcome(_oracles()["_root_paths"], roots)
    assert actual[2] == "python_runtime_" + code


def test_accepted_roots_return_sorted_original_path_values_without_reusing_raw_inputs():
    roots = {"z": Path("/z"), "a": Path("/a")}
    for call in (runtime._root_paths, _oracles()["_root_paths"]):
        result = call(roots)
        assert list(result) == ["a", "z"]
        assert all(type(path) is type(Path()) for path in result.values())
        assert all(result[label] == raw and result[label] is not raw for label, raw in roots.items())


@pytest.mark.parametrize("mode", [
    "normal", "overlap", "invalid_label", "invalid_raw", "noncanonical_raw", "duplicate",
    "len_zero", "len_over", "extra_items", "items_raises", "iter_raises", "index_raises",
    "str_raises", "shrink_limit",
])
def test_mapping_length_items_index_and_raw_string_callbacks_keep_original_sequence(monkeypatch, mode):
    def observe(original):
        with monkeypatch.context() as patch:
            events = []
            patch.setattr(runtime, "MAX_PYTHON_RUNTIME_ROOTS", 16)
            label_gate, path_gate = runtime._label, runtime._path

            def label(value):
                events.append(("label", value))
                return label_gate(value)

            def path(value, **kwargs):
                events.append(("path", value))
                return path_gate(value, **kwargs)

            patch.setattr(runtime, "_label", label)
            patch.setattr(runtime, "_path", path)

            class Raw(str):
                def __str__(self):
                    text = str.__str__(self)
                    events.append(("str", text))
                    if mode == "str_raises":
                        raise RuntimeError("raw string refusal")
                    if mode == "shrink_limit":
                        # The oracle uses copied globals; mutate the executing function's limit.
                        call.__globals__["MAX_PYTHON_RUNTIME_ROOTS"] = 1
                    return text

            rows = [("first", Raw("/first")), ("second", Raw("/second"))]
            if mode == "overlap":
                rows[1] = ("second", Raw("/first/child"))
            elif mode == "invalid_label":
                rows[0] = ("bad label", Raw("/first"))
            elif mode == "invalid_raw":
                rows[0] = ("first", object())
            elif mode == "noncanonical_raw":
                rows[0] = ("first", Raw("/first/"))
            elif mode == "duplicate":
                rows[1] = ("first", Raw("/second"))
            elif mode == "extra_items":
                rows = [(f"root{index}", Raw(f"/independent-{index}")) for index in range(17)]

            class Input(Mapping):
                def __len__(self):
                    events.append("len")
                    return 0 if mode == "len_zero" else 17 if mode == "len_over" else min(len(rows), 16)

                def items(self):
                    events.append("items")
                    if mode == "items_raises":
                        raise RuntimeError("items refusal")
                    if mode == "duplicate":
                        return iter(rows)
                    return super().items()

                def __iter__(self):
                    events.append("iter")
                    if mode == "iter_raises":
                        raise RuntimeError("iterator refusal")
                    return iter(label for label, _raw in rows)

                def __getitem__(self, key):
                    events.append(("index", key))
                    if mode == "index_raises":
                        raise RuntimeError("index refusal")
                    return next(raw for label, raw in rows if label == key)

            call = _oracles()["_root_paths"] if original else runtime._root_paths
            outcome = _outcome(call, Input())
            return outcome, list(events)

    outcomes = [observe(original) for original in (True, False)]
    assert outcomes[0] == outcomes[1]
    if mode == "normal":
        assert outcomes[0][1] == ["len", "items", "iter", ("index", "first"),
                                  ("label", "first"), ("str", "/first"), ("path", "/first"),
                                  ("index", "second"), ("label", "second"),
                                  ("str", "/second"), ("path", "/second")]
    elif mode in {"len_zero", "len_over"}:
        assert outcomes[0][1] == ["len"]
    elif mode == "extra_items":
        assert outcomes[0][0][2] == "python_runtime_roots_invalid"
        assert outcomes[0][1][-1] == ("index", "root16")
    elif mode == "duplicate":
        assert outcomes[0][0][2] == "python_runtime_root_duplicate"
        assert outcomes[0][1][-1] == ("path", "/second")


@pytest.mark.parametrize("value,code", [
    ("module.py", None), ("pkg/字🙂.py", None), ("pkg/e\u0301.py", None),
    ("pkg/THING.PTH", "listed_import_hook"), (".pth", "listed_import_hook"),
    ("pkg/SITECUSTOMIZE.PY", "listed_import_hook"),
    ("USERCUSTOMIZE.PY", "listed_import_hook"), ("pkg/ſitecustomize.py", "listed_import_hook"),
    ("pkg/module.pth.backup", None), ("pkg/sitecustomize.py.backup", None),
    ("pkg/．pth", None), ("pkg/SİTEcustomize.py", None),
    ("pkg/", "path_invalid"), ("pkg/.", "path_invalid"), (".", "path_invalid"),
])
def test_file_declaration_casefold_and_path_refusals_match_actual_old_ast(value, code):
    actual = _outcome(runtime.PythonRuntimeFileDeclaration.__post_init__, _declaration(path=value))
    assert actual == _outcome(_oracles()["__post_init__"], _declaration(path=value))
    if code is None:
        assert actual == ("ok", None)
    else:
        assert actual[2] == "python_runtime_" + code


@pytest.mark.parametrize("change", [
    "canonical", "hook", "interior_dot", "trailing_slash", "trailing_dot", "dot",
    "parent", "double_slash", "unicode", "path", "pathlike", "pathlike_hook",
    "foreign_string", "bytes", "none", "false_role", "raising_role",
])
def test_basename_reads_fresh_path_after_role_callback_and_preserves_path_fallback(monkeypatch, change):
    def observe(original):
        with monkeypatch.context() as patch:
            events = []
            value = _declaration()

            class Pathlike:
                def __fspath__(self):
                    events.append("fspath")
                    return "pkg/SITECUSTOMIZE.PY" if change == "pathlike_hook" else "pkg/module.py"

            class ForeignString(str):
                def rpartition(self, *_args):
                    events.append("foreign-rpartition")
                    raise AssertionError("foreign string used as exact text")

            replacement = {
                "canonical": "pkg/module.py", "hook": "pkg/HOOK.PTH",
                "interior_dot": "pkg/./sitecustomize.py", "trailing_slash": "pkg/USERCUSTOMIZE.PY/",
                "trailing_dot": "pkg/sitecustomize.py/.", "dot": ".", "parent": "../module.py",
                "double_slash": "pkg//module.py", "unicode": "pkg/字🙂.py",
                "path": Path("pkg/SITECUSTOMIZE.PY"), "pathlike": Pathlike(),
                "pathlike_hook": Pathlike(), "foreign_string": ForeignString("pkg/module.py"),
                "bytes": b"pkg/module.py", "none": None,
                "false_role": Pathlike(), "raising_role": Pathlike(),
            }[change]

            class Roles:
                def __contains__(self, role):
                    events.append(("role", role))
                    object.__setattr__(value, "relative_path", replacement)
                    if change == "raising_role":
                        raise RuntimeError("role callback refusal")
                    return change != "false_role"

            patch.setattr(runtime, "_ROLE_SLOTS", Roles())
            call = _oracles()["__post_init__"] if original else (
                runtime.PythonRuntimeFileDeclaration.__post_init__)
            return _outcome(call, value), list(events)

    outcomes = [observe(original) for original in (True, False)]
    assert outcomes[0] == outcomes[1]
    assert outcomes[0][1][0] == ("role", "project_source")
    if change in {"pathlike", "pathlike_hook"}:
        assert outcomes[0][1] == [("role", "project_source"), "fspath"]
    if change in {"false_role", "raising_role"}:
        assert outcomes[0][1] == [("role", "project_source")]
    if change in {"hook", "interior_dot", "trailing_slash", "trailing_dot", "path", "pathlike_hook"}:
        assert outcomes[0][0][2] == "python_runtime_listed_import_hook"
    elif change in {"canonical", "dot", "parent", "double_slash", "unicode", "pathlike", "foreign_string"}:
        assert outcomes[0][0] == ("ok", None)


@pytest.mark.parametrize("label,path,role,code,contains", [
    ("bad label", "../bad", "invalid", "root_label_invalid", False),
    ("root", "../bad", "invalid", "path_invalid", False),
    ("root", "hook.pth", "invalid", "role_invalid", True),
    ("root", "hook.pth", None, "role_invalid", False),
])
def test_declaration_rejection_order_still_precedes_basename(monkeypatch, label, path, role, code, contains):
    def observe(original):
        events = []

        class Roles:
            def __contains__(self, value):
                events.append(value)
                return False

        with monkeypatch.context() as patch:
            patch.setattr(runtime, "_ROLE_SLOTS", Roles())
            call = _oracles()["__post_init__"] if original else (
                runtime.PythonRuntimeFileDeclaration.__post_init__)
            return _outcome(call, _declaration(label, path, role)), list(events)

    outcomes = [observe(original) for original in (True, False)]
    assert outcomes[0] == outcomes[1]
    assert outcomes[0][0][2] == "python_runtime_" + code
    assert bool(outcomes[0][1]) is contains
