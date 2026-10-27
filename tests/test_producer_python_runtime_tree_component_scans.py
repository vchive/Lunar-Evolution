"""Canonical string computations match the retained pre-change pathlib AST."""

from __future__ import annotations

import ast
import copy
import hashlib
import itertools

import pytest
from test_producer_python_runtime_tree import fixture

from lunar_evolution import producer_python_runtime as declared
from lunar_evolution import producer_python_runtime_tree as runtime

# Exact old function AST, retained independently of the current implementation.
# Source module SHA256 before this slice:
# 1b70d8ad9b37267a9203ef3d81b2becc25c021061e7c4498987bf3ee02355d23.
_ORIGINAL = '''
def _relative(value: object, *, root: bool = False) -> str:
    _text(value, declared._MAX_PATH_BYTES)
    checked = declared._path(value, absolute=False, dot=root)
    if len(Path(checked).parts) > MAX_PYTHON_RUNTIME_TREE_DEPTH:
        _fail("depth_exceeded")
    return checked

def _name(value: object) -> str:
    checked = _relative(value)
    if len(Path(checked).parts) != 1:
        _fail("name_invalid")
    return checked

def _validate_tree_graph(
    tree: PythonRuntimeTreeManifest,
    directories: tuple[PythonRuntimeTreeDirectory, ...],
    original: declared.PythonRuntimeManifest,
) -> None:
    keys = tuple(_key(item) for item in directories)
    if keys != tuple(sorted(set(keys))):
        _fail("directories_not_canonical")
    observed = dict(zip(keys, directories, strict=True))
    roots = {root.label: root for root in original.roots}
    files = {(file.root_label, file.relative_path): file for file in original.files}
    if any(label not in roots for label, _path in keys) or set(keys) & set(files):
        _fail("graph_invalid")
    identities = [(item.device, item.inode) for item in directories] + [(file.device, file.inode) for file in original.files]
    if len(identities) != len(set(identities)):
        _fail("entry_alias")
    children = {key: set() for key in keys}
    for label, path in (*keys, *files):
        _relative(path, root=path == ".")
        if path == ".":
            continue
        parent = (label, Path(path).parent.as_posix())
        if parent not in observed:
            _fail("graph_invalid")
        children[parent].add(Path(path).name)
    for key, directory in observed.items():
        if directory.children != tuple(sorted(children[key])):
            _fail("membership_invalid")
    for label, root in roots.items():
        directory = observed.get((label, "."))
        if directory is None or (directory.device, directory.inode, directory.mode) != (root.device, root.inode, root.mode):
            _fail("root_binding_invalid")
        path = Path(root.path)
        for original_directory in root.directories:
            pinned = Path(original_directory.path)
            if pinned.is_relative_to(path):
                relative = pinned.relative_to(path).as_posix()
                found = observed.get((label, relative))
                if found is None or (found.device, found.inode, found.mode) != (
                    original_directory.device, original_directory.inode, original_directory.mode,
                ):
                    _fail("directory_binding_invalid")
    body = tree.to_dict()
    body.pop("tree_sha256")
    if _sha(tree.tree_sha256) != _digest(body):
        _fail("digest_mismatch")
'''


def _oracle():
    namespace = dict(vars(runtime))
    nodes = ast.parse(_ORIGINAL)
    assert len(nodes.body) == 3 and all(isinstance(node, ast.FunctionDef) for node in nodes.body)
    exec(compile(nodes, "<retained-pre-scan-tree-functions>", "exec"), namespace)  # noqa: S102 - fixed original AST oracle
    return namespace


def _outcome(call, *args, **kwargs):
    try:
        return "ok", call(*args, **kwargs)
    except (runtime.PythonRuntimeTreeError, declared.PythonRuntimeError) as error:
        return "refused", type(error), error.code


@pytest.mark.parametrize("depth", [-1, 0, 1, 2, 64])
def test_component_computations_match_old_ast_for_spelling_and_depth(monkeypatch, depth):
    monkeypatch.setattr(runtime, "MAX_PYTHON_RUNTIME_TREE_DEPTH", depth)
    original = _oracle()
    values = ["", ".", "..", "/", "//", "a/", "a//b", "a/../b", "./a", "a/.",
              "字/🙂", "module.py", "a\\b", "a\n", "a\r", "a\x00", "\ud800",
              "a" * 4096, "a" * 4097, "字" * 1365, "字" * 1366, None, True, 1]
    values += ["".join(chars) for size in range(5)
               for chars in itertools.product("a./", repeat=size)]
    values += ["/".join(["x"] * size) for size in (1, 2, 63, 64, 65, 127, 128, 129)]
    for value in values:
        for root in (False, True):
            assert _outcome(runtime._relative, value, root=root) == _outcome(
                original["_relative"], value, root=root,
            )
        assert _outcome(runtime._name, value) == _outcome(
            original["_name"], value,
        )


def test_exact_type_refusal_precedes_foreign_callbacks():
    callbacks = []

    class Foreign(str):
        def encode(self, *_args, **_kwargs):
            callbacks.append("encode")
            raise AssertionError("foreign encoding")

        def __str__(self):
            callbacks.append("str")
            raise AssertionError("foreign coercion")

    for namespace in (vars(runtime), _oracle()):
        for name in ("_relative", "_name"):
            result = _outcome(namespace[name], Foreign("module.py"))
            assert result == ("refused", runtime.PythonRuntimeTreeError,
                              "python_runtime_tree_text_invalid")
    assert callbacks == []


def test_original_scalar_gate_order_and_fresh_calls_remain(monkeypatch):
    events = []
    actual_text, actual_path = runtime._text, declared._path

    def text(value, maximum):
        events.append(("text", value, maximum))
        return actual_text(value, maximum)

    def path(value, **kwargs):
        events.append(("path", value, kwargs))
        return actual_path(value, **kwargs)

    monkeypatch.setattr(runtime, "_text", text)
    monkeypatch.setattr(declared, "_path", path)
    for namespace in (_oracle(), vars(runtime)):
        events.clear()
        assert namespace["_name"]("module.py") == "module.py"
        assert namespace["_name"]("module.py") == "module.py"
        assert [event[0] for event in events] == ["text", "path", "text", "path"]
        events.clear()
        result = _outcome(namespace["_relative"], "x" * 4097)
        assert result[-1] == "python_runtime_tree_text_invalid"
        assert [event[0] for event in events] == ["text"]


@pytest.fixture(scope="module")
def closed_tree(tmp_path_factory):
    return fixture(tmp_path_factory.mktemp("canonical-tree-components")).closed


@pytest.mark.parametrize("mutation,expected", [
    ("valid", "ok"), ("unicode_empty_directory", "ok"),
    ("missing_parent", "graph_invalid"), ("orphan_file", "graph_invalid"),
    ("membership", "membership_invalid"), ("root_binding", "root_binding_invalid"),
    ("alias", "entry_alias"), ("order", "directories_not_canonical"),
    ("deep_directory", "depth_exceeded"), ("invalid_file", "python_runtime_path_invalid"),
])
def test_graph_parent_name_and_membership_match_original_ast(closed_tree, mutation, expected):
    tree = copy.deepcopy(closed_tree)
    directories = list(tree.directories)
    original = tree.declared_manifest
    nested = next(item for item in directories if item.relative_path == "site/empty/nested")
    parent = next(item for item in directories
                  if (item.root_label, item.relative_path) == (nested.root_label, "site/empty"))
    if mutation == "unicode_empty_directory":
        object.__setattr__(nested, "relative_path", "site/empty/字🙂")
        object.__setattr__(parent, "children", ("字🙂",))
    elif mutation == "missing_parent":
        directories.remove(parent)
    elif mutation in {"orphan_file", "invalid_file"}:
        object.__setattr__(original.files[0], "relative_path",
                           "absent/module.py" if mutation == "orphan_file" else "a/../module.py")
    elif mutation == "membership":
        object.__setattr__(parent, "children", ())
    elif mutation == "root_binding":
        root_directory = next(item for item in directories if item.relative_path == ".")
        object.__setattr__(root_directory, "inode", max(
            item.inode for item in (*directories, *original.files)
        ) + 1)
    elif mutation == "alias":
        object.__setattr__(nested, "inode", parent.inode)
        object.__setattr__(nested, "device", parent.device)
    elif mutation == "order":
        directories.reverse()
    elif mutation == "deep_directory":
        object.__setattr__(nested, "relative_path", "/".join(["x"] * 65))
        directories.sort(key=runtime._key)
    object.__setattr__(tree, "directories", tuple(directories))
    if mutation == "unicode_empty_directory":
        body = tree.to_dict()
        body.pop("tree_sha256")
        object.__setattr__(tree, "tree_sha256", hashlib.sha256(runtime._canonical(body)).hexdigest())
    result = _outcome(lambda: runtime._validate_tree_graph(tree, tree.directories, original))
    assert result == _outcome(
        lambda: _oracle()["_validate_tree_graph"](tree, tree.directories, original),
    )
    if expected == "ok":
        assert result == ("ok", None)
    elif expected.startswith("python_runtime_"):
        assert result[-1] == expected
    else:
        assert result[-1] == "python_runtime_tree_" + expected
