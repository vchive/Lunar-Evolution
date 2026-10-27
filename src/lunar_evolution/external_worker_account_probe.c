/* Fixed no-secret installed-account probe. No candidate or interpreter execution. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <grp.h>
#include <linux/capability.h>
#include <poll.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

extern char **environ;

static uint32_t u32(const unsigned char *p) {
    return (uint32_t)p[0] | ((uint32_t)p[1] << 8) |
           ((uint32_t)p[2] << 16) | ((uint32_t)p[3] << 24);
}
static void put32(unsigned char *p, uint32_t n) {
    for (unsigned i = 0; i < 4; ++i) p[i] = (unsigned char)(n >> (i * 8));
}
static uint64_t now_ns(void) {
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC, &t) != 0) return UINT64_MAX;
    return (uint64_t)t.tv_sec * UINT64_C(1000000000) + (uint64_t)t.tv_nsec;
}
static int transfer(int fd, unsigned char *p, size_t n, int writing, uint64_t deadline) {
    while (n) {
        uint64_t now = now_ns();
        if (now >= deadline) return -1;
        uint64_t ms = (deadline - now + UINT64_C(999999)) / UINT64_C(1000000);
        struct pollfd item = {fd, writing ? POLLOUT : POLLIN, 0};
        int ready = poll(&item, 1, ms > INT32_MAX ? INT32_MAX : (int)ms);
        if (ready < 0 && errno == EINTR) continue;
        if (ready != 1 || now_ns() >= deadline ||
            !(item.revents & (writing ? POLLOUT : POLLIN))) return -1;
        ssize_t got = writing ? write(fd, p, n) : read(fd, p, n);
        if (got < 0 && errno == EINTR) continue;
        if (got <= 0) return -1;
        p += got; n -= (size_t)got;
    }
    return 0;
}
int main(int argc, char **argv) {
    if (argc != 3 || strcmp(argv[1], "--fixed-no-secret-probe-v1") != 0) return 70;
    uint64_t deadline = 0;
    if (!argv[2][0]) return 70;
    for (const char *p = argv[2]; *p; ++p) {
        if (*p < '0' || *p > '9' || deadline > (UINT64_MAX - 9) / 10) return 70;
        deadline = deadline * 10 + (unsigned)(*p - '0');
    }
    if (now_ns() >= deadline) return 77;
    /* The parent passes only this static executable FD, never secret FDs.
       Closing it before the control body also excludes all descriptors >= 3. */
#ifdef SYS_close_range
    if (syscall(SYS_close_range, 3U, ~0U, 0U) != 0) return 71;
#else
    return 71;
#endif
    if (environ == NULL || environ[0] != NULL) return 72;
    if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0 ||
        prctl(PR_GET_NO_NEW_PRIVS, 0, 0, 0, 0) != 1) return 73;
    uid_t u, e, s; gid_t g, eg, sg;
    if (getresuid(&u, &e, &s) != 0 || getresgid(&g, &eg, &sg) != 0 ||
        u == 0 || u != e || u != s || g != eg || g != sg || getgroups(0, NULL) != 0) return 74;
    struct __user_cap_header_struct h = {_LINUX_CAPABILITY_VERSION_3, 0};
    struct __user_cap_data_struct caps[2];
    memset(caps, 0, sizeof(caps));
    if (syscall(SYS_capget, &h, caps) != 0) return 75;
    for (unsigned i = 0; i < 2; ++i)
        if (caps[i].effective || caps[i].permitted || caps[i].inheritable) return 75;
    for (unsigned i = 0; i < 64; ++i) {
        int ambient = prctl(PR_CAP_AMBIENT, PR_CAP_AMBIENT_IS_SET, i, 0, 0);
        if (ambient > 0 || (ambient < 0 && errno != EINVAL)) return 75;
    }
    unsigned char header[28];
    /* The fixed small header is delivered before paths, with no secret data.
       A closed original parent pipe means failure, never a replacement origin. */
    if (transfer(0, header, sizeof(header), 0, deadline) != 0 ||
        memcmp(header, "LAPIN1\0\0", 8) != 0 ||
        ((uint64_t)u32(header + 8) | ((uint64_t)u32(header + 12) << 32)) != deadline) return 76;
    uint32_t errors[3];
    for (unsigned i = 0; i < 3; ++i) {
        uint32_t size = u32(header + 16 + 4 * i);
        char path[4097];
        if (size == 0 || size > 4096 ||
            transfer(0, (unsigned char *)path, size, 0, deadline) != 0) return 76;
        path[size] = 0;
        if (path[0] != '/' || memchr(path, 0, size) != NULL) return 76;
        if (now_ns() >= deadline) return 77;
        int flags = O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC;
        if (i == 2) flags |= O_DIRECTORY;
        int fd = open(path, flags);
        errors[i] = fd < 0 ? (uint32_t)errno : 0;
        if (fd >= 0) close(fd);  /* Never read even one secret byte. */
    }
    unsigned char result[64];
    memset(result, 0, sizeof(result));
    memcpy(result, "LAPROB1\0", 8);
    uint32_t values[14] = {u, e, s, g, eg, sg, 0, 1,
        errors[0], errors[1], errors[2], 1, 1, 1};
    for (unsigned i = 0; i < 14; ++i) put32(result + 8 + i * 4, values[i]);
    if (transfer(1, result, sizeof(result), 1, deadline) != 0) return 77;
    return 0;
}
