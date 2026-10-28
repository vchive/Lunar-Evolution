"""Real REGISTER descriptors through the production native wire/check helpers.

This finite receiver is not the installed supervisor or cgroup acceptance. It
never changes credentials. Positive root-owned publication checks require an
already-root runner; an ordinary developer run must observe the native refusal.
"""
from __future__ import annotations

import array
import os
import platform
import shutil
import socket
import struct
import subprocess
import sys
import time

import pytest
from test_native_original_publication import _publish

from lunar_evolution import native_bootstrap
from lunar_evolution.native_original_publication import hold_native_original_publications

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or platform.machine().lower() not in {"x86_64", "amd64"},
    reason="finite native Linux x86-64 publication receiver",
)

_RECEIVER = r'''
#define _GNU_SOURCE
#include "native_whole_scope_platform.h"
#include <stdlib.h>
int main(int argc, char **argv) {
    if (argc != 3) return 64;
    int endpoint = atoi(argv[1]);
    uint64_t deadline = strtoull(argv[2], NULL, 10);
    if (wq_socket(endpoint)) return 64;
    wq_binding_t expected;
    memset(&expected, 0, sizeof(expected));
    expected.deadline_ns = deadline;
    expected.candidate_uid = 1000; expected.candidate_gid = 1000;
    char *hashes[] = {expected.launch_sha256, expected.intent_sha256, expected.target_sha256,
        expected.bootstrap_sha256, expected.supervisor_sha256, expected.profile_sha256};
    for (size_t i = 0; i < 6; ++i) memset(hashes[i], 'a', 64);
    wq_message_t message;
    int originals[3];
    if (wq_receive(endpoint, &message, originals, 3, deadline)) return 65;
    if (wq_message_check(&message, &expected, WQ_REGISTER, 1, 3) ||
        wq_fd_distinct(originals, 3)) return 66;
    int result = 0;
    for (size_t i = 0; i < 3; ++i)
        if (wq_publication_check(originals[i], &message.publications[i], deadline)) result = 67;
    for (size_t i = 0; i < 3; ++i) close(originals[i]);
    return result;
}
'''


@pytest.fixture(scope="module")
def native_receiver(tmp_path_factory):
    compiler = shutil.which("cc") or shutil.which("gcc")
    if compiler is None:
        pytest.skip("native receiver compiler unavailable")
    directory = tmp_path_factory.mktemp("native-original-publication")
    source, executable = directory / "receiver.c", directory / "receiver"
    source.write_text(_RECEIVER)
    subprocess.run(
        [compiler, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-I",
         str(native_bootstrap.native_bootstrap_source_path().parent), str(source), "-o", str(executable)],
        check=True, capture_output=True, timeout=30, env={"PATH": os.defpath, "LANG": "C"},
    )
    return executable


def _receive(executable, descriptors, pins, *, pin_change=None):
    deadline = time.monotonic_ns() + 5_000_000_000
    binding = struct.pack("<Q65s65s65s65s65s65sIII32I", deadline,
                          *((b"a" * 64,) * 6), 1000, 1000, 0, *((0,) * 32))
    raw_pins = []
    for index, pin in enumerate(pins):
        digest, size, device, inode, mtime, ctime = pin
        values = [device, inode, size, mtime, ctime, digest.encode("ascii")]
        if pin_change is not None and index == 0:
            selected = pin_change
            values[selected] = b"b" * 64 if selected == 5 else values[selected] + 1
        raw_pins.append(struct.pack("<5Q65s", *values))
    packet = (struct.pack("<6I", 0x3151574C, 1, 5, 1, 3, 0) + binding
              + bytes(40 + 8) + b"".join(raw_pins))
    assert len(packet) == 925
    sender, receiver = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    with sender, receiver:
        sender.sendmsg([packet], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", descriptors))])
        return subprocess.run(
            [str(executable), str(receiver.fileno()), str(deadline)],
            pass_fds=(receiver.fileno(),), check=False, capture_output=True,
            timeout=5, env={"PATH": os.defpath, "LANG": "C"},
        ).returncode


def test_native_register_consumes_actual_creator_fds_and_requires_root_publications(tmp_path, native_receiver):
    with hold_native_original_publications() as owner:
        _publish(owner, tmp_path)
        descriptors, pins = owner._borrow_for_native_transfer()
        expected = 0 if os.geteuid() == 0 and os.getegid() == 0 else 67
        assert _receive(native_receiver, descriptors, pins) == expected


def test_native_register_rejects_missing_original_rights(tmp_path, native_receiver):
    with hold_native_original_publications() as owner:
        _publish(owner, tmp_path)
        descriptors, pins = owner._borrow_for_native_transfer()
        assert _receive(native_receiver, descriptors[:2], pins) == 65


def test_native_register_rejects_same_original_under_two_roles(tmp_path, native_receiver):
    with hold_native_original_publications() as owner:
        _publish(owner, tmp_path)
        descriptors, pins = owner._borrow_for_native_transfer()
        assert _receive(native_receiver, (descriptors[0], descriptors[0], descriptors[2]), pins) == 66


@pytest.mark.skipif(os.geteuid() != 0 or os.getegid() != 0,
                    reason="positive native root-owned publication prerequisite; never elevate")
@pytest.mark.parametrize("pin_change", range(6))
def test_native_register_checks_every_original_publication_pin(tmp_path, native_receiver, pin_change):
    with hold_native_original_publications() as owner:
        _publish(owner, tmp_path)
        descriptors, pins = owner._borrow_for_native_transfer()
        assert _receive(native_receiver, descriptors, pins) == 0
        assert _receive(native_receiver, descriptors, pins, pin_change=pin_change) == 67
