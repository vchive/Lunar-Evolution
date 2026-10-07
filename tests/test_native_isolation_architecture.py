"""Compile the real header's unsupported Linux ABI branch on the current host."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


def test_unsupported_linux_architecture_refuses_even_with_modern_syscall_names(tmp_path):
    compiler = shutil.which("clang") or shutil.which("cc")
    if compiler is None:
        pytest.skip("local C compiler unavailable")
    source = tmp_path / "unsupported-architecture.c"
    target = tmp_path / "unsupported-architecture"
    source.write_text(r'''
/* Load host types before changing only the header's ABI selection macros. */
#include <errno.h>
#include <stddef.h>
#include <string.h>
#include <sys/types.h>
#undef __APPLE__
#undef __x86_64__
#undef __aarch64__
#undef __i386__
#ifndef __linux__
#define __linux__ 1
#endif
/* New headers must not make an unsupported ABI fall through to Landlock. */
#undef __NR_fchmodat2
#undef __NR_clone3
#undef __NR_pidfd_send_signal
#undef __NR_io_uring_setup
#undef __NR_io_uring_enter
#undef __NR_io_uring_register
#define __NR_fchmodat2 452
#define __NR_clone3 435
#define __NR_pidfd_send_signal 424
#define __NR_io_uring_setup 425
#define __NR_io_uring_enter 426
#define __NR_io_uring_register 427
#include "native_producer_isolation.h"
int main(void) {
    return lunar_apply_isolation("linux-landlock-seccomp-v1", 0, 0, 0, 0) == ENOTSUP ? 0 : 1;
}
''', encoding="utf-8")
    # The actual header is compiled, with no model, target campaign or network.
    # This checks its unsupported branch; it is not Linux enforcement evidence.
    subprocess.run(
        [compiler, "-Wall", "-Wextra", "-Werror", "-I",
         str(Path(__file__).parents[1] / "src/lunar_evolution"), str(source), "-o", str(target)],
        check=True, capture_output=True, timeout=30, env={"PATH": os.defpath, "LANG": "C"},
    )
    result = subprocess.run([str(target)], check=False, capture_output=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr
