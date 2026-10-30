"""Absolute ancestry scans preserve the frozen original pathlib graph contract."""

from __future__ import annotations

import ast
import copy
import hashlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_producer_python_runtime_tree import fixture
from test_producer_python_runtime_tree_component_scans import _ORIGINAL, _oracle

from lunar_evolution import producer_python_runtime_tree as runtime


def _outcome(call, *args):
    try:
        return "ok", call(*args)
    except (runtime.PythonRuntimeTreeError, TypeError, RuntimeError) as error:
        return "error", type(error), getattr(error, "code", None), error.args


def _graph(root_path, pin_paths):
    root = SimpleNamespace(label="root", path=root_path, device=1, inode=1, mode=0o755)
    root.directories = tuple(SimpleNamespace(path=path, device=1, inode=1, mode=0o755)
                             for path in pin_paths)
    observed = SimpleNamespace(root_label="root", relative_path=".",
                               device=1, inode=1, mode=0o755, children=())
    original = SimpleNamespace(roots=(root,), files=())
    digest = runtime._digest({})
    tree = SimpleNamespace(tree_sha256=digest, to_dict=lambda: {"tree_sha256": digest})
    return tree, (observed,), original


def test_retained_original_ancestry_loop_matches_actual_historical_ast():
    graph = next(node for node in ast.parse(_ORIGINAL).body
                 if isinstance(node, ast.FunctionDef) and node.name == "_validate_tree_graph")
    loop = next(node for node in graph.body if isinstance(node, ast.For)
                and isinstance(node.target, ast.Tuple)
                and [part.id for part in node.target.elts] == ["label", "root"])
    # Exact loop independently present in historical 1e6, PR189 2486 and
    # pre-change 869198bc. The previous component scan left it unchanged.
    # Python 3.13 omits empty lists by default; pin the complete AST on every
    # supported interpreter, including its empty args/keywords/orelse fields.
    dumped = ast.dump(loop, show_empty=True) if sys.version_info >= (3, 13) else ast.dump(loop)
    assert hashlib.sha256(dumped.encode()).hexdigest() == (
        "54b721b763e926e500e7f42235588ea3d6f7f9c75237981c04f0b8ceb97f5f29")


@pytest.mark.parametrize("root,pin,accepted", [
    ("/", "/", True), ("/", "/a", False), ("/a", "/a", True),
    ("/a", "/a/b", False), ("/a", "/ab", True), ("/a/b", "/a/bc", True),
    ("/a", "/", True), ("/Root", "/root", True),
    ("/字", "/字/🙂", False), ("/字", "/字🙂", True),
    ("/é", "/e\u0301", True), ("/a", "/a/.hidden", False),
    ("/a", "/a/..name", False), ("/a", "/a\\b", True),
    ("a", "a", True), ("a", "a/b", False), (".", ".", True),
    (".", "a", False), ("//a", "//a", True), ("//a", "/a", True),
    ("/a", "//a", True), ("/a", "/a/../b", False),
    ("/a/..", "/a/..", True), ("/a/..", "/b", True),
    ("/a//b/", "/a/b", True), ("///a", "/a", True),
])
def test_ordinary_and_fallback_ancestry_matches_original_ast(root, pin, accepted):
    arguments = _graph(root, (pin,))
    actual = _outcome(runtime._validate_tree_graph, *arguments)
    assert actual == _outcome(_oracle()["_validate_tree_graph"], *arguments)
    if accepted:
        assert actual == ("ok", None)
    else:
        assert actual[2] == "python_runtime_tree_directory_binding_invalid"


def test_noncanonical_and_unusual_post_callback_paths_keep_pathlib_semantics():
    paths = ["", ".", "..", "a", "a/b", "a/../b", "/", "//", "///",
             "/a", "/a/", "/a/./b", "/a//b", "/a/../b", "/a/..",
             "//a", "//a/b", "/ab", "/字/🙂", "/a\x00/b", "/a\\b"]
    paths += [Path(value) for value in paths]
    call = _oracle()["_validate_tree_graph"]
    for root in paths:
        for pin in paths:
            arguments = _graph(root, (pin,))
            assert _outcome(runtime._validate_tree_graph, *arguments) == _outcome(call, *arguments)


@pytest.mark.parametrize("mutation", ["none", "root_path", "pin_identity", "pin_error", "root_binding"])
def test_pathlike_callbacks_gate_order_and_fresh_pin_fields_remain(mutation):
    def observe(call):
        events = []
        tree, observed, original = _graph("/a", ("/a", "/a"))
        root = original.roots[0]

        class RootPath:
            def __fspath__(self):
                events.append("root_path")
                return "/a"

        class PinPath:
            def __init__(self, index):
                self.index = index

            def __fspath__(self):
                events.append(("pin_path", self.index))
                if mutation == "root_path":
                    # The original local Path has already been constructed.
                    root.path = "/changed-after-root-construction"
                elif mutation == "pin_identity" and self.index == 0:
                    root.directories[0].inode = 99
                elif mutation == "pin_error" and self.index == 0:
                    raise RuntimeError("fixed synthetic callback")
                return "/a"

        root.path = RootPath()
        for index, pin in enumerate(root.directories):
            pin.path = PinPath(index)
        if mutation == "root_binding":
            root.inode = 99
        return _outcome(call, tree, observed, original), events

    old, new = [observe(call) for call in (_oracle()["_validate_tree_graph"], runtime._validate_tree_graph)]
    assert old == new
    if mutation == "root_binding":
        assert new[0][2] == "python_runtime_tree_root_binding_invalid"
        assert new[1] == []
    elif mutation in {"pin_identity", "pin_error"}:
        assert new[1] == ["root_path", ("pin_path", 0)]
    else:
        assert new == (("ok", None), ["root_path", ("pin_path", 0), ("pin_path", 1)])


@pytest.mark.parametrize("mutation", ["valid", "ancestor_pin", "descendant_identity", "digest"])
def test_real_closed_tree_keeps_bindings_and_digest_refusals(tmp_path, mutation):
    tree = copy.deepcopy(fixture(tmp_path).closed)
    original = tree.declared_manifest
    if mutation == "ancestor_pin":
        root = original.roots[0]
        # A pin outside the selected root never becomes an observed tree member.
        object.__setattr__(root.directories[0], "path", "/not-a-selected-runtime-root")
    elif mutation == "descendant_identity":
        root = original.roots[0]
        pin = next(pin for pin in root.directories if pin.path == root.path)
        object.__setattr__(pin, "inode", pin.inode + 100000)
    elif mutation == "digest":
        object.__setattr__(tree, "tree_sha256", "0" * 64)
    if mutation == "ancestor_pin":
        body = tree.to_dict()
        body.pop("tree_sha256")
        object.__setattr__(tree, "tree_sha256", runtime._digest(body))
    arguments = tree, tree.directories, original
    actual = _outcome(runtime._validate_tree_graph, *arguments)
    assert actual == _outcome(_oracle()["_validate_tree_graph"], *arguments)
    if mutation in {"valid", "ancestor_pin"}:
        assert actual == ("ok", None)
    elif mutation == "descendant_identity":
        assert actual[2] == "python_runtime_tree_directory_binding_invalid"
    else:
        assert actual[2] == "python_runtime_tree_digest_mismatch"
