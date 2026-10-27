"""Create-only CLI for the fixed source profile, without builds or execution."""

from __future__ import annotations

import argparse
import os
import stat
import sys
from pathlib import Path

from .prepare import (
    ARCHIVE_BYTES,
    BROKER_BYTES,
    PREPARED_PATHS,
    TRANSPORT_BYTES,
    ShinkaPreparationError,
    ShinkaPreparedProfile,
    prepare_shinka_sources,
)


class _Parser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise ShinkaPreparationError("shinka_source_arguments_invalid")


def _read_regular(path: Path, maximum: int) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum:
            raise ShinkaPreparationError("shinka_source_input_invalid")
        chunks = []
        remaining = maximum + 1
        while remaining:
            part = os.read(descriptor, min(65536, remaining))
            if not part:
                break
            chunks.append(part)
            remaining -= len(part)
        raw = b"".join(chunks)
        after = os.fstat(descriptor)
        named = os.stat(path, follow_symlinks=False)
        fields = ("st_dev", "st_ino", "st_mode", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns")
        if (len(raw) != before.st_size or len(raw) > maximum
                or any(getattr(before, name) != getattr(after, name) for name in fields)
                or any(getattr(after, name) != getattr(named, name) for name in fields)):
            raise ShinkaPreparationError("shinka_source_input_drift")
        return raw
    finally:
        os.close(descriptor)


def _write_file(directory: int, name: str, raw: bytes) -> None:
    descriptor = os.open(
        name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o444, dir_fd=directory,
    )
    try:
        offset = 0
        while offset < len(raw):
            count = os.write(descriptor, raw[offset:])
            if count <= 0:
                raise ShinkaPreparationError("shinka_source_output_failed")
            offset += count
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_prepared_profile(profile: ShinkaPreparedProfile, destination: Path) -> None:
    """Create a fresh directory and commit its preparation manifest last.

    Only preparer-created profiles belong here; this is not source admission.
    No caller-owned existing output is removed. A failed partial new directory is
    retained for inspection and cannot be silently reused as a completed profile.
    """
    if (type(profile) is not ShinkaPreparedProfile
            or type(profile.sources) is not tuple
            or len(profile.sources) != len(PREPARED_PATHS)
            or {source.path for source in profile.sources} != PREPARED_PATHS
            or any(type(source.data) is not bytes for source in profile.sources)
            or type(profile.manifest) is not bytes):
        raise ShinkaPreparationError("shinka_source_output_invalid")
    destination.mkdir(mode=0o755, parents=False, exist_ok=False)
    descriptor = os.open(destination, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        for source in profile.sources:
            parts = source.path.split("/")
            current = os.dup(descriptor)
            try:
                for part in parts[:-1]:
                    try:
                        os.mkdir(part, 0o755, dir_fd=current)
                    except FileExistsError:
                        pass
                    child = os.open(
                        part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                        dir_fd=current,
                    )
                    os.close(current)
                    current = child
                _write_file(current, parts[-1], source.data)
                os.fsync(current)
            finally:
                os.close(current)
        _write_file(descriptor, "source-manifest.json", profile.manifest)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main(argv: list[str] | None = None) -> int:
    parser = _Parser(description="Prepare pinned Shinka sources; never build or execute.")
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--destination", required=True, type=Path)
    try:
        arguments = parser.parse_args(argv)
        repository = Path(__file__).resolve().parents[2]
        profile = prepare_shinka_sources(
            _read_regular(arguments.archive, ARCHIVE_BYTES),
            broker_source_bytes=_read_regular(
                repository / "src/lunar_evolution/producer_broker_ipc.py", BROKER_BYTES,
            ),
            transport_source_bytes=_read_regular(
                repository / "src/lunar_evolution/http_transport.py", TRANSPORT_BYTES,
            ),
        )
        _write_prepared_profile(profile, arguments.destination)
    except ShinkaPreparationError as error:
        print(str(error), file=sys.stderr)
        return 2
    except (OSError, ValueError, OverflowError):
        print("shinka_source_io_failed", file=sys.stderr)
        return 2
    print("shinka_source_prepared " + profile.manifest_sha256)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
