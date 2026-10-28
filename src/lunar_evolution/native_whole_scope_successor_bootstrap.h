/* Explicit default-off B v4 branch. Old bootstrap behavior is unchanged.
 * Q owns S/G/R; B owns T and consumes no peer wait. The last gate check is
 * observation, not an atomic liveness guarantee concurrent with a peer death. */
#ifndef LUNAR_NATIVE_WHOLE_SCOPE_SUCCESSOR_BOOTSTRAP_H
#define LUNAR_NATIVE_WHOLE_SCOPE_SUCCESSOR_BOOTSTRAP_H
#include "native_whole_scope_successor_protocol.h"
#include "native_whole_scope_successor_resources.h"

typedef struct {
    int control, gate, frame, lifeline, enrollment, lifecycle, profile;
    uint64_t deadline;
    int q_lifeline, peers[3], peers_required;
} w4_bootstrap_fds_t;

static int w4_b_controller(const w4_bootstrap_fds_t *f) {
    struct pollfd p = {f->lifeline, POLLIN, 0};
    return wq_remaining(f->deadline) < 0 || poll(&p, 1, 0) != 0 ? -1 : 0;
}
static int w4_b_checkpoint(const w4_bootstrap_fds_t *f) {
    if (w4_b_controller(f)) return -1;
    if (f->q_lifeline >= 0) {
        struct pollfd p = {f->q_lifeline, POLLIN, 0};
        if (poll(&p, 1, 0) != 0) return -1;
    }
    if (f->peers_required) for (size_t i = 0; i < 3; ++i) {
        struct pollfd p = {f->peers[i], POLLIN, 0};
        if (f->peers[i] <= 2 || syscall(SYS_pidfd_send_signal, f->peers[i], 0, NULL, 0) ||
            poll(&p, 1, 0) != 0) return -1;
    }
    return w4_b_controller(f);
}
static int w4_b_before_gate(const w4_bootstrap_fds_t *f) {
    uint64_t now;
    return !f->peers_required || f->q_lifeline <= 2 || f->deadline <= W4_RESERVE_NS ||
        wq_now(&now) || now >= f->deadline - W4_RESERVE_NS || w4_b_checkpoint(f) ? -1 : 0;
}
static int w4_b_poll(const w4_bootstrap_fds_t *f, int fd, short events) {
    for (;;) {
        if (w4_b_checkpoint(f)) return -1;
        struct pollfd p = {fd, events, 0};
        int timeout = wq_remaining(f->deadline);
        if (timeout < 0) return -1;
        int got = poll(&p, 1, timeout);
        if (got < 0 && errno == EINTR) continue;
        if (got < 0 || p.revents & (POLLERR | POLLNVAL) || w4_b_checkpoint(f)) return -1;
        if (p.revents & (events | POLLHUP)) return 0;
    }
}
static int w4_b_receive(const w4_bootstrap_fds_t *f, int fd, wq_message_t *m,
                         int *rights, size_t count) {
    for (;;) {
        if (w4_b_checkpoint(f)) return -1;
        if (!w4_receive(fd, m, sizeof(*m), rights, count, f->deadline)) {
            /* Callers own all delivered rights even if a later liveness check
             * refuses; main then exits, closing its actual descriptors. */
            return w4_b_checkpoint(f);
        }
        if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR) return -1;
        if (w4_b_poll(f, fd, POLLIN)) return -1;
    }
}
static int w4_b_send(const w4_bootstrap_fds_t *f, int fd, const wq_message_t *m,
                      const int *rights, size_t count) {
    for (;;) {
        if (w4_b_checkpoint(f)) return -1;
        if (!w4_send(fd, m, sizeof(*m), rights, count)) return w4_b_checkpoint(f);
        if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR) return -1;
        if (w4_b_poll(f, fd, POLLOUT)) return -1;
    }
}
static int w4_b_read(const w4_bootstrap_fds_t *f, int fd, void *data, size_t size,
                      size_t *received, int require_eof) {
    size_t used = 0;
    for (;;) {
        if (w4_b_checkpoint(f)) return -1;
        ssize_t got = read(fd, (unsigned char *)data + used, size - used);
        if (got > 0) {
            used += (size_t)got;
            if (used == size) { *received = used; return require_eof ? -1 : 0; }
        } else if (!got) {
            *received = used;
            return require_eof ? w4_b_checkpoint(f) : -1;
        } else {
            if (errno != EINTR && errno != EAGAIN && errno != EWOULDBLOCK) return -1;
            if (w4_b_poll(f, fd, POLLIN)) return -1;
        }
    }
}
static int w4_b_publications(const wq_message_t *m) {
    for (size_t i = 0; i < 3; ++i)
        if (!m->publications[i].inode || !m->publications[i].size ||
            m->publications[i].size > MAX_CONTROL || wq_digest(m->publications[i].sha256)) return -1;
    return 0;
}
static int w4_b_final_result(const w4_bootstrap_fds_t *f, const wq_message_t *registration,
                             w4_result_t *result) {
    int q_lost = 0;
    for (;;) {
        if (w4_b_controller(f)) return -1;
        if (!w4_receive(f->lifecycle, result, sizeof(*result), NULL, 0, f->deadline)) break;
        if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR) return -1;
        if (q_lost) return -1;
        struct pollfd observed[3] = {{f->lifecycle, POLLIN, 0},
            {f->lifeline, POLLIN, 0}, {f->q_lifeline, POLLIN, 0}};
        int timeout = wq_remaining(f->deadline);
        if (timeout < 0) return -1;
        int got = poll(observed, 3, timeout);
        if (got < 0 && errno == EINTR) continue;
        if (got < 0 || observed[1].revents ||
            observed[0].revents & (POLLERR | POLLNVAL)) return -1;
        /* Drain once more before interpreting Q EOF: its result may have been
         * queued concurrently with the last EAGAIN. No result means unknown. */
        if (observed[2].revents) q_lost = 1;
    }
    return w4_check(&result->context, &registration->binding, W4_RESULT, 4, 0) ||
        !w4_context_equal(&result->context, registration) ||
        w4_commit_check(&result->commit, registration) || result->commit.decision != 1 ||
        result->facts != 7 || result->r_code != CLD_EXITED || result->r_status || result->reserved ||
        !result->observed_ns || result->observed_ns < result->commit.committed_ns ||
        result->observed_ns >= f->deadline || w4_b_controller(f) ? -1 : 0;
}

static int w4_b_done(w4_bootstrap_fds_t *f, const wq_message_t *message) {
    for (;;) {
        if (w4_b_checkpoint(f)) return -1;
        if (!w4_send(f->lifecycle, message, sizeof(*message), NULL, 0)) {
            /* Once Q consumes DONE it may legitimately retire all peers and
             * itself. Do not apply a stale peer-liveness postcondition. */
            f->peers_required = 0;
            return w4_b_controller(f);
        }
        if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR) return -1;
        if (w4_b_poll(f, f->lifecycle, POLLOUT)) return -1;
    }
}

static int w4_b_close_unlisted(const w4_bootstrap_fds_t *f, const control_t *control,
                                const int *dynamic, size_t dynamic_count) {
    int keep[W4_FD_LIMIT];
    size_t count = 0;
    for (size_t i = 0; i < dynamic_count; ++i) {
        if (dynamic[i] < 0) continue;
        if (dynamic[i] <= 2 || count == W4_FD_LIMIT) return -1;
        keep[count++] = dynamic[i];
    }
    for (size_t i = 0; i < control->grant_count; ++i) {
        if (count == W4_FD_LIMIT) return -1;
        keep[count++] = control->grants[i].fd;
    }
    if (control->version >= 3) {
        if (count == W4_FD_LIMIT) return -1;
        keep[count++] = control->sink_fd;
    }
    if (control->version == 4) {
        if (count == W4_FD_LIMIT) return -1;
        keep[count++] = control->completion_fd;
    }
    if (count + 3 > W4_FD_LIMIT) return -1;
    for (size_t i = 0; i < count; ++i) {
        if (keep[i] <= 2) return -1;
        for (size_t j = 0; j < i; ++j) if (keep[i] == keep[j]) return -1;
        for (size_t j = i; j && keep[j] < keep[j - 1]; --j) {
            int value = keep[j]; keep[j] = keep[j - 1]; keep[j - 1] = value;
        }
    }
    unsigned int first = 3;
    for (size_t i = 0; i < count; ++i) {
        unsigned int next = (unsigned int)keep[i];
        if (first < next && syscall(SYS_close_range, first, next - 1, 0)) return -1;
        first = next + 1;
    }
    return syscall(SYS_close_range, first, UINT_MAX, 0) || w4_b_checkpoint(f) ? -1 : 0;
}

/* The control prefix only reads existing descriptions. Identify every original
 * input before the shared helper closes unlisted inheritance and locks all
 * later acquisitions, including received rights and transient validation FDs.
 * Broker environment numbers must not be used again after relocation. */
static int w4_b_resources(w4_bootstrap_fds_t *f, control_t *control,
                           int *broker_r, int *broker_w) {
    int reserved[] = {f->gate, f->frame, f->lifeline, f->enrollment,
        f->lifecycle, f->profile, control->target_fd, control->bootstrap_fd};
    size_t reserved_count = sizeof(reserved) / sizeof(reserved[0]);
    if (wq_fd_distinct(reserved, reserved_count) ||
        grant_fds_disjoint(control, reserved, reserved_count) ||
        handoff_broker(getenv("LUNAR_PRODUCER_RESPONSE_FD"), getenv("LUNAR_PRODUCER_REQUEST_FD"),
                       reserved, reserved_count, broker_r, broker_w)) return -1;
    int broker[] = {*broker_r, *broker_w};
    if (grant_fds_disjoint(control, broker, 2) ||
        validate_private_sink(control, f->deadline, reserved, reserved_count) ||
        validate_private_sink(control, f->deadline, broker, 2)) return -1;
    int *slots[W4_FD_LIMIT]; size_t count = 0;
    slots[count++] = &f->gate; slots[count++] = &f->frame;
    slots[count++] = &f->lifeline; slots[count++] = &f->enrollment;
    slots[count++] = &f->lifecycle; slots[count++] = &f->profile;
    slots[count++] = &control->target_fd; slots[count++] = &control->bootstrap_fd;
    if (*broker_r >= 0) { slots[count++] = broker_r; slots[count++] = broker_w; }
    for (size_t i = 0; i < control->grant_count; ++i) {
        if (count == W4_FD_LIMIT) return -1;
        slots[count++] = &control->grants[i].fd;
    }
    w4_resource_fixed_t fixed[2]; size_t fixed_count = 0;
    if (control->version >= 3)
        fixed[fixed_count++] = (w4_resource_fixed_t){&control->sink_fd, FIXED_LIVE_SINK_FD};
    if (control->version == 4)
        fixed[fixed_count++] = (w4_resource_fixed_t){&control->completion_fd, FIXED_COMPLETION_SINK_FD};
    return w4_resource_enter(slots, count, fixed, fixed_count);
}

/* Fixed sinks already name original OFDs; v4 changes only CLOEXEC without
 * duplicate acquisition. Do not call this from the legacy child path. */
static int w4_b_inherit_sinks(const control_t *control) {
    if ((control->version >= 3 && control->sink_fd != FIXED_LIVE_SINK_FD) ||
        (control->version == 4 && control->completion_fd != FIXED_COMPLETION_SINK_FD)) return -1;
    if (control->version >= 3 && handoff_cloexec(control->sink_fd, 0)) return -1;
    return control->version == 4 ? handoff_cloexec(control->completion_fd, 0) : 0;
}

/* Explicit v4 setup preserves the legacy credential, actual-U access, grant
 * isolation and original release checks. Its only sink handoff uses the fixed
 * original OFDs already counted by the inherited kernel resource limit. */
static _Noreturn void w4_b_child(const wq_bootstrap_fds_t *fds, control_t *control,
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
    if (w4_b_inherit_sinks(control)) child_start_failed(error_fd, EINVAL, 78);
    if (control->version >= 3) {
        snprintf(sink_deadline, sizeof(sink_deadline), "LUNAR_FIXED_LIVE_DEADLINE_NS=%llu",
                 (unsigned long long)control->sink_deadline_ns);
        environment[env_count++] = sink_deadline;
    }
    if (control->version == 4) {
        snprintf(completion_deadline, sizeof(completion_deadline), "LUNAR_FIXED_COMPLETION_DEADLINE_NS=%llu",
                 (unsigned long long)control->completion_deadline_ns);
        environment[env_count++] = completion_deadline;
    }
    environment[env_count] = NULL;
    if (wq_remaining(fds->deadline) < 0) child_start_failed(error_fd, ECANCELED, 78);
    fexecve(control->target_fd, control->argv, environment);
    child_start_failed(error_fd, errno, 78);
}

static int w4_bootstrap_main(int argc, char **argv) {
    if (argc != 18) return 64;
    const char *names[8] = {"--control-fd", "--gate-fd", "--frame-fd", "--controller-lifeline-fd",
        "--scope-enrollment-fd", "--scope-lifecycle-fd", "--profile-fd", "--deadline-monotonic-ns"};
    w4_bootstrap_fds_t fds;
    memset(&fds, 0, sizeof(fds));
    fds.q_lifeline = -1;
    for (size_t i = 0; i < 3; ++i) fds.peers[i] = -1;
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
    if (w4_b_read(&fds, fds.control, raw, sizeof(raw), &received, 1) ||
        parse_control(raw, received, &control) || control.version < 2) return 66;
    if (close(fds.control)) return 66;
    fds.control = -1;
    int broker_r = -1, broker_w = -1;
    if (w4_b_resources(&fds, &control, &broker_r, &broker_w) || w4_b_checkpoint(&fds)) return 78;
    wq_message_t message;
    int initial_rights[2] = {-1, -1};
    if (w4_b_receive(&fds, fds.enrollment, &message, initial_rights, 2)) return 78;
    int scope_fd = initial_rights[0];
    fds.q_lifeline = initial_rights[1];
    if (grant_protocol_pipe(fds.q_lifeline, O_RDONLY) || w4_b_checkpoint(&fds)) return 78;
    wq_binding_t binding; memcpy(&binding, &message.binding, sizeof(binding));
    wq_identity_t scope; memcpy(&scope, &message.scope, sizeof(scope));
    wq_profile_t profile;
    wq_publication_t zero_publications[3] = {{0}};
    if (w4_check(&message, &binding, W4_B_SCOPE, 1, 2) ||
        binding.deadline_ns != fds.deadline || message.target_pid ||
        memcmp(message.publications, zero_publications, sizeof(zero_publications)) ||
        memcmp(binding.launch_sha256, control.launch, 65) || memcmp(binding.intent_sha256, control.intent, 65) ||
        memcmp(binding.target_sha256, control.target_sha, 65) ||
        w4_load_profile(fds.profile, binding.profile_sha256, &profile, fds.deadline) ||
        wq_profile_binding(&profile, &binding) || wq_b_profile_grants(&control, &profile, fds.deadline)) return 78;
    wq_identity_t observed_scope;
    char image_digest[65], target_digest[65];
    struct stat self, original_bootstrap, original_target;
    controller_guard_t guard; memset(&guard, 0, sizeof(guard));
    guard.fd = fds.lifeline; guard.deadline_ns = fds.deadline;
    int reserved[10] = {fds.gate, fds.frame, fds.lifeline, fds.enrollment, fds.lifecycle,
        fds.profile, scope_fd, control.target_fd, control.bootstrap_fd, fds.q_lifeline};
    if (wq_fd_distinct(reserved, 10) || wq_identity(scope_fd, &observed_scope, 1) ||
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
        grant_fds_disjoint(&control, reserved, 10) || validate_grant_graph(&control, &guard) ||
        validate_private_sink(&control, fds.deadline, reserved, 10)) return 78;
    int error_pipe[2], ready_pipe[2], release_pipe[2];
    if (pipe2(error_pipe, O_CLOEXEC | O_NONBLOCK) || pipe2(ready_pipe, O_CLOEXEC | O_NONBLOCK) ||
        pipe2(release_pipe, O_CLOEXEC | O_NONBLOCK)) return 78;
    int target_fd = fcntl(control.target_fd, F_DUPFD_CLOEXEC, 3), target_pidfd = -1;
    if (target_fd < 0 || w4_b_checkpoint(&fds)) return 78;
    int dynamic[] = {fds.gate, fds.frame, fds.lifeline, fds.enrollment, fds.lifecycle, fds.profile, scope_fd,
        target_fd, control.target_fd, control.bootstrap_fd, error_pipe[0], error_pipe[1],
        ready_pipe[0], ready_pipe[1], release_pipe[0], release_pipe[1], broker_r, broker_w, fds.q_lifeline};
    if (grant_fds_disjoint(&control, dynamic, sizeof(dynamic) / sizeof(dynamic[0])) ||
        validate_private_sink(&control, fds.deadline, dynamic, sizeof(dynamic) / sizeof(dynamic[0])) ||
        w4_b_close_unlisted(&fds, &control, dynamic, sizeof(dynamic) / sizeof(dynamic[0]))) return 78;
    struct clone_args arguments;
    memset(&arguments, 0, sizeof(arguments));
    arguments.flags = CLONE_INTO_CGROUP | CLONE_PIDFD;
    arguments.pidfd = (uint64_t)(uintptr_t)&target_pidfd;
    arguments.cgroup = (uint64_t)scope_fd; arguments.exit_signal = SIGCHLD;
    /* This entrypoint has never created the legacy controller pthread. */
    pid_t target = (pid_t)syscall(SYS_clone3, &arguments, sizeof(arguments));
    if (target < 0) return 78; /* Never fork/migrate as a fallback. */
    if (!target) {
        /* T closes Q's observation inputs in the original close-all-except
         * child path; only B holds Q's lifeline and S/G/R observation copies.
         * T's own final exec check uses the unchanged execution cutoff. */
        wq_bootstrap_fds_t child_fds = {fds.control, fds.gate, fds.frame, fds.lifeline,
            fds.enrollment, fds.lifecycle, fds.profile, fds.deadline - W4_RESERVE_NS};
        w4_b_child(&child_fds, &control, &profile, target_fd, error_pipe[1],
                   ready_pipe[1], release_pipe[0], scope_fd, broker_r, broker_w);
    }
    close(error_pipe[1]); close(ready_pipe[1]); close(release_pipe[0]); close(target_fd);
    unsigned char ready[2];
    if (w4_b_read(&fds, ready_pipe[0], ready, sizeof(ready), &received, 1) ||
        received != 1 || ready[0] != 'R' || close(ready_pipe[0]) || close(scope_fd)) return 78;
    scope_fd = -1; /* One-shot enrollment authority is irrevocably closed. */
    w4_init(&message, &binding, W4_ENROLLED, 1, 1);
    memcpy(&message.scope, &scope, sizeof(scope)); message.target_pid = (uint64_t)target;
    if (w4_b_send(&fds, fds.enrollment, &message, &target_pidfd, 1) ||
        w4_b_receive(&fds, fds.enrollment, &message, NULL, 0) ||
        w4_check(&message, &binding, W4_ENROLL_ACK, 2, 0) ||
        !wq_identity_equal(&message.scope, &scope) || message.target_pid != (uint64_t)target ||
        memcmp(message.publications, zero_publications, sizeof(zero_publications)) ||
        close(fds.enrollment) ||
        emit_frame(fds.frame, control.launch, control.intent, 1, "bootstrap_ready", NULL, 0, 0)) return 78;
    /* The original Q delivers its direct-child observation pidfds on the
     * lifecycle channel before any release request. These are never wait rights. */
    if (w4_b_receive(&fds, fds.lifecycle, &message, fds.peers, 3) ||
        w4_check(&message, &binding, W4_B_PEERS, 2, 3) ||
        !wq_identity_equal(&message.scope, &scope) || message.target_pid != (uint64_t)target)
        return 78;
    wq_message_t registration = message;
    if (w4_b_publications(&registration)) return 78;
    int peer_roles[] = {fds.peers[0], fds.peers[1], fds.peers[2], target_pidfd,
        fds.lifeline, fds.q_lifeline, fds.lifecycle, fds.frame, fds.profile,
        control.target_fd, control.bootstrap_fd};
    if (wq_fd_distinct(peer_roles, sizeof(peer_roles) / sizeof(peer_roles[0])) ||
        grant_fds_disjoint(&control, peer_roles, sizeof(peer_roles) / sizeof(peer_roles[0])) ||
        validate_private_sink(&control, fds.deadline, peer_roles,
                              sizeof(peer_roles) / sizeof(peer_roles[0]))) return 78;
    fds.peers_required = 1;
    if (w4_b_checkpoint(&fds)) return 78;
    w4_change(&message, W4_B_PEER_ACK, 2, 0);
    if (w4_b_send(&fds, fds.lifecycle, &message, NULL, 0)) return 78;
    unsigned char gate[2];
    if (w4_b_read(&fds, fds.gate, gate, sizeof(gate), &received, 1) || received != 1 || gate[0] != '1' ||
        close(fds.gate) || validate_grant_graph(&control, &guard) ||
        wq_b_profile_grants(&control, &profile, fds.deadline) || w4_b_checkpoint(&fds)) return 78;
    message = registration;
    w4_change(&message, W4_B_RELEASE, 3, 0);
    if (w4_b_send(&fds, fds.lifecycle, &message, NULL, 0) ||
        w4_b_receive(&fds, fds.lifecycle, &message, NULL, 0) ||
        w4_check(&message, &binding, W4_PERMIT, 3, 0) ||
        !w4_context_equal(&message, &registration) ||
        w4_b_before_gate(&fds)) return 78;
    wq_publication_t original_publications[3];
    memcpy(original_publications, message.publications, sizeof(original_publications));
    for (size_t i = 0; i < 3; ++i)
        if (!original_publications[i].inode || !original_publications[i].size ||
            original_publications[i].size > MAX_CONTROL || wq_digest(original_publications[i].sha256)) return 78;
    if (wq_b_profile_grants(&control, &profile, fds.deadline) ||
        w4_load_profile(fds.profile, binding.profile_sha256, &profile, fds.deadline) ||
        wq_profile_binding(&profile, &binding) ||
        validate_grant_graph(&control, &guard) || w4_b_before_gate(&fds)) return 78;
    unsigned char release = '1';
    if (write(release_pipe[1], &release, 1) != 1 || close(release_pipe[1])) return 78;
    int exec_error = 0;
    if (w4_b_read(&fds, error_pipe[0], &exec_error, sizeof(exec_error), &received, 1) || received ||
        close(error_pipe[0]) || emit_frame(fds.frame, control.launch, control.intent, 2, "target_started",
                                         target_digest, target, getpgrp())) return 78;
    siginfo_t child_status;
    for (;;) {
        if (w4_b_checkpoint(&fds)) return 78;
        memset(&child_status, 0, sizeof(child_status));
        if (waitid(P_PIDFD, (id_t)target_pidfd, &child_status, WEXITED | WNOHANG)) {
            if (errno == EINTR) continue;
            return 78;
        }
        if (child_status.si_pid) break;
        if (w4_b_poll(&fds, target_pidfd, POLLIN)) return 78;
    }
    if (child_status.si_pid != target || w4_b_checkpoint(&fds)) return 78;
    close(target_pidfd);
    message = registration;
    w4_change(&message, W4_B_DONE, 4, 0);
    if (w4_b_done(&fds, &message)) return 78;
    /* Q now intentionally retires S/G/R. Their exited pidfds cannot remain
     * liveness prerequisites, and Q may exit after queuing its complete result.
     * This consumes that original result, never a replacement for C's Q wait. */
    fds.peers_required = 0;
    w4_result_t result;
    if (w4_b_final_result(&fds, &registration, &result) ||
        emit_frame(fds.frame, control.launch, control.intent, 3, "terminal", NULL, 0, 0)) return 78;
    free_control(&control);
    if (child_status.si_code == CLD_EXITED) return child_status.si_status;
    if (child_status.si_code == CLD_KILLED || child_status.si_code == CLD_DUMPED) return 128 + child_status.si_status;
    return 78;
}
#endif
