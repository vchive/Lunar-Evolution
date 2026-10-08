"""Private POSIX queues, never existing outside queue names or provider traffic.

The creating parent owns every O_EXCL mode0600 queue and all cleanup. Targets
receive only its unique name, never a queue descriptor. Formal tests use sealed
v2 grants and both original guardian children. Darwin/ABI skips are not Linux
enforcement evidence; keyrings and other kernel IPC routes remain outside scope.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import errno
import json
import os
import subprocess
import sys
import uuid
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from _native_target_fixture import compile_native_target
from test_native_independent_guardian import _formal
from test_native_trusted_controller_death import _frame

from lunar_evolution.native_bootstrap import build_native_bootstrap_artifact

_SOURCE = r'''
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>
#include "native_producer_isolation.h"

#ifdef __NR_mq_open
_Static_assert(LUNAR_NR_MQ_OPEN == __NR_mq_open, "mq_open UAPI");
_Static_assert(LUNAR_NR_MQ_UNLINK == __NR_mq_unlink, "mq_unlink UAPI");
_Static_assert(LUNAR_NR_MQ_TIMEDSEND == __NR_mq_timedsend, "mq_timedsend UAPI");
_Static_assert(LUNAR_NR_MQ_TIMEDRECEIVE == __NR_mq_timedreceive, "mq_timedreceive UAPI");
_Static_assert(LUNAR_NR_MQ_NOTIFY == __NR_mq_notify, "mq_notify UAPI");
_Static_assert(LUNAR_NR_MQ_GETSETATTR == __NR_mq_getsetattr, "mq_getsetattr UAPI");
#endif
#ifdef __NR_mq_timedsend_time64
_Static_assert(LUNAR_NR_MQ_TIMEDSEND_TIME64 == __NR_mq_timedsend_time64, "mq send time64 UAPI");
_Static_assert(LUNAR_NR_MQ_TIMEDRECEIVE_TIME64 == __NR_mq_timedreceive_time64, "mq receive time64 UAPI");
#endif
static void observed(long result, int error, int marker) {
    printf("{\"result\":%ld,\"errno\":%d,\"marker\":%s}\n", result, error, marker ? "true" : "false");
}
static long number(const char *name) {
    if (!strcmp(name, "mq_open")) return LUNAR_NR_MQ_OPEN;
    if (!strcmp(name, "mq_unlink")) return LUNAR_NR_MQ_UNLINK;
    if (!strcmp(name, "mq_timedsend")) return LUNAR_NR_MQ_TIMEDSEND;
    if (!strcmp(name, "mq_timedreceive")) return LUNAR_NR_MQ_TIMEDRECEIVE;
    if (!strcmp(name, "mq_notify")) return LUNAR_NR_MQ_NOTIFY;
    if (!strcmp(name, "mq_getsetattr")) return LUNAR_NR_MQ_GETSETATTR;
#ifdef LUNAR_NR_MQ_TIMEDSEND_TIME64
    if (!strcmp(name, "mq_timedsend_time64")) return LUNAR_NR_MQ_TIMEDSEND_TIME64;
    if (!strcmp(name, "mq_timedreceive_time64")) return LUNAR_NR_MQ_TIMEDRECEIVE_TIME64;
#endif
    return -1;
}
static int raw(const char *name) {
    long nr = number(name); if (nr < 0) return 77;
    errno = 0;
    /* Invalid component names cannot create or unlink any host object if a
       rule disappears. Other probes use invalid descriptors/pointers only. */
    long result;
    if (!strcmp(name, "mq_open")) result = syscall(nr, "invalid/name", O_RDONLY, 0, NULL);
    else if (!strcmp(name, "mq_unlink")) result = syscall(nr, "invalid/name");
    else result = syscall(nr, -1L, -1L, -1L, -1L, -1L, -1L);
    observed(result, errno, 0); return 0;
}
static int queue(const char *operation, const char *name) {
    if (name[0] != '/' || !name[1] || strchr(name + 1, '/')) return 10;
    long result; int error, marker = 0;
    /* Linux mq syscalls take one component; libc strips its public leading '/'. */
    if (!strcmp(operation, "unlink")) {
        errno = 0; result = syscall(LUNAR_NR_MQ_UNLINK, name + 1); error = errno;
    } else {
        int flags = !strcmp(operation, "send") ? O_WRONLY : O_RDONLY;
        errno = 0;
        int fd = (int)syscall(LUNAR_NR_MQ_OPEN, name + 1, flags | O_NONBLOCK, 0, NULL);
        if (fd < 0) { observed(-1, errno, 0); return 0; }
        if (!strcmp(operation, "send")) {
            errno = 0;
            result = syscall(LUNAR_NR_MQ_TIMEDSEND, fd, "MQ-MARK!", 8, 0, NULL); error = errno;
        } else if (!strcmp(operation, "receive")) {
            char bytes[16];
            errno = 0;
            result = syscall(LUNAR_NR_MQ_TIMEDRECEIVE, fd, bytes, sizeof(bytes), NULL, NULL); error = errno;
            marker = result == 8 && !memcmp(bytes, "original", 8);
        } else { close(fd); return 11; }
        if (close(fd)) return 12;
    }
    observed(result, error, marker); return 0;
}
static void *thread_result(void *value) { *(int *)value = 42; return value; }
static int ordinary(const char *root, int target) {
    int p[2]; char bytes[4];
    if (pipe2(p, O_CLOEXEC) || write(p[1], "ping", 4) != 4 ||
        read(p[0], bytes, 4) != 4 || memcmp(bytes, "ping", 4) || close(p[0]) || close(p[1])) return 20;
    char path[4096];
    if (snprintf(path, sizeof(path), "%s/ordinary", root) >= (int)sizeof(path)) return 21;
    int file = open(path, O_CREAT | O_RDWR | O_TRUNC, 0600);
    if (file < 0 || write(file, "test", 4) != 4 || ftruncate(file, 2) ||
        lseek(file, 0, SEEK_SET) != 0 || read(file, bytes, 2) != 2 || memcmp(bytes, "te", 2) || close(file)) return 22;
    pid_t child = fork(); if (child < 0) return 23;
    if (!child) _exit(0);
    int status;
    if (waitpid(child, &status, 0) != child || !WIFEXITED(status) || WEXITSTATUS(status)) return 24;
    pthread_t thread; int value = 0; void *returned = NULL;
    if (pthread_create(&thread, NULL, thread_result, &value) || pthread_join(thread, &returned) ||
        value != 42 || returned != &value) return 25;
    const char *response = getenv("LUNAR_PRODUCER_RESPONSE_FD"), *request = getenv("LUNAR_PRODUCER_REQUEST_FD");
    int r = -1, w = -1;
    if (response && request) {
        r = atoi(response); w = atoi(request);
        if (write(w, "ping", 4) != 4 || read(r, bytes, 4) != 4 || memcmp(bytes, "pong", 4)) return 26;
    }
    if (target > 2) for (int fd = 3; fd < 4096; ++fd) {
        if (fd == target || fd == r || fd == w) continue;
        errno = 0; if (fcntl(fd, F_GETFD) != -1 || errno != EBADF) return 27;
    }
    printf("{\"ordinary\":true,\"broker\":%s}\n", r >= 0 ? "true" : "false"); return 0;
}
int main(int argc, char **argv) {
    if (argc != 6) return 2;
    if (!strcmp(argv[1], "filtered")) {
        const char *writes[] = {argv[4]};
        if (lunar_apply_isolation("linux-landlock-seccomp-v1", NULL, 0, writes, 1)) return 3;
    }
    if (!strcmp(argv[2], "raw")) return raw(argv[3]);
    if (!strcmp(argv[2], "ordinary")) return ordinary(argv[4], atoi(argv[5]));
    return queue(argv[2], argv[3]);
}
'''

_SYSCALLS = (
    "mq_open", "mq_unlink", "mq_timedsend", "mq_timedreceive", "mq_notify", "mq_getsetattr",
    "mq_timedsend_time64", "mq_timedreceive_time64",
)


@pytest.fixture(scope="module", params=[False, True], ids=["host-uapi", "omitted-uapi-names"])
def compiled(tmp_path_factory, request):
    if sys.platform != "linux":
        pytest.skip("actual Linux POSIX queue controls")
    root = tmp_path_factory.mktemp("native-posix-mq")
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
        pytest.skip("requires actual native i386 mq time64 entry")
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    return json.loads(result.stdout)


class _MqAttr(ctypes.Structure):
    _fields_ = [(name, ctypes.c_long) for name in ("flags", "maxmsg", "msgsize", "curmsgs")]
    _fields_.append(("reserved", ctypes.c_long * 4))


def _library():
    lib = ctypes.CDLL(None, use_errno=True)
    if not hasattr(lib, "mq_open"):
        runtime = ctypes.util.find_library("rt")
        assert runtime is not None, "local Linux POSIX queue library unavailable"
        lib = ctypes.CDLL(runtime, use_errno=True)
    lib.mq_open.argtypes = [ctypes.c_char_p, ctypes.c_int]
    lib.mq_open.restype = ctypes.c_int
    lib.mq_close.argtypes = [ctypes.c_int]
    lib.mq_unlink.argtypes = [ctypes.c_char_p]
    lib.mq_send.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_uint]
    lib.mq_receive.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p]
    lib.mq_receive.restype = ctypes.c_ssize_t
    lib.mq_getattr.argtypes = [ctypes.c_int, ctypes.POINTER(_MqAttr)]
    return lib


@contextmanager
def _owned_queue(*, preload=False):
    lib = _library()
    name = f"/lunar185-{os.getpid()}-{uuid.uuid4().hex}".encode("ascii")
    attr = _MqAttr(maxmsg=4, msgsize=16)
    descriptor = lib.mq_open(name, os.O_CREAT | os.O_EXCL | os.O_RDWR | os.O_NONBLOCK,
                             ctypes.c_uint(0o600), ctypes.byref(attr))
    assert descriptor >= 0, ctypes.get_errno()  # No cleanup authority unless O_EXCL succeeded.
    identity = None

    def named():
        ctypes.set_errno(0)
        reopened = lib.mq_open(name, os.O_RDWR | os.O_NONBLOCK)
        if reopened < 0:
            assert ctypes.get_errno() == errno.ENOENT, ctypes.get_errno()
            return False
        try:
            current = os.fstat(reopened)
            assert (current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino), \
                "private queue name identity mismatch"
        finally:
            assert lib.mq_close(reopened) == 0, ctypes.get_errno()
        return True

    def state():
        linked = named()
        attributes = _MqAttr()
        assert lib.mq_getattr(descriptor, ctypes.byref(attributes)) == 0, ctypes.get_errno()
        assert attributes.curmsgs in (0, 1)
        message = ctypes.create_string_buffer(16)
        ctypes.set_errno(0)
        size = lib.mq_receive(descriptor, message, 16, None)
        if size < 0:
            assert ctypes.get_errno() == errno.EAGAIN, ctypes.get_errno()
            return linked, None
        assert size == 8
        return linked, message.raw[:size]

    try:
        identity = os.fstat(descriptor)
        assert identity.st_mode & 0o777 == 0o600
        if preload:
            assert lib.mq_send(descriptor, b"original", 8, 0) == 0, ctypes.get_errno()
        yield name.decode("ascii"), state
    finally:
        original = sys.exc_info()[1]
        failures = []
        try:
            # O_EXCL ownership begins before the first stat. If that stat
            # failed, supplement its missing identity once from the still-held
            # original descriptor; never refresh an identity already recorded.
            if identity is None:
                identity = os.fstat(descriptor)
            # Verify the original object before deleting its unique name. A
            # disappeared or substituted name never authorizes a foreign unlink.
            if named() and lib.mq_unlink(name) != 0:
                raise RuntimeError(f"private queue unlink failed: errno={ctypes.get_errno()}")
        except (AssertionError, OSError, RuntimeError) as exc:
            failures.append(exc)
        finally:
            if lib.mq_close(descriptor) != 0:
                failures.append(RuntimeError(f"private queue close failed: errno={ctypes.get_errno()}"))
        if failures:
            if original is not None:
                for failure in failures:
                    original.add_note(str(failure))
            else:
                raise failures[0]


@pytest.mark.parametrize("failure", ["stat-recovered", "stat-still-fails", "replaced-name",
                                      "recorded-identity"])
def test_owned_queue_stat_failure_keeps_primary_and_original_cleanup_authority(monkeypatch, failure):
    # Synthetic descriptors and a mock library model only this fixture's own
    # freshly-created queue. No real queue, FD, or foreign unlink is involved.
    descriptor, reopened = 1000071, 1000072
    held_calls, closed, unlinked = [], [], []
    identity = SimpleNamespace(st_dev=101, st_ino=202, st_mode=0o600)
    replacement = SimpleNamespace(st_dev=101, st_ino=303, st_mode=0o600)
    primary = OSError(errno.EIO, "inert primary stat failure")
    original_fstat = os.fstat

    def stat(fd):
        if fd == descriptor:
            held_calls.append(fd)
            if failure != "recorded-identity" and len(held_calls) == 1:
                raise primary
            if failure == "stat-still-fails":
                raise OSError(errno.EIO, "inert cleanup stat failure")
            return identity
        if fd == reopened:
            return replacement if failure in {"replaced-name", "recorded-identity"} else identity
        return original_fstat(fd)

    def close(fd):
        closed.append(fd)
        return 0

    def unlink(name):
        unlinked.append(name)
        return 0

    lib = SimpleNamespace(mq_open=lambda _name, flags, *_args: descriptor if flags & os.O_EXCL else reopened,
                          mq_close=close, mq_unlink=unlink)
    monkeypatch.setattr(sys.modules[__name__], "_library", lambda: lib)
    monkeypatch.setattr(os, "fstat", stat)
    with pytest.raises(OSError) as caught, _owned_queue():
        if failure == "recorded-identity":
            raise primary
        pytest.fail("initial stat failure must not yield a queue")
    assert caught.value is primary
    assert closed.count(descriptor) == 1
    assert len(held_calls) == (1 if failure == "recorded-identity" else 2)
    if failure == "stat-recovered":
        assert len(unlinked) == 1 and closed.count(reopened) == 1
        assert not getattr(primary, "__notes__", [])
    else:
        assert unlinked == []
        assert closed.count(reopened) == (0 if failure == "stat-still-fails" else 1)
        assert getattr(primary, "__notes__", [])
        assert ("cleanup stat failure" if failure == "stat-still-fails" else "identity mismatch") in \
            " ".join(primary.__notes__)


@pytest.mark.parametrize("operation", ["send", "receive", "unlink"])
@pytest.mark.parametrize("filtered", [False, True], ids=["baseline", "filtered"])
def test_private_parent_owned_named_queue_route_and_rejection(compiled, tmp_path, operation, filtered):
    with _owned_queue(preload=operation == "receive") as (name, state):
        result = _run(compiled, tmp_path, "filtered" if filtered else "baseline", operation, name)
        assert result == {
            "result": -1 if filtered else (8 if operation == "receive" else 0),
            "errno": errno.EPERM if filtered else 0,
            "marker": not filtered and operation == "receive",
        }
        assert state() == (operation != "unlink" or filtered,
                           b"original" if filtered and operation == "receive" else
                           b"MQ-MARK!" if not filtered and operation == "send" else None)


def _finish_formal(fixture):
    assert _frame(fixture.frame).kind == "bootstrap_ready"
    os.write(fixture.gate, b"1")
    fixture.close(fixture.gate)
    assert _frame(fixture.frame).kind == "target_started"
    assert _frame(fixture.frame).kind == "terminal"
    stdout, stderr = fixture.process.communicate(timeout=3)
    assert fixture.process.returncode == 0, stderr
    assert fixture.watcher.wait(timeout=3) == 0
    return json.loads(stdout)


@pytest.mark.parametrize("operation", ["send", "receive", "unlink"])
def test_v2_original_guardian_target_cannot_access_private_named_queue(compiled, tmp_path, operation):
    with _owned_queue(preload=operation == "receive") as (name, state):
        def mutate(data):
            data.argv = [str(compiled.target), "formal", operation, name, str(tmp_path / "work"), "0"]

        with _formal(compiled, tmp_path, mutate=mutate) as fixture:
            assert _finish_formal(fixture) == {"result": -1, "errno": errno.EPERM, "marker": False}
        assert state() == (True, b"original" if operation == "receive" else None)


@pytest.mark.parametrize("operation", _SYSCALLS)
def test_raw_named_queue_entries_refuse_before_kernel_validation(compiled, tmp_path, operation):
    assert _run(compiled, tmp_path, "filtered", "raw", operation) == {
        "result": -1, "errno": errno.EPERM, "marker": False,
    }


def test_filtered_ordinary_pipe_file_fork_and_thread(compiled, tmp_path):
    assert _run(compiled, tmp_path, "filtered", "ordinary") == {"ordinary": True, "broker": False}
    assert (tmp_path / "ordinary").read_bytes() == b"te"


@pytest.mark.parametrize("broker", [False, True])
def test_v2_original_guardian_keeps_ordinary_io_broker_and_fd_closure(compiled, tmp_path, broker):
    def mutate(data):
        data.argv = [str(compiled.target), "formal", "ordinary", "unused", str(tmp_path / "work"),
                     str(data.target_fd)]

    with _formal(compiled, tmp_path, mutate=mutate, broker=broker) as fixture:
        if broker:
            os.write(fixture.response, b"pong")
        assert _finish_formal(fixture) == {"ordinary": True, "broker": broker}
        assert (fixture.working / "ordinary").read_bytes() == b"te"
        if broker:
            assert os.read(fixture.request, 4) == b"ping"
