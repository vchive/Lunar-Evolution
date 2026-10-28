/* New single-threaded B path. The legacy bootstrap/control ABI stays separate. */
#ifndef LUNAR_NATIVE_WHOLE_SCOPE_BOOTSTRAP_H
#define LUNAR_NATIVE_WHOLE_SCOPE_BOOTSTRAP_H
#include "native_whole_scope_platform.h"
#include <linux/sched.h>
#include <linux/securebits.h>

typedef struct {
    int control, gate, frame, lifeline, enrollment, lifecycle, profile;
    uint64_t deadline;
} wq_bootstrap_fds_t;

static int wq_b_checkpoint(const wq_bootstrap_fds_t *fds) {
    struct pollfd owner = {fds->lifeline, POLLIN, 0};
    if (wq_remaining(fds->deadline) < 0) return -1;
    int result = poll(&owner, 1, 0);
    return result == 0 && wq_remaining(fds->deadline) >= 0 ? 0 : -1;
}

static int wq_b_poll(const wq_bootstrap_fds_t *fds, int fd, short events) {
    for (;;) {
        int timeout = wq_remaining(fds->deadline);
        if (timeout < 0 || wq_b_checkpoint(fds)) return -1;
        struct pollfd observed[2] = {{fds->lifeline, POLLIN, 0}, {fd, events, 0}};
        int result = poll(observed, 2, timeout);
        if (result < 0 && errno == EINTR) continue;
        if (result < 0 || observed[0].revents || wq_b_checkpoint(fds) ||
            (observed[1].revents & (POLLERR | POLLNVAL))) return -1;
        if (observed[1].revents & events) return 0;
        /* EOF is interpreted by the next exact read/recv. It is never a
         * positive lifecycle fact, but a pipe's final EOF is required input. */
        if (observed[1].revents & POLLHUP) return 0;
    }
}

static int wq_b_receive(const wq_bootstrap_fds_t *fds, int fd, wq_message_t *message,
                        int *rights, size_t count) {
    for (;;) {
        if (wq_b_checkpoint(fds)) return -1;
        if (!wq_receive(fd, message, rights, count, fds->deadline)) return wq_b_checkpoint(fds);
        if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR) return -1;
        if (wq_b_poll(fds, fd, POLLIN)) return -1;
    }
}

static int wq_b_send(const wq_bootstrap_fds_t *fds, int fd, const wq_message_t *message,
                     const int *rights, size_t count) {
    for (;;) {
        if (wq_b_checkpoint(fds)) return -1;
        if (!wq_send(fd, message, rights, count)) return wq_b_checkpoint(fds);
        if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR) return -1;
        if (wq_b_poll(fds, fd, POLLOUT)) return -1;
    }
}

static int wq_b_read(const wq_bootstrap_fds_t *fds, int fd, void *data, size_t size,
                      size_t *received, int require_eof) {
    size_t used = 0;
    for (;;) {
        if (wq_b_checkpoint(fds)) return -1;
        ssize_t result = read(fd, (unsigned char *)data + used, size - used);
        if (result > 0) {
            used += (size_t)result;
            if (used == size) { *received = used; return require_eof ? -1 : 0; }
        } else if (!result) {
            *received = used;
            return require_eof ? 0 : -1;
        } else {
            if (errno != EINTR && errno != EAGAIN && errno != EWOULDBLOCK) return -1;
            if (wq_b_poll(fds, fd, POLLIN)) return -1;
        }
    }
}

/* Drop the entire root credential/capability set before pre-exec readiness.
 * There is no setuid image, external publisher command or capability-only A.
 * A caller cannot select these values: they came from the fixed installed
 * profile independently revalidated by both native owners. */
static int wq_b_drop_credentials(const wq_profile_t *profile) {
    if (wq_root_identity()) return -1;
    gid_t groups[WQ_MAX_GROUPS];
    for (size_t i = 0; i < profile->group_count; ++i) groups[i] = (gid_t)profile->groups[i];
    if (prctl(PR_CAP_AMBIENT, PR_CAP_AMBIENT_CLEAR_ALL, 0, 0, 0) ||
        prctl(PR_SET_KEEPCAPS, 0, 0, 0, 0)) return -1;
    int last = -1;
    for (int capability = 0; capability < 64; ++capability) {
        int value = prctl(PR_CAPBSET_READ, capability, 0, 0, 0);
        if (value < 0) {
            if (errno != EINVAL || capability == 0) return -1;
            last = capability - 1;
            break;
        }
        if (value && prctl(PR_CAPBSET_DROP, capability, 0, 0, 0)) return -1;
    }
    if (last < 0) return -1; /* An unknown capability range needs profile review. */
    unsigned int bits = SECBIT_NOROOT | SECBIT_NOROOT_LOCKED |
        SECBIT_NO_SETUID_FIXUP | SECBIT_NO_SETUID_FIXUP_LOCKED |
        SECBIT_NO_CAP_AMBIENT_RAISE | SECBIT_NO_CAP_AMBIENT_RAISE_LOCKED;
    if (prctl(PR_SET_SECUREBITS, bits, 0, 0, 0) ||
        setgroups(profile->group_count, groups) ||
        setresgid(profile->candidate_gid, profile->candidate_gid, profile->candidate_gid) ||
        setresuid(profile->candidate_uid, profile->candidate_uid, profile->candidate_uid)) return -1;
    struct __user_cap_header_struct header = {_LINUX_CAPABILITY_VERSION_3, 0};
    struct __user_cap_data_struct empty[2] = {{0}, {0}}, actual[2];
    if (syscall(SYS_capset, &header, empty) || prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) ||
        syscall(SYS_capget, &header, actual) || memcmp(actual, empty, sizeof(empty)) ||
        prctl(PR_GET_NO_NEW_PRIVS, 0, 0, 0, 0) != 1 ||
        prctl(PR_GET_SECUREBITS, 0, 0, 0, 0) != (int)bits) return -1;
    uid_t real, effective, saved;
    gid_t greal, geffective, gsaved, observed[WQ_MAX_GROUPS];
    if (getresuid(&real, &effective, &saved) || getresgid(&greal, &geffective, &gsaved) ||
        real != profile->candidate_uid || effective != real || saved != real ||
        greal != profile->candidate_gid || geffective != greal || gsaved != greal ||
        getgroups(WQ_MAX_GROUPS, observed) != (int)profile->group_count ||
        memcmp(groups, observed, profile->group_count * sizeof(gid_t))) return -1;
    for (int capability = 0; capability <= last; ++capability)
        if (prctl(PR_CAPBSET_READ, capability, 0, 0, 0) != 0 ||
            prctl(PR_CAP_AMBIENT, PR_CAP_AMBIENT_IS_SET, capability, 0, 0) != 0) return -1;
    errno = 0;
    if (!setresuid(0, 0, 0) || errno != EPERM) return -1;
    errno = 0;
    if (!setresgid(0, 0, 0) || errno != EPERM) return -1;
    return 0;
}

/* Only the whole-scope entrypoint admits this exact distinct-account input
 * layout. The ordinary bootstrap and its 0400/0500 inputs remain unchanged.
 * The original controller binds schema/security facts into the manifest SHA;
 * B independently checks the exact marker, finite grant set and real objects. */
static int wq_b_input_kind(const control_t *control) {
    int kind = 0;
    for (size_t i = 0; i < control->argc; ++i) {
        int candidate = !strcmp(control->argv[i], "--lunar-producer-input-v1") ? 1 :
                        !strcmp(control->argv[i], "--lunar-rsi-input-v1") ? 2 : 0;
        if (!candidate) continue;
        if (kind || i + 2 != control->argc || !hex64(control->argv[i + 1])) return -1;
        kind = candidate;
    }
    return kind;
}

typedef struct __attribute__((packed)) {
    uint16_t tag, permissions;
    uint32_t id;
} wq_b_acl_entry_t;
typedef struct __attribute__((packed)) {
    uint32_t version;
    wq_b_acl_entry_t entries[5];
} wq_b_acl_t;

static int wq_b_input_acl(int fd, uint32_t uid, uint16_t permission) {
    wq_b_acl_t wanted = {2, {{1, permission, UINT_MAX}, {2, permission, uid},
        {4, 0, UINT_MAX}, {16, permission, UINT_MAX}, {32, 0, UINT_MAX}}};
    unsigned char raw[sizeof(wanted) + 1];
    ssize_t size = fgetxattr(fd, "system.posix_acl_access", raw, sizeof(raw));
    if (!uid || size != (ssize_t)sizeof(wanted) || memcmp(raw, &wanted, sizeof(wanted))) return -1;
    size = fgetxattr(fd, "system.posix_acl_default", raw, sizeof(raw));
    return size < 0 && errno == ENODATA ? 0 : -1;
}

static int wq_b_input_grant(const control_t *control, const grant_t *grant,
                           const wq_profile_t *profile, uint64_t deadline) {
    const grant_node_t *leaf = &control->nodes[grant->node];
    wq_chain_t chain;
    if (grant->role != 1 || wq_remaining(deadline) < 0 || wq_chain_open(leaf->path, &chain, 0)) return -1;
    int result = -1;
    if (chain.count < 4) goto done;
    size_t file_index = chain.count - 1, dir_index = chain.count - 2;
    wq_identity_t held;
    struct stat file, directory;
    /* wq_chain_open uses readable no-follow descriptors, including when the
     * inherited original grant is O_PATH (which cannot supply fgetxattr).
     * Every opened identity must match the original graph, never a new pin. */
    uint32_t node = grant->node;
    for (size_t i = chain.count; i > 0; --i) {
        const wq_identity_t *pin = &chain.pins[i - 1];
        if (node >= control->node_count || pin->device != control->nodes[node].device ||
            pin->inode != control->nodes[node].inode ||
            (i == 1 ? node != 0 : node == 0)) goto done;
        if (i > 1) node = control->nodes[node].parent;
    }
    if (!wq_identity_equal(&chain.pins[chain.count - 4], &profile->execution_root) ||
        wq_identity(grant->fd, &held, 0) || !wq_identity_equal(&held, &chain.pins[file_index]) ||
        held.mount_id != profile->execution_root.mount_id ||
        chain.pins[dir_index].mount_id != held.mount_id ||
        fstat(chain.fds[file_index], &file) || fstat(chain.fds[dir_index], &directory) ||
        !S_ISREG(file.st_mode) || !S_ISDIR(directory.st_mode) || file.st_uid || file.st_gid ||
        directory.st_uid || directory.st_gid || file.st_nlink != 1 ||
        (file.st_mode & 07777) != 0440 || (directory.st_mode & 07777) != 0550 ||
        wq_b_input_acl(chain.fds[file_index], profile->candidate_uid, 4) ||
        wq_b_input_acl(chain.fds[dir_index], profile->candidate_uid, 5) ||
        wq_chain_check(&chain) || wq_remaining(deadline) < 0) goto done;
    result = 0;
done:
    wq_chain_close(&chain);
    return result;
}

static int wq_b_profile_grants(const control_t *control, const wq_profile_t *profile,
                             uint64_t deadline) {
    size_t root_length = strlen(profile->execution_path);
    const char *working = control->cwd;
    if (strncmp(working, profile->execution_path, root_length) ||
        strncmp(working + root_length, "/lunar-", 7)) return -1;
    const char *nonce = working + root_length + 7;
    if (strlen(nonce) != 64 + 5 || strcmp(nonce + 64, "/work")) return -1;
    for (size_t i = 0; i < 64; ++i)
        if (!((nonce[i] >= '0' && nonce[i] <= '9') || (nonce[i] >= 'a' && nonce[i] <= 'f'))) return -1;
    char output[MAX_PATH_BYTES + 1];
    size_t prefix = strlen(working) - 4;
    if (prefix + 6 > MAX_PATH_BYTES) return -1;
    memcpy(output, working, prefix); memcpy(output + prefix, "output", 7);
    int input_kind = wq_b_input_kind(control);
    if (input_kind < 0) return -1;
    unsigned int writes = 0, input_bits = 0;
    for (size_t i = 0; i < control->grant_count; ++i) {
        const grant_t *grant = &control->grants[i];
        const char *path = control->nodes[grant->node].path;
        struct stat info;
        if (fstat(grant->fd, &info)) return -1;
        if (grant->role & 4) {
            ++writes;
            if ((strcmp(path, working) && strcmp(path, output)) ||
                info.st_uid != profile->candidate_uid || info.st_gid != profile->candidate_gid ||
                (info.st_mode & 07777) != 0700) return -1;
        } else {
            int allowed = 0;
            for (size_t root = 0; root < profile->readonly_count; ++root)
                if (path_under(path, profile->readonly_paths[root])) allowed = 1;
            if (allowed) {
                if (info.st_uid || (info.st_mode & 0022)) return -1;
            } else {
                const char *suffixes[3] = {".producer-input/config.json", ".rsi-input/request.json",
                                            ".rsi-input/memory.json"};
                int selected = -1;
                for (size_t item = 0; item < 3; ++item)
                    if (!strncmp(path, working, prefix) && !strcmp(path + prefix, suffixes[item]))
                        selected = (int)item;
                if (selected < 0 || (input_bits & (1u << selected)) ||
                    (input_kind == 1 ? selected != 0 : input_kind != 2 || selected == 0) ||
                    wq_b_input_grant(control, grant, profile, deadline)) return -1;
                input_bits |= 1u << selected;
            }
        }
    }
    unsigned int expected_inputs = input_kind == 1 ? 1u : input_kind == 2 ? 6u : 0u;
    return writes == 2 && input_bits == expected_inputs && wq_remaining(deadline) >= 0 ? 0 : -1;
}

static int wq_b_keep(int *keep, size_t count) {
    if (!count || count > MAX_GRANTS + 10) return -1;
    for (size_t i = 0; i < count; ++i) {
        if (keep[i] <= 2) return -1;
        for (size_t j = 0; j < i; ++j) if (keep[j] == keep[i]) return -1;
        for (size_t j = i; j && keep[j] < keep[j - 1]; --j) {
            int swap = keep[j]; keep[j] = keep[j - 1]; keep[j - 1] = swap;
        }
    }
    unsigned int first = 3;
    for (size_t i = 0; i < count; ++i) {
        unsigned int next = (unsigned int)keep[i];
        if (first < next && syscall(SYS_close_range, first, next - 1, 0)) return -1;
        first = next + 1;
    }
    return syscall(SYS_close_range, first, UINT_MAX, 0) ? -1 : 0;
}

static _Noreturn void wq_b_child(const wq_bootstrap_fds_t *fds, control_t *control,
                                const wq_profile_t *profile, int target_fd,
                                int error_fd, int ready_fd, int release_fd,
                                int scope_fd, int broker_r, int broker_w) {
    if (close(scope_fd) || wq_b_checkpoint(fds) ||
        dup2(target_fd, control->target_fd) < 0 || handoff_cloexec(control->target_fd, 0))
        child_start_failed(error_fd, ECANCELED, 78);
    int keep[MAX_GRANTS + 10]; size_t count = 0;
    keep[count++] = control->target_fd; keep[count++] = error_fd;
    keep[count++] = ready_fd; keep[count++] = release_fd; keep[count++] = fds->lifeline;
    if (broker_r >= 0) { keep[count++] = broker_r; keep[count++] = broker_w; }
    if (control->version >= 3) keep[count++] = control->sink_fd;
    if (control->version == 4) keep[count++] = control->completion_fd;
    for (size_t i = 0; i < control->grant_count; ++i) keep[count++] = control->grants[i].fd;
    if (wq_b_keep(keep, count) || wq_b_drop_credentials(profile)) child_start_failed(error_fd, EPERM, 78);
    /* Prove real U access on original grant objects, rather than an A-only
     * preflight. faccessat2 is required by this explicit Linux >=5.14 profile. */
    for (size_t i = 0; i < control->grant_count; ++i) {
        int mode = control->grants[i].role == 1 ? R_OK : R_OK | X_OK;
        if (control->grants[i].role & 4) mode |= W_OK;
        if (syscall(SYS_faccessat2, control->grants[i].fd, "", mode, AT_EMPTY_PATH | AT_EACCESS))
            child_start_failed(error_fd, EACCES, 78);
    }
    if (syscall(SYS_faccessat2, control->target_fd, "", X_OK, AT_EMPTY_PATH | AT_EACCESS) ||
        fchdir(control->grants[control->cwd_grant].fd)) child_start_failed(error_fd, EACCES, 78);
    lunar_grant_fd_t original[MAX_GRANTS];
    for (size_t i = 0; i < control->grant_count; ++i) {
        original[i].fd = control->grants[i].fd; original[i].role = control->grants[i].role;
    }
    if (lunar_apply_grant_isolation(original, control->grant_count)) child_start_failed(error_fd, EPERM, 78);
    close_original_grants(control);
    count = 0;
    keep[count++] = control->target_fd; keep[count++] = error_fd;
    keep[count++] = ready_fd; keep[count++] = release_fd; keep[count++] = fds->lifeline;
    if (broker_r >= 0) { keep[count++] = broker_r; keep[count++] = broker_w; }
    if (control->version >= 3) keep[count++] = control->sink_fd;
    if (control->version == 4) keep[count++] = control->completion_fd;
    if (wq_b_keep(keep, count) || wq_b_checkpoint(fds)) child_start_failed(error_fd, ECANCELED, 78);
    unsigned char ready = 'R';
    if (write(ready_fd, &ready, 1) != 1 || close(ready_fd)) child_start_failed(error_fd, EPIPE, 78);
    unsigned char release[2]; size_t received = 0;
    if (wq_b_read(fds, release_fd, release, sizeof(release), &received, 1) ||
        received != 1 || release[0] != '1' || wq_b_checkpoint(fds) ||
        close(release_fd) || close(fds->lifeline)) child_start_failed(error_fd, ECANCELED, 78);
    char broker_read[80], broker_write[80], sink_deadline[80], completion_deadline[80];
    char *environment[8] = {"PATH=/usr/bin:/bin", "LANG=C", "LUNAR_BOOTSTRAP_RELEASED=1", NULL};
    size_t env_count = 3;
    if (broker_r >= 0) {
        if (handoff_cloexec(broker_r, 0) || handoff_cloexec(broker_w, 0)) child_start_failed(error_fd, EINVAL, 78);
        snprintf(broker_read, sizeof(broker_read), "LUNAR_PRODUCER_RESPONSE_FD=%d", broker_r);
        snprintf(broker_write, sizeof(broker_write), "LUNAR_PRODUCER_REQUEST_FD=%d", broker_w);
        environment[env_count++] = broker_read; environment[env_count++] = broker_write;
    }
    if (control->version >= 3) {
        if (dup2(control->sink_fd, FIXED_LIVE_SINK_FD) < 0 ||
            handoff_cloexec(FIXED_LIVE_SINK_FD, 0)) child_start_failed(error_fd, EINVAL, 78);
        if (control->sink_fd != FIXED_LIVE_SINK_FD) close(control->sink_fd);
        snprintf(sink_deadline, sizeof(sink_deadline), "LUNAR_FIXED_LIVE_DEADLINE_NS=%llu",
                 (unsigned long long)control->sink_deadline_ns);
        environment[env_count++] = sink_deadline;
    }
    if (control->version == 4) {
        if (dup2(control->completion_fd, FIXED_COMPLETION_SINK_FD) < 0 ||
            handoff_cloexec(FIXED_COMPLETION_SINK_FD, 0)) child_start_failed(error_fd, EINVAL, 78);
        if (control->completion_fd != FIXED_COMPLETION_SINK_FD) close(control->completion_fd);
        snprintf(completion_deadline, sizeof(completion_deadline), "LUNAR_FIXED_COMPLETION_DEADLINE_NS=%llu",
                 (unsigned long long)control->completion_deadline_ns);
        environment[env_count++] = completion_deadline;
    }
    environment[env_count] = NULL;
    if (wq_remaining(fds->deadline) < 0) child_start_failed(error_fd, ECANCELED, 78);
    fexecve(control->target_fd, control->argv, environment);
    child_start_failed(error_fd, errno, 78);
}

static int wq_bootstrap_main(int argc, char **argv) {
    if (argc != 18) return 64;
    const char *names[8] = {"--control-fd", "--gate-fd", "--frame-fd", "--controller-lifeline-fd",
        "--scope-enrollment-fd", "--scope-lifecycle-fd", "--profile-fd", "--deadline-monotonic-ns"};
    wq_bootstrap_fds_t fds;
    memset(&fds, 0, sizeof(fds));
    int *fields[7] = {&fds.control, &fds.gate, &fds.frame, &fds.lifeline,
        &fds.enrollment, &fds.lifecycle, &fds.profile};
    for (size_t i = 0; i < 8; ++i) {
        if (strcmp(argv[2 + i * 2], names[i])) return 64;
        if (i < 7 ? parse_handoff_fd(argv[3 + i * 2], fields[i]) :
            parse_deadline_arg(argv[3 + i * 2], &fds.deadline)) return 64;
    }
    int private_fds[7] = {fds.control, fds.gate, fds.frame, fds.lifeline,
        fds.enrollment, fds.lifecycle, fds.profile};
    if (wq_root_identity() || wq_fd_distinct(private_fds, 7) ||
        grant_protocol_pipe(fds.control, O_RDONLY) || grant_protocol_pipe(fds.gate, O_RDONLY) ||
        grant_protocol_pipe(fds.frame, O_WRONLY) || grant_protocol_pipe(fds.lifeline, O_RDONLY) ||
        wq_socket(fds.enrollment) || wq_socket(fds.lifecycle) ||
        getpgrp() != getpid() || getsid(0) != getpid()) return 64;
    struct sigaction disposition;
    if (sigaction(SIGCHLD, NULL, &disposition) || disposition.sa_handler == SIG_IGN ||
        (disposition.sa_flags & SA_NOCLDWAIT)) return 64;
    for (size_t i = 0; i < 4; ++i) {
        int flags = fcntl(private_fds[i], F_GETFL);
        if (flags < 0 || fcntl(private_fds[i], F_SETFL, flags | O_NONBLOCK)) return 64;
    }
    unsigned char raw[MAX_CONTROL + 1]; size_t received = 0;
    control_t control; memset(&control, 0, sizeof(control));
    if (wq_b_read(&fds, fds.control, raw, sizeof(raw), &received, 1) ||
        parse_control(raw, received, &control) || control.version < 2) return 66;
    close(fds.control);
    wq_message_t message;
    int scope_fd = -1;
    if (wq_b_receive(&fds, fds.enrollment, &message, &scope_fd, 1)) return 78;
    wq_binding_t binding; memcpy(&binding, &message.binding, sizeof(binding));
    wq_identity_t scope; memcpy(&scope, &message.scope, sizeof(scope));
    wq_profile_t profile;
    wq_publication_t zero_publications[3] = {{0}};
    if (wq_message_check(&message, &binding, WQ_SCOPE, 1, 1) ||
        binding.deadline_ns != fds.deadline || message.target_pid ||
        memcmp(message.publications, zero_publications, sizeof(zero_publications)) ||
        memcmp(binding.launch_sha256, control.launch, 65) || memcmp(binding.intent_sha256, control.intent, 65) ||
        memcmp(binding.target_sha256, control.target_sha, 65) ||
        wq_load_profile(fds.profile, binding.profile_sha256, &profile, fds.deadline) ||
        wq_profile_binding(&profile, &binding) || wq_b_profile_grants(&control, &profile, fds.deadline)) return 78;
    wq_identity_t observed_scope;
    char image_digest[65], target_digest[65];
    struct stat self, original_bootstrap, original_target;
    controller_guard_t guard; memset(&guard, 0, sizeof(guard));
    guard.fd = fds.lifeline; guard.deadline_ns = fds.deadline;
    int reserved[9] = {fds.gate, fds.frame, fds.lifeline, fds.enrollment, fds.lifecycle,
        fds.profile, scope_fd, control.target_fd, control.bootstrap_fd};
    if (wq_fd_distinct(reserved, 9) || wq_identity(scope_fd, &observed_scope, 1) ||
        !wq_identity_equal(&scope, &observed_scope) || !S_ISDIR(scope.mode) ||
        sealed_exec_fd(control.bootstrap_fd) == 0 || sealed_exec_fd(control.target_fd) == 0 ||
        fstat(control.target_fd, &original_target) || original_target.st_uid || original_target.st_gid ||
        (original_target.st_mode & 07777) != 0755 ||
        stat("/proc/self/exe", &self) || fstat(control.bootstrap_fd, &original_bootstrap) ||
        self.st_dev != original_bootstrap.st_dev || self.st_ino != original_bootstrap.st_ino ||
        wq_hash_fd(control.bootstrap_fd, image_digest, fds.deadline) ||
        memcmp(image_digest, binding.bootstrap_sha256, 65) ||
        wq_hash_fd(control.target_fd, target_digest, fds.deadline) ||
        memcmp(target_digest, binding.target_sha256, 65) ||
        grant_fds_disjoint(&control, reserved, 9) || validate_grant_graph(&control, &guard) ||
        validate_private_sink(&control, fds.deadline, reserved, 9)) return 78;
    int broker_r = -1, broker_w = -1;
    if (handoff_broker(getenv("LUNAR_PRODUCER_RESPONSE_FD"), getenv("LUNAR_PRODUCER_REQUEST_FD"),
        reserved, 9, &broker_r, &broker_w)) return 78;
    int error_pipe[2], ready_pipe[2], release_pipe[2];
    if (pipe2(error_pipe, O_CLOEXEC | O_NONBLOCK) || pipe2(ready_pipe, O_CLOEXEC | O_NONBLOCK) ||
        pipe2(release_pipe, O_CLOEXEC | O_NONBLOCK)) return 78;
    int target_fd = fcntl(control.target_fd, F_DUPFD_CLOEXEC, 3), target_pidfd = -1;
    if (target_fd < 0 || wq_b_checkpoint(&fds)) return 78;
    int dynamic[] = {fds.frame, fds.lifeline, fds.enrollment, fds.lifecycle, fds.profile, scope_fd,
        target_fd, control.target_fd, control.bootstrap_fd, error_pipe[0], error_pipe[1],
        ready_pipe[0], ready_pipe[1], release_pipe[0], release_pipe[1], broker_r, broker_w};
    if (grant_fds_disjoint(&control, dynamic, sizeof(dynamic) / sizeof(dynamic[0])) ||
        validate_private_sink(&control, fds.deadline, dynamic, sizeof(dynamic) / sizeof(dynamic[0]))) return 78;
    struct clone_args arguments;
    memset(&arguments, 0, sizeof(arguments));
    arguments.flags = CLONE_INTO_CGROUP | CLONE_PIDFD;
    arguments.pidfd = (uint64_t)(uintptr_t)&target_pidfd;
    arguments.cgroup = (uint64_t)scope_fd; arguments.exit_signal = SIGCHLD;
    /* This entrypoint has never created the legacy controller pthread. */
    pid_t target = (pid_t)syscall(SYS_clone3, &arguments, sizeof(arguments));
    if (target < 0) return 78; /* Never fork/migrate as a fallback. */
    if (!target) wq_b_child(&fds, &control, &profile, target_fd, error_pipe[1],
                            ready_pipe[1], release_pipe[0], scope_fd, broker_r, broker_w);
    close(error_pipe[1]); close(ready_pipe[1]); close(release_pipe[0]); close(target_fd);
    unsigned char ready[2];
    if (wq_b_read(&fds, ready_pipe[0], ready, sizeof(ready), &received, 1) ||
        received != 1 || ready[0] != 'R' || close(ready_pipe[0]) || close(scope_fd)) return 78;
    scope_fd = -1; /* One-shot enrollment authority is irrevocably closed. */
    wq_message_init(&message, &binding, WQ_ENROLLED, 1, 1);
    memcpy(&message.scope, &scope, sizeof(scope)); message.target_pid = (uint64_t)target;
    if (wq_b_send(&fds, fds.enrollment, &message, &target_pidfd, 1) ||
        wq_b_receive(&fds, fds.enrollment, &message, NULL, 0) ||
        wq_message_check(&message, &binding, WQ_ENROLL_ACK, 2, 0) ||
        !wq_identity_equal(&message.scope, &scope) || message.target_pid != (uint64_t)target ||
        memcmp(message.publications, zero_publications, sizeof(zero_publications)) ||
        close(fds.enrollment) ||
        emit_frame(fds.frame, control.launch, control.intent, 1, "bootstrap_ready", NULL, 0, 0)) return 78;
    unsigned char gate[2];
    if (wq_b_read(&fds, fds.gate, gate, sizeof(gate), &received, 1) || received != 1 || gate[0] != '1' ||
        close(fds.gate) || validate_grant_graph(&control, &guard) ||
        wq_b_profile_grants(&control, &profile, fds.deadline) || wq_b_checkpoint(&fds)) return 78;
    wq_message_init(&message, &binding, WQ_RELEASE, 3, 0);
    memcpy(&message.scope, &scope, sizeof(scope)); message.target_pid = (uint64_t)target;
    if (wq_b_send(&fds, fds.lifecycle, &message, NULL, 0) ||
        wq_b_receive(&fds, fds.lifecycle, &message, NULL, 0) ||
        wq_message_check(&message, &binding, WQ_RELEASE_PERMIT, 3, 0) ||
        !wq_identity_equal(&message.scope, &scope) || message.target_pid != (uint64_t)target ||
        wq_b_checkpoint(&fds)) return 78;
    wq_publication_t original_publications[3];
    memcpy(original_publications, message.publications, sizeof(original_publications));
    for (size_t i = 0; i < 3; ++i)
        if (!original_publications[i].inode || !original_publications[i].size ||
            original_publications[i].size > MAX_CONTROL || wq_digest(original_publications[i].sha256)) return 78;
    if (wq_b_profile_grants(&control, &profile, fds.deadline) || wq_b_checkpoint(&fds)) return 78;
    unsigned char release = '1';
    if (write(release_pipe[1], &release, 1) != 1 || close(release_pipe[1])) return 78;
    int exec_error = 0;
    if (wq_b_read(&fds, error_pipe[0], &exec_error, sizeof(exec_error), &received, 1) || received ||
        close(error_pipe[0]) || emit_frame(fds.frame, control.launch, control.intent, 2, "target_started",
                                         target_digest, target, getpgrp())) return 78;
    siginfo_t child_status;
    for (;;) {
        if (wq_b_checkpoint(&fds)) return 78;
        memset(&child_status, 0, sizeof(child_status));
        if (waitid(P_PIDFD, (id_t)target_pidfd, &child_status, WEXITED | WNOHANG)) {
            if (errno == EINTR) continue;
            return 78;
        }
        if (child_status.si_pid) break;
        if (wq_b_poll(&fds, target_pidfd, POLLIN)) return 78;
    }
    if (child_status.si_pid != target || wq_b_checkpoint(&fds)) return 78;
    close(target_pidfd);
    wq_message_init(&message, &binding, WQ_TARGET_DONE, 4, 0);
    memcpy(&message.scope, &scope, sizeof(scope)); message.target_pid = (uint64_t)target;
    memcpy(message.publications, original_publications, sizeof(original_publications));
    if (wq_b_send(&fds, fds.lifecycle, &message, NULL, 0) ||
        wq_b_receive(&fds, fds.lifecycle, &message, NULL, 0) ||
        wq_message_check(&message, &binding, WQ_COMPLETE, 4, 0) ||
        !wq_identity_equal(&message.scope, &scope) || message.target_pid != (uint64_t)target ||
        memcmp(message.publications, original_publications, sizeof(original_publications)) ||
        wq_b_checkpoint(&fds) ||
        emit_frame(fds.frame, control.launch, control.intent, 3, "terminal", NULL, 0, 0)) return 78;
    free_control(&control);
    if (child_status.si_code == CLD_EXITED) return child_status.si_status;
    if (child_status.si_code == CLD_KILLED || child_status.si_code == CLD_DUMPED) return 128 + child_status.si_status;
    return 78;
}
#endif
