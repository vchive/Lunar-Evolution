"""Directory traversal keeps the original inventory and validation contract."""

from __future__ import annotations

import builtins
import copy
import os
from pathlib import Path

import pytest

from lunar_evolution import producer_python_runtime as runtime


def _previous_directory_paths(root_paths, declarations, imports):
    """Independent copy of the helper before the ancestor walk optimization."""
    result = {}
    minimum_bytes = len(runtime._canonical({
        "files": [item.to_dict() for item in declarations],
        "import_roots": [item.to_dict() for item in imports],
    }))
    for label, root in root_paths.items():
        wanted: set[Path] = set()

        def add(path: Path, collected: set[Path] = wanted) -> None:
            nonlocal minimum_bytes
            if path not in collected:
                minimum_bytes += len(runtime._canonical({
                    "path": path.as_posix(), "device": 0, "inode": 1, "mode": 0,
                }))
                if minimum_bytes > runtime.MAX_PYTHON_RUNTIME_MANIFEST_BYTES:
                    runtime._fail("manifest_too_large")
                collected.add(path)

        for path in (root, *root.parents):
            add(path)
        selected = [root / item.relative_path for item in declarations if item.root_label == label]
        for path in selected:
            runtime._path(path.as_posix(), absolute=True)
        directories = [path.parent for path in selected]
        directories.extend(root / item.relative_path for item in imports if item.root_label == label)
        for path in directories:
            runtime._path(path.as_posix(), absolute=True)
            for ancestor in (path, *path.parents):
                add(ancestor)
        result[label] = tuple(sorted(wanted, key=lambda item: item.as_posix()))
    return result


def _inputs(roots, files=(), imports=()):
    declarations = []
    import_roots = []
    # Direct field assignment lets these pure helper tests include malformed
    # inputs; they must still fail at the original helper validation step.
    for label, relative_path in files:
        item = object.__new__(runtime.PythonRuntimeFileDeclaration)
        for name, value in (("root_label", label), ("relative_path", relative_path),
                            ("role", "project_resource")):
            object.__setattr__(item, name, value)
        declarations.append(item)
    for label, relative_path in imports:
        item = object.__new__(runtime.PythonRuntimeImportRoot)
        object.__setattr__(item, "root_label", label)
        object.__setattr__(item, "relative_path", relative_path)
        import_roots.append(item)
    return ({label: Path(path) for label, path in roots}, declarations, import_roots)


def _capture(monkeypatch, function, inputs, limit=None):
    events = []
    original_path = runtime._path
    original_canonical = runtime._canonical

    def path(value, **kwargs):
        events.append(("path", value, kwargs))
        return original_path(value, **kwargs)

    def canonical(value):
        events.append(("canonical", copy.deepcopy(value)))
        return original_canonical(value)

    with monkeypatch.context() as patch:
        patch.setattr(runtime, "_path", path)
        patch.setattr(runtime, "_canonical", canonical)
        if limit is not None:
            patch.setattr(runtime, "MAX_PYTHON_RUNTIME_MANIFEST_BYTES", limit)
        try:
            outcome = function(*inputs)
        except runtime.PythonRuntimeError as error:
            outcome = error.code
    return outcome, events


_CASES = [
    ("no-roots-empty", (), (), ()),
    ("root-only", (("a", "/base/root"),), (), ()),
    ("slash-root", (("a", "/"),), (("a", "one.py"),), (("a", "."),)),
    ("multiple-roots", (("a", "/base/shared/a"), ("b", "/base/shared/b")),
     (("a", "pkg/x.py"), ("b", "pkg/y.py"), ("a", "pkg/z.py")),
     (("b", "."), ("a", "pkg"), ("a", "pkg/deep"))),
    ("nested-roots", (("a", "/base"), ("b", "/base/nested")),
     (("b", "same/sub/x.py"), ("a", "nested/same/sub/y.py")), (("b", "."),)),
    ("repeated-imports", (("a", "/base/root"),),
     (("a", "pkg/a.py"), ("a", "pkg/b.py")),
     (("a", "."), ("a", "."), ("a", "pkg"), ("a", "pkg/deep"), ("a", "pkg"))),
    ("imports-without-files", (("a", "/base/root"),), (),
     (("a", "."), ("a", "lib/pkg"), ("a", "lib"))),
    ("deep-chain", (("a", "/base"),),
     (("a", "/".join(["d"] * 120) + "/a.py"),
      ("a", "/".join(["d"] * 120) + "/b.py")), (("a", "/".join(["d"] * 119)),)),
    ("unicode", (("a", "/根/星球"),),
     (("a", "共通/算法.py"), ("a", "共通/🌙.py"), ("a", "é/e\u0301.py")),
     (("a", "."), ("a", "共通"))),
    ("shared-parent-1000", (("a", "/base/common"),),
     tuple(("a", f"pkg/deep/shared/file_{index}.py") for index in range(1000)),
     (("a", "pkg"),)),
]
for _name, _relative in (
    ("dotdot", "../escape/a.py"), ("newline", "bad\nname/a.py"),
    ("backslash", "bad\\name/a.py"), ("nul", "bad\x00name/a.py"),
    ("byte-limit", "星" * 1400 + "/a.py"),
    ("part-limit", "/".join(["a"] * 129) + "/x.py"), ("surrogate", "\ud800/a.py"),
):
    _CASES.extend([
        ("reject-file-" + _name, (("a", "/base"),), (("a", _relative),), ()),
        ("reject-import-" + _name, (("a", "/base"),), (), (("a", _relative),)),
    ])


@pytest.mark.parametrize("name,roots,files,imports", _CASES, ids=[case[0] for case in _CASES])
def test_directory_paths_match_previous_results_and_validation_events(
    monkeypatch, name, roots, files, imports,
):
    inputs = _inputs(roots, files, imports)
    expected = _capture(monkeypatch, _previous_directory_paths, inputs)
    actual = _capture(monkeypatch, runtime._directory_paths, inputs)
    assert actual == expected
    outcome, _events = actual
    if name.startswith("reject-"):
        suffix = "json_invalid" if name.endswith("surrogate") else "path_invalid"
        assert outcome == "python_runtime_" + suffix
    else:
        assert isinstance(outcome, dict)


def _minimum_bytes(events):
    return sum(len(runtime._canonical(value)) for kind, value, *_ in events if kind == "canonical")


@pytest.mark.parametrize("case", [_CASES[1], _CASES[3], _CASES[8]], ids=["root", "multi", "unicode"])
@pytest.mark.parametrize("boundary", ["exact-total", "below-total", "exact-initial", "below-initial"])
def test_exact_manifest_limits_keep_original_bytes_and_canonical_order(monkeypatch, case, boundary):
    name, roots, files, imports = case
    inputs = _inputs(roots, files, imports)
    _outcome, events = _capture(monkeypatch, _previous_directory_paths, inputs)
    minimum = _minimum_bytes(events)
    initial = len(runtime._canonical(events[0][1]))
    limit = {"exact-total": minimum, "below-total": minimum - 1,
             "exact-initial": initial, "below-initial": initial - 1}[boundary]
    expected = _capture(monkeypatch, _previous_directory_paths, inputs, limit)
    actual = _capture(monkeypatch, runtime._directory_paths, inputs, limit)
    assert actual == expected
    if boundary == "exact-total":
        assert isinstance(actual[0], dict)
    else:
        assert actual[0] == "python_runtime_manifest_too_large"
    if name == "unicode":
        assert any(len(runtime._canonical(value)) > len(runtime._canonical(value).decode())
                   for kind, value, *_ in events if kind == "canonical")


def test_manifest_budget_accumulates_across_labels_including_shared_slash(monkeypatch):
    roots = (("a", "/first/shared"), ("b", "/second/shared"))
    inputs = _inputs(roots)
    _outcome, events = _capture(monkeypatch, _previous_directory_paths, inputs)
    limit = _minimum_bytes(events) - 1
    for root in roots:
        outcome, _ = _capture(monkeypatch, runtime._directory_paths, _inputs((root,)), limit)
        assert isinstance(outcome, dict)
    expected = _capture(monkeypatch, _previous_directory_paths, inputs, limit)
    actual = _capture(monkeypatch, runtime._directory_paths, inputs, limit)
    assert actual == expected
    assert actual[0] == "python_runtime_manifest_too_large"
    assert [value["path"] for kind, value, *_ in actual[1]
            if kind == "canonical" and "path" in value].count("/") == 2


def test_already_wanted_import_directory_still_runs_path_rejection(monkeypatch):
    inputs = _inputs((("a", "/base/../root"),), imports=(("a", "."),))
    expected = _capture(monkeypatch, _previous_directory_paths, inputs)
    actual = _capture(monkeypatch, runtime._directory_paths, inputs)
    assert actual == expected
    assert actual[0] == "python_runtime_path_invalid"
    assert [event for event in actual[1] if event[0] == "path"] == [
        ("path", "/base/../root", {"absolute": True}),
    ]


def test_duplicate_directories_keep_every_path_check_and_only_unique_canonical_bytes(monkeypatch):
    inputs = _inputs((("a", "/a"),), (("a", "pkg/a.py"), ("a", "pkg/b.py")),
                     (("a", "."), ("a", "pkg"), ("a", "pkg")))
    expected = _capture(monkeypatch, _previous_directory_paths, inputs)
    actual = _capture(monkeypatch, runtime._directory_paths, inputs)
    assert actual == expected
    assert [value for kind, value, *_ in actual[1] if kind == "path"] == [
        "/a/pkg/a.py", "/a/pkg/b.py", "/a/pkg", "/a/pkg", "/a", "/a/pkg", "/a/pkg",
    ]
    assert [value["path"] for kind, value, *_ in actual[1]
            if kind == "canonical" and "path" in value] == ["/a", "/", "/a/pkg"]


def test_directory_inventory_uses_no_filesystem_observation(monkeypatch):
    inputs = _inputs((("a", "/pure/根"), ("b", "/pure/根/nested")),
                     (("a", "pkg/a.py"), ("b", "lib/b.py")), (("a", "."), ("b", "lib")))
    expected = _previous_directory_paths(*inputs)

    def forbidden(*args, **kwargs):
        raise AssertionError("Directory inventory must not observe the filesystem")

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", forbidden)
        for name in ("open", "stat", "lstat", "scandir", "listdir"):
            patch.setattr(os, name, forbidden)
        for name in ("open", "stat", "lstat", "resolve", "iterdir", "glob", "rglob", "exists"):
            patch.setattr(Path, name, forbidden)
        patch.setattr(runtime, "DirectoryChain", forbidden)
        patch.setattr(runtime, "_observe_directory", forbidden)
        patch.setattr(runtime, "_observe_file", forbidden)
        actual = runtime._directory_paths(*inputs)
    assert actual == expected


def test_directory_inventory_has_no_cross_call_set_or_validation_reuse(monkeypatch):
    first = _inputs((("a", "/base"),), (("a", "old/deep/a.py"),))
    second = _inputs((("a", "/base"),), (("a", "new/deep/b.py"),))
    first_result = _capture(monkeypatch, runtime._directory_paths, first)
    second_result = _capture(monkeypatch, runtime._directory_paths, second)
    assert second_result == _capture(monkeypatch, _previous_directory_paths, second)
    assert second_result == _capture(monkeypatch, runtime._directory_paths, second)
    assert Path("/base/old") in first_result[0]["a"]
    assert Path("/base/old") not in second_result[0]["a"]


@pytest.mark.parametrize("kind,extra", [("bytes", 0), ("bytes", 1), ("parts", 0), ("parts", 1)])
def test_selected_absolute_path_exact_byte_and_part_limits(monkeypatch, kind, extra):
    if kind == "bytes":
        relative = "a" * (runtime._MAX_PATH_BYTES - len("/r/") + extra)
    else:
        relative = "/".join(["a"] * (runtime._MAX_PATH_PARTS - 2 + extra))
    inputs = _inputs((("a", "/r"),), (("a", relative),))
    expected = _capture(monkeypatch, _previous_directory_paths, inputs)
    actual = _capture(monkeypatch, runtime._directory_paths, inputs)
    assert actual == expected
    if extra:
        assert actual[0] == "python_runtime_path_invalid"
    else:
        assert isinstance(actual[0], dict)


def test_each_label_keeps_its_full_sorted_directory_inventory(monkeypatch):
    inputs = _inputs((("a", "/same/root"), ("b", "/same/root")),
                     (("a", "z/a.py"), ("a", "a/b.py"), ("b", "z/c.py")))
    actual = _capture(monkeypatch, runtime._directory_paths, inputs)
    assert actual == _capture(monkeypatch, _previous_directory_paths, inputs)
    result = {label: tuple(path.as_posix() for path in paths) for label, paths in actual[0].items()}
    assert result == {
        "a": ("/", "/same", "/same/root", "/same/root/a", "/same/root/z"),
        "b": ("/", "/same", "/same/root", "/same/root/z"),
    }


@pytest.mark.parametrize("extra", [0, -1], ids=["exact-initial", "below-initial"])
def test_empty_inventory_keeps_initial_canonical_byte_limit(monkeypatch, extra):
    limit = len(runtime._canonical({"files": [], "import_roots": []})) + extra
    expected = _capture(monkeypatch, _previous_directory_paths, _inputs(()), limit)
    actual = _capture(monkeypatch, runtime._directory_paths, _inputs(()), limit)
    assert actual == expected
    assert actual[0] == ({} if extra == 0 else "python_runtime_manifest_too_large")
