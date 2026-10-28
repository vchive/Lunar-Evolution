/* Explicit linux-cgroup2-original-scope-v1 private x86-64 ABI.
 * All frames travel on original anonymous SOCK_SEQPACKET pairs. Neither a
 * frame nor a copied profile is an execution or quiescence capability.
 */
#ifndef LUNAR_NATIVE_WHOLE_SCOPE_PROTOCOL_H
#define LUNAR_NATIVE_WHOLE_SCOPE_PROTOCOL_H

#if !defined(__linux__) || !defined(__x86_64__)
#error "whole-scope-v1 requires native Linux x86-64"
#endif
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <poll.h>
#include <stdint.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

#define WQ_PROFILE_NAME "linux-cgroup2-original-scope-v1"
#define WQ_PROFILE_PATH "/etc/lunar-evolution/whole-scope-v1.profile"
#define WQ_MAGIC 0x3151574cu
#define WQ_PROFILE_MAGIC 0x3150574cu
#define WQ_VERSION 1u
#define WQ_MAX_GROUPS 32u
#define WQ_MAX_ROOTS 16u
#define WQ_PATH_BYTES 1024u
#define WQ_MAX_RIGHTS 4u
#define WQ_EVENT_BYTES 4096u

/* No native padding: little-endian Linux x86-64 only, with fixed zero
 * reserved fields. Python uses '<' and the exact same finite sizes. */
typedef struct __attribute__((packed)) {
    uint64_t device, inode, mount_id;
    uint32_t uid, gid, mode, reserved;
} wq_identity_t;

typedef struct __attribute__((packed)) {
    uint64_t device, inode;
} wq_namespace_t;

typedef struct __attribute__((packed)) {
    uint32_t magic, version, size, candidate_uid, candidate_gid, group_count;
    uint32_t groups[WQ_MAX_GROUPS];
    uint32_t readonly_count, flags;
    wq_identity_t delegation, execution_root, readonly_roots[WQ_MAX_ROOTS];
    /* /proc/self/ns/{user,pid,mnt,cgroup}, in this exact order. */
    wq_namespace_t namespaces[4];
    char delegation_path[WQ_PATH_BYTES], execution_path[WQ_PATH_BYTES];
    char readonly_paths[WQ_MAX_ROOTS][WQ_PATH_BYTES];
    char bootstrap_sha256[65], supervisor_sha256[65];
} wq_profile_t;

typedef struct __attribute__((packed)) {
    uint64_t deadline_ns;
    char launch_sha256[65], intent_sha256[65], target_sha256[65];
    char bootstrap_sha256[65], supervisor_sha256[65], profile_sha256[65];
    uint32_t candidate_uid, candidate_gid, group_count, groups[WQ_MAX_GROUPS];
} wq_binding_t;

typedef struct __attribute__((packed)) {
    uint64_t device, inode, size, mtime_ns, ctime_ns;
    char sha256[65];
} wq_publication_t;

enum wq_operation {
    WQ_INIT = 1,
    WQ_SCOPE = 2,
    WQ_ENROLLED = 3,
    WQ_ENROLL_ACK = 4,
    WQ_REGISTER = 5,
    WQ_REGISTER_ACK = 6,
    WQ_RELEASE = 7,
    WQ_RELEASE_PERMIT = 8,
    WQ_TARGET_DONE = 9,
    WQ_COMPLETE = 10,
    WQ_CANCEL = 11,
    WQ_GUARD_READY = 12,
    WQ_GUARD_RETIRE = 13,
    WQ_STORE_REGISTER = 14,
    WQ_STORE_EVENT = 15,
    WQ_STORE_ACK = 16,
    WQ_PUBLISH = 17,
    WQ_PUBLISHED = 18
};

typedef struct __attribute__((packed)) {
    uint32_t magic, version, operation, sequence, fd_count, reserved;
    wq_binding_t binding;
    wq_identity_t scope;
    uint64_t target_pid;
    /* registration, handoff, deadline: actual original creator FDs in this
     * order on WQ_REGISTER. S/B PERMIT, TARGET_DONE and COMPLETE bind these
     * same original pins; storage records retain them as diagnostics. All
     * other operations, including C-S ACK/RELEASE/COMPLETE, require zeros. */
    wq_publication_t publications[3];
} wq_message_t;

_Static_assert(sizeof(wq_identity_t) == 40, "identity ABI");
_Static_assert(sizeof(wq_publication_t) == 105, "publication ABI");
_Static_assert(sizeof(wq_binding_t) == 538, "binding ABI");
_Static_assert(sizeof(wq_message_t) == 925, "message ABI");
_Static_assert(sizeof(wq_profile_t) == 19506, "profile ABI");

static inline int wq_now(uint64_t *value) {
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now) || now.tv_sec < 0)
        return -1;
    *value = (uint64_t)now.tv_sec * 1000000000ULL + (uint64_t)now.tv_nsec;
    return 0;
}

static inline int wq_remaining(uint64_t deadline) {
    uint64_t now;
    if (!deadline || wq_now(&now) || now >= deadline) {
        errno = ETIMEDOUT;
        return -1;
    }
    uint64_t left = deadline - now;
    return left >= 10000000ULL ? 10 : (int)((left + 999999ULL) / 1000000ULL);
}

static inline int wq_digest(const char *text) {
    if (text[64])
        return -1;
    for (size_t i = 0; i < 64; ++i)
        if (!((text[i] >= '0' && text[i] <= '9') || (text[i] >= 'a' && text[i] <= 'f')))
            return -1;
    return 0;
}

static inline int wq_binding_valid(const wq_binding_t *binding) {
    if (!binding->deadline_ns || !binding->candidate_uid || binding->candidate_uid == UINT_MAX ||
        !binding->candidate_gid || binding->candidate_gid == UINT_MAX ||
        binding->group_count > WQ_MAX_GROUPS || wq_digest(binding->launch_sha256) ||
        wq_digest(binding->intent_sha256) || wq_digest(binding->target_sha256) ||
        wq_digest(binding->bootstrap_sha256) || wq_digest(binding->supervisor_sha256) ||
        wq_digest(binding->profile_sha256))
        return -1;
    for (size_t i = 0; i < WQ_MAX_GROUPS; ++i) {
        if (i < binding->group_count) {
            if (!binding->groups[i] || binding->groups[i] == UINT_MAX ||
                (i && binding->groups[i - 1] >= binding->groups[i]))
                return -1;
        } else if (binding->groups[i])
            return -1;
    }
    return 0;
}

static inline void wq_message_init(wq_message_t *message, const wq_binding_t *binding,
                                   uint32_t operation, uint32_t sequence, uint32_t count) {
    memset(message, 0, sizeof(*message));
    message->magic = WQ_MAGIC;
    message->version = WQ_VERSION;
    message->operation = operation;
    message->sequence = sequence;
    message->fd_count = count;
    memcpy(&message->binding, binding, sizeof(*binding));
}

static inline int wq_message_check(const wq_message_t *message, const wq_binding_t *binding,
                                   uint32_t operation, uint32_t sequence, uint32_t count) {
    return message->magic != WQ_MAGIC || message->version != WQ_VERSION || message->reserved ||
           message->operation != operation || message->sequence != sequence ||
           message->fd_count != count || memcmp(&message->binding, binding, sizeof(*binding)) ||
           wq_binding_valid(&message->binding);
}

static inline int wq_socket(int fd) {
    int type = 0, flags = fcntl(fd, F_GETFL);
    socklen_t size = sizeof(type);
    struct sockaddr_storage address;
    socklen_t length = sizeof(address);
    if (fd <= 2 || flags < 0 || (flags & O_ASYNC) ||
        getsockopt(fd, SOL_SOCKET, SO_TYPE, &type, &size) || type != SOCK_SEQPACKET ||
        getsockname(fd, (struct sockaddr *)&address, &length) || address.ss_family != AF_UNIX ||
        length != sizeof(sa_family_t))
        return -1;
    return fcntl(fd, F_SETFL, flags | O_NONBLOCK);
}

/* Exactly one packet per call. EAGAIN/EINTR is returned to the caller's poll
 * loop so it can observe its original lifelines between every finite attempt. */
static inline int wq_send(int socket_fd, const wq_message_t *message, const int *rights,
                          size_t count) {
    if (count > WQ_MAX_RIGHTS || count != message->fd_count || (count && !rights)) {
        errno = EPROTO;
        return -1;
    }
    if (wq_remaining(message->binding.deadline_ns) < 0)
        return -1;
    struct iovec vector = {(void *)message, sizeof(*message)};
    char ancillary[CMSG_SPACE(sizeof(int) * WQ_MAX_RIGHTS)];
    struct msghdr header;
    memset(&header, 0, sizeof(header));
    header.msg_iov = &vector;
    header.msg_iovlen = 1;
    if (count) {
        memset(ancillary, 0, sizeof(ancillary));
        header.msg_control = ancillary;
        header.msg_controllen = CMSG_SPACE(sizeof(int) * count);
        struct cmsghdr *control = CMSG_FIRSTHDR(&header);
        control->cmsg_level = SOL_SOCKET;
        control->cmsg_type = SCM_RIGHTS;
        control->cmsg_len = CMSG_LEN(sizeof(int) * count);
        memcpy(CMSG_DATA(control), rights, sizeof(int) * count);
    }
    ssize_t size = sendmsg(socket_fd, &header, MSG_DONTWAIT | MSG_NOSIGNAL);
    if (size < 0)
        return -1;
    if (size != (ssize_t)sizeof(*message)) {
        errno = EPROTO;
        return -1;
    }
    return wq_remaining(message->binding.deadline_ns) < 0 ? -1 : 0;
}

static inline int wq_receive(int socket_fd, wq_message_t *message, int *rights, size_t expected,
                             uint64_t deadline) {
    if (expected > WQ_MAX_RIGHTS || (expected && !rights)) {
        errno = EPROTO;
        return -1;
    }
    if (wq_remaining(deadline) < 0)
        return -1;
    unsigned char raw[sizeof(*message) + 1];
    struct iovec vector = {raw, sizeof(raw)};
    char ancillary[CMSG_SPACE(sizeof(int) * WQ_MAX_RIGHTS)];
    struct msghdr header;
    memset(&header, 0, sizeof(header));
    memset(ancillary, 0, sizeof(ancillary));
    header.msg_iov = &vector;
    header.msg_iovlen = 1;
    header.msg_control = ancillary;
    header.msg_controllen = sizeof(ancillary);
    ssize_t size = recvmsg(socket_fd, &header, MSG_DONTWAIT | MSG_CMSG_CLOEXEC);
    if (size < 0)
        return -1;
    int acquired[WQ_MAX_RIGHTS];
    size_t count = 0;
    int invalid = 0, rights_headers = 0;
    for (struct cmsghdr *control = CMSG_FIRSTHDR(&header); control;
         control = CMSG_NXTHDR(&header, control)) {
        if (control->cmsg_level != SOL_SOCKET || control->cmsg_type != SCM_RIGHTS ||
            control->cmsg_len < CMSG_LEN(0) || (control->cmsg_len - CMSG_LEN(0)) % sizeof(int)) {
            invalid = 1;
            continue;
        }
        if (++rights_headers > 1)
            invalid = 1;
        size_t n = (control->cmsg_len - CMSG_LEN(0)) / sizeof(int);
        int *fds = (int *)CMSG_DATA(control);
        for (size_t i = 0; i < n; ++i) {
            if (count < WQ_MAX_RIGHTS)
                acquired[count++] = fds[i];
            else {
                close(fds[i]);
                invalid = 1;
            }
        }
    }
    if (size != (ssize_t)sizeof(*message) || header.msg_flags & (MSG_TRUNC | MSG_CTRUNC) ||
        invalid || count != expected || wq_remaining(deadline) < 0) {
        for (size_t i = 0; i < count; ++i)
            close(acquired[i]);
        errno = EPROTO;
        return -1;
    }
    memcpy(message, raw, sizeof(*message));
    if (message->fd_count != expected) {
        for (size_t i = 0; i < count; ++i)
            close(acquired[i]);
        errno = EPROTO;
        return -1;
    }
    for (size_t i = 0; i < count; ++i)
        rights[i] = acquired[i];
    return 0;
}
#endif
