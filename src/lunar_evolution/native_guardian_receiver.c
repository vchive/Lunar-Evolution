/* One original guardian's independent, native, create-only custody receiver.
 * This process is not a cleanup authority. The original guardian alone owns
 * the original group pidfd. Neither an exit status nor D proves group cleanup.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#if !defined(__linux__)
#error "the independent custody receiver requires Linux"
#endif

#define REGISTRATION "guardian-registration-v1.json"
#define EVENT "guardian-event-v1.json"
#define PROTOCOL "lunar-native-guardian-custody-v1"

typedef struct {
    int bootstrap, group, lifeline, finish, ack, directory, registration, event;
    uint64_t deadline;
    const char *context, *launch, *profile, *guardian, *receiver;
    struct stat directory_pin, registration_pin, event_pin;
} receiver_t;

static int parse_number(const char *text, uint64_t maximum, uint64_t *result) {
    uint64_t value = 0;
    if (!text || !*text || (*text == '0' && text[1])) return -1;
    for (const unsigned char *p = (const unsigned char *)text; *p; ++p) {
        if (*p < '0' || *p > '9' || value > (maximum - (*p - '0')) / 10) return -1;
        value = value * 10 + (*p - '0');
    }
    *result = value; return 0;
}

static int parse_fd(const char *text, int *result) {
    uint64_t value;
    if (parse_number(text, INT_MAX, &value) || value <= 2) return -1;
    *result = (int)value; return 0;
}

static int digest(const char *text) {
    if (!text || strlen(text) != 64) return -1;
    for (size_t i = 0; i < 64; ++i)
        if (!((text[i] >= '0' && text[i] <= '9') || (text[i] >= 'a' && text[i] <= 'f'))) return -1;
    return 0;
}

static int remaining(const receiver_t *r) {
    struct timespec now;
    if (!r->deadline || clock_gettime(CLOCK_MONOTONIC, &now) || now.tv_sec < 0) return -1;
    uint64_t value = (uint64_t)now.tv_sec * 1000000000ULL + (uint64_t)now.tv_nsec;
    if (value >= r->deadline) return -1;
    uint64_t left = r->deadline - value;
    return left >= 10000000 ? 10 : (int)((left + 999999) / 1000000);
}

static int same_inode(const struct stat *a, const struct stat *b) {
    return a->st_dev == b->st_dev && a->st_ino == b->st_ino;
}

static int private_directory(const receiver_t *r) {
    struct stat now;
    return fstat(r->directory, &now) || !S_ISDIR(now.st_mode) ||
        now.st_uid != geteuid() || (now.st_mode & 07777) != 0700 ||
        !same_inode(&now, &r->directory_pin) || now.st_gid != r->directory_pin.st_gid;
}

static int bound_file(const receiver_t *r, int fd, const char *name, const struct stat *pin, size_t size) {
    struct stat current, named;
    return fstat(fd, &current) || fstatat(r->directory, name, &named, AT_SYMLINK_NOFOLLOW) ||
        !S_ISREG(current.st_mode) || (current.st_mode & 07777) != 0600 ||
        current.st_uid != geteuid() || current.st_nlink != 1 || current.st_size != (off_t)size ||
        !same_inode(&current, pin) || !same_inode(&current, &named) || private_directory(r);
}

/* No path/argv discovery, /proc scan, or inherited secret-bearing descriptor.
 * Linux close_range is older than the group-pidfd capability this path needs.
 */
static int close_except(const int *keep, size_t count) {
    int sorted[12];
    if (count > 12) return -1;
    for (size_t i = 0; i < count; ++i) {
        if (keep[i] <= 2) return -1;
        sorted[i] = keep[i];
        for (size_t j = i; j && sorted[j] < sorted[j - 1]; --j) {
            int temp = sorted[j]; sorted[j] = sorted[j - 1]; sorted[j - 1] = temp;
        }
    }
    unsigned int first = 0;
    for (size_t i = 0; i < count; ++i) {
        unsigned int fd = (unsigned int)sorted[i];
        if (i && sorted[i - 1] == sorted[i]) return -1;
        if (first < fd && syscall(SYS_close_range, first, fd - 1, 0)) return -1;
        first = fd + 1;
    }
    return syscall(SYS_close_range, first, UINT_MAX, 0) ? -1 : 0;
}

static int pipe_role(int fd, int access, struct stat *info) {
    int flags = fcntl(fd, F_GETFL);
    return flags < 0 || (flags & O_ACCMODE) != access || (flags & O_ASYNC) ||
        fstat(fd, info) || !S_ISFIFO(info->st_mode);
}

static int high_fd(int fd) {
    if (fd < 0 || fd > 2) return fd;
    int result = fcntl(fd, F_DUPFD_CLOEXEC, 3);
    if (close(fd)) { if (result >= 0) close(result); return -1; }
    return result;
}

static int sealed_executable(int fd) {
    struct stat info;
    int required = F_SEAL_WRITE | F_SEAL_GROW | F_SEAL_SHRINK | F_SEAL_SEAL;
    int seals = fcntl(fd, F_GET_SEALS);
    unsigned char header[4];
    return fstat(fd, &info) || !S_ISREG(info.st_mode) || info.st_nlink != 0 ||
        !(info.st_mode & 0111) || (info.st_mode & 06000) || info.st_size < 4 ||
        seals < 0 || (seals & required) != required || pread(fd, header, 4, 0) != 4 ||
        memcmp(header, "\177ELF", 4);
}

static int write_ack(const receiver_t *r, unsigned char value) {
    for (;;) {
        if (remaining(r) < 0) return -1;
        ssize_t count = write(r->ack, &value, 1);
        if (count == 1) return remaining(r) < 0 ? -1 : 0;
        if (count < 0 && errno == EINTR) continue;
        if (count < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
            struct pollfd observed = {r->ack, POLLOUT, 0};
            int timeout = remaining(r), result;
            if (timeout < 0) return -1;
            result = poll(&observed, 1, timeout);
            if (result < 0 && errno == EINTR) continue;
            if (result < 0 || observed.revents & (POLLERR | POLLHUP | POLLNVAL)) return -1;
            continue;
        }
        return -1;
    }
}

static int persist(const receiver_t *r, int event, int native_d, int status) {
    int fd = event ? r->event : r->registration;
    const char *name = event ? EVENT : REGISTRATION;
    const struct stat *pin = event ? &r->event_pin : &r->registration_pin;
    char bytes[2048];
    int kind = event ? (WIFEXITED(status) ? 1 : WIFSIGNALED(status) ? 2 : 0) : 0;
    int value = event ? (kind == 1 ? WEXITSTATUS(status) : kind == 2 ? WTERMSIG(status) : -1) : 0;
    if (event && !kind) return -1;
    int size = snprintf(bytes, sizeof(bytes),
        "{\"protocol\":\"%s\",\"kind\":\"%s\",\"context_sha256\":\"%s\","
        "\"launch_sha256\":\"%s\",\"profile_sha256\":\"%s\",\"guardian_sha256\":\"%s\","
        "\"receiver_sha256\":\"%s\",\"deadline_monotonic_ns\":%llu,"
        "\"directory_device\":%llu,\"directory_inode\":%llu,"
        "\"record_device\":%llu,\"record_inode\":%llu,\"native_ready_observed\":true,"
        "\"native_d_observed\":%s,\"watcher_exit_kind\":%d,\"watcher_exit_value\":%d,"
        "\"signal_result_known\":false,\"cleanup_status\":\"unknown\","
        "\"native_success\":false,\"publication_authority\":false,\"cleanup_authority\":false,"
        "\"production_admission\":false,\"isolation_accepted\":false,"
        "\"immutable_custody_verified\":false,\"whole_group_cleanup_verified\":false}\n",
        PROTOCOL, event ? "watcher-exit" : "custody-registration", r->context, r->launch,
        r->profile, r->guardian, r->receiver, (unsigned long long)r->deadline,
        (unsigned long long)r->directory_pin.st_dev, (unsigned long long)r->directory_pin.st_ino,
        (unsigned long long)pin->st_dev, (unsigned long long)pin->st_ino,
        native_d ? "true" : "false", kind, value);
    if (size <= 0 || (size_t)size >= sizeof(bytes) || remaining(r) < 0 ||
        bound_file(r, fd, name, pin, 0)) return -1;
    size_t offset = 0;
    while (offset < (size_t)size) {
        if (remaining(r) < 0) return -1;
        ssize_t wrote = write(fd, bytes + offset, (size_t)size - offset);
        if (wrote < 0 && errno == EINTR) continue;
        if (wrote <= 0) return -1;
        offset += (size_t)wrote;
        if (remaining(r) < 0) return -1;
    }
    /* fsync has no portable hard completion bound. No ACK is issued if it
     * returns after expiry; the independent original guardian keeps its own
     * emergency deadline. No renewed grace interval or repair is attempted.
     */
    if (remaining(r) < 0 || fsync(fd) || remaining(r) < 0 ||
        bound_file(r, fd, name, pin, (size_t)size) || remaining(r) < 0 ||
        fsync(r->directory) || remaining(r) < 0 ||
        bound_file(r, fd, name, pin, (size_t)size)) return -1;
    return 0;
}

int main(int argc, char **argv) {
    receiver_t r; memset(&r, 0, sizeof(r));
    const char *names[] = {"--bootstrap-fd", "--group-pidfd", "--controller-lifeline-fd",
        "--guardian-finish-fd", "--guardian-ack-fd", "--custody-dir-fd", "--context-sha256",
        "--launch-sha256", "--profile-sha256", "--guardian-sha256", "--receiver-sha256",
        "--deadline-monotonic-ns"};
    if (argc != 25) return 64;
    for (size_t i = 0; i < 12; ++i) if (strcmp(argv[1 + 2 * i], names[i])) return 64;
    if (parse_fd(argv[2], &r.bootstrap) || parse_fd(argv[4], &r.group) ||
        parse_fd(argv[6], &r.lifeline) || parse_fd(argv[8], &r.finish) ||
        parse_fd(argv[10], &r.ack) || parse_fd(argv[12], &r.directory) ||
        parse_number(argv[24], UINT64_MAX, &r.deadline) || !r.deadline) return 64;
    r.context = argv[14]; r.launch = argv[16]; r.profile = argv[18];
    r.guardian = argv[20]; r.receiver = argv[22];
    if (digest(r.context) || digest(r.launch) || digest(r.profile) || digest(r.guardian) ||
        digest(r.receiver) || remaining(&r) < 0 || sealed_executable(r.bootstrap)) return 64;
    int inherited[] = {r.bootstrap, r.group, r.lifeline, r.finish, r.ack, r.directory};
    for (size_t i = 0; i < 6; ++i) for (size_t j = 0; j < i; ++j)
        if (inherited[i] == inherited[j]) return 64;
    struct stat pipes[3];
    if (pipe_role(r.lifeline, O_RDONLY, &pipes[0]) || pipe_role(r.finish, O_RDONLY, &pipes[1]) ||
        pipe_role(r.ack, O_WRONLY, &pipes[2]) || fstat(r.directory, &r.directory_pin) ||
        private_directory(&r)) return 64;
    for (size_t i = 0; i < 3; ++i) for (size_t j = 0; j < i; ++j)
        if (same_inode(&pipes[i], &pipes[j])) return 64;
    struct sigaction ignored; memset(&ignored, 0, sizeof(ignored)); ignored.sa_handler = SIG_IGN;
    if (sigemptyset(&ignored.sa_mask) || sigaction(SIGPIPE, &ignored, NULL)) return 64;
    int flags = fcntl(r.ack, F_GETFL);
    if (flags < 0 || fcntl(r.ack, F_SETFL, flags | O_NONBLOCK) || close_except(inherited, 6)) return 64;
    if (remaining(&r) < 0) return 78;
    r.registration = high_fd(openat(r.directory, REGISTRATION, O_RDWR | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600));
    if (r.registration < 0 || fstat(r.registration, &r.registration_pin) || remaining(&r) < 0) return 79;
    r.event = high_fd(openat(r.directory, EVENT, O_RDWR | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600));
    if (r.event < 0 || fstat(r.event, &r.event_pin) || remaining(&r) < 0) return 79;
    int native_ack[2];
    if (pipe2(native_ack, O_CLOEXEC | O_NONBLOCK) || remaining(&r) < 0) return 79;
    for (size_t i = 0; i < 2; ++i) {
        native_ack[i] = high_fd(native_ack[i]);
        if (native_ack[i] < 0) return 79;
    }
    pid_t child = fork();
    if (child < 0) return 79;
    if (!child) {
        int keep[] = {r.bootstrap, r.group, r.lifeline, r.finish, native_ack[1]};
        if (setsid() < 0 || close_except(keep, 5)) _exit(64);
        for (size_t i = 0; i < 5; ++i) if (fcntl(keep[i], F_SETFD, 0)) _exit(64);
        char group[24], life[24], finish[24], ack[24], deadline[32];
        snprintf(group, sizeof(group), "%d", r.group); snprintf(life, sizeof(life), "%d", r.lifeline);
        snprintf(finish, sizeof(finish), "%d", r.finish); snprintf(ack, sizeof(ack), "%d", native_ack[1]);
        snprintf(deadline, sizeof(deadline), "%llu", (unsigned long long)r.deadline);
        char *command[] = {"lunar-original-native-guardian", "--group-pidfd", group,
            "--controller-lifeline-fd", life, "--guardian-finish-fd", finish,
            "--guardian-ack-fd", ack, "--deadline-monotonic-ns", deadline, NULL};
        char *environment[] = {"PATH=/usr/bin:/bin", "LANG=C", NULL};
        fexecve(r.bootstrap, command, environment); _exit(64);
    }
    /* Only the exact original child remains supervised here. This receiver
     * drops its group pidfd and never signals a group or reconstructs an ID.
     */
    int keep[] = {r.ack, r.directory, r.registration, r.event, native_ack[0]};
    if (close_except(keep, 5)) return 79;
    int ready = 0, done = 0, eof = 0, invalid = 0, status = 0;
    for (;;) {
        if (remaining(&r) < 0) return 78;
        if (!eof) {
            unsigned char bytes[2]; ssize_t count = read(native_ack[0], bytes, sizeof(bytes));
            if (count > 0) {
                if (count != 1 || (!ready && bytes[0] != 'R') || (ready && (done || bytes[0] != 'D'))) invalid = 1;
                else if (!ready) {
                    ready = 1;
                    if (persist(&r, 0, 0, 0) || write_ack(&r, 'R')) return 79;
                } else done = 1;
            } else if (!count) eof = 1;
            else if (errno != EINTR && errno != EAGAIN && errno != EWOULDBLOCK) invalid = 1;
        }
        pid_t observed = waitpid(child, &status, WNOHANG);
        if (observed == child) {
            /* Drain only already queued original bytes, without a fresh wait. */
            if (!eof && !invalid) {
                unsigned char bytes[2]; ssize_t count = read(native_ack[0], bytes, sizeof(bytes));
                if (count == 1 && ready && !done && bytes[0] == 'D') done = 1;
                else if (count > 0 || (count < 0 && errno != EAGAIN && errno != EWOULDBLOCK)) invalid = 1;
                if (count == 0) eof = 1;
                if (count == 1 && read(native_ack[0], bytes, sizeof(bytes)) == 0) eof = 1;
            }
            if (!ready || persist(&r, 1, done && !invalid, status)) return 79;
            if (!invalid && done && eof && WIFEXITED(status) && WEXITSTATUS(status) == 0) {
                if (write_ack(&r, 'D')) return 79;
                return 0;
            }
            return 78;
        }
        if (observed < 0 || invalid) return 79;
        int timeout = remaining(&r);
        if (timeout < 0) return 78;
        struct pollfd observed_pipe = {native_ack[0], POLLIN, 0};
        int result = poll(eof ? NULL : &observed_pipe, eof ? 0 : 1, timeout);
        if ((result < 0 && errno != EINTR) || (!eof && (observed_pipe.revents & (POLLERR | POLLNVAL)))) return 79;
    }
}
