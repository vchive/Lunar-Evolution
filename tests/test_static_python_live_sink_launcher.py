"""Compile the reviewed C launcher against an inert fake Python API only."""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from test_static_python_rsi_launch import _FAKE_HEADER

ROOT = Path(__file__).parents[1]
_RUNTIME = r'''
#define _POSIX_C_SOURCE 200809L
#include "Python.h"
#include "lunar_fixture_profile.h"
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
static PyObject module = {"main"}, collector = {"collector"}, solver = {"solver"};
static PyObject argument, captured = {"private\n"}, result = {"result"};
PyStatus PyStatus_Ok(void) { return (PyStatus){0}; }
int PyStatus_Exception(PyStatus s) { (void)s; return 0; }
void Py_ExitStatusException(PyStatus s) { (void)s; exit(90); }
PyStatus lunar_preconfig(PyPreConfig *c) { (void)c; return PyStatus_Ok(); }
PyStatus lunar_config(PyConfig *c) { (void)c; return PyStatus_Ok(); }
PyStatus Py_PreInitialize(PyPreConfig *c) { (void)c; return PyStatus_Ok(); }
PyStatus Py_InitializeFromConfig(const PyConfig *c) { (void)c; puts("INIT"); return PyStatus_Ok(); }
void PyConfig_Clear(PyConfig *c) { (void)c; }
PyObject *PyImport_ImportModule(const char *name) {
    if (strcmp(name, "_lunar_static_main")) exit(91);
    return &module;
}
PyObject *PyObject_GetAttrString(PyObject *m, const char *name) {
    if (m != &module) exit(92);
    if (!strcmp(name, "_lunar_collect_live_modules")) { puts("COLLECTOR"); return &collector; }
    if (strcmp(name, "_rsi_launch")) exit(93);
    errno = 0;
    if (fcntl(198, F_GETFD) != -1 || errno != EBADF) exit(94);
    puts("SOLVER_AFTER_CLOSE"); return &solver;
}
PyObject *PyUnicode_FromString(const char *text) { argument.text = text; return &argument; }
PyObject *PyObject_CallOneArg(PyObject *f, PyObject *a) {
    if (a != &argument || strlen(a->text) != 64) exit(95);
    if (f == &collector) return &captured;
    if (f != &solver) exit(96);
    puts("SOLVER_CALLED"); return &result;
}
int PyBytes_CheckExact(PyObject *value) { return value == &captured && !getenv("FIXTURE_BAD_BYTES"); }
int PyBytes_AsStringAndSize(PyObject *value, char **raw, Py_ssize_t *size) {
    if (value != &captured) return -1;
    *raw = (char *)value->text; *size = (Py_ssize_t)strlen(value->text); return 0;
}
void PyErr_Print(void) { puts("PYERR"); }
int Py_FinalizeEx(void) { puts("FINALIZE"); return 0; }
int lunar_sink_main(int argc, char **argv);
int main(int argc, char **argv) {
    const char *fd_text = getenv("FIXTURE_SINK_FD");
    if (!fd_text) return 97;
    int original = atoi(fd_text);
    if (dup2(original, 198) < 0) return 98;
    if (original != 198) close(original);
    int flags = fcntl(198, F_GETFL);
    if (flags < 0 || fcntl(198, F_SETFL, flags | O_NONBLOCK)) return 99;
    return lunar_sink_main(argc, argv);
}
'''


@pytest.fixture(scope="module")
def live_launcher_probe(tmp_path_factory):
    compiler = shutil.which("cc")
    if compiler is None:
        pytest.skip("test-only C compiler unavailable")
    staging = tmp_path_factory.mktemp("live-launcher-fake-runtime")
    header = _FAKE_HEADER.replace("#endif", """typedef long Py_ssize_t;
int PyBytes_CheckExact(PyObject *);
int PyBytes_AsStringAndSize(PyObject *, char **, Py_ssize_t *);
#endif""")
    (staging / "Python.h").write_text(header)
    (staging / "lunar_fixture_profile.h").write_bytes(
        (ROOT / "tools/static_python_fixture/assets/lunar_fixture_profile.h").read_bytes(),
    )
    source = (ROOT / "tools/static_python_rsi_fixture/assets/launcher_live_sink.c").read_text()
    (staging / "launcher.c").write_text(source.replace("int main(int argc", "int lunar_sink_main(int argc"))
    (staging / "runtime.c").write_text(_RUNTIME)
    output = staging / "probe"
    result = subprocess.run(
        [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", str(staging),
         str(staging / "launcher.c"), str(staging / "runtime.c"), "-o", str(output)],
        capture_output=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    return output


@pytest.mark.parametrize("fault", [None, "bad-result", "expired", "no-deadline", "bad-marker"])
def test_in_image_call_completes_private_write_and_close_before_solver(live_launcher_probe, fault):
    read_fd, write_fd = os.pipe()
    try:
        # The fake C runtime samples CLOCK_MONOTONIC explicitly. On Darwin,
        # Python's monotonic clock can use a different epoch.
        env = {"PATH": os.defpath, "FIXTURE_SINK_FD": str(write_fd),
               "LUNAR_FIXED_LIVE_DEADLINE_NS": str(time.clock_gettime_ns(time.CLOCK_MONOTONIC) + 3_000_000_000)}
        if fault == "bad-result":
            env["FIXTURE_BAD_BYTES"] = "1"
        elif fault == "expired":
            env["LUNAR_FIXED_LIVE_DEADLINE_NS"] = "1"
        elif fault == "no-deadline":
            env.pop("LUNAR_FIXED_LIVE_DEADLINE_NS")
        result = subprocess.run(
            [str(live_launcher_probe), "wrong" if fault == "bad-marker" else "--lunar-rsi-input-v1", "a" * 64],
            pass_fds=(write_fd,), close_fds=True, env=env, capture_output=True, timeout=4, check=False,
        )
        os.close(write_fd)
        write_fd = -1
        raw = os.read(read_fd, 128)
        assert os.read(read_fd, 1) == b"" and result.stderr == b""
        if fault is None:
            assert result.returncode == 0 and raw == b"private\n"
            assert result.stdout.splitlines() == [b"INIT", b"COLLECTOR", b"SOLVER_AFTER_CLOSE", b"SOLVER_CALLED", b"FINALIZE"]
        else:
            assert result.returncode == (1 if fault == "bad-result" else 64)
            assert raw == b"" and b"SOLVER" not in result.stdout
    finally:
        if write_fd >= 0:
            os.close(write_fd)
        os.close(read_fd)
