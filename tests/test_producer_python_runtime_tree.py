"""Closed layouts are observed using inert blobs, never a runnable Python producer."""

from __future__ import annotations

import builtins
import hashlib
import json
import os
import shutil
import socket
import stat
import subprocess
from collections.abc import Sequence
from dataclasses import FrozenInstanceError, replace

import pytest
from test_producer_python_runtime import _build, _inventory, _path, _tree, _verify

from lunar_evolution import producer_python_runtime as declared
from lunar_evolution import producer_python_runtime_tree as runtime


def fixture(tmp_path, *, layout="portable-tree"):
    tree = _tree(tmp_path, layout=layout)
    (tree.roots["deps"] / "site" / "empty" / "nested").mkdir(parents=True)
    tree.original = _build(tree)
    tree.closed = build(tree)
    return tree


def build(tree, **changes):
    return runtime.build_python_runtime_tree_manifest(**{
        "declared_manifest": tree.original, "expected_manifest_sha256": tree.original.manifest_sha256,
        "expected_target": tree.target, **changes,
    })


def verify(tree, **changes):
    return runtime.verify_python_runtime_tree_manifest(tree.closed, **{
        "expected_tree_sha256": tree.closed.tree_sha256,
        "expected_manifest_sha256": tree.original.manifest_sha256, "expected_target": tree.target, **changes,
    })


def resign(value):
    value.pop("tree_sha256", None)
    value["tree_sha256"] = hashlib.sha256(runtime._canonical(value)).hexdigest()
    return runtime._canonical(value)


def refused(call):
    with pytest.raises(runtime.PythonRuntimeTreeError) as error:
        call()
    assert str(error.value).startswith("python_runtime_tree_")
    return error.value


@pytest.mark.parametrize("layout", ["portable-tree", "venv-tree"])
def test_build_parse_verify_pin_exact_empty_membership_and_files(tmp_path, layout):
    tree = fixture(tmp_path, layout=layout)
    closed = tree.closed
    assert runtime.parse_python_runtime_tree_manifest(closed.to_json()) == closed
    assert runtime.parse_python_runtime_tree_manifest(closed.to_json().decode()) == closed
    assert closed.declared_manifest == tree.original
    observation = verify(tree)
    assert observation.file_count == len(tree.original.files)
    assert observation.directory_count == len(closed.directories)
    assert observation.entry_count == observation.file_count + observation.directory_count
    assert observation.total_bytes == sum(item.size for item in tree.original.files)
    assert any(item.relative_path == "site/empty/nested" and item.children == () for item in closed.directories)
    for value in (observation.to_dict(), closed.to_dict()):
        assert value["scope"] == "closed-filesystem-layout"
        for field in runtime._CAPABILITIES:
            assert value[field] is False
    assert tree.original.to_dict()["scope"] == "declared-files-only"


def test_frozen_dtos_and_detached_wire_cannot_change_original_pins(tmp_path):
    tree = fixture(tmp_path)
    raw = tree.closed.to_json()
    with pytest.raises(FrozenInstanceError):
        tree.closed.tree_sha256 = "0" * 64
    with pytest.raises(FrozenInstanceError):
        tree.closed.directories[0].children = ()
    wire = tree.closed.to_dict()
    wire["directories"][0]["children"].append("forged")
    wire["declared_manifest"]["files"][0]["sha256"] = "0" * 64
    assert tree.closed.to_json() == raw
    object.__setattr__(tree.closed.directories[0], "mode", True)
    refused(lambda: verify(tree))


class ForbiddenSequence(Sequence):
    def __len__(self):
        raise AssertionError("untrusted collection length callback")

    def __getitem__(self, index):
        raise AssertionError("untrusted collection indexing callback")

    def __iter__(self):
        raise AssertionError("untrusted collection iteration callback")


@pytest.mark.parametrize("field", ["tree-directories", "children", "roots", "files", "import_roots", "root-directories"])
def test_mutated_collection_is_refused_before_callbacks_or_serialization(tmp_path, monkeypatch, field):
    tree = fixture(tmp_path)
    tree.original = tree.closed.declared_manifest
    subject, attribute = {
        "tree-directories": (tree.closed, "directories"),
        "children": (tree.closed.directories[0], "children"),
        "roots": (tree.original, "roots"),
        "files": (tree.original, "files"),
        "import_roots": (tree.original, "import_roots"),
        "root-directories": (tree.original.roots[0], "directories"),
    }[field]
    object.__setattr__(subject, attribute, ForbiddenSequence())

    def no_serialization(*_args, **_kwargs):
        pytest.fail("invalid DTO must be rejected before serialization")

    monkeypatch.setattr(runtime.PythonRuntimeTreeManifest, "to_dict", no_serialization)
    monkeypatch.setattr(declared.PythonRuntimeManifest, "to_dict", no_serialization)
    refused(lambda: verify(tree))
    if field not in {"tree-directories", "children"}:
        refused(lambda: build(tree))


@pytest.mark.parametrize("field", ["tree-directories", "children", "combined-entries", "roots", "files", "import_roots", "root-directories"])
def test_oversized_mutated_immutable_tuple_refuses_before_serialization(tmp_path, monkeypatch, field):
    tree = fixture(tmp_path)
    tree.original = tree.closed.declared_manifest
    if field == "combined-entries":
        monkeypatch.setattr(runtime, "MAX_PYTHON_RUNTIME_TREE_ENTRIES", len(tree.closed.directories) + len(tree.original.files) - 1)
    else:
        subject, attribute, maximum = {
            "tree-directories": (tree.closed, "directories", runtime.MAX_PYTHON_RUNTIME_TREE_ENTRIES),
            "children": (next(item for item in tree.closed.directories if item.children), "children", runtime.MAX_PYTHON_RUNTIME_TREE_ENTRIES),
            "roots": (tree.original, "roots", declared.MAX_PYTHON_RUNTIME_ROOTS),
            "files": (tree.original, "files", declared.MAX_PYTHON_RUNTIME_FILES),
            "import_roots": (tree.original, "import_roots", declared._MAX_IMPORT_ROOTS),
            "root-directories": (tree.original.roots[0], "directories", runtime.MAX_PYTHON_RUNTIME_TREE_ENTRIES + declared._MAX_PATH_PARTS),
        }[field]
        collection = getattr(subject, attribute)
        object.__setattr__(subject, attribute, (collection[0],) * (maximum + 1))

    def no_serialization(*_args, **_kwargs):
        pytest.fail("oversized DTO must be rejected before serialization")

    monkeypatch.setattr(runtime.PythonRuntimeTreeManifest, "to_dict", no_serialization)
    monkeypatch.setattr(declared.PythonRuntimeManifest, "to_dict", no_serialization)
    refused(lambda: verify(tree))
    if field not in {"tree-directories", "children", "combined-entries"}:
        refused(lambda: build(tree))


@pytest.mark.parametrize("field", ["directory-path", "directory-item", "file-path", "import-path", "target", "entrypoint", "root-item", "file-item", "import-item"])
def test_mutated_declared_nested_schema_refuses_before_serialization(tmp_path, monkeypatch, field):
    tree = fixture(tmp_path)
    tree.original = tree.closed.declared_manifest
    if field == "directory-path":
        object.__setattr__(tree.original.roots[0].directories[0], "path", ForbiddenSequence())
    elif field == "directory-item":
        object.__setattr__(tree.original.roots[0], "directories", (ForbiddenSequence(),))
    elif field == "file-path":
        object.__setattr__(tree.original.files[0], "relative_path", ForbiddenSequence())
    elif field == "import-path":
        object.__setattr__(tree.original.import_roots[0], "relative_path", ForbiddenSequence())
    elif field in {"target", "entrypoint"}:
        object.__setattr__(tree.original, field, ForbiddenSequence())
    else:
        attribute = {"root-item": "roots", "file-item": "files", "import-item": "import_roots"}[field]
        object.__setattr__(tree.original, attribute, (ForbiddenSequence(),))

    monkeypatch.setattr(declared.PythonRuntimeManifest, "to_dict", lambda *_a: pytest.fail("nested schema serialized"))
    refused(lambda: verify(tree))
    refused(lambda: build(tree))


def test_mutated_aggregate_ancestor_pin_bound_refuses_before_root_validation_or_serialization(tmp_path, monkeypatch):
    tree = fixture(tmp_path)
    tree.original = tree.closed.declared_manifest
    maximum = runtime.MAX_PYTHON_RUNTIME_TREE_ENTRIES + declared.MAX_PYTHON_RUNTIME_ROOTS * declared._MAX_PATH_PARTS
    count = maximum // len(tree.original.roots) + 1
    for root in tree.original.roots:
        object.__setattr__(root, "directories", (root.directories[0],) * count)

    def forbidden(*_args, **_kwargs):
        pytest.fail("oversized ancestor pins must fail before semantic validation or serialization")

    monkeypatch.setattr(declared.PythonRuntimeRoot, "__post_init__", forbidden)
    monkeypatch.setattr(declared.PythonRuntimeManifest, "to_dict", forbidden)
    refused(lambda: verify(tree))
    refused(lambda: build(tree))


@pytest.mark.parametrize("field", ["file", "import"])
def test_mutated_declared_depth_refuses_before_serialization(tmp_path, monkeypatch, field):
    tree = fixture(tmp_path)
    tree.original = tree.closed.declared_manifest
    subject = tree.original.files[0] if field == "file" else tree.original.import_roots[0]
    object.__setattr__(subject, "relative_path", "/".join(["nested"] * (runtime.MAX_PYTHON_RUNTIME_TREE_DEPTH + 1)))
    monkeypatch.setattr(declared.PythonRuntimeManifest, "to_dict", lambda *_a: pytest.fail("deep DTO serialized"))
    refused(lambda: verify(tree))
    refused(lambda: build(tree))


@pytest.mark.parametrize("kind", ["declared", "tree", "target"])
def test_external_pin_drift_refuses_before_tree_observation(tmp_path, monkeypatch, kind):
    tree = fixture(tmp_path)
    options = {
        "declared": {"expected_manifest_sha256": "0" * 64},
        "tree": {"expected_tree_sha256": "0" * 64},
        "target": {"expected_target": replace(tree.target, architecture="aarch64")},
    }[kind]
    monkeypatch.setattr(runtime, "_observe_snapshot", lambda *_a, **_k: pytest.fail("pin drift read"))
    refused(lambda: verify(tree, **options))
    if kind != "tree":
        refused(lambda: build(tree, **options))


@pytest.mark.parametrize("name", ["unlisted.py", "unlisted.pyc", "unlisted.pth", "sitecustomize.py", "usercustomize.py", "unlisted-native.so", "resource.json"])
def test_v1_accepts_unlisted_files_but_closed_tree_build_and_verify_refuse(tmp_path, name):
    tree = fixture(tmp_path)
    path = tree.roots["deps"] / "site" / name
    path.write_bytes(b"inert unknown member")
    assert _verify(tree.original).file_count == len(tree.declarations)
    before = _inventory(tree.base)
    refused(lambda: build(tree))
    refused(lambda: verify(tree))
    assert _inventory(tree.base) == before


@pytest.mark.parametrize("kind", ["add-empty", "remove-empty", "replace-empty", "change-empty-mode", "touch-empty"])
def test_empty_directory_changes_refuse_without_implicit_readmission(tmp_path, kind):
    tree = fixture(tmp_path)
    path = tree.roots["deps"] / "site" / "empty" / "nested"
    original_mode = stat.S_IMODE(path.stat().st_mode)
    try:
        if kind == "add-empty":
            (path / "new").mkdir()
        elif kind == "remove-empty":
            path.rmdir()
        elif kind == "replace-empty":
            path.rename(path.with_name("removed"))
            path.mkdir()
            path.with_name("removed").rmdir()
        elif kind == "change-empty-mode":
            path.chmod(0o500)
        else:
            info = path.stat()
            os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 1))
        assert _verify(tree.original).file_count == len(tree.declarations)
        before = _inventory(tree.base)
        refused(lambda: verify(tree))
        assert _inventory(tree.base) == before
    finally:
        if path.exists():
            path.chmod(original_mode)


@pytest.mark.parametrize("role", ["interpreter", "loader", "shared_library", "stdlib", "stdlib_archive", "extension", "site_package", "project_source", "project_resource", "dependency_lock"])
def test_each_declared_role_byte_drift_refuses(tmp_path, role):
    tree = fixture(tmp_path)
    path = _path(tree, role)
    path.write_bytes(path.read_bytes() + b"drift")
    before = _inventory(tree.base)
    refused(lambda: verify(tree))
    assert _inventory(tree.base) == before


@pytest.mark.parametrize("kind", ["file-inode", "root-inode", "parent-inode", "root-mode", "file-mode"])
def test_source_and_ancestor_identity_or_permission_drift_refuses(tmp_path, kind):
    tree = fixture(tmp_path)
    path = _path(tree, "project_source") if kind.startswith("file") else tree.roots["project"]
    prior = stat.S_IMODE(path.stat().st_mode)
    try:
        if kind == "file-inode":
            replacement = path.with_name("replacement")
            replacement.write_bytes(path.read_bytes())
            replacement.chmod(prior)
            replacement.replace(path)
        elif kind in {"root-inode", "parent-inode"}:
            path = path if kind == "root-inode" else path.parent
            renamed = path.with_name(path.name + "-retained")
            path.rename(renamed)
            shutil.copytree(renamed, path)
        else:
            path.chmod(0o500)
        before = _inventory(tree.base)
        refused(lambda: verify(tree))
        assert _inventory(tree.base) == before
    finally:
        if path.exists() and kind in {"root-mode", "file-mode"}:
            path.chmod(prior)


@pytest.mark.parametrize("kind", ["symlink-file", "symlink-dir", "hardlink", "fifo", "socket"])
def test_unsafe_entries_refuse_without_opening_unknown_special_objects(tmp_path, monkeypatch, kind):
    tree = fixture(tmp_path)
    path = tree.roots["deps"] / "site" / "unsafe"
    stream = None
    if kind == "symlink-file":
        path.symlink_to(_path(tree, "project_source"))
    elif kind == "symlink-dir":
        path.symlink_to(tree.roots["project"], target_is_directory=True)
    elif kind == "hardlink":
        os.link(_path(tree, "project_source"), path)
    elif kind == "fifo":
        os.mkfifo(path)
    else:
        stream = socket.socket(socket.AF_UNIX)
        # Unix socket sockaddr paths are much shorter than filesystem paths on Darwin.
        with monkeypatch.context() as patch:
            patch.chdir(path.parent)
            stream.bind(path.name)
    opened = os.open

    def guarded(name, *args, **kwargs):
        if isinstance(name, str) and name == "unsafe":
            pytest.fail("unknown/special entry must not be opened")
        return opened(name, *args, **kwargs)

    monkeypatch.setattr(runtime.os, "open", guarded)
    try:
        refused(lambda: build(tree))
        refused(lambda: verify(tree))
    finally:
        if stream is not None:
            stream.close()


@pytest.mark.parametrize("mutation", [
    "extra", "schema", "protocol", "scope", "execution", "protection", "archive", "loader", "digest",
    "directory-extra", "directory-bool", "directory-path", "directory-root", "directory-order", "directory-duplicate",
    "directory-alias", "missing-root", "missing-parent", "children-extra", "children-missing", "children-duplicate",
    "children-order", "children-path", "declared-manifest", "root-binding", "root-mode", "file-as-directory",
])
def test_rehashed_wire_cannot_relax_schema_graph_capabilities_or_original_bindings(tmp_path, mutation):
    tree = fixture(tmp_path)
    wire = tree.closed.to_dict()
    directory = next(item for item in wire["directories"] if item["relative_path"] == "." and item["root_label"] == "runtime")
    nested = next(item for item in wire["directories"] if item["relative_path"] == "site/empty/nested")
    if mutation == "extra":
        wire["runtime_grant"] = True
    elif mutation in {"schema", "protocol", "scope", "execution", "protection", "archive", "loader"}:
        key, value = {
            "schema": ("schema_version", 1), "protocol": ("protocol", "other"), "scope": ("scope", "sealed-runtime"),
            "execution": ("execution_performed", True), "protection": ("runtime_load_protection", True),
            "archive": ("archive_contents_complete", True), "loader": ("loader_dependencies_complete", True),
        }[mutation]
        wire[key] = value
    elif mutation == "digest":
        wire["tree_sha256"] = "0" * 64
    elif mutation == "directory-extra":
        directory["seal"] = True
    elif mutation == "directory-bool":
        directory["mtime_ns"] = True
    elif mutation == "directory-path":
        nested["relative_path"] = "../escape"
    elif mutation == "directory-root":
        nested["root_label"] = "unknown"
    elif mutation == "directory-order":
        wire["directories"].reverse()
    elif mutation == "directory-duplicate":
        wire["directories"].append(dict(nested))
    elif mutation == "directory-alias":
        nested["device"], nested["inode"] = directory["device"], directory["inode"]
    elif mutation == "missing-root":
        wire["directories"].remove(directory)
    elif mutation == "missing-parent":
        nested["relative_path"] = "absent/nested"
    elif mutation.startswith("children-"):
        if mutation == "children-extra":
            directory["children"].append("unknown")
        elif mutation == "children-missing":
            directory["children"].pop()
        elif mutation == "children-duplicate":
            directory["children"].append(directory["children"][0])
        elif mutation == "children-order":
            directory["children"].reverse()
        else:
            directory["children"] = ["../escape"]
    elif mutation == "declared-manifest":
        wire["declared_manifest"]["manifest_sha256"] = "0" * 64
    elif mutation == "root-binding":
        directory["inode"] += 1
    elif mutation == "root-mode":
        directory["mode"] ^= 0o200
    else:
        nested["root_label"], nested["relative_path"] = "project", "src/main.py"
        wire["directories"].sort(key=lambda item: (item["root_label"], item["relative_path"]))
    raw = runtime._canonical(wire) if mutation == "digest" else resign(wire)
    refused(lambda: runtime.parse_python_runtime_tree_manifest(raw))


@pytest.mark.parametrize("kind", ["duplicate", "noncanonical", "nan", "invalid-utf8", "oversize", "partial", "object"])
def test_invalid_json_is_bounded_and_refused(tmp_path, kind):
    tree = fixture(tmp_path)
    raw = tree.closed.to_json()
    if kind == "duplicate":
        raw = raw.replace(b'"scope":"closed-filesystem-layout"', b'"scope":"closed-filesystem-layout","scope":"closed-filesystem-layout"')
    elif kind == "noncanonical":
        raw = json.dumps(tree.closed.to_dict(), indent=2)
    elif kind == "nan":
        raw = raw.replace(b'"scope":"closed-filesystem-layout"', b'"scope":NaN')
    elif kind == "invalid-utf8":
        raw = b"\xff"
    elif kind == "oversize":
        raw = b"x" * (runtime.MAX_PYTHON_RUNTIME_TREE_MANIFEST_BYTES + 1)
    elif kind == "partial":
        raw = raw[:-1]
    else:
        raw = tree.closed.to_dict()
    refused(lambda: runtime.parse_python_runtime_tree_manifest(raw))


@pytest.mark.parametrize("kind", ["entries", "depth", "file-bytes", "total-bytes", "json-bytes"])
def test_build_and_verifier_refuse_independent_work_bounds(tmp_path, monkeypatch, kind):
    tree = fixture(tmp_path)
    if kind == "entries":
        monkeypatch.setattr(runtime, "MAX_PYTHON_RUNTIME_TREE_ENTRIES", len(tree.original.files) + len(tree.closed.directories) - 1)
    elif kind == "depth":
        monkeypatch.setattr(runtime, "MAX_PYTHON_RUNTIME_TREE_DEPTH", 2)
    elif kind == "file-bytes":
        monkeypatch.setattr(declared, "MAX_PYTHON_RUNTIME_FILE_BYTES", 1)
    elif kind == "total-bytes":
        monkeypatch.setattr(declared, "MAX_PYTHON_RUNTIME_TOTAL_BYTES", 1)
    else:
        monkeypatch.setattr(runtime, "MAX_PYTHON_RUNTIME_TREE_MANIFEST_BYTES", 100)
    refused(lambda: build(tree))
    refused(lambda: verify(tree))


def test_earlier_membership_mutation_during_later_file_read_is_closed(tmp_path, monkeypatch):
    tree = fixture(tmp_path)
    read, changed = runtime._read_file, []

    def drift(*args, **kwargs):
        result = read(*args, **kwargs)
        if kwargs["read_bytes"] and not changed and args[2].role == "interpreter":
            changed.append(True)
            (tree.roots["deps"] / "site" / "empty" / "late").mkdir()
        return result

    monkeypatch.setattr(runtime, "_read_file", drift)
    refused(lambda: build(tree))
    assert changed == [True]


def test_final_v1_reads_cannot_leave_new_membership_unchecked(tmp_path, monkeypatch):
    tree = fixture(tmp_path)
    pins, calls = runtime._pins, []

    def drift(*args, **kwargs):
        result = pins(*args, **kwargs)
        calls.append(True)
        if len(calls) == 2:
            (tree.roots["deps"] / "site" / "empty" / "late").mkdir()
        return result

    monkeypatch.setattr(runtime, "_pins", drift)
    assert refused(lambda: build(tree)).code.endswith("tree_changed")
    assert calls == [True, True]


def test_second_snapshot_directory_drift_refuses(tmp_path, monkeypatch):
    tree = fixture(tmp_path)
    observe, calls = runtime._observe_snapshot, []

    def drift(*args, **kwargs):
        result = observe(*args, **kwargs)
        calls.append(True)
        if len(calls) == 1:
            (tree.roots["deps"] / "site" / "empty" / "late").mkdir()
        return result

    monkeypatch.setattr(runtime, "_observe_snapshot", drift)
    assert refused(lambda: build(tree)).code.endswith("tree_changed")


@pytest.mark.parametrize("boundary", ["read", "scan"])
@pytest.mark.parametrize("error", [OSError, KeyboardInterrupt, SystemExit])
def test_all_owned_descriptors_close_on_refusal_or_interrupt(tmp_path, monkeypatch, boundary, error):
    tree = fixture(tmp_path)
    opened, closed, read, scan = os.open, os.close, os.read, os.scandir
    active, in_tree = set(), [False]
    read_file = runtime._read_file

    def tracking_open(*args, **kwargs):
        descriptor = opened(*args, **kwargs)
        active.add(descriptor)
        return descriptor

    def tracking_close(descriptor):
        active.discard(descriptor)
        return closed(descriptor)

    def target_read(*args, **kwargs):
        if boundary == "read" and in_tree[0]:
            raise error("inert interruption")
        return read(*args, **kwargs)

    def target_scan(*args, **kwargs):
        if boundary == "scan":
            raise error("inert interruption")
        return scan(*args, **kwargs)

    def mark_read(*args, **kwargs):
        in_tree[0] = True
        return read_file(*args, **kwargs)

    monkeypatch.setattr(runtime.os, "open", tracking_open)
    monkeypatch.setattr(runtime.os, "close", tracking_close)
    monkeypatch.setattr(runtime.os, "read", target_read)
    monkeypatch.setattr(runtime.os, "scandir", target_scan)
    monkeypatch.setattr(runtime, "_read_file", mark_read)
    with pytest.raises(runtime.PythonRuntimeTreeError if error is OSError else error):
        build(tree)
    assert active == set()


def test_parse_is_effect_free_and_checks_are_read_only_no_launch_import_or_grants(tmp_path, monkeypatch):
    tree = fixture(tmp_path)
    raw, before = tree.closed.to_json(), _inventory(tree.base)

    def forbidden(*args, **kwargs):
        pytest.fail("filesystem preflight must not import, execute, write, or change permissions")

    with monkeypatch.context() as effects:
        for name in ("write", "mkdir", "chmod", "fchmod", "rename", "replace", "unlink"):
            effects.setattr(runtime.os, name, forbidden)
        effects.setattr(subprocess, "Popen", forbidden)
        effects.setattr(subprocess, "run", forbidden)
        effects.setattr(builtins, "__import__", forbidden)
        assert build(tree) == tree.closed
        assert verify(tree).tree_sha256 == tree.closed.tree_sha256
    # monkeypatch itself imports inspect while registering a patch; set the import gate last.
    with monkeypatch.context() as effects:
        for name in ("write", "mkdir", "chmod", "fchmod", "rename", "replace", "unlink",
                     "open", "stat", "fstat", "scandir"):
            effects.setattr(runtime.os, name, forbidden)
        effects.setattr(subprocess, "Popen", forbidden)
        effects.setattr(subprocess, "run", forbidden)
        effects.setattr(builtins, "__import__", forbidden)
        assert runtime.parse_python_runtime_tree_manifest(raw) == tree.closed
    assert _inventory(tree.base) == before
