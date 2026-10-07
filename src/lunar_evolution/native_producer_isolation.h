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

static int lunar_apply_isolation(const char *profile,
                                 const char *const *read_paths, size_t read_count,
                                 const char *const *write_dirs, size_t write_count) {
    size_t i;
    if (!profile || !profile[0] || read_count > 64 || write_count > 16 ||
        (!read_paths && read_count) || (!write_dirs && write_count)) return EINVAL;
    for (i = 0; i < read_count; i++) {
        if (!read_paths[i] || !read_paths[i][0]) return EINVAL;
    }
    for (i = 0; i < write_count; i++) {
        if (!write_dirs[i] || !write_dirs[i][0]) return EINVAL;
    }
#if defined(__APPLE__)
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
                #ifdef LANDLOCK_ACCESS_FS_REFER
                LANDLOCK_ACCESS_FS_REFER |
                #endif
                0,
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
            #ifdef LANDLOCK_ACCESS_FS_REFER
            LANDLOCK_ACCESS_FS_REFER |
            #endif
            0;
        for (i = 0; i < read_count + write_count; i++) {
            const char *path = i < read_count ? read_paths[i] : write_dirs[i - read_count];
            int fd = open(path, O_PATH | O_CLOEXEC);
            if (fd < 0) { close(ruleset_fd); return errno ? errno : EACCES; }
            struct landlock_path_beneath_attr rule = { .parent_fd = fd, .allowed_access = i < read_count ? read_access : write_access };
            struct stat st;
            if (fstat(fd, &st) != 0) {
                int error = errno; close(fd); close(ruleset_fd); return error ? error : EACCES;
            }
            /* READ_DIR is valid only for directory rules.  An exact regular
               read/execute path stays exact and never grants directory access. */
            if (!S_ISDIR(st.st_mode)) {
                if (i >= read_count || !S_ISREG(st.st_mode)) {
                    close(fd); close(ruleset_fd); return EINVAL;
                }
                rule.allowed_access &= ~LANDLOCK_ACCESS_FS_READ_DIR;
            }
            if (syscall(__NR_landlock_add_rule, ruleset_fd, LANDLOCK_RULE_PATH_BENEATH, &rule, 0) < 0) {
                int error = errno; close(fd); close(ruleset_fd); return error ? error : EACCES;
            }
            close(fd);
        }
        if (syscall(__NR_landlock_restrict_self, ruleset_fd, 0) < 0) { int error = errno; close(ruleset_fd); return error ? error : EPERM; }
        close(ruleset_fd);
        /* Landlock does not mediate chmod. With bound read inputs, deny these
           permission APIs for the entire target (including writable work
           files); open/mkdir creation modes and ordinary output writes remain
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
            BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
        };
        struct sock_fprog program = { .len = (unsigned short)(sizeof(filter) / sizeof(filter[0])), .filter = filter };
        if (prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, &program) != 0) return errno ? errno : EPERM;
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
#endif
