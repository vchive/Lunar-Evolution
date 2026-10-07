"""Actual inert Linux mutation gates, with owned-file controls and host checks.

No inherited writable descriptor, network, model or producer campaign is used.
ABI-query fault injection tests the real boundary's rejection branch separately
from the actual kernel enforcement fixtures.
"""

from __future__ import annotations

import errno
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest
from _native_target_fixture import compile_native_target

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="actual Linux Landlock/seccomp fixture")

_SOURCE = r'''
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/time.h>
#include <sys/xattr.h>
#include <unistd.h>
#include <utime.h>
#include <linux/landlock.h>
#ifdef OLD_HEADERS
#undef LANDLOCK_CREATE_RULESET_VERSION
#undef LANDLOCK_ACCESS_FS_REFER
#undef LANDLOCK_ACCESS_FS_TRUNCATE
#undef __NR_setxattrat
#undef __NR_removexattrat
#undef __NR_chown32
#undef __NR_lchown32
#undef __NR_fchown32
#undef __NR_utimensat_time64
#endif
#include "native_producer_isolation.h"

struct fixture_xattr_args { uint64_t value; uint32_t size; uint32_t flags; };
static long mutate(const char *operation, const char *path, int fd) {
    uid_t uid = getuid(); gid_t gid = getgid();
    struct utimbuf seconds = {1234567890, 1234567891};
    struct timeval micros[2] = {{1234567890, 0}, {1234567891, 0}};
    struct timespec nanos[2] = {{1234567890, 0}, {1234567891, 0}};
    const char *name = "user.lunar-mutation-fixture", *value = "changed";
    struct fixture_xattr_args args = {(uint64_t)(uintptr_t)value, 7, 0};
    #ifdef __NR_chown
    if (!strcmp(operation, "chown")) return syscall(__NR_chown, path, uid, gid);
    #endif
    #ifdef __NR_lchown
    if (!strcmp(operation, "lchown")) return syscall(__NR_lchown, path, uid, gid);
    #endif
    #ifdef __NR_fchown
    if (!strcmp(operation, "fchown")) return syscall(__NR_fchown, fd, uid, gid);
    #endif
    #ifdef __NR_fchownat
    if (!strcmp(operation, "fchownat")) return syscall(__NR_fchownat, AT_FDCWD, path, uid, gid, 0);
    #endif
    #ifdef LUNAR_NR_CHOWN32
    if (!strcmp(operation, "chown32")) return syscall(LUNAR_NR_CHOWN32, path, uid, gid);
    #endif
    #ifdef LUNAR_NR_LCHOWN32
    if (!strcmp(operation, "lchown32")) return syscall(LUNAR_NR_LCHOWN32, path, uid, gid);
    #endif
    #ifdef LUNAR_NR_FCHOWN32
    if (!strcmp(operation, "fchown32")) return syscall(LUNAR_NR_FCHOWN32, fd, uid, gid);
    #endif
    #ifdef __NR_utime
    if (!strcmp(operation, "utime")) return syscall(__NR_utime, path, &seconds);
    #else
    (void)seconds;
    #endif
    #ifdef __NR_utimes
    if (!strcmp(operation, "utimes")) return syscall(__NR_utimes, path, micros);
    #endif
    #ifdef __NR_futimesat
    if (!strcmp(operation, "futimesat")) return syscall(__NR_futimesat, AT_FDCWD, path, micros);
    #endif
    #if !defined(__NR_utimes) && !defined(__NR_futimesat)
    (void)micros;
    #endif
    #ifdef __NR_utimensat
    if (!strcmp(operation, "utimensat")) return syscall(__NR_utimensat, AT_FDCWD, path, nanos, 0);
    if (!strcmp(operation, "utimensat_fd")) return syscall(__NR_utimensat, fd, NULL, nanos, 0);
    #endif
    #ifdef LUNAR_NR_UTIMENSAT_TIME64
    if (!strcmp(operation, "utimensat_time64")) {
        int64_t time64[4] = {1234567890, 0, 1234567891, 0};
        return syscall(LUNAR_NR_UTIMENSAT_TIME64, AT_FDCWD, path, time64, 0);
    }
    #endif
    #ifdef __NR_setxattr
    if (!strcmp(operation, "setxattr")) return syscall(__NR_setxattr, path, name, value, 7, 0);
    #endif
    #ifdef __NR_lsetxattr
    if (!strcmp(operation, "lsetxattr")) return syscall(__NR_lsetxattr, path, name, value, 7, 0);
    #endif
    #ifdef __NR_fsetxattr
    if (!strcmp(operation, "fsetxattr")) return syscall(__NR_fsetxattr, fd, name, value, 7, 0);
    #endif
    #ifdef __NR_removexattr
    if (!strcmp(operation, "removexattr")) return syscall(__NR_removexattr, path, name);
    #endif
    #ifdef __NR_lremovexattr
    if (!strcmp(operation, "lremovexattr")) return syscall(__NR_lremovexattr, path, name);
    #endif
    #ifdef __NR_fremovexattr
    if (!strcmp(operation, "fremovexattr")) return syscall(__NR_fremovexattr, fd, name);
    #endif
    if (!strcmp(operation, "setxattrat"))
        return syscall(LUNAR_NR_SETXATTRAT, AT_FDCWD, path, 0, name, &args, sizeof(args));
    if (!strcmp(operation, "removexattrat"))
        return syscall(LUNAR_NR_REMOVEXATTRAT, AT_FDCWD, path, 0, name);
    errno = ENOSYS; return -2; /* This operation is absent from the native ABI. */
}
static int output_io(const char *work) {
    if (chdir(work) || mkdir("nested", 0700)) return 20;
    int fd = open("nested/result", O_CREAT | O_RDWR, 0600);
    if (fd < 0 || write(fd, "abcdef", 6) != 6 || ftruncate(fd, 3) ||
        lseek(fd, 0, SEEK_SET) != 0) return 21;
    char data[8] = {0};
    if (read(fd, data, sizeof(data)) != 3 || strcmp(data, "abc") || close(fd)) return 22;
    if (truncate("nested/result", 1)) return 23;
    fd = open("nested/result", O_WRONLY | O_TRUNC);
    if (fd < 0 || write(fd, "output", 6) != 6 || close(fd)) return 24;
    return 0;
}
static int metadata_reads(const char *path) {
    struct stat by_path, by_link, by_fd;
    int fd = open(path, O_RDONLY);
    if (fd < 0 || stat(path, &by_path) || lstat(path, &by_link) || fstat(fd, &by_fd)) return 30;
    if (by_path.st_ino != by_fd.st_ino || by_link.st_ino != by_fd.st_ino ||
        by_fd.st_size != 15 || (by_fd.st_mode & 0777) != 0600) return 31;
    const char *name = "user.lunar-mutation-fixture";
    char value[64] = {0}, names[128] = {0};
    if (getxattr(path, name, value, sizeof(value)) != 7 || strcmp(value, "initial") ||
        lgetxattr(path, name, value, sizeof(value)) != 7 ||
        fgetxattr(fd, name, value, sizeof(value)) != 7 ||
        listxattr(path, names, sizeof(names)) <= 0 ||
        llistxattr(path, names, sizeof(names)) <= 0 ||
        flistxattr(fd, names, sizeof(names)) <= 0) return 32;
    struct fixture_xattr_args args = {(uint64_t)(uintptr_t)value, sizeof(value), 0};
    errno = 0;
    long result = syscall(464, AT_FDCWD, path, 0, name, &args, sizeof(args));
    if (result != 7 && !(result == -1 && errno == ENOSYS)) return 33;
    errno = 0;
    result = syscall(465, AT_FDCWD, path, 0, names, sizeof(names));
    if (result <= 0 && !(result == -1 && errno == ENOSYS)) return 34;
    return close(fd) ? 35 : 0;
}
int main(int argc, char **argv) {
    if (argc == 2 && !strcmp(argv[1], "abi")) {
        errno = 0; long abi = syscall(__NR_landlock_create_ruleset, NULL, 0, LANDLOCK_CREATE_RULESET_VERSION);
        printf("{\"abi\":%ld,\"errno\":%d}\n", abi, errno); return 0;
    }
    if (argc != 7) return 2;
    const char *mode = argv[1], *input = argv[2], *work = argv[3];
    const char *operation = argv[4], *path = argv[5];
    int bound = atoi(argv[6]);
    if (strcmp(mode, "control")) {
        const char *reads[] = {input}, *writes[] = {work};
        int result = lunar_apply_isolation("linux-landlock-seccomp-v1", reads, bound ? 1 : 0, writes, 1);
        if (result) { printf("{\"isolation\":%d}\n", result); return 0; }
    }
    if (!strcmp(operation, "output_io")) return output_io(work);
    if (!strcmp(operation, "metadata_reads")) return metadata_reads(path);
    errno = 0; long result;
    if (!strcmp(operation, "truncate")) result = truncate(path, 1);
    #ifdef __NR_truncate
    else if (!strcmp(operation, "raw_truncate")) result = syscall(__NR_truncate, path, 1);
    #endif
    #ifdef __NR_truncate64
    else if (!strcmp(operation, "raw_truncate64")) result = syscall(__NR_truncate64, path, 1, 0);
    #endif
    else {
        int fd = open(path, bound ? O_RDONLY : O_RDWR);
        if (fd < 0) return 3;
        errno = 0; result = mutate(operation, path, fd);
        int saved = errno;
        if (close(fd)) return 4;
        errno = saved;
    }
    printf("{\"result\":%ld,\"errno\":%d}\n", result, errno); return 0;
}
'''

_MUTATIONS = (
    "chown", "lchown", "fchown", "fchownat", "chown32", "lchown32", "fchown32",
    "utime", "utimes", "futimesat", "utimensat", "utimensat_fd", "utimensat_time64",
    "setxattr", "lsetxattr", "fsetxattr", "removexattr", "lremovexattr", "fremovexattr",
    "setxattrat", "removexattrat",
)
_MODERN_XATTR = {"setxattrat", "removexattrat"}
_XATTR_NAME = "user.lunar-mutation-fixture"


@pytest.fixture(scope="module", params=(False, True), ids=("current-headers", "old-headers"))
def mutation_target(tmp_path_factory, request):
    directory = tmp_path_factory.mktemp("input-mutation")
    source, target = directory / "mutation.c", directory / "mutation"
    source.write_text(_SOURCE, encoding="utf-8")
    flags = ("-DOLD_HEADERS=1",) if request.param else ()
    compile_native_target(
        source, target, "-I", str(Path(__file__).parents[1] / "src/lunar_evolution"), *flags,
    )
    return target


@pytest.fixture
def supported_target(mutation_target):
    actual = _run(mutation_target, "abi")
    if actual["abi"] < 3:
        pytest.skip(f"actual kernel lacks Landlock ABI>=3: {actual}")
    return mutation_target


def _run(target: Path, *args: object) -> dict:
    completed = subprocess.run(
        [str(target), *map(str, args)], capture_output=True, timeout=5, check=False,
        env={"PATH": os.defpath, "LANG": "C"},
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return json.loads(completed.stdout) if completed.stdout else {}


def _material(path: Path, *, xattr: bool = False) -> None:
    path.write_bytes(b"immutable-input")
    path.chmod(0o600)  # Unfiltered owned-file mutations must be genuinely possible.
    if xattr:
        try:
            os.setxattr(path, _XATTR_NAME, b"initial")
        except OSError as exc:
            if exc.errno in {errno.ENOTSUP, errno.EOPNOTSUPP}:
                pytest.skip("disposable fixture filesystem has no user xattrs")
            raise


def _snapshot(path: Path) -> tuple:
    data = path.read_bytes()
    info = path.stat()
    attrs = tuple(sorted((key, os.getxattr(path, key)) for key in os.listxattr(path)))
    # Reading legitimately updates atime; mtime/ctime are independent mutation evidence.
    return (
        data, info.st_size, stat.S_IMODE(info.st_mode), info.st_uid, info.st_gid,
        info.st_mtime_ns, info.st_ctime_ns, attrs,
    )


def test_actual_kernel_capability_refuses_unsupported_boundary(mutation_target, tmp_path):
    abi = _run(mutation_target, "abi")
    work = tmp_path / "work"
    work.mkdir()
    material = tmp_path / "input"
    _material(material)
    result = _run(mutation_target, "isolated", material, work, "output_io", material, 1)
    if abi["abi"] < 3:
        assert result == {"isolation": errno.ENOTSUP}
        assert not (work / "nested").exists()
    else:
        assert result == {}
        assert (work / "nested" / "result").read_bytes() == b"output"
    assert material.read_bytes() == b"immutable-input"


@pytest.mark.parametrize("operation", _MUTATIONS)
@pytest.mark.parametrize("subject", ("input", "output"))
def test_bound_read_denies_metadata_mutations_with_independent_host_snapshot(
    supported_target, tmp_path, operation, subject,
):
    work = tmp_path / "work"
    work.mkdir()
    material, control = tmp_path / "input", tmp_path / "control"
    _material(material, xattr="xattr" in operation)
    _material(control, xattr="xattr" in operation)
    victim = material if subject == "input" else work / "output"
    if subject == "output":
        _material(victim, xattr="xattr" in operation)
    unfiltered = _run(supported_target, "control", material, work, operation, control, 0)
    if unfiltered["result"] == -2:
        pytest.skip(f"{operation} is absent from the actual native ABI")
    if operation in _MODERN_XATTR and unfiltered == {"result": -1, "errno": errno.ENOSYS}:
        # The new syscall number must still hit seccomp before an older kernel
        # can return ENOSYS; never skip its bound-input deny rule.
        pass
    else:
        assert unfiltered == {"result": 0, "errno": 0}, (operation, unfiltered)
    before = _snapshot(victim)
    denied = _run(supported_target, "isolated", material, work, operation, victim, 1)
    assert denied == {"result": -1, "errno": errno.EPERM}, (operation, denied)
    assert _snapshot(victim) == before


@pytest.mark.parametrize("operation", _MUTATIONS)
def test_no_read_grants_preserve_work_metadata_behavior(supported_target, tmp_path, operation):
    work = tmp_path / "work"
    work.mkdir()
    material, control, output = tmp_path / "input", tmp_path / "control", work / "output"
    for path in (material, control, output):
        _material(path, xattr="xattr" in operation)
    unfiltered = _run(supported_target, "control", material, work, operation, control, 0)
    if unfiltered["result"] == -2:
        pytest.skip(f"{operation} is absent from the actual native ABI")
    if operation in _MODERN_XATTR and unfiltered == {"result": -1, "errno": errno.ENOSYS}:
        expected = unfiltered
    else:
        assert unfiltered == {"result": 0, "errno": 0}, (operation, unfiltered)
        expected = {"result": 0, "errno": 0}
    assert _run(supported_target, "isolated", material, work, operation, output, 0) == expected
    assert output.read_bytes() == b"immutable-input"
    if operation.startswith("utime") or operation == "futimesat":
        assert output.stat().st_mtime_ns == 1234567891 * 1_000_000_000
    elif "setxattr" in operation and expected["result"] == 0:
        assert os.getxattr(output, _XATTR_NAME) == b"changed"
    elif "removexattr" in operation and expected["result"] == 0:
        assert _XATTR_NAME not in os.listxattr(output)


@pytest.mark.parametrize("operation", ("truncate", "raw_truncate", "raw_truncate64"))
@pytest.mark.parametrize("subject", ("input", "outside"))
def test_pathname_truncation_is_denied_by_landlock_not_file_mode(
    supported_target, tmp_path, operation, subject,
):
    if operation == "raw_truncate64" and not sys.maxsize < 2**32:
        pytest.skip("truncate64 is an explicit 32-bit ABI entry")
    work = tmp_path / "work"
    work.mkdir()
    material, outside, control = tmp_path / "input", tmp_path / "outside", tmp_path / "control"
    for path in (material, outside, control):
        _material(path)
    assert _run(supported_target, "control", material, work, operation, control, 0) == {
        "result": 0, "errno": 0,
    }
    assert control.read_bytes() == b"i"
    victim = material if subject == "input" else outside
    before = _snapshot(victim)
    denied = _run(supported_target, "isolated", material, work, operation, victim, 1)
    assert denied["result"] == -1 and denied["errno"] in {errno.EACCES, errno.EPERM}
    assert _snapshot(victim) == before


@pytest.mark.parametrize("bound", (False, True))
def test_output_creation_read_write_and_truncation_remain_available(supported_target, tmp_path, bound):
    work = tmp_path / "work"
    work.mkdir()
    material = tmp_path / "input"
    _material(material)
    before = _snapshot(material)
    assert _run(supported_target, "isolated", material, work, "output_io", material, int(bound)) == {}
    assert (work / "nested" / "result").read_bytes() == b"output"
    assert stat.S_IMODE((work / "nested" / "result").stat().st_mode) == 0o600
    assert _snapshot(material) == before


def test_bound_input_metadata_and_xattr_reads_remain_available(supported_target, tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    material = tmp_path / "input"
    _material(material, xattr=True)
    before = _snapshot(material)
    assert _run(supported_target, "isolated", material, work, "metadata_reads", material, 1) == {}
    assert _snapshot(material) == before


_QUERY_SOURCE = r'''
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdarg.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <unistd.h>
#include <signal.h>
#include <linux/audit.h>
#include <linux/filter.h>
#include <linux/landlock.h>
#include <linux/seccomp.h>
#include <sys/prctl.h>
#include <sys/syscall.h>
static int requested, unexpected;
static long fixture_syscall(long number, ...) {
    va_list args; va_start(args, number);
    void *attr = va_arg(args, void *);
    int size = va_arg(args, int);
    int flags = va_arg(args, int);
    va_end(args);
    if (number != __NR_landlock_create_ruleset || attr != NULL || size != 0 || flags != 1)
        unexpected++;
    requested++;
    errno = ENOSYS;
    return QUERY_ABI;
}
#undef LANDLOCK_CREATE_RULESET_VERSION
#undef LANDLOCK_ACCESS_FS_REFER
#undef LANDLOCK_ACCESS_FS_TRUNCATE
#define syscall fixture_syscall
#include "native_producer_isolation.h"
#undef syscall
int main(void) {
    int prior_privilege = prctl(PR_GET_NO_NEW_PRIVS, 0, 0, 0, 0);
    int result = lunar_apply_isolation("linux-landlock-seccomp-v1", NULL, 0, NULL, 0);
    if (result != ENOTSUP || requested != 1 || unexpected != 0) return 2;
    if (prior_privilege < 0 || prctl(PR_GET_NO_NEW_PRIVS, 0, 0, 0, 0) != prior_privilege) return 3;
    /* Reaching a caller's exec continuation is forbidden after rejection. */
    if (result == 0) { puts("target-exec-continuation"); return 4; }
    return 0;
}
'''


@pytest.mark.parametrize("queried_abi", (-1, 0, 1, 2))
def test_actual_boundary_rejects_abi2_and_query_errors_before_policy_or_exec(tmp_path, queried_abi):
    source, target = tmp_path / "query.c", tmp_path / "query"
    source.write_text(_QUERY_SOURCE, encoding="utf-8")
    compile_native_target(
        source, target, "-I", str(Path(__file__).parents[1] / "src/lunar_evolution"),
        f"-DQUERY_ABI={queried_abi}",
    )
    assert _run(target) == {}
