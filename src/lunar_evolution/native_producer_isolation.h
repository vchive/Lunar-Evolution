#ifndef LUNAR_NATIVE_PRODUCER_ISOLATION_H
#define LUNAR_NATIVE_PRODUCER_ISOLATION_H
/*
 * Apply the exact, controller-generated producer policy in a child immediately
 * before exec.  Returns 0 on success or a fixed errno value.  This API is
 * intentionally self-contained so the trusted bootstrap has no helper process.
 */
#include <errno.h>
#include <stddef.h>
#include <string.h>
#include <sys/types.h>

typedef struct { int fd; unsigned int role; } lunar_grant_fd_t;

static int lunar_apply_isolation_internal(const char *profile,
                                 const char *const *read_paths, size_t read_count,
                                 const char *const *write_dirs, size_t write_count,
                                 const lunar_grant_fd_t *grants, size_t grant_count) {
    size_t i;
    if (grants) {
        if (!grant_count || grant_count > 81 || read_paths || write_dirs) return EINVAL;
        read_count = write_count = 0;
        for (i = 0; i < grant_count; ++i) {
            if (grants[i].fd <= 2) return EINVAL;
            if (grants[i].role == 1 || grants[i].role == 2) ++read_count;
            else if (grants[i].role == 4 || grants[i].role == 12) ++write_count;
            else return EINVAL;
        }
    } else if (grant_count) return EINVAL;
    if (!profile || !profile[0] || read_count > 64 || write_count > 16 ||
        (!grants && ((!read_paths && read_count) || (!write_dirs && write_count)))) return EINVAL;
    for (i = 0; !grants && i < read_count; i++) {
        if (!read_paths[i] || !read_paths[i][0]) return EINVAL;
    }
    for (i = 0; !grants && i < write_count; i++) {
        if (!write_dirs[i] || !write_dirs[i][0]) return EINVAL;
    }
#if defined(__APPLE__)
    if (grants) return ENOTSUP;
    /* sandbox_init applies a deny-default SBPL profile.  The profile is already
       canonicalized and path-bound by Python; paths are revalidated as nonempty
       here so the C boundary cannot silently broaden the policy. */
    #include <sandbox.h>
    char *errorbuf = NULL;
    if (sandbox_init(profile, 0, &errorbuf) != 0) {
        if (errorbuf) sandbox_free_error(errorbuf);
        return EPERM;
    }
    return 0;
#elif defined(__linux__)
    /* The syscall-number fallbacks and audit/clone layout below are defined
       only for these ABIs. Reject every other architecture before touching
       Landlock, even if its recent headers provide the modern syscall names. */
    #if !defined(__x86_64__) && !defined(__aarch64__) && !defined(__i386__)
    (void)profile; (void)read_paths; (void)write_dirs; return ENOTSUP;
    #else
    /* Linux support is compiled only when the host provides both Landlock and
       seccomp headers.  The implementation is intentionally fail-closed on
       older kernels rather than claiming a weaker policy. */
    #if defined(__has_include)
      #if __has_include(<linux/landlock.h>) && __has_include(<linux/filter.h>) && __has_include(<sys/prctl.h>) && __has_include(<sys/syscall.h>)
        #include <fcntl.h>
        #include <linux/filter.h>
        #include <linux/audit.h>
        #include <linux/landlock.h>
        #include <linux/seccomp.h>
        #include <sys/prctl.h>
        #include <sys/syscall.h>
        #include <unistd.h>
        #include <sys/stat.h>
        #include <stdint.h>
        #include <signal.h>
        #include <sys/ioctl.h>
        /* These stable Landlock UAPI values must not disappear merely because
           build headers predate ABI 2/3. The runtime ABI query, not conditional
           compilation of a weaker rights mask, establishes kernel support. */
        #ifndef LANDLOCK_CREATE_RULESET_VERSION
        #define LANDLOCK_CREATE_RULESET_VERSION (1U << 0)
        #endif
        #ifndef LANDLOCK_ACCESS_FS_REFER
        #define LANDLOCK_ACCESS_FS_REFER (1ULL << 13)
        #endif
        #ifndef LANDLOCK_ACCESS_FS_TRUNCATE
        #define LANDLOCK_ACCESS_FS_TRUNCATE (1ULL << 14)
        #endif
        long landlock_abi = syscall(__NR_landlock_create_ruleset, NULL, 0,
                                   LANDLOCK_CREATE_RULESET_VERSION);
        if (landlock_abi < 3) return ENOTSUP;
        /* Landlock requires no-new-privileges before restricting an
           unprivileged process.  Set it before creating/installing the ruleset
           so kernels do not reject the restriction with EPERM. */
        if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0) return errno ? errno : EPERM;
        struct landlock_ruleset_attr ruleset = {
            .handled_access_fs = LANDLOCK_ACCESS_FS_EXECUTE | LANDLOCK_ACCESS_FS_WRITE_FILE |
                LANDLOCK_ACCESS_FS_READ_FILE | LANDLOCK_ACCESS_FS_READ_DIR | LANDLOCK_ACCESS_FS_REMOVE_DIR |
                LANDLOCK_ACCESS_FS_REMOVE_FILE | LANDLOCK_ACCESS_FS_MAKE_CHAR | LANDLOCK_ACCESS_FS_MAKE_DIR |
                LANDLOCK_ACCESS_FS_MAKE_REG | LANDLOCK_ACCESS_FS_MAKE_SOCK | LANDLOCK_ACCESS_FS_MAKE_FIFO |
                LANDLOCK_ACCESS_FS_MAKE_BLOCK | LANDLOCK_ACCESS_FS_MAKE_SYM |
                LANDLOCK_ACCESS_FS_REFER | LANDLOCK_ACCESS_FS_TRUNCATE,
        };
        int ruleset_fd = (int)syscall(__NR_landlock_create_ruleset, &ruleset, sizeof(ruleset), 0);
        if (ruleset_fd < 0) return ENOTSUP;
        unsigned long long read_access = LANDLOCK_ACCESS_FS_EXECUTE | LANDLOCK_ACCESS_FS_READ_FILE | LANDLOCK_ACCESS_FS_READ_DIR;
        unsigned long long write_access = read_access | LANDLOCK_ACCESS_FS_WRITE_FILE | LANDLOCK_ACCESS_FS_REMOVE_DIR |
            LANDLOCK_ACCESS_FS_REMOVE_FILE | LANDLOCK_ACCESS_FS_MAKE_DIR | LANDLOCK_ACCESS_FS_MAKE_REG |
            #ifdef LANDLOCK_ACCESS_FS_MAKE_SOCK
            LANDLOCK_ACCESS_FS_MAKE_SOCK |
            #endif
            #ifdef LANDLOCK_ACCESS_FS_MAKE_FIFO
            LANDLOCK_ACCESS_FS_MAKE_FIFO |
            #endif
            LANDLOCK_ACCESS_FS_REFER | LANDLOCK_ACCESS_FS_TRUNCATE;
        for (i = 0; i < (grants ? grant_count : read_count + write_count); i++) {
            int is_write = grants ? (grants[i].role & 4) != 0 : i >= read_count;
            int fd = grants ? grants[i].fd : open(i < read_count ? read_paths[i] : write_dirs[i - read_count], O_PATH | O_CLOEXEC);
            if (fd < 0) { close(ruleset_fd); return errno ? errno : EACCES; }
            unsigned long long access = is_write ? write_access : read_access;
            if (grants && grants[i].role == 1) access = LANDLOCK_ACCESS_FS_READ_FILE;
            struct landlock_path_beneath_attr rule = { .parent_fd = fd, .allowed_access = access };
            struct stat st;
            if (fstat(fd, &st) != 0) {
                int error = errno; if (!grants) close(fd); close(ruleset_fd); return error ? error : EACCES;
            }
            if (grants && ((grants[i].role == 1 && (!S_ISREG(st.st_mode) || st.st_nlink != 1)) ||
                           (grants[i].role != 1 && !S_ISDIR(st.st_mode)))) {
                close(ruleset_fd); return EINVAL;
            }
            /* READ_DIR is valid only for directory rules.  An exact regular
               read/execute path stays exact and never grants directory access. */
            if (!S_ISDIR(st.st_mode)) {
                if (is_write || !S_ISREG(st.st_mode)) {
                    if (!grants) close(fd); close(ruleset_fd); return EINVAL;
                }
                rule.allowed_access &= ~LANDLOCK_ACCESS_FS_READ_DIR;
            }
            if (syscall(__NR_landlock_add_rule, ruleset_fd, LANDLOCK_RULE_PATH_BENEATH, &rule, 0) < 0) {
                int error = errno; if (!grants) close(fd); close(ruleset_fd); return error ? error : EACCES;
            }
            if (!grants) close(fd);
        }
        if (syscall(__NR_landlock_restrict_self, ruleset_fd, 0) < 0) { int error = errno; close(ruleset_fd); return error ? error : EPERM; }
        close(ruleset_fd);
        /* Landlock does not mediate ownership, timestamps or xattrs. With
           bound read inputs, deny mutation APIs for the entire target
           (including writable work files); open/mkdir creation modes and writes remain
           available. This is deliberately not path-sensitive metadata control.
           fchmodat2 is syscall 452 on every supported Linux architecture, even
           when the build host's older headers do not name the newer syscall. */
        #if defined(__NR_fchmodat2)
        #define LUNAR_NR_FCHMODAT2 __NR_fchmodat2
        #elif defined(__x86_64__) || defined(__aarch64__) || defined(__i386__)
        #define LUNAR_NR_FCHMODAT2 452
        #else
        return ENOTSUP;
        #endif
        /* setxattrat/removexattrat arrived after the common syscall headers.
           Their numbers are shared by all three supported ABIs. i386 also
           has a separate utimensat time64 entry; it must not bypass the gate. */
        #if defined(__NR_setxattrat)
        #define LUNAR_NR_SETXATTRAT __NR_setxattrat
        #else
        #define LUNAR_NR_SETXATTRAT 463
        #endif
        #if defined(__NR_removexattrat)
        #define LUNAR_NR_REMOVEXATTRAT __NR_removexattrat
        #else
        #define LUNAR_NR_REMOVEXATTRAT 466
        #endif
        #if defined(__NR_utimensat_time64)
        #define LUNAR_NR_UTIMENSAT_TIME64 __NR_utimensat_time64
        #elif defined(__i386__)
        #define LUNAR_NR_UTIMENSAT_TIME64 412
        #endif
        #if defined(__i386__)
        #if defined(__NR_chown32)
        #define LUNAR_NR_CHOWN32 __NR_chown32
        #else
        #define LUNAR_NR_CHOWN32 212
        #endif
        #if defined(__NR_lchown32)
        #define LUNAR_NR_LCHOWN32 __NR_lchown32
        #else
        #define LUNAR_NR_LCHOWN32 198
        #endif
        #if defined(__NR_fchown32)
        #define LUNAR_NR_FCHOWN32 __NR_fchown32
        #else
        #define LUNAR_NR_FCHOWN32 207
        #endif
        #endif
        #define LUNAR_DENY_INPUT_MUTATION(number) \
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, number, 0, 1), \
            BPF_STMT(BPF_RET | BPF_K, read_count ? SECCOMP_RET_ERRNO | EPERM : SECCOMP_RET_ALLOW)
        /* These modern syscall numbers are shared by the supported x86_64,
           aarch64 and i386 ABIs. Older libc headers must not silently omit a
           deny rule for a syscall provided by the running kernel. */
        #if defined(__NR_clone3)
        #define LUNAR_NR_CLONE3 __NR_clone3
        #else
        #define LUNAR_NR_CLONE3 435
        #endif
        #if defined(__NR_pidfd_send_signal)
        #define LUNAR_NR_PIDFD_SEND_SIGNAL __NR_pidfd_send_signal
        #else
        #define LUNAR_NR_PIDFD_SEND_SIGNAL 424
        #endif
        #if defined(__NR_pidfd_getfd)
        #define LUNAR_NR_PIDFD_GETFD __NR_pidfd_getfd
        #else
        #define LUNAR_NR_PIDFD_GETFD 438
        #endif
        #if defined(__NR_io_uring_setup)
        #define LUNAR_NR_IO_URING_SETUP __NR_io_uring_setup
        #else
        #define LUNAR_NR_IO_URING_SETUP 425
        #endif
        #if defined(__NR_io_uring_enter)
        #define LUNAR_NR_IO_URING_ENTER __NR_io_uring_enter
        #else
        #define LUNAR_NR_IO_URING_ENTER 426
        #endif
        #if defined(__NR_io_uring_register)
        #define LUNAR_NR_IO_URING_REGISTER __NR_io_uring_register
        #else
        #define LUNAR_NR_IO_URING_REGISTER 427
        #endif
        /* Legacy clone's flags are argument 0 on every supported ABI. Deny
           NEWTIME/NEWNS/NEWCGROUP/NEWUTS/NEWIPC/NEWUSER/NEWPID/NEWNET while
           retaining normal fork, vfork and thread flags. NEWTIME shares the
           low exit-signal byte, but no valid signal uses its 0x80 bit. */
        #define LUNAR_CLONE_NAMESPACE_FLAGS 0x7e020080U
        /* Stable native UAPI tables, including entries absent from old libc
           headers. i386 semop/time32 semtimedop use ipc, not invented direct
           numbers; the time64 entry and ipc itself are both filtered below. */
        #if defined(__x86_64__)
        #define LUNAR_NR_SHMGET 29
        #define LUNAR_NR_SHMAT 30
        #define LUNAR_NR_SHMCTL 31
        #define LUNAR_NR_SHMDT 67
        #define LUNAR_NR_MSGGET 68
        #define LUNAR_NR_MSGSND 69
        #define LUNAR_NR_MSGRCV 70
        #define LUNAR_NR_MSGCTL 71
        #define LUNAR_NR_SEMGET 64
        #define LUNAR_NR_SEMOP 65
        #define LUNAR_NR_SEMCTL 66
        #define LUNAR_NR_SEMTIMEDOP 220
        #define LUNAR_NR_SENDMMSG 307
        #define LUNAR_NR_RECVMSG 47
        #define LUNAR_NR_RECVMMSG 299
        #define LUNAR_NR_SOCKETPAIR 53
        #elif defined(__aarch64__)
        #define LUNAR_NR_SHMGET 194
        #define LUNAR_NR_SHMAT 196
        #define LUNAR_NR_SHMCTL 195
        #define LUNAR_NR_SHMDT 197
        #define LUNAR_NR_MSGGET 186
        #define LUNAR_NR_MSGSND 189
        #define LUNAR_NR_MSGRCV 188
        #define LUNAR_NR_MSGCTL 187
        #define LUNAR_NR_SEMGET 190
        #define LUNAR_NR_SEMOP 193
        #define LUNAR_NR_SEMCTL 191
        #define LUNAR_NR_SEMTIMEDOP 192
        #define LUNAR_NR_SENDMMSG 269
        #define LUNAR_NR_RECVMSG 212
        #define LUNAR_NR_RECVMMSG 243
        #define LUNAR_NR_SOCKETPAIR 199
        #else /* Native i386, not x32 or the compat ABI of a 64-bit process. */
        #define LUNAR_NR_SHMGET 395
        #define LUNAR_NR_SHMAT 397
        #define LUNAR_NR_SHMCTL 396
        #define LUNAR_NR_SHMDT 398
        #define LUNAR_NR_MSGGET 399
        #define LUNAR_NR_MSGSND 400
        #define LUNAR_NR_MSGRCV 401
        #define LUNAR_NR_MSGCTL 402
        #define LUNAR_NR_SEMGET 393
        #define LUNAR_NR_SEMCTL 394
        #define LUNAR_NR_IPC 117
        #define LUNAR_NR_SEMTIMEDOP_TIME64 420
        #define LUNAR_NR_SENDMMSG 345
        #define LUNAR_NR_RECVMSG 372
        #define LUNAR_NR_RECVMMSG 337
        #define LUNAR_NR_RECVMMSG_TIME64 417
        #define LUNAR_NR_SOCKETPAIR 360
        #endif
        #define LUNAR_DENY_IPC(number) \
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, number, 0, 1), \
            BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM)
        /* This only narrows the target's control surface; it is not complete
           containment or a post-bootstrap descendant supervision protocol.
           Namespace, external signal/memory and network control calls fail
           with EPERM. clone3 returns ENOSYS so libc can use filtered legacy
           clone for ordinary threads. Other calls remain governed by Landlock
           and the target's normal runtime. */
        struct sock_filter filter[] = {
            BPF_STMT(BPF_LD | BPF_W | BPF_ABS, 4),
            #if defined(__x86_64__)
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, AUDIT_ARCH_X86_64, 1, 0),
            #elif defined(__aarch64__)
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, AUDIT_ARCH_AARCH64, 1, 0),
            #elif defined(__i386__)
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, AUDIT_ARCH_I386, 1, 0),
            #endif
            BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_KILL_PROCESS),
            BPF_STMT(BPF_LD | BPF_W | BPF_ABS, 0),
            #if defined(__x86_64__)
            /* x32 has the same audit architecture but tags syscall numbers;
               allowing that alternate number space would bypass this list. */
            BPF_JUMP(BPF_JMP | BPF_JSET | BPF_K, 0x40000000U, 0, 1), BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
            #endif
            #ifdef __NR_clone
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_clone, 0, 4),
            BPF_STMT(BPF_LD | BPF_W | BPF_ABS, (unsigned int)offsetof(struct seccomp_data, args[0])),
            BPF_JUMP(BPF_JMP | BPF_JSET | BPF_K, LUNAR_CLONE_NAMESPACE_FLAGS, 0, 1),
            BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
            BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
            #endif
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, LUNAR_NR_CLONE3, 0, 1), BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | ENOSYS),
            #ifdef __NR_setsid
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_setsid, 0, 1), BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
            #endif
            #ifdef __NR_setpgid
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_setpgid, 0, 1), BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
            #endif
            #ifdef __NR_setns
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_setns, 0, 1), BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
            #endif
            #ifdef __NR_kill
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_kill, 0, 1), BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
            #endif
            #ifdef __NR_tkill
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_tkill, 0, 1), BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
            #endif
            #ifdef __NR_tgkill
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_tgkill, 0, 1), BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
            #endif
            #ifdef __NR_rt_sigqueueinfo
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_rt_sigqueueinfo, 0, 1), BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
            #endif
            #ifdef __NR_rt_tgsigqueueinfo
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_rt_tgsigqueueinfo, 0, 1), BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
            #endif
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, LUNAR_NR_PIDFD_SEND_SIGNAL, 0, 1), BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, LUNAR_NR_PIDFD_GETFD, 0, 1), BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
            #ifdef __NR_process_vm_readv
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_process_vm_readv, 0, 1), BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
            #endif
            #ifdef __NR_process_vm_writev
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_process_vm_writev, 0, 1), BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
            #endif
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, LUNAR_NR_IO_URING_SETUP, 0, 1), BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, LUNAR_NR_IO_URING_REGISTER, 0, 1), BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, LUNAR_NR_IO_URING_ENTER, 0, 1), BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
            #ifdef __NR_socketcall
            /* i386 multiplexes network operations through socketcall. */
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_socketcall, 0, 1), BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
            #endif
            /* SysV IPC addresses host-namespace objects without inherited FDs
               or filesystem paths. Ancillary socket APIs can acquire/export
               descriptors. These bounded controls are not full egress proof. */
            LUNAR_DENY_IPC(LUNAR_NR_SHMGET),
            LUNAR_DENY_IPC(LUNAR_NR_SHMAT),
            LUNAR_DENY_IPC(LUNAR_NR_SHMCTL),
            LUNAR_DENY_IPC(LUNAR_NR_SHMDT),
            LUNAR_DENY_IPC(LUNAR_NR_MSGGET),
            LUNAR_DENY_IPC(LUNAR_NR_MSGSND),
            LUNAR_DENY_IPC(LUNAR_NR_MSGRCV),
            LUNAR_DENY_IPC(LUNAR_NR_MSGCTL),
            LUNAR_DENY_IPC(LUNAR_NR_SEMGET),
            LUNAR_DENY_IPC(LUNAR_NR_SEMCTL),
            #ifdef LUNAR_NR_SEMOP
            LUNAR_DENY_IPC(LUNAR_NR_SEMOP),
            LUNAR_DENY_IPC(LUNAR_NR_SEMTIMEDOP),
            #endif
            #ifdef LUNAR_NR_IPC
            LUNAR_DENY_IPC(LUNAR_NR_IPC),
            LUNAR_DENY_IPC(LUNAR_NR_SEMTIMEDOP_TIME64),
            LUNAR_DENY_IPC(LUNAR_NR_RECVMMSG_TIME64),
            #endif
            LUNAR_DENY_IPC(LUNAR_NR_SENDMMSG),
            LUNAR_DENY_IPC(LUNAR_NR_RECVMSG),
            LUNAR_DENY_IPC(LUNAR_NR_RECVMMSG),
            #ifdef __NR_socket
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_socket, 0, 1), BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
            #endif
            #ifdef __NR_connect
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_connect, 0, 1), BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
            #endif
            #ifdef __NR_bind
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_bind, 0, 1), BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
            #endif
            #ifdef __NR_listen
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_listen, 0, 1), BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
            #endif
            #ifdef __NR_accept
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_accept, 0, 1), BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
            #endif
            #ifdef __NR_accept4
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_accept4, 0, 1), BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
            #endif
            #ifdef __NR_sendto
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_sendto, 0, 1), BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
            #endif
            #ifdef __NR_sendmsg
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_sendmsg, 0, 1), BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
            #endif
            #ifdef __NR_ptrace
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_ptrace, 0, 1), BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
            #endif
            #ifdef __NR_unshare
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_unshare, 0, 1), BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
            #endif
            #ifdef __NR_chmod
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_chmod, 0, 1), BPF_STMT(BPF_RET | BPF_K, read_count ? SECCOMP_RET_ERRNO | EPERM : SECCOMP_RET_ALLOW),
            #endif
            #ifdef __NR_fchmod
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_fchmod, 0, 1), BPF_STMT(BPF_RET | BPF_K, read_count ? SECCOMP_RET_ERRNO | EPERM : SECCOMP_RET_ALLOW),
            #endif
            #ifdef __NR_fchmodat
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_fchmodat, 0, 1), BPF_STMT(BPF_RET | BPF_K, read_count ? SECCOMP_RET_ERRNO | EPERM : SECCOMP_RET_ALLOW),
            #endif
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, LUNAR_NR_FCHMODAT2, 0, 1), BPF_STMT(BPF_RET | BPF_K, read_count ? SECCOMP_RET_ERRNO | EPERM : SECCOMP_RET_ALLOW),
            #ifdef __NR_chown
            LUNAR_DENY_INPUT_MUTATION(__NR_chown),
            #endif
            #ifdef __NR_lchown
            LUNAR_DENY_INPUT_MUTATION(__NR_lchown),
            #endif
            #ifdef __NR_fchown
            LUNAR_DENY_INPUT_MUTATION(__NR_fchown),
            #endif
            #ifdef __NR_fchownat
            LUNAR_DENY_INPUT_MUTATION(__NR_fchownat),
            #endif
            #ifdef LUNAR_NR_CHOWN32
            LUNAR_DENY_INPUT_MUTATION(LUNAR_NR_CHOWN32),
            #endif
            #ifdef LUNAR_NR_LCHOWN32
            LUNAR_DENY_INPUT_MUTATION(LUNAR_NR_LCHOWN32),
            #endif
            #ifdef LUNAR_NR_FCHOWN32
            LUNAR_DENY_INPUT_MUTATION(LUNAR_NR_FCHOWN32),
            #endif
            #ifdef __NR_utime
            LUNAR_DENY_INPUT_MUTATION(__NR_utime),
            #endif
            #ifdef __NR_utimes
            LUNAR_DENY_INPUT_MUTATION(__NR_utimes),
            #endif
            #ifdef __NR_futimesat
            LUNAR_DENY_INPUT_MUTATION(__NR_futimesat),
            #endif
            #ifdef __NR_utimensat
            LUNAR_DENY_INPUT_MUTATION(__NR_utimensat),
            #endif
            #ifdef LUNAR_NR_UTIMENSAT_TIME64
            LUNAR_DENY_INPUT_MUTATION(LUNAR_NR_UTIMENSAT_TIME64),
            #endif
            #ifdef __NR_setxattr
            LUNAR_DENY_INPUT_MUTATION(__NR_setxattr),
            #endif
            #ifdef __NR_lsetxattr
            LUNAR_DENY_INPUT_MUTATION(__NR_lsetxattr),
            #endif
            #ifdef __NR_fsetxattr
            LUNAR_DENY_INPUT_MUTATION(__NR_fsetxattr),
            #endif
            #ifdef __NR_removexattr
            LUNAR_DENY_INPUT_MUTATION(__NR_removexattr),
            #endif
            #ifdef __NR_lremovexattr
            LUNAR_DENY_INPUT_MUTATION(__NR_lremovexattr),
            #endif
            #ifdef __NR_fremovexattr
            LUNAR_DENY_INPUT_MUTATION(__NR_fremovexattr),
            #endif
            LUNAR_DENY_INPUT_MUTATION(LUNAR_NR_SETXATTRAT),
            LUNAR_DENY_INPUT_MUTATION(LUNAR_NR_REMOVEXATTRAT),
            BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
        };
        #undef LUNAR_DENY_INPUT_MUTATION
        #undef LUNAR_DENY_IPC
        struct sock_fprog program = { .len = (unsigned short)(sizeof(filter) / sizeof(filter[0])), .filter = filter };
        if (prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, &program) != 0) return errno ? errno : EPERM;
        /* AF_UNIX socketpair is private internal IPC, useful to fork/thread
           runtimes. Preserve it without admitting other domains or int-narrowed
           upper-word encodings. i386 socketcall remains denied wholesale. */
        struct sock_filter pair_control[] = {
            BPF_STMT(BPF_LD | BPF_W | BPF_ABS, 0),
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, LUNAR_NR_SOCKETPAIR, 1, 0),
            BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
            BPF_STMT(BPF_LD | BPF_W | BPF_ABS, (unsigned int)offsetof(struct seccomp_data, args[0]) + 4),
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 0, 1, 0),
            BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
            BPF_STMT(BPF_LD | BPF_W | BPF_ABS, (unsigned int)offsetof(struct seccomp_data, args[0])),
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 1 /* AF_UNIX */, 1, 0),
            BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
            BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
        };
        struct sock_fprog pair_program = {
            .len = (unsigned short)(sizeof(pair_control) / sizeof(pair_control[0])), .filter = pair_control,
        };
        if (prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, &pair_program) != 0) return errno ? errno : EPERM;
        /* The first filter already validates the native audit architecture and
           rejects x32. These additional intersecting filters never enlarge it.
           Explicit signal denials alone do not mediate asynchronous pipe/file
           ownership, dnotify or leases. Admit ordinary fcntl commands only and
           reject O_ASYNC even when F_SETFL is otherwise legitimate.
           Supported ABIs are little-endian; reject upper command/flag words
           rather than relying on the kernel's later int narrowing. */
        #if defined(__i386__)
        #ifdef __NR_fcntl64
        #define LUNAR_NR_FCNTL64 __NR_fcntl64
        #else
        #define LUNAR_NR_FCNTL64 221
        #endif
        #else
        #define LUNAR_NR_FCNTL64 __NR_fcntl
        #endif
        #define LUNAR_ALLOW_FCNTL(command) \
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, command, 0, 1), \
            BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW)
        struct sock_filter fd_control[] = {
            BPF_STMT(BPF_LD | BPF_W | BPF_ABS, 0),
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_fcntl, 2, 0),
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, LUNAR_NR_FCNTL64, 1, 0),
            BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
            BPF_STMT(BPF_LD | BPF_W | BPF_ABS, (unsigned int)offsetof(struct seccomp_data, args[1]) + 4),
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 0, 1, 0),
            BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
            BPF_STMT(BPF_LD | BPF_W | BPF_ABS, (unsigned int)offsetof(struct seccomp_data, args[1])),
            LUNAR_ALLOW_FCNTL(F_DUPFD),
            LUNAR_ALLOW_FCNTL(F_GETFD),
            LUNAR_ALLOW_FCNTL(F_SETFD),
            LUNAR_ALLOW_FCNTL(F_GETFL),
            LUNAR_ALLOW_FCNTL(F_GETLK),
            LUNAR_ALLOW_FCNTL(F_SETLK),
            LUNAR_ALLOW_FCNTL(F_SETLKW),
            #ifdef F_GETLK64
            LUNAR_ALLOW_FCNTL(F_GETLK64),
            LUNAR_ALLOW_FCNTL(F_SETLK64),
            LUNAR_ALLOW_FCNTL(F_SETLKW64),
            #endif
            /* Stable Linux UAPI commands, also when build headers are old. */
            LUNAR_ALLOW_FCNTL(1030), /* F_DUPFD_CLOEXEC */
            LUNAR_ALLOW_FCNTL(36),   /* F_OFD_GETLK */
            LUNAR_ALLOW_FCNTL(37),   /* F_OFD_SETLK */
            LUNAR_ALLOW_FCNTL(38),   /* F_OFD_SETLKW */
            LUNAR_ALLOW_FCNTL(1025), /* F_GETLEASE */
            LUNAR_ALLOW_FCNTL(1032), /* F_GETPIPE_SZ */
            LUNAR_ALLOW_FCNTL(1034), /* F_GET_SEALS */
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, F_SETFL, 0, 7),
            BPF_STMT(BPF_LD | BPF_W | BPF_ABS, (unsigned int)offsetof(struct seccomp_data, args[2]) + 4),
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 0, 1, 0),
            BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
            BPF_STMT(BPF_LD | BPF_W | BPF_ABS, (unsigned int)offsetof(struct seccomp_data, args[2])),
            BPF_JUMP(BPF_JMP | BPF_JSET | BPF_K, O_ASYNC, 0, 1),
            BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
            BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
            BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
        };
        #undef LUNAR_ALLOW_FCNTL
        #undef LUNAR_NR_FCNTL64
        struct sock_fprog fd_program = {
            .len = (unsigned short)(sizeof(fd_control) / sizeof(fd_control[0])), .filter = fd_control,
        };
        if (prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, &fd_program) != 0) return errno ? errno : EPERM;
        /* Only these fixed descriptor/pipe requests are needed at this local
           boundary. In particular FIOASYNC/FIOSETOWN, terminal/device controls,
           filesystem mutations and unknown/future requests cannot pass it.
           This does not prove complete egress or the identity of host stdio. */
        #define LUNAR_ALLOW_IOCTL(request) \
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, request, 0, 1), \
            BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW)
        struct sock_filter ioctl_control[] = {
            BPF_STMT(BPF_LD | BPF_W | BPF_ABS, 0),
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_ioctl, 1, 0),
            BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
            BPF_STMT(BPF_LD | BPF_W | BPF_ABS, (unsigned int)offsetof(struct seccomp_data, args[1]) + 4),
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 0, 1, 0),
            BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
            BPF_STMT(BPF_LD | BPF_W | BPF_ABS, (unsigned int)offsetof(struct seccomp_data, args[1])),
            LUNAR_ALLOW_IOCTL(FIONREAD),
            LUNAR_ALLOW_IOCTL(FIONBIO),
            LUNAR_ALLOW_IOCTL(FIOCLEX),
            LUNAR_ALLOW_IOCTL(FIONCLEX),
            BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
        };
        #undef LUNAR_ALLOW_IOCTL
        struct sock_fprog ioctl_program = {
            .len = (unsigned short)(sizeof(ioctl_control) / sizeof(ioctl_control[0])), .filter = ioctl_control,
        };
        if (prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, &ioctl_program) != 0) return errno ? errno : EPERM;
        return 0;
      #else
        (void)profile; (void)read_paths; (void)write_dirs; return ENOTSUP;
      #endif
    #else
      (void)profile; (void)read_paths; (void)write_dirs; return ENOTSUP;
    #endif
    #endif
#else
    (void)profile; (void)read_paths; (void)write_dirs; return ENOTSUP;
#endif
}

static int lunar_apply_isolation(const char *profile,
                                 const char *const *read_paths, size_t read_count,
                                 const char *const *write_dirs, size_t write_count) {
    return lunar_apply_isolation_internal(profile, read_paths, read_count, write_dirs, write_count, NULL, 0);
}

static inline int lunar_apply_grant_isolation(const lunar_grant_fd_t *grants, size_t grant_count) {
    if (!grants) return EINVAL;
    return lunar_apply_isolation_internal("linux-landlock-seccomp-v1", NULL, 0, NULL, 0, grants, grant_count);
}
#endif
