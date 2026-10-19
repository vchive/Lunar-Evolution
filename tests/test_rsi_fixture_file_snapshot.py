"""SQLite scratch files never enter the durable fixture file observation."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from test_python_producer_recovery_anchor import _durable_snapshot
from test_rsi_python_admission import _files


def _value(tmp_path):
    return SimpleNamespace(
        workspace=tmp_path,
        ledger=SimpleNamespace(database=tmp_path / "selected-service.sqlite3"),
    )


@pytest.mark.parametrize("suffix", ["", "-wal", "-shm", "-journal", "-temporary"])
def test_ledger_paths_are_excluded_before_stat_or_read(tmp_path, monkeypatch, suffix):
    value = _value(tmp_path)
    evidence = tmp_path / "evidence.json"
    evidence.write_bytes(b"original evidence")
    transient = tmp_path / (value.ledger.database.name + suffix)
    original_rglob, original_lstat, original_read = Path.rglob, Path.lstat, Path.read_bytes
    calls = []

    def rglob(path, pattern):
        yield from original_rglob(path, pattern)
        if path == tmp_path:
            # Model a SQLite sidecar removed after directory enumeration.
            yield transient

    def lstat(path):
        if path == transient:
            calls.append("stat")
            raise FileNotFoundError(transient)
        return original_lstat(path)

    def read(path):
        if path == transient:
            calls.append("read")
            raise FileNotFoundError(transient)
        return original_read(path)

    monkeypatch.setattr(Path, "rglob", rglob)
    monkeypatch.setattr(Path, "lstat", lstat)
    monkeypatch.setattr(Path, "read_bytes", read)

    result = _files(value)

    assert set(result) == {Path("evidence.json")}
    assert result[Path("evidence.json")][-1] == b"original evidence"
    assert calls == []


def test_ledger_file_lifetime_does_not_change_durable_file_snapshot(tmp_path):
    value = _value(tmp_path)
    (tmp_path / "evidence.json").write_bytes(b"original evidence")
    original = _files(value)
    database_files = [tmp_path / (value.ledger.database.name + suffix)
                      for suffix in ("", "-wal", "-shm", "-journal")]
    for path in database_files:
        path.write_bytes(b"SQLite scratch state")
    assert _files(value) == original
    for path in database_files:
        path.unlink()
    assert _files(value) == original


def test_unexcluded_disappearing_file_still_fails(tmp_path, monkeypatch):
    value = _value(tmp_path)
    missing = tmp_path / "missing-evidence.json"
    monkeypatch.setattr(Path, "rglob", lambda _path, _pattern: iter((missing,)))

    with pytest.raises(FileNotFoundError):
        _files(value)


def test_generic_snapshot_remains_strict_without_an_exclusion(tmp_path):
    database = tmp_path / "selected-service.sqlite3"
    sidecar = tmp_path / "selected-service.sqlite3-shm"
    database.write_bytes(b"database")
    sidecar.write_bytes(b"sidecar")

    snapshot = _durable_snapshot(tmp_path)

    assert set(snapshot) == {Path(database.name), Path(sidecar.name)}
    assert snapshot[Path(sidecar.name)][-1] == b"sidecar"


def test_database_prefix_in_another_directory_remains_durable(tmp_path):
    value = _value(tmp_path)
    directory = tmp_path / "retained"
    directory.mkdir()
    evidence = directory / (value.ledger.database.name + "-shm")
    evidence.write_bytes(b"original durable file")
    original = _files(value)
    name = evidence.relative_to(tmp_path)
    assert original[name][-1] == b"original durable file"

    evidence.write_bytes(b"changed durable file")

    assert _files(value)[name] != original[name]
