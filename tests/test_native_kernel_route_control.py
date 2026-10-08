"""Local Linux probes for kernel-global routes outside the path/IPC contract.

The fixture only uses malformed/empty arguments so an unfiltered process cannot
touch a host object.  A filtered result must be EPERM before kernel argument
validation.  This is a bounded deny contract, not a claim of complete Linux
containment or remote-worker isolation.
"""

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

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="Linux kernel route controls")

_SOURCE = r'''
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <sys/syscall.h>
#include <unistd.h>
#include "native_producer_isolation.h"

#if defined(__NR_bpf)
_Static_assert(LUNAR_NR_BPF == __NR_bpf, "bpf UAPI");
#endif
#if defined(__NR_perf_event_open)
_Static_assert(LUNAR_NR_PERF_EVENT_OPEN == __NR_perf_event_open, "perf UAPI");
#endif
#if defined(__NR_userfaultfd)
_Static_assert(LUNAR_NR_USERFAULTFD == __NR_userfaultfd, "userfaultfd UAPI");
#endif
#if defined(__NR_fanotify_init)
_Static_assert(LUNAR_NR_FANOTIFY_INIT == __NR_fanotify_init, "fanotify UAPI");
#endif

static int denied(long number) {
    errno = 0;
    long result = syscall(number, 0L, 0L, 0L, 0L, 0L, 0L);
    printf("{\"result\":%ld,\"errno\":%d}\n", result, errno);
    return result == -1 && errno == EPERM ? 0 : 20;
}

static int ordinary(const char *root) {
    int pipefd[2];
    char buffer[4];
    if (pipe(pipefd) || write(pipefd[1], "ping", 4) != 4 ||
        read(pipefd[0], buffer, 4) != 4 || memcmp(buffer, "ping", 4) ||
        close(pipefd[0]) || close(pipefd[1])) return 30;
    char path[4096];
    if (snprintf(path, sizeof(path), "%s/ordinary", root) >= (int)sizeof(path)) return 31;
    int fd = open(path, O_CREAT | O_RDWR | O_TRUNC, 0600);
    if (fd < 0 || write(fd, "ok", 2) != 2 || close(fd)) return 32;
    puts("{\"ordinary\":true}");
    return 0;
}

int main(int argc, char **argv) {
    if (argc != 3) return 2;
    const char *writes[] = {argv[1]};
    if (lunar_apply_isolation("linux-landlock-seccomp-v1", NULL, 0, writes, 1)) return 3;
    if (!strcmp(argv[2], "ordinary")) return ordinary(argv[1]);
    if (!strcmp(argv[2], "bpf")) return denied(LUNAR_NR_BPF);
    if (!strcmp(argv[2], "perf_event_open")) return denied(LUNAR_NR_PERF_EVENT_OPEN);
    if (!strcmp(argv[2], "userfaultfd")) return denied(LUNAR_NR_USERFAULTFD);
    if (!strcmp(argv[2], "fanotify_init")) return denied(LUNAR_NR_FANOTIFY_INIT);
    if (!strcmp(argv[2], "name_to_handle_at")) return denied(LUNAR_NR_NAME_TO_HANDLE_AT);
    if (!strcmp(argv[2], "open_by_handle_at")) return denied(LUNAR_NR_OPEN_BY_HANDLE_AT);
    if (!strcmp(argv[2], "mount")) return denied(LUNAR_NR_MOUNT);
    if (!strcmp(argv[2], "umount2")) return denied(LUNAR_NR_UMOUNT2);
    if (!strcmp(argv[2], "pivot_root")) return denied(LUNAR_NR_PIVOT_ROOT);
    if (!strcmp(argv[2], "chroot")) return denied(LUNAR_NR_CHROOT);
    return 4;
}
'''

_ROUTES = (
    "bpf", "perf_event_open", "userfaultfd", "fanotify_init",
    "name_to_handle_at", "open_by_handle_at", "mount", "umount2",
    "pivot_root", "chroot",
)


@pytest.fixture(scope="module")
def compiled(tmp_path_factory):
    root = tmp_path_factory.mktemp("native-kernel-routes")
    source, target = root / "target.c", root / "target"
    source.write_text(_SOURCE, encoding="utf-8")
    compile_native_target(source, target, "-I", str(Path(__file__).parents[1] / "src/lunar_evolution"))
    return SimpleNamespace(target=target)


def _run(compiled, root: Path, route: str) -> dict[str, object]:
    result = subprocess.run(
        [str(compiled.target), str(root), route],
        close_fds=True,
        capture_output=True,
        timeout=5,
        check=False,
        env={"PATH": os.defpath, "LANG": "C"},
    )
    if result.returncode == 3:
        pytest.skip("host kernel lacks the required Landlock/seccomp boundary")
    assert result.returncode == 0, (result.returncode, result.stdout, result.stderr)
    return json.loads(result.stdout)


@pytest.mark.parametrize("route", _ROUTES)
def test_kernel_global_routes_refuse_before_argument_validation(compiled, tmp_path, route):
    assert _run(compiled, tmp_path, route) == {"result": -1, "errno": errno.EPERM}


def test_kernel_route_filter_preserves_pipe_and_declared_file_io(compiled, tmp_path):
    assert _run(compiled, tmp_path, "ordinary") == {"ordinary": True}
    assert (tmp_path / "ordinary").read_bytes() == b"ok"
