"""Binary CI retention and bounded display are independent of test selection."""
from __future__ import annotations

import hashlib
import importlib.util
import io
import shlex
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "tools/ci_console.py"
SPEC = importlib.util.spec_from_file_location("ci_console", SCRIPT)
assert SPEC and SPEC.loader
console = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(console)


class _ChunkedInput:
    def __init__(self, raw: bytes, sizes: tuple[int, ...]):
        self.raw = raw
        self.sizes = iter(sizes)
        self.reads = []

    def read1(self, maximum):
        self.reads.append(maximum)
        size = min(next(self.sizes, maximum), maximum)
        result, self.raw = self.raw[:size], self.raw[size:]
        return result


@pytest.mark.parametrize("raw", [
    b"", b"short\n\nlast", b"cr\rprogress\r\nnext\n", "字🙂\r\n尾".encode(),
    b"x" * 4096 + b"\nexact", b"x" * 4096,
])
def test_short_lines_are_exact_across_binary_chunk_boundaries(raw):
    source = _ChunkedInput(raw, (1, 2, 1, 3, 1, 4, 4090, 2, 1))
    displayed, retained = io.BytesIO(), io.BytesIO()
    console.copy_stream(source, displayed, retained)
    assert retained.getvalue() == displayed.getvalue() == raw
    assert source.reads and set(source.reads) == {64 * 1024}


@pytest.mark.parametrize("terminated", [False, True])
def test_oversize_line_hash_covers_all_original_bytes_including_cr(terminated):
    line = b"a" * 4095 + "🙂".encode() + b"\r" + b"z" * (256 * 1024)
    raw = line + (b"\nnext\r\n" if terminated else b"")
    displayed, retained = io.BytesIO(), io.BytesIO()
    console.copy_stream(_ChunkedInput(raw, (4095, 1, 2, 1, 1)), displayed, retained)
    marker = (
        "lunar-ci-console omitted-tail "
        f"line_bytes={len(line)} retained_bytes=4096 sha256={hashlib.sha256(line).hexdigest()}\n"
    ).encode()
    assert retained.getvalue() == raw
    assert displayed.getvalue() == line[:4096] + b"\n" + marker + (b"next\r\n" if terminated else b"")
    assert max(map(len, displayed.getvalue().split(b"\n"))) <= 4096


@pytest.mark.parametrize("terminated", [False, True])
def test_first_byte_past_limit_is_omitted_and_original_lf_is_not_hashed(terminated):
    line = b"x" * 4097
    raw = line + (b"\n" if terminated else b"")
    displayed, retained = io.BytesIO(), io.BytesIO()
    console.copy_stream(_ChunkedInput(raw, (4096, 1, 1)), displayed, retained)
    marker = (
        "lunar-ci-console omitted-tail line_bytes=4097 retained_bytes=4096 "
        f"sha256={hashlib.sha256(line).hexdigest()}\n"
    ).encode()
    assert retained.getvalue() == raw
    assert displayed.getvalue() == b"x" * 4096 + b"\n" + marker


def test_natural_subprocess_pipeline_retains_giant_split_line_and_finite_console(tmp_path):
    logfile = tmp_path / "pytest.log"
    emitter = subprocess.Popen([
        sys.executable, "-c",
        ("import os\nos.write(1, 'start字\\r\\n'.encode())\n"
        "for _ in range(600): os.write(1, b'x' * 4093)\n"
        "os.write(1, b'\\nend\\n')\n"),
    ], stdout=subprocess.PIPE)
    assert emitter.stdout is not None
    observer = subprocess.Popen([sys.executable, str(SCRIPT), "--log", str(logfile)],
                                stdin=emitter.stdout, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE)
    emitter.stdout.close()
    output, errors = observer.communicate(timeout=20)
    assert emitter.wait(timeout=20) == observer.returncode == 0
    assert errors == b""
    line = b"x" * (600 * 4093)
    assert logfile.read_bytes() == "start字\r\n".encode() + line + b"\nend\n"
    assert output.startswith("start字\r\n".encode() + b"x" * 4096 + b"\n")
    assert output.endswith(b"\nend\n")
    assert hashlib.sha256(line).hexdigest().encode() in output
    assert f"line_bytes={len(line)}".encode() in output
    assert len(output) < 4500
    assert max(map(len, output.split(b"\n"))) <= 4096
    assert stat.S_IMODE(logfile.stat().st_mode) == 0o600


def test_raw_short_writes_are_completed_without_losing_bytes():
    class ShortWriter(io.BytesIO):
        def write(self, raw):
            return super().write(raw[:3])

    raw = b"short write\nlast"
    displayed, retained = ShortWriter(), ShortWriter()
    console.copy_stream(io.BytesIO(raw), displayed, retained)
    assert displayed.getvalue() == retained.getvalue() == raw


@pytest.mark.parametrize("failure", ["input", "retained", "console", "flush", "retained-flush"])
def test_stream_io_errors_fail_without_claiming_completion(failure):
    class FailingInput:
        def read1(self, maximum):
            raise OSError("input failed")

    class FailingWrite(io.BytesIO):
        def write(self, raw):
            raise OSError("write failed")

    class FailingFlush(io.BytesIO):
        def flush(self):
            raise OSError("flush failed")

    source = FailingInput() if failure == "input" else io.BytesIO(b"original\n")
    retained = (FailingWrite() if failure == "retained" else
                FailingFlush() if failure == "retained-flush" else io.BytesIO())
    displayed = (FailingWrite() if failure == "console" else
                 FailingFlush() if failure == "flush" else io.BytesIO())
    with pytest.raises(OSError):
        console.copy_stream(source, displayed, retained)
    if failure in {"console", "flush", "retained-flush"}:
        assert retained.getvalue() == b"original\n"


def test_main_fails_on_input_error_and_retains_partial_create_only_log(tmp_path, monkeypatch):
    class InterruptedInput:
        def __init__(self):
            self.calls = 0

        def read1(self, maximum):
            self.calls += 1
            if self.calls == 1:
                return b"partial\n"
            raise OSError("private input failure")

    logfile = tmp_path / "pytest.log"
    displayed, errors = io.BytesIO(), io.StringIO()
    monkeypatch.setattr(console.sys, "stdin", SimpleNamespace(buffer=InterruptedInput()))
    monkeypatch.setattr(console.sys, "stdout", SimpleNamespace(buffer=displayed))
    monkeypatch.setattr(console.sys, "stderr", errors)
    assert console.main(["--log", str(logfile)]) == 1
    assert logfile.read_bytes() == displayed.getvalue() == b"partial\n"
    assert errors.getvalue() == "lunar-ci-console io failure\n"
    assert console.main(["--log", str(logfile)]) == 1
    assert logfile.read_bytes() == b"partial\n"


@pytest.mark.parametrize("existing", ["regular", "symlink"])
def test_cli_never_overwrites_existing_log_or_symlink_target(tmp_path, existing):
    original = tmp_path / "original"
    original.write_bytes(b"previous evidence\n")
    logfile = tmp_path / "pytest.log"
    if existing == "symlink":
        logfile.symlink_to(original)
    else:
        logfile.write_bytes(original.read_bytes())
    result = subprocess.run([sys.executable, str(SCRIPT), "--log", str(logfile)], input=b"replacement\n",
                            capture_output=True, check=False, timeout=20)
    assert result.returncode != 0
    assert result.stdout == b""
    assert result.stderr == b"lunar-ci-console io failure\n"
    assert original.read_bytes() == logfile.read_bytes() == b"previous evidence\n"


@pytest.mark.parametrize("exit_code", [0, 7])
def test_workflow_pipefail_preserves_upstream_failure_with_successful_logger(tmp_path, exit_code):
    logfile = tmp_path / "pytest.log"
    emitter = "import sys; print('original upstream result'); sys.exit(" + str(exit_code) + ")"
    pipeline = (
        shlex.join([sys.executable, "-c", emitter]) + " 2>&1 | "
        + shlex.join([sys.executable, str(SCRIPT), "--log", str(logfile)])
    )
    result = subprocess.run(["bash", "-o", "pipefail", "-c", pipeline],
                            capture_output=True, check=False, timeout=20)
    assert result.returncode == exit_code and result.stderr == b""
    assert result.stdout == logfile.read_bytes() == b"original upstream result\n"
