"""Descriptor ownership regressions for staged-source observation."""

from __future__ import annotations

import errno
import os
from pathlib import Path

import pytest
import test_static_python_source_staging as staging_fixtures

from tools.static_python_fixture import candidate_build_source
from tools.static_python_fixture import candidate_build_source_observation as observation


@pytest.fixture
def staging_record(tmp_path: Path) -> dict[str, object]:
    sources = {
        path: (staging_fixtures.FIXTURE / (path + ".source")).read_bytes()
        for path in staging_fixtures.preparation.SOURCE_PATHS
    }
    bundle = staging_fixtures._bundle(staging_fixtures._entries(sources))
    result = staging_fixtures._stage(bundle, tmp_path.resolve() / "stage")
    staging, _ = candidate_build_source._validate_staging(
        result.canonical_json, result.staging_sha256,
    )
    return staging


@pytest.mark.parametrize(
    ("failure_point", "open_index"),
    [
        ("child_fstat", 1),
        ("child_stat", 1),
        ("root_fstat", -1),
        ("root_stat", -1),
    ],
)
def test_open_root_closes_every_acquired_descriptor_on_verification_error(
    staging_record: dict[str, object], monkeypatch: pytest.MonkeyPatch,
    failure_point: str, open_index: int,
) -> None:
    real_open = os.open
    real_fstat = os.fstat
    real_stat = os.stat
    opened: list[tuple[int, object, int | None]] = []

    def tracked_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
        fd = real_open(path, flags, *args, **kwargs)
        opened.append((fd, path, kwargs.get("dir_fd")))
        return fd

    monkeypatch.setattr(observation.os, "open", tracked_open)
    components = observation._path_parts(staging_record["destination"])

    def target_fd() -> int | None:
        if not opened:
            return None
        return opened[open_index][0] if open_index >= 0 and len(opened) > open_index else (
            opened[-1][0] if open_index < 0 and len(opened) == len(components) + 1 else None
        )

    def fail_fstat(fd: int) -> os.stat_result:
        if failure_point.endswith("fstat") and fd == target_fd():
            raise OSError(errno.EIO, "injected fstat failure")
        return real_fstat(fd)

    def fail_stat(path: object, *args: object, **kwargs: object) -> os.stat_result:
        target = target_fd()
        if failure_point.endswith("stat") and target is not None:
            target_record = opened[open_index] if open_index >= 0 else opened[-1]
            if path == target_record[1] and kwargs.get("dir_fd") == target_record[2]:
                raise OSError(errno.EIO, "injected stat failure")
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(observation.os, "fstat", fail_fstat)
    monkeypatch.setattr(observation.os, "stat", fail_stat)

    with pytest.raises(OSError, match="injected"):
        observation._open_root(staging_record)

    # Use the saved syscall directly: every descriptor returned by a successful
    # open, including the one whose metadata check failed, must now be closed.
    expected_opens = 2 if open_index >= 0 else len(components) + 1
    assert len(opened) == expected_opens
    for fd, _path, _parent in opened:
        with pytest.raises(OSError) as caught:
            real_fstat(fd)
        assert caught.value.errno == errno.EBADF
