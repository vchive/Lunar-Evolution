"""Bounded same-process Python frame observations, with honest terminal status.

This API never launches a case, imports a producer, or observes another process.
An explicit caller owns any outer process deadline. Bounds here are cooperative:
an unreturned Python/OS operation can outlive them. A bounded finish then reports
writer_running/unknown, never a successful stop. No locals/globals, argv, env,
thread names, raw thread IDs, source lines or unapproved filenames are emitted.
"""

from __future__ import annotations

import json
import math
import os
import re
import sys
import threading
import time
from pathlib import PurePosixPath

_CURRENT_FRAMES = sys._current_frames
_MAX_SECONDS = 180.0
_MAX_SAMPLES = 721
_MAX_THREADS = 32
_MAX_DEPTH = 64
_MAX_FRAMES = 128
_MAX_SLOTS = 64
_MAX_RECORD_BYTES = 128 * 1024
_MAX_TOTAL_BYTES = 8 * 1024 * 1024
_RESERVED_END_BYTES = 1024
_FUNCTION = re.compile(r"[A-Za-z0-9_.<>]{1,96}\Z")
_STDLIB_FILES = frozenset({
    "_collections_abc.py", "_pydecimal.py", "abc.py", "ast.py", "base64.py",
    "bisect.py", "codecs.py", "collections/__init__.py", "collections/abc.py",
    "contextlib.py", "contextvars.py", "copy.py", "copyreg.py", "dataclasses.py",
    "decimal.py", "encodings/utf_8.py", "enum.py", "fractions.py", "functools.py",
    "genericpath.py", "hashlib.py", "heapq.py", "importlib/__init__.py",
    "importlib/_bootstrap.py", "importlib/_bootstrap_external.py", "importlib/util.py",
    "inspect.py", "io.py", "json/__init__.py", "json/decoder.py", "json/encoder.py",
    "json/scanner.py", "linecache.py", "logging/__init__.py", "logging/config.py",
    "logging/handlers.py", "ntpath.py", "os.py", "pathlib.py", "pickle.py",
    "posixpath.py", "queue.py", "random.py", "re/__init__.py", "re/_compiler.py",
    "re/_constants.py", "re/_parser.py", "runpy.py", "selectors.py", "shutil.py",
    "signal.py", "socket.py", "sqlite3/__init__.py", "sqlite3/dbapi2.py",
    "stat.py", "string.py", "struct.py", "subprocess.py", "tempfile.py",
    "textwrap.py", "threading.py", "token.py", "tokenize.py", "traceback.py",
    "types.py", "typing.py", "warnings.py", "weakref.py",
})


class DiagnosticError(ValueError):
    """Fixed code without paths, observations or underlying exception content."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def checked_allowlist(value: object) -> frozenset[str]:
    if type(value) not in (list, tuple, frozenset) or not 1 <= len(value) <= 4096:
        raise DiagnosticError("allowlist_invalid")
    result = set()
    for name in value:
        if (type(name) is not str or len(name) > 512 or not name.endswith(".py")
                or "\\" in name or any(character in name for character in "\x00\r\n")
                or any(part in {"", ".", ".."} for part in name.split("/"))):
            raise DiagnosticError("allowlist_invalid")
        try:
            if len(name.encode("utf-8")) > 512:
                raise DiagnosticError("allowlist_invalid")
        except UnicodeError:
            raise DiagnosticError("allowlist_invalid") from None
        result.add(name)
    if len(result) != len(value):
        raise DiagnosticError("allowlist_invalid")
    return frozenset(result)


def _checked_root(value: object) -> str:
    if (type(value) is not str or len(value) > 4096 or not value.startswith("/")
            or value.startswith("//") or "\\" in value
            or any(character in value for character in "\x00\r\n")
            or ".." in value.split("/") or str(PurePosixPath(value)) != value):
        raise DiagnosticError("root_invalid")
    try:
        if len(value.encode("utf-8")) > 4096:
            raise DiagnosticError("root_invalid")
    except UnicodeError:
        raise DiagnosticError("root_invalid") from None
    return value.rstrip("/") + "/"


class StackSampler:
    """One owner and one daemon writer; use start(), then bounded finish()."""

    def __init__(self, source_root, allowed, output, *, stdlib_root,
                 seconds=180.0, interval=0.5):
        self.prefix = _checked_root(source_root)
        self.stdlib_prefix = _checked_root(stdlib_root)
        self.allowed = checked_allowlist(allowed)
        if type(seconds) not in (int, float) or not 0 < seconds <= _MAX_SECONDS:
            raise DiagnosticError("duration_invalid")
        if type(interval) not in (int, float) or interval not in (0.25, 0.5):
            raise DiagnosticError("interval_invalid")
        self.seconds = seconds
        self.interval = interval
        self.max_samples = min(_MAX_SAMPLES, math.ceil(seconds / interval) + 1)
        self.main_ident = threading.get_ident()
        self.slots = {self.main_ident: 0}
        self.origin = time.monotonic()
        self.stop = threading.Event()
        self.bytes_written = 0
        self.line_incomplete = False
        self.samples_observed = 0
        self.samples_written = 0
        self.reason = "not_started"
        self.terminal_status = "pending"
        self.started = False
        self.fd = None
        try:
            self.fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                              | os.O_CLOEXEC | os.O_NOFOLLOW, 0o600)
        except OSError:
            raise DiagnosticError("output_unavailable") from None
        try:
            os.fchmod(self.fd, 0o600)
            self.thread = threading.Thread(target=self._run, daemon=True)
            if not self._write({
                "event": "start", "monotonic_seconds": 0.0, "diagnostic_only": True,
                "protocol": "lunar-own-python-stack-diagnostic-v2",
                "interval_seconds": interval, "max_seconds": seconds,
                "max_samples": self.max_samples, "max_threads_per_sample": _MAX_THREADS,
                "max_depth_per_thread": _MAX_DEPTH, "max_frames_per_sample": _MAX_FRAMES,
                "max_record_bytes": _MAX_RECORD_BYTES, "max_total_bytes": _MAX_TOTAL_BYTES,
            }):
                raise DiagnosticError("initialization_failed")
        except BaseException:  # noqa: BLE001 - close owned output on interrupted initialization.
            try:
                os.close(self.fd)
            except OSError:
                pass
            finally:
                self.fd = None
            raise DiagnosticError("initialization_failed") from None

    def _elapsed(self):
        value = time.monotonic() - self.origin
        if type(value) not in (int, float) or not math.isfinite(value):
            raise DiagnosticError("clock_invalid")
        return max(0.0, value)

    def _write(self, record, *, final=False):
        if self.line_incomplete:
            raise DiagnosticError("line_incomplete")
        raw = (json.dumps(record, ensure_ascii=True, separators=(",", ":"))
               + "\n").encode("utf-8")
        ceiling = _MAX_TOTAL_BYTES if final else _MAX_TOTAL_BYTES - _RESERVED_END_BYTES
        if len(raw) > _MAX_RECORD_BYTES or self.bytes_written + len(raw) > ceiling:
            if not final:
                self.reason = ("record_byte_limit" if len(raw) > _MAX_RECORD_BYTES
                               else "total_byte_limit")
            return False
        remaining = memoryview(raw)
        while remaining:
            written = os.write(self.fd, remaining)
            if written <= 0:
                raise DiagnosticError("write_incomplete")
            self.bytes_written += written
            remaining = remaining[written:]
            self.line_incomplete = bool(remaining)
        os.fsync(self.fd)
        return True

    def start(self):
        if self.started or self.fd is None:
            raise DiagnosticError("state_invalid")
        self.started = True
        try:
            self.thread.start()
        except BaseException:  # noqa: BLE001 - retain a terminal when thread startup is interrupted.
            self.started = False
            self._complete("start_error")
            raise DiagnosticError("start_failed") from None

    def _sample(self, sample_index):
        snapshot = _CURRENT_FRAMES()
        frame = code = None
        threads, frame_count = [], 0
        try:
            ordered = sorted(snapshot)
            if self.main_ident in snapshot:
                ordered.remove(self.main_ident)
                ordered.insert(0, self.main_ident)
            for ident in ordered[:_MAX_THREADS]:
                if ident not in self.slots:
                    if len(self.slots) >= _MAX_SLOTS:
                        continue
                    self.slots[ident] = len(self.slots)
                classification = ("main" if ident == self.main_ident else
                                  "sampler" if ident == self.thread.ident else "worker")
                frame, depth, unlisted = snapshot[ident], 0, 0
                frames = []
                while frame is not None and depth < _MAX_DEPTH:
                    depth += 1
                    code = frame.f_code
                    filename, function = code.co_filename, code.co_name
                    scope, relative, permitted = None, None, False
                    if type(filename) is str:
                        if filename.startswith(self.prefix):
                            scope, relative = "source", filename[len(self.prefix):]
                            permitted = relative in self.allowed
                        elif filename.startswith(self.stdlib_prefix):
                            scope, relative = "stdlib", filename[len(self.stdlib_prefix):]
                            permitted = relative in _STDLIB_FILES
                    line = frame.f_lineno
                    if (permitted and type(function) is str and _FUNCTION.fullmatch(function)
                            and type(line) is int and 0 <= line <= 2**31 - 1
                            and frame_count < _MAX_FRAMES):
                        frames.append({"scope": scope, "file": relative,
                                       "function": function, "line": line})
                        frame_count += 1
                    else:
                        unlisted += 1
                    frame = frame.f_back
                threads.append({"slot": self.slots[ident], "class": classification,
                                "frames": frames, "unlisted_or_capped_frames": unlisted,
                                "depth_capped": frame is not None})
            return {"event": "sample", "sample": sample_index,
                    "monotonic_seconds": self._elapsed(), "threads": threads,
                    "threads_omitted": max(0, len(snapshot) - len(threads)),
                    "frames_recorded": frame_count}
        finally:
            # Release thread object graphs even when metadata observation fails.
            frame = code = None
            snapshot.clear()

    def _complete(self, reason):
        self.reason = reason
        try:
            written = self._write({
                "event": "stop", "reason": reason, "monotonic_seconds": self._elapsed(),
                "samples_observed": self.samples_observed, "samples_written": self.samples_written,
            }, final=True)
            self.terminal_status = "written" if written else "write_unknown"
        except BaseException:  # noqa: BLE001 - terminal write interruption must remain unknown.
            self.terminal_status = "write_unknown"
        finally:
            try:
                if self.fd is not None:
                    os.close(self.fd)
            except OSError:
                pass
            self.fd = None

    def _run(self):
        self.reason = "running"
        stage = "observation"
        try:
            for index in range(self.max_samples):
                stage = "observation"
                if self.stop.is_set():
                    self.reason = "main_completed"
                    break
                if self._elapsed() >= self.seconds:
                    self.reason = "duration_limit"
                    break
                record = self._sample(index)
                self.samples_observed += 1
                stage = "output"
                if not self._write(record):
                    break
                self.samples_written += 1
                stage = "wait"
                # Delayed GIL access never creates a catch-up sampling burst.
                self.stop.wait(self.interval)
            else:
                self.reason = "sample_limit"
        except Exception:  # noqa: BLE001 - expose a fixed stage code, never raw frame/error data.
            self.reason = {"observation": "observation_error", "output": "output_error",
                           "wait": "sampler_error"}[stage]
        except BaseException:  # noqa: BLE001 - record interruption separately from observation errors.
            self.reason = "sampler_interrupted"
        finally:
            self._complete(self.reason)

    def finish(self):
        """Stop cooperatively; never close a file still owned by a live writer."""
        self.stop.set()
        if not self.started and self.fd is not None:
            self._complete("not_started")
        elif self.started:
            self.thread.join(timeout=0.5)
        alive = self.started and self.thread.is_alive()
        return {"writer_running": alive,
                "terminal_status": "unknown" if alive else self.terminal_status,
                "reason": "writer_running" if alive else self.reason,
                "samples_observed": self.samples_observed, "samples_written": self.samples_written}
