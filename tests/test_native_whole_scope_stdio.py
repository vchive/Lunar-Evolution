"""Actual v4 inherited stream gates; no installed scope or candidate is run."""
from __future__ import annotations

import platform
import shutil
import subprocess
import sys

import pytest

from lunar_evolution.native_bootstrap import native_bootstrap_source_paths

_HARNESS = r'''
#define main installed_bootstrap_main
#include "native_bootstrap.c"
#undef main
#include <assert.h>

static void replace(int slot, int fd) {
    assert(fd > 2); assert(dup2(fd, slot) == slot); assert(!close(fd));
}
static void flag(int fd, int value) {
    int old = fcntl(fd, F_GETFL); assert(old >= 0);
    assert(!fcntl(fd, F_SETFL, old | value));
    assert((fcntl(fd, F_GETFL) & value) == value);
}
static int path_fd(int fd) {
    char path[64]; snprintf(path, sizeof(path), "/proc/self/fd/%d", fd);
    int result = open(path, O_PATH | O_CLOEXEC); assert(result > 2); return result;
}
static void mutate(int slot, const char *kind) {
    if (!strcmp(kind, "file")) replace(slot, open("file", O_RDWR | O_CREAT | O_EXCL | O_CLOEXEC, 0600));
    else if (!strcmp(kind, "directory")) replace(slot, open(".", O_RDONLY | O_DIRECTORY | O_CLOEXEC));
    else if (!strcmp(kind, "null")) replace(slot, open("/dev/null", O_RDWR | O_CLOEXEC));
    else if (!strcmp(kind, "zero")) replace(slot, open("/dev/zero", O_RDONLY | O_CLOEXEC));
    else if (!strcmp(kind, "null-write")) replace(slot, open("/dev/null", O_WRONLY | O_CLOEXEC));
    else if (!strcmp(kind, "path")) replace(slot, path_fd(slot));
    else if (!strcmp(kind, "async")) flag(slot, O_ASYNC);
    else if (!strcmp(kind, "nonblock")) flag(slot, O_NONBLOCK);
    else if (!strcmp(kind, "closed")) assert(!close(slot));
    else if (!strcmp(kind, "fifo")) {
        assert(!mkfifo("named-fifo", 0600));
        replace(slot, open("named-fifo", O_RDWR | O_NONBLOCK | O_CLOEXEC));
    } else if (!strcmp(kind, "socket")) {
        int pair[2]; assert(!socketpair(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0, pair));
        replace(slot, pair[0]); assert(!close(pair[1]));
    } else {
        int pair[2]; assert(!pipe2(pair, O_CLOEXEC | O_NONBLOCK));
        if (!strcmp(kind, "pipe-read")) { replace(slot, pair[0]); assert(!close(pair[1])); }
        else if (!strcmp(kind, "pipe-write")) { replace(slot, pair[1]); assert(!close(pair[0])); }
        else {
            assert(!strcmp(kind, "pipe-rdwr"));
            char path[64]; snprintf(path, sizeof(path), "/proc/self/fd/%d", pair[1]);
            int both = open(path, O_RDWR | O_CLOEXEC | O_NONBLOCK); assert(both > 2);
            replace(slot, both); assert(!close(pair[0])); assert(!close(pair[1]));
        }
    }
}
int main(int argc, char **argv) {
    assert(argc == 3);
    int roles[2] = {open("/dev/zero", O_RDONLY | O_CLOEXEC), -1};
    assert(roles[0] > 2);
    w4_b_stdio_t original;
    const char *kind = argv[2];
    if (!strcmp(argv[1], "normal")) {
        assert(!strcmp(kind, "read") || !strcmp(kind, "rdwr") || !strcmp(kind, "nonblock"));
        replace(0, open("/dev/null", (!strcmp(kind, "read") ? O_RDONLY : O_RDWR) | O_CLOEXEC));
        if (!strcmp(kind, "nonblock")) { flag(1, O_NONBLOCK); flag(2, O_NONBLOCK); }
        assert(!w4_b_stdio_acquire(&original, roles, 1));
        assert(!w4_b_stdio_check(&original, roles, 1));
    } else if (!strcmp(argv[1], "input")) {
        mutate(0, kind); assert(w4_b_stdio_acquire(&original, roles, 1));
    } else if (!strcmp(argv[1], "output1") || !strcmp(argv[1], "output2")) {
        mutate(argv[1][6] - '0', kind); assert(w4_b_stdio_acquire(&original, roles, 1));
    } else if (!strcmp(argv[1], "alias")) {
        if (!strcmp(kind, "outputs")) assert(dup2(1, 2) == 2);
        else if (!strcmp(kind, "opposite-end")) {
            int pair[2]; assert(!pipe2(pair, O_CLOEXEC));
            replace(1, pair[1]); roles[1] = pair[0];
        } else {
            int slot = kind[0] - '0'; assert(slot >= 0 && slot <= 2 && !kind[1]);
            roles[1] = dup(slot); assert(roles[1] > 2);
        }
        assert(w4_b_stdio_acquire(&original, roles, roles[1] < 0 ? 1 : 2));
    } else if (!strcmp(argv[1], "recheck")) {
        assert(!w4_b_stdio_acquire(&original, roles, 1));
        if (!strcmp(kind, "stdout-replaced")) mutate(1, "pipe-write");
        else if (!strcmp(kind, "stderr-replaced")) mutate(2, "pipe-write");
        else if (!strcmp(kind, "input-replaced")) mutate(0, "zero");
        else if (!strcmp(kind, "flags")) flag(1, O_NONBLOCK);
        else {
            assert(!strcmp(kind, "role-alias"));
            assert(dup2(1, roles[0]) == roles[0]);
        }
        assert(w4_b_stdio_check(&original, roles, 1));
    } else {
        assert(!strcmp(argv[1], "roles"));
        if (!strcmp(kind, "closed")) { assert(!close(roles[0])); assert(w4_b_stdio_acquire(&original, roles, 1)); }
        else if (!strcmp(kind, "standard")) { roles[0] = 0; assert(w4_b_stdio_acquire(&original, roles, 1)); }
        else if (!strcmp(kind, "empty")) assert(w4_b_stdio_acquire(&original, roles, 0));
        else { assert(!strcmp(kind, "null")); assert(w4_b_stdio_acquire(&original, NULL, 1)); }
    }
    return 0;
}
'''


@pytest.fixture(scope="module")
def stdio_harness(tmp_path_factory):
    if sys.platform != "linux" or platform.machine().lower() not in {"x86_64", "amd64"}:
        pytest.skip("actual Linux x86-64 standard stream objects")
    compiler = shutil.which("cc")
    if compiler is None:
        pytest.skip("C compiler is unavailable")
    root = tmp_path_factory.mktemp("whole-scope-stdio-harness")
    source, executable = root / "harness.c", root / "harness"
    source.write_text(_HARNESS)
    result = subprocess.run(
        [compiler, "-std=c11", "-O2", "-pthread", "-I",
         str(native_bootstrap_source_paths()[0].parent), str(source), "-o", str(executable)],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert result.returncode == 0, result.stderr
    return executable


def _case(executable, tmp_path, group, name):
    process = subprocess.run(
        [str(executable), group, name], stdin=subprocess.DEVNULL, capture_output=True,
        cwd=tmp_path, text=True, timeout=10, check=False,
    )
    assert process.returncode == 0, process.stderr
    assert not process.stdout and not process.stderr


@pytest.mark.parametrize("kind", ["read", "rdwr", "nonblock"])
def test_original_devnull_and_distinct_output_pipes_pass(stdio_harness, tmp_path, kind):
    _case(stdio_harness, tmp_path, "normal", kind)


@pytest.mark.parametrize("kind", [
    "file", "directory", "zero", "null-write", "path", "closed", "fifo", "socket", "pipe-read",
])
def test_unknown_or_writable_input_object_refuses(stdio_harness, tmp_path, kind):
    _case(stdio_harness, tmp_path, "input", kind)


@pytest.mark.parametrize("slot", [1, 2])
@pytest.mark.parametrize("kind", [
    "file", "directory", "null", "path", "async", "closed", "fifo", "socket", "pipe-read", "pipe-rdwr",
])
def test_each_output_requires_actual_write_only_anonymous_pipe(stdio_harness, tmp_path, slot, kind):
    _case(stdio_harness, tmp_path, "output" + str(slot), kind)


@pytest.mark.parametrize("kind", ["outputs", "0", "1", "2", "opposite-end"])
def test_stream_objects_cannot_overlap_each_other_or_retained_original_roles(stdio_harness, tmp_path, kind):
    _case(stdio_harness, tmp_path, "alias", kind)


@pytest.mark.parametrize("kind", ["stdout-replaced", "stderr-replaced", "input-replaced", "flags", "role-alias"])
def test_ready_boundary_rechecks_original_objects_flags_and_role_relationships(stdio_harness, tmp_path, kind):
    _case(stdio_harness, tmp_path, "recheck", kind)


@pytest.mark.parametrize("kind", ["closed", "standard", "empty", "null"])
def test_retained_role_acquisition_cannot_use_unobserved_descriptors(stdio_harness, tmp_path, kind):
    _case(stdio_harness, tmp_path, "roles", kind)


def test_stdio_gate_is_bound_to_both_original_v4_child_boundaries_only():
    root = native_bootstrap_source_paths()[0].parent
    source = (root / "native_whole_scope_successor_bootstrap.h").read_text()
    child = source.split("static _Noreturn void w4_b_child(", 1)[1].split("static int w4_bootstrap_main(", 1)[0]
    acquire = child.index("w4_b_stdio_acquire(&original_stdio, keep, count)")
    drop = child.index("wq_b_drop_credentials(profile)")
    check = child.index("w4_b_stdio_check(&original_stdio, keep, count)")
    ready = child.index("unsigned char ready = 'R'")
    assert acquire < drop < check < ready
    assert child.count("w4_b_stdio_acquire(") == child.count("w4_b_stdio_check(") == 1
    assert "stdio" not in (root / "native_whole_scope_bootstrap.h").read_text()
