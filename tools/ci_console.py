"""Retain complete CI bytes while limiting each console line's payload to 4096 bytes.

The --log output is create-only and receives the original binary stdin without
decoding or rewriting it. Console lines are delimited only by LF. Short lines,
including CR and UTF-8 bytes split across input chunks, are reproduced exactly.
An oversized line retains its first 4096 bytes, then a synthetic LF and one finite
omission marker. The marker's SHA256 covers the entire original line, excluding
its terminating LF (if present), including CR and all omitted bytes. Its byte
count uses the same domain. An oversized final unterminated line gets a marker
at EOF. Neither a raw logfile nor a marker alone establishes test completion.

Memory use is bounded by fixed input chunks and hash state, independent of line
length. This tool does not start, stop, retry, or impose timeouts on processes.
Input, raw-log, and console I/O errors are failures for the shell's pipefail gate;
any partial raw logfile is retained and is never overwritten on another run.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path
from typing import BinaryIO

_READ_CHUNK_BYTES = 64 * 1024
_CONSOLE_LINE_BYTES = 4096


def _write_all(stream: BinaryIO, raw: bytes | memoryview) -> None:
    remaining = memoryview(raw)
    while remaining:
        written = stream.write(remaining)
        if type(written) is not int or not 0 < written <= len(remaining):
            raise OSError("incomplete binary write")
        remaining = remaining[written:]


def copy_stream(source: BinaryIO, console: BinaryIO, retained: BinaryIO) -> None:
    """Copy a finite-chunk binary stream, with full-line hashes for omitted tails."""
    line_bytes = 0
    line_digest = hashlib.sha256()
    truncated = False

    def finish_line(*, terminated: bool) -> None:
        nonlocal line_bytes, line_digest, truncated
        if truncated:
            marker = (
                "lunar-ci-console omitted-tail "
                f"line_bytes={line_bytes} retained_bytes={_CONSOLE_LINE_BYTES} "
                f"sha256={line_digest.hexdigest()}\n"
            ).encode("ascii")
            _write_all(console, marker)
        elif terminated:
            _write_all(console, b"\n")
        line_bytes = 0
        line_digest = hashlib.sha256()
        truncated = False

    while True:
        chunk = source.read1(_READ_CHUNK_BYTES)
        if type(chunk) is not bytes or len(chunk) > _READ_CHUNK_BYTES:
            raise OSError("invalid binary input read")
        if not chunk:
            break
        _write_all(retained, chunk)
        fragments = chunk.split(b"\n")
        for index, fragment in enumerate(fragments):
            room = max(0, _CONSOLE_LINE_BYTES - line_bytes)
            if room:
                _write_all(console, fragment[:room])
            line_bytes += len(fragment)
            line_digest.update(fragment)
            if line_bytes > _CONSOLE_LINE_BYTES and not truncated:
                _write_all(console, b"\n")
                truncated = True
            if index < len(fragments) - 1:
                finish_line(terminated=True)
        retained.flush()
        console.flush()
    if line_bytes:
        finish_line(terminated=False)
    retained.flush()
    console.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", required=True, type=Path, help="create-only complete binary logfile")
    arguments = parser.parse_args(argv)
    try:
        descriptor = os.open(arguments.log, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
                             0o600)
        with os.fdopen(descriptor, "wb") as retained:
            copy_stream(sys.stdin.buffer, sys.stdout.buffer, retained)
    except (OSError, ValueError):
        # Avoid reproducing source bytes, paths, or a huge failed console write.
        try:
            sys.stderr.write("lunar-ci-console io failure\n")
            sys.stderr.flush()
        except (OSError, ValueError):
            pass
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
