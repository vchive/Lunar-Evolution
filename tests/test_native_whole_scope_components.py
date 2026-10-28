"""Actual native packet ownership and fake-filesystem refusal, without a profile.

This harness consumes the production implementation. It never acquires a
delegation, installs a profile, changes credentials or releases a candidate.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys

import pytest

from lunar_evolution.native_whole_scope_build import native_whole_scope_source_paths

_HARNESS = r'''
#define main installed_scope_main
#include "native_whole_scope.c"
#undef main
#include <assert.h>

static int descriptor_count(void) {
    DIR *directory = opendir("/proc/self/fd");
    assert(directory);
    int count = 0;
    struct dirent *entry;
    while ((entry = readdir(directory)))
        if (strcmp(entry->d_name, ".") && strcmp(entry->d_name, ".."))
            count++;
    assert(!closedir(directory));
    return count;
}

static void packet(int socket_fd, const void *bytes, size_t size, int fd, size_t count) {
    struct iovec vector = {(void *)bytes, size};
    unsigned char ancillary[CMSG_SPACE(2 * sizeof(int))];
    struct msghdr header;
    memset(&header, 0, sizeof(header));
    memset(ancillary, 0, sizeof(ancillary));
    header.msg_iov = &vector;
    header.msg_iovlen = 1;
    if (count) {
        assert(count <= 2);
        header.msg_control = ancillary;
        header.msg_controllen = CMSG_SPACE(count * sizeof(int));
        struct cmsghdr *control = CMSG_FIRSTHDR(&header);
        control->cmsg_level = SOL_SOCKET;
        control->cmsg_type = SCM_RIGHTS;
        control->cmsg_len = CMSG_LEN(count * sizeof(int));
        int descriptors[2] = {fd, fd};
        memcpy(CMSG_DATA(control), descriptors, count * sizeof(int));
    }
    assert(sendmsg(socket_fd, &header, MSG_NOSIGNAL) == (ssize_t)size);
}

int main(int argc, char **argv) {
    assert(argc == 2);
    uint64_t now;
    assert(!wq_now(&now));
    uint64_t deadline = now + 5000000000ULL;
    wq_binding_t binding;
    memset(&binding, 0, sizeof(binding));
    binding.deadline_ns = deadline;
    binding.candidate_uid = 65534;
    binding.candidate_gid = 65534;
    char *digests[6] = {binding.launch_sha256, binding.intent_sha256, binding.target_sha256,
                       binding.bootstrap_sha256, binding.supervisor_sha256, binding.profile_sha256};
    for (size_t i = 0; i < 6; i++)
        memset(digests[i], 'a' + (int)i, 64);
    assert(!wq_binding_valid(&binding));
    int sockets[2];
    assert(!socketpair(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC | SOCK_NONBLOCK, 0, sockets));
    assert(!wq_socket(sockets[0]) && !wq_socket(sockets[1]));
    int material = open(argv[1], O_RDWR | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
    assert(material >= 0);
    wq_message_t message, received;
    wq_message_init(&message, &binding, WQ_REGISTER, 1, 1);
    int baseline = descriptor_count();

    /* Short, oversized and wrong-count packets must close every acquired FD. */
    for (size_t variant = 0; variant < 3; variant++) {
        unsigned char raw[sizeof(message) + 1];
        memcpy(raw, &message, sizeof(message));
        raw[sizeof(message)] = 0;
        size_t size = variant == 0 ? sizeof(message) - 1 :
                      variant == 1 ? sizeof(message) + 1 : sizeof(message);
        packet(sockets[0], raw, size, material, variant == 2 ? 2 : 1);
        int right = -1;
        errno = 0;
        assert(wq_receive(sockets[1], &received, &right, 1, deadline));
        assert(errno == EPROTO && right == -1 && descriptor_count() == baseline);
    }
    /* Exact frame transport does not excuse a nonce mismatch or role alias. */
    assert(!wq_send(sockets[0], &message, &material, 1));
    int right = -1;
    assert(!wq_receive(sockets[1], &received, &right, 1, deadline));
    assert(fcntl(right, F_GETFD) & FD_CLOEXEC);
    assert(!wq_message_check(&received, &binding, WQ_REGISTER, 1, 1));
    received.binding.launch_sha256[0] = 'f';
    assert(wq_message_check(&received, &binding, WQ_REGISTER, 1, 1));
    close(right);
    message.fd_count = 2;
    packet(sockets[0], &message, sizeof(message), material, 2);
    int aliases[2] = {-1, -1};
    assert(!wq_receive(sockets[1], &received, aliases, 2, deadline));
    assert(wq_fd_distinct(aliases, 2));
    close(aliases[0]);
    close(aliases[1]);
    assert(descriptor_count() == baseline);

    /* Neither ordinary-file EOF nor fabricated populated=0 is a scope fact. */
    scope_t fake;
    memset(&fake, 0, sizeof(fake));
    fake.deadline = deadline;
    fake.files[4] = material;
    assert(!wq_identity(material, &fake.pins[4], 0));
    int populated = -99;
    assert(scope_events(&fake, 4, &populated) && populated == -99);
    const char fabricated[] = "populated 0\nfrozen 0\n";
    assert(write(material, fabricated, sizeof(fabricated) - 1) == (ssize_t)sizeof(fabricated) - 1);
    assert(scope_events(&fake, 4, &populated) && populated == -99);
    close(sockets[0]);
    errno = 0;
    assert(wq_receive(sockets[1], &received, NULL, 0, deadline) && errno == EPROTO);
    close(sockets[1]);
    close(material);
    assert(!unlink(argv[1]));
    return 0;
}
'''


@pytest.mark.skipif(
    sys.platform != "linux" or platform.machine().lower() not in {"x86_64", "amd64"},
    reason="actual Linux x86-64 native component consumption",
)
def test_actual_native_packets_close_refused_fds_and_fake_events_never_prove_empty(tmp_path):
    compiler = shutil.which("clang") or shutil.which("cc")
    if compiler is None:
        pytest.skip("native C compiler unavailable")
    source = tmp_path / "component.c"
    source.write_text(_HARNESS, encoding="ascii")
    executable = tmp_path / "component"
    subprocess.run(
        [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-O2", "-I",
         str(native_whole_scope_source_paths()[0].parent), str(source), "-o", str(executable)],
        check=True, capture_output=True, timeout=30, env={"PATH": os.defpath, "LANG": "C"},
    )
    subprocess.run(
        [str(executable), str(tmp_path / "fabricated-events")], check=True,
        stdin=subprocess.DEVNULL, capture_output=True, timeout=10,
        env={"PATH": os.defpath, "LANG": "C"},
    )
