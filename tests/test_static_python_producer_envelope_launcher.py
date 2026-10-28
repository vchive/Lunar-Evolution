"""Compile the actual v2 C launcher against explicitly inert Python C API stubs.

Real process/pipe/argv/clock syscalls are exercised. There is no CPython runtime,
solver, model, candidate execution, sealed image or accepted native acquisition.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_MANIFEST = "a" * 64
_FINGERPRINT = "f" * 64
_RUN = "launch-run.42"
_ARGUMENTS = ("--lunar-fixed-producer-envelope-v1", _RUN, _FINGERPRINT,
              "--lunar-rsi-input-v1", _MANIFEST)

_HEADER = r"""
#ifndef PYTHON_H
#define PYTHON_H
#include <stddef.h>
typedef ptrdiff_t Py_ssize_t;
typedef struct { int unused; } PyStatus;
typedef struct { int unused; } PyPreConfig;
typedef struct { int unused; } PyConfig;
typedef struct { const char *text; unsigned long long number; } PyObject;
PyStatus PyStatus_Ok(void);
int PyStatus_Exception(PyStatus);
void Py_ExitStatusException(PyStatus);
PyStatus Py_PreInitialize(PyPreConfig *);
PyStatus Py_InitializeFromConfig(const PyConfig *);
void PyConfig_Clear(PyConfig *);
PyObject *PyImport_ImportModule(const char *);
PyObject *PyObject_GetAttrString(PyObject *, const char *);
PyObject *PyUnicode_FromString(const char *);
PyObject *PyLong_FromUnsignedLongLong(unsigned long long);
PyObject *PyObject_CallOneArg(PyObject *, PyObject *);
PyObject *PyObject_CallFunctionObjArgs(PyObject *, ...);
int PyBytes_CheckExact(PyObject *);
int PyBytes_AsStringAndSize(PyObject *, char **, Py_ssize_t *);
void PyErr_Print(void);
int Py_FinalizeEx(void);
#define Py_XDECREF(value) ((void)(value))
#endif
"""

_RUNTIME = r"""
#define _POSIX_C_SOURCE 200809L
#include "Python.h"
#include "lunar_fixture_profile.h"
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static PyObject module = {"_lunar_static_main", 0};
static PyObject collector = {"_lunar_collect_live_modules", 0};
static PyObject callable = {"_rsi_launch", 0};
static PyObject result = {"inert-result", 0};
static PyObject captured = {"inert-capture", 0};
static PyObject unicode_values[3];
static PyObject number;
static int unicode_count, live_closes, completion_closes;
static char startup[128];

int lunar_test_close(int fd) {
    if (fd == 198) ++live_closes;
    if (fd == 197) ++completion_closes;
    return close(fd);
}
static int closed(int fd) {
    errno = 0;
    return fcntl(fd, F_GETFD) == -1 && errno == EBADF;
}
static int pipe_writer(int fd) {
    struct stat info;
    int flags = fcntl(fd, F_GETFL);
    return flags >= 0 && (flags & O_ACCMODE) == O_WRONLY &&
        (flags & O_NONBLOCK) && !fstat(fd, &info) && S_ISFIFO(info.st_mode);
}
PyStatus PyStatus_Ok(void) { return (PyStatus){0}; }
int PyStatus_Exception(PyStatus value) { (void)value; return 0; }
void Py_ExitStatusException(PyStatus value) { (void)value; exit(90); }
PyStatus lunar_preconfig(PyPreConfig *config) {
    (void)config;
    if (getenv("LUNAR_FIXED_LIVE_DEADLINE_NS") ||
        getenv("LUNAR_FIXED_COMPLETION_DEADLINE_NS")) exit(91);
    if (!pipe_writer(197) || !pipe_writer(198)) exit(92);
    puts("PRECONFIG"); return PyStatus_Ok();
}
PyStatus lunar_config(PyConfig *config) {
    (void)config; puts("CONFIG"); return PyStatus_Ok();
}
PyStatus Py_PreInitialize(PyPreConfig *config) {
    (void)config; puts("PREINIT"); return PyStatus_Ok();
}
PyStatus Py_InitializeFromConfig(const PyConfig *config) {
    (void)config; puts("INIT"); return PyStatus_Ok();
}
void PyConfig_Clear(PyConfig *config) { (void)config; }
PyObject *PyImport_ImportModule(const char *name) {
    if (strcmp(name, module.text)) exit(93);
    return &module;
}
PyObject *PyObject_GetAttrString(PyObject *value, const char *name) {
    if (value != &module) exit(94);
    if (!strcmp(name, collector.text)) return &collector;
    if (strcmp(name, callable.text)) exit(95);
    if (!closed(198) || live_closes != 1 || completion_closes != 0 || !pipe_writer(197)) exit(96);
    return &callable;
}
PyObject *PyUnicode_FromString(const char *value) {
    if (unicode_count >= 3) exit(97);
    unicode_values[unicode_count].text = value;
    return &unicode_values[unicode_count++];
}
PyObject *PyLong_FromUnsignedLongLong(unsigned long long value) {
    number.number = value; return &number;
}
PyObject *PyObject_CallOneArg(PyObject *function, PyObject *argument) {
    if (function != &collector || argument != &unicode_values[0]) exit(98);
    if (!pipe_writer(197) || !pipe_writer(198) || live_closes || completion_closes) exit(99);
    int size = snprintf(startup, sizeof(startup), "STARTUP:%s\n", argument->text);
    if (size <= 0 || (size_t)size >= sizeof(startup)) exit(100);
    printf("COLLECT:%s\n", argument->text);
    return &captured;
}
int PyBytes_CheckExact(PyObject *value) { return value == &captured; }
int PyBytes_AsStringAndSize(PyObject *value, char **raw, Py_ssize_t *length) {
    if (value != &captured) return -1;
    *raw = startup; *length = (Py_ssize_t)strlen(startup); return 0;
}
PyObject *PyObject_CallFunctionObjArgs(PyObject *function, ...) {
    va_list arguments;
    va_start(arguments, function);
    PyObject *manifest = va_arg(arguments, PyObject *);
    PyObject *deadline = va_arg(arguments, PyObject *);
    PyObject *run_id = va_arg(arguments, PyObject *);
    PyObject *fingerprint = va_arg(arguments, PyObject *);
    PyObject *end = va_arg(arguments, PyObject *);
    va_end(arguments);
    if (function != &callable || manifest != &unicode_values[0] || deadline != &number ||
        run_id != &unicode_values[1] || fingerprint != &unicode_values[2] || end) exit(101);
    if (!closed(198) || live_closes != 1 || completion_closes || !pipe_writer(197)) exit(102);
    const char *expected = getenv("INERT_EXPECTED_DEADLINE");
    if (!expected || deadline->number != strtoull(expected, NULL, 10)) exit(103);
    char observed[128];
    size_t used = 0;
    for (;;) {
        ssize_t count = read(196, observed + used, sizeof(observed) - used);
        if (count == 0) break; /* Original startup writer EOF before this call. */
        if (count < 0 || used + (size_t)count >= sizeof(observed)) exit(104);
        used += (size_t)count;
    }
    if (used != strlen(startup) || memcmp(observed, startup, used)) exit(105);
    printf("STARTUP_EOF:%s\n", manifest->text);
    printf("CALL:%s:%llu:%s:%s\n", manifest->text, deadline->number, run_id->text, fingerprint->text);
    if (write(197, "BORROWED197\n", 12) != 12) exit(106);
    if (getenv("INERT_CALLBACK_FAILURE")) return NULL;
    return &result; /* The inert callable never closes its borrowed writer. */
}
void PyErr_Print(void) {
    if (!closed(197) || completion_closes != 1) exit(107);
    puts("PYERR");
}
int Py_FinalizeEx(void) {
    if (!closed(197) || !closed(198) || completion_closes != 1 || live_closes != 1) exit(108);
    close(196);
    puts("FINALIZE:close198=1:close197=1"); return 0;
}
"""

# Only this test launcher wrapper owns the extra read handle on FD196. The real
# native closure does not gain this capability. The handshake closes the parent's
# source writers before exec, making the startup EOF assertion deterministic.
_EXEC = r"""
import fcntl, json, os, sys
launcher, raw_fds, mode, raw_arguments = sys.argv[1:]
original = tuple(map(int, json.loads(raw_fds)))
copied = [fcntl.fcntl(fd, fcntl.F_DUPFD_CLOEXEC, 300) for fd in original]
for fd in set(original):
    os.close(fd)
startup_read, startup_write, completion_read, completion_write = copied
os.dup2(startup_read, 196)
if mode != 'missing-startup':
    os.dup2(startup_read if mode == 'read-startup' else startup_write, 198)
if mode != 'missing-completion':
    if mode == 'regular-completion':
        temporary = os.open(os.devnull, os.O_WRONLY)
        os.dup2(temporary, 197)
        os.close(temporary)
    else:
        os.dup2(completion_read if mode == 'read-completion' else completion_write, 197)
for fd in copied:
    os.close(fd)
os.set_blocking(196, False)
if mode != 'missing-startup':
    os.set_blocking(198, mode == 'blocking-startup')
if mode != 'missing-completion':
    os.set_blocking(197, mode == 'blocking-completion')
if os.read(0, 1) != b'x':
    raise SystemExit(109)
os.execve(launcher, [launcher, *json.loads(raw_arguments)], os.environ)
"""


@pytest.fixture(scope="module")
def inert_envelope_launcher(tmp_path_factory):
    compiler = shutil.which("cc")
    if compiler is None:
        pytest.skip("inert C API launcher probe requires a C compiler")
    directory = tmp_path_factory.mktemp("inert-envelope-launcher")
    (directory / "Python.h").write_text(_HEADER, encoding="ascii")
    (directory / "lunar_fixture_profile.h").write_bytes(
        (_ROOT / "tools/static_python_fixture/assets/lunar_fixture_profile.h").read_bytes(),
    )
    runtime = directory / "inert-runtime.c"
    runtime.write_text(_RUNTIME, encoding="ascii")
    source = _ROOT / "tools/static_python_rsi_fixture/assets/launcher_producer_envelope.c"
    object_file = directory / "actual-launcher.o"
    executable = directory / "inert-envelope-probe"
    for command in (
        [compiler, "-std=c99", "-Wall", "-Wextra", "-Werror", "-I", str(directory),
         "-Dclose=lunar_test_close", "-c", str(source), "-o", str(object_file)],
        [compiler, "-std=c99", "-Wall", "-Wextra", "-Werror", "-I", str(directory),
         str(runtime), str(object_file), "-o", str(executable)],
    ):
        completed = subprocess.run(command, capture_output=True, timeout=30, check=False)
        assert completed.returncode == 0, completed.stderr.decode("utf-8", errors="replace")
    return executable


def _probe(executable, arguments=_ARGUMENTS, *, mode="valid", deadlines=None, callback_failure=False):
    startup_read, startup_write = os.pipe()
    completion_read, completion_write = os.pipe()
    descriptors = (startup_read, startup_write, completion_read, completion_write)
    deadline = time.monotonic_ns() + 10_000_000_000
    environment = {
        "PATH": os.defpath, "LANG": "C", "LUNAR_FIXED_LIVE_DEADLINE_NS": str(deadline),
        "LUNAR_FIXED_COMPLETION_DEADLINE_NS": str(deadline), "INERT_EXPECTED_DEADLINE": str(deadline),
    }
    for key, value in (deadlines or {}).items():
        if value is None:
            environment.pop(key, None)
        else:
            environment[key] = value
    if callback_failure:
        environment["INERT_CALLBACK_FAILURE"] = "1"
    process = None
    try:
        process = subprocess.Popen(
            [sys.executable, "-c", _EXEC, str(executable), json.dumps(descriptors), mode,
             json.dumps(arguments)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            pass_fds=descriptors, env=environment,
        )
        os.close(startup_write)
        os.close(completion_write)
        startup_write = completion_write = -1
        stdout, stderr = process.communicate(input=b"x", timeout=5)
        # No source writer remains in the parent/wrapper: these reads must EOF.
        os.set_blocking(startup_read, False)
        os.set_blocking(completion_read, False)
        return process.returncode, stdout, stderr, os.read(startup_read, 4096), os.read(completion_read, 4096), deadline
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.communicate(timeout=5)
        for descriptor in (startup_read, startup_write, completion_read, completion_write):
            if descriptor >= 0:
                os.close(descriptor)


@pytest.mark.parametrize("arguments", [
    (), _ARGUMENTS[:-1], (*_ARGUMENTS, "extra"),
    ("--wrong-profile", *_ARGUMENTS[1:]),
    (_ARGUMENTS[0], "", *_ARGUMENTS[2:]),
    (_ARGUMENTS[0], "../run", *_ARGUMENTS[2:]),
    (_ARGUMENTS[0], "x" * 129, *_ARGUMENTS[2:]),
    (_ARGUMENTS[0], "secret=value", *_ARGUMENTS[2:]),
    (_ARGUMENTS[0], "é", *_ARGUMENTS[2:]),
    (*_ARGUMENTS[:2], "F" * 64, *_ARGUMENTS[3:]),
    (*_ARGUMENTS[:2], "f" * 63, *_ARGUMENTS[3:]),
    (*_ARGUMENTS[:3], "--wrong-input", _MANIFEST),
    (*_ARGUMENTS[:-1], "a" * 65), (*_ARGUMENTS[:-1], "g" * 64),
])
def test_actual_c_launcher_refuses_nonexact_argv_before_inert_runtime(inert_envelope_launcher, arguments):
    code, stdout, stderr, startup, completion, _deadline = _probe(inert_envelope_launcher, arguments)
    assert code == 64
    assert stdout == stderr == startup == completion == b""


@pytest.mark.parametrize("run_id", [_RUN, "r", "R" + "x" * 127])
def test_actual_c_forwards_manifest_deadline_run_fingerprint_and_owns_pipe_closes(inert_envelope_launcher, run_id):
    arguments = (_ARGUMENTS[0], run_id, *_ARGUMENTS[2:])
    code, stdout, stderr, startup, completion, deadline = _probe(inert_envelope_launcher, arguments)
    assert code == 0 and stderr == startup == b""
    assert completion == b"BORROWED197\n"
    assert stdout.decode("ascii").splitlines() == [
        "PRECONFIG", "PREINIT", "CONFIG", "INIT", f"COLLECT:{_MANIFEST}",
        f"STARTUP_EOF:{_MANIFEST}", f"CALL:{_MANIFEST}:{deadline}:{run_id}:{_FINGERPRINT}",
        "FINALIZE:close198=1:close197=1",
    ]


@pytest.mark.parametrize("mode", [
    "missing-startup", "missing-completion", "read-startup", "read-completion",
    "blocking-startup", "blocking-completion", "regular-completion",
])
def test_actual_c_requires_both_nonblocking_private_pipe_writers(inert_envelope_launcher, mode):
    code, stdout, stderr, startup, completion, _deadline = _probe(inert_envelope_launcher, mode=mode)
    assert code == 64
    assert stdout == stderr == startup == completion == b""


@pytest.mark.parametrize("name", ["LUNAR_FIXED_LIVE_DEADLINE_NS", "LUNAR_FIXED_COMPLETION_DEADLINE_NS"])
@pytest.mark.parametrize("value", [None, "", "0", "01", "-1", "not-a-number", "18446744073709551616", "1"])
def test_actual_c_refuses_missing_invalid_expired_or_different_original_deadlines(
    inert_envelope_launcher, name, value,
):
    code, stdout, stderr, startup, completion, _deadline = _probe(
        inert_envelope_launcher, deadlines={name: value},
    )
    assert code == 64
    assert stdout == stderr == startup == completion == b""


def test_actual_c_refuses_two_distinct_future_deadlines_before_initialization(inert_envelope_launcher):
    future = time.monotonic_ns() + 60_000_000_000
    code, stdout, stderr, startup, completion, _deadline = _probe(
        inert_envelope_launcher,
        deadlines={"LUNAR_FIXED_LIVE_DEADLINE_NS": str(future),
                   "LUNAR_FIXED_COMPLETION_DEADLINE_NS": str(future + 1)},
    )
    assert code == 64
    assert stdout == stderr == startup == completion == b""


def test_actual_c_closes_borrowed_completion_writer_before_error_reporting(inert_envelope_launcher):
    code, stdout, stderr, startup, completion, _deadline = _probe(inert_envelope_launcher, callback_failure=True)
    assert code == 1 and stderr == startup == b"" and completion == b"BORROWED197\n"
    assert stdout.decode("ascii").splitlines()[-2:] == ["PYERR", "FINALIZE:close198=1:close197=1"]
