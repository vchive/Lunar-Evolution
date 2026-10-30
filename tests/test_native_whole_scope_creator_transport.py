"""Actual creator-OFD transport/adoption, without an installed native scope.

R, packets, files, ACLs, durability calls, fork ownership and both SCM_RIGHTS
hops are real. Only root uid/gid metadata is projected. S's production creator
adoption/packet preparation helpers are consumed directly; its real scope gate
is never forged or treated as successful. No candidate or root dispatch runs.
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
#include <sys/socket.h>
#include <unistd.h>
static int projected_fstat(int fd, struct stat *out);
static int projected_fstatat(int fd, const char *name, struct stat *out, int flags);
static int injected_fsync(int fd);
static ssize_t injected_recvmsg(int fd, struct msghdr *message, int flags);
#define fstat projected_fstat
#define fstatat projected_fstatat
#define fsync injected_fsync
#define recvmsg injected_recvmsg
#define main installed_scope_main
#include "native_whole_scope.c"
#undef main
#undef recvmsg
#undef fsync
#undef fstatat
#undef fstat
#include <assert.h>
#include <stdatomic.h>
#include <sys/mman.h>

static const char *fault;
static _Atomic int *injected;
static int projected_fstat(int fd, struct stat *out) {
    int result = fstat(fd, out);
    if (!result) out->st_uid = out->st_gid = 0;
    return result;
}
static int projected_fstatat(int fd, const char *name, struct stat *out, int flags) {
    int result = fstatat(fd, name, out, flags);
    if (!result) out->st_uid = out->st_gid = 0;
    return result;
}
static int injected_fsync(int fd) {
    struct stat info;
    assert(!fstat(fd, &info));
    if (S_ISREG(info.st_mode)) {
        if ((!strcmp(fault, "registration-fsync-failure") && info.st_size == 925) ||
            (!strcmp(fault, "empty-terminal-fsync-failure") && !info.st_size) ||
            (!strcmp(fault, "terminal-fsync-failure") && info.st_size == 941)) {
            atomic_fetch_add(injected, 1); errno = EIO; return -1;
        }
        if (!strcmp(fault, "blocked-terminal") && info.st_size == 941) {
            atomic_fetch_add(injected, 1);
            assert(!raise(SIGSTOP));
        }
    }
    return fsync(fd);
}
static ssize_t injected_recvmsg(int fd, struct msghdr *message, int flags) {
    /* R's first terminal receive starts only after its creator-send postcheck.
     * Synchronize the later cross-stage mutation to that actual boundary. */
    if (!strncmp(fault, "receiver-registration-", 22) && message->msg_iovlen &&
        message->msg_iov[0].iov_len == sizeof(wq_custody_event_t) + 1)
        atomic_store(injected, 1);
    ssize_t result = recvmsg(fd, message, flags);
    if (result == 941 && message->msg_iovlen && message->msg_iov[0].iov_len >= 941) {
        wq_custody_event_t event;
        memcpy(&event, message->msg_iov[0].iov_base, sizeof(event));
        if (event.original.operation == WQ_V3_TERMINAL_ACK) {
            if (!strcmp(fault, "ack-extension-corrupt")) {
                event.facts ^= WQ_CUSTODY_SCOPE_EMPTY;
                memcpy(message->msg_iov[0].iov_base, &event, sizeof(event));
                atomic_fetch_add(injected, 1);
            }
            if (!strcmp(fault, "lost-ack")) {
                atomic_fetch_add(injected, 1); errno = ECONNRESET; return -1;
            }
        }
    }
    return result;
}
static int descriptor_count(void) {
    DIR *directory = opendir("/proc/self/fd");
    assert(directory);
    int count = 0;
    struct dirent *entry;
    while ((entry = readdir(directory)))
        if (strcmp(entry->d_name, ".") && strcmp(entry->d_name, "..")) count++;
    assert(!closedir(directory));
    return count;
}
static void initialize(supervisor_t *s, int directory) {
    memset(s, 0, sizeof(*s));
    uint64_t now;
    assert(!wq_now(&now));
    s->deadline = now + 2000000000ULL;
    s->scope.deadline = s->deadline;
    s->profile = s->delegation = s->bootstrap = s->controller = s->enrollment = -1;
    s->lifecycle = s->lifeline = s->image = s->target = -1;
    s->scope.leaf = s->scope.delegation = -1;
    s->guardian.pidfd = s->guardian.fd = s->guardian_lifeline = -1;
    s->receiver.pidfd = s->receiver.fd = -1;
    s->custody_creators[0] = s->custody_creators[1] = -1;
    for (int i = 0; i < 8; i++) s->scope.files[i] = -1;
    for (int i = 0; i < 3; i++) s->publications[i] = -1;
    s->custody = directory;
    s->custody_v3 = 1;
    assert(!private_directory(directory, &s->custody_parent));
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
static int receive_creators(supervisor_t *s, wq_message_t *ack, int rights[2]) {
    for (;;) {
        if (!wq_receive(s->receiver.fd, ack, rights, 2, s->deadline)) return 0;
        if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR) return -1;
        int ms = wq_remaining(s->deadline);
        struct pollfd p = {s->receiver.fd, POLLIN, 0};
        if (ms < 0 || (poll(&p, 1, ms) < 0 && errno != EINTR)) return -1;
    }
}
static void start_receiver_fixture(supervisor_t *s, const wq_message_t *registration) {
    int channel[2];
    assert(!socketpair(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC | SOCK_NONBLOCK, 0, channel));
    pid_t pid = fork();
    assert(pid >= 0);
    if (!pid) {
        close(channel[0]);
        receiver_v3_main(s->custody, channel[1], &s->binding, &s->scope.leaf_pin);
    }
    close(channel[1]);
    s->receiver.fd = channel[0];
    s->receiver.pid = pid;
    s->receiver.pidfd = (int)syscall(SYS_pidfd_open, pid, 0);
    assert(s->receiver.pidfd > 2);
    assert(!wq_send(s->receiver.fd, registration, NULL, 0));
}
static void cleanup_receiver(supervisor_t *s) {
    if (!s->receiver.reaped) {
        /* Test-only retirement after an unknown/expired outcome does not
         * contribute an original-budget fact or make a late ACK valid. */
        (void)syscall(SYS_pidfd_send_signal, s->receiver.pidfd, SIGKILL, NULL, 0);
        assert(waitpid(s->receiver.pid, NULL, 0) == s->receiver.pid);
    }
    close(s->receiver.pidfd); close(s->receiver.fd);
}
static void transport_refusal(supervisor_t *s, const wq_message_t *ack, const int originals[2]) {
    int channel[2];
    assert(!socketpair(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC | SOCK_NONBLOCK, 0, channel));
    unsigned char raw[sizeof(*ack) + 1];
    memcpy(raw, ack, sizeof(*ack)); raw[sizeof(*ack)] = 0;
    size_t size = !strcmp(fault, "short") ? sizeof(*ack) - 1 :
                  !strcmp(fault, "oversized") ? sizeof(*ack) + 1 : sizeof(*ack);
    size_t count = !strcmp(fault, "no-rights") ? 0 : !strcmp(fault, "one-right") ? 1 :
                   !strcmp(fault, "extra-rights") ? 3 : !strcmp(fault, "truncated-rights") ? 6 : 2;
    struct iovec vector = {raw, size};
    char ancillary[CMSG_SPACE(6 * sizeof(int))];
    struct msghdr message;
    memset(&message, 0, sizeof(message)); memset(ancillary, 0, sizeof(ancillary));
    message.msg_iov = &vector; message.msg_iovlen = 1;
    if (count) {
        message.msg_control = ancillary; message.msg_controllen = CMSG_SPACE(count * sizeof(int));
        struct cmsghdr *control = CMSG_FIRSTHDR(&message);
        control->cmsg_level = SOL_SOCKET; control->cmsg_type = SCM_RIGHTS;
        control->cmsg_len = CMSG_LEN(count * sizeof(int));
        int rights[6];
        for (size_t i = 0; i < count; i++) rights[i] = originals[i % 2];
        memcpy(CMSG_DATA(control), rights, count * sizeof(int));
    }
    int baseline = descriptor_count();
    assert(sendmsg(channel[0], &message, MSG_NOSIGNAL) == (ssize_t)size);
    wq_message_t received;
    int rights[2] = {-1, -1};
    assert(wq_receive(channel[1], &received, rights, 2, s->deadline));
    assert(rights[0] == -1 && rights[1] == -1 && descriptor_count() == baseline);
    close(channel[0]); close(channel[1]);
}
static void mutate_registration(supervisor_t *s, const wq_message_t *registration) {
    if (strstr(fault, "same-bytes")) {
        assert(pwrite(s->custody_creators[0], registration, sizeof(*registration), 0) ==
               (ssize_t)sizeof(*registration));
    } else {
        struct timespec times[2] = {s->custody_registration.st_atim,
                                    s->custody_registration.st_mtim};
        times[1].tv_sec++;
        assert(!futimens(s->custody_creators[0], times));
    }
    struct stat after;
    wq_message_t actual;
    assert(!fstat(s->custody_creators[0], &after));
    assert(!v3_stat_equal(&s->custody_registration, &after));
    assert(pread(s->custody_creators[0], &actual, sizeof(actual), 0) == (ssize_t)sizeof(actual));
    assert(!memcmp(&actual, registration, sizeof(actual)));
}
static child_t forward_to_controller(supervisor_t *s, const wq_message_t *registration,
                                      int *ready, int *command) {
    int channel[2], replies[2], commands[2];
    assert(!socketpair(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC | SOCK_NONBLOCK, 0, channel));
    assert(!pipe2(replies, O_CLOEXEC) && !pipe2(commands, O_CLOEXEC));
    child_t child;
    memset(&child, 0, sizeof(child));
    pid_t pid = fork();
    assert(pid >= 0);
    if (!pid) {
        int keep[] = {s->custody, channel[1], replies[1], commands[0]};
        assert(!close_except(keep, 4));
        int null = open("/dev/null", O_RDWR | O_CLOEXEC);
        assert(null == 0 && dup2(null, 1) == 1 && dup2(null, 2) == 2);
        wq_message_t message, expected = *registration;
        expected.operation = WQ_V3_CONTROLLER_CREATORS;
        expected.sequence = 2; expected.fd_count = 2;
        int files[2] = {-1, -1};
        for (;;) {
            if (!wq_receive(channel[1], &message, files, 2, s->deadline)) break;
            assert(errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR);
            int ms = wq_remaining(s->deadline);
            struct pollfd p = {channel[1], POLLIN, 0};
            assert(ms >= 0 && poll(&p, 1, ms) >= 0);
        }
        assert(!memcmp(&message, &expected, sizeof(message)));
        wq_identity_t pins[2];
        assert(!wq_identity(files[0], &pins[0], 0) && !wq_identity(files[1], &pins[1], 0));
        /* Instrumentation queries only: every product read must preserve
         * the exact original shared OFD positions set by R's writes. */
        assert(lseek(files[0], 0, SEEK_CUR) == 925 && lseek(files[1], 0, SEEK_CUR) == 0);
        assert(!v3_creators_check(s->custody, files, &s->custody_parent, pins,
                                  registration, NULL, s->deadline));
        assert(lseek(files[0], 0, SEEK_CUR) == 925 && lseek(files[1], 0, SEEK_CUR) == 0);
        assert(write(replies[1], "C", 1) == 1);
        char byte;
        assert(read(commands[0], &byte, 1) == 1 && byte == 'T');
        wq_custody_event_t terminal;
        assert(pread(files[1], &terminal, sizeof(terminal), 0) == (ssize_t)sizeof(terminal));
        assert(!wq_v3_event_check(&terminal, registration));
        assert(!v3_creators_check(s->custody, files, &s->custody_parent, pins,
                                  registration, &terminal, s->deadline));
        assert(lseek(files[0], 0, SEEK_CUR) == 925 && lseek(files[1], 0, SEEK_CUR) == 941);
        close(files[0]); close(files[1]);
        assert(write(replies[1], "D", 1) == 1);
        _exit(0);
    }
    close(channel[1]); close(replies[1]); close(commands[0]);
    child.pid = pid;
    child.pidfd = (int)syscall(SYS_pidfd_open, pid, 0);
    assert(child.pidfd > 2);
    s->controller = channel[0];
    wq_message_t message;
    assert(!prepare_v3_controller_creators(s, &message));
    assert(!wq_send(channel[0], &message, s->custody_creators, 2));
    close_custody_creators(s);
    *ready = replies[0]; *command = commands[1];
    char byte;
    assert(read(*ready, &byte, 1) == 1 && byte == 'C');
    return child;
}
int main(int argc, char **argv) {
    assert(argc == 3);
    fault = argv[1];
    injected = mmap(NULL, sizeof(*injected), PROT_READ | PROT_WRITE,
                    MAP_SHARED | MAP_ANONYMOUS, -1, 0);
    assert(injected != MAP_FAILED);
    atomic_init(injected, 0);
    int directory = open(argv[2], O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
    assert(directory > 2);
    supervisor_t s;
    initialize(&s, directory);
    wq_message_t registration;
    v3_registration(&s, &registration);
    assert(!wq_v3_message_check(&registration, &s.binding, WQ_V3_STORE_REGISTER, 1, 0));
    assert(wq_message_check(&registration, &s.binding, WQ_STORE_REGISTER, 1, 0));
    start_receiver_fixture(&s, &registration);
    wq_message_t ack;
    int incoming[2] = {-1, -1};
    int baseline = descriptor_count();
    int received = receive_creators(&s, &ack, incoming);
    if (!strcmp(fault, "registration-fsync-failure") || !strcmp(fault, "empty-terminal-fsync-failure")) {
        assert(received && incoming[0] == -1 && incoming[1] == -1);
        assert(descriptor_count() == baseline && atomic_load(injected) == 1);
        cleanup_receiver(&s); close(directory); return 0;
    }
    assert(!received && descriptor_count() == baseline + 2);
    assert(incoming[0] > 2 && incoming[1] > 2);
    if (!strcmp(fault, "short") || !strcmp(fault, "oversized") || !strcmp(fault, "no-rights") ||
        !strcmp(fault, "one-right") || !strcmp(fault, "extra-rights") || !strcmp(fault, "truncated-rights")) {
        transport_refusal(&s, &ack, incoming);
        close(incoming[0]); close(incoming[1]);
        cleanup_receiver(&s); close(directory); return 0;
    }
    int reject = 1;
    if (!strcmp(fault, "wrong-context")) ack.binding.launch_sha256[0] = 'f';
    else if (!strcmp(fault, "wrong-version")) ack.version = 2;
    else if (!strcmp(fault, "wrong-sequence")) ack.sequence = 2;
    else if (!strcmp(fault, "aliased-rights")) { close(incoming[1]); incoming[1] = dup(incoming[0]); }
    else if (!strcmp(fault, "original-role-alias")) s.publications[0] = incoming[0];
    else if (!strcmp(fault, "wrong-mode")) assert(!fchmod(incoming[0], 0640));
    else if (!strcmp(fault, "readonly-substitute")) {
        close(incoming[0]);
        incoming[0] = openat(directory, v3_record_names[0], O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
        assert(incoming[0] > 2);
    } else if (!strcmp(fault, "hardlink-drift"))
        assert(!linkat(directory, v3_record_names[0], directory, "alias", 0));
    else if (!strcmp(fault, "name-replacement")) {
        char bytes[925];
        assert(pread(incoming[0], bytes, sizeof(bytes), 0) == (ssize_t)sizeof(bytes));
        assert(!unlinkat(directory, v3_record_names[0], 0));
        int replacement = openat(directory, v3_record_names[0], O_RDWR | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
        assert(replacement > 2 && write(replacement, bytes, sizeof(bytes)) == (ssize_t)sizeof(bytes));
        close(replacement);
    } else if (!strcmp(fault, "extra-name")) {
        int extra = openat(directory, "extra", O_RDWR | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
        assert(extra > 2); close(extra);
    } else if (!strcmp(fault, "access-acl")) {
        acl_t acl = {2, {{1, 6, UINT32_MAX}, {2, 0, 65534}, {4, 0, UINT32_MAX},
                          {16, 0, UINT32_MAX}, {32, 0, UINT32_MAX}}};
        assert(!fsetxattr(incoming[0], "system.posix_acl_access", &acl, sizeof(acl), XATTR_CREATE));
    } else if (!strcmp(fault, "changed-registration")) {
        char byte = 'X'; assert(pwrite(incoming[0], &byte, 1, 24) == 1);
    } else if (!strcmp(fault, "partial-terminal")) {
        char byte = 'X'; assert(pwrite(incoming[1], &byte, 1, 0) == 1);
    } else if (!strcmp(fault, "expired-adoption")) {
        int ms;
        while ((ms = wq_remaining(s.deadline)) >= 0) assert(poll(NULL, 0, ms + 1) == 0);
    } else reject = 0;
    int adopted = adopt_v3_creators(&s, &registration, &ack, incoming);
    assert(incoming[0] == -1 && incoming[1] == -1);
    if (reject) {
        assert(adopted && !s.custody_registered);
        assert(s.custody_creators[0] == -1 && s.custody_creators[1] == -1);
        assert(descriptor_count() == baseline);
        cleanup_receiver(&s); close(directory); return 0;
    }
    assert(!adopted && s.custody_registered);
    if (!strcmp(fault, "registration-same-bytes") || !strcmp(fault, "registration-timestamp")) {
        mutate_registration(&s, &registration);
        wq_message_t refused;
        assert(prepare_v3_controller_creators(&s, &refused));
        close_custody_creators(&s);
        assert(descriptor_count() == baseline);
        cleanup_receiver(&s); close(directory); return 0;
    }
    if (!strcmp(fault, "receiver-registration-same-bytes") ||
        !strcmp(fault, "receiver-registration-timestamp")) {
        while (!atomic_load(injected)) {
            assert(wq_remaining(s.deadline) >= 0);
            assert(poll(NULL, 0, 1) == 0);
        }
        mutate_registration(&s, &registration);
        assert(persist_v3_terminal(&s, WQ_CUSTODY_PROTOCOL, WQ_CUSTODY_STOP_ATTEMPTED));
        assert(s.custody_terminal_sent);
        assert(child_wait(&s.receiver, s.deadline, 1));
        assert(s.receiver.reaped && wq_remaining(s.deadline) >= 0);
        struct stat terminal;
        assert(!fstat(s.custody_creators[1], &terminal) && !terminal.st_size);
        close_custody_creators(&s);
        assert(descriptor_count() == baseline);
        cleanup_receiver(&s); close(directory); return 0;
    }
    if (!strcmp(fault, "post-adoption-truncate") || !strcmp(fault, "post-adoption-timestamp")) {
        if (!strcmp(fault, "post-adoption-truncate")) {
            char byte = 'X';
            assert(pwrite(s.custody_creators[1], &byte, 1, 0) == 1);
            assert(!ftruncate(s.custody_creators[1], 0));
        } else {
            struct timespec times[2] = {s.custody_empty_terminal.st_atim,
                                        s.custody_empty_terminal.st_mtim};
            times[1].tv_sec++;
            assert(!futimens(s.custody_creators[1], times));
        }
        struct stat after;
        assert(!fstat(s.custody_creators[1], &after));
        assert(after.st_size == 0 && !v3_stat_equal(&s.custody_empty_terminal, &after));
        wq_message_t refused;
        assert(prepare_v3_controller_creators(&s, &refused));
        close_custody_creators(&s);
        assert(descriptor_count() == baseline);
        cleanup_receiver(&s); close(directory); return 0;
    }
    if (!strcmp(fault, "terminal-fsync-failure") || !strcmp(fault, "blocked-terminal")) {
        assert(persist_v3_terminal(&s, WQ_CUSTODY_PROTOCOL, WQ_CUSTODY_STOP_ATTEMPTED));
        assert(s.custody_terminal_sent && atomic_load(injected) == 1);
        close_custody_creators(&s); cleanup_receiver(&s); close(directory); return 0;
    }
    int ready, command;
    child_t controller = forward_to_controller(&s, &registration, &ready, &command);
    assert(s.custody_creators[0] == -1 && s.custody_creators[1] == -1);
    if (!strcmp(fault, "normal")) {
        wq_custody_event_t event;
        memset(&event, 0, sizeof(event));
        event.original = registration;
        event.original.operation = WQ_V3_STORE_NORMAL; event.original.sequence = 2;
        event.facts = WQ_CUSTODY_NORMAL_FACTS;
        uint64_t now; assert(!wq_now(&now)); event.observed_monotonic_ns = now;
        assert(!wq_v3_event_check(&event, &registration));
        assert(!wq_custody_send(s.receiver.fd, &event));
        wq_custody_event_t terminal_ack;
        for (;;) {
            if (!wq_custody_receive(s.receiver.fd, &terminal_ack, s.deadline)) break;
            assert(errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR);
            int ms = wq_remaining(s.deadline);
            struct pollfd p = {s.receiver.fd, POLLIN, 0};
            assert(ms >= 0 && poll(&p, 1, ms) >= 0);
        }
        assert(!wq_v3_terminal_ack_check(&terminal_ack, &event));
    } else {
        int result = persist_v3_terminal(&s, WQ_CUSTODY_PROTOCOL, WQ_CUSTODY_STOP_ATTEMPTED);
        int lost = !strcmp(fault, "ack-extension-corrupt") || !strcmp(fault, "lost-ack");
        assert((result != 0) == lost && s.custody_terminal_sent);
        if (lost) assert(atomic_load(injected) == 1);
    }
    assert(!child_wait(&s.receiver, s.deadline, 1));
    assert(write(command, "T", 1) == 1);
    char byte;
    assert(read(ready, &byte, 1) == 1 && byte == 'D');
    assert(!child_wait(&controller, s.deadline, 1));
    close(controller.pidfd); close(s.controller); close(ready); close(command);
    cleanup_receiver(&s); close(directory);
    assert(!munmap(injected, sizeof(*injected)));
    return 0;
}
'''

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or platform.machine().lower() not in {"x86_64", "amd64"},
    reason="actual Linux x86-64 creator-description transport/adoption",
)


@pytest.fixture(scope="module")
def creator_native(tmp_path_factory):
    compiler = shutil.which("clang") or shutil.which("cc")
    if compiler is None:
        pytest.skip("native C compiler unavailable")
    root = tmp_path_factory.mktemp("creator-native")
    source = root / "creators.c"
    source.write_text(_HARNESS, encoding="ascii")
    executable = root / "creators"
    subprocess.run(
        [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-Wpedantic", "-O2", "-I",
         str(native_whole_scope_source_paths()[0].parent), str(source), "-o", str(executable)],
        check=True, capture_output=True, timeout=30, env={"PATH": os.defpath, "LANG": "C"},
    )
    return executable


@pytest.mark.parametrize("case", [
    "normal", "abnormal", "ack-extension-corrupt", "lost-ack",
    "registration-fsync-failure", "empty-terminal-fsync-failure", "terminal-fsync-failure",
    "blocked-terminal", "short", "oversized", "no-rights", "one-right", "extra-rights",
    "truncated-rights", "wrong-context", "wrong-version", "wrong-sequence", "aliased-rights",
    "original-role-alias", "wrong-mode", "readonly-substitute", "hardlink-drift",
    "name-replacement", "extra-name", "access-acl", "changed-registration", "partial-terminal",
    "expired-adoption", "post-adoption-truncate", "post-adoption-timestamp",
    "registration-same-bytes", "registration-timestamp", "receiver-registration-same-bytes",
    "receiver-registration-timestamp",
])
def test_actual_creator_delivery_and_failure_retirement(creator_native, tmp_path, case):
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    subprocess.run(
        [str(creator_native), case, str(directory)], check=True, capture_output=True,
        stdin=subprocess.DEVNULL, timeout=8, env={"PATH": os.defpath, "LANG": "C"},
    )
