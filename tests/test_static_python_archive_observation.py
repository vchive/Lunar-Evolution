"""Focused, provider-free tests for Feature189 Gate A archive observation."""

from __future__ import annotations

import dataclasses
import hashlib
import io
import lzma
import tarfile
from types import SimpleNamespace

import pytest

import tools.static_python_fixture.archive_observation as observation
from tools.static_python_fixture.archive_observation import (
    ArchiveSourceIdentity,
    StaticPythonArchiveObservationError,
    observe_archive_snapshot,
    snapshot_archive,
    snapshot_archive_bytes,
    snapshot_inert_archive_bytes,
)

ROOT = "Python-3.13.12"


def _tar(*infos: tuple[tarfile.TarInfo, bytes | None], format: int = tarfile.USTAR_FORMAT) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=format) as archive:
        for info, payload in infos:
            archive.addfile(info, None if payload is None else io.BytesIO(payload))
    return output.getvalue()


def _directory(path: str = ROOT, *, mode: int = 0o755) -> tarfile.TarInfo:
    info = tarfile.TarInfo(path)
    info.type = tarfile.DIRTYPE
    info.mode = mode
    return info


def _file(path: str, payload: bytes = b"payload", *, mode: int = 0o644) -> tuple[tarfile.TarInfo, bytes]:
    info = tarfile.TarInfo(path)
    info.mode = mode
    info.size = len(payload)
    return info, payload


def _compressed(*entries: tuple[tarfile.TarInfo, bytes | None], format: int = tarfile.USTAR_FORMAT) -> bytes:
    return lzma.compress(_tar(*entries, format=format), format=lzma.FORMAT_XZ)


def _snapshot(*entries: tuple[tarfile.TarInfo, bytes | None], format: int = tarfile.USTAR_FORMAT):
    return snapshot_inert_archive_bytes(_compressed(*entries, format=format), "cpython")


def _assert_refused(call, reason: str | None = None) -> None:
    with pytest.raises(StaticPythonArchiveObservationError) as raised:
        call()
    if reason is not None:
        assert raised.value.reason == "static_python_archive_observation_" + reason


def _normal_snapshot():
    return _snapshot(
        (_directory(), None),
        _file(f"{ROOT}/z.txt", b"last"),
        _file(f"{ROOT}/a.txt", b"first"),
    )


def _edited_header(raw: bytes, start: int, end: int, replacement: bytes) -> bytes:
    result = bytearray(raw)
    result[start:end] = replacement
    result[148:156] = b" " * 8
    checksum = sum(result[:512])
    result[148:156] = f"{checksum:06o}\0 ".encode("ascii")
    return bytes(result)


def test_inert_ustar_observation_hashes_and_sorts_members() -> None:
    result = observe_archive_snapshot(_normal_snapshot(), require_profile=False)
    assert [member.path for member in result.members] == [ROOT, f"{ROOT}/a.txt", f"{ROOT}/z.txt"]
    assert result.members[1].size == 5
    assert result.members[1].sha256 == hashlib.sha256(b"first").hexdigest()
    assert result.members[2].sha256 == hashlib.sha256(b"last").hexdigest()
    assert result.total_bytes == 9
    assert result.metadata_validation == "skipped-inert-profile"
    assert result.signature_verification == "not-performed"
    assert result.manifest_sha256 == hashlib.sha256(result.manifest_json).hexdigest()
    assert result.to_manifest()["members"] == [
        {"path": ROOT, "kind": "directory", "size": 0, "mode": 0o755, "sha256": None},
        {"path": f"{ROOT}/a.txt", "kind": "file", "size": 5, "mode": 0o644,
         "sha256": hashlib.sha256(b"first").hexdigest()},
        {"path": f"{ROOT}/z.txt", "kind": "file", "size": 4, "mode": 0o644,
         "sha256": hashlib.sha256(b"last").hexdigest()},
    ]


def test_snapshot_is_frozen_and_observation_does_not_reopen(monkeypatch) -> None:
    snapshot = _normal_snapshot()
    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.archive = "zig"  # type: ignore[misc]
    malformed = dataclasses.replace(snapshot, compressed_bytes=bytearray(snapshot.compressed_bytes))
    _assert_refused(lambda: observe_archive_snapshot(malformed, require_profile=False),
                    "snapshot_integrity_invalid")

    def blocked_open(*args, **kwargs):
        raise AssertionError("observation must consume snapshot bytes only")

    monkeypatch.setattr(observation.os, "open", blocked_open)
    assert observe_archive_snapshot(snapshot, require_profile=False).total_bytes == 9


def test_profile_pin_and_snapshot_integrity_refusals() -> None:
    compressed = _compressed((_directory(), None), _file(f"{ROOT}/x", b"x"))
    _assert_refused(lambda: snapshot_archive_bytes(compressed, "cpython"), "archive_pin_mismatch")
    _assert_refused(lambda: snapshot_inert_archive_bytes(compressed, "unknown"), "archive_invalid")
    snapshot = snapshot_inert_archive_bytes(compressed, "cpython")
    _assert_refused(lambda: observe_archive_snapshot(
        dataclasses.replace(snapshot, archive_size=snapshot.archive_size + 1), require_profile=False),
        "snapshot_integrity_invalid")
    _assert_refused(lambda: observe_archive_snapshot(
        dataclasses.replace(snapshot, expected_size=1), require_profile=False),
        "snapshot_profile_drift")
    _assert_refused(lambda: observe_archive_snapshot(snapshot), "archive_pin_mismatch")
    _assert_refused(lambda: observe_archive_snapshot(snapshot, require_profile=1),
                    "profile_flag_invalid")
    _assert_refused(lambda: observe_archive_snapshot(
        dataclasses.replace(snapshot, signature_verification="verified"), require_profile=False),
        "signature_status_invalid")


def test_xz_corruption_truncation_and_concatenation_are_rejected() -> None:
    compressed = _compressed((_directory(), None), _file(f"{ROOT}/x", b"x"))
    _assert_refused(lambda: observe_archive_snapshot(
        snapshot_inert_archive_bytes(compressed[:-1], "cpython"), require_profile=False),
        "xz_truncated")
    corrupted = compressed[:20] + bytes([compressed[20] ^ 0xFF]) + compressed[21:]
    _assert_refused(lambda: observe_archive_snapshot(
        snapshot_inert_archive_bytes(corrupted, "cpython"), require_profile=False),
        "xz_invalid")
    concatenated = compressed + lzma.compress(b"tail", format=lzma.FORMAT_XZ)
    _assert_refused(lambda: observe_archive_snapshot(
        snapshot_inert_archive_bytes(concatenated, "cpython"), require_profile=False),
        "xz_trailing_data")
    large = _compressed((_directory(), None), _file(f"{ROOT}/large", b"x" * 70_000))
    large_concatenated = large + lzma.compress(b"tail", format=lzma.FORMAT_XZ)
    _assert_refused(lambda: observe_archive_snapshot(
        snapshot_inert_archive_bytes(large_concatenated, "cpython"), require_profile=False),
        "xz_trailing_data")


def test_tar_end_markers_and_trailing_bytes_are_required() -> None:
    compressed = _compressed((_directory(), None), _file(f"{ROOT}/x", b"x"))
    tar_bytes = lzma.decompress(compressed)
    # The writer pads beyond the required two end blocks; remove everything
    # after the member data to remove both markers rather than only padding.
    for malformed in (tar_bytes[:1536], tar_bytes + b"nonzero", tar_bytes + b"\0"):
        _assert_refused(lambda malformed=malformed: observe_archive_snapshot(
            snapshot_inert_archive_bytes(lzma.compress(malformed, format=lzma.FORMAT_XZ), "cpython"),
            require_profile=False))


@pytest.mark.parametrize("name", [
    "/" + ROOT + "/x", ROOT + "//x", ROOT + r"\x", ROOT + "/./x", ROOT + "/../x",
    "other/x", ROOT + "/bad:name", ROOT + "/bad\x01name",
])
def test_path_traversal_and_normalization_are_rejected(name: str) -> None:
    _assert_refused(lambda: observe_archive_snapshot(
        _snapshot((_directory(), None), _file(name)), require_profile=False))


@pytest.mark.parametrize("member_type", [
    tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.FIFOTYPE, tarfile.CHRTYPE, tarfile.BLKTYPE,
])
def test_links_and_special_file_types_are_rejected(member_type: bytes) -> None:
    info = tarfile.TarInfo(f"{ROOT}/special")
    info.type = member_type
    info.linkname = f"{ROOT}/target"
    _assert_refused(lambda: observe_archive_snapshot(
        _snapshot((_directory(), None), (info, None)), require_profile=False))


def test_pax_gnu_sparse_and_special_mode_are_rejected() -> None:
    pax = tarfile.TarInfo(f"{ROOT}/pax")
    pax.size = 1
    pax.pax_headers = {"comment": "extension"}
    _assert_refused(lambda: observe_archive_snapshot(
        _snapshot((_directory(), None), (pax, b"x"), format=tarfile.PAX_FORMAT), require_profile=False))
    long_name = f"{ROOT}/" + "a" * 150
    _assert_refused(lambda: observe_archive_snapshot(
        _snapshot((_directory(), None), _file(long_name), format=tarfile.GNU_FORMAT),
        require_profile=False))
    special = _file(f"{ROOT}/setuid", b"x", mode=0o4755)
    _assert_refused(lambda: observe_archive_snapshot(
        _snapshot((_directory(), None), special), require_profile=False), "member_mode_invalid")


def test_duplicate_ancestor_and_missing_root_are_rejected() -> None:
    duplicate = _snapshot(
        (_directory(), None), _file(f"{ROOT}/same", b"a"), _file(f"{ROOT}/same", b"b"))
    _assert_refused(lambda: observe_archive_snapshot(duplicate, require_profile=False),
                    "member_duplicate_path")
    collision = _snapshot(
        (_directory(), None), _file(f"{ROOT}/file", b"a"), _file(f"{ROOT}/file/child", b"b"))
    _assert_refused(lambda: observe_archive_snapshot(collision, require_profile=False),
                    "file_directory_collision")
    no_root = _snapshot(_file(f"{ROOT}/orphan", b"x"))
    _assert_refused(lambda: observe_archive_snapshot(no_root, require_profile=False),
                    "root_directory_missing")


def test_member_and_stream_budgets_are_enforced(monkeypatch) -> None:
    snapshot = _normal_snapshot()
    monkeypatch.setattr(observation, "MAX_TAR_MEMBERS", 1)
    _assert_refused(lambda: observe_archive_snapshot(snapshot, require_profile=False),
                    "member_count_exceeded")
    monkeypatch.setattr(observation, "MAX_TAR_MEMBERS", 65_536)
    monkeypatch.setattr(observation, "MAX_FILE_BYTES", 1)
    _assert_refused(lambda: observe_archive_snapshot(snapshot, require_profile=False),
                    "member_size_invalid")
    monkeypatch.setattr(observation, "MAX_FILE_BYTES", 256 * 1024 * 1024)
    monkeypatch.setattr(observation, "MAX_TOTAL_FILE_BYTES", 1)
    _assert_refused(lambda: observe_archive_snapshot(snapshot, require_profile=False),
                    "total_byte_budget_exceeded")
    monkeypatch.setattr(observation, "MAX_TOTAL_FILE_BYTES", 1024 * 1024 * 1024)
    monkeypatch.setattr(observation, "MAX_TAR_STREAM_BYTES", 1)
    _assert_refused(lambda: observe_archive_snapshot(snapshot, require_profile=False),
                    "tar_stream_budget_exceeded")


def test_compressed_budget_and_deadline_are_enforced(monkeypatch, tmp_path) -> None:
    compressed = _compressed((_directory(), None), _file(f"{ROOT}/x", b"x"))
    monkeypatch.setattr(observation, "MAX_COMPRESSED_ARCHIVE_BYTES", len(compressed) - 1)
    _assert_refused(lambda: snapshot_inert_archive_bytes(compressed, "cpython"),
                    "archive_size_invalid")
    _assert_refused(lambda: snapshot_archive(tmp_path / "missing", "cpython",
                                             deadline=1.0, monotonic=lambda: 2.0), "wall_timeout")


def test_path_snapshot_uses_fixed_profile_and_rejects_symlink_components(monkeypatch, tmp_path) -> None:
    compressed = _compressed((_directory(), None), _file(f"{ROOT}/x", b"x"))
    profile = observation._Profile("cpython", ROOT, "3.13.12", len(compressed),
                                   hashlib.sha256(compressed).hexdigest())
    monkeypatch.setitem(observation._PROFILES, "cpython", profile)
    archive_path = tmp_path / "archive.xz"
    archive_path.write_bytes(compressed)
    snapshot = snapshot_archive(archive_path, "cpython")
    assert snapshot.profile_pin_verified is True
    assert snapshot.source_identity is not None
    parent = tmp_path / "real"
    parent.mkdir()
    link_parent = tmp_path / "link-parent"
    link_parent.symlink_to(parent, target_is_directory=True)
    _assert_refused(lambda: snapshot_archive(link_parent / "archive.xz", "cpython"),
                    "archive_read_failed")
    link_file = tmp_path / "link-file"
    link_file.symlink_to(archive_path)
    _assert_refused(lambda: snapshot_archive(link_file, "cpython"), "archive_read_failed")


def test_profile_metadata_validator_is_second_layer(monkeypatch, tmp_path) -> None:
    snapshot = _normal_snapshot()
    profile = observation._Profile("cpython", ROOT, "3.13.12", snapshot.archive_size,
                                   snapshot.archive_sha256)
    monkeypatch.setitem(observation._PROFILES, "cpython", profile)
    archive_path = tmp_path / "archive.xz"
    archive_path.write_bytes(snapshot.compressed_bytes)
    snapshot = snapshot_archive(archive_path, "cpython")
    calls: dict[str, object] = {}

    def fake_validator(manifest, *, expected_sha256, require_source_preimages):
        calls["manifest"] = manifest
        calls["expected_sha256"] = expected_sha256
        calls["require_source_preimages"] = require_source_preimages
        return SimpleNamespace(source_preimages_checked=True)

    monkeypatch.setattr(observation, "validate_static_python_extraction_manifest", fake_validator)
    result = observe_archive_snapshot(snapshot, expected_manifest_sha256="a" * 64,
                                      require_source_preimages=True)
    assert result.metadata_validation == "validated"
    assert result.source_preimages_checked is True
    assert calls["expected_sha256"] == "a" * 64
    assert calls["require_source_preimages"] is True


@pytest.mark.parametrize("member_type", [b"x", b"g", b"L", b"K", b"S", b"\0"])
def test_extensions_are_refused_before_library_header_parsing(monkeypatch, member_type) -> None:
    raw = _edited_header(_tar((_directory(), None)), 156, 157, member_type)
    snapshot = snapshot_inert_archive_bytes(lzma.compress(raw, format=lzma.FORMAT_XZ), "cpython")

    def forbidden(*args, **kwargs):
        raise AssertionError("extended header must not reach library parser")

    monkeypatch.setattr(tarfile.TarInfo, "frombuf", forbidden)
    _assert_refused(lambda: observe_archive_snapshot(snapshot, require_profile=False),
                    "member_type_unsupported")


@pytest.mark.parametrize("start,end,replacement", [
    (100, 108, b"\x80" + b"\0" * 7),
    (108, 116, b"-000001\0"),
    (136, 148, b"00000000008\0"),
    (124, 136, b"\0" + b"0000000001\0"),
])
def test_non_ustar_numeric_fields_are_refused(start, end, replacement) -> None:
    raw = _edited_header(_tar((_directory(), None)), start, end, replacement)
    snapshot = snapshot_inert_archive_bytes(lzma.compress(raw, format=lzma.FORMAT_XZ), "cpython")
    _assert_refused(lambda: observe_archive_snapshot(snapshot, require_profile=False),
                    "tar_numeric_unsupported")


@pytest.mark.parametrize("start,end", [(0, 100), (345, 500)])
def test_tar_text_after_nul_is_not_silently_discarded(start, end) -> None:
    replacement = b"name\0garbage" + bytes(end - start - len(b"name\0garbage"))
    raw = _edited_header(_tar((_directory(), None)), start, end, replacement)
    snapshot = snapshot_inert_archive_bytes(lzma.compress(raw, format=lzma.FORMAT_XZ), "cpython")
    _assert_refused(lambda: observe_archive_snapshot(snapshot, require_profile=False),
                    "tar_text_unsupported")


@pytest.mark.parametrize("flag", [0, 1, None, "false"])
def test_profile_flag_requires_exact_bool(flag) -> None:
    compressed = _compressed((_directory(), None))
    _assert_refused(lambda: snapshot_archive_bytes(compressed, "cpython", require_profile=flag),
                    "profile_flag_invalid")
    _assert_refused(lambda: observe_archive_snapshot(_normal_snapshot(), require_profile=flag),
                    "profile_flag_invalid")


def test_bytes_pin_seam_cannot_claim_path_acquisition(monkeypatch) -> None:
    compressed = _compressed((_directory(), None))
    profile = observation._Profile("cpython", ROOT, "3.13.12", len(compressed),
                                   hashlib.sha256(compressed).hexdigest())
    monkeypatch.setitem(observation._PROFILES, "cpython", profile)
    snapshot = snapshot_archive_bytes(compressed, "cpython")
    assert snapshot.profile_pin_verified is False
    assert snapshot.source_identity is None
    forged = dataclasses.replace(snapshot, profile_pin_verified=True)
    _assert_refused(lambda: observe_archive_snapshot(forged), "archive_pin_mismatch")


def test_parent_close_failure_cleans_up_new_child(monkeypatch) -> None:
    descriptors = iter((101, 102))
    closed = []
    monkeypatch.setattr(observation.os, "open", lambda *args, **kwargs: next(descriptors))

    def close(fd):
        closed.append(fd)
        if fd == 101:
            raise OSError("uncertain close")

    monkeypatch.setattr(observation.os, "close", close)
    _assert_refused(lambda: snapshot_archive("folder/archive.xz", "cpython"), "cleanup_unknown")
    assert closed == [101, 102]


@pytest.mark.parametrize("clock", [lambda: float("nan"), lambda: float("inf"), lambda: "bad"])
def test_invalid_monotonic_values_are_refused(clock) -> None:
    _assert_refused(lambda: snapshot_archive("archive.xz", "cpython", deadline=1.0,
                                             monotonic=clock), "clock_invalid")


def test_deadline_is_checked_before_parent_traversal(monkeypatch) -> None:
    clocks = iter((0.0, 2.0))
    opened = []
    closed = []

    def open_fd(*args, **kwargs):
        opened.append(args[0])
        return 101

    monkeypatch.setattr(observation.os, "open", open_fd)
    monkeypatch.setattr(observation.os, "close", closed.append)
    _assert_refused(lambda: snapshot_archive("folder/archive.xz", "cpython", deadline=1.0,
                                             monotonic=lambda: next(clocks)), "wall_timeout")
    assert opened == ["."]
    assert closed == [101]


@pytest.mark.parametrize("path", ["", "a/../b", "a/./b", "a//b", "/a//b", "a/" * 65 + "b"])
def test_literal_source_paths_are_bounded_and_not_normalized(path) -> None:
    _assert_refused(lambda: snapshot_archive(path, "cpython"), "path_invalid")


def test_snapshot_fields_are_checked_before_hashing(monkeypatch) -> None:
    snapshot = _normal_snapshot()
    monkeypatch.setattr(observation, "MAX_COMPRESSED_ARCHIVE_BYTES", 1)
    monkeypatch.setattr(observation.hashlib, "sha256", lambda *_: pytest.fail("hash before budget"))
    _assert_refused(lambda: observe_archive_snapshot(snapshot, require_profile=False),
                    "snapshot_integrity_invalid")


def test_source_identity_and_pin_flag_types_are_checked() -> None:
    snapshot = _normal_snapshot()
    bad_identity = ArchiveSourceIdentity(1, 1, snapshot.archive_size, "bad", 1, 1)
    _assert_refused(lambda: observe_archive_snapshot(
        dataclasses.replace(snapshot, source_identity=bad_identity), require_profile=False),
        "snapshot_integrity_invalid")
    _assert_refused(lambda: observe_archive_snapshot(
        dataclasses.replace(snapshot, profile_pin_verified=1), require_profile=False),
        "snapshot_profile_drift")


def test_actual_metadata_validator_accepts_canonical_hash_and_rejects_wrong_pin(monkeypatch, tmp_path):
    import tools.static_python_fixture.verified_inputs as metadata

    compressed = _compressed((_directory(), None), _file(f"{ROOT}/x", b"x"))
    digest = hashlib.sha256(compressed).hexdigest()
    profile = observation._Profile("cpython", ROOT, "3.13.12", len(compressed), digest)
    monkeypatch.setitem(observation._PROFILES, "cpython", profile)
    monkeypatch.setattr(metadata, "_CPYTHON", dataclasses.replace(metadata._CPYTHON, sha256=digest))
    path = tmp_path / "inert-pinned-archive.xz"
    path.write_bytes(compressed)
    snapshot = snapshot_archive(path, "cpython")
    expected = observe_archive_snapshot(snapshot, require_profile=False).manifest_sha256
    result = observe_archive_snapshot(snapshot, expected_manifest_sha256=expected)
    assert result.metadata_validation == "validated"
    assert result.manifest_sha256 == expected
    _assert_refused(lambda: observe_archive_snapshot(snapshot, expected_manifest_sha256="b" * 64),
                    "metadata_manifest_invalid")


@pytest.mark.parametrize("valid_hash", [True, False])
def test_cleanup_attempts_both_owners_and_preserves_primary(monkeypatch, tmp_path, valid_hash):
    compressed = _compressed((_directory(), None), _file(f"{ROOT}/x", b"x"))
    digest = hashlib.sha256(compressed).hexdigest() if valid_hash else "a" * 64
    monkeypatch.setitem(observation._PROFILES, "cpython",
                        observation._Profile("cpython", ROOT, "3.13.12", len(compressed), digest))
    path = tmp_path / "archive.xz"
    path.write_bytes(compressed)
    monkeypatch.chdir(tmp_path)
    real_open = observation.os.open
    real_close = observation.os.close
    file_fd = None
    closed = []

    def open_fd(path, flags, **kwargs):
        nonlocal file_fd
        fd = real_open(path, flags, **kwargs)
        if flags == observation._FILE_FLAGS:
            file_fd = fd
        return fd

    def close_fd(fd):
        closed.append(fd)
        real_close(fd)
        if fd == file_fd:
            raise OSError("uncertain close")

    monkeypatch.setattr(observation.os, "open", open_fd)
    monkeypatch.setattr(observation.os, "close", close_fd)
    _assert_refused(lambda: snapshot_archive("archive.xz", "cpython"),
                    "cleanup_unknown" if valid_hash else "archive_sha256_mismatch")
    assert len(closed) == 2
    assert closed[0] == file_fd


@pytest.mark.parametrize("read_case", ["partial", "empty", "extra"])
def test_path_acquisition_checks_partial_reads_and_exact_eof(monkeypatch, tmp_path, read_case):
    compressed = _compressed((_directory(), None), _file(f"{ROOT}/x", b"x"))
    monkeypatch.setitem(observation._PROFILES, "cpython", observation._Profile(
        "cpython", ROOT, "3.13.12", len(compressed), hashlib.sha256(compressed).hexdigest()))
    path = tmp_path / "archive.xz"
    path.write_bytes(compressed)
    real_pread = observation.os.pread

    def pread(fd, wanted, offset):
        if read_case == "empty" and offset == 0:
            return b""
        if read_case == "extra" and offset == len(compressed):
            return b"x"
        return real_pread(fd, min(wanted, 2), offset)

    monkeypatch.setattr(observation.os, "pread", pread)
    if read_case == "partial":
        assert snapshot_archive(path, "cpython").compressed_bytes == compressed
    else:
        _assert_refused(lambda: snapshot_archive(path, "cpython"),
                        "archive_read_failed" if read_case == "empty" else "archive_size_drift")


def test_path_acquisition_rejects_named_inode_drift(monkeypatch, tmp_path):
    compressed = _compressed((_directory(), None))
    monkeypatch.setitem(observation._PROFILES, "cpython", observation._Profile(
        "cpython", ROOT, "3.13.12", len(compressed), hashlib.sha256(compressed).hexdigest()))
    path = tmp_path / "archive.xz"
    path.write_bytes(compressed)
    real_stat = observation.os.stat
    calls = 0

    def stat_path(*args, **kwargs):
        nonlocal calls
        info = real_stat(*args, **kwargs)
        calls += 1
        return SimpleNamespace(st_dev=info.st_dev, st_ino=info.st_ino + (calls > 1),
                               st_size=info.st_size, st_mode=info.st_mode,
                               st_mtime_ns=info.st_mtime_ns, st_ctime_ns=info.st_ctime_ns)

    monkeypatch.setattr(observation.os, "stat", stat_path)
    _assert_refused(lambda: snapshot_archive(path, "cpython"), "archive_identity_drift")


def test_fifo_path_is_rejected_without_blocking(tmp_path):
    path = tmp_path / "fifo.xz"
    observation.os.mkfifo(path)
    _assert_refused(lambda: snapshot_archive(path, "cpython"), "archive_not_regular")


@pytest.mark.parametrize("expire_at", ["digest", "snapshot"])
def test_deadline_remains_active_after_last_read(monkeypatch, tmp_path, expire_at):
    compressed = _compressed((_directory(), None))
    digest = hashlib.sha256(compressed).hexdigest()
    monkeypatch.setitem(observation._PROFILES, "cpython",
                        observation._Profile("cpython", ROOT, "3.13.12", len(compressed), digest))
    (tmp_path / "archive.xz").write_bytes(compressed)
    monkeypatch.chdir(tmp_path)
    expired = False
    closed = []
    real_close = observation.os.close

    def close(fd):
        closed.append(fd)
        real_close(fd)

    monkeypatch.setattr(observation.os, "close", close)
    if expire_at == "digest":
        real_sha256 = observation.hashlib.sha256

        def sha256(raw):
            nonlocal expired
            result = real_sha256(raw)
            expired = True
            return result

        monkeypatch.setattr(observation.hashlib, "sha256", sha256)
    else:
        real_snapshot = observation._snapshot_bytes

        def snapshot_bytes(*args, **kwargs):
            nonlocal expired
            result = real_snapshot(*args, **kwargs)
            expired = True
            return result

        monkeypatch.setattr(observation, "_snapshot_bytes", snapshot_bytes)
    _assert_refused(lambda: snapshot_archive("archive.xz", "cpython", deadline=1.0,
                                             monotonic=lambda: 2.0 if expired else 0.0),
                    "wall_timeout")
    assert len(closed) == 2
