/* Explicit default-off v4. No v1/v2/v3 frame is admitted by these functions. */
#ifndef LUNAR_NATIVE_WHOLE_SCOPE_SUCCESSOR_PROTOCOL_H
#define LUNAR_NATIVE_WHOLE_SCOPE_SUCCESSOR_PROTOCOL_H
#include "native_whole_scope_platform.h"
#include <signal.h>
#include <sys/wait.h>

#define W4_MAGIC 0x3451574cu
#define W4_PROFILE_MAGIC 0x3450574cu
#define W4_VERSION 4u
#define W4_PROFILE_PATH "/etc/lunar-evolution/whole-scope-successor-v4.profile"
#define W4_RESERVE_NS 250000000ULL
#define W4_FD_LIMIT 96u
#define W4_FAILURE 78
enum w4_operation {
    W4_INIT = 64, W4_SCOPE_A, W4_SCOPE_B, W4_S_PEERS, W4_G_PEERS, W4_R_INIT,
    W4_READY, W4_B_SCOPE, W4_ENROLLED, W4_ENROLL_ACK, W4_C_ENROLLED,
    W4_REGISTER, W4_S_CONTEXT, W4_G_CONTEXT, W4_CONTEXT_ACK, W4_R_REGISTER,
    W4_R_CREATORS, W4_C_CREATORS, W4_CREATORS_ADOPTED, W4_REGISTERED_READY,
    W4_B_PEERS, W4_B_PEER_ACK, W4_C_RELEASE, W4_B_RELEASE, W4_PERMIT,
    W4_B_DONE, W4_S_DONE, W4_PROPOSAL, W4_S_PREPARE, W4_S_PREPARED,
    W4_G_RETIRE_NORMAL, W4_S_EXIT_NORMAL, W4_G_STOP, W4_G_RETIRE_ABNORMAL,
    W4_COMMIT_NORMAL, W4_COMMIT_ABNORMAL, W4_ACK, W4_RESULT,
    W4_ABNORMAL_RESULT, W4_CANCEL, W4_ROLE_CANCEL, W4_PUBLISH, W4_PUBLISHED
};
enum w4_reason { W4_OK, W4_C_LOST, W4_DEADLINE, W4_R_FAULT, W4_PROTOCOL,
                 W4_S_LOST, W4_G_LOST, W4_C_CANCEL };
enum w4_source { W4_SOURCE_S = 1, W4_SOURCE_G = 2, W4_SOURCE_Q = 3 };
#define W4_STOP 1u
#define W4_EMPTY 2u
#define W4_B_EXIT 4u
#define W4_S_WAIT 8u
#define W4_G_WAIT 16u
#define W4_T_EXIT 32u
#define W4_NORMAL_Q_FACTS 58u
#define W4_SOURCE_T_EXIT 8u
typedef struct __attribute__((packed)) {
    wq_message_t context;
    uint32_t reason, reserved;
} w4_command_t;
typedef struct __attribute__((packed)) {
    wq_message_t context;
    uint32_t source, trigger, facts, reserved;
    uint64_t observed_ns;
} w4_proposal_t;
typedef struct __attribute__((packed)) {
    wq_message_t context;
    uint32_t decision, reason, decision_sequence, facts;
    uint64_t committed_ns;
    uint32_t s_code, s_status, g_code, g_status;
    w4_proposal_t proposal;
} w4_commit_t;
typedef struct __attribute__((packed)) {
    wq_message_t context;
    w4_commit_t commit;
    uint32_t facts, r_code, r_status, reserved;
    uint64_t observed_ns;
} w4_result_t;
_Static_assert(sizeof(w4_command_t) == 933, "v4 command ABI");
_Static_assert(sizeof(w4_proposal_t) == 949, "v4 proposal ABI");
_Static_assert(sizeof(w4_commit_t) == 1914, "v4 commit/ACK ABI");
_Static_assert(sizeof(w4_result_t) == 2863, "v4 result ABI");
#define W4_MAX_PACKET sizeof(w4_result_t)

/* Relocate the acquired description itself; never reopen an object by name. */
static inline int w4_high_fd(int actual) {
    if (actual < 0 || actual > 2) return actual;
    int relocated = fcntl(actual, F_DUPFD_CLOEXEC, 3);
    int saved = errno;
    if (close(actual)) {
        if (relocated >= 0) close(relocated);
        return -1;
    }
    errno = saved;
    return relocated;
}
static inline int w4_no_acl(int fd) {
    unsigned char value[128];
    if (fgetxattr(fd, "system.posix_acl_access", value, sizeof(value)) >= 0 || errno != ENODATA) return -1;
    return fgetxattr(fd, "system.posix_acl_default", value, sizeof(value)) >= 0 || errno != ENODATA ? -1 : 0;
}

static inline void w4_init(wq_message_t *m, const wq_binding_t *b, uint32_t op,
                           uint32_t seq, uint32_t count) {
    wq_message_init(m, b, op, seq, count);
    m->magic = W4_MAGIC;
    m->version = W4_VERSION;
}
static inline void w4_change(wq_message_t *m, uint32_t op, uint32_t seq, uint32_t count) {
    m->operation = op; m->sequence = seq; m->fd_count = count;
}
static inline int w4_check(const wq_message_t *m, const wq_binding_t *b,
                            uint32_t op, uint32_t seq, uint32_t count) {
    return m->magic != W4_MAGIC || m->version != W4_VERSION || m->reserved ||
           m->operation != op || m->sequence != seq || m->fd_count != count ||
           memcmp(&m->binding, b, sizeof(*b)) || wq_binding_valid(b);
}
static inline int w4_context_equal(const wq_message_t *a, const wq_message_t *b) {
    return !memcmp(&a->binding, &b->binding, sizeof(a->binding)) &&
           !memcmp(&a->scope, &b->scope, sizeof(a->scope)) &&
           a->target_pid == b->target_pid &&
           !memcmp(a->publications, b->publications, sizeof(a->publications));
}
static inline int w4_send(int fd, const void *packet, size_t bytes,
                          const int *rights, size_t count) {
    const wq_message_t *m = packet;
    if (bytes < sizeof(*m) || bytes > W4_MAX_PACKET || count > WQ_MAX_RIGHTS ||
        count != m->fd_count || (count && !rights) || wq_remaining(m->binding.deadline_ns) < 0) {
        errno = EPROTO; return -1;
    }
    struct iovec vector = {(void *)packet, bytes};
    char ancillary[CMSG_SPACE(sizeof(int) * WQ_MAX_RIGHTS)];
    struct msghdr h = {0}; h.msg_iov = &vector; h.msg_iovlen = 1;
    if (count) {
        memset(ancillary, 0, sizeof(ancillary)); h.msg_control = ancillary;
        h.msg_controllen = CMSG_SPACE(sizeof(int) * count);
        struct cmsghdr *c = CMSG_FIRSTHDR(&h);
        c->cmsg_level = SOL_SOCKET; c->cmsg_type = SCM_RIGHTS;
        c->cmsg_len = CMSG_LEN(sizeof(int) * count); memcpy(CMSG_DATA(c), rights, count * sizeof(int));
    }
    ssize_t got = sendmsg(fd, &h, MSG_DONTWAIT | MSG_NOSIGNAL);
    if (got < 0) return -1;
    if (got != (ssize_t)bytes) { errno = EPROTO; return -1; }
    return wq_remaining(m->binding.deadline_ns) < 0 ? -1 : 0;
}
/* Incoming numbers become owned here, even when a later cmsg/header refuses. */
static inline int w4_receive(int fd, void *packet, size_t bytes, int *rights,
                             size_t expected, uint64_t deadline) {
    if (bytes < sizeof(wq_message_t) || bytes > W4_MAX_PACKET || expected > WQ_MAX_RIGHTS ||
        (expected && !rights) || wq_remaining(deadline) < 0) { errno = EPROTO; return -1; }
    unsigned char raw[sizeof(w4_result_t) + 1];
    char ancillary[CMSG_SPACE(sizeof(int) * WQ_MAX_RIGHTS)];
    struct iovec v = {raw, sizeof(raw)}; struct msghdr h = {0};
    h.msg_iov = &v; h.msg_iovlen = 1; h.msg_control = ancillary; h.msg_controllen = sizeof(ancillary);
    ssize_t got = recvmsg(fd, &h, MSG_DONTWAIT | MSG_CMSG_CLOEXEC);
    if (got < 0) return -1;
    int acquired[WQ_MAX_RIGHTS], invalid = 0; size_t count = 0;
    for (size_t i = 0; i < WQ_MAX_RIGHTS; ++i) acquired[i] = -1;
    for (struct cmsghdr *c = CMSG_FIRSTHDR(&h); c; c = CMSG_NXTHDR(&h, c)) {
        if (c->cmsg_len < CMSG_LEN(0) || c->cmsg_level != SOL_SOCKET || c->cmsg_type != SCM_RIGHTS ||
            (c->cmsg_len - CMSG_LEN(0)) % sizeof(int)) { invalid = 1; continue; }
        size_t n = (c->cmsg_len - CMSG_LEN(0)) / sizeof(int);
        for (size_t i = 0; i < n; ++i) {
            int actual; memcpy(&actual, (unsigned char *)CMSG_DATA(c) + i * sizeof(int), sizeof(actual));
            if (count < WQ_MAX_RIGHTS) {
                acquired[count] = w4_high_fd(actual);
                if (acquired[count] < 0) invalid = 1;
                ++count;
            }
            else { close(actual); invalid = 1; }
        }
    }
    if (got != (ssize_t)bytes || h.msg_flags & (MSG_TRUNC | MSG_CTRUNC) || count != expected ||
        invalid || wq_remaining(deadline) < 0) invalid = 1;
    if (!invalid) {
        memcpy(packet, raw, bytes);
        const wq_message_t *m = packet;
        if (m->magic != W4_MAGIC || m->version != W4_VERSION || m->reserved || m->fd_count != expected ||
            m->binding.deadline_ns != deadline || wq_binding_valid(&m->binding)) invalid = 1;
    }
    if (invalid) {
        for (size_t i = 0; i < count; ++i) if (acquired[i] >= 0) close(acquired[i]);
        errno = EPROTO; return -1;
    }
    for (size_t i = 0; i < count; ++i) rights[i] = acquired[i];
    return 0;
}
static inline int w4_proposal_check(const w4_proposal_t *p, const wq_message_t *registration,
                                    uint32_t source) {
    if (w4_check(&p->context, &registration->binding, W4_PROPOSAL, 7, 0) ||
        !w4_context_equal(&p->context, registration) || p->source != source || p->reserved ||
        source < W4_SOURCE_S || source > W4_SOURCE_Q ||
        p->trigger > 8 || p->facts & ~15u || !p->observed_ns ||
        p->observed_ns >= registration->binding.deadline_ns) return -1;
    if (source == W4_SOURCE_S) return p->trigger || p->facts != 10u;
    return !(p->facts & W4_STOP) || !p->trigger ||
           ((p->facts & W4_EMPTY) && !(p->facts & W4_B_EXIT));
}
static inline int w4_wait_fields(uint32_t facts, uint32_t bit, uint32_t code, uint32_t status) {
    if (!(facts & bit)) return code || status;
    if (code == CLD_EXITED) return status > 255;
    return (code != CLD_KILLED && code != CLD_DUMPED) || !status || status >= NSIG;
}
static inline int w4_commit_check(const w4_commit_t *c, const wq_message_t *registration) {
    uint32_t op = c->decision == 1 ? W4_COMMIT_NORMAL : W4_COMMIT_ABNORMAL;
    if ((c->decision != 1 && c->decision != 2) ||
        w4_check(&c->context, &registration->binding, op, 2, 0) ||
        !w4_context_equal(&c->context, registration) || c->decision_sequence != 1 ||
        c->facts & ~63u || !c->committed_ns || c->committed_ns >= registration->binding.deadline_ns ||
        c->proposal.observed_ns > c->committed_ns ||
        w4_wait_fields(c->facts, W4_S_WAIT, c->s_code, c->s_status) ||
        w4_wait_fields(c->facts, W4_G_WAIT, c->g_code, c->g_status) ||
        w4_proposal_check(&c->proposal, registration, c->proposal.source)) return -1;
    if (c->decision == 1) return c->reason || c->proposal.source != W4_SOURCE_S ||
        c->facts != W4_NORMAL_Q_FACTS || c->s_code != CLD_EXITED || c->s_status ||
        c->g_code != CLD_EXITED || c->g_status;
    return c->reason < W4_C_LOST || c->reason > W4_C_CANCEL || !(c->facts & W4_STOP) ||
           (c->proposal.source != W4_SOURCE_G && c->proposal.source != W4_SOURCE_Q) ||
           ((c->facts & W4_EMPTY) && !(c->facts & W4_B_EXIT));
}

/* Independent fixed v4 installation parser; no rewrite to a v1 header. */
static inline int w4_load_profile(int fd, const char expected[65], wq_profile_t *p,
                                   uint64_t deadline) {
    if (wq_root_identity() || setgroups(0, NULL) || getgroups(0, NULL) ||
        wq_digest(expected) || wq_sealed(fd)) return -1;
    char digest[65]; struct stat info;
    if (wq_hash_fd(fd, digest, deadline) || memcmp(digest, expected, 65) || fstat(fd, &info) ||
        info.st_size != (off_t)sizeof(*p) || pread(fd, p, sizeof(*p), 0) != (ssize_t)sizeof(*p)) return -1;
    wq_chain_t chain;
    if (wq_chain_open(W4_PROFILE_PATH, &chain, 0)) return -1;
    int original = chain.fds[chain.count - 1]; struct stat source;
    int invalid = fstat(original, &source) || !S_ISREG(source.st_mode) || source.st_uid || source.st_gid ||
        (source.st_mode & 07777) != 0600 || source.st_nlink != 1 || w4_no_acl(original) ||
        wq_hash_fd(original, digest, deadline) || memcmp(digest, expected, 65) || wq_chain_check(&chain);
    wq_chain_close(&chain);
    if (invalid || p->magic != W4_PROFILE_MAGIC || p->version != W4_VERSION || p->size != sizeof(*p) ||
        p->flags != 1 || !p->candidate_uid || p->candidate_uid == UINT_MAX ||
        !p->candidate_gid || p->candidate_gid == UINT_MAX || p->group_count > WQ_MAX_GROUPS ||
        !p->readonly_count || p->readonly_count > WQ_MAX_ROOTS ||
        wq_digest(p->bootstrap_sha256) || wq_digest(p->supervisor_sha256) || wq_profile_namespaces(p)) return -1;
    for (size_t i = 0; i < WQ_MAX_GROUPS; ++i)
        if (i < p->group_count ? (!p->groups[i] || p->groups[i] == UINT_MAX ||
            (i && p->groups[i - 1] >= p->groups[i])) : p->groups[i]) return -1;
    const wq_identity_t *roots[WQ_MAX_ROOTS + 2] = {&p->delegation, &p->execution_root};
    const char *paths[WQ_MAX_ROOTS + 2] = {p->delegation_path, p->execution_path};
    for (size_t i = 0; i < p->readonly_count; ++i) { roots[i + 2] = &p->readonly_roots[i]; paths[i + 2] = p->readonly_paths[i]; }
    for (size_t i = 0; i < (size_t)p->readonly_count + 2; ++i) {
        if (!memchr(paths[i], 0, WQ_PATH_BYTES) || paths[i][0] != '/' || !paths[i][1] ||
            roots[i]->reserved || !S_ISDIR(roots[i]->mode) || roots[i]->uid || roots[i]->mode & 0022 ||
            wq_path_contains(paths[i], W4_PROFILE_PATH)) return -1;
        if (wq_chain_open(paths[i], &chain, 1)) return -1;
        wq_identity_t actual;
        invalid = wq_identity(chain.fds[chain.count - 1], &actual, i == 0) ||
            !wq_identity_equal(&actual, roots[i]) || wq_chain_check(&chain);
        wq_chain_close(&chain);
        if (invalid) return -1;
        for (size_t k = strlen(paths[i]) + 1; k < WQ_PATH_BYTES; ++k) if (paths[i][k]) return -1;
        for (size_t j = 0; j < i; ++j)
            if (wq_path_contains(paths[i], paths[j]) || wq_path_contains(paths[j], paths[i]) ||
                (roots[i]->device == roots[j]->device && roots[i]->inode == roots[j]->inode)) return -1;
    }
    for (size_t i = p->readonly_count; i < WQ_MAX_ROOTS; ++i) {
        wq_identity_t empty = {0}; char path[WQ_PATH_BYTES] = {0};
        if (memcmp(&p->readonly_roots[i], &empty, sizeof(empty)) || memcmp(p->readonly_paths[i], path, sizeof(path))) return -1;
    }
    return wq_remaining(deadline) < 0 ? -1 : 0;
}
#endif
