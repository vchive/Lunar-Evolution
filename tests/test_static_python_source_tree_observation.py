"""Original source-tree observation over inert archive snapshots."""

from __future__ import annotations

import dataclasses
import hashlib
import io
import json
import lzma
import math
import tarfile
import time
from pathlib import Path

import pytest

from tools.static_python_fixture import archive_observation as archive
from tools.static_python_fixture import source_tree_observation as tree

ROOT = "Python-3.13.12"
FIXTURE = Path(__file__).parent / "fixtures/static_python_source"


def _dir(path, mode=0o755):
    member = tarfile.TarInfo(path)
    member.type = tarfile.DIRTYPE
    member.mode = mode
    return member, None


def _file(path, raw, mode=0o644):
    member = tarfile.TarInfo(path)
    member.size = len(raw)
    member.mode = mode
    return member, raw


def _bundle(entries):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for member, raw in entries:
            tar.addfile(member, None if raw is None else io.BytesIO(raw))
    compressed = lzma.compress(stream.getvalue(), format=lzma.FORMAT_XZ)
    members = sorted([{
        "path": item.name.rstrip("/") if item.isdir() else item.name,
        "kind": "directory" if item.isdir() else "file", "size": item.size,
        "mode": item.mode,
        "sha256": None if raw is None else hashlib.sha256(raw).hexdigest(),
    } for item, raw in entries], key=lambda item: item["path"])
    manifest = {"schema": "lunar-static-python-extraction-manifest-v1",
                "archive": "cpython", "root": ROOT,
                "archive_sha256": hashlib.sha256(compressed).hexdigest(),
                "members": members}
    manifest_json = json.dumps(manifest, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=False, allow_nan=False).encode()
    raw_tree = {
        "schema": tree.SOURCE_TREE_SCHEMA, "archive": "cpython", "root": ROOT,
        "version": "3.13.12",
        "files": [{"path": item["path"], "mode": item["mode"],
                   "size": item["size"], "sha256": item["sha256"]}
                  for item in members if item["kind"] == "file"],
    }
    tree_json = json.dumps(raw_tree, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, allow_nan=False).encode()
    return archive.snapshot_inert_archive_bytes(compressed, "cpython"), (
        hashlib.sha256(manifest_json).hexdigest(), hashlib.sha256(tree_json).hexdigest(),
    )


def _entries():
    return [_dir(ROOT), _dir(ROOT + "/Lib", 0o755),
            _file(ROOT + "/README.md", b"read me\n", 0o640),
            _file(ROOT + "/Lib/example.py", b"print('fixture')\n", 0o755),
            _file(ROOT + "/empty", b"", 0o600)]


def _observe(bundle, **kwargs):
    snapshot, pins = bundle
    options = {"expected_manifest_sha256": pins[0],
               "expected_source_tree_sha256": pins[1], "require_profile": False,
               "deadline": time.monotonic() + 10.0}
    options.update(kwargs)
    return tree.observe_snapshot_source_tree(snapshot, **options)


def _refused(call, reason):
    with pytest.raises(tree.StaticPythonSourceTreeObservationError) as error:
        call()
    assert error.value.reason == "static_python_source_tree_observation_" + reason


def test_complete_original_tree_uses_archive_modes_and_detached_views():
    result = _observe(_bundle(_entries()))
    assert result.schema == tree.SOURCE_TREE_OBSERVATION_SCHEMA
    assert result.profile_pin_verified is False
    assert result.metadata_validation == "skipped-inert-profile"
    assert result.signature_verification == "not-performed"
    assert [item.path for item in result.files] == [
        ROOT + "/Lib/example.py", ROOT + "/README.md", ROOT + "/empty"]
    assert [item.mode for item in result.files] == [0o755, 0o640, 0o600]
    assert result.source_tree_sha256 == hashlib.sha256(result.tree_json).hexdigest()
    assert result.observation_sha256 == hashlib.sha256(result.canonical_json).hexdigest()
    assert result.to_tree()["files"][0]["path"] == ROOT + "/Lib/example.py"
    detached = result.to_manifest()
    detached["files"].clear()
    detached["source_tree_sha256"] = "changed"
    assert len(result.files) == 3
    assert result.to_manifest()["source_tree_sha256"] == result.source_tree_sha256
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.files = ()


def test_tree_digest_is_independent_from_manifest_digest():
    result = _observe(_bundle(_entries()))
    assert result.manifest_sha256 != result.source_tree_sha256
    assert result.tree_json != result.canonical_json


@pytest.mark.parametrize("bad", [None, "", "A" * 64, "0" * 64, "f" * 64, "a" * 63, 1])
def test_external_pins_refuse_before_decode(monkeypatch, bad):
    bundle = _bundle(_entries())
    monkeypatch.setattr(archive, "_decompress", lambda *args, **kwargs: pytest.fail("decode"))
    _refused(lambda: _observe(bundle, expected_source_tree_sha256=bad), "source_tree_pin_invalid")


def test_manifest_and_tree_drift_refuse_before_success():
    bundle = _bundle(_entries())
    _refused(lambda: _observe(bundle, expected_manifest_sha256="a" * 64),
             "manifest_pin_mismatch")
    _refused(lambda: _observe(bundle, expected_source_tree_sha256="b" * 64),
             "source_tree_pin_mismatch")


def test_profile_mode_keeps_existing_fixed_pin_gate(monkeypatch):
    bundle = _bundle(_entries())
    monkeypatch.setattr(archive, "_decompress", lambda *args, **kwargs: pytest.fail("decode"))
    _refused(lambda: _observe(bundle, require_profile=True), "archive_archive_pin_mismatch")


@pytest.mark.parametrize("deadline", [None, True, 1, 0.0, -1.0, math.nan, math.inf])
def test_deadline_shape_refuses_before_decode(monkeypatch, deadline):
    bundle = _bundle(_entries())
    monkeypatch.setattr(archive, "_decompress", lambda *args, **kwargs: pytest.fail("decode"))
    _refused(lambda: _observe(bundle, deadline=deadline), "deadline_invalid")


def test_single_decode_and_no_path_or_runtime_route(monkeypatch):
    bundle = _bundle(_entries())
    calls = []
    original = archive._decompress

    def once(snapshot, checkpoint=None):
        calls.append(snapshot)
        return original(snapshot, checkpoint)

    monkeypatch.setattr(archive, "_decompress", once)
    result = _observe(bundle)
    assert result.files
    assert calls == [bundle[0]]


def test_deadline_covers_archive_walk():
    bundle = _bundle(_entries())
    ticks = iter([0.0, 0.0, 0.0, 2.0])
    _refused(lambda: _observe(bundle, deadline=1.0, monotonic=lambda: next(ticks)), "wall_timeout")


def test_zig_snapshot_is_outside_cpython_source_tree_slice():
    bundle = _bundle(_entries())
    snapshot = dataclasses.replace(bundle[0], archive="zig")
    _refused(lambda: tree.observe_snapshot_source_tree(
        snapshot, expected_manifest_sha256=bundle[1][0],
        expected_source_tree_sha256=bundle[1][1], require_profile=False,
        deadline=time.monotonic() + 10.0,
    ), "archive_invalid")


def test_huge_clock_value_is_a_fixed_refusal():
    bundle = _bundle(_entries())
    _refused(lambda: _observe(bundle, monotonic=lambda: 10**10000), "clock_invalid")
