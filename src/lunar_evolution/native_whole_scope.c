/* Finite sealed whole-scope supervisor, its exact guardian/storage children,
 * and the fixed installed grant publisher. No mode is a daemon or evaluator.
 */
#define _GNU_SOURCE
#include "native_whole_scope_platform.h"
#include <linux/sched.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/wait.h>

#define WQ_FAILURE 78
#define WQ_MAX_FILES 16384u
#define WQ_CLEANUP_RESERVE_NS 250000000ULL

typedef struct {
    int delegation, leaf, files[8];
    wq_identity_t parent_pin, leaf_pin, pins[8];
    char name[72];
    uint64_t deadline;
} scope_t;
static const char *scope_names[8] = {"cgroup.type",      "cgroup.subtree_control",
                                     "cgroup.max.depth", "cgroup.max.descendants",
                                     "cgroup.events",    "cgroup.kill",
                                     "cgroup.events",    "cgroup.kill"};
typedef struct {
    int fd, pidfd;
    pid_t pid;
    int reaped;
} child_t;
typedef struct {
    int profile, delegation, bootstrap, controller, enrollment, lifecycle, lifeline, image, custody;
    uint64_t deadline, execution_cutoff;
    wq_binding_t binding;
    wq_profile_t installed;
    scope_t scope;
    wq_chain_t delegation_chain;
    child_t guardian, receiver;
    int guardian_lifeline, target;
    uint64_t target_pid;
    int publications[3];
    wq_publication_t publication_pins[3];
    int guardian_retiring, receiver_retiring, bootstrap_finishing, controller_released;
    int cleanup_started;
    int custody_v2, custody_v3, custody_registered, custody_terminal_sent;
    int custody_creators[2];
    wq_identity_t custody_parent, custody_record_pins[2];
    struct stat custody_registration, custody_empty_terminal;
    uint32_t failure_reason;
} supervisor_t;

static int number(const char *text, uint64_t max, uint64_t *out) {
    if (!text || !*text || (*text == '0' && text[1]))
        return -1;
    uint64_t value = 0;
    for (const unsigned char *p = (const unsigned char *)text; *p; p++) {
        if (*p < '0' || *p > '9' || value > (max - (*p - '0')) / 10)
            return -1;
        value = value * 10 + (*p - '0');
    }
    *out = value;
    return 0;
}
static int fd_arg(const char *text, int *out, int optional) {
    uint64_t value;
    if (optional && !strcmp(text, "-1")) {
        *out = -1;
        return 0;
    }
    if (number(text, INT_MAX, &value) || value <= 2)
        return -1;
    *out = (int)value;
    return 0;
}
static int nonblock(int fd) {
    int flags = fcntl(fd, F_GETFL);
    return flags < 0 || fcntl(fd, F_SETFL, flags | O_NONBLOCK) < 0;
}
static int pipe_reader(int fd) {
    struct stat st;
    int flags = fcntl(fd, F_GETFL);
    return flags < 0 || (flags & O_ACCMODE) != O_RDONLY || flags & O_ASYNC || fstat(fd, &st) ||
           !S_ISFIFO(st.st_mode) || nonblock(fd);
}
static int live(int fd) {
    unsigned char byte;
    ssize_t got = read(fd, &byte, 1);
    return got < 0 && (errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR) ? 0 : -1;
}
static int exited(int pidfd) {
    struct pollfd p = {pidfd, POLLIN, 0};
    int got = poll(&p, 1, 0);
    if (got < 0)
        return -1;
    return got && p.revents & POLLIN ? 1 : p.revents ? -1 : 0;
}
static int zero(const void *value, size_t size) {
    const unsigned char *p = value;
    for (size_t i = 0; i < size; i++)
        if (p[i])
            return -1;
    return 0;
}
static int close_except(const int *keep, size_t count) {
    int sorted[32];
    if (count > 32)
        return -1;
    for (size_t i = 0; i < count; i++) {
        if (keep[i] <= 2)
            return -1;
        sorted[i] = keep[i];
        for (size_t j = i; j && sorted[j] < sorted[j - 1]; j--) {
            int tmp = sorted[j];
            sorted[j] = sorted[j - 1];
            sorted[j - 1] = tmp;
        }
    }
    unsigned int first = 0;
    for (size_t i = 0; i < count; i++) {
        unsigned int fd = (unsigned int)sorted[i];
        if (i && sorted[i - 1] == sorted[i])
            return -1;
        if (first < fd && syscall(SYS_close_range, first, fd - 1, 0))
            return -1;
        first = fd + 1;
    }
    return syscall(SYS_close_range, first, UINT_MAX, 0) ? -1 : 0;
}
static int signals_ready(void) {
    struct sigaction current;
    if (sigaction(SIGCHLD, NULL, &current) || current.sa_handler == SIG_IGN ||
        current.sa_flags & SA_NOCLDWAIT)
        return -1;
    struct sigaction action;
    memset(&action, 0, sizeof(action));
    action.sa_handler = SIG_DFL;
    sigemptyset(&action.sa_mask);
    if (sigaction(SIGCHLD, &action, NULL))
        return -1;
    signal(SIGPIPE, SIG_IGN);
    return 0;
}
static int checked_read(int fd, const wq_identity_t *pin, char *out, size_t capacity,
                        uint64_t deadline, int cgroup) {
    wq_identity_t now;
    if (wq_remaining(deadline) < 0 || wq_identity(fd, &now, cgroup) ||
        !wq_identity_equal(&now, pin))
        return -1;
    size_t used = 0;
    for (;;) {
        if (wq_remaining(deadline) < 0)
            return -1;
        /* S and G inherit some of these original open file descriptions.
         * Their exact reads must not race through a shared seek position. */
        ssize_t got = pread(fd, out + used, capacity - used, (off_t)used);
        if (got < 0 && errno == EINTR)
            continue;
        if (got < 0)
            return -1;
        if (!got)
            break;
        used += (size_t)got;
        if (used == capacity)
            return -1;
    }
    if (wq_remaining(deadline) < 0 || wq_identity(fd, &now, cgroup) ||
        !wq_identity_equal(&now, pin))
        return -1;
    out[used] = 0;
    return (int)used;
}
static int scope_events(scope_t *s, int reader, int *populated) {
    char raw[WQ_EVENT_BYTES + 1];
    int got = checked_read(s->files[reader], &s->pins[reader], raw, WQ_EVENT_BYTES, s->deadline, 1);
    if (got < 0)
        return -1;
    if (!strcmp(raw, "populated 0\nfrozen 0\n") || !strcmp(raw, "frozen 0\npopulated 0\n")) {
        *populated = 0;
        return 0;
    }
    if (!strcmp(raw, "populated 1\nfrozen 0\n") || !strcmp(raw, "frozen 0\npopulated 1\n")) {
        *populated = 1;
        return 0;
    }
    return -1;
}
static int scope_check(scope_t *s, int guardian) {
    wq_identity_t current;
    struct stat named;
    if (wq_remaining(s->deadline) < 0 || wq_identity(s->leaf, &current, 1) ||
        !wq_identity_equal(&current, &s->leaf_pin))
        return -1;
    if (!guardian &&
        (wq_identity(s->delegation, &current, 1) || !wq_identity_equal(&current, &s->parent_pin) ||
         fstatat(s->delegation, s->name, &named, AT_SYMLINK_NOFOLLOW) ||
         (uint64_t)named.st_dev != s->leaf_pin.device || named.st_ino != s->leaf_pin.inode))
        return -1;
    for (int i = 0; i < 8; i++) {
        if (guardian && (i == 4 || i == 5))
            continue;
        if (wq_identity(s->files[i], &current, 1) || !wq_identity_equal(&current, &s->pins[i]) ||
            fstatat(s->leaf, scope_names[i], &named, AT_SYMLINK_NOFOLLOW) ||
            (uint64_t)named.st_dev != current.device || named.st_ino != current.inode)
            return -1;
    }
    {
        char raw[WQ_EVENT_BYTES + 1];
        if (checked_read(s->files[0], &s->pins[0], raw, WQ_EVENT_BYTES, s->deadline, 1) < 0 ||
            strcmp(raw, "domain\n"))
            return -1;
        int got = checked_read(s->files[1], &s->pins[1], raw, WQ_EVENT_BYTES, s->deadline, 1);
        if (got < 0 || (got && strcmp(raw, "\n")))
            return -1;
        for (int i = 2; i < 4; i++)
            if (checked_read(s->files[i], &s->pins[i], raw, WQ_EVENT_BYTES, s->deadline, 1) < 0 ||
                strcmp(raw, "0\n"))
                return -1;
        int copy = openat(s->leaf, ".", O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
        if (copy < 0)
            return -1;
        DIR *directory = fdopendir(copy);
        if (!directory) {
            close(copy);
            return -1;
        }
        struct dirent *entry;
        int invalid = 0;
        errno = 0;
        while ((entry = readdir(directory))) {
            if (!strcmp(entry->d_name, ".") || !strcmp(entry->d_name, ".."))
                continue;
            if (fstatat(s->leaf, entry->d_name, &named, AT_SYMLINK_NOFOLLOW) ||
                S_ISDIR(named.st_mode) || wq_remaining(s->deadline) < 0) {
                invalid = 1;
                break;
            }
        }
        if (errno)
            invalid = 1;
        closedir(directory);
        if (invalid)
            return -1;
    }
    return wq_remaining(s->deadline) < 0 ? -1 : 0;
}
static int scope_create(scope_t *s, int delegation, const wq_identity_t *parent,
                        const wq_binding_t *binding) {
    memset(s, 0, sizeof(*s));
    s->delegation = delegation;
    s->leaf = -1;
    s->deadline = binding->deadline_ns;
    for (int i = 0; i < 8; i++)
        s->files[i] = -1;
    if (wq_identity(delegation, &s->parent_pin, 1) || !wq_identity_equal(&s->parent_pin, parent) ||
        !S_ISDIR(parent->mode))
        return -1;
    int size = snprintf(s->name, sizeof(s->name), "lunar-%s", binding->launch_sha256);
    if (size != 70 || mkdirat(delegation, s->name, 0700))
        return -1;
    s->leaf = openat(delegation, s->name, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (s->leaf < 0 || wq_identity(s->leaf, &s->leaf_pin, 1) || s->leaf_pin.uid ||
        !S_ISDIR(s->leaf_pin.mode) || s->leaf_pin.device != parent->device ||
        s->leaf_pin.mount_id != parent->mount_id || s->leaf_pin.inode == parent->inode)
        return -1;
    for (int i = 0; i < 8; i++) {
        int writable = i == 2 || i == 3 || i == 5 || i == 7;
        int flags = (writable ? O_WRONLY : O_RDONLY) | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK;
        if (i == 2 || i == 3)
            flags = (flags & ~O_ACCMODE) | O_RDWR;
        s->files[i] = openat(s->leaf, scope_names[i], flags);
        if (s->files[i] < 0 || wq_identity(s->files[i], &s->pins[i], 1) ||
            !S_ISREG(s->pins[i].mode) || s->pins[i].uid ||
            s->pins[i].device != s->leaf_pin.device || s->pins[i].mount_id != s->leaf_pin.mount_id)
            return -1;
        if ((i == 2 || i == 3) &&
            (wq_remaining(s->deadline) < 0 || write(s->files[i], "0", 1) != 1 ||
             wq_remaining(s->deadline) < 0))
            return -1;
    }
    int populated;
    if (scope_check(s, 0) || scope_events(s, 4, &populated) || populated)
        return -1;
    return 0;
}
static void scope_kill(scope_t *s, int guardian) {
    int fd = s->files[guardian ? 7 : 5];
    if (fd >= 0) {
        ssize_t ignored = write(fd, "1", 1);
        (void)ignored;
    }
}
static int child_clone(child_t *child) {
    memset(child, 0, sizeof(*child));
    child->fd = -1;
    child->pidfd = -1;
    struct clone_args arguments;
    memset(&arguments, 0, sizeof(arguments));
    arguments.flags = CLONE_PIDFD;
    arguments.pidfd = (uint64_t)(uintptr_t)&child->pidfd;
    arguments.exit_signal = SIGCHLD;
    pid_t pid = (pid_t)syscall(SYS_clone3, &arguments, sizeof(arguments));
    if (pid < 0)
        return -1;
    if (!pid)
        return 0;
    child->pid = pid;
    if (child->pidfd <= 2 || syscall(SYS_pidfd_send_signal, child->pidfd, 0, NULL, 0))
        return -1;
    return 1;
}
static int child_wait(child_t *child, uint64_t deadline, int expected_zero) {
    if (child->pidfd < 0 || child->reaped)
        return -1;
    for (;;) {
        if (wq_remaining(deadline) < 0)
            return -1;
        siginfo_t observed;
        memset(&observed, 0, sizeof(observed));
        if (waitid(P_PIDFD, (id_t)child->pidfd, &observed, WEXITED | WNOHANG))
            return -1;
        if (observed.si_pid) {
            if (observed.si_pid != child->pid)
                return -1;
            child->reaped = 1;
            if (wq_remaining(deadline) < 0)
                return -1;
            return expected_zero && (observed.si_code != CLD_EXITED || observed.si_status) ? -1 : 0;
        }
        struct pollfd p = {child->pidfd, POLLIN, 0};
        int remaining = wq_remaining(deadline);
        if (remaining < 0)
            return -1;
        if (poll(&p, 1, remaining) < 0 && errno != EINTR)
            return -1;
    }
}
static int supervisor_check(supervisor_t *s) {
    uint64_t now;
    if ((s->custody_v2 || s->custody_v3) && !s->failure_reason) {
        struct pollfd controller = {s->controller, POLLIN, 0};
        int observed = poll(&controller, 1, 0);
        if (wq_remaining(s->deadline) < 0 ||
            (s->controller_released && !s->cleanup_started &&
             (wq_now(&now) || now >= s->execution_cutoff)))
            s->failure_reason = WQ_CUSTODY_DEADLINE;
        else if (live(s->lifeline) ||
                 (observed > 0 && controller.revents & (POLLHUP | POLLERR | POLLNVAL)))
            s->failure_reason = WQ_CUSTODY_CONTROLLER_LOST;
        else if (s->receiver.pidfd >= 0 && !s->receiver_retiring && exited(s->receiver.pidfd))
            s->failure_reason = WQ_CUSTODY_RECEIVER_FAULT;
    }
    if (wq_remaining(s->deadline) < 0 || live(s->lifeline) ||
        (s->controller_released && !s->cleanup_started &&
         (wq_now(&now) || now >= s->execution_cutoff)) ||
        (!s->bootstrap_finishing && exited(s->bootstrap)) ||
        (s->guardian.pidfd >= 0 && !s->guardian_retiring && exited(s->guardian.pidfd)) ||
        (s->receiver.pidfd >= 0 && !s->receiver_retiring && exited(s->receiver.pidfd)))
        return -1;
    if (s->controller_released) {
        struct pollfd control = {s->controller, POLLIN, 0};
        int observed = poll(&control, 1, 0);
        if (observed < 0 || observed || control.revents)
            return -1;
    }
    if (wq_chain_check(&s->delegation_chain))
        return -1;
    return scope_check(&s->scope, 0);
}
static void custody_failure_fallback(supervisor_t *s) {
    if ((s->custody_v2 || s->custody_v3) && !s->failure_reason) {
        /* Preserve an actually observed original lifeline, deadline or R
         * failure. A generic scope/chain/G/packet refusal cannot identify R. */
        (void)supervisor_check(s);
        if (!s->failure_reason)
            s->failure_reason = WQ_CUSTODY_PROTOCOL;
    }
}
static int transfer(supervisor_t *s, int socket, wq_message_t *message, int *rights, size_t count,
                    int sending) {
    for (;;) {
        if (supervisor_check(s))
            return -1;
        int result = sending ? wq_send(socket, message, rights, count)
                             : wq_receive(socket, message, rights, count, s->deadline);
        if (!result) {
            if (sending && socket == s->guardian.fd && message->operation == WQ_GUARD_RETIRE)
                s->guardian_retiring = 1;
            if (sending && socket == s->receiver.fd && message->operation == WQ_STORE_EVENT)
                s->receiver_retiring = 1;
            if (sending && socket == s->lifecycle && message->operation == WQ_COMPLETE)
                s->bootstrap_finishing = 1;
            return supervisor_check(s);
        }
        if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)
            return -1;
        struct pollfd p = {socket, sending ? POLLOUT : POLLIN, 0};
        int remaining = wq_remaining(s->deadline);
        if (remaining < 0)
            return -1;
        if (poll(&p, 1, remaining) < 0 && errno != EINTR)
            return -1;
        if (p.revents & (POLLHUP | POLLERR | POLLNVAL))
            return -1;
    }
}
static int message_payload(const wq_message_t *message, const scope_t *scope, uint64_t target,
                           int pubs) {
    return !wq_identity_equal(&message->scope, &scope->leaf_pin) || message->target_pid != target ||
           (!pubs && zero(message->publications, sizeof(message->publications)));
}
static int send_simple(supervisor_t *s, int socket, uint32_t operation, uint32_t sequence) {
    wq_message_t message;
    wq_message_init(&message, &s->binding, operation, sequence, 0);
    message.scope = s->scope.leaf_pin;
    message.target_pid = s->target_pid;
    if (socket == s->lifecycle && (operation == WQ_RELEASE_PERMIT || operation == WQ_COMPLETE))
        memcpy(message.publications, s->publication_pins, sizeof(message.publications));
    return transfer(s, socket, &message, NULL, 0, 1);
}
static int receive_simple(supervisor_t *s, int socket, uint32_t operation, uint32_t sequence) {
    wq_message_t message;
    int publication_reply = socket == s->lifecycle && operation == WQ_TARGET_DONE;
    if (transfer(s, socket, &message, NULL, 0, 0) ||
        wq_message_check(&message, &s->binding, operation, sequence, 0) ||
        message_payload(&message, &s->scope, s->target_pid, publication_reply) ||
        (publication_reply &&
         memcmp(message.publications, s->publication_pins, sizeof(message.publications))))
        return -1;
    if (socket == s->controller && operation == WQ_RELEASE)
        s->controller_released = 1;
    return 0;
}
/* Always close the possible late-clone route before killing even an empty
 * scope. Deadline expiry permits emergency actions only, never positive facts. */
static uint32_t emergency_stop_observed(scope_t *scope, int bootstrap, int guardian) {
    uint32_t facts = WQ_CUSTODY_STOP_ATTEMPTED;
    int ignored = (int)syscall(SYS_pidfd_send_signal, bootstrap, SIGKILL, NULL, 0);
    (void)ignored;
    int enrollment_closed = 0;
    while (wq_remaining(scope->deadline) >= 0) {
        int observed = exited(bootstrap);
        if (observed == 1) {
            enrollment_closed = 1;
            facts |= WQ_CUSTODY_BOOTSTRAP_EXIT;
            break;
        }
        if (observed < 0)
            break;
        struct pollfd p = {bootstrap, POLLIN, 0};
        int timeout = wq_remaining(scope->deadline);
        if (timeout < 0)
            break;
        if (poll(&p, 1, timeout) < 0 && errno != EINTR)
            break;
    }
    scope_kill(scope, guardian);
    /* A successful kill write, B exit or channel EOF cannot substitute for
     * the original recursive empty read. Failure callers retain unknown even
     * when this best-effort observation completes inside the original budget. */
    if (!enrollment_closed)
        return facts;
    for (;;) {
        int populated;
        if (scope_check(scope, guardian) || scope_events(scope, guardian ? 6 : 4, &populated))
            return facts;
        if (!populated)
            return facts | WQ_CUSTODY_SCOPE_EMPTY;
        struct pollfd p = {scope->files[guardian ? 6 : 4], POLLPRI | POLLERR, 0};
        int ms = wq_remaining(scope->deadline);
        if (ms < 0 || (poll(&p, 1, ms) < 0 && errno != EINTR))
            return facts;
    }
}
static void emergency_stop(scope_t *scope, int bootstrap, int guardian) {
    (void)emergency_stop_observed(scope, bootstrap, guardian);
}
static _Noreturn void guardian_main(scope_t scope, const wq_binding_t *binding, int bootstrap,
                                    int controller, int parent, int channel) {
    int keep[] = {scope.leaf,     scope.files[0], scope.files[1], scope.files[2],
                  scope.files[3], scope.files[6], scope.files[7], bootstrap,
                  controller,     parent,         channel};
    if (close_except(keep, 11) || wq_socket(channel) || pipe_reader(controller) ||
        pipe_reader(parent) || scope_check(&scope, 1) ||
        syscall(SYS_pidfd_send_signal, bootstrap, 0, NULL, 0))
        goto failure;
    wq_message_t ready;
    wq_message_init(&ready, binding, WQ_GUARD_READY, 0, 0);
    ready.scope = scope.leaf_pin;
    for (;;) {
        if (wq_remaining(scope.deadline) < 0 || live(controller) || live(parent) ||
            exited(bootstrap))
            goto failure;
        if (!wq_send(channel, &ready, NULL, 0))
            break;
        if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)
            goto failure;
    }
    for (;;) {
        if (wq_remaining(scope.deadline) < 0 || live(controller) || live(parent) ||
            exited(bootstrap) || scope_check(&scope, 1))
            goto failure;
        wq_message_t message;
        if (!wq_receive(channel, &message, NULL, 0, scope.deadline)) {
            int populated;
            if (wq_message_check(&message, binding, WQ_GUARD_RETIRE, 1, 0) ||
                !wq_identity_equal(&message.scope, &scope.leaf_pin) ||
                zero(message.publications, sizeof(message.publications)) || !message.target_pid ||
                scope_events(&scope, 6, &populated) || populated || scope_check(&scope, 1))
                goto failure;
            _exit(0);
        }
        if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)
            goto failure;
        struct pollfd observed[3] = {
            {channel, POLLIN, 0}, {controller, POLLIN, 0}, {parent, POLLIN, 0}};
        int timeout = wq_remaining(scope.deadline);
        if (timeout < 0)
            goto failure;
        if (poll(observed, 3, timeout) < 0 && errno != EINTR)
            goto failure;
        if (observed[0].revents & (POLLERR | POLLHUP | POLLNVAL))
            goto failure;
    }
failure:
    emergency_stop(&scope, bootstrap, 1);
    _exit(WQ_FAILURE);
}
static int private_directory(int fd, wq_identity_t *pin) {
    return wq_identity(fd, pin, 0) || !S_ISDIR(pin->mode) || pin->uid || pin->gid ||
           (pin->mode & 07777) != 0700;
}
static int private_no_acl(int fd) {
    const char *names[] = {"system.posix_acl_access", "system.posix_acl_default"};
    for (size_t i = 0; i < 2; i++)
        if (fgetxattr(fd, names[i], NULL, 0) >= 0 || errno != ENODATA)
            return -1;
    return 0;
}
static int store_record_bytes(int directory, int fd, const char *name, const void *record,
                              size_t size, uint64_t deadline, const wq_identity_t *parent,
                              const wq_identity_t *original, int private_acl) {
    wq_identity_t now;
    struct stat named, held;
    if (wq_remaining(deadline) < 0 || wq_identity(directory, &now, 0) ||
        !wq_identity_equal(parent, &now) || wq_identity(fd, &now, 0) ||
        !wq_identity_equal(original, &now) ||
        (private_acl && (private_no_acl(directory) || private_no_acl(fd))) ||
        fstatat(directory, name, &named, AT_SYMLINK_NOFOLLOW) ||
        (uint64_t)named.st_dev != original->device || named.st_ino != original->inode ||
        named.st_nlink != 1 || named.st_mode != original->mode ||
        named.st_uid != original->uid || named.st_gid != original->gid || named.st_size)
        return -1;
    size_t offset = 0;
    while (offset < size) {
        if (wq_remaining(deadline) < 0)
            return -1;
        ssize_t n = write(fd, (const char *)record + offset, size - offset);
        if (n < 0 && errno == EINTR)
            continue;
        if (n <= 0)
            return -1;
        offset += (size_t)n;
    }
    if (fsync(fd) || fsync(directory) || wq_remaining(deadline) < 0 ||
        wq_identity(directory, &now, 0) || !wq_identity_equal(parent, &now) ||
        wq_identity(fd, &now, 0) || !wq_identity_equal(original, &now) ||
        (private_acl && (private_no_acl(directory) || private_no_acl(fd))) ||
        fstat(fd, &held) || held.st_size != (off_t)size || held.st_nlink != 1 ||
        fstatat(directory, name, &named, AT_SYMLINK_NOFOLLOW) ||
        named.st_size != (off_t)size || named.st_ino != original->inode ||
        (uint64_t)named.st_dev != original->device || named.st_nlink != 1 ||
        named.st_mode != original->mode || named.st_uid != original->uid ||
        named.st_gid != original->gid)
        return -1;
    return 0;
}
static int store_record(int directory, int fd, const char *name, const wq_message_t *message,
                        const wq_identity_t *parent, const wq_identity_t *original) {
    return store_record_bytes(directory, fd, name, message, sizeof(*message),
                              message->binding.deadline_ns, parent, original, 0);
}
static const char *v3_record_names[2] = {"scope-registration-v3.bin", "scope-terminal-v3.bin"};
static int v3_fixed_names(int directory, const wq_identity_t *parent, uint64_t deadline) {
    if (wq_remaining(deadline) < 0)
        return -1;
    int scan = openat(directory, ".", O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    wq_identity_t current;
    if (scan < 0)
        return -1;
    if (wq_identity(scan, &current, 0) || !wq_identity_equal(parent, &current)) {
        close(scan);
        return -1;
    }
    DIR *entries = fdopendir(scan);
    if (!entries) {
        close(scan);
        return -1;
    }
    unsigned int seen = 0;
    int result = -1;
    for (size_t i = 0; i < 5; i++) {
        if (wq_remaining(deadline) < 0)
            break;
        errno = 0;
        struct dirent *entry = readdir(entries);
        if (!entry) {
            if (!errno && seen == 3)
                result = 0;
            break;
        }
        if (!strcmp(entry->d_name, ".") || !strcmp(entry->d_name, ".."))
            continue;
        unsigned int bit = !strcmp(entry->d_name, v3_record_names[0]) ? 1u :
                           !strcmp(entry->d_name, v3_record_names[1]) ? 2u : 0u;
        if (!bit || (seen & bit))
            break;
        seen |= bit;
    }
    if (closedir(entries) || wq_remaining(deadline) < 0)
        return -1;
    return result;
}
static int v3_record_identity(int directory, int fd, const char *name,
                              const wq_identity_t *parent, const wq_identity_t *pin,
                              off_t size, uint64_t deadline) {
    wq_identity_t current;
    struct stat held, named;
    if (wq_remaining(deadline) < 0)
        return -1;
    int flags = fcntl(fd, F_GETFL), descriptor_flags = fcntl(fd, F_GETFD);
    /* Linux may expose the kernel O_LARGEFILE bit even when libc's x86-64
     * O_LARGEFILE constant is zero. No caller changes shared OFD flags/offset. */
    int allowed = O_ACCMODE | O_NOFOLLOW | O_LARGEFILE | 0100000;
    return wq_remaining(deadline) < 0 || private_directory(directory, &current) ||
           !wq_identity_equal(parent, &current) || private_no_acl(directory) ||
           fd <= 2 || flags < 0 || (flags & O_ACCMODE) != O_RDWR || (flags & ~allowed) ||
           descriptor_flags < 0 || !(descriptor_flags & FD_CLOEXEC) ||
           wq_identity(fd, &current, 0) || !wq_identity_equal(pin, &current) ||
           !S_ISREG(current.mode) || current.uid || current.gid ||
           (current.mode & 07777) != 0600 || current.device != parent->device ||
           current.mount_id != parent->mount_id || private_no_acl(fd) ||
           fstat(fd, &held) || held.st_nlink != 1 || held.st_size != size ||
           fstatat(directory, name, &named, AT_SYMLINK_NOFOLLOW) ||
           (uint64_t)named.st_dev != pin->device || named.st_ino != pin->inode ||
           named.st_mode != pin->mode || named.st_uid != pin->uid || named.st_gid != pin->gid ||
           named.st_nlink != 1 || named.st_size != size || wq_remaining(deadline) < 0;
}
/* The empty terminal has no permitted mutation before R's one terminal write.
 * Retain its actual first observation, not a new zero-length observation after
 * a write/truncate pair. atime is deliberately excluded: bounded pread may
 * update it without changing a record. */
static int v3_stat_equal(const struct stat *left, const struct stat *right) {
    return left->st_dev == right->st_dev && left->st_ino == right->st_ino &&
           left->st_mode == right->st_mode && left->st_uid == right->st_uid &&
           left->st_gid == right->st_gid && left->st_nlink == right->st_nlink &&
           left->st_size == right->st_size &&
           left->st_mtim.tv_sec == right->st_mtim.tv_sec &&
           left->st_mtim.tv_nsec == right->st_mtim.tv_nsec &&
           left->st_ctim.tv_sec == right->st_ctim.tv_sec &&
           left->st_ctim.tv_nsec == right->st_ctim.tv_nsec;
}
static int v3_stat_pin_check(int directory, int fd, const char *name,
                              const struct stat *original, uint64_t deadline) {
    struct stat held, named;
    return wq_remaining(deadline) < 0 || fstat(fd, &held) ||
           !v3_stat_equal(original, &held) ||
           fstatat(directory, name, &named, AT_SYMLINK_NOFOLLOW) ||
           !v3_stat_equal(original, &named) || wq_remaining(deadline) < 0;
}
static int v3_empty_terminal_check(int directory, int fd, const struct stat *original,
                                   uint64_t deadline) {
    return original->st_size ||
           v3_stat_pin_check(directory, fd, v3_record_names[1], original, deadline);
}
static int v3_creators_check(int directory, const int files[2], const wq_identity_t *parent,
                              const wq_identity_t pins[2], const wq_message_t *registration,
                              const wq_custody_event_t *terminal, uint64_t deadline) {
    off_t sizes[] = {registration ? (off_t)sizeof(*registration) : 0,
                     terminal ? (off_t)sizeof(*terminal) : 0};
    struct stat before[2], held, named;
    if (wq_fd_distinct(files, 2) || v3_fixed_names(directory, parent, deadline))
        return -1;
    for (size_t i = 0; i < 2; i++)
        if (v3_record_identity(directory, files[i], v3_record_names[i], parent, &pins[i],
                               sizes[i], deadline) || fstat(files[i], &before[i]))
            return -1;
    char raw[sizeof(wq_custody_event_t) + 1];
    if (registration &&
        (checked_read(files[0], &pins[0], raw, sizeof(*registration) + 1, deadline, 0) !=
             (int)sizeof(*registration) || memcmp(raw, registration, sizeof(*registration))))
        return -1;
    if (terminal &&
        (checked_read(files[1], &pins[1], raw, sizeof(*terminal) + 1, deadline, 0) !=
             (int)sizeof(*terminal) || memcmp(raw, terminal, sizeof(*terminal))))
        return -1;
    for (size_t i = 0; i < 2; i++)
        if (v3_record_identity(directory, files[i], v3_record_names[i], parent, &pins[i],
                               sizes[i], deadline) || fstat(files[i], &held) ||
            !v3_stat_equal(&before[i], &held) ||
            fstatat(directory, v3_record_names[i], &named, AT_SYMLINK_NOFOLLOW) ||
            !v3_stat_equal(&before[i], &named))
            return -1;
    return v3_fixed_names(directory, parent, deadline);
}
static _Noreturn void receiver_main(int directory, int channel, const wq_binding_t *binding,
                                    const wq_identity_t *scope) {
    int keep[] = {directory, channel};
    if (close_except(keep, 2) || wq_socket(channel))
        _exit(WQ_FAILURE);
    wq_identity_t parent, pins[2];
    int files[2] = {-1, -1};
    const char *names[2] = {"scope-registration-v1.bin", "scope-terminal-v1.bin"};
    if (private_directory(directory, &parent))
        _exit(WQ_FAILURE);
    for (int i = 0; i < 2; i++) {
        files[i] =
            openat(directory, names[i], O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
        if (files[i] < 0 || wq_identity(files[i], &pins[i], 0) || pins[i].uid || pins[i].gid ||
            (pins[i].mode & 07777) != 0600)
            _exit(WQ_FAILURE);
    }
    uint64_t target = 0;
    wq_publication_t originals[3];
    memset(originals, 0, sizeof(originals));
    for (uint32_t sequence = 1; sequence <= 2; sequence++) {
        wq_message_t message;
        for (;;) {
            if (wq_remaining(binding->deadline_ns) < 0)
                _exit(WQ_FAILURE);
            if (!wq_receive(channel, &message, NULL, 0, binding->deadline_ns))
                break;
            if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)
                _exit(WQ_FAILURE);
            struct pollfd p = {channel, POLLIN, 0};
            int ms = wq_remaining(binding->deadline_ns);
            if (ms < 0 || (poll(&p, 1, ms) < 0 && errno != EINTR))
                _exit(WQ_FAILURE);
        }
        if (wq_message_check(&message, binding, sequence == 1 ? WQ_STORE_REGISTER : WQ_STORE_EVENT,
                             sequence, 0) ||
            !wq_identity_equal(scope, &message.scope) || !message.target_pid ||
            message.target_pid > INT_MAX)
            _exit(WQ_FAILURE);
        for (size_t i = 0; i < 3; i++)
            if (!message.publications[i].inode || !message.publications[i].size ||
                wq_digest(message.publications[i].sha256))
                _exit(WQ_FAILURE);
        if (sequence == 1) {
            target = message.target_pid;
            memcpy(originals, message.publications, sizeof(originals));
        } else if (message.target_pid != target ||
                   memcmp(originals, message.publications, sizeof(originals)))
            _exit(WQ_FAILURE);
        if (store_record(directory, files[sequence - 1], names[sequence - 1], &message, &parent,
                         &pins[sequence - 1]))
            _exit(WQ_FAILURE);
        wq_message_t ack;
        wq_message_init(&ack, binding, WQ_STORE_ACK, sequence, 0);
        ack.scope = *scope;
        ack.target_pid = message.target_pid;
        for (;;) {
            if (!wq_send(channel, &ack, NULL, 0))
                break;
            if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)
                _exit(WQ_FAILURE);
            if (wq_remaining(binding->deadline_ns) < 0)
                _exit(WQ_FAILURE);
        }
    }
    _exit(0);
}
/* Selected only by --supervisor-custody-v2. R has no execution, signal,
 * lifeline or scope handle; blocking filesystem work cannot block G's stop. */
static _Noreturn void receiver_v2_main(int directory, int channel, const wq_binding_t *binding,
                                       const wq_identity_t *scope) {
    int keep[] = {directory, channel};
    if (close_except(keep, 2) || wq_socket(channel))
        _exit(WQ_FAILURE);
    wq_identity_t parent, pins[2];
    int files[2];
    const char *names[] = {"scope-registration-v2.bin", "scope-terminal-v2.bin"};
    if (private_directory(directory, &parent) || private_no_acl(directory))
        _exit(WQ_FAILURE);
    for (int i = 0; i < 2; i++) {
        files[i] = openat(directory, names[i], O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
        if (files[i] < 0 || wq_identity(files[i], &pins[i], 0) || pins[i].uid || pins[i].gid ||
            (pins[i].mode & 07777) != 0600)
            _exit(WQ_FAILURE);
    }
    wq_message_t registration;
    for (;;) {
        if (wq_remaining(binding->deadline_ns) < 0)
            _exit(WQ_FAILURE);
        if (!wq_receive(channel, &registration, NULL, 0, binding->deadline_ns))
            break;
        if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)
            _exit(WQ_FAILURE);
        struct pollfd p = {channel, POLLIN, 0};
        int ms = wq_remaining(binding->deadline_ns);
        if (ms < 0 || (poll(&p, 1, ms) < 0 && errno != EINTR))
            _exit(WQ_FAILURE);
    }
    if (wq_message_check(&registration, binding, WQ_STORE_REGISTER, 1, 0) ||
        !wq_identity_equal(scope, &registration.scope) || !registration.target_pid ||
        registration.target_pid > INT_MAX)
        _exit(WQ_FAILURE);
    for (size_t i = 0; i < 3; i++)
        if (!registration.publications[i].inode || !registration.publications[i].size ||
            wq_digest(registration.publications[i].sha256))
            _exit(WQ_FAILURE);
    if (store_record_bytes(directory, files[0], names[0], &registration, sizeof(registration),
                           binding->deadline_ns, &parent, &pins[0], 1))
        _exit(WQ_FAILURE);
    wq_message_t ack;
    wq_message_init(&ack, binding, WQ_STORE_ACK, 1, 0);
    ack.scope = *scope;
    ack.target_pid = registration.target_pid;
    for (;;) {
        if (!wq_send(channel, &ack, NULL, 0))
            break;
        if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)
            _exit(WQ_FAILURE);
    }
    wq_custody_event_t event;
    for (;;) {
        if (wq_remaining(binding->deadline_ns) < 0)
            _exit(WQ_FAILURE);
        if (!wq_custody_receive(channel, &event, binding->deadline_ns))
            break;
        if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)
            _exit(WQ_FAILURE);
        struct pollfd p = {channel, POLLIN, 0};
        int ms = wq_remaining(binding->deadline_ns);
        if (ms < 0 || (poll(&p, 1, ms) < 0 && errno != EINTR))
            _exit(WQ_FAILURE);
    }
    if (wq_custody_event_check(&event, &registration) ||
        store_record_bytes(directory, files[1], names[1], &event, sizeof(event),
                           binding->deadline_ns, &parent, &pins[1], 1))
        _exit(WQ_FAILURE);
    ack = event.original;
    ack.operation = WQ_CUSTODY_ACK;
    for (;;) {
        if (!wq_send(channel, &ack, NULL, 0))
            break;
        if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)
            _exit(WQ_FAILURE);
    }
    _exit(0);
}
static _Noreturn void receiver_v3_main(int directory, int channel, const wq_binding_t *binding,
                                       const wq_identity_t *scope) {
    int keep[] = {directory, channel};
    if (wq_remaining(binding->deadline_ns) < 0 || close_except(keep, 2) || wq_socket(channel))
        _exit(WQ_FAILURE);
    wq_identity_t parent, pins[2];
    struct stat original_registration, empty_terminal;
    int files[2] = {-1, -1};
    if (private_directory(directory, &parent) || private_no_acl(directory))
        _exit(WQ_FAILURE);
    for (size_t i = 0; i < 2; i++) {
        if (wq_remaining(binding->deadline_ns) < 0)
            _exit(WQ_FAILURE);
        files[i] = openat(directory, v3_record_names[i],
                          O_RDWR | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
        if (files[i] >= 0 && files[i] <= 2) {
            /* close_except intentionally removed stdio. Retain that exact
             * creator OFD above stdio without reopening its name. */
            int original = files[i];
            files[i] = fcntl(original, F_DUPFD_CLOEXEC, 3);
            close(original);
        }
        if (files[i] < 0 || wq_identity(files[i], &pins[i], 0))
            _exit(WQ_FAILURE);
    }
    if (fstat(files[1], &empty_terminal) ||
        v3_creators_check(directory, files, &parent, pins, NULL, NULL, binding->deadline_ns) ||
        v3_empty_terminal_check(directory, files[1], &empty_terminal, binding->deadline_ns))
        _exit(WQ_FAILURE);
    wq_message_t registration;
    for (;;) {
        if (wq_remaining(binding->deadline_ns) < 0)
            _exit(WQ_FAILURE);
        if (!wq_receive(channel, &registration, NULL, 0, binding->deadline_ns))
            break;
        if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)
            _exit(WQ_FAILURE);
        struct pollfd p = {channel, POLLIN, 0};
        int ms = wq_remaining(binding->deadline_ns);
        if (ms < 0 || (poll(&p, 1, ms) < 0 && errno != EINTR))
            _exit(WQ_FAILURE);
    }
    if (wq_v3_message_check(&registration, binding, WQ_V3_STORE_REGISTER, 1, 0) ||
        !wq_identity_equal(scope, &registration.scope) || !registration.target_pid ||
        registration.target_pid > INT_MAX)
        _exit(WQ_FAILURE);
    for (size_t i = 0; i < 3; i++)
        if (!registration.publications[i].inode || !registration.publications[i].size ||
            wq_digest(registration.publications[i].sha256))
            _exit(WQ_FAILURE);
    if (store_record_bytes(directory, files[0], v3_record_names[0], &registration,
                           sizeof(registration), binding->deadline_ns, &parent, &pins[0], 1) ||
        fstat(files[0], &original_registration) ||
        fsync(files[1]) || fsync(directory) ||
        v3_creators_check(directory, files, &parent, pins, &registration, NULL,
                           binding->deadline_ns) ||
        v3_stat_pin_check(directory, files[0], v3_record_names[0], &original_registration,
                            binding->deadline_ns) ||
        v3_empty_terminal_check(directory, files[1], &empty_terminal, binding->deadline_ns))
        _exit(WQ_FAILURE);
    wq_message_t creators = registration;
    creators.operation = WQ_V3_REGISTER_CREATORS;
    creators.fd_count = 2;
    for (;;) {
        if (wq_remaining(binding->deadline_ns) < 0 ||
            v3_stat_pin_check(directory, files[0], v3_record_names[0], &original_registration,
                                binding->deadline_ns) ||
            v3_empty_terminal_check(directory, files[1], &empty_terminal,
                                      binding->deadline_ns))
            _exit(WQ_FAILURE);
        if (!wq_send(channel, &creators, files, 2)) {
            if (v3_stat_pin_check(directory, files[0], v3_record_names[0], &original_registration,
                                    binding->deadline_ns))
                _exit(WQ_FAILURE);
            break;
        }
        if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)
            _exit(WQ_FAILURE);
        struct pollfd p = {channel, POLLOUT, 0};
        int ms = wq_remaining(binding->deadline_ns);
        if (ms < 0 || (poll(&p, 1, ms) < 0 && errno != EINTR))
            _exit(WQ_FAILURE);
    }
    wq_custody_event_t event;
    for (;;) {
        if (wq_remaining(binding->deadline_ns) < 0)
            _exit(WQ_FAILURE);
        if (!wq_custody_receive(channel, &event, binding->deadline_ns))
            break;
        if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)
            _exit(WQ_FAILURE);
        struct pollfd p = {channel, POLLIN, 0};
        int ms = wq_remaining(binding->deadline_ns);
        if (ms < 0 || (poll(&p, 1, ms) < 0 && errno != EINTR))
            _exit(WQ_FAILURE);
    }
    if (wq_v3_event_check(&event, &registration) ||
        v3_stat_pin_check(directory, files[0], v3_record_names[0], &original_registration,
                            binding->deadline_ns) ||
        v3_creators_check(directory, files, &parent, pins, &registration, NULL,
                           binding->deadline_ns) ||
        v3_empty_terminal_check(directory, files[1], &empty_terminal, binding->deadline_ns) ||
        store_record_bytes(directory, files[1], v3_record_names[1], &event, sizeof(event),
                           binding->deadline_ns, &parent, &pins[1], 1) ||
        v3_creators_check(directory, files, &parent, pins, &registration, &event,
                           binding->deadline_ns) ||
        v3_stat_pin_check(directory, files[0], v3_record_names[0], &original_registration,
                            binding->deadline_ns))
        _exit(WQ_FAILURE);
    wq_custody_event_t ack = event;
    ack.original.operation = WQ_V3_TERMINAL_ACK;
    for (;;) {
        if (v3_stat_pin_check(directory, files[0], v3_record_names[0], &original_registration,
                                binding->deadline_ns))
            _exit(WQ_FAILURE);
        if (!wq_custody_send(channel, &ack)) {
            if (v3_stat_pin_check(directory, files[0], v3_record_names[0], &original_registration,
                                    binding->deadline_ns))
                _exit(WQ_FAILURE);
            break;
        }
        if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)
            _exit(WQ_FAILURE);
        struct pollfd p = {channel, POLLOUT, 0};
        int ms = wq_remaining(binding->deadline_ns);
        if (ms < 0 || (poll(&p, 1, ms) < 0 && errno != EINTR))
            _exit(WQ_FAILURE);
    }
    _exit(0);
}
static int start_guardian(supervisor_t *s) {
    int channel[2], lifeline[2];
    if (socketpair(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC | SOCK_NONBLOCK, 0, channel) ||
        pipe2(lifeline, O_CLOEXEC | O_NONBLOCK))
        return -1;
    int cloned = child_clone(&s->guardian);
    if (!cloned) {
        close(channel[0]);
        close(lifeline[1]);
        guardian_main(s->scope, &s->binding, s->bootstrap, s->lifeline, lifeline[0], channel[1]);
    }
    if (cloned < 0) {
        close(channel[0]);
        close(channel[1]);
        close(lifeline[0]);
        close(lifeline[1]);
        return -1;
    }
    s->guardian.fd = channel[0];
    s->guardian_lifeline = lifeline[1];
    close(channel[1]);
    close(lifeline[0]);
    wq_message_t ready;
    if (transfer(s, s->guardian.fd, &ready, NULL, 0, 0) ||
        wq_message_check(&ready, &s->binding, WQ_GUARD_READY, 0, 0) ||
        message_payload(&ready, &s->scope, 0, 0))
        return -1;
    /* G now owns its independently opened event description and kill writer. */
    return 0;
}
static int start_receiver(supervisor_t *s) {
    if (s->custody < 0)
        return 0;
    wq_identity_t pin;
    if (private_directory(s->custody, &pin))
        return -1;
    if (s->custody_v3) {
        if (private_no_acl(s->custody))
            return -1;
        s->custody_parent = pin;
    }
    int channel[2];
    if (socketpair(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC | SOCK_NONBLOCK, 0, channel))
        return -1;
    int cloned = child_clone(&s->receiver);
    if (!cloned) {
        close(channel[0]);
        if (s->custody_v3)
            receiver_v3_main(s->custody, channel[1], &s->binding, &s->scope.leaf_pin);
        if (s->custody_v2)
            receiver_v2_main(s->custody, channel[1], &s->binding, &s->scope.leaf_pin);
        receiver_main(s->custody, channel[1], &s->binding, &s->scope.leaf_pin);
    }
    if (cloned < 0) {
        close(channel[0]);
        close(channel[1]);
        return -1;
    }
    s->receiver.fd = channel[0];
    close(channel[1]);
    return 0;
}
static int publication_check(supervisor_t *s) {
    for (int i = 0; i < 3; i++) {
        if (wq_publication_check(s->publications[i], &s->publication_pins[i], s->deadline))
            return -1;
    }
    return 0;
}
static int persist(supervisor_t *s, uint32_t operation, uint32_t sequence) {
    if (s->custody < 0)
        return 0;
    wq_message_t message;
    wq_message_init(&message, &s->binding, operation, sequence, 0);
    message.scope = s->scope.leaf_pin;
    message.target_pid = s->target_pid;
    memcpy(message.publications, s->publication_pins, sizeof(message.publications));
    if (transfer(s, s->receiver.fd, &message, NULL, 0, 1)) {
        custody_failure_fallback(s);
        return -1;
    }
    int result = receive_simple(s, s->receiver.fd, WQ_STORE_ACK, sequence);
    if (result)
        custody_failure_fallback(s);
    if (!result && s->custody_v2 && operation == WQ_STORE_REGISTER)
        s->custody_registered = 1;
    return result;
}
static void close_custody_creators(supervisor_t *s) {
    for (size_t i = 0; i < 2; i++) {
        int fd = s->custody_creators[i];
        s->custody_creators[i] = -1;
        if (fd >= 0)
            close(fd);
    }
}
static void v3_registration(supervisor_t *s, wq_message_t *message) {
    wq_message_init(message, &s->binding, WQ_V3_STORE_REGISTER, 1, 0);
    message->version = WQ_CREATOR_VERSION;
    message->scope = s->scope.leaf_pin;
    message->target_pid = s->target_pid;
    memcpy(message->publications, s->publication_pins, sizeof(message->publications));
}
static int v3_creator_role(const int creators[2], int role) {
    if (role < 0)
        return 0;
    struct stat original;
    if (fstat(role, &original))
        return role <= 2 && errno == EBADF ? 0 : -1;
    for (size_t i = 0; i < 2; i++) {
        struct stat incoming;
        if (creators[i] == role || fstat(creators[i], &incoming) ||
            (incoming.st_dev == original.st_dev && incoming.st_ino == original.st_ino &&
             (incoming.st_mode & S_IFMT) == (original.st_mode & S_IFMT)))
            return -1;
    }
    return 0;
}
static int v3_creator_roles(supervisor_t *s) {
    int roles[] = {s->profile, s->delegation, s->bootstrap, s->controller, s->enrollment,
                   s->lifecycle, s->lifeline, s->image, s->custody, s->target,
                   s->publications[0], s->publications[1], s->publications[2], s->scope.leaf,
                   s->guardian.fd, s->guardian.pidfd, s->receiver.fd, s->receiver.pidfd,
                   s->guardian_lifeline, 0, 1, 2};
    if (wq_fd_distinct(s->custody_creators, 2))
        return -1;
    for (size_t i = 0; i < sizeof(roles) / sizeof(roles[0]); i++)
        if (v3_creator_role(s->custody_creators, roles[i]))
            return -1;
    for (size_t i = 0; i < 8; i++)
        if (v3_creator_role(s->custody_creators, s->scope.files[i]))
            return -1;
    for (size_t i = 0; i < s->delegation_chain.count; i++)
        if (v3_creator_role(s->custody_creators, s->delegation_chain.fds[i]))
            return -1;
    return 0;
}
/* This consumes only actual received rights, never a public/recovered owner.
 * Adoption precedes every context/identity check and failure retires both. */
static int adopt_v3_creators(supervisor_t *s, const wq_message_t *registration,
                              const wq_message_t *ack, int incoming[2]) {
    if (s->custody_creators[0] >= 0 || s->custody_creators[1] >= 0) {
        for (size_t i = 0; i < 2; i++) {
            if (incoming[i] >= 0)
                close(incoming[i]);
            incoming[i] = -1;
        }
        return -1;
    }
    for (size_t i = 0; i < 2; i++) {
        s->custody_creators[i] = incoming[i];
        incoming[i] = -1;
    }
    wq_message_t expected = *registration;
    expected.operation = WQ_V3_REGISTER_CREATORS;
    expected.fd_count = 2;
    int invalid = memcmp(ack, &expected, sizeof(expected)) || v3_creator_roles(s);
    for (size_t i = 0; !invalid && i < 2; i++)
        invalid = wq_identity(s->custody_creators[i], &s->custody_record_pins[i], 0);
    if (!invalid)
        invalid = fstat(s->custody_creators[0], &s->custody_registration) ||
                  fstat(s->custody_creators[1], &s->custody_empty_terminal);
    if (!invalid)
        invalid = v3_creators_check(s->custody, s->custody_creators, &s->custody_parent,
                                    s->custody_record_pins, registration, NULL, s->deadline) ||
                  v3_stat_pin_check(s->custody, s->custody_creators[0], v3_record_names[0],
                                      &s->custody_registration, s->deadline) ||
                  v3_empty_terminal_check(s->custody, s->custody_creators[1],
                                            &s->custody_empty_terminal, s->deadline);
    if (invalid) {
        close_custody_creators(s);
        return -1;
    }
    s->custody_registered = 1;
    return 0;
}
static int receive_v3_creators(supervisor_t *s, const wq_message_t *registration) {
    if (s->custody_creators[0] >= 0 || s->custody_creators[1] >= 0)
        return -1;
    for (;;) {
        if (supervisor_check(s))
            return -1;
        wq_message_t ack;
        int incoming[2] = {-1, -1};
        if (!wq_receive(s->receiver.fd, &ack, incoming, 2, s->deadline)) {
            if (adopt_v3_creators(s, registration, &ack, incoming))
                return -1;
            if (supervisor_check(s)) {
                close_custody_creators(s);
                return -1;
            }
            return 0;
        }
        if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)
            return -1;
        struct pollfd p = {s->receiver.fd, POLLIN, 0};
        int ms = wq_remaining(s->deadline);
        if (ms < 0 || (poll(&p, 1, ms) < 0 && errno != EINTR))
            return -1;
    }
}
static int persist_v3_registration(supervisor_t *s) {
    if (!s->custody_v3 || s->custody_registered)
        return -1;
    wq_message_t registration;
    v3_registration(s, &registration);
    if (transfer(s, s->receiver.fd, &registration, NULL, 0, 1) ||
        receive_v3_creators(s, &registration)) {
        custody_failure_fallback(s);
        return -1;
    }
    return 0;
}
static int prepare_v3_controller_creators(supervisor_t *s, wq_message_t *message) {
    v3_registration(s, message);
    if (!s->custody_v3 || !s->custody_registered || v3_creator_roles(s) ||
        v3_creators_check(s->custody, s->custody_creators, &s->custody_parent,
                           s->custody_record_pins, message, NULL, s->deadline) ||
        v3_stat_pin_check(s->custody, s->custody_creators[0], v3_record_names[0],
                            &s->custody_registration, s->deadline) ||
        v3_empty_terminal_check(s->custody, s->custody_creators[1],
                                  &s->custody_empty_terminal, s->deadline))
        return -1;
    message->operation = WQ_V3_CONTROLLER_CREATORS;
    message->sequence = 2;
    message->fd_count = 2;
    return 0;
}
static int forward_v3_creators(supervisor_t *s) {
    wq_message_t message;
    if (prepare_v3_controller_creators(s, &message)) {
        close_custody_creators(s);
        return -1;
    }
    int result = transfer(s, s->controller, &message, s->custody_creators, 2, 1);
    if (!result)
        result = prepare_v3_controller_creators(s, &message);
    /* A successful send owns queued kernel duplicates, not C's receipt. The
     * unchanged release gate remains necessary after C's actual adoption. */
    close_custody_creators(s);
    return result;
}
static int persist_v2_terminal(supervisor_t *s, uint32_t reason, uint32_t facts) {
    if (!s->custody_v2 || !s->custody_registered || s->custody_terminal_sent ||
        s->receiver.pidfd < 0 || s->receiver.reaped || exited(s->receiver.pidfd))
        return -1;
    wq_custody_event_t event;
    memset(&event, 0, sizeof(event));
    wq_message_init(&event.original, &s->binding,
                    reason ? WQ_CUSTODY_ABNORMAL : WQ_CUSTODY_NORMAL, 2, 0);
    event.original.version = WQ_CUSTODY_VERSION;
    event.original.scope = s->scope.leaf_pin;
    event.original.target_pid = s->target_pid;
    memcpy(event.original.publications, s->publication_pins, sizeof(s->publication_pins));
    event.reason = reason;
    event.facts = facts;
    uint64_t observed;
    if (wq_remaining(s->deadline) < 0 || wq_now(&observed))
        return -1;
    event.observed_monotonic_ns = observed;
    wq_message_t registration = event.original;
    registration.version = WQ_VERSION;
    registration.operation = WQ_STORE_REGISTER;
    registration.sequence = 1;
    if (wq_custody_event_check(&event, &registration))
        return -1;
    /* Stop precedes this call on every abnormal path. Never use transfer():
     * controller death is the recorded cause, not permission to renew it. */
    for (;;) {
        if (wq_remaining(s->deadline) < 0 || exited(s->receiver.pidfd))
            return -1;
        if (!reason && supervisor_check(s))
            return -1;
        if (!wq_custody_send(s->receiver.fd, &event))
            break;
        if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)
            return -1;
        struct pollfd p = {s->receiver.fd, POLLOUT, 0};
        int ms = wq_remaining(s->deadline);
        if (ms < 0 || (poll(&p, 1, ms) < 0 && errno != EINTR))
            return -1;
    }
    s->custody_terminal_sent = 1;
    s->receiver_retiring = 1;
    wq_message_t expected = event.original;
    expected.operation = WQ_CUSTODY_ACK;
    for (;;) {
        wq_message_t ack;
        if (wq_remaining(s->deadline) < 0)
            return -1;
        if (!reason && supervisor_check(s))
            return -1;
        if (!wq_receive(s->receiver.fd, &ack, NULL, 0, s->deadline)) {
            if (memcmp(&ack, &expected, sizeof(ack)))
                return -1;
            s->receiver_retiring = 1;
            return 0;
        }
        if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)
            return -1;
        struct pollfd p = {s->receiver.fd, POLLIN, 0};
        int ms = wq_remaining(s->deadline);
        if (ms < 0 || (poll(&p, 1, ms) < 0 && errno != EINTR))
            return -1;
    }
}
static int persist_v3_terminal(supervisor_t *s, uint32_t reason, uint32_t facts) {
    if (!s->custody_v3 || !s->custody_registered || s->custody_terminal_sent ||
        s->receiver.pidfd < 0 || s->receiver.reaped || exited(s->receiver.pidfd))
        return -1;
    wq_message_t registration;
    v3_registration(s, &registration);
    wq_custody_event_t event;
    memset(&event, 0, sizeof(event));
    event.original = registration;
    event.original.operation = reason ? WQ_V3_STORE_ABNORMAL : WQ_V3_STORE_NORMAL;
    event.original.sequence = 2;
    event.reason = reason;
    event.facts = facts;
    uint64_t now;
    if (wq_remaining(s->deadline) < 0 || wq_now(&now))
        return -1;
    event.observed_monotonic_ns = now;
    if (wq_v3_event_check(&event, &registration))
        return -1;
    for (;;) {
        if (wq_remaining(s->deadline) < 0 || exited(s->receiver.pidfd) ||
            (!reason && supervisor_check(s)))
            return -1;
        if (!wq_custody_send(s->receiver.fd, &event))
            break;
        if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)
            return -1;
        struct pollfd p = {s->receiver.fd, POLLOUT, 0};
        int ms = wq_remaining(s->deadline);
        if (ms < 0 || (poll(&p, 1, ms) < 0 && errno != EINTR))
            return -1;
    }
    s->custody_terminal_sent = 1;
    s->receiver_retiring = 1;
    for (;;) {
        if (wq_remaining(s->deadline) < 0 || (!reason && supervisor_check(s)))
            return -1;
        wq_custody_event_t ack;
        if (!wq_custody_receive(s->receiver.fd, &ack, s->deadline))
            return wq_v3_terminal_ack_check(&ack, &event) ? -1 : 0;
        if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)
            return -1;
        struct pollfd p = {s->receiver.fd, POLLIN, 0};
        int ms = wq_remaining(s->deadline);
        if (ms < 0 || (poll(&p, 1, ms) < 0 && errno != EINTR))
            return -1;
    }
}
static int finish_abnormal_custody(supervisor_t *s) {
    /* Wake the original G before S's possibly failing scope observation or
     * R's filesystem work. Do not kill G before its independent stop route. */
    if (s->guardian_lifeline >= 0) {
        close(s->guardian_lifeline);
        s->guardian_lifeline = -1;
    }
    uint32_t facts = emergency_stop_observed(&s->scope, s->bootstrap, 0);
    if (s->guardian.pidfd >= 0 && !s->guardian.reaped)
        (void)child_wait(&s->guardian, s->deadline, 0);
    if (s->guardian.reaped)
        facts |= WQ_CUSTODY_GUARDIAN_REAPED;
    /* Expiry, original-R loss or a missing ACK retains unknown. No alternate
     * G/R, repaired context or fresh deadline is created by this attempt. */
    return s->custody_v3 ? persist_v3_terminal(s, s->failure_reason, facts)
                         : persist_v2_terminal(s, s->failure_reason, facts);
}
static int target_member(supervisor_t *s) {
    int fd = openat(s->scope.leaf, "cgroup.procs", O_RDONLY | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK);
    if (fd < 0)
        return -1;
    wq_identity_t pin;
    char bytes[128] = {0}, expected[128];
    int populated;
    int invalid = wq_identity(fd, &pin, 1) ||
                  checked_read(fd, &pin, bytes, sizeof(bytes) - 1, s->deadline, 1) < 0;
    int size = snprintf(expected, sizeof(expected), "%llu\n", (unsigned long long)s->target_pid);
    if (size <= 0 || strcmp(bytes, expected))
        invalid = 1;
    close(fd);
    return invalid || scope_events(&s->scope, 4, &populated) || populated != 1 ||
           exited(s->target) || supervisor_check(s);
}
static int run_supervisor(supervisor_t *s) {
    wq_message_t init;
    for (;;) {
        if (wq_remaining(s->deadline) < 0 || live(s->lifeline) || exited(s->bootstrap))
            return -1;
        if (!wq_receive(s->controller, &init, NULL, 0, s->deadline))
            break;
        if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)
            return -1;
        struct pollfd p = {s->controller, POLLIN, 0};
        int ms = wq_remaining(s->deadline);
        if (ms < 0 || (poll(&p, 1, ms) < 0 && errno != EINTR))
            return -1;
    }
    s->binding = init.binding;
    char digest[65];
    uint64_t now;
    if (wq_message_check(&init, &s->binding, WQ_INIT, 0, 0) ||
        s->binding.deadline_ns != s->deadline || wq_now(&now) ||
        s->deadline <= WQ_CLEANUP_RESERVE_NS || now >= s->deadline - WQ_CLEANUP_RESERVE_NS ||
        zero(&init.scope, sizeof(init.scope)) || init.target_pid ||
        zero(init.publications, sizeof(init.publications)) ||
        wq_load_profile(s->profile, s->binding.profile_sha256, &s->installed, s->deadline) ||
        wq_profile_binding(&s->installed, &s->binding) || wq_sealed(s->image) ||
        wq_hash_fd(s->image, digest, s->deadline) ||
        memcmp(digest, s->binding.supervisor_sha256, 65) ||
        wq_chain_open(s->installed.delegation_path, &s->delegation_chain, 1) ||
        !wq_identity_equal(&s->delegation_chain.pins[s->delegation_chain.count - 1],
                           &s->installed.delegation) ||
        syscall(SYS_pidfd_send_signal, s->bootstrap, 0, NULL, 0) ||
        scope_create(&s->scope, s->delegation, &s->installed.delegation, &s->binding) ||
        start_guardian(s) || start_receiver(s))
        return -1;
    s->execution_cutoff = s->deadline - WQ_CLEANUP_RESERVE_NS;
    wq_message_t enrollment;
    wq_message_init(&enrollment, &s->binding, WQ_SCOPE, 1, 1);
    enrollment.scope = s->scope.leaf_pin;
    int leaf = s->scope.leaf;
    if (transfer(s, s->enrollment, &enrollment, &leaf, 1, 1))
        return -1;
    int target = -1;
    if (transfer(s, s->enrollment, &enrollment, &target, 1, 0))
        return -1;
    s->target = target;
    if (wq_message_check(&enrollment, &s->binding, WQ_ENROLLED, 1, 1) || !enrollment.target_pid ||
        enrollment.target_pid > INT_MAX ||
        !wq_identity_equal(&enrollment.scope, &s->scope.leaf_pin) ||
        zero(enrollment.publications, sizeof(enrollment.publications)) ||
        syscall(SYS_pidfd_send_signal, target, 0, NULL, 0))
        return -1;
    s->target_pid = enrollment.target_pid;
    int target_roles[] = {s->target,     s->bootstrap,  s->profile,    s->image,     s->delegation,
                          s->scope.leaf, s->controller, s->enrollment, s->lifecycle, s->lifeline};
    if (wq_fd_distinct(target_roles, sizeof(target_roles) / sizeof(target_roles[0])))
        return -1;
    if (target_member(s) || send_simple(s, s->enrollment, WQ_ENROLL_ACK, 2))
        return -1;
    close(s->enrollment);
    s->enrollment = -1;
    if (send_simple(s, s->controller, WQ_ENROLL_ACK, 1))
        return -1;
    wq_message_t registration;
    int publications[3] = {-1, -1, -1};
    if (transfer(s, s->controller, &registration, publications, 3, 0))
        return -1;
    for (int i = 0; i < 3; i++)
        s->publications[i] = publications[i];
    if (wq_message_check(&registration, &s->binding, WQ_REGISTER, 1, 3) ||
        message_payload(&registration, &s->scope, s->target_pid, 1) ||
        wq_fd_distinct(publications, 3))
        return -1;
    int publication_roles[] = {publications[0], publications[1], publications[2], s->target,
                               s->bootstrap,    s->profile,      s->image,        s->delegation,
                               s->scope.leaf,   s->controller,   s->lifecycle,    s->lifeline};
    if (wq_fd_distinct(publication_roles, sizeof(publication_roles) / sizeof(publication_roles[0])))
        return -1;
    memcpy(s->publication_pins, registration.publications, sizeof(s->publication_pins));
    if (publication_check(s) ||
        (s->custody_v3 ? persist_v3_registration(s) : persist(s, WQ_STORE_REGISTER, 1)) ||
        (s->custody_v3 ? forward_v3_creators(s)
                       : send_simple(s, s->controller, WQ_REGISTER_ACK, 2)) ||
        receive_simple(s, s->controller, WQ_RELEASE, 3) || publication_check(s) ||
        target_member(s) || receive_simple(s, s->lifecycle, WQ_RELEASE, 3) ||
        publication_check(s) || target_member(s) ||
        send_simple(s, s->lifecycle, WQ_RELEASE_PERMIT, 3) ||
        receive_simple(s, s->lifecycle, WQ_TARGET_DONE, 4))
        return -1;
    for (;;) {
        int populated;
        if (supervisor_check(s) || publication_check(s) || scope_events(&s->scope, 4, &populated))
            return -1;
        if (!populated) {
            /* Leader completion alone never releases the finite cleanup
             * reserve while any original-scope descendant is still alive. */
            s->cleanup_started = 1;
            break;
        }
        struct pollfd p = {s->scope.files[4], POLLPRI | POLLERR, 0};
        int ms = wq_remaining(s->deadline);
        if (ms < 0 || (poll(&p, 1, ms) < 0 && errno != EINTR))
            return -1;
    }
    if (exited(s->target) != 1 || publication_check(s) ||
        send_simple(s, s->guardian.fd, WQ_GUARD_RETIRE, 1) ||
        child_wait(&s->guardian, s->deadline, 1))
        return -1;
    close(s->guardian.pidfd);
    s->guardian.pidfd = -1;
    if (s->custody_v3 ? persist_v3_terminal(s, WQ_CUSTODY_OK, WQ_CUSTODY_NORMAL_FACTS)
         : s->custody_v2 ? persist_v2_terminal(s, WQ_CUSTODY_OK, WQ_CUSTODY_NORMAL_FACTS)
                         : persist(s, WQ_STORE_EVENT, 2)) {
        custody_failure_fallback(s);
        return -1;
    }
    if (s->receiver.pidfd >= 0) {
        if (child_wait(&s->receiver, s->deadline, 1))
            return -1;
        close(s->receiver.pidfd);
        s->receiver.pidfd = -1;
    }
    int populated;
    if (scope_check(&s->scope, 0) || scope_events(&s->scope, 4, &populated) || populated ||
        publication_check(s) || send_simple(s, s->lifecycle, WQ_COMPLETE, 4) ||
        send_simple(s, s->controller, WQ_COMPLETE, 4))
        return -1;
    return 0;
}
/* POSIX access ACL v2: only root owner, fixed numeric U, empty owning group,
 * the exact U mask, and no other permission. No default ACL is permitted. */
typedef struct __attribute__((packed)) {
    uint16_t tag, permissions;
    uint32_t id;
} acl_entry_t;
typedef struct __attribute__((packed)) {
    uint32_t version;
    acl_entry_t entries[5];
} acl_t;
static int acl_grant(int fd, uint32_t uid, unsigned int owner, unsigned int candidate, int create) {
    acl_t wanted = {2,
                    {{1, (uint16_t)owner, UINT_MAX},
                     {2, (uint16_t)candidate, uid},
                     {4, 0, UINT_MAX},
                     {16, (uint16_t)candidate, UINT_MAX},
                     {32, 0, UINT_MAX}}};
    unsigned char raw[sizeof(wanted) + 1];
    ssize_t current = fgetxattr(fd, "system.posix_acl_access", raw, sizeof(raw));
    if (create) {
        if (current >= 0 || errno != ENODATA)
            return -1;
        if (fsetxattr(fd, "system.posix_acl_access", &wanted, sizeof(wanted), XATTR_CREATE))
            return -1;
    } else if (current != (ssize_t)sizeof(wanted) || memcmp(raw, &wanted, sizeof(wanted)))
        return -1;
    current = fgetxattr(fd, "system.posix_acl_access", raw, sizeof(raw));
    if (current != (ssize_t)sizeof(wanted) || memcmp(raw, &wanted, sizeof(wanted)))
        return -1;
    current = fgetxattr(fd, "system.posix_acl_default", raw, sizeof(raw));
    return current < 0 && errno == ENODATA ? 0 : -1;
}
static int readonly_tree(int fd, const wq_profile_t *profile, uint64_t deadline, size_t *count,
                         unsigned int depth) {
    struct stat info;
    if (wq_remaining(deadline) < 0 || depth > 32 || ++*count > WQ_MAX_FILES || fstat(fd, &info) ||
        info.st_uid || info.st_gid || info.st_mode & 0222 ||
        (!S_ISDIR(info.st_mode) && (!S_ISREG(info.st_mode) || info.st_nlink != 1)))
        return -1;
    unsigned int permission = S_ISDIR(info.st_mode) || info.st_mode & 0111 ? 5 : 4;
    /* Installed readonly roots already carry the exact ACL. This attempt does
     * not mutate shared roots or change a frozen input's ctime. */
    if (acl_grant(fd, profile->candidate_uid, permission, permission, 0))
        return -1;
    if (!S_ISDIR(info.st_mode))
        return 0;
    int copied = fcntl(fd, F_DUPFD_CLOEXEC, 3);
    if (copied < 0)
        return -1;
    DIR *directory = fdopendir(copied);
    if (!directory) {
        close(copied);
        return -1;
    }
    struct dirent *entry;
    int invalid = 0;
    errno = 0;
    while ((entry = readdir(directory))) {
        if (!strcmp(entry->d_name, ".") || !strcmp(entry->d_name, ".."))
            continue;
        struct stat named;
        if (fstatat(fd, entry->d_name, &named, AT_SYMLINK_NOFOLLOW) ||
            (!S_ISDIR(named.st_mode) && !S_ISREG(named.st_mode))) {
            invalid = 1;
            break;
        }
        int flags = O_RDONLY | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK;
        if (S_ISDIR(named.st_mode))
            flags |= O_DIRECTORY;
        int child = openat(fd, entry->d_name, flags);
        if (child < 0) {
            invalid = 1;
            break;
        }
        struct stat actual;
        if (fstat(child, &actual) || actual.st_dev != named.st_dev ||
            actual.st_ino != named.st_ino ||
            readonly_tree(child, profile, deadline, count, depth + 1))
            invalid = 1;
        close(child);
        if (invalid)
            break;
        errno = 0;
    }
    if (errno)
        invalid = 1;
    closedir(directory);
    struct stat after;
    if (fstat(fd, &after) || info.st_dev != after.st_dev || info.st_ino != after.st_ino ||
        info.st_mode != after.st_mode || info.st_uid != after.st_uid ||
        info.st_gid != after.st_gid || memcmp(&info.st_ctim, &after.st_ctim, sizeof(info.st_ctim)))
        invalid = 1;
    return invalid ? -1 : 0;
}
static int publisher(int profile_fd, int execution, int controller, int image, uint64_t deadline) {
    wq_message_t request;
    for (;;) {
        if (wq_remaining(deadline) < 0)
            return -1;
        if (!wq_receive(controller, &request, NULL, 0, deadline))
            break;
        if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)
            return -1;
        struct pollfd p = {controller, POLLIN, 0};
        int ms = wq_remaining(deadline);
        if (ms < 0 || (poll(&p, 1, ms) < 0 && errno != EINTR))
            return -1;
    }
    wq_profile_t profile;
    char hash[65];
    wq_identity_t root;
    if (wq_message_check(&request, &request.binding, WQ_PUBLISH, 0, 0) ||
        memcmp(request.binding.launch_sha256, request.binding.intent_sha256, 65) ||
        request.binding.deadline_ns != deadline || zero(&request.scope, sizeof(request.scope)) ||
        request.target_pid || zero(request.publications, sizeof(request.publications)) ||
        wq_load_profile(profile_fd, request.binding.profile_sha256, &profile, deadline) ||
        wq_profile_binding(&profile, &request.binding) || wq_sealed(image) ||
        wq_hash_fd(image, hash, deadline) || memcmp(hash, profile.supervisor_sha256, 65) ||
        wq_identity(execution, &root, 0) || !wq_identity_equal(&root, &profile.execution_root))
        return -1;
    size_t files = 0;
    for (size_t i = 0; i < profile.readonly_count; i++) {
        wq_chain_t chain;
        if (wq_chain_open(profile.readonly_paths[i], &chain, 1))
            return -1;
        int invalid = readonly_tree(chain.fds[chain.count - 1], &profile, deadline, &files, 0) ||
                      wq_chain_check(&chain);
        wq_chain_close(&chain);
        if (invalid)
            return -1;
    }
    char name[72];
    if (snprintf(name, sizeof(name), "lunar-%s", request.binding.launch_sha256) != 70 ||
        wq_remaining(deadline) < 0 || mkdirat(execution, name, 0700))
        return -1;
    int attempt = openat(execution, name, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (attempt < 0)
        return -1;
    int children[2] = {-1, -1};
    const char *names[2] = {"work", "output"};
    int result = -1;
    wq_identity_t created_attempt, created_children[2];
    if (wq_identity(attempt, &created_attempt, 0) || created_attempt.uid || created_attempt.gid ||
        (created_attempt.mode & 07777) != 0700 ||
        acl_grant(attempt, profile.candidate_uid, 7, 1, 1))
        goto done;
    for (int i = 0; i < 2; i++) {
        if (wq_remaining(deadline) < 0 || mkdirat(attempt, names[i], 0700))
            goto done;
        children[i] = openat(attempt, names[i], O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
        if (children[i] < 0 || wq_identity(children[i], &created_children[i], 0) ||
            fchown(children[i], profile.candidate_uid, profile.candidate_gid) ||
            fchmod(children[i], 0700))
            goto done;
        struct stat info;
        unsigned char acl[128];
        ssize_t size = fgetxattr(children[i], "system.posix_acl_access", acl, sizeof(acl));
        if (fstat(children[i], &info) || info.st_uid != profile.candidate_uid ||
            info.st_gid != profile.candidate_gid || (info.st_mode & 07777) != 0700 || size >= 0 ||
            errno != ENODATA)
            goto done;
        size = fgetxattr(children[i], "system.posix_acl_default", acl, sizeof(acl));
        if (size >= 0 || errno != ENODATA)
            goto done;
    }
    wq_message_t response;
    wq_message_init(&response, &request.binding, WQ_PUBLISHED, 1, 3);
    if (wq_identity(attempt, &response.scope, 0) || response.scope.uid || response.scope.gid ||
        (response.scope.mode & 07777) != 0710 || response.scope.device != created_attempt.device ||
        response.scope.inode != created_attempt.inode ||
        response.scope.mount_id != created_attempt.mount_id ||
        acl_grant(attempt, profile.candidate_uid, 7, 1, 0))
        goto done;
    wq_identity_t current;
    if (wq_identity(execution, &current, 0) || !wq_identity_equal(&current, &root))
        goto done;
    struct stat named;
    if (fstatat(execution, name, &named, AT_SYMLINK_NOFOLLOW) ||
        (uint64_t)named.st_dev != created_attempt.device || named.st_ino != created_attempt.inode)
        goto done;
    for (int i = 0; i < 2; i++) {
        if (wq_identity(children[i], &current, 0) || current.device != created_children[i].device ||
            current.inode != created_children[i].inode ||
            current.mount_id != created_children[i].mount_id ||
            current.uid != profile.candidate_uid || current.gid != profile.candidate_gid ||
            (current.mode & 07777) != 0700 ||
            fstatat(attempt, names[i], &named, AT_SYMLINK_NOFOLLOW) ||
            (uint64_t)named.st_dev != current.device || named.st_ino != current.inode)
            goto done;
    }
    int rights[3] = {attempt, children[0], children[1]};
    for (;;) {
        if (wq_remaining(deadline) < 0)
            goto done;
        if (!wq_send(controller, &response, rights, 3)) {
            result = 0;
            break;
        }
        if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)
            goto done;
        struct pollfd p = {controller, POLLOUT, 0};
        int ms = wq_remaining(deadline);
        if (ms < 0 || (poll(&p, 1, ms) < 0 && errno != EINTR))
            goto done;
    }
done:
    for (int i = 0; i < 2; i++)
        if (children[i] >= 0)
            close(children[i]);
    close(attempt);
    return result;
}
#include "native_whole_scope_successor.h"

int main(int argc, char **argv) {
    if (wq_root_identity() || signals_ready())
        return 64;
    if (argc > 1 && !strcmp(argv[1], "--successor-coordinator-v4"))
        return w4_coordinator_main(argc, argv);
    if (argc == 12 && (!strcmp(argv[1], "--publish-v1") ||
                       !strcmp(argv[1], "--publish-successor-v4"))) {
        const char *flags[5] = {"--profile-fd", "--execution-root-fd", "--controller-fd",
                                "--image-fd", "--deadline-monotonic-ns"};
        int fds[4];
        uint64_t deadline;
        for (int i = 0; i < 5; i++)
            if (strcmp(argv[2 + 2 * i], flags[i]))
                return 64;
        for (int i = 0; i < 4; i++)
            if (fd_arg(argv[3 + 2 * i], &fds[i], 0))
                return 64;
        if (number(argv[11], UINT64_MAX, &deadline) || wq_fd_distinct(fds, 4) || wq_socket(fds[2]))
            return 64;
        int result = !strcmp(argv[1], "--publish-successor-v4")
            ? w4_publisher(fds[0], fds[1], fds[2], fds[3], deadline)
            : publisher(fds[0], fds[1], fds[2], fds[3], deadline);
        return result ? WQ_FAILURE : 0;
    }
    if (argc != 22 || (strcmp(argv[1], "--supervisor-v1") &&
                       strcmp(argv[1], "--supervisor-custody-v2") &&
                       strcmp(argv[1], "--supervisor-custody-v3")))
        return 64;
    const char *flags[10] = {
        "--profile-fd",     "--delegation-fd",        "--bootstrap-pidfd",        "--controller-fd",
        "--enrollment-fd",  "--lifecycle-fd",         "--controller-lifeline-fd", "--image-fd",
        "--custody-dir-fd", "--deadline-monotonic-ns"};
    supervisor_t s;
    memset(&s, 0, sizeof(s));
    s.custody_v2 = !strcmp(argv[1], "--supervisor-custody-v2");
    s.custody_v3 = !strcmp(argv[1], "--supervisor-custody-v3");
    s.custody_creators[0] = s.custody_creators[1] = -1;
    int *roles[9] = {&s.profile,   &s.delegation, &s.bootstrap, &s.controller, &s.enrollment,
                     &s.lifecycle, &s.lifeline,   &s.image,     &s.custody};
    s.target = -1;
    s.scope.leaf = -1;
    for (int i = 0; i < 8; i++)
        s.scope.files[i] = -1;
    s.guardian.pidfd = -1;
    s.receiver.pidfd = -1;
    s.guardian_lifeline = -1;
    for (int i = 0; i < 3; i++)
        s.publications[i] = -1;
    for (int i = 0; i < 10; i++)
        if (strcmp(argv[2 + 2 * i], flags[i]))
            return 64;
    for (int i = 0; i < 9; i++)
        if (fd_arg(argv[3 + 2 * i], roles[i], i == 8))
            return 64;
    int required[9];
    size_t count = 0;
    for (int i = 0; i < 9; i++)
        if (*roles[i] >= 0)
            required[count++] = *roles[i];
    if (number(argv[21], UINT64_MAX, &s.deadline) || wq_fd_distinct(required, count) ||
        wq_socket(s.controller) || wq_socket(s.enrollment) || wq_socket(s.lifecycle) ||
        pipe_reader(s.lifeline) || ((s.custody_v2 || s.custody_v3) && s.custody < 0))
        return 64;
    int result = run_supervisor(&s);
    if (result) {
        if ((s.custody_v2 || s.custody_v3) && !s.failure_reason)
            s.failure_reason = wq_remaining(s.deadline) < 0
                                   ? WQ_CUSTODY_DEADLINE : WQ_CUSTODY_PROTOCOL;
        if (s.custody_v2 || s.custody_v3)
            (void)finish_abnormal_custody(&s);
        else
            emergency_stop(&s.scope, s.bootstrap, 0);
        child_t *children[2] = {&s.guardian, &s.receiver};
        for (int i = 0; i < 2; i++)
            if (children[i]->pidfd >= 0 && !children[i]->reaped) {
                int ignored =
                    (int)syscall(SYS_pidfd_send_signal, children[i]->pidfd, SIGKILL, NULL, 0);
                (void)ignored;
                child_wait(children[i], s.deadline, 0);
            }
    }
    if (s.custody_v3)
        close_custody_creators(&s);
    return result ? WQ_FAILURE : 0;
}
