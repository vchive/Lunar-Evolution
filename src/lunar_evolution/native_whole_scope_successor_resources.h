/* V4-only native total descriptor bound. No path reopens or limit restoration. */
#ifndef LUNAR_NATIVE_WHOLE_SCOPE_SUCCESSOR_RESOURCES_H
#define LUNAR_NATIVE_WHOLE_SCOPE_SUCCESSOR_RESOURCES_H
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <linux/audit.h>
#include <linux/filter.h>
#include <linux/seccomp.h>
#include <stddef.h>
#include <sys/prctl.h>
#include <sys/resource.h>
#include <sys/syscall.h>
#include <unistd.h>

#define W4_RESOURCE_FD_LIMIT 96u
typedef struct { int *slot; int target; } w4_resource_fixed_t;

/* No FD is acquired while reducing an inherited table to the finite inputs. */
static inline int w4_resource_close_unlisted(const int *fds, size_t count) {
    int sorted[W4_RESOURCE_FD_LIMIT];
    for (size_t i = 0; i < count; ++i) {
        sorted[i] = fds[i];
        for (size_t j = i; j && sorted[j] < sorted[j - 1]; --j) {
            int swap = sorted[j]; sorted[j] = sorted[j - 1]; sorted[j - 1] = swap;
        }
    }
    unsigned int first = 3;
    for (size_t i = 0; i < count; ++i) {
        if (first < (unsigned int)sorted[i] &&
            syscall(SYS_close_range, first, (unsigned int)sorted[i] - 1, 0)) return -1;
        first = (unsigned int)sorted[i] + 1;
    }
    return syscall(SYS_close_range, first, UINT_MAX, 0) ? -1 : 0;
}

/* Even a privileged native helper cannot raise its own/its children's limit.
 * Trusted external administration remains outside this local filter boundary. */
static inline int w4_resource_lock(unsigned int low_limit) {
#if defined(__x86_64__) && !defined(__ILP32__)
    struct rlimit bound = {(rlim_t)low_limit, (rlim_t)low_limit};
    if (setrlimit(RLIMIT_NOFILE, &bound)) return -1;
    struct sock_filter filter[] = {
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, arch)),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, AUDIT_ARCH_X86_64, 1, 0),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),
        BPF_JUMP(BPF_JMP | BPF_JSET | BPF_K, 0x40000000u, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_setrlimit, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_prlimit64, 0, 5),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, args[2])),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 0, 0, 2),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, args[2]) + 4),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 0, 1, 0),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
    };
    struct sock_fprog program = {(unsigned short)(sizeof(filter) / sizeof(filter[0])), filter};
    if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0)) return -1;
    return syscall(SYS_seccomp, SECCOMP_SET_MODE_FILTER, SECCOMP_FILTER_FLAG_TSYNC, &program) ? -1 : 0;
#else
    (void)low_limit;
    errno = ENOTSUP;
    return -1;
#endif
}

/* Slots name actual acquired OFDs and are rewritten in place. Fixed entries
 * are separate, exclusively FD197/198; a conflicting retained target refuses.
 * The caller is the original finite single-threaded native entry. On failure
 * it terminates the attempt: closing, lowering and filtering are not undone. */
static inline int w4_resource_enter(int **slots, size_t count,
                                     const w4_resource_fixed_t *fixed, size_t fixed_count) {
    if (count > W4_RESOURCE_FD_LIMIT || fixed_count > 2 ||
        count + fixed_count > W4_RESOURCE_FD_LIMIT || (count && !slots) ||
        (fixed_count && !fixed)) return -1;
    int initial[W4_RESOURCE_FD_LIMIT];
    size_t retained = count + fixed_count, actual = retained;
    for (size_t i = 0; i < retained; ++i) {
        int *slot = i < count ? slots[i] : fixed[i - count].slot;
        if (!slot || *slot <= 2 || fcntl(*slot, F_GETFD) < 0) return -1;
        initial[i] = *slot;
        for (size_t j = 0; j < i; ++j) if (initial[j] == initial[i]) return -1;
    }
    for (int fd = 0; fd < 3; ++fd) {
        if (fcntl(fd, F_GETFD) >= 0) ++actual;
        else if (errno != EBADF) return -1;
    }
    if (actual > W4_RESOURCE_FD_LIMIT) return -1;
    for (size_t i = 0; i < fixed_count; ++i) {
        if (fixed[i].target != 197 && fixed[i].target != 198) return -1;
        for (size_t j = 0; j < i; ++j) if (fixed[j].target == fixed[i].target) return -1;
        for (size_t j = 0; j < retained; ++j)
            if (initial[j] == fixed[i].target && initial[j] != *fixed[i].slot) return -1;
    }
    if (w4_resource_close_unlisted(initial, retained)) return -1;
    for (size_t i = 0; i < fixed_count; ++i) {
        int original = *fixed[i].slot;
        if (original == fixed[i].target) continue;
        if (actual >= W4_RESOURCE_FD_LIMIT) { errno = EMFILE; return -1; }
        if (dup3(original, fixed[i].target, O_CLOEXEC) < 0) return -1;
        *fixed[i].slot = fixed[i].target;
        if (close(original)) return -1;
    }
    unsigned int low_limit = W4_RESOURCE_FD_LIMIT - (unsigned int)fixed_count;
    if (w4_resource_lock(low_limit)) return -1;
    for (size_t i = 0; i < count; ++i) {
        int original = *slots[i];
        if ((unsigned int)original < low_limit) continue;
        if (actual >= W4_RESOURCE_FD_LIMIT) { errno = EMFILE; return -1; }
        int low = fcntl(original, F_DUPFD_CLOEXEC, 3);
        if (low < 0) return -1;
        if ((unsigned int)low >= low_limit) { close(low); return -1; }
        *slots[i] = low;
        if (close(original)) return -1;
    }
    return 0;
}
#endif
