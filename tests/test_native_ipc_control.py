"""Disposable Linux IPC objects and socket ancillary fixtures, never outside campaigns.

Direct header fixtures deliberately inherit socket peers; formal SysV fixtures
inherit only the existing v2 original grants and sealed target, passing numeric IDs.
Parent-owned objects are private0600, nonblocking and always removed by that parent.
Darwin skips and source table checks are not native Linux/ARM/i386 execution evidence.
"""
from __future__ import annotations

import array
import ctypes
import errno
import json
import os
import socket
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest
from _native_target_fixture import compile_native_target
from test_native_grant_objects import _release, _start
from test_native_trusted_controller_death import _frame

from lunar_evolution.native_bootstrap import build_native_bootstrap_artifact

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="actual Linux bounded IPC controls")

_SOURCE = r'''
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ipc.h>
#include <sys/msg.h>
#include <sys/sem.h>
#include <sys/shm.h>
#include <sys/socket.h>
#include <sys/syscall.h>
#include <sys/uio.h>
#include <sys/wait.h>
#include <unistd.h>
#include "native_producer_isolation.h"

/* Compile against the running host's independent UAPI names when available.
   The omitted-header variant removes these names before including the header. */
#ifdef __NR_shmget
_Static_assert(LUNAR_NR_SHMGET == __NR_shmget, "shmget UAPI");
_Static_assert(LUNAR_NR_SHMAT == __NR_shmat, "shmat UAPI");
_Static_assert(LUNAR_NR_SHMCTL == __NR_shmctl, "shmctl UAPI");
_Static_assert(LUNAR_NR_SHMDT == __NR_shmdt, "shmdt UAPI");
_Static_assert(LUNAR_NR_MSGGET == __NR_msgget, "msgget UAPI");
_Static_assert(LUNAR_NR_MSGSND == __NR_msgsnd, "msgsnd UAPI");
_Static_assert(LUNAR_NR_MSGRCV == __NR_msgrcv, "msgrcv UAPI");
_Static_assert(LUNAR_NR_MSGCTL == __NR_msgctl, "msgctl UAPI");
_Static_assert(LUNAR_NR_SEMGET == __NR_semget, "semget UAPI");
_Static_assert(LUNAR_NR_SEMCTL == __NR_semctl, "semctl UAPI");
#endif
#ifdef __NR_semop
_Static_assert(LUNAR_NR_SEMOP == __NR_semop, "semop UAPI");
_Static_assert(LUNAR_NR_SEMTIMEDOP == __NR_semtimedop, "semtimedop UAPI");
#endif
#ifdef __NR_sendmmsg
_Static_assert(LUNAR_NR_SENDMMSG == __NR_sendmmsg, "sendmmsg UAPI");
#endif
#ifdef __NR_recvmsg
_Static_assert(LUNAR_NR_RECVMSG == __NR_recvmsg, "recvmsg UAPI");
#endif
#ifdef __NR_recvmmsg
_Static_assert(LUNAR_NR_RECVMMSG == __NR_recvmmsg, "recvmmsg UAPI");
#endif
#ifdef __NR_socketpair
_Static_assert(LUNAR_NR_SOCKETPAIR == __NR_socketpair, "socketpair UAPI");
#endif
#ifdef __NR_ipc
_Static_assert(LUNAR_NR_IPC == __NR_ipc, "ipc UAPI");
#endif
#ifdef __NR_semtimedop_time64
_Static_assert(LUNAR_NR_SEMTIMEDOP_TIME64 == __NR_semtimedop_time64, "semtimedop time64 UAPI");
#endif
#ifdef __NR_recvmmsg_time64
_Static_assert(LUNAR_NR_RECVMMSG_TIME64 == __NR_recvmmsg_time64, "recvmmsg time64 UAPI");
#endif
static void observed(long result, int error, int received) {
    printf("{\"result\":%ld,\"errno\":%d,\"received_fd\":%s}\n", result, error, received ? "true" : "false");
}
static long number(const char *name) {
    if (!strcmp(name, "shmget")) return LUNAR_NR_SHMGET;
    if (!strcmp(name, "shmat")) return LUNAR_NR_SHMAT;
    if (!strcmp(name, "shmctl")) return LUNAR_NR_SHMCTL;
    if (!strcmp(name, "shmdt")) return LUNAR_NR_SHMDT;
    if (!strcmp(name, "msgget")) return LUNAR_NR_MSGGET;
    if (!strcmp(name, "msgsnd")) return LUNAR_NR_MSGSND;
    if (!strcmp(name, "msgrcv")) return LUNAR_NR_MSGRCV;
    if (!strcmp(name, "msgctl")) return LUNAR_NR_MSGCTL;
    if (!strcmp(name, "semget")) return LUNAR_NR_SEMGET;
    if (!strcmp(name, "semctl")) return LUNAR_NR_SEMCTL;
#ifdef LUNAR_NR_SEMOP
    if (!strcmp(name, "semop")) return LUNAR_NR_SEMOP;
    if (!strcmp(name, "semtimedop")) return LUNAR_NR_SEMTIMEDOP;
#endif
    if (!strcmp(name, "sendmmsg")) return LUNAR_NR_SENDMMSG;
    if (!strcmp(name, "recvmsg")) return LUNAR_NR_RECVMSG;
    if (!strcmp(name, "recvmmsg")) return LUNAR_NR_RECVMMSG;
#ifdef LUNAR_NR_IPC
    if (!strcmp(name, "ipc")) return LUNAR_NR_IPC;
    if (!strcmp(name, "semtimedop_time64")) return LUNAR_NR_SEMTIMEDOP_TIME64;
    if (!strcmp(name, "recvmmsg_time64")) return LUNAR_NR_RECVMMSG_TIME64;
#endif
    return -1;
}
static int raw(const char *op) {
    long nr = number(op); if (nr < 0) return 77;
    errno = 0;
    long result;
    /* Invalid IDs/pointers cannot mutate a real object if a rule disappears.
       msgget has no harmless invalid private-create signature: report a newly
       allocated IPC_PRIVATE ID so the fixture parent can remove it on failure. */
    if (!strcmp(op, "msgget")) result = syscall(nr, IPC_PRIVATE, 0600);
    else if (!strcmp(op, "shmget")) result = syscall(nr, IPC_PRIVATE, 0, 0600);
    else if (!strcmp(op, "semget")) result = syscall(nr, IPC_PRIVATE, 0, 0600);
    else result = syscall(nr, -1L, -1L, -1L, -1L, -1L, -1L);
    observed(result, errno, 0); return 0;
}
static int ipc(const char *op, int id) {
    int error; long result;
    if (!strcmp(op, "msg")) {
        struct { long kind; char body[8]; } message = {1, {'I','P','C','-','M','A','R','K'}};
        errno = 0; result = msgsnd(id, &message, sizeof(message.body), IPC_NOWAIT); error = errno;
    } else if (!strcmp(op, "shm")) {
        errno = 0; void *bytes = shmat(id, NULL, 0); error = errno;
        result = bytes == (void *)-1 ? -1 : 0;
        if (result == 0) { memcpy(bytes, "IPC-MARK", 8); if (shmdt(bytes)) return 21; }
    } else if (!strcmp(op, "sem")) {
        struct sembuf operation = {0, 1, IPC_NOWAIT};
        errno = 0; result = semop(id, &operation, 1); error = errno;
    } else return 22;
    observed(result, error, 0); return 0;
}
static int messages(const char *op, int fd, int file) {
    char bytes[8] = "IPC-MARK";
    union { struct cmsghdr aligned; char bytes[CMSG_SPACE(sizeof(int))]; } control;
    memset(&control, 0, sizeof(control));
    struct iovec iov = {bytes, sizeof(bytes)};
    struct mmsghdr item; memset(&item, 0, sizeof(item));
    item.msg_hdr.msg_iov = &iov; item.msg_hdr.msg_iovlen = 1;
    item.msg_hdr.msg_control = control.bytes; item.msg_hdr.msg_controllen = sizeof(control.bytes);
    long result; int error, received = 0;
    if (!strcmp(op, "sendmmsg") || !strcmp(op, "sendmmsg-fd")) {
        if (!strcmp(op, "sendmmsg-fd")) {
            struct cmsghdr *header = CMSG_FIRSTHDR(&item.msg_hdr);
            header->cmsg_level = SOL_SOCKET; header->cmsg_type = SCM_RIGHTS;
            header->cmsg_len = CMSG_LEN(sizeof(file)); memcpy(CMSG_DATA(header), &file, sizeof(file));
        } else { item.msg_hdr.msg_control = NULL; item.msg_hdr.msg_controllen = 0; }
        errno = 0; result = syscall(LUNAR_NR_SENDMMSG, fd, &item, 1, MSG_DONTWAIT); error = errno;
    } else {
        errno = 0;
        if (!strcmp(op, "recvmsg")) result = syscall(LUNAR_NR_RECVMSG, fd, &item.msg_hdr, MSG_DONTWAIT);
        else result = syscall(LUNAR_NR_RECVMMSG, fd, &item, 1, MSG_DONTWAIT, NULL);
        error = errno;
        if (result >= 0) {
            struct cmsghdr *header = CMSG_FIRSTHDR(&item.msg_hdr);
            if (header && header->cmsg_level == SOL_SOCKET && header->cmsg_type == SCM_RIGHTS &&
                header->cmsg_len == CMSG_LEN(sizeof(int))) {
                int acquired; char content[7]; memcpy(&acquired, CMSG_DATA(header), sizeof(acquired));
                received = read(acquired, content, sizeof(content)) == 7 && !memcmp(content, "outside", 7);
                if (close(acquired)) return 23;
            }
            if (memcmp(bytes, "IPC-MARK", 8)) return 24;
        }
    }
    observed(result, error, received); return 0;
}
static int pair(uint64_t domain) {
    if (sizeof(unsigned long) == 4 && (domain >> 32)) return 77;
    int descriptors[2] = {-1, -1}; errno = 0;
    long result = syscall(LUNAR_NR_SOCKETPAIR, (unsigned long)domain, SOCK_STREAM, 0, descriptors);
    int error = errno;
    if (result == 0 && (close(descriptors[0]) || close(descriptors[1]))) return 25;
    observed(result, error, 0); return 0;
}
static void *thread_result(void *value) { *(int *)value = 42; return value; }
static int ordinary(const char *root, int target) {
    int p[2], s[2]; char bytes[4];
    if (pipe2(p, O_CLOEXEC)) return 30;
    struct iovec written[2] = {{"pi", 2}, {"ng", 2}};
    struct iovec readback[2] = {{bytes, 1}, {bytes + 1, 3}};
    if (writev(p[1], written, 2) != 4 || readv(p[0], readback, 2) != 4 || memcmp(bytes, "ping", 4)) return 31;
    if (close(p[0]) || close(p[1])) return 32;
    /* i386's legacy socketcall intentionally stays denied; use its native entry. */
    if (syscall(LUNAR_NR_SOCKETPAIR, AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0, s)) return 33;
    if (write(s[0], "pong", 4) != 4 || read(s[1], bytes, 4) != 4 || memcmp(bytes, "pong", 4)) return 34;
    if (close(s[0]) || close(s[1])) return 35;
    char path[4096];
    if (snprintf(path, sizeof(path), "%s/ordinary", root) >= (int)sizeof(path)) return 36;
    int file = open(path, O_CREAT | O_RDWR | O_TRUNC, 0600);
    if (file < 0 || write(file, "test", 4) != 4 || ftruncate(file, 2) || lseek(file, 0, SEEK_SET) != 0 ||
        read(file, bytes, 2) != 2 || memcmp(bytes, "te", 2) || close(file)) return 37;
    pid_t child = fork(); if (child < 0) return 38;
    if (!child) _exit(0);
    int status; if (waitpid(child, &status, 0) != child || !WIFEXITED(status) || WEXITSTATUS(status)) return 39;
    pthread_t thread; int value = 0; void *returned = NULL;
    if (pthread_create(&thread, NULL, thread_result, &value) || pthread_join(thread, &returned) ||
        value != 42 || returned != &value) return 40;
    const char *response = getenv("LUNAR_PRODUCER_RESPONSE_FD"), *request = getenv("LUNAR_PRODUCER_REQUEST_FD");
    int r = -1, w = -1;
    if (response && request) {
        r = atoi(response); w = atoi(request);
        if (write(w, "ping", 4) != 4 || read(r, bytes, 4) != 4 || memcmp(bytes, "pong", 4)) return 41;
    }
    if (target > 2) for (int fd = 3; fd < 4096; ++fd) {
        if (fd == target || fd == r || fd == w) continue;
        errno = 0; if (fcntl(fd, F_GETFD) != -1 || errno != EBADF) return 42;
    }
    printf("{\"ordinary\":true,\"broker\":%s}\n", r >= 0 ? "true" : "false"); return 0;
}
int main(int argc, char **argv) {
    if (argc != 6) return 2;
    if (!strcmp(argv[1], "filtered")) {
        const char *writes[] = {argv[4]};
        if (lunar_apply_isolation("linux-landlock-seccomp-v1", NULL, 0, writes, 1)) return 3;
    }
    if (!strcmp(argv[2], "raw")) return raw(argv[5]);
    if (!strcmp(argv[2], "pair")) return pair(strtoull(argv[3], NULL, 0));
    if (!strcmp(argv[2], "ordinary")) return ordinary(argv[4], atoi(argv[3]));
    if (!strcmp(argv[2], "msg") || !strcmp(argv[2], "shm") || !strcmp(argv[2], "sem")) return ipc(argv[2], atoi(argv[3]));
    return messages(argv[2], atoi(argv[3]), atoi(argv[5]));
}
'''

_SYSCALLS = (
    "shmget", "shmat", "shmctl", "shmdt", "msgget", "msgsnd", "msgrcv", "msgctl",
    "semget", "semctl", "semop", "semtimedop", "sendmmsg", "recvmsg", "recvmmsg",
    "socketpair", "ipc", "semtimedop_time64", "recvmmsg_time64",
)


@pytest.fixture(scope="module", params=[False, True], ids=["host-uapi", "omitted-uapi-names"])
def compiled(tmp_path_factory, request):
    root = tmp_path_factory.mktemp("native-ipc")
    source, target = root / "target.c", root / "target"
    text = _SOURCE
    if request.param:
        text = text.replace('#include "native_producer_isolation.h"',
                            "\n".join(f"#undef __NR_{name}" for name in _SYSCALLS)
                            + '\n#include "native_producer_isolation.h"')
    source.write_text(text, encoding="utf-8")
    compile_native_target(source, target, "-pthread", "-I", str(Path(__file__).parents[1] / "src/lunar_evolution"))
    return target, build_native_bootstrap_artifact(root / "bootstrap")


def _run(compiled, root, mode, operation, argument=0, extra=0, *, pass_fds=()):
    result = subprocess.run(
        [str(compiled[0]), mode, operation, str(argument), str(root), str(extra)],
        pass_fds=pass_fds, close_fds=True, capture_output=True, timeout=5, check=False,
        env={"PATH": os.defpath, "LANG": "C"},
    )
    if result.returncode == 77:
        pytest.skip("requires actual native i386/time64 or a 64-bit syscall argument")
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    return json.loads(result.stdout)


def _libc():
    lib = ctypes.CDLL(None, use_errno=True)
    lib.shmat.restype = ctypes.c_void_p
    lib.shmdt.argtypes = [ctypes.c_void_p]
    return lib


def _remove(lib, kind, identifier):
    if kind == "msg":
        result = lib.msgctl(identifier, 0, None)
    elif kind == "shm":
        result = lib.shmctl(identifier, 0, None)
    else:
        result = lib.semctl(identifier, 0, 0)
    if result != 0:
        raise RuntimeError(f"private fixture cleanup failed: {kind}, errno={ctypes.get_errno()}")


@contextmanager
def _owned_ipc(kind):
    lib = _libc()
    if kind == "msg":
        identifier = lib.msgget(0, 0o600)
    elif kind == "shm":
        identifier = lib.shmget(0, 64, 0o600)
    else:
        identifier = lib.semget(0, 1, 0o600)
    assert identifier >= 0, ctypes.get_errno()
    pointer = None
    try:
        if kind == "shm":
            pointer = lib.shmat(identifier, None, 0)
            assert pointer != ctypes.c_void_p(-1).value, ctypes.get_errno()
            ctypes.memmove(pointer, b"original", 8)
        elif kind == "sem":
            assert lib.semctl(identifier, 0, 16, 3) == 0, ctypes.get_errno()  # SETVAL

        def state():
            if kind == "shm":
                return ctypes.string_at(pointer, 8)
            if kind == "sem":
                return lib.semctl(identifier, 0, 12)  # GETVAL
            message = ctypes.create_string_buffer(ctypes.sizeof(ctypes.c_long) + 8)
            ctypes.set_errno(0)
            result = lib.msgrcv(identifier, message, 8, 0, 0o4000)  # IPC_NOWAIT
            if result == -1:
                assert ctypes.get_errno() == errno.ENOMSG
                return None
            assert result == 8
            return message.raw[ctypes.sizeof(ctypes.c_long):]

        yield identifier, state
    finally:
        original = sys.exc_info()[1]
        failures = []
        try:
            if pointer not in (None, ctypes.c_void_p(-1).value) and lib.shmdt(pointer) != 0:
                failures.append(RuntimeError("private fixture shmdt failed"))
        except (OSError, RuntimeError) as exc:
            failures.append(exc)
        finally:
            try:
                _remove(lib, kind, identifier)
            except (OSError, RuntimeError) as exc:
                failures.append(exc)
        if failures:
            if original is not None:
                for failure in failures:
                    original.add_note(str(failure))
            else:
                raise failures[0]


@pytest.mark.parametrize("kind", ["msg", "shm", "sem"])
@pytest.mark.parametrize("filtered", [False, True], ids=["baseline", "filtered"])
def test_private_parent_owned_ipc_route_and_rejection(compiled, tmp_path, kind, filtered):
    with _owned_ipc(kind) as (identifier, state):
        result = _run(compiled, tmp_path, "filtered" if filtered else "baseline", kind, identifier)
        assert result == {"result": -1 if filtered else 0, "errno": errno.EPERM if filtered else 0,
                          "received_fd": False}
        assert state() == ({"msg": None, "shm": b"original", "sem": 3}[kind] if filtered
                           else {"msg": b"IPC-MARK", "shm": b"IPC-MARK", "sem": 4}[kind])


@pytest.mark.parametrize("kind", ["msg", "shm", "sem"])
def test_v2_sealed_formal_target_cannot_use_private_host_ipc(compiled, tmp_path, kind):
    with _owned_ipc(kind) as (identifier, state):
        def mutate(data):
            data.argv = [str(compiled[0]), "formal", kind, str(identifier), str(tmp_path / "work"), "0"]

        with _start(tmp_path, compiled, mutate=mutate) as fixture:
            _release(fixture)
            assert _frame(fixture.frame).kind == "target_started"
            assert _frame(fixture.frame).kind == "terminal"
            stdout, stderr = fixture.process.communicate(timeout=5)
            assert fixture.process.returncode == 0, stderr
            assert json.loads(stdout) == {"result": -1, "errno": errno.EPERM, "received_fd": False}
        assert state() == {"msg": None, "shm": b"original", "sem": 3}[kind]


@pytest.mark.parametrize("operation", [name for name in _SYSCALLS if name != "socketpair"])
def test_raw_native_and_time64_calls_refuse_before_kernel_operation(compiled, tmp_path, operation):
    result = _run(compiled, tmp_path, "filtered", "raw", extra=operation)
    try:
        assert result == {"result": -1, "errno": errno.EPERM, "received_fd": False}
    finally:
        # Only msgget can allocate despite these deliberately invalid raw probes.
        # IPC_PRIVATE guarantees it is newly created, never an unrelated host ID.
        if operation == "msgget" and result["result"] >= 0:
            _remove(_libc(), "msg", result["result"])


@pytest.mark.parametrize("domain", [0, 2, 10, 30, 0xFFFFFFFF, 0x100000001, 0xFFFFFFFF00000001,
                                    0x100000000, 0xFFFFFFFFFFFFFFFF])
def test_socketpair_only_accepts_exact_full_argument_af_unix(compiled, tmp_path, domain):
    assert _run(compiled, tmp_path, "filtered", "pair", domain) == {
        "result": -1, "errno": errno.EPERM, "received_fd": False,
    }


def test_exact_af_unix_socketpair_still_works(compiled, tmp_path):
    assert _run(compiled, tmp_path, "filtered", "pair", socket.AF_UNIX) == {
        "result": 0, "errno": 0, "received_fd": False,
    }


def _received_fds(ancillary):
    descriptors = []
    for level, kind, data in ancillary:
        if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
            values = array.array("i")
            values.frombytes(data[:len(data) - len(data) % values.itemsize])
            descriptors.extend(values)
    return descriptors


@pytest.mark.parametrize("filtered", [False, True], ids=["baseline", "filtered"])
@pytest.mark.parametrize("rights", [False, True], ids=["bytes", "scm-rights"])
def test_direct_inherited_socket_sendmmsg_is_refused(compiled, tmp_path, filtered, rights):
    working = tmp_path / "work"
    working.mkdir()
    outside = tmp_path / "outside"
    outside.write_bytes(b"outside")
    left, right = socket.socketpair()
    file = os.open(outside, os.O_RDONLY)
    received = []
    try:
        operation = "sendmmsg-fd" if rights else "sendmmsg"
        result = _run(compiled, working, "filtered" if filtered else "baseline", operation,
                      left.fileno(), file, pass_fds=(left.fileno(), file))
        assert result == {"result": -1 if filtered else 1, "errno": errno.EPERM if filtered else 0,
                          "received_fd": False}
        right.setblocking(False)
        if filtered:
            with pytest.raises(BlockingIOError):
                right.recvmsg(8, socket.CMSG_SPACE(array.array("i").itemsize))
        else:
            content, ancillary, _, _ = right.recvmsg(8, socket.CMSG_SPACE(array.array("i").itemsize))
            received = _received_fds(ancillary)
            assert content == b"IPC-MARK"
            assert len(received) == int(rights)
            if rights:
                assert os.read(received[0], 7) == b"outside"
    finally:
        for descriptor in received:
            os.close(descriptor)
        os.close(file)
        left.close()
        right.close()


@pytest.mark.parametrize("operation", ["recvmsg", "recvmmsg"])
@pytest.mark.parametrize("filtered", [False, True], ids=["baseline", "filtered"])
def test_direct_inherited_socket_cannot_receive_ancillary_fds(compiled, tmp_path, operation, filtered):
    working = tmp_path / "work"
    working.mkdir()
    outside = tmp_path / "outside"
    outside.write_bytes(b"outside")
    left, right = socket.socketpair()
    file = os.open(outside, os.O_RDONLY)
    try:
        assert right.sendmsg([b"IPC-MARK"], [(socket.SOL_SOCKET, socket.SCM_RIGHTS,
                                            array.array("i", [file]))]) == 8
        result = _run(compiled, working, "filtered" if filtered else "baseline", operation,
                      left.fileno(), pass_fds=(left.fileno(),))
        assert result == {"result": -1 if filtered else (8 if operation == "recvmsg" else 1),
                          "errno": errno.EPERM if filtered else 0, "received_fd": not filtered}
    finally:
        # Closing queued SCM_RIGHTS messages releases kernel-held references too.
        os.close(file)
        left.close()
        right.close()


def test_filtered_ordinary_pipe_file_fork_thread_and_socketpair(compiled, tmp_path):
    assert _run(compiled, tmp_path, "filtered", "ordinary") == {"ordinary": True, "broker": False}
    assert (tmp_path / "ordinary").read_bytes() == b"te"


@pytest.mark.parametrize("broker", [False, True])
def test_v2_sealed_target_keeps_useful_io_and_original_fd_closure(compiled, tmp_path, broker):
    def mutate(data):
        data.argv = [str(compiled[0]), "formal", "ordinary", str(data.target_fd), str(tmp_path / "work"), "0"]

    with _start(tmp_path, compiled, mutate=mutate, broker=broker) as fixture:
        if broker:
            os.write(fixture.response, b"pong")
        _release(fixture)
        assert _frame(fixture.frame).kind == "target_started"
        assert _frame(fixture.frame).kind == "terminal"
        stdout, stderr = fixture.process.communicate(timeout=5)
        assert fixture.process.returncode == 0, stderr
        assert json.loads(stdout) == {"ordinary": True, "broker": broker}
        assert (fixture.working / "ordinary").read_bytes() == b"te"
        if broker:
            assert os.read(fixture.request, 4) == b"ping"
