"""Bounded inert Linux keyring fixtures; never inspect pre-existing host keys."""
from __future__ import annotations

import errno
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from _native_target_fixture import compile_native_target
from test_native_independent_guardian import _formal
from test_native_named_ipc_control import _finish_formal

from lunar_evolution.native_bootstrap import build_native_bootstrap_artifact

_SOURCE = r'''
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <signal.h>
#include <sys/prctl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>
#include "native_producer_isolation.h"
#ifdef __NR_add_key
_Static_assert(LUNAR_NR_ADD_KEY == __NR_add_key, "add_key UAPI");
_Static_assert(LUNAR_NR_REQUEST_KEY == __NR_request_key, "request_key UAPI");
_Static_assert(LUNAR_NR_KEYCTL == __NR_keyctl, "keyctl UAPI");
#endif
static void observed(long result, int error) {
    printf("{\"result\":%ld,\"errno\":%d}\n", result, error);
}
static int raw(const char *name) {
    errno = 0; long result;
    /* NULL types and an invalid negative special ID cannot create/lookup any
       existing key. NULL callout information cannot invoke an external helper. */
    if (!strcmp(name, "add_key"))
        result = syscall(LUNAR_NR_ADD_KEY, NULL, NULL, NULL, 0UL, -2147483648L);
    else if (!strcmp(name, "request_key"))
        result = syscall(LUNAR_NR_REQUEST_KEY, NULL, NULL, NULL, -2147483648L);
    else {
        long command = !strcmp(name, "keyctl") ? 0x7fffffffL : strtol(name, NULL, 10);
        result = syscall(LUNAR_NR_KEYCTL, command, -2147483648L, NULL, 0UL, 0UL);
    }
    observed(result, errno); return 0;
}
static long key(long command, long id, void *bytes, size_t length) {
    return syscall(LUNAR_NR_KEYCTL, command, id, bytes, length, 0UL);
}
static int private_route(const char *root, const char *operation, int filtered) {
    /* A NULL name always creates a fresh anonymous session ring in this
       disposable process. Never query a pre-existing user/session ring. */
    long ring = syscall(LUNAR_NR_KEYCTL, 1L, NULL, 0UL, 0UL, 0UL);
    if (ring < 0) {
        int error = errno;
        if (error != EPERM && error != EACCES && error != ENOSYS) return 10;
        observed(-1, error); return 77;
    }
    long original = syscall(LUNAR_NR_ADD_KEY, "user", "original", "original", 8UL, ring);
    int code = 0; long cleared, revoked;
    if (original < 0) {
        int error = errno;
        if (error == EPERM || error == EACCES || error == ENOSYS) { observed(-1, error); code = 77; }
        else code = 11;
        goto cleanup;
    }
    char bytes[32] = {0};
    if (key(11, original, bytes, sizeof(bytes)) != 8 || memcmp(bytes, "original", 8)) {
        code = 12; goto cleanup;
    }
    /* Read, write and lookup baselines use only our new ring/key. */
    if (key(2, original, "baseline", 8) || key(11, original, bytes, sizeof(bytes)) != 8 ||
        memcmp(bytes, "baseline", 8) || key(2, original, "original", 8)) {
        code = 13; goto cleanup;
    }
    int response[2]; if (pipe2(response, O_CLOEXEC)) { code = 14; goto cleanup; }
    pid_t original_parent = getpid();
    pid_t child = fork();
    if (child < 0) { close(response[0]); close(response[1]); code = 15; goto cleanup; }
    if (!child) {
        close(response[0]);
        if (prctl(PR_SET_PDEATHSIG, SIGKILL, 0, 0, 0) || getppid() != original_parent) _exit(24);
        if (filtered) {
            const char *writes[] = {root};
            if (lunar_apply_isolation("linux-landlock-seccomp-v1", NULL, 0, writes, 1)) _exit(16);
        }
        errno = 0; long result;
        if (!strcmp(operation, "read")) result = key(11, original, bytes, sizeof(bytes));
        else if (!strcmp(operation, "update")) result = key(2, original, "changed!", 8);
        else if (!strcmp(operation, "search"))
            result = syscall(LUNAR_NR_KEYCTL, 10L, ring, "user", "original", 0UL);
        else if (!strcmp(operation, "add"))
            result = syscall(LUNAR_NR_ADD_KEY, "user", "extra", "bounded", 7UL, ring);
        else if (!strcmp(operation, "request"))
            result = syscall(LUNAR_NR_REQUEST_KEY, "user", "original", NULL, ring);
        else _exit(17);
        long message[] = {result, errno};
        if (write(response[1], message, sizeof(message)) != (ssize_t)sizeof(message) || close(response[1])) _exit(18);
        _exit(0);
    }
    close(response[1]); long message[2];
    ssize_t size = read(response[0], message, sizeof(message)); close(response[0]);
    int status;
    if (waitpid(child, &status, 0) != child || !WIFEXITED(status) || WEXITSTATUS(status) ||
        size != (ssize_t)sizeof(message)) { code = 19; goto cleanup; }
    if (filtered) {
        if (message[0] != -1 || message[1] != EPERM ||
            key(11, original, bytes, sizeof(bytes)) != 8 || memcmp(bytes, "original", 8)) {
            code = 20; goto cleanup;
        }
        int ids[4]; if (key(11, ring, ids, sizeof(ids)) != (long)sizeof(int) || ids[0] != original) {
            code = 21; goto cleanup;
        }
    } else if (message[0] < 0 || message[1]) { code = 22; goto cleanup; }
    observed(message[0], (int)message[1]);
cleanup:
    /* CLEAR/REVOKE refer only to the freshly allocated ring, even if a target
       refusal regresses and creates an extra bounded key there. */
    cleared = key(7, ring, NULL, 0); revoked = key(3, ring, NULL, 0);
    if (cleared || revoked) {
        fprintf(stderr, "private keyring cleanup failed; primary=%d clear=%ld revoke=%ld\n", code, cleared, revoked);
        if (!code || code == 77) code = 23;
    }
    return code;
}
static void *thread_result(void *value) { *(int *)value = 42; return value; }
static int ordinary(const char *root, int target) {
    int p[2]; char bytes[4];
    if (pipe2(p, O_CLOEXEC) || write(p[1], "ping", 4) != 4 ||
        read(p[0], bytes, 4) != 4 || memcmp(bytes, "ping", 4) || close(p[0]) || close(p[1])) return 30;
    char path[4096];
    if (snprintf(path, sizeof(path), "%s/ordinary", root) >= (int)sizeof(path)) return 31;
    int file = open(path, O_CREAT | O_RDWR | O_TRUNC, 0600);
    if (file < 0 || write(file, "test", 4) != 4 || ftruncate(file, 2) || close(file)) return 32;
    pid_t child = fork(); if (child < 0) return 33;
    if (!child) _exit(0);
    int status;
    if (waitpid(child, &status, 0) != child || !WIFEXITED(status) || WEXITSTATUS(status)) return 34;
    pthread_t thread; int value = 0; void *returned = NULL;
    if (pthread_create(&thread, NULL, thread_result, &value) || pthread_join(thread, &returned) ||
        value != 42 || returned != &value) return 35;
    const char *response = getenv("LUNAR_PRODUCER_RESPONSE_FD"), *request = getenv("LUNAR_PRODUCER_REQUEST_FD");
    int r = -1, w = -1;
    if (response && request) {
        r = atoi(response); w = atoi(request);
        if (write(w, "ping", 4) != 4 || read(r, bytes, 4) != 4 || memcmp(bytes, "pong", 4)) return 36;
    }
    if (target > 2) for (int fd = 3; fd < 4096; ++fd) {
        if (fd == target || fd == r || fd == w) continue;
        errno = 0; if (fcntl(fd, F_GETFD) != -1 || errno != EBADF) return 37;
    }
    printf("{\"ordinary\":true,\"broker\":%s}\n", r >= 0 ? "true" : "false"); return 0;
}
int main(int argc, char **argv) {
    if (argc != 6) return 2;
    if (!strcmp(argv[2], "private")) return private_route(argv[4], argv[3], !strcmp(argv[1], "filtered"));
    if (!strcmp(argv[1], "filtered")) {
        const char *writes[] = {argv[4]};
        if (lunar_apply_isolation("linux-landlock-seccomp-v1", NULL, 0, writes, 1)) return 3;
    }
    if (!strcmp(argv[2], "ordinary")) return ordinary(argv[4], atoi(argv[5]));
    return raw(argv[3]);
}
'''

_SYSCALLS = ("add_key", "request_key", "keyctl")
_PROBES = (*_SYSCALLS, "0", "2", "9", "10", "11", "21", "30")


@pytest.fixture(scope="module", params=[False, True], ids=["host-uapi", "omitted-uapi-names"])
def compiled(tmp_path_factory, request):
    if sys.platform != "linux":
        pytest.skip("actual Linux keyring controls")
    root = tmp_path_factory.mktemp("native-keyring")
    source, target = root / "target.c", root / "target"
    text = _SOURCE
    if request.param:
        text = text.replace('#include "native_producer_isolation.h"',
                            "\n".join(f"#undef __NR_{name}" for name in _SYSCALLS)
                            + '\n#include "native_producer_isolation.h"')
    source.write_text(text, encoding="utf-8")
    compile_native_target(source, target, "-pthread", "-I", str(Path(__file__).parents[1] / "src/lunar_evolution"))
    return SimpleNamespace(target=target, artifact=build_native_bootstrap_artifact(root / "bootstrap"))


def _run(compiled, root, mode, operation, argument="unused"):
    result = subprocess.run(
        [str(compiled.target), mode, operation, argument, str(root), "0"],
        close_fds=True, capture_output=True, timeout=5, check=False,
        env={"PATH": os.defpath, "LANG": "C"},
    )
    if result.returncode == 77:
        assert operation == "private"
        observed = json.loads(result.stdout)
        assert observed["result"] == -1 and observed["errno"] in {errno.EPERM, errno.EACCES, errno.ENOSYS}
        pytest.skip(f"private anonymous keyring unavailable under host policy: errno={observed['errno']}")
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    return json.loads(result.stdout)


@pytest.mark.parametrize("operation", _PROBES)
def test_raw_keyring_entries_refuse_before_kernel_validation(compiled, tmp_path, operation):
    assert _run(compiled, tmp_path, "filtered", "raw", operation) == {"result": -1, "errno": errno.EPERM}


@pytest.mark.parametrize("operation", ["read", "update", "search", "add", "request"])
@pytest.mark.parametrize("filtered", [False, True], ids=["usable-baseline", "filtered"])
def test_disposable_private_keyring_routes_and_unchanged_original(compiled, tmp_path, operation, filtered):
    observed = _run(compiled, tmp_path, "filtered" if filtered else "baseline", "private", operation)
    if filtered:
        assert observed == {"result": -1, "errno": errno.EPERM}
    else:
        assert observed["result"] >= 0 and observed["errno"] == 0


@pytest.mark.parametrize("operation", _SYSCALLS)
def test_v2_original_guardian_target_refuses_keyring_family(compiled, tmp_path, operation):
    def mutate(data):
        data.argv = [str(compiled.target), "formal", "raw", operation, str(tmp_path / "work"), "0"]

    with _formal(compiled, tmp_path, mutate=mutate) as fixture:
        assert _finish_formal(fixture) == {"result": -1, "errno": errno.EPERM}


def test_filtered_ordinary_pipe_file_fork_and_thread(compiled, tmp_path):
    assert _run(compiled, tmp_path, "filtered", "ordinary") == {"ordinary": True, "broker": False}
    assert (tmp_path / "ordinary").read_bytes() == b"te"


@pytest.mark.parametrize("broker", [False, True])
def test_v2_original_guardian_keeps_io_broker_and_fd_closure(compiled, tmp_path, broker):
    def mutate(data):
        data.argv = [str(compiled.target), "formal", "ordinary", "unused", str(tmp_path / "work"), str(data.target_fd)]

    with _formal(compiled, tmp_path, mutate=mutate, broker=broker) as fixture:
        if broker:
            os.write(fixture.response, b"pong")
        assert _finish_formal(fixture) == {"ordinary": True, "broker": broker}
        assert (fixture.working / "ordinary").read_bytes() == b"te"
        if broker:
            assert os.read(fixture.request, 4) == b"ping"
