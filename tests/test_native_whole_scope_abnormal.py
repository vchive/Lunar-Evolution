"""Real R write/fsync/channel and S failure ordering, without root/cgroup proof.

The C fixture projects only fstat/fstatat uid/gid to the installed root identity.
It uses actual files, names, ACLs, channels, fork children, pidfds, exact waits
and fsync. Its invalid scope cannot establish a recursive cgroup empty fact.
No installed profile, candidate, root dispatch or deployment case is run.
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
#define _GNU_SOURCE
#include <sys/stat.h>
#include <unistd.h>
static int fixture_fstat(int fd, struct stat *out);
static int fixture_fstatat(int fd, const char *name, struct stat *out, int flags);
static int fixture_fsync(int fd);
#define fstat fixture_fstat
#define fstatat fixture_fstatat
#define fsync fixture_fsync
#define main installed_scope_main
#include "native_whole_scope.c"
#undef main
#undef fsync
#undef fstatat
#undef fstat
#include <assert.h>

static const char *fault;
static int receiver_directory = -1;
static int fixture_fstat(int fd, struct stat *out) {
    int result = fstat(fd, out);
    if (!result) out->st_uid = out->st_gid = 0;
    return result;
}
static int fixture_fstatat(int fd, const char *name, struct stat *out, int flags) {
    int result = fstatat(fd, name, out, flags);
    if (!result) out->st_uid = out->st_gid = 0;
    return result;
}
static int fixture_fsync(int fd) {
    struct stat info;
    assert(!fstat(fd, &info));
    if (S_ISREG(info.st_mode) && info.st_size == (off_t)sizeof(wq_custody_event_t)) {
        if (!strcmp(fault, "fsync-failure")) { errno = EIO; return -1; }
        if (!strcmp(fault, "blocked-receiver")) assert(!raise(SIGSTOP));
        if (!strcmp(fault, "directory-drift")) assert(!fchmod(receiver_directory, 0755));
        if (!strcmp(fault, "hardlink-drift"))
            assert(!linkat(receiver_directory, "scope-terminal-v2.bin", receiver_directory, "alias", 0));
        if (!strcmp(fault, "access-acl") || !strcmp(fault, "default-acl")) {
            /* A named entry masked to zero preserves 0700/0600: mode alone
             * cannot stand in for checking actual extended ACL absence. */
            int target = !strcmp(fault, "default-acl") ? receiver_directory : fd;
            acl_t acl = {2, {{1, target == fd ? 6 : 7, UINT32_MAX}, {2, 0, 65534},
                              {4, 0, UINT32_MAX}, {16, 0, UINT32_MAX}, {32, 0, UINT32_MAX}}};
            const char *name = target == fd ? "system.posix_acl_access" : "system.posix_acl_default";
            assert(!fsetxattr(target, name, &acl, sizeof(acl), XATTR_CREATE));
        }
    }
    return fsync(fd);
}
static void initialize(supervisor_t *s, int directory) {
    memset(s, 0, sizeof(*s));
    uint64_t now;
    assert(!wq_now(&now));
    s->deadline = now + 2000000000ULL;
    s->scope.deadline = s->deadline;
    s->scope.leaf = s->scope.delegation = -1;
    for (int i = 0; i < 8; i++) s->scope.files[i] = -1;
    s->bootstrap = s->guardian.pidfd = s->receiver.pidfd = s->guardian_lifeline = -1;
    s->custody = directory;
    s->custody_v2 = 1;
    s->binding.deadline_ns = s->deadline;
    s->binding.candidate_uid = s->binding.candidate_gid = 65534;
    char *digests[] = {s->binding.launch_sha256, s->binding.intent_sha256, s->binding.target_sha256,
                      s->binding.bootstrap_sha256, s->binding.supervisor_sha256, s->binding.profile_sha256};
    for (size_t i = 0; i < 6; i++) memset(digests[i], 'a' + (int)i, 64);
    assert(!wq_binding_valid(&s->binding));
    s->scope.leaf_pin.inode = 71;
    s->scope.leaf_pin.mode = S_IFDIR | 0700;
    s->target_pid = 123;
    for (size_t i = 0; i < 3; i++) {
        s->publication_pins[i].inode = 21 + i;
        s->publication_pins[i].size = 7;
        memset(s->publication_pins[i].sha256, 'a', 64);
    }
}
static wq_message_t registration(supervisor_t *s) {
    wq_message_t value;
    wq_message_init(&value, &s->binding, WQ_STORE_REGISTER, 1, 0);
    value.scope = s->scope.leaf_pin;
    value.target_pid = s->target_pid;
    memcpy(value.publications, s->publication_pins, sizeof(value.publications));
    return value;
}
static int receive_ack(supervisor_t *s, wq_message_t *ack) {
    for (;;) {
        if (!wq_receive(s->receiver.fd, ack, NULL, 0, s->deadline)) return 0;
        if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR) return -1;
        int ms = wq_remaining(s->deadline);
        struct pollfd p = {s->receiver.fd, POLLIN, 0};
        if (ms < 0 || (poll(&p, 1, ms) < 0 && errno != EINTR)) return -1;
    }
}
static void start_receiver_fixture(supervisor_t *s) {
    int channel[2];
    assert(!socketpair(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC | SOCK_NONBLOCK, 0, channel));
    pid_t pid = fork();
    assert(pid >= 0);
    if (!pid) {
        close(channel[0]);
        receiver_directory = s->custody;
        receiver_v2_main(s->custody, channel[1], &s->binding, &s->scope.leaf_pin);
    }
    close(channel[1]);
    s->receiver.fd = channel[0];
    s->receiver.pid = pid;
    s->receiver.pidfd = (int)syscall(SYS_pidfd_open, pid, 0);
    assert(s->receiver.pidfd > 2);
    wq_message_t original = registration(s), ack;
    assert(!wq_send(s->receiver.fd, &original, NULL, 0));
    assert(!receive_ack(s, &ack));
    assert(!wq_message_check(&ack, &s->binding, WQ_STORE_ACK, 1, 0));
    assert(wq_identity_equal(&ack.scope, &s->scope.leaf_pin));
    assert(ack.target_pid == s->target_pid && !zero(ack.publications, sizeof(ack.publications)));
    s->custody_registered = 1;
}
static off_t record_size(int directory, const char *name) {
    struct stat info;
    assert(!fstatat(directory, name, &info, AT_SYMLINK_NOFOLLOW));
    return info.st_size;
}
static wq_custody_event_t terminal(supervisor_t *s, uint32_t reason, uint32_t facts) {
    wq_custody_event_t event;
    memset(&event, 0, sizeof(event));
    event.original = registration(s);
    event.original.version = WQ_CUSTODY_VERSION;
    event.original.operation = reason ? WQ_CUSTODY_ABNORMAL : WQ_CUSTODY_NORMAL;
    event.original.sequence = 2;
    event.reason = reason;
    event.facts = facts;
    uint64_t now;
    assert(!wq_now(&now));
    event.observed_monotonic_ns = now;
    return event;
}
static wq_custody_event_t read_terminal(supervisor_t *s) {
    wq_custody_event_t value;
    int fd = openat(s->custody, "scope-terminal-v2.bin", O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    assert(fd > 2 && read(fd, &value, sizeof(value)) == (ssize_t)sizeof(value));
    char extra;
    assert(read(fd, &extra, 1) == 0);
    close(fd);
    wq_message_t original = registration(s);
    assert(!wq_custody_event_check(&value, &original));
    return value;
}
static int start_stop_fixture(supervisor_t *s) {
    int lifeline[2], marker[2];
    assert(!pipe2(lifeline, O_CLOEXEC));
    assert(!pipe2(marker, O_CLOEXEC));
    pid_t bootstrap = fork();
    assert(bootstrap >= 0);
    if (!bootstrap) {
        close(lifeline[0]); close(lifeline[1]); close(marker[0]); close(marker[1]);
        for (;;) pause();
    }
    s->bootstrap = (int)syscall(SYS_pidfd_open, bootstrap, 0);
    assert(s->bootstrap > 2);
    pid_t guardian = fork();
    assert(guardian >= 0);
    if (!guardian) {
        close(lifeline[1]); close(marker[0]); close(s->receiver.fd);
        char byte;
        ssize_t n;
        do { n = read(lifeline[0], &byte, 1); } while (n < 0 && errno == EINTR);
        assert(!n);
        /* This independent child represents G's stop notification only. Its
         * marker and exact reap do not establish any cgroup empty fact. */
        assert(write(marker[1], "G", 1) == 1);
        _exit(0);
    }
    close(lifeline[0]); close(marker[1]);
    s->guardian_lifeline = lifeline[1];
    s->guardian.pid = guardian;
    s->guardian.pidfd = (int)syscall(SYS_pidfd_open, guardian, 0);
    assert(s->guardian.pidfd > 2);
    return marker[0];
}
static void cleanup_child(child_t *child) {
    if (child->pidfd >= 0) {
        if (!child->reaped) {
            (void)syscall(SYS_pidfd_send_signal, child->pidfd, SIGKILL, NULL, 0);
            assert(waitpid(child->pid, NULL, 0) == child->pid);
        }
        close(child->pidfd);
    }
}
int main(int argc, char **argv) {
    assert(argc == 3);
    fault = argv[1];
    int directory = open(argv[2], O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
    assert(directory > 2);
    supervisor_t s;
    initialize(&s, directory);
    start_receiver_fixture(&s);
    assert(record_size(directory, "scope-registration-v2.bin") == 925);
    assert(record_size(directory, "scope-terminal-v2.bin") == 0);
    int helper = !strcmp(fault, "controller-lost") || !strcmp(fault, "cutoff") ||
                 !strcmp(fault, "protocol") || !strcmp(fault, "blocked-receiver") ||
                 !strcmp(fault, "expired");
    if (helper) {
        int marker = start_stop_fixture(&s);
        s.failure_reason = WQ_CUSTODY_PROTOCOL;
        int life[2], control[2];
        assert(!pipe2(life, O_CLOEXEC | O_NONBLOCK));
        assert(!socketpair(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC | SOCK_NONBLOCK, 0, control));
        s.lifeline = life[0]; s.controller = control[0];
        if (!strcmp(fault, "controller-lost")) {
            close(life[1]); life[1] = -1;
            s.failure_reason = 0;
            assert(supervisor_check(&s) && s.failure_reason == WQ_CUSTODY_CONTROLLER_LOST);
        } else if (!strcmp(fault, "cutoff")) {
            s.controller_released = 1;
            assert(!wq_now(&s.execution_cutoff));
            s.failure_reason = 0;
            assert(supervisor_check(&s) && s.failure_reason == WQ_CUSTODY_DEADLINE);
        } else if (!strcmp(fault, "protocol")) {
            /* A real invalid-scope refusal, with the original R still alive,
             * cannot be relabeled as evidence of a receiver failure. */
            s.failure_reason = 0;
            custody_failure_fallback(&s);
            assert(s.failure_reason == WQ_CUSTODY_PROTOCOL);
        }
        if (!strcmp(fault, "expired")) {
            /* Consume, rather than replace, the exact original budget. */
            int ms;
            while ((ms = wq_remaining(s.deadline)) >= 0)
                assert(poll(NULL, 0, ms + 1) == 0);
            s.failure_reason = WQ_CUSTODY_DEADLINE;
        }
        int result = finish_abnormal_custody(&s);
        if (!strcmp(fault, "blocked-receiver") || !strcmp(fault, "expired")) {
            assert(result && !s.receiver.reaped);
            if (!strcmp(fault, "blocked-receiver"))
                assert(s.guardian.reaped && s.guardian_lifeline == -1);
            if (!strcmp(fault, "expired"))
                assert(record_size(directory, "scope-terminal-v2.bin") == 0);
        } else {
            assert(!result && s.guardian.reaped && s.guardian_lifeline == -1);
            wq_custody_event_t observed = read_terminal(&s);
            assert(observed.reason == s.failure_reason);
            assert(observed.facts == (WQ_CUSTODY_STOP_ATTEMPTED | WQ_CUSTODY_BOOTSTRAP_EXIT |
                                      WQ_CUSTODY_GUARDIAN_REAPED));
            assert(!(observed.facts & WQ_CUSTODY_SCOPE_EMPTY));
        }
        cleanup_child(&s.guardian);
        char byte;
        ssize_t marked = read(marker, &byte, 1);
        if (!strcmp(fault, "expired"))
            assert(marked == 0 || (marked == 1 && byte == 'G'));
        else
            assert(marked == 1 && byte == 'G');
        close(marker); close(life[0]);
        if (life[1] >= 0) close(life[1]);
        close(control[0]); close(control[1]);
        siginfo_t b;
        memset(&b, 0, sizeof(b));
        assert(!waitid(P_PIDFD, (id_t)s.bootstrap, &b, WEXITED));
        assert(b.si_pid && b.si_code == CLD_KILLED && b.si_status == SIGKILL);
        close(s.bootstrap);
    } else if (!strcmp(fault, "receiver-dead")) {
        assert(!syscall(SYS_pidfd_send_signal, s.receiver.pidfd, SIGKILL, NULL, 0));
        assert(!child_wait(&s.receiver, s.deadline, 0));
        s.failure_reason = 0;
        int life[2];
        assert(!pipe2(life, O_CLOEXEC | O_NONBLOCK));
        s.lifeline = life[0]; s.controller = -1;
        assert(supervisor_check(&s) && s.failure_reason == WQ_CUSTODY_RECEIVER_FAULT);
        assert(persist_v2_terminal(&s, s.failure_reason, WQ_CUSTODY_STOP_ATTEMPTED));
        assert(!s.custody_terminal_sent && record_size(directory, "scope-terminal-v2.bin") == 0);
        close(life[0]); close(life[1]);
    } else {
        uint32_t reason = !strcmp(fault, "normal") ? WQ_CUSTODY_OK : WQ_CUSTODY_RECEIVER_FAULT;
        uint32_t facts = reason ? WQ_CUSTODY_STOP_ATTEMPTED : WQ_CUSTODY_NORMAL_FACTS;
        wq_custody_event_t event = terminal(&s, reason, facts);
        if (!strcmp(fault, "changed-binding")) event.original.binding.launch_sha256[0] = 'f';
        if (!strcmp(fault, "invalid-facts")) event.facts |= 16;
        if (!strcmp(fault, "invalid-time")) event.observed_monotonic_ns = s.deadline;
        if (!strcmp(fault, "ancillary") || !strcmp(fault, "short") || !strcmp(fault, "oversized")) {
            char bytes[sizeof(event) + 1];
            memcpy(bytes, &event, sizeof(event)); bytes[sizeof(event)] = 0;
            size_t size = !strcmp(fault, "short") ? sizeof(event) - 1 :
                          !strcmp(fault, "oversized") ? sizeof(event) + 1 : sizeof(event);
            struct iovec vector = {bytes, size};
            char ancillary[CMSG_SPACE(sizeof(int))];
            struct msghdr header;
            memset(&header, 0, sizeof(header)); memset(ancillary, 0, sizeof(ancillary));
            header.msg_iov = &vector; header.msg_iovlen = 1;
            if (!strcmp(fault, "ancillary")) {
                header.msg_control = ancillary; header.msg_controllen = sizeof(ancillary);
                struct cmsghdr *control = CMSG_FIRSTHDR(&header);
                control->cmsg_level = SOL_SOCKET; control->cmsg_type = SCM_RIGHTS;
                control->cmsg_len = CMSG_LEN(sizeof(int));
                memcpy(CMSG_DATA(control), &directory, sizeof(int));
            }
            assert(sendmsg(s.receiver.fd, &header, MSG_NOSIGNAL) == (ssize_t)size);
        } else assert(!wq_custody_send(s.receiver.fd, &event));
        if (!strcmp(fault, "lost-ack")) {
            /* Observe bytes, then abandon the original channel without
             * consuming an ACK. A persisted record is not that lost ACK. */
            while (record_size(directory, "scope-terminal-v2.bin") != (off_t)sizeof(event)) {
                assert(wq_remaining(s.deadline) >= 0);
                assert(poll(NULL, 0, 1) == 0);
            }
            close(s.receiver.fd); s.receiver.fd = -1;
            assert(!s.custody_terminal_sent);
        } else {
            wq_message_t ack;
            int got = receive_ack(&s, &ack);
            int valid = !strcmp(fault, "normal") || !strcmp(fault, "receiver-reason");
            assert((got == 0) == valid);
            if (valid) {
                wq_message_t expected = event.original;
                expected.operation = WQ_CUSTODY_ACK;
                assert(!memcmp(&ack, &expected, sizeof(ack)));
                wq_custody_event_t observed = read_terminal(&s);
                assert(!memcmp(&observed, &event, sizeof(event)));
            } else if (!strcmp(fault, "changed-binding") || !strcmp(fault, "invalid-facts") ||
                       !strcmp(fault, "invalid-time") || !strcmp(fault, "ancillary") ||
                       !strcmp(fault, "short") || !strcmp(fault, "oversized"))
                assert(record_size(directory, "scope-terminal-v2.bin") == 0);
        }
    }
    cleanup_child(&s.receiver);
    if (s.receiver.fd >= 0) close(s.receiver.fd);
    close(directory);
    return 0;
}
'''

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or platform.machine().lower() not in {"x86_64", "amd64"},
    reason="actual Linux x86-64 receiver/pidfd/exact-child failure boundaries",
)


@pytest.fixture(scope="module")
def abnormal_native(tmp_path_factory):
    compiler = shutil.which("clang") or shutil.which("cc")
    if compiler is None:
        pytest.skip("native C compiler unavailable")
    root = tmp_path_factory.mktemp("abnormal-native")
    source = root / "abnormal.c"
    source.write_text(_HARNESS, encoding="ascii")
    executable = root / "abnormal"
    subprocess.run(
        [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-Wpedantic", "-O2", "-I",
         str(native_whole_scope_source_paths()[0].parent), str(source), "-o", str(executable)],
        check=True, capture_output=True, timeout=30, env={"PATH": os.defpath, "LANG": "C"},
    )
    return executable


@pytest.mark.parametrize("case", [
    "normal", "controller-lost", "cutoff", "protocol", "receiver-reason", "receiver-dead",
    "changed-binding", "invalid-facts", "invalid-time", "ancillary", "short", "oversized",
    "fsync-failure", "blocked-receiver", "lost-ack", "expired", "directory-drift",
    "hardlink-drift", "access-acl", "default-acl",
])
def test_actual_private_receiver_and_original_supervisor_failure_ordering(abnormal_native, tmp_path, case):
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    subprocess.run(
        [str(abnormal_native), case, str(directory)], check=True, capture_output=True,
        stdin=subprocess.DEVNULL, timeout=8, env={"PATH": os.defpath, "LANG": "C"},
    )
