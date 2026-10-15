"""Detached tree parsing preserves exact refusals and public DTO drift gates."""

from __future__ import annotations

import json
import socket
import subprocess
from pathlib import Path

import pytest
from test_producer_python_runtime_tree import build, fixture, resign, verify

from lunar_evolution import producer_python_runtime as declared
from lunar_evolution import producer_python_runtime_tree as runtime


@pytest.mark.parametrize("text", [False, True], ids=["bytes", "text"])
def test_detached_tree_roundtrip_remains_pure_and_publicly_revalidatable(tmp_path, monkeypatch, text):
    tree = fixture(tmp_path)
    raw = tree.closed.to_json()

    def forbidden(*_args, **_kwargs):
        pytest.fail("detached tree parser must not access files, processes or network")

    with monkeypatch.context() as patch:
        for method in ("open", "read_bytes", "write_bytes", "stat", "lstat", "mkdir"):
            patch.setattr(Path, method, forbidden)
        patch.setattr(subprocess, "Popen", forbidden)
        patch.setattr(subprocess, "run", forbidden)
        patch.setattr(socket, "create_connection", forbidden)
        patch.setattr(socket.socket, "connect", forbidden)
        patch.setattr(runtime, "verify_python_runtime_tree_manifest", forbidden)
        parsed = runtime.parse_python_runtime_tree_manifest(raw.decode() if text else raw)
        assert parsed == tree.closed
        assert parsed.to_json() == raw
        assert parsed.to_dict() == json.loads(raw)
        assert type(parsed) is runtime.PythonRuntimeTreeManifest
        assert type(parsed.declared_manifest) is declared.PythonRuntimeManifest
        assert type(parsed.directories) is tuple
        assert runtime.PythonRuntimeTreeManifest(
            parsed.declared_manifest, parsed.directories, parsed.tree_sha256,
        ) == parsed
    tree.closed = parsed
    assert verify(tree).tree_sha256 == parsed.tree_sha256


@pytest.mark.parametrize("text", [False, True], ids=["bytes", "text"])
@pytest.mark.parametrize("mutation,code", [
    ("whitespace", "schema_invalid"),
    ("duplicate", "duplicate_json_key"),
    ("capability", "schema_invalid"),
    ("digest", "digest_mismatch"),
    ("directory_bool", "stat_invalid"),
    ("directory_order", "directories_not_canonical"),
    ("children_duplicate", "membership_invalid"),
    ("root_binding", "root_binding_invalid"),
    ("declared_digest", "json_invalid"),
])
def test_detached_tree_keeps_exact_fixed_wire_refusals(tmp_path, text, mutation, code):
    tree = fixture(tmp_path)
    raw = tree.closed.to_json()
    wire = json.loads(raw)
    directory = next(item for item in wire["directories"]
                     if item["root_label"] == "runtime" and item["relative_path"] == ".")
    if mutation == "whitespace":
        raw = b" " + raw
    elif mutation == "duplicate":
        raw = raw[:-1] + b',"scope":"closed-filesystem-layout"}'
    elif mutation == "digest":
        wire["tree_sha256"] = "0" * 64
        raw = runtime._canonical(wire)
    else:
        if mutation == "capability":
            wire["execution_performed"] = True
        elif mutation == "directory_bool":
            directory["mtime_ns"] = True
        elif mutation == "directory_order":
            wire["directories"].reverse()
        elif mutation == "children_duplicate":
            directory["children"].append(directory["children"][0])
        elif mutation == "root_binding":
            directory["inode"] = max(item["inode"] for item in (
                *wire["directories"], *wire["declared_manifest"]["files"],
            )) + 1
        else:
            wire["declared_manifest"]["manifest_sha256"] = "0" * 64
        raw = resign(wire)
    with pytest.raises(runtime.PythonRuntimeTreeError) as refused:
        runtime.parse_python_runtime_tree_manifest(raw.decode() if text else raw)
    assert refused.value.code == "python_runtime_tree_" + code


@pytest.mark.parametrize("gate,field", [
    ("constructor", "files"), ("constructor", "directories"),
    ("post_init", "files"), ("post_init", "directories"),
    ("build", "files"), ("verify", "files"), ("verify", "directories"),
])
def test_public_tree_gates_reject_mutated_same_wire_collections_before_callbacks(
    tmp_path, gate, field,
):
    tree = fixture(tmp_path)
    parsed = runtime.parse_python_runtime_tree_manifest(tree.closed.to_json())
    callbacks = []

    class SameItems(tuple):
        def __iter__(self):
            callbacks.append("iter")
            return super().__iter__()

        def __len__(self):
            callbacks.append("len")
            return super().__len__()

    subject = parsed.declared_manifest if field == "files" else parsed
    original = getattr(subject, field)
    changed = SameItems(original)
    assert tuple(tuple.__iter__(changed)) == original
    assert tuple.__len__(changed) == len(original)
    object.__setattr__(subject, field, changed)
    tree.original, tree.closed = parsed.declared_manifest, parsed
    with pytest.raises(runtime.PythonRuntimeTreeError):
        if gate == "constructor":
            runtime.PythonRuntimeTreeManifest(parsed.declared_manifest, parsed.directories, parsed.tree_sha256)
        elif gate == "post_init":
            parsed.__post_init__()
        elif gate == "build":
            build(tree)
        else:
            verify(tree)
    assert callbacks == []
