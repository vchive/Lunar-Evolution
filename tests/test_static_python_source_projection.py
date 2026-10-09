"""Synthetic inert archive members only; no upstream source is executed."""

from __future__ import annotations

import builtins
import dataclasses
import hashlib
import io
import json
import lzma
import math
import os
import socket
import subprocess
import tarfile
import time
import urllib.request
from pathlib import Path

import pytest

from tools.static_python_fixture import archive_observation as archive
from tools.static_python_fixture import source_patches as preparation
from tools.static_python_fixture import source_projection as projection

ROOT = "Python-3.13.12"
FIXTURE = Path(__file__).parent / "fixtures/static_python_source"


@pytest.fixture
def sources():
    return {path: (FIXTURE / (path + ".source")).read_bytes()
            for path in preparation.SOURCE_PATHS}


def _dir(path):
    member = tarfile.TarInfo(path)
    member.type = tarfile.DIRTYPE
    member.mode = 0o755
    return member, None


def _file(path, raw):
    member = tarfile.TarInfo(path)
    member.size = len(raw)
    member.mode = 0o644
    return member, raw


def _bundle(entries):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w", format=tarfile.USTAR_FORMAT) as tar:
        for member, raw in entries:
            tar.addfile(member, None if raw is None else io.BytesIO(raw))
    compressed = lzma.compress(stream.getvalue(), format=lzma.FORMAT_XZ)
    # The harness retains this pin from its known entry vector; it does not
    # take the expected digest from observe_archive_snapshot's return value.
    metadata = {
        "schema": "lunar-static-python-extraction-manifest-v1", "archive": "cpython",
        "root": ROOT, "archive_sha256": hashlib.sha256(compressed).hexdigest(),
        "members": sorted([{
            "path": member.name.rstrip("/") if member.isdir() else member.name,
            "kind": "directory" if member.isdir() else "file", "size": member.size,
            "mode": member.mode, "sha256": None if raw is None else hashlib.sha256(raw).hexdigest(),
        } for member, raw in entries], key=lambda item: item["path"]),
    }
    canonical = json.dumps(metadata, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, allow_nan=False).encode()
    return (archive.snapshot_inert_archive_bytes(compressed, "cpython"),
            hashlib.sha256(canonical).hexdigest())


def _entries(sources):
    return [_dir(ROOT)] + [_file(ROOT + "/" + path, raw) for path, raw in sources.items()]


def _prepare(bundle, **kwargs):
    snapshot, pin = bundle
    options = {"expected_manifest_sha256": pin, "require_profile": False,
               "deadline": time.monotonic() + 10.0}
    options.update(kwargs)
    return projection.prepare_archive_sources(snapshot, **options)


def _refused(call, reason=None):
    with pytest.raises(projection.StaticPythonSourceProjectionError) as error:
        call()
    if reason is not None:
        assert error.value.reason == "static_python_source_projection_" + reason
    return error.value


def _forbid(*args, **kwargs):
    pytest.fail("unexpected work or effect")


def test_actual_preimage_to_postimage_chain_is_frozen_and_detached(sources):
    expected, policy = preparation.prepare_static_python_sources(sources)
    snapshot, pin = _bundle(_entries(sources))
    result = _prepare((snapshot, pin))
    assert tuple(item.path for item in result.sources) == tuple(sorted(preparation.SOURCE_PATHS))
    for item in result.sources:
        assert item.archive_path == ROOT + "/" + item.path
        assert item.preimage_bytes == sources[item.path]
        assert item.preimage_size == len(sources[item.path])
        assert item.preimage_sha256 == hashlib.sha256(item.preimage_bytes).hexdigest()
        assert item.postimage_bytes == expected[item.path]
        assert item.postimage_size == len(expected[item.path])
        assert item.postimage_sha256 == hashlib.sha256(item.postimage_bytes).hexdigest()
    assert result.snapshot_sha256 == snapshot.snapshot_sha256
    assert result.manifest_sha256 == pin
    assert result.policy_sha256 == hashlib.sha256(result.policy_json).hexdigest()
    assert json.loads(result.policy_json) == policy
    assert result.projection_sha256 == hashlib.sha256(result.canonical_json).hexdigest()
    assert result.metadata_validation == "skipped-inert-profile"
    assert result.profile_pin_verified is False
    assert result.source_preimages_checked is True
    assert result.signature_verification == "not-performed"
    for key in ("release_verified", "source_execution_performed", "extraction_performed",
                "build_performed", "frozen_headers_generated", "runtime_execution_performed",
                "runtime_load_protection", "production_admission", "general_code_origin_protection"):
        assert getattr(result, key) is False
        assert result.to_manifest()[key] is False
    detached = result.to_manifest()
    detached["sources"].clear()
    sources.clear()
    assert len(result.sources) == len(result.to_manifest()["sources"]) == 3
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.sources = ()
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.sources[0].postimage_size = 0


def test_one_snapshot_one_decoder_and_no_reopen_or_effects(sources, monkeypatch):
    bundle = _bundle(_entries(sources))
    calls = []
    decode = archive._decompress

    def observe_once(snapshot, checkpoint=None):
        calls.append(snapshot)
        return decode(snapshot, checkpoint)

    monkeypatch.setattr(archive, "_decompress", observe_once)
    for owner, name in ((builtins, "open"), (os, "open"), (os, "stat"),
                        (Path, "read_bytes"), (Path, "write_bytes"),
                        (tarfile, "open"), (tarfile.TarFile, "extract"),
                        (tarfile.TarFile, "extractall"), (subprocess, "Popen"),
                        (subprocess, "run"), (socket, "socket"), (urllib.request, "urlopen")):
        monkeypatch.setattr(owner, name, _forbid)
    assert len(_prepare(bundle).sources) == 3
    assert calls == [bundle[0]]


@pytest.mark.parametrize("bad_pin", [None, "", "A" * 64, "0" * 64, "f" * 64, "a" * 63, 1])
def test_manifest_pin_shape_refuses_before_parser_or_patch(sources, monkeypatch, bad_pin):
    bundle = _bundle(_entries(sources))
    monkeypatch.setattr(projection, "_observe_archive_snapshot", _forbid)
    monkeypatch.setattr(preparation, "prepare_static_python_sources", _forbid)
    _refused(lambda: _prepare(bundle, expected_manifest_sha256=bad_pin), "manifest_pin_invalid")


def test_manifest_drift_refuses_before_preparation(sources, monkeypatch):
    bundle = _bundle(_entries(sources))
    monkeypatch.setattr(preparation, "prepare_static_python_sources", _forbid)
    _refused(lambda: _prepare(bundle, expected_manifest_sha256="b" * 64), "manifest_pin_mismatch")


@pytest.mark.parametrize("mutation", ["missing", "directory", "duplicate", "same-size", "size", "alias"])
def test_selected_sources_must_be_exact_fixed_members(sources, monkeypatch, mutation):
    path = preparation.SOURCE_PATHS[0]
    expected_reason = {
        "missing": "source_missing", "directory": "archive_selected_source_kind_invalid",
        "duplicate": "archive_member_duplicate_path", "same-size": "source_preimage_mismatch",
        "size": "source_preimage_mismatch", "alias": "source_missing",
    }[mutation]
    entries = _entries(sources)
    if mutation == "missing":
        entries.pop(1)
    elif mutation == "directory":
        entries[1] = _dir(ROOT + "/" + path)
    elif mutation == "duplicate":
        entries.append(entries[1])
    elif mutation == "same-size":
        entries[1] = _file(ROOT + "/" + path, b"!" + sources[path][1:])
    elif mutation == "size":
        entries[1] = _file(ROOT + "/" + path, sources[path] + b"!")
    else:
        entries[1] = _file(ROOT + "/alternative/" + path, sources[path])
    bundle = _bundle(entries)
    monkeypatch.setattr(preparation, "prepare_static_python_sources", _forbid)
    _refused(lambda: _prepare(bundle), expected_reason)


@pytest.mark.parametrize("extra_kind", ["link", "traversal", "duplicate-other"])
def test_full_archive_is_validated_after_all_three_sources(sources, monkeypatch, extra_kind):
    entries = _entries(sources)
    if extra_kind == "link":
        member = tarfile.TarInfo(ROOT + "/late-link")
        member.type = tarfile.SYMTYPE
        member.linkname = ROOT + "/Python/import.c"
        entries.append((member, None))
    elif extra_kind == "traversal":
        entries.append(_file(ROOT + "/../late-file", b"bad"))
    else:
        entries += [_file(ROOT + "/other", b"one"), _file(ROOT + "/other", b"two")]
    bundle = _bundle(entries)
    monkeypatch.setattr(preparation, "prepare_static_python_sources", _forbid)
    _refused(lambda: _prepare(bundle))


def test_profile_requirement_does_not_fall_back_to_inert(sources, monkeypatch):
    bundle = _bundle(_entries(sources))
    monkeypatch.setattr(archive, "_decompress", _forbid)
    monkeypatch.setattr(preparation, "prepare_static_python_sources", _forbid)
    _refused(lambda: _prepare(bundle, require_profile=True), "archive_archive_pin_mismatch")


@pytest.mark.parametrize("bad", [None, {}, "archive.xz", b"archive"])
def test_snapshot_input_has_no_mapping_or_path_fallback(monkeypatch, bad):
    monkeypatch.setattr(projection, "_observe_archive_snapshot", _forbid)
    _refused(lambda: projection.prepare_archive_sources(
        bad, expected_manifest_sha256="a" * 64, deadline=1.0), "snapshot_invalid")


@pytest.mark.parametrize("bad", [None, True, 1, 0.0, -1.0, math.nan, math.inf])
def test_deadline_shape_refuses_before_work(sources, monkeypatch, bad):
    bundle = _bundle(_entries(sources))
    monkeypatch.setattr(projection, "_observe_archive_snapshot", _forbid)
    _refused(lambda: _prepare(bundle, deadline=bad), "deadline_invalid")


@pytest.mark.parametrize("bad", [0, 1, None, "false"])
def test_profile_flag_requires_exact_bool(sources, monkeypatch, bad):
    bundle = _bundle(_entries(sources))
    monkeypatch.setattr(projection, "_observe_archive_snapshot", _forbid)
    _refused(lambda: _prepare(bundle, require_profile=bad), "profile_flag_invalid")


def test_selected_size_budget_precedes_member_hash_and_copy(sources, monkeypatch):
    bundle = _bundle(_entries(sources))
    monkeypatch.setattr(preparation, "MAX_SOURCE_BYTES", len(sources[preparation.SOURCE_PATHS[0]]) - 1)
    monkeypatch.setattr(archive, "_member_bytes", _forbid)
    _refused(lambda: _prepare(bundle), "archive_selected_source_size_invalid")


def test_selected_aggregate_budget_precedes_next_member_hash(sources, monkeypatch):
    bundle = _bundle(_entries(sources))
    first, second = preparation.SOURCE_PATHS[:2]
    monkeypatch.setattr(preparation, "MAX_TOTAL_SOURCE_BYTES", len(sources[first]) + len(sources[second]) - 1)
    hashed = []
    original = archive._member_bytes

    def hash_member(raw, member, checkpoint=None):
        hashed.append(member.name)
        assert member.name != ROOT + "/" + second
        return original(raw, member, checkpoint)

    monkeypatch.setattr(archive, "_member_bytes", hash_member)
    _refused(lambda: _prepare(bundle), "archive_selected_source_budget_exceeded")
    assert hashed == [ROOT + "/" + first]


def test_member_bytes_are_cross_checked_before_preparation(sources, monkeypatch):
    bundle = _bundle(_entries(sources))
    original = projection._observe_archive_snapshot

    def drift(*args, **kwargs):
        observed, captured = original(*args, **kwargs)
        altered = list(captured)
        path, raw = altered[0]
        altered[0] = (path, b"!" + raw[1:])
        return observed, tuple(altered)

    monkeypatch.setattr(projection, "_observe_archive_snapshot", drift)
    monkeypatch.setattr(preparation, "prepare_static_python_sources", _forbid)
    _refused(lambda: _prepare(bundle), "source_member_mismatch")


@pytest.mark.parametrize("phase", ["decode", "member-hash", "patch", "return"])
def test_original_deadline_is_not_reset_between_phases(sources, monkeypatch, phase):
    bundle = _bundle(_entries(sources))
    expired = False

    def clock():
        return 2.0 if expired else 0.0

    if phase == "decode":
        owner, name = archive, "_decompress"
    elif phase == "member-hash":
        owner, name = archive, "_member_bytes"
    elif phase == "patch":
        owner, name = preparation, "prepare_static_python_sources"
    else:
        owner, name = projection, "StaticPythonArchiveSourcePreparation"
    original = getattr(owner, name)

    def expire(*args, **kwargs):
        nonlocal expired
        result = original(*args, **kwargs)
        expired = True
        return result

    monkeypatch.setattr(owner, name, expire)
    _refused(lambda: _prepare(bundle, deadline=1.0, monotonic=clock), "wall_timeout")


def test_expired_deadline_and_invalid_clock_refuse_before_parser(sources, monkeypatch):
    bundle = _bundle(_entries(sources))
    monkeypatch.setattr(projection, "_observe_archive_snapshot", _forbid)
    _refused(lambda: _prepare(bundle, deadline=1.0, monotonic=lambda: 1.0), "wall_timeout")
    for value in (math.nan, math.inf, "bad", True, 10**10_000):
        _refused(lambda value=value: _prepare(bundle, deadline=1.0, monotonic=lambda: value),
                 "clock_invalid")


def test_postimage_returned_by_preparation_is_rehashed(sources, monkeypatch):
    bundle = _bundle(_entries(sources))
    original = preparation.prepare_static_python_sources

    def corrupt(inputs):
        outputs, policy = original(inputs)
        path = preparation.SOURCE_PATHS[0]
        outputs[path] = b"!" + outputs[path][1:]
        return outputs, policy

    monkeypatch.setattr(preparation, "prepare_static_python_sources", corrupt)
    _refused(lambda: _prepare(bundle), "source_postimage_mismatch")


def test_callback_bearing_input_types_are_refused_without_callbacks(sources, monkeypatch):
    bundle = _bundle(_entries(sources))

    class Text(str):
        __hash__ = str.__hash__
        __eq__ = _forbid

    class Bytes(bytes):
        __len__ = _forbid

    monkeypatch.setattr(preparation, "prepare_static_python_sources", _forbid)
    _refused(lambda: _prepare(bundle, expected_manifest_sha256=Text(bundle[1])), "manifest_pin_invalid")
    bad_archive = dataclasses.replace(bundle[0], archive=Text("cpython"))
    _refused(lambda: _prepare((bad_archive, bundle[1])), "archive_invalid")
    bad_bytes = dataclasses.replace(bundle[0], compressed_bytes=Bytes(bundle[0].compressed_bytes))
    _refused(lambda: _prepare((bad_bytes, bundle[1])), "archive_snapshot_integrity_invalid")


def test_wrong_archive_has_no_cpython_source_fallback(sources, monkeypatch):
    snapshot, pin = _bundle(_entries(sources))
    wrong = archive.snapshot_inert_archive_bytes(snapshot.compressed_bytes, "zig")
    monkeypatch.setattr(projection, "_observe_archive_snapshot", _forbid)
    _refused(lambda: _prepare((wrong, pin)), "archive_invalid")


def test_profile_metadata_and_inert_status_are_kept_separate(sources, monkeypatch, tmp_path):
    from tools.static_python_fixture import verified_inputs as metadata

    inert, pin = _bundle(_entries(sources))
    profile = archive._Profile("cpython", ROOT, "3.13.12", inert.archive_size,
                               inert.archive_sha256)
    monkeypatch.setitem(archive._PROFILES, "cpython", profile)
    monkeypatch.setattr(metadata, "_CPYTHON", dataclasses.replace(
        metadata._CPYTHON, sha256=inert.archive_sha256))
    fixture_path = tmp_path / "inert-fixture.xz"
    fixture_path.write_bytes(inert.compressed_bytes)
    snapshot = archive.snapshot_archive(fixture_path, "cpython")
    result = _prepare((snapshot, pin), require_profile=True)
    assert result.metadata_validation == "validated"
    assert result.profile_pin_verified is True
    assert result.release_verified is False
    assert json.loads(result.policy_json)["source_archive_verification"] == "not-performed"
    skipped = _prepare((snapshot, pin), require_profile=False)
    assert skipped.metadata_validation == "skipped-inert-profile"
    assert skipped.profile_pin_verified is False
    assert skipped.release_verified is False


def test_wrapped_deadline_refusal_has_no_exception_cause_cycle(sources, monkeypatch):
    bundle = _bundle(_entries(sources))
    expired = False
    original = archive._decompress

    def expire(*args, **kwargs):
        nonlocal expired
        result = original(*args, **kwargs)
        expired = True
        return result

    monkeypatch.setattr(archive, "_decompress", expire)
    error = _refused(lambda: _prepare(bundle, deadline=1.0,
                                    monotonic=lambda: 2.0 if expired else 0.0), "wall_timeout")
    seen = set()
    current = error
    while current is not None:
        assert id(current) not in seen
        seen.add(id(current))
        current = current.__cause__


@pytest.mark.parametrize("tail", ["xz-stream", "nonzero-tar"])
def test_trailing_material_is_rejected_even_after_fixed_sources(sources, monkeypatch, tail):
    snapshot, pin = _bundle(_entries(sources))
    if tail == "xz-stream":
        compressed = snapshot.compressed_bytes + lzma.compress(b"tail", format=lzma.FORMAT_XZ)
    else:
        compressed = lzma.compress(lzma.decompress(snapshot.compressed_bytes) + b"nonzero",
                                   format=lzma.FORMAT_XZ)
    altered = archive.snapshot_inert_archive_bytes(compressed, "cpython")
    monkeypatch.setattr(preparation, "prepare_static_python_sources", _forbid)
    _refused(lambda: _prepare((altered, pin)))
