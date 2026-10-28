/* Explicit v4 graph. Included after the reviewed v1/v2/v3 filesystem helpers;
 * none of their state machines or wire constants is used as a v4 owner. */
#ifndef LUNAR_NATIVE_WHOLE_SCOPE_SUCCESSOR_H
#define LUNAR_NATIVE_WHOLE_SCOPE_SUCCESSOR_H
#include "native_whole_scope_successor_protocol.h"
#include "native_whole_scope_successor_resources.h"
_Static_assert(W4_FD_LIMIT == W4_RESOURCE_FD_LIMIT, "v4 resource/role FD bound");

typedef int (*w4_checkpoint_t)(void *);
static int w4_again(void) { return errno == EAGAIN || errno == EWOULDBLOCK || errno == EINTR; }
static int w4_keep_from(const int *fds, size_t count, unsigned int first) {
    if (!count || count > W4_FD_LIMIT) return -1;
    int sorted[W4_FD_LIMIT];
    for (size_t i = 0; i < count; ++i) {
        if (fds[i] <= 2) return -1;
        sorted[i] = fds[i];
        for (size_t j = i; j && sorted[j] < sorted[j - 1]; --j) {
            int swap = sorted[j]; sorted[j] = sorted[j - 1]; sorted[j - 1] = swap;
        }
    }
    for (size_t i = 0; i < count; ++i) {
        if (i && sorted[i] == sorted[i - 1]) return -1;
        if (first < (unsigned int)sorted[i] && syscall(SYS_close_range, first, (unsigned int)sorted[i] - 1, 0)) return -1;
        first = (unsigned int)sorted[i] + 1;
    }
    return syscall(SYS_close_range, first, UINT_MAX, 0) ? -1 : 0;
}
static int w4_keep(const int *fds, size_t count) { return w4_keep_from(fds, count, 0); }
static int w4_transfer(int fd, void *packet, size_t bytes, int *rights, size_t count,
                        int sending, uint64_t deadline, w4_checkpoint_t check, void *owner) {
    for (;;) {
        if (wq_remaining(deadline) < 0 || (check && check(owner))) return -1;
        int result = sending ? w4_send(fd, packet, bytes, rights, count) :
                               w4_receive(fd, packet, bytes, rights, count, deadline);
        if (!result) {
            if (wq_remaining(deadline) >= 0 && (!check || !check(owner))) return 0;
            if (!sending) for (size_t i = 0; i < count; ++i) { close(rights[i]); rights[i] = -1; }
            return -1;
        }
        if (!w4_again()) return -1;
        struct pollfd p = {fd, sending ? POLLOUT : POLLIN, 0};
        int remaining = wq_remaining(deadline);
        if (remaining < 0 || (poll(&p, 1, remaining) < 0 && errno != EINTR)) return -1;
    }
}
static size_t w4_packet_size(uint32_t operation) {
    switch (operation) {
    case W4_PROPOSAL: case W4_S_PREPARE: case W4_S_PREPARED:
    case W4_G_RETIRE_NORMAL: case W4_S_EXIT_NORMAL: case W4_G_RETIRE_ABNORMAL:
        return sizeof(w4_proposal_t);
    case W4_COMMIT_NORMAL: case W4_COMMIT_ABNORMAL: case W4_ACK: return sizeof(w4_commit_t);
    case W4_G_STOP: case W4_CANCEL: case W4_ROLE_CANCEL: return sizeof(w4_command_t);
    case W4_RESULT: case W4_ABNORMAL_RESULT: return sizeof(w4_result_t);
    default: return sizeof(wq_message_t);
    }
}
static int w4_receive_any(int fd, void *packet, size_t *bytes, uint64_t deadline) {
    wq_message_t peek;
    ssize_t got = recv(fd, &peek, sizeof(peek), MSG_PEEK | MSG_DONTWAIT);
    if (got < 0) return -1;
    size_t expected = got >= (ssize_t)sizeof(peek) ? w4_packet_size(peek.operation) : sizeof(peek);
    if (w4_receive(fd, packet, expected, NULL, 0, deadline)) return -1;
    *bytes = expected; return 0;
}
static const char *w4_record_names[2] = {"scope-registration-v4.bin", "scope-terminal-v4.bin"};
static int w4_names(int directory, const wq_identity_t *parent, uint64_t deadline) {
    if (wq_remaining(deadline) < 0) return -1;
    int fd = openat(directory, ".", O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    wq_identity_t current;
    if (fd < 0) return -1;
    if (wq_identity(fd, &current, 0) || !wq_identity_equal(parent, &current)) { close(fd); return -1; }
    DIR *entries = fdopendir(fd);
    if (!entries) { close(fd); return -1; }
    unsigned int seen = 0; int result = -1;
    for (unsigned int i = 0; i < 5; ++i) {
        if (wq_remaining(deadline) < 0) break;
        errno = 0; struct dirent *entry = readdir(entries);
        if (!entry) { if (!errno && seen == 3) result = 0; break; }
        if (!strcmp(entry->d_name, ".") || !strcmp(entry->d_name, "..")) continue;
        unsigned int bit = !strcmp(entry->d_name, w4_record_names[0]) ? 1u :
                           !strcmp(entry->d_name, w4_record_names[1]) ? 2u : 0u;
        if (!bit || seen & bit) break;
        seen |= bit;
    }
    if (closedir(entries) || wq_remaining(deadline) < 0) return -1;
    return result;
}
static int w4_records(int directory, const int files[2], const wq_identity_t *parent,
                       const wq_identity_t pins[2], const wq_message_t *registration,
                       const w4_commit_t *terminal, const struct stat *registration_pin,
                       const struct stat *empty_pin, uint64_t deadline) {
    off_t sizes[2] = {registration ? (off_t)sizeof(*registration) : 0,
                      terminal ? (off_t)sizeof(*terminal) : 0};
    struct stat before[2], after, named;
    if (wq_fd_distinct(files, 2) || w4_names(directory, parent, deadline)) return -1;
    for (size_t i = 0; i < 2; ++i)
        if (v3_record_identity(directory, files[i], w4_record_names[i], parent, &pins[i], sizes[i], deadline) ||
            fstat(files[i], &before[i])) return -1;
    char raw[sizeof(w4_commit_t) + 1];
    if (registration && (checked_read(files[0], &pins[0], raw, sizeof(*registration) + 1, deadline, 0) !=
        (int)sizeof(*registration) || memcmp(raw, registration, sizeof(*registration)))) return -1;
    if (terminal && (checked_read(files[1], &pins[1], raw, sizeof(*terminal) + 1, deadline, 0) !=
        (int)sizeof(*terminal) || memcmp(raw, terminal, sizeof(*terminal)))) return -1;
    for (size_t i = 0; i < 2; ++i)
        if (v3_record_identity(directory, files[i], w4_record_names[i], parent, &pins[i], sizes[i], deadline) ||
            fstat(files[i], &after) || !v3_stat_equal(&before[i], &after) ||
            fstatat(directory, w4_record_names[i], &named, AT_SYMLINK_NOFOLLOW) ||
            !v3_stat_equal(&before[i], &named)) return -1;
    if (registration_pin && v3_stat_pin_check(directory, files[0], w4_record_names[0], registration_pin, deadline)) return -1;
    if (!terminal && empty_pin && (empty_pin->st_size ||
        v3_stat_pin_check(directory, files[1], w4_record_names[1], empty_pin, deadline))) return -1;
    return w4_names(directory, parent, deadline);
}
typedef struct {
    int channel, to_r, c_life, q_life, s_life, g_life, own_life;
    int peers[3], target, publications[3], registered, prepared, abnormal, normal_draining;
    uint64_t deadline, cutoff;
    uint32_t source, trigger;
    scope_t scope;
    wq_message_t context;
} w4_role_t;
static int w4_role_check(void *opaque) {
    w4_role_t *r = opaque; uint64_t now;
    if (wq_remaining(r->deadline) < 0) { r->trigger = 2; return -1; }
    if (live(r->q_life)) { r->trigger = 7; return -1; }
    if (r->abnormal) return 0;
    if (live(r->c_life)) { r->trigger = 1; return -1; }
    if (!r->normal_draining && (wq_now(&now) || now >= r->cutoff)) { r->trigger = 2; return -1; }
    if (r->peers[2] >= 0 && exited(r->peers[2])) { r->trigger = 3; return -1; }
    if (!r->prepared && r->peers[1] >= 0 && exited(r->peers[1])) {
        r->trigger = r->source == W4_SOURCE_G ? 5 : 6; return -1;
    }
    return 0;
}
static int w4_role_io(w4_role_t *r, void *packet, size_t bytes, int *rights, size_t count, int send) {
    return w4_transfer(r->channel, packet, bytes, rights, count, send, r->deadline, w4_role_check, r);
}
static int w4_role_context_check(w4_role_t *r) {
    if (!r->registered || scope_check(&r->scope, 1)) return -1;
    if (r->source == W4_SOURCE_S) {
        for (size_t i = 0; i < 3; ++i) {
            if (wq_publication_check(r->publications[i], &r->context.publications[i], r->deadline)) return -1;
        }
    }
    return 0;
}
static int w4_role_fds(w4_role_t *r) {
    int roles[23] = {r->channel, r->to_r, r->c_life, r->q_life, r->own_life,
        r->source == W4_SOURCE_S ? r->g_life : r->s_life,
        r->scope.leaf, r->scope.files[0], r->scope.files[1], r->scope.files[2],
        r->scope.files[3], r->scope.files[6], r->scope.files[7]};
    size_t count = 13;
    for (size_t i = 0; i < 3; ++i) if (r->peers[i] >= 0) {
        if (syscall(SYS_pidfd_send_signal, r->peers[i], 0, NULL, 0)) return -1;
        roles[count++] = r->peers[i];
    }
    if (r->target >= 0) roles[count++] = r->target;
    for (size_t i = 0; i < 3; ++i) if (r->publications[i] >= 0) roles[count++] = r->publications[i];
    return wq_fd_distinct(roles, count);
}
static int w4_role_init(w4_role_t *r, const wq_binding_t *binding) {
    int rights[4] = {-1, -1, -1, -1}; wq_message_t m;
    if (w4_role_io(r, &m, sizeof(m), rights, 4, 0)) return -1;
    r->scope.leaf = rights[0]; r->scope.files[0] = rights[1];
    r->scope.files[1] = rights[2]; r->scope.files[2] = rights[3];
    if (w4_check(&m, binding, W4_SCOPE_A, 0, 4) || m.target_pid || zero(m.publications, sizeof(m.publications))) return -1;
    r->scope.leaf_pin = m.scope; r->scope.deadline = r->deadline;
    if (w4_role_io(r, &m, sizeof(m), rights, 3, 0)) return -1;
    r->scope.files[3] = rights[0]; r->scope.files[6] = rights[1]; r->scope.files[7] = rights[2];
    if (w4_check(&m, binding, W4_SCOPE_B, 1, 3) || !wq_identity_equal(&m.scope, &r->scope.leaf_pin) ||
        m.target_pid || zero(m.publications, sizeof(m.publications))) return -1;
    int fds[7] = {r->scope.leaf, r->scope.files[0], r->scope.files[1], r->scope.files[2],
                  r->scope.files[3], r->scope.files[6], r->scope.files[7]};
    if (wq_fd_distinct(fds, 7)) return -1;
    wq_identity_t leaf;
    if (wq_identity(r->scope.leaf, &leaf, 1) || !wq_identity_equal(&leaf, &r->scope.leaf_pin)) return -1;
    for (size_t i = 0; i < 8; ++i)
        if (i != 4 && i != 5 && wq_identity(r->scope.files[i], &r->scope.pins[i], 1)) return -1;
    if (scope_check(&r->scope, 1) || w4_role_io(r, &m, sizeof(m), rights, 3, 0)) return -1;
    for (size_t i = 0; i < 3; ++i) r->peers[i] = rights[i];
    if (w4_check(&m, binding, r->source == W4_SOURCE_S ? W4_S_PEERS : W4_G_PEERS, 2, 3) ||
        !wq_identity_equal(&m.scope, &r->scope.leaf_pin) || m.target_pid ||
        zero(m.publications, sizeof(m.publications)) || w4_role_fds(r)) return -1;
    w4_init(&m, binding, W4_READY, 3, 0); m.scope = r->scope.leaf_pin;
    if (w4_role_io(r, &m, sizeof(m), NULL, 0, 1)) return -1;
    size_t count = r->source == W4_SOURCE_S ? 4 : 0;
    if (w4_role_io(r, &m, sizeof(m), rights, count, 0)) return -1;
    if (count) { r->target = rights[0]; for (size_t i = 0; i < 3; ++i) r->publications[i] = rights[i + 1]; }
    if (w4_check(&m, binding, count ? W4_S_CONTEXT : W4_G_CONTEXT, 5, (uint32_t)count) ||
        !wq_identity_equal(&m.scope, &r->scope.leaf_pin) || !m.target_pid ||
        !zero(m.publications, sizeof(m.publications))) return -1;
    r->context = m; r->registered = 1;
    if (w4_role_context_check(r) || w4_role_fds(r) ||
        (r->target >= 0 && syscall(SYS_pidfd_send_signal, r->target, 0, NULL, 0))) return -1;
    w4_change(&m, W4_CONTEXT_ACK, 5, 0);
    return w4_role_io(r, &m, sizeof(m), NULL, 0, 1);
}
static int w4_submit_proposal(w4_role_t *r, w4_proposal_t *p) {
    if (w4_transfer(r->to_r, p, sizeof(*p), NULL, 0, 1, r->deadline, w4_role_check, r)) return -1;
    return w4_role_io(r, p, sizeof(*p), NULL, 0, 1);
}
static int w4_bound_proposal(const w4_proposal_t *packet, const w4_proposal_t *original,
                              uint32_t operation, uint32_t sequence) {
    w4_proposal_t expected = *original;
    w4_change(&expected.context, operation, sequence, 0);
    return memcmp(packet, &expected, sizeof(expected));
}
static _Noreturn void w4_primary(w4_role_t r, const wq_binding_t *binding) {
    if (w4_role_init(&r, binding)) goto failure;
    wq_message_t done;
    if (w4_role_io(&r, &done, sizeof(done), NULL, 0, 0) ||
        w4_check(&done, binding, W4_S_DONE, 6, 0) || !w4_context_equal(&done, &r.context)) goto failure;
    for (;;) {
        int populated;
        if (w4_role_check(&r) || w4_role_context_check(&r) || scope_events(&r.scope, 6, &populated)) goto failure;
        if (!populated && exited(r.target) == 1) break;
        struct pollfd p = {r.scope.files[6], POLLPRI | POLLERR, 0};
        int left = wq_remaining(r.deadline);
        if (left < 0 || (poll(&p, 1, left) < 0 && errno != EINTR)) goto failure;
    }
    /* Genuine empty completion before cutoff may use the original reserve. */
    r.normal_draining = 1;
    w4_proposal_t original = {0}; original.context = r.context;
    w4_change(&original.context, W4_PROPOSAL, 7, 0);
    original.source = W4_SOURCE_S; original.facts = 10;
    uint64_t observed_ns;
    if (wq_now(&observed_ns)) goto failure;
    original.observed_ns = observed_ns;
    if (w4_submit_proposal(&r, &original)) goto failure;
    w4_proposal_t request;
    if (w4_role_io(&r, &request, sizeof(request), NULL, 0, 0) ||
        w4_bound_proposal(&request, &original, W4_S_PREPARE, 8) || live(r.c_life) || w4_role_context_check(&r)) goto failure;
    r.prepared = 1;
    w4_change(&request.context, W4_S_PREPARED, 8, 0);
    if (w4_role_io(&r, &request, sizeof(request), NULL, 0, 1) ||
        w4_role_io(&r, &request, sizeof(request), NULL, 0, 0) ||
        w4_bound_proposal(&request, &original, W4_S_EXIT_NORMAL, 9) || live(r.c_life) ||
        w4_role_context_check(&r)) goto failure;
    int populated;
    if (scope_events(&r.scope, 6, &populated) || populated || wq_remaining(r.deadline) < 0) goto failure;
    _exit(0);
failure:
    if (r.peers[0] >= 0 && r.scope.leaf >= 0 && r.scope.files[7] >= 0)
        emergency_stop(&r.scope, r.peers[0], 1);
    _exit(W4_FAILURE);
}
static _Noreturn void w4_guardian(w4_role_t r, const wq_binding_t *binding) {
    if (w4_role_init(&r, binding)) goto stop;
    for (;;) {
        if (w4_role_check(&r) || w4_role_context_check(&r)) goto stop;
        unsigned char packet[sizeof(w4_result_t)]; size_t size;
        if (!w4_receive_any(r.channel, packet, &size, r.deadline)) {
            wq_message_t *m = (wq_message_t *)packet;
            if (m->operation == W4_G_STOP && size == sizeof(w4_command_t)) {
                w4_command_t *command = (w4_command_t *)packet;
                if (w4_check(m, binding, W4_G_STOP, 6, 0) || !w4_context_equal(m, &r.context) ||
                    command->reserved || command->reason < 1 || command->reason > 7) goto stop;
                r.trigger = 8; goto stop;
            }
            if (m->operation == W4_G_RETIRE_NORMAL && size == sizeof(w4_proposal_t)) {
                w4_proposal_t original = *(w4_proposal_t *)packet;
                w4_change(&original.context, W4_PROPOSAL, 7, 0);
                int populated;
                if (w4_bound_proposal((w4_proposal_t *)packet, &original, W4_G_RETIRE_NORMAL, 8) ||
                    w4_proposal_check(&original, &r.context, W4_SOURCE_S) ||
                    scope_events(&r.scope, 6, &populated) || populated || live(r.c_life) ||
                    wq_remaining(r.deadline) < 0) goto stop;
                _exit(0);
            }
            goto stop;
        }
        if (!w4_again()) goto stop;
        struct pollfd p = {r.channel, POLLIN, 0}; int left = wq_remaining(r.deadline);
        if (left < 0 || (poll(&p, 1, left) < 0 && errno != EINTR)) goto stop;
    }
stop:
    r.abnormal = 1;
    uint32_t facts = W4_STOP;
    if (r.peers[0] >= 0 && r.scope.leaf >= 0 && r.scope.files[7] >= 0)
        facts = emergency_stop_observed(&r.scope, r.peers[0], 1);
    if (!r.registered || !r.trigger || r.trigger == 7 || wq_remaining(r.deadline) < 0 || live(r.q_life)) _exit(W4_FAILURE);
    w4_proposal_t proposal = {0}; proposal.context = r.context;
    w4_change(&proposal.context, W4_PROPOSAL, 7, 0);
    proposal.source = W4_SOURCE_G; proposal.trigger = r.trigger; proposal.facts = facts & 7u;
    uint64_t observed_ns;
    if (wq_now(&observed_ns)) _exit(W4_FAILURE);
    proposal.observed_ns = observed_ns;
    if (w4_submit_proposal(&r, &proposal)) _exit(W4_FAILURE);
    int retired = 0;
    for (unsigned int received = 0; received < 2 && !retired; ++received) {
        unsigned char packet[sizeof(w4_result_t)]; size_t bytes;
        for (;;) {
            if (w4_role_check(&r)) _exit(W4_FAILURE);
            if (!w4_receive_any(r.channel, packet, &bytes, r.deadline)) break;
            if (!w4_again()) _exit(W4_FAILURE);
            struct pollfd p = {r.channel, POLLIN, 0}; int left = wq_remaining(r.deadline);
            if (left < 0 || (poll(&p, 1, left) < 0 && errno != EINTR)) _exit(W4_FAILURE);
        }
        if (bytes == sizeof(w4_command_t)) {
            w4_command_t *stop = (w4_command_t *)packet;
            if (received || w4_check(&stop->context, binding, W4_G_STOP, 6, 0) ||
                !w4_context_equal(&stop->context, &r.context) || stop->reserved ||
                stop->reason < W4_C_LOST || stop->reason > W4_C_CANCEL) _exit(W4_FAILURE);
            /* The independently observed proposal is immutable. A queued Q
             * stop after it neither replaces its source nor rewrites facts. */
        } else if (bytes == sizeof(w4_proposal_t) &&
            !w4_bound_proposal((w4_proposal_t *)packet, &proposal, W4_G_RETIRE_ABNORMAL, 8)) retired = 1;
        else _exit(W4_FAILURE);
    }
    if (!retired) _exit(W4_FAILURE);
    int populated;
    if (w4_role_context_check(&r) || scope_events(&r.scope, 6, &populated) || populated) _exit(W4_FAILURE);
    _exit(W4_FAILURE);
}
typedef struct { int channel, q_life; uint64_t deadline; } w4_storage_t;
static int w4_storage_check(void *opaque) {
    w4_storage_t *r = opaque;
    return wq_remaining(r->deadline) < 0 || live(r->q_life);
}
static _Noreturn void w4_receiver(int channel, int s_channel, int g_channel, int q_life,
                                  const wq_binding_t *binding) {
    w4_storage_t r = {channel, q_life, binding->deadline_ns};
    wq_message_t registration; int directory = -1;
    if (w4_transfer(channel, &registration, sizeof(registration), &directory, 1, 0, r.deadline, w4_storage_check, &r) ||
        w4_check(&registration, binding, W4_R_INIT, 0, 1) || registration.target_pid ||
        zero(registration.publications, sizeof(registration.publications))) _exit(W4_FAILURE);
    wq_identity_t parent, original_scope = registration.scope;
    if (private_directory(directory, &parent) || private_no_acl(directory)) _exit(W4_FAILURE);
    w4_change(&registration, W4_READY, 1, 0);
    if (w4_transfer(channel, &registration, sizeof(registration), NULL, 0, 1, r.deadline, w4_storage_check, &r) ||
        w4_transfer(channel, &registration, sizeof(registration), NULL, 0, 0, r.deadline, w4_storage_check, &r) ||
        w4_check(&registration, binding, W4_R_REGISTER, 1, 0) || !registration.target_pid ||
        !wq_identity_equal(&registration.scope, &original_scope) ||
        !zero(registration.publications, sizeof(registration.publications))) _exit(W4_FAILURE);
    int files[2] = {-1, -1}; wq_identity_t pins[2]; struct stat reg_pin, empty_pin;
    for (size_t i = 0; i < 2; ++i) {
        files[i] = w4_high_fd(openat(directory, w4_record_names[i], O_RDWR | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600));
        if (files[i] < 0 || wq_identity(files[i], &pins[i], 0)) _exit(W4_FAILURE);
    }
    if (w4_records(directory, files, &parent, pins, NULL, NULL, NULL, NULL, r.deadline) ||
        fstat(files[1], &empty_pin) ||
        store_record_bytes(directory, files[0], w4_record_names[0], &registration, sizeof(registration),
                           r.deadline, &parent, &pins[0], 1) || fsync(files[1]) || fsync(directory) ||
        fstat(files[0], &reg_pin) ||
        w4_records(directory, files, &parent, pins, &registration, NULL, &reg_pin, &empty_pin, r.deadline)) _exit(W4_FAILURE);
    wq_message_t creators = registration; w4_change(&creators, W4_R_CREATORS, 1, 2);
    if (w4_transfer(channel, &creators, sizeof(creators), files, 2, 1, r.deadline, w4_storage_check, &r)) _exit(W4_FAILURE);
    w4_proposal_t proposals[3]; int seen[3] = {0, 0, 0};
    w4_commit_t commit; int committed = 0;
    int channels[3] = {s_channel, g_channel, channel};
    while (!committed) {
        if (w4_storage_check(&r)) _exit(W4_FAILURE);
        struct pollfd polling[3] = {{channels[0], POLLIN, 0}, {channels[1], POLLIN, 0}, {channel, POLLIN, 0}};
        int left = wq_remaining(r.deadline);
        if (left < 0 || (poll(polling, 3, left) < 0 && errno != EINTR)) _exit(W4_FAILURE);
        for (size_t i = 0; i < 3 && !committed; ++i) {
            if (polling[i].revents & (POLLERR | POLLNVAL)) _exit(W4_FAILURE);
            if (!(polling[i].revents & (POLLIN | POLLHUP))) continue;
            unsigned char pending;
            ssize_t peeked = recv(channels[i], &pending, 1, MSG_PEEK | MSG_DONTWAIT);
            if (!peeked) {
                if (i == 2 || close(channels[i])) _exit(W4_FAILURE);
                channels[i] = -1; /* Source loss is not a proposal or any wait fact. */
                continue;
            }
            if (peeked < 0) { if (w4_again()) continue; _exit(W4_FAILURE); }
            unsigned char packet[sizeof(w4_result_t)]; size_t bytes;
            if (w4_receive_any(channels[i], packet, &bytes, r.deadline)) _exit(W4_FAILURE);
            wq_message_t *m = (wq_message_t *)packet;
            if (m->operation == W4_PROPOSAL && bytes == sizeof(w4_proposal_t)) {
                if (seen[i] || w4_proposal_check((w4_proposal_t *)packet, &registration, (uint32_t)i + 1)) _exit(W4_FAILURE);
                proposals[i] = *(w4_proposal_t *)packet; seen[i] = 1;
            } else if (i == 2 && (m->operation == W4_COMMIT_NORMAL || m->operation == W4_COMMIT_ABNORMAL) &&
                       bytes == sizeof(w4_commit_t)) {
                commit = *(w4_commit_t *)packet;
                if (w4_commit_check(&commit, &registration)) _exit(W4_FAILURE);
                size_t selected = commit.proposal.source - 1;
                if (selected >= 3 || !seen[selected] || memcmp(&proposals[selected], &commit.proposal, sizeof(commit.proposal))) _exit(W4_FAILURE);
                committed = 1;
            } else _exit(W4_FAILURE);
        }
    }
    if (w4_storage_check(&r) ||
        w4_records(directory, files, &parent, pins, &registration, NULL, &reg_pin, &empty_pin, r.deadline) ||
        store_record_bytes(directory, files[1], w4_record_names[1], &commit, sizeof(commit), r.deadline, &parent, &pins[1], 1) ||
        w4_records(directory, files, &parent, pins, &registration, &commit, &reg_pin, NULL, r.deadline) ||
        w4_storage_check(&r)) _exit(W4_FAILURE);
    commit.context.operation = W4_ACK;
    if (w4_transfer(channel, &commit, sizeof(commit), NULL, 0, 1, r.deadline, w4_storage_check, &r)) _exit(W4_FAILURE);
    _exit(0);
}
typedef struct {
    int profile, delegation, controller, enrollment, lifecycle, lifeline, image, custody, bootstrap, target;
    int publications[3], creators[2], registered, released, abnormal, normal_draining, locked, sent;
    int retiring[3], bootstrap_finishing;
    int qs[2], qg[2], qr[2], sr[2], gr[2], qlife[2], slife[2], glife[2];
    uint64_t deadline, cutoff;
    uint32_t reason;
    scope_t scope;
    child_t children[3];
    siginfo_t waited[3];
    wq_binding_t binding;
    wq_profile_t installed;
    wq_message_t context, registration;
    wq_identity_t private_pin, creator_pins[2];
    struct stat registration_pin, empty_pin;
    wq_chain_t delegation_chain, custody_chain;
    w4_commit_t commit;
} w4_q_t;
static int w4_close(int *fd) {
    int owned = *fd; *fd = -1;
    return owned >= 0 ? close(owned) : 0;
}
static int w4_q_inventory(w4_q_t *q) {
    int owned[W4_FD_LIMIT]; size_t count = 3; /* Reserved standard roles. */
    owned[0] = 0; owned[1] = 1; owned[2] = 2;
    const int fixed[] = {q->profile, q->delegation, q->controller, q->enrollment, q->lifecycle,
        q->lifeline, q->image, q->custody, q->bootstrap, q->target, q->scope.leaf,
        q->scope.delegation, q->publications[0], q->publications[1], q->publications[2],
        q->creators[0], q->creators[1], q->children[0].pidfd, q->children[1].pidfd,
        q->children[2].pidfd};
    int *pairs[] = {q->qs, q->qg, q->qr, q->sr, q->gr, q->qlife, q->slife, q->glife};
    for (size_t group = 0; group < 5; ++group) {
        size_t length = group == 0 ? sizeof(fixed) / sizeof(fixed[0]) : group == 1 ? 8 :
            group == 2 ? 16 : group == 3 ? q->delegation_chain.count : q->custody_chain.count;
        for (size_t i = 0; i < length; ++i) {
            int fd = group == 0 ? fixed[i] : group == 1 ? q->scope.files[i] :
                group == 2 ? pairs[i / 2][i % 2] : group == 3 ? q->delegation_chain.fds[i] : q->custody_chain.fds[i];
            if (fd < 0) continue;
            if (fd <= 2) return -1;
            size_t j = 0; while (j < count && owned[j] != fd) ++j;
            if (j < count) continue;
            if (count == W4_FD_LIMIT) return -1;
            owned[count++] = fd;
        }
    }
    return 0;
}
static int w4_q_received_roles(w4_q_t *q, const int *incoming, size_t count) {
    const int reserved[] = {q->profile, q->delegation, q->controller, q->enrollment, q->lifecycle,
        q->lifeline, q->image, q->custody, q->bootstrap, q->target, q->scope.leaf,
        q->publications[0], q->publications[1], q->publications[2], q->qs[0], q->qg[0], q->qr[0],
        q->qlife[0], q->qlife[1], q->slife[0], q->glife[0], q->children[0].pidfd,
        q->children[1].pidfd, q->children[2].pidfd, 0, 1, 2};
    if (wq_fd_distinct(incoming, count)) return -1;
    for (size_t i = 0; i < count; ++i) {
        struct stat a;
        if (fstat(incoming[i], &a)) return -1;
        for (size_t group = 0; group < 2; ++group) {
            size_t length = group ? 8 : sizeof(reserved) / sizeof(reserved[0]);
            for (size_t j = 0; j < length; ++j) {
                int other = group ? q->scope.files[j] : reserved[j];
                if (other < 0 || other == incoming[i]) continue;
                struct stat b;
                if (fstat(other, &b)) { if (other <= 2 && errno == EBADF) continue; return -1; }
                if (a.st_dev == b.st_dev && a.st_ino == b.st_ino &&
                    (a.st_mode & S_IFMT) == (b.st_mode & S_IFMT)) return -1;
            }
        }
    }
    return w4_q_inventory(q);
}
static int w4_q_check(void *opaque) {
    w4_q_t *q = opaque; uint64_t now;
    if (wq_remaining(q->deadline) < 0) { q->reason = q->reason ? q->reason : W4_DEADLINE; return -1; }
    if (w4_q_inventory(q)) { q->reason = W4_PROTOCOL; return -1; }
    if (q->abnormal) return 0;
    if (live(q->lifeline)) { q->reason = W4_C_LOST; return -1; }
    if (!q->normal_draining && (wq_now(&now) || now >= q->cutoff)) { q->reason = W4_DEADLINE; return -1; }
    if (q->registered) {
        struct pollfd p = {q->controller, POLLIN, 0};
        int pending = poll(&p, 1, 0);
        if (pending < 0) { q->reason = W4_PROTOCOL; return -1; }
        if (p.revents) {
            wq_message_t peek;
            ssize_t bytes = recv(q->controller, &peek, sizeof(peek), MSG_PEEK | MSG_DONTWAIT);
            if (q->released || bytes != (ssize_t)sizeof(peek) || peek.operation == W4_CANCEL) {
                w4_command_t command;
                int invalid = !(p.revents & POLLIN) ||
                    w4_receive(q->controller, &command, sizeof(command), NULL, 0, q->deadline) ||
                    w4_check(&command.context, &q->binding, W4_CANCEL, 5, 0) ||
                    !w4_context_equal(&command.context, &q->context) ||
                    command.reason != W4_C_CANCEL || command.reserved;
                q->reason = invalid ? W4_PROTOCOL : W4_C_CANCEL;
                return -1;
            }
        }
    }
    if (q->bootstrap >= 0 && !q->bootstrap_finishing && exited(q->bootstrap)) { q->reason = W4_PROTOCOL; return -1; }
    const uint32_t reasons[3] = {W4_S_LOST, W4_G_LOST, W4_R_FAULT};
    for (size_t i = 0; i < 3; ++i)
        if (q->children[i].pidfd >= 0 && !q->retiring[i] && exited(q->children[i].pidfd)) {
            q->reason = reasons[i]; return -1;
        }
    return 0;
}
static int w4_q_io(w4_q_t *q, int fd, void *p, size_t bytes, int *rights, size_t count, int send) {
    return w4_transfer(fd, p, bytes, rights, count, send, q->deadline, w4_q_check, q);
}
static void w4_q_message(w4_q_t *q, wq_message_t *m, uint32_t op, uint32_t seq, uint32_t count) {
    *m = q->context; w4_change(m, op, seq, count);
}
/* Actual original direct-child wait; status survives retirement independently
 * of the pidfd number. An observation copy cannot enter this ownership slot. */
static int w4_q_wait(w4_q_t *q, int index) {
    if (index < 0 || index > 2 || q->children[index].pidfd < 0 || q->children[index].reaped) return -1;
    q->retiring[index] = 1;
    for (;;) {
        if (w4_q_check(q)) return -1;
        siginfo_t status = {0};
        if (waitid(P_PIDFD, (id_t)q->children[index].pidfd, &status, WEXITED | WNOHANG)) {
            if (errno == EINTR) continue;
            return -1;
        }
        if (status.si_pid) {
            if (status.si_pid != q->children[index].pid ||
                (status.si_code != CLD_EXITED && status.si_code != CLD_KILLED && status.si_code != CLD_DUMPED)) return -1;
            q->waited[index] = status; q->children[index].reaped = 1;
            return wq_remaining(q->deadline) < 0 ? -1 : 0;
        }
        struct pollfd p = {q->children[index].pidfd, POLLIN, 0}; int left = wq_remaining(q->deadline);
        if (left < 0 || (poll(&p, 1, left) < 0 && errno != EINTR)) return -1;
    }
}
static int w4_q_zero_wait(w4_q_t *q, int index) {
    return w4_q_wait(q, index) || q->waited[index].si_code != CLD_EXITED || q->waited[index].si_status;
}
static int w4_q_objects(w4_q_t *q, const w4_commit_t *terminal) {
    wq_profile_t current_profile;
    if (wq_remaining(q->deadline) < 0 || wq_chain_check(&q->delegation_chain) ||
        wq_chain_check(&q->custody_chain) ||
        w4_load_profile(q->profile, q->binding.profile_sha256, &current_profile, q->deadline) ||
        memcmp(&current_profile, &q->installed, sizeof(current_profile)) || scope_check(&q->scope, 0)) return -1;
    if (!q->registered) return 0;
    for (size_t i = 0; i < 3; ++i)
        if (wq_publication_check(q->publications[i], &q->registration.publications[i], q->deadline)) return -1;
    if (q->creators[0] < 0 || q->creators[1] < 0) return -1;
    return w4_records(q->custody, q->creators, &q->private_pin, q->creator_pins,
        &q->registration, terminal, &q->registration_pin, terminal ? NULL : &q->empty_pin, q->deadline);
}
static int w4_q_target_member(w4_q_t *q) {
    int fd = openat(q->scope.leaf, "cgroup.procs", O_RDONLY | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK);
    if (fd < 0) return -1;
    wq_identity_t pin;
    char bytes[128] = {0}, expected[128]; int populated;
    int invalid = wq_identity(fd, &pin, 1) ||
        checked_read(fd, &pin, bytes, sizeof(bytes) - 1, q->deadline, 1) < 0;
    int size = snprintf(expected, sizeof(expected), "%llu\n", (unsigned long long)q->context.target_pid);
    if (size <= 0 || strcmp(bytes, expected)) invalid = 1;
    if (close(fd)) invalid = 1;
    return invalid || scope_check(&q->scope, 0) || scope_events(&q->scope, 4, &populated) ||
        populated != 1 || exited(q->target) || w4_q_check(q);
}
static int w4_q_scope_to_role(w4_q_t *q, int channel) {
    int owned[7] = {-1, -1, -1, -1, -1, -1, -1}; int result = -1;
    const char *names[6] = {"cgroup.type", "cgroup.subtree_control", "cgroup.max.depth",
                            "cgroup.max.descendants", "cgroup.events", "cgroup.kill"};
    owned[0] = openat(q->scope.leaf, ".", O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    for (size_t i = 0; i < 6; ++i) {
        owned[i + 1] = openat(q->scope.leaf, names[i],
            (i == 5 ? O_WRONLY : O_RDONLY) | O_NONBLOCK | O_NOFOLLOW | O_CLOEXEC);
        if (owned[i + 1] < 0) goto done;
    }
    if (owned[0] < 0 || wq_fd_distinct(owned, 7) || scope_check(&q->scope, 0)) goto done;
    wq_identity_t current;
    const size_t indexes[6] = {0, 1, 2, 3, 6, 7};
    if (wq_identity(owned[0], &current, 1) || !wq_identity_equal(&current, &q->scope.leaf_pin)) goto done;
    for (size_t i = 0; i < 6; ++i)
        if (wq_identity(owned[i + 1], &current, 1) ||
            !wq_identity_equal(&current, &q->scope.pins[indexes[i]])) goto done;
    wq_message_t m; w4_q_message(q, &m, W4_SCOPE_A, 0, 4);
    if (w4_q_io(q, channel, &m, sizeof(m), owned, 4, 1)) goto done;
    w4_q_message(q, &m, W4_SCOPE_B, 1, 3);
    if (w4_q_io(q, channel, &m, sizeof(m), owned + 4, 3, 1)) goto done;
    result = 0;
done:
    for (size_t i = 0; i < 7; ++i) if (w4_close(&owned[i])) result = -1;
    return result;
}
static void w4_role_seed(w4_role_t *r, w4_q_t *q, uint32_t source) {
    memset(r, 0, sizeof(*r)); r->source = source;
    r->deadline = q->deadline; r->cutoff = q->cutoff; r->c_life = q->lifeline; r->q_life = q->qlife[0];
    r->channel = source == W4_SOURCE_S ? q->qs[1] : q->qg[1];
    r->to_r = source == W4_SOURCE_S ? q->sr[0] : q->gr[0];
    r->s_life = q->slife[0]; r->g_life = q->glife[0];
    r->own_life = source == W4_SOURCE_S ? q->slife[1] : q->glife[1];
    r->scope.leaf = r->scope.delegation = r->target = -1;
    for (size_t i = 0; i < 8; ++i) r->scope.files[i] = -1;
    for (size_t i = 0; i < 3; ++i) r->peers[i] = r->publications[i] = -1;
}
static int w4_q_children(w4_q_t *q) {
    int *pairs[] = {q->qs, q->qg, q->qr, q->sr, q->gr};
    for (size_t i = 0; i < 5; ++i)
        if (socketpair(AF_UNIX, SOCK_SEQPACKET | SOCK_NONBLOCK | SOCK_CLOEXEC, 0, pairs[i])) return -1;
    if (pipe2(q->qlife, O_NONBLOCK | O_CLOEXEC) || pipe2(q->slife, O_NONBLOCK | O_CLOEXEC) ||
        pipe2(q->glife, O_NONBLOCK | O_CLOEXEC)) return -1;
    for (size_t i = 0; i < 3; ++i) {
        int cloned = child_clone(&q->children[i]);
        if (cloned < 0) return -1;
        if (!cloned) {
            if (i < 2) {
                w4_role_t role; w4_role_seed(&role, q, i ? W4_SOURCE_G : W4_SOURCE_S);
                int keep[6] = {role.channel, role.to_r, role.c_life, role.q_life, role.own_life,
                                i ? role.s_life : role.g_life};
                if (w4_keep(keep, 6) || wq_socket(role.channel) || wq_socket(role.to_r) ||
                    pipe_reader(role.c_life) || pipe_reader(role.q_life)) _exit(W4_FAILURE);
                if (i) w4_guardian(role, &q->binding);
                w4_primary(role, &q->binding);
            }
            int keep[4] = {q->qr[1], q->sr[1], q->gr[1], q->qlife[0]};
            if (w4_keep(keep, 4) || wq_socket(q->qr[1]) || wq_socket(q->sr[1]) ||
                wq_socket(q->gr[1]) || pipe_reader(q->qlife[0])) _exit(W4_FAILURE);
            w4_receiver(q->qr[1], q->sr[1], q->gr[1], q->qlife[0], &q->binding);
        }
    }
    int *close_slots[] = {&q->qs[1], &q->qg[1], &q->qr[1], &q->sr[0], &q->sr[1],
                          &q->gr[0], &q->gr[1], &q->slife[1], &q->glife[1]};
    for (size_t i = 0; i < sizeof(close_slots) / sizeof(close_slots[0]); ++i)
        if (w4_close(close_slots[i])) return -1;
    if (w4_q_scope_to_role(q, q->qs[0]) || w4_q_scope_to_role(q, q->qg[0])) return -1;
    wq_message_t m;
    int peers[3] = {q->bootstrap, q->children[1].pidfd, q->children[2].pidfd};
    w4_q_message(q, &m, W4_S_PEERS, 2, 3);
    if (w4_q_io(q, q->qs[0], &m, sizeof(m), peers, 3, 1)) return -1;
    peers[1] = q->children[0].pidfd;
    w4_q_message(q, &m, W4_G_PEERS, 2, 3);
    if (w4_q_io(q, q->qg[0], &m, sizeof(m), peers, 3, 1)) return -1;
    w4_q_message(q, &m, W4_R_INIT, 0, 1);
    if (w4_q_io(q, q->qr[0], &m, sizeof(m), &q->custody, 1, 1)) return -1;
    int channels[3] = {q->qs[0], q->qg[0], q->qr[0]};
    for (size_t i = 0; i < 3; ++i) {
        if (w4_q_io(q, channels[i], &m, sizeof(m), NULL, 0, 0) ||
            w4_check(&m, &q->binding, W4_READY, i < 2 ? 3 : 1, 0) ||
            !w4_context_equal(&m, &q->context)) return -1;
    }
    return 0;
}
static int w4_q_creator_roles(w4_q_t *q) {
    int roles[] = {q->profile, q->delegation, q->controller, q->enrollment, q->lifecycle,
        q->lifeline, q->image, q->custody, q->bootstrap, q->target, q->scope.leaf,
        q->publications[0], q->publications[1], q->publications[2], q->qs[0], q->qg[0], q->qr[0],
        q->qlife[0], q->qlife[1], q->slife[0], q->glife[0], q->children[0].pidfd,
        q->children[1].pidfd, q->children[2].pidfd, 0, 1, 2};
    if (wq_fd_distinct(q->creators, 2)) return -1;
    for (size_t i = 0; i < sizeof(roles) / sizeof(roles[0]); ++i)
        if (v3_creator_role(q->creators, roles[i])) return -1;
    for (size_t i = 0; i < 8; ++i) if (v3_creator_role(q->creators, q->scope.files[i])) return -1;
    for (size_t i = 0; i < q->delegation_chain.count; ++i)
        if (v3_creator_role(q->creators, q->delegation_chain.fds[i])) return -1;
    for (size_t i = 0; i < q->custody_chain.count; ++i)
        if (v3_creator_role(q->creators, q->custody_chain.fds[i])) return -1;
    return 0;
}
static int w4_q_registration(w4_q_t *q) {
    wq_message_t m; int scope[2] = {q->scope.leaf, q->qlife[0]};
    w4_q_message(q, &m, W4_B_SCOPE, 1, 2);
    if (w4_q_io(q, q->enrollment, &m, sizeof(m), scope, 2, 1) || w4_close(&q->qlife[0]) ||
        w4_q_io(q, q->enrollment, &m, sizeof(m), &q->target, 1, 0) ||
        w4_check(&m, &q->binding, W4_ENROLLED, 1, 1) ||
        !wq_identity_equal(&m.scope, &q->scope.leaf_pin) || !m.target_pid || m.target_pid > INT_MAX ||
        zero(m.publications, sizeof(m.publications)) ||
        syscall(SYS_pidfd_send_signal, q->target, 0, NULL, 0) || w4_q_received_roles(q, &q->target, 1)) return -1;
    q->context.target_pid = m.target_pid;
    if (w4_q_target_member(q)) return -1;
    w4_q_message(q, &m, W4_ENROLL_ACK, 2, 0);
    if (w4_q_io(q, q->enrollment, &m, sizeof(m), NULL, 0, 1) || w4_close(&q->enrollment)) return -1;
    w4_q_message(q, &m, W4_C_ENROLLED, 1, 0);
    if (w4_q_io(q, q->controller, &m, sizeof(m), NULL, 0, 1) ||
        w4_q_io(q, q->controller, &m, sizeof(m), q->publications, 3, 0) ||
        w4_check(&m, &q->binding, W4_REGISTER, 1, 3) ||
        !wq_identity_equal(&m.scope, &q->scope.leaf_pin) || m.target_pid != q->context.target_pid ||
        !zero(m.publications, sizeof(m.publications)) || w4_q_received_roles(q, q->publications, 3)) return -1;
    q->context = m;
    for (size_t i = 0; i < 3; ++i)
        if (wq_publication_check(q->publications[i], &m.publications[i], q->deadline)) return -1;
    int s_rights[4] = {q->target, q->publications[0], q->publications[1], q->publications[2]};
    w4_q_message(q, &m, W4_S_CONTEXT, 5, 4);
    if (w4_q_io(q, q->qs[0], &m, sizeof(m), s_rights, 4, 1)) return -1;
    w4_q_message(q, &m, W4_G_CONTEXT, 5, 0);
    if (w4_q_io(q, q->qg[0], &m, sizeof(m), NULL, 0, 1)) return -1;
    int channels[2] = {q->qs[0], q->qg[0]};
    for (size_t i = 0; i < 2; ++i)
        if (w4_q_io(q, channels[i], &m, sizeof(m), NULL, 0, 0) ||
            w4_check(&m, &q->binding, W4_CONTEXT_ACK, 5, 0) || !w4_context_equal(&m, &q->context)) return -1;
    int peer_rights[3] = {q->children[0].pidfd, q->children[1].pidfd, q->children[2].pidfd};
    w4_q_message(q, &m, W4_B_PEERS, 2, 3);
    if (w4_q_io(q, q->lifecycle, &m, sizeof(m), peer_rights, 3, 1) ||
        w4_q_io(q, q->lifecycle, &m, sizeof(m), NULL, 0, 0) ||
        w4_check(&m, &q->binding, W4_B_PEER_ACK, 2, 0) || !w4_context_equal(&m, &q->context)) return -1;
    w4_q_message(q, &q->registration, W4_R_REGISTER, 1, 0);
    if (w4_q_io(q, q->qr[0], &q->registration, sizeof(q->registration), NULL, 0, 1) ||
        w4_q_io(q, q->qr[0], &m, sizeof(m), q->creators, 2, 0)) return -1;
    if (w4_check(&m, &q->binding, W4_R_CREATORS, 1, 2) || !w4_context_equal(&m, &q->context) ||
        w4_q_creator_roles(q) || wq_identity(q->creators[0], &q->creator_pins[0], 0) ||
        wq_identity(q->creators[1], &q->creator_pins[1], 0) || fstat(q->creators[0], &q->registration_pin) ||
        fstat(q->creators[1], &q->empty_pin)) return -1;
    q->registered = 1;
    if (w4_q_objects(q, NULL)) return -1;
    w4_q_message(q, &m, W4_C_CREATORS, 2, 2);
    if (w4_q_io(q, q->controller, &m, sizeof(m), q->creators, 2, 1) ||
        w4_q_io(q, q->controller, &m, sizeof(m), NULL, 0, 0) ||
        w4_check(&m, &q->binding, W4_CREATORS_ADOPTED, 2, 0) ||
        !w4_context_equal(&m, &q->context) || w4_q_objects(q, NULL)) return -1;
    w4_q_message(q, &m, W4_REGISTERED_READY, 2, 0);
    return w4_q_io(q, q->controller, &m, sizeof(m), NULL, 0, 1);
}
static int w4_q_persist(w4_q_t *q, const w4_proposal_t *proposal, int normal, uint32_t facts) {
    if (q->locked || w4_q_objects(q, NULL)) return -1;
    memset(&q->commit, 0, sizeof(q->commit));
    w4_q_message(q, &q->commit.context, normal ? W4_COMMIT_NORMAL : W4_COMMIT_ABNORMAL, 2, 0);
    q->commit.decision = normal ? 1 : 2; q->commit.reason = normal ? W4_OK : q->reason;
    q->commit.decision_sequence = 1; q->commit.facts = facts;
    q->commit.proposal = *proposal;
    if (q->children[0].reaped) { q->commit.facts |= W4_S_WAIT;
        q->commit.s_code = (uint32_t)q->waited[0].si_code; q->commit.s_status = (uint32_t)q->waited[0].si_status; }
    if (q->children[1].reaped) { q->commit.facts |= W4_G_WAIT;
        q->commit.g_code = (uint32_t)q->waited[1].si_code; q->commit.g_status = (uint32_t)q->waited[1].si_status; }
    uint64_t now;
    if (wq_now(&now)) return -1;
    q->commit.committed_ns = now;
    if (w4_commit_check(&q->commit, &q->registration)) return -1;
    q->locked = 1; q->retiring[2] = 1;
    if (w4_q_io(q, q->qr[0], &q->commit, sizeof(q->commit), NULL, 0, 1)) return -1;
    q->sent = 1;
    w4_commit_t ack, expected = q->commit; expected.context.operation = W4_ACK;
    if (w4_q_io(q, q->qr[0], &ack, sizeof(ack), NULL, 0, 0) || memcmp(&ack, &expected, sizeof(ack)) ||
        w4_q_zero_wait(q, 2) || w4_q_objects(q, &q->commit)) return -1;
    return 0;
}
static int w4_q_result(w4_q_t *q, int normal) {
    w4_result_t result = {0}; w4_q_message(q, &result.context, normal ? W4_RESULT : W4_ABNORMAL_RESULT, 4, 0);
    result.commit = q->commit; result.facts = 7;
    result.r_code = (uint32_t)q->waited[2].si_code; result.r_status = (uint32_t)q->waited[2].si_status;
    uint64_t now; if (wq_now(&now)) return -1; result.observed_ns = now;
    if (w4_q_io(q, q->controller, &result, sizeof(result), NULL, 0, 1)) return -1;
    if (normal) {
        q->bootstrap_finishing = 1;
        if (w4_q_io(q, q->lifecycle, &result, sizeof(result), NULL, 0, 1)) return -1;
    }
    return 0;
}
static int w4_q_run(w4_q_t *q) {
    wq_message_t m;
    if (w4_q_io(q, q->controller, &m, sizeof(m), &q->bootstrap, 1, 0) ||
        w4_check(&m, &m.binding, W4_INIT, 0, 1) || m.binding.deadline_ns != q->deadline ||
        zero(&m.scope, sizeof(m.scope)) || m.target_pid || zero(m.publications, sizeof(m.publications))) return -1;
    q->binding = m.binding; q->context = m; w4_change(&q->context, W4_INIT, 0, 0);
    if (w4_q_received_roles(q, &q->bootstrap, 1)) return -1;
    char digest[65], private_path[WQ_PATH_BYTES];
    char link[80]; snprintf(link, sizeof(link), "/proc/self/fd/%d", q->custody);
    ssize_t length = readlink(link, private_path, sizeof(private_path) - 1);
    if (length <= 0 || length >= (ssize_t)sizeof(private_path) - 1) return -1;
    private_path[length] = 0;
    if (w4_load_profile(q->profile, q->binding.profile_sha256, &q->installed, q->deadline) ||
        wq_profile_binding(&q->installed, &q->binding) || wq_sealed(q->image) ||
        wq_hash_fd(q->image, digest, q->deadline) || memcmp(digest, q->binding.supervisor_sha256, 65) ||
        wq_chain_open(q->installed.delegation_path, &q->delegation_chain, 1) ||
        !wq_identity_equal(&q->delegation_chain.pins[q->delegation_chain.count - 1], &q->installed.delegation) ||
        private_directory(q->custody, &q->private_pin) || private_no_acl(q->custody) ||
        wq_chain_open(private_path, &q->custody_chain, 1) ||
        !wq_identity_equal(&q->custody_chain.pins[q->custody_chain.count - 1], &q->private_pin) ||
        syscall(SYS_pidfd_send_signal, q->bootstrap, 0, NULL, 0) ||
        scope_create(&q->scope, q->delegation, &q->installed.delegation, &q->binding)) return -1;
    q->context.scope = q->scope.leaf_pin;
    if (w4_q_children(q) || w4_q_registration(q) || w4_q_objects(q, NULL)) return -1;
    if (w4_q_io(q, q->controller, &m, sizeof(m), NULL, 0, 0) ||
        w4_check(&m, &q->binding, W4_C_RELEASE, 3, 0) || !w4_context_equal(&m, &q->context) ||
        w4_q_io(q, q->lifecycle, &m, sizeof(m), NULL, 0, 0) ||
        w4_check(&m, &q->binding, W4_B_RELEASE, 3, 0) || !w4_context_equal(&m, &q->context) ||
        w4_q_objects(q, NULL) || w4_q_target_member(q)) return -1;
    q->released = 1;
    w4_q_message(q, &m, W4_PERMIT, 3, 0);
    if (w4_q_io(q, q->lifecycle, &m, sizeof(m), NULL, 0, 1) ||
        w4_q_io(q, q->lifecycle, &m, sizeof(m), NULL, 0, 0) ||
        w4_check(&m, &q->binding, W4_B_DONE, 4, 0) || !w4_context_equal(&m, &q->context)) return -1;
    for (;;) {
        int populated;
        if (w4_q_check(q) || w4_q_objects(q, NULL) || scope_events(&q->scope, 4, &populated)) return -1;
        if (!populated && exited(q->target) == 1) break;
        struct pollfd p = {q->scope.files[4], POLLPRI | POLLERR, 0}; int left = wq_remaining(q->deadline);
        if (left < 0 || (poll(&p, 1, left) < 0 && errno != EINTR)) return -1;
    }
    q->normal_draining = 1;
    w4_q_message(q, &m, W4_S_DONE, 6, 0);
    w4_proposal_t proposal, response;
    if (w4_q_io(q, q->qs[0], &m, sizeof(m), NULL, 0, 1) ||
        w4_q_io(q, q->qs[0], &proposal, sizeof(proposal), NULL, 0, 0) ||
        w4_proposal_check(&proposal, &q->registration, W4_SOURCE_S)) return -1;
    response = proposal; w4_change(&response.context, W4_S_PREPARE, 8, 0);
    if (w4_q_io(q, q->qs[0], &response, sizeof(response), NULL, 0, 1) ||
        w4_q_io(q, q->qs[0], &response, sizeof(response), NULL, 0, 0) ||
        w4_bound_proposal(&response, &proposal, W4_S_PREPARED, 8)) return -1;
    q->retiring[1] = 1;
    response = proposal; w4_change(&response.context, W4_G_RETIRE_NORMAL, 8, 0);
    if (w4_q_io(q, q->qg[0], &response, sizeof(response), NULL, 0, 1) || w4_q_zero_wait(q, 1)) return -1;
    q->retiring[0] = 1;
    response = proposal; w4_change(&response.context, W4_S_EXIT_NORMAL, 9, 0);
    if (w4_q_io(q, q->qs[0], &response, sizeof(response), NULL, 0, 1) || w4_q_zero_wait(q, 0)) return -1;
    int populated;
    if (w4_q_objects(q, NULL) || scope_events(&q->scope, 4, &populated) || populated || live(q->lifeline) ||
        w4_q_persist(q, &proposal, 1, W4_EMPTY | W4_T_EXIT) || w4_q_result(q, 1)) return -1;
    return 0;
}
static void w4_q_abnormal(w4_q_t *q) {
    q->abnormal = 1;
    if (!q->reason) q->reason = W4_PROTOCOL;
    /* Original stop precedes any R storage interaction. G is independently
     * armed even while this coordinator is in a syscall. */
    if (q->children[0].pidfd >= 0 && !q->children[0].reaped) {
        int ignored = (int)syscall(SYS_pidfd_send_signal, q->children[0].pidfd, SIGKILL, NULL, 0); (void)ignored;
        (void)w4_q_wait(q, 0);
    }
    uint32_t facts = W4_STOP;
    if (q->bootstrap >= 0) {
        int ignored = (int)syscall(SYS_pidfd_send_signal, q->bootstrap, SIGKILL, NULL, 0); (void)ignored;
        if (q->scope.leaf >= 0) facts = emergency_stop_observed(&q->scope, q->bootstrap, 0) & 7u;
    }
    if (!q->registered || q->locked || wq_remaining(q->deadline) < 0) goto cleanup;
    w4_command_t command = {0}; w4_q_message(q, &command.context, W4_G_STOP, 6, 0); command.reason = q->reason;
    w4_proposal_t proposal; int original_g = 0;
    if (q->children[1].pidfd >= 0 && !q->children[1].reaped && exited(q->children[1].pidfd) == 0 &&
        !w4_q_io(q, q->qg[0], &command, sizeof(command), NULL, 0, 1) &&
        !w4_q_io(q, q->qg[0], &proposal, sizeof(proposal), NULL, 0, 0) &&
        !w4_proposal_check(&proposal, &q->registration, W4_SOURCE_G)) {
        w4_proposal_t retire = proposal; w4_change(&retire.context, W4_G_RETIRE_ABNORMAL, 8, 0);
        if (!w4_q_io(q, q->qg[0], &retire, sizeof(retire), NULL, 0, 1) && !w4_q_wait(q, 1)) original_g = 1;
    }
    if (!original_g) {
        if (q->children[1].pidfd >= 0 && !q->children[1].reaped) {
            int ignored = (int)syscall(SYS_pidfd_send_signal, q->children[1].pidfd, SIGKILL, NULL, 0); (void)ignored;
            (void)w4_q_wait(q, 1);
        }
        memset(&proposal, 0, sizeof(proposal)); w4_q_message(q, &proposal.context, W4_PROPOSAL, 7, 0);
        proposal.source = W4_SOURCE_Q; proposal.trigger = q->reason == W4_C_LOST ? 1u :
            q->reason == W4_DEADLINE ? 2u : q->reason == W4_R_FAULT ? 3u : q->reason == W4_S_LOST ? 5u :
            q->reason == W4_G_LOST ? 6u : 4u; proposal.facts = facts;
        uint64_t now; if (wq_now(&now)) goto cleanup; proposal.observed_ns = now;
        if (w4_q_io(q, q->qr[0], &proposal, sizeof(proposal), NULL, 0, 1)) goto cleanup;
    }
    if (q->children[0].reaped && q->children[1].reaped &&
        !w4_q_persist(q, &proposal, 0, facts) && !live(q->lifeline)) (void)w4_q_result(q, 0);
cleanup:
    for (int i = 0; i < 3; ++i) if (q->children[i].pidfd >= 0 && !q->children[i].reaped) {
        int ignored = (int)syscall(SYS_pidfd_send_signal, q->children[i].pidfd, SIGKILL, NULL, 0); (void)ignored;
        (void)w4_q_wait(q, i);
    }
}
static int w4_coordinator_main(int argc, char **argv) {
    if (argc != 20 || strcmp(argv[1], "--successor-coordinator-v4")) return 64;
    const char *names[9] = {"--profile-fd", "--delegation-fd", "--controller-fd", "--enrollment-fd",
        "--lifecycle-fd", "--controller-lifeline-fd", "--image-fd", "--custody-dir-fd", "--deadline-monotonic-ns"};
    w4_q_t q; memset(&q, 0, sizeof(q));
    int *fields[8] = {&q.profile, &q.delegation, &q.controller, &q.enrollment, &q.lifecycle, &q.lifeline, &q.image, &q.custody};
    q.bootstrap = q.target = q.scope.leaf = q.scope.delegation = -1;
    int *pairs[] = {q.qs, q.qg, q.qr, q.sr, q.gr, q.qlife, q.slife, q.glife};
    for (size_t i = 0; i < 8; ++i) pairs[i][0] = pairs[i][1] = -1;
    for (size_t i = 0; i < 3; ++i) { q.children[i].pidfd = -1; q.publications[i] = -1; }
    q.creators[0] = q.creators[1] = -1;
    for (size_t i = 0; i < 8; ++i) q.scope.files[i] = -1;
    for (size_t i = 0; i < 9; ++i) {
        if (strcmp(argv[2 + 2 * i], names[i])) return 64;
        if (i < 8 ? fd_arg(argv[3 + 2 * i], fields[i], 0) : number(argv[3 + 2 * i], UINT64_MAX, &q.deadline)) return 64;
    }
    uint64_t now;
    int required[8]; for (size_t i = 0; i < 8; ++i) required[i] = *fields[i];
    if (wq_root_identity() || signals_ready() || wq_fd_distinct(required, 8) ||
        wq_socket(q.controller) || wq_socket(q.enrollment) || wq_socket(q.lifecycle) || pipe_reader(q.lifeline) ||
        getpgrp() != getpid() || getsid(0) != getpid() ||
        q.deadline <= W4_RESERVE_NS || wq_now(&now) || now >= q.deadline - W4_RESERVE_NS) return 64;
    q.cutoff = q.deadline - W4_RESERVE_NS;
    if (w4_resource_enter(fields, 8, NULL, 0)) return W4_FAILURE;
    int result = w4_q_run(&q);
    if (result) w4_q_abnormal(&q);
    return result ? W4_FAILURE : 0;
}
static int w4_publisher(int profile_fd, int execution, int controller, int image, uint64_t deadline) {
    int *fields[4] = {&profile_fd, &execution, &controller, &image};
    if (w4_resource_enter(fields, 4, NULL, 0)) return -1;
    wq_message_t request;
    for (;;) {
        if (wq_remaining(deadline) < 0)
            return -1;
        if (!w4_receive(controller, &request, sizeof(request), NULL, 0, deadline))
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
    if (w4_check(&request, &request.binding, W4_PUBLISH, 0, 0) ||
        memcmp(request.binding.launch_sha256, request.binding.intent_sha256, 65) ||
        request.binding.deadline_ns != deadline || zero(&request.scope, sizeof(request.scope)) ||
        request.target_pid || zero(request.publications, sizeof(request.publications)) ||
        w4_load_profile(profile_fd, request.binding.profile_sha256, &profile, deadline) ||
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
    w4_init(&response, &request.binding, W4_PUBLISHED, 1, 3);
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
        if (!w4_send(controller, &response, sizeof(response), rights, 3)) {
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
#endif
