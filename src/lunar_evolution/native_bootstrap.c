/*
 * Lunar Evolution trusted producer bootstrap.
 *
 * This is intentionally a small, dependency-free executable.  It reads one
 * bounded binary control record, announces readiness, waits for one release
 * byte, and only then forks/execs the already-bound target.  No target path,
 * argv, or environment is inspected before the release byte.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <poll.h>
#include <pthread.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
#if defined(__linux__)
#include <sys/prctl.h>
#include <sys/statfs.h>
#include <sys/syscall.h>
#endif
#include "native_producer_isolation.h"

#if defined(__APPLE__)
#include <mach/mach_time.h>
static mach_timebase_info_data_t native_timebase;
#endif

#if !defined(__APPLE__) && !defined(__linux__)
#error "native trusted bootstrap supports Darwin and Linux only"
#endif

/* Small self-contained SHA-256 implementation keeps the artifact free of
 * OpenSSL/CommonCrypto runtime dependencies. */
typedef struct { uint32_t h[8]; uint64_t n; unsigned char b[64]; size_t used; } SHA_CTX;
static const uint32_t K[64] = {
  0x428a2f98u,0x71374491u,0xb5c0fbcfu,0xe9b5dba5u,0x3956c25bu,0x59f111f1u,0x923f82a4u,0xab1c5ed5u,
  0xd807aa98u,0x12835b01u,0x243185beu,0x550c7dc3u,0x72be5d74u,0x80deb1feu,0x9bdc06a7u,0xc19bf174u,
  0xe49b69c1u,0xefbe4786u,0x0fc19dc6u,0x240ca1ccu,0x2de92c6fu,0x4a7484aau,0x5cb0a9dcu,0x76f988dau,
  0x983e5152u,0xa831c66du,0xb00327c8u,0xbf597fc7u,0xc6e00bf3u,0xd5a79147u,0x06ca6351u,0x14292967u,
  0x27b70a85u,0x2e1b2138u,0x4d2c6dfcu,0x53380d13u,0x650a7354u,0x766a0abbu,0x81c2c92eu,0x92722c85u,
  0xa2bfe8a1u,0xa81a664bu,0xc24b8b70u,0xc76c51a3u,0xd192e819u,0xd6990624u,0xf40e3585u,0x106aa070u,
  0x19a4c116u,0x1e376c08u,0x2748774cu,0x34b0bcb5u,0x391c0cb3u,0x4ed8aa4au,0x5b9cca4fu,0x682e6ff3u,
  0x748f82eeu,0x78a5636fu,0x84c87814u,0x8cc70208u,0x90befffau,0xa4506cebu,0xbef9a3f7u,0xc67178f2u};
static uint32_t rr(uint32_t x,int n){return (x>>n)|(x<<(32-n));}
static uint32_t beword(const unsigned char *p){return ((uint32_t)p[0]<<24)|((uint32_t)p[1]<<16)|((uint32_t)p[2]<<8)|p[3];}
static void SHA_BLOCK(SHA_CTX *c,const unsigned char *p){uint32_t w[64],a,b,d,e,f,g,h,t1,t2; int i;
  for(i=0;i<16;i++)w[i]=beword(p+4*i); for(i=16;i<64;i++){uint32_t s0=rr(w[i-15],7)^rr(w[i-15],18)^(w[i-15]>>3),s1=rr(w[i-2],17)^rr(w[i-2],19)^(w[i-2]>>10);w[i]=w[i-16]+s0+w[i-7]+s1;}
  a=c->h[0];b=c->h[1];d=c->h[3];e=c->h[4];f=c->h[5];g=c->h[6];h=c->h[7];uint32_t cc=c->h[2];
  for(i=0;i<64;i++){uint32_t S1=rr(e,6)^rr(e,11)^rr(e,25),ch=(e&f)^((~e)&g);t1=h+S1+ch+K[i]+w[i];uint32_t S0=rr(a,2)^rr(a,13)^rr(a,22),ma=(a&b)^(a&cc)^(b&cc);t2=S0+ma;h=g;g=f;f=e;e=d+t1;d=cc;cc=b;b=a;a=t1+t2;}
  c->h[0]+=a;c->h[1]+=b;c->h[2]+=cc;c->h[3]+=d;c->h[4]+=e;c->h[5]+=f;c->h[6]+=g;c->h[7]+=h;}
static void SHA_INIT(SHA_CTX *c){static const uint32_t h[8]={0x6a09e667u,0xbb67ae85u,0x3c6ef372u,0xa54ff53au,0x510e527fu,0x9b05688cu,0x1f83d9abu,0x5be0cd19u};memcpy(c->h,h,sizeof(h));c->n=0;c->used=0;}
static void SHA_UPDATE(SHA_CTX *c,const void *data,size_t n){const unsigned char *p=data;c->n+=n;while(n){size_t take=64-c->used;if(take>n)take=n;memcpy(c->b+c->used,p,take);c->used+=take;p+=take;n-=take;if(c->used==64){SHA_BLOCK(c,c->b);c->used=0;}}}
static void SHA_FINAL(unsigned char out[32],SHA_CTX *c){uint64_t bits=c->n*8;size_t i; c->b[c->used++]=0x80;while(c->used!=56){if(c->used==64){SHA_BLOCK(c,c->b);c->used=0;}c->b[c->used++]=0;}for(i=0;i<8;i++)c->b[56+i]=(unsigned char)(bits>>(56-8*i));SHA_BLOCK(c,c->b);for(i=0;i<8;i++){out[4*i]=(unsigned char)(c->h[i]>>24);out[4*i+1]=(unsigned char)(c->h[i]>>16);out[4*i+2]=(unsigned char)(c->h[i]>>8);out[4*i+3]=(unsigned char)c->h[i];}}

#define MAX_CONTROL (64u * 1024u)
#define MAX_PATH_BYTES 4096u
#define MAX_ARGC 64u
#define MAX_ARG_BYTES 4096u
#define MAGIC "LNB1"
#define PROTOCOL "lunar-trusted-producer-bootstrap-v1"
#define SCHEMA "1"

typedef struct {
    char launch[65], intent[65], target_sha[65];
    int32_t target_fd;
    char *target_path, *cwd, *profile;
    char **read_paths, **write_dirs;
    uint32_t read_count, write_count;
    char **argv;
    uint32_t argc;
} control_t;

static int read_full(int fd, void *out, size_t len) {
    unsigned char *p = (unsigned char *)out;
    while (len) {
        ssize_t n = read(fd, p, len);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return -1;
        p += (size_t)n; len -= (size_t)n;
    }
    return 0;
}

static int write_full(int fd, const void *data, size_t len) {
    const unsigned char *p = (const unsigned char *)data;
    while (len) {
        ssize_t n = write(fd, p, len);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) return -1;
        p += (size_t)n; len -= (size_t)n;
    }
    return 0;
}

static uint32_t be32(const unsigned char *p) {
    return ((uint32_t)p[0] << 24) | ((uint32_t)p[1] << 16) |
           ((uint32_t)p[2] << 8) | (uint32_t)p[3];
}

static int hex64(const char *s) {
    for (int i = 0; i < 64; i++) {
        char c = s[i];
        if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) return 0;
    }
    return s[64] == '\0';
}

static int read_string(const unsigned char *buf, size_t total, size_t *pos,
                       char **out, uint32_t max_len) {
    if (*pos + 4 > total) return -1;
    uint32_t len = be32(buf + *pos); *pos += 4;
    if (len == 0 || len > max_len || *pos + len > total) return -1;
    char *value = (char *)calloc((size_t)len + 1, 1);
    if (!value) return -1;
    memcpy(value, buf + *pos, len); *pos += len;
    if (memchr(value, '\0', len) != NULL) { free(value); return -1; }
    *out = value;
    return 0;
}

static void free_control(control_t *c) {
    free(c->target_path); free(c->cwd); free(c->profile);
    if (c->argv) { for (uint32_t i = 0; i < c->argc; i++) free(c->argv[i]); }
    if (c->read_paths) { for (uint32_t i = 0; i < c->read_count; i++) free(c->read_paths[i]); }
    if (c->write_dirs) { for (uint32_t i = 0; i < c->write_count; i++) free(c->write_dirs[i]); }
    free(c->argv); free(c->read_paths); free(c->write_dirs); memset(c, 0, sizeof(*c));
}

static int parse_control(const unsigned char *buf, size_t total, control_t *c) {
    if (total < 4 + 2 + 2 + 64 * 3 + 4 || memcmp(buf, MAGIC, 4) != 0) return -1;
    /* version and flags are two-byte values; version is encoded at offsets 4..5. */
    if (buf[4] != 0 || buf[5] != 1 || buf[6] != 0 || buf[7] != 0) return -1;
    size_t pos = 8;
    memcpy(c->launch, buf + pos, 64); c->launch[64] = 0; pos += 64;
    memcpy(c->intent, buf + pos, 64); c->intent[64] = 0; pos += 64;
    memcpy(c->target_sha, buf + pos, 64); c->target_sha[64] = 0; pos += 64;
    if (!hex64(c->launch) || !hex64(c->intent) || !hex64(c->target_sha) || pos + 4 > total) return -1;
    c->target_fd = (int32_t)be32(buf + pos); pos += 4;
    if (read_string(buf, total, &pos, &c->target_path, MAX_PATH_BYTES) != 0 ||
        read_string(buf, total, &pos, &c->cwd, MAX_PATH_BYTES) != 0 ||
        read_string(buf, total, &pos, &c->profile, 32 * 1024) != 0 || pos + 4 > total) return -1;
    c->read_count = be32(buf + pos); pos += 4;
    if (c->read_count > 64) return -1;
    c->read_paths = (char **)calloc(c->read_count ? c->read_count : 1, sizeof(char *));
    if (!c->read_paths) return -1;
    for (uint32_t i = 0; i < c->read_count; i++) {
        if (read_string(buf, total, &pos, &c->read_paths[i], MAX_PATH_BYTES) != 0) return -1;
    }
    if (pos + 4 > total) return -1;
    c->write_count = be32(buf + pos); pos += 4;
    if (c->write_count > 16) return -1;
    c->write_dirs = (char **)calloc(c->write_count ? c->write_count : 1, sizeof(char *));
    if (!c->write_dirs) return -1;
    for (uint32_t i = 0; i < c->write_count; i++) {
        if (read_string(buf, total, &pos, &c->write_dirs[i], MAX_PATH_BYTES) != 0) return -1;
    }
    if (pos + 4 > total) return -1;
    c->argc = be32(buf + pos); pos += 4;
    if (c->argc == 0 || c->argc > MAX_ARGC) return -1;
    c->argv = (char **)calloc(c->argc + 1, sizeof(char *));
    if (!c->argv) return -1;
    for (uint32_t i = 0; i < c->argc; i++) {
        if (read_string(buf, total, &pos, &c->argv[i], MAX_ARG_BYTES) != 0) return -1;
    }
    return pos == total ? 0 : -1;
}

static int hash_fd(int fd, unsigned char digest[32]) {
    SHA_CTX ctx; unsigned char block[65536]; ssize_t n;
    if (lseek(fd, 0, SEEK_SET) < 0) return -1;
    SHA_INIT(&ctx);
    while ((n = read(fd, block, sizeof(block))) > 0) SHA_UPDATE(&ctx, block, (size_t)n);
    if (n < 0) return -1;
    if (lseek(fd, 0, SEEK_SET) < 0) return -1;
    SHA_FINAL(digest, &ctx); return 0;
}

static int hash_path_or_fd(const control_t *c, unsigned char digest[32], int *opened) {
    int fd = c->target_fd >= 0 ? dup(c->target_fd) : open(c->target_path, O_RDONLY | O_CLOEXEC);
    if (fd < 0) return -1;
    struct stat st;
    if (fstat(fd, &st) != 0 || !S_ISREG(st.st_mode) ||
        st.st_size < 1 || st.st_size > 128 * 1024 * 1024 || !(st.st_mode & 0111)) {
        close(fd); return -1;
    }
    if (st.st_nlink != 1) {
#if defined(__linux__)
        /* Anonymous memfds deliberately have no pathname link.  Only an
           inherited, fully sealed descriptor may use this execution route;
           deleted or mutable files must not stand in for attested bytes. */
        int required_seals = F_SEAL_WRITE | F_SEAL_GROW | F_SEAL_SHRINK | F_SEAL_SEAL;
        int seals = fcntl(fd, F_GET_SEALS);
        if (c->target_fd < 0 || st.st_nlink != 0 || seals < 0 ||
            (seals & required_seals) != required_seals) {
            close(fd); return -1;
        }
#else
        close(fd); return -1;
#endif
    }
    if (hash_fd(fd, digest) != 0) { close(fd); return -1; }
    *opened = fd; return 0;
}

static void hex_lower(const unsigned char digest[32], char out[65]) {
    static const char *digits = "0123456789abcdef";
    for (int i = 0; i < 32; i++) { out[i * 2] = digits[digest[i] >> 4]; out[i * 2 + 1] = digits[digest[i] & 15]; }
    out[64] = 0;
}

static int frame_json(char *out, size_t cap, const char *launch, const char *intent,
                      int seq, const char *kind, const char *target_sha,
                      pid_t pid, pid_t pgid) {
    char body[2048], digest[65];
    int has_target = target_sha != NULL;
    int n = snprintf(body, sizeof(body),
        "{\"intent_sha256\":\"%s\",\"kind\":\"%s\",\"launch_sha256\":\"%s\","
        "\"observed_pgid\":%s,\"observed_pid\":%s,\"protocol\":\"%s\",\"schema_version\":\"%s\","
        "\"sequence\":%d,\"target_executable_identity\":%s}",
        intent, kind, launch, "null", "null",
        PROTOCOL, SCHEMA, seq, "null");
    if (n < 0 || (size_t)n >= sizeof(body)) return -1;
    if (has_target) {
        /* Fill the three non-null values without permitting producer-controlled JSON. */
        n = snprintf(body, sizeof(body),
            "{\"intent_sha256\":\"%s\",\"kind\":\"%s\",\"launch_sha256\":\"%s\","
            "\"observed_pgid\":%ld,\"observed_pid\":%ld,\"protocol\":\"%s\",\"schema_version\":\"%s\","
            "\"sequence\":%d,\"target_executable_identity\":\"%s\"}",
            intent, kind, launch, (long)pgid, (long)pid, PROTOCOL, SCHEMA, seq, target_sha);
    }
    if (n < 0 || (size_t)n >= sizeof(body)) return -1;
    SHA_CTX ctx; unsigned char sum[32]; SHA_INIT(&ctx); SHA_UPDATE(&ctx, body, (size_t)n); SHA_FINAL(sum, &ctx); hex_lower(sum, digest);
    n = snprintf(out, cap,
        "{\"frame_sha256\":\"%s\",\"intent_sha256\":\"%s\",\"kind\":\"%s\",\"launch_sha256\":\"%s\","
        "\"observed_pgid\":%s,\"observed_pid\":%s,\"protocol\":\"%s\",\"schema_version\":\"%s\","
        "\"sequence\":%d,\"target_executable_identity\":%s}\n",
        digest, intent, kind, launch, "null", "null",
        PROTOCOL, SCHEMA, seq, "null");
    if (has_target) {
        n = snprintf(out, cap,
            "{\"frame_sha256\":\"%s\",\"intent_sha256\":\"%s\",\"kind\":\"%s\",\"launch_sha256\":\"%s\","
            "\"observed_pgid\":%ld,\"observed_pid\":%ld,\"protocol\":\"%s\",\"schema_version\":\"%s\","
            "\"sequence\":%d,\"target_executable_identity\":\"%s\"}\n",
            digest, intent, kind, launch, (long)pgid, (long)pid, PROTOCOL, SCHEMA, seq, target_sha);
    }
    return (n < 0 || (size_t)n >= cap) ? -1 : n;
}

static int emit_frame(int fd, const char *launch, const char *intent, int seq, const char *kind,
                      const char *target_sha, pid_t pid, pid_t pgid) {
    char line[4096]; int n = frame_json(line, sizeof(line), launch, intent, seq, kind, target_sha, pid, pgid);
    return n < 0 ? -1 : write_full(fd, line, (size_t)n);
}

static int parse_fd_arg(const char *arg, int *out) {
    char *end = NULL; long value = strtol(arg, &end, 10);
    if (!arg[0] || !end || *end || value < 0 || value > INT_MAX) return -1;
    *out = (int)value; return 0;
}

#if defined(__linux__)
/* This capability uses kernel descriptor operations, never a finite RLIMIT or
   /proc census. The fallback is valid only on the Linux ABIs we support. */
#if !defined(__NR_close_range) && (defined(__x86_64__) || defined(__aarch64__) || defined(__i386__))
#define __NR_close_range 436
#endif
#define LUNAR_PIPEFS_MAGIC 0x50495045UL

static int parse_handoff_fd(const char *arg, int *out) {
    unsigned int value = 0;
    if (!arg || !arg[0] || (arg[0] == '0' && arg[1])) return -1;
    for (const char *p = arg; *p; ++p) {
        if (*p < '0' || *p > '9') return -1;
        unsigned int digit = (unsigned int)(*p - '0');
        if (value > ((unsigned int)INT_MAX - digit) / 10) return -1;
        value = value * 10 + digit;
    }
    if (value <= 2) return -1;
    *out = (int)value;
    return 0;
}

static int handoff_pipe(int fd, int access, struct stat *info) {
    struct statfs fs;
    int flags = fcntl(fd, F_GETFL);
    /* PIPEFS + FIFO proves an anonymous kernel pipe, not its original owner.
       Trusted Python creates the two fresh pipes; no durable provenance or
       authority is inferred from the caller's environment numbers alone. */
    if (flags < 0 || (flags & O_ACCMODE) != access || (flags & O_PATH) != 0 ||
        fstat(fd, info) != 0 || !S_ISFIFO(info->st_mode) ||
        fstatfs(fd, &fs) != 0 || (unsigned long)fs.f_type != LUNAR_PIPEFS_MAGIC)
        return -1;
    return 0;
}

static int handoff_broker(const char *read_arg, const char *write_arg,
                          const int *reserved, size_t reserved_count, int *r, int *w) {
    *r = *w = -1;
    if (!read_arg && !write_arg) return 0;
    if (parse_handoff_fd(read_arg, r) || parse_handoff_fd(write_arg, w) || *r == *w)
        return -1;
    for (size_t i = 0; i < reserved_count; ++i) {
        if (*r == reserved[i] || *w == reserved[i]) return -1;
    }
    struct stat read_info, write_info;
    if (handoff_pipe(*r, O_RDONLY, &read_info) || handoff_pipe(*w, O_WRONLY, &write_info) ||
        (read_info.st_dev == write_info.st_dev && read_info.st_ino == write_info.st_ino))
        return -1;
    return 0;
}

static int handoff_cloexec(int fd, int enabled) {
    int flags = fcntl(fd, F_GETFD);
    if (flags < 0 || fcntl(fd, F_SETFD, enabled ? flags | FD_CLOEXEC : flags & ~FD_CLOEXEC) != 0)
        return -1;
    return 0;
}

static int handoff_close_extra(int target_fd, int error_fd, int broker_r, int broker_w) {
    int keep[4]; size_t count = 0;
    keep[count++] = error_fd;
    if (target_fd >= 0) keep[count++] = target_fd;
    if (broker_r >= 0) { keep[count++] = broker_r; keep[count++] = broker_w; }
    for (size_t i = 0; i < count; ++i) {
        if (keep[i] <= 2) return EINVAL;
        for (size_t j = 0; j < i; ++j) if (keep[j] == keep[i]) return EINVAL;
        for (size_t j = i; j > 0 && keep[j] < keep[j - 1]; --j) {
            int swap = keep[j]; keep[j] = keep[j - 1]; keep[j - 1] = swap;
        }
    }
#if defined(__NR_close_range) && (defined(__x86_64__) || defined(__aarch64__) || defined(__i386__))
    unsigned int first = 3;
    for (size_t i = 0; i < count; ++i) {
        unsigned int next = (unsigned int)keep[i];
        if (first < next && syscall(__NR_close_range, first, next - 1, 0) != 0)
            return errno ? errno : ENOTSUP;
        first = next + 1;
    }
    if (syscall(__NR_close_range, first, UINT_MAX, 0) != 0)
        return errno ? errno : ENOTSUP;
    return 0;
#else
    return ENOTSUP;
#endif
}
#endif

static _Noreturn void child_start_failed(int fd, int error, int status) {
    int reported = error ? error : EINVAL;
    (void)write_full(fd, &reported, sizeof(reported));
    _exit(status);
}

typedef struct {
    int enabled;
    int fd;
    pid_t pid;
    uint64_t deadline_ns;
    pthread_t thread;
} controller_guard_t;

static int parse_deadline_arg(const char *arg, uint64_t *out) {
    uint64_t value = 0;
    if (!arg[0]) return -1;
    for (const char *p = arg; *p; p++) {
        if (*p < '0' || *p > '9') return -1;
        uint64_t digit = (uint64_t)(*p - '0');
        if (value > (UINT64_MAX - digit) / 10) return -1;
        value = value * 10 + digit;
    }
    if (!value) return -1;
    *out = value;
    return 0;
}

static int native_monotonic_ns(uint64_t *out) {
#if defined(__APPLE__)
    /* Python monotonic_ns uses this clock, not Darwin CLOCK_MONOTONIC. The
       timebase is initialized before creating any thread or forking a target. */
    if (!native_timebase.denom) return -1;
    __uint128_t scaled = (__uint128_t)mach_absolute_time() * native_timebase.numer;
    scaled /= native_timebase.denom;
    if (scaled > UINT64_MAX) return -1;
    *out = (uint64_t)scaled;
#else
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now) != 0 || now.tv_sec < 0 ||
        now.tv_nsec < 0 || now.tv_nsec >= 1000000000 ||
        (uint64_t)now.tv_sec > (UINT64_MAX - (uint64_t)now.tv_nsec) / 1000000000) return -1;
    *out = (uint64_t)now.tv_sec * 1000000000 + (uint64_t)now.tv_nsec;
#endif
    return 0;
}

static int guard_deadline_expired(const controller_guard_t *guard) {
    uint64_t now;
    return guard->deadline_ns &&
        (native_monotonic_ns(&now) != 0 || now >= guard->deadline_ns);
}

static void stop_own_guarded_group(const controller_guard_t *guard) {
    /* Select only this still-private kernel group, never a persisted/recovered PID. */
    if (guard->enabled && getpid() == guard->pid && getpgrp() == guard->pid &&
        getsid(0) == guard->pid) {
        (void)kill(0, SIGKILL);
    }
    _exit(78);
}

static void check_controller_guard(const controller_guard_t *guard) {
    if (!guard->enabled) return;
    for (;;) {
        if (getpid() != guard->pid || getpgrp() != guard->pid ||
            getsid(0) != guard->pid || guard_deadline_expired(guard))
            stop_own_guarded_group(guard);
        struct pollfd owner_pipe = {guard->fd, POLLIN, 0};
        int observed = poll(&owner_pipe, 1, 0);
        if (observed < 0 && errno == EINTR) continue;
        if (observed != 0 || guard_deadline_expired(guard))
            stop_own_guarded_group(guard);
        return;
    }
}

static int setup_child_supervision(void) {
#if defined(__linux__)
    int enabled = 0;
    if (prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) != 0 ||
        prctl(PR_GET_CHILD_SUBREAPER, &enabled, 0, 0, 0) != 0 || enabled != 1)
        return -1;
    /* An inherited ignored SIGCHLD/SA_NOCLDWAIT could auto-reap children and
       destroy waitable-tree evidence. Targets cannot change this disposition
       in the separate bootstrap process. */
    struct sigaction restored;
    memset(&restored, 0, sizeof(restored)); restored.sa_handler = SIG_DFL;
    if (sigemptyset(&restored.sa_mask) != 0 || sigaction(SIGCHLD, &restored, NULL) != 0)
        return -1;
#endif
    return 0;
}

static int drain_supervised_children(const controller_guard_t *guard) {
#if defined(__linux__)
    for (;;) {
        check_controller_guard(guard);
        int status;
        /* __WALL also covers inherited non-SIGCHLD clone children. ECHILD,
           not a group probe which includes this leader, establishes drain. */
        pid_t waited = waitpid(-1, &status, __WALL | WNOHANG);
        if (waited > 0) continue;
        if (waited < 0) {
            if (errno == EINTR) continue;
            if (errno == ECHILD) return 0;
            return -1;
        }
        /* Reuse the original guardian and absolute deadline. The legacy
           unguarded fixture interface offers cooperative drain only. */
        struct pollfd owner_pipe = {guard->fd, POLLIN, 0};
        int observed = poll(guard->enabled ? &owner_pipe : NULL, guard->enabled ? 1 : 0, 10);
        if (observed < 0 && errno == EINTR) continue;
        if (observed != 0) {
            if (guard->enabled) stop_own_guarded_group(guard);
            return -1;
        }
    }
#else
    (void)guard;
    return 0;
#endif
}

static void *watch_controller(void *value) {
    controller_guard_t *guard = (controller_guard_t *)value;
    for (;;) {
        int timeout_ms = -1;
        if (guard->deadline_ns) {
            uint64_t now;
            if (native_monotonic_ns(&now) != 0 || now >= guard->deadline_ns)
                stop_own_guarded_group(guard);
            uint64_t remaining = guard->deadline_ns - now;
            /* Round only the poll wait, never the deadline. Recheck after every
               wakeup/EINTR; no reception-time or retry-time timeout is allocated. */
            timeout_ms = remaining >= 100000000 ? 100 : (int)((remaining + 999999) / 1000000);
        }
        struct pollfd owner_pipe = {guard->fd, POLLIN, 0};
        int observed = poll(&owner_pipe, 1, timeout_ms);
        if (observed < 0 && errno == EINTR) continue;
        /* The owner never sends data. EOF, unexpected bytes and errors stop work. */
        if (observed != 0) stop_own_guarded_group(guard);
    }
    return NULL;
}

static int start_controller_guard(controller_guard_t *guard, int fd, uint64_t deadline_ns) {
    struct stat info;
    int flags = fcntl(fd, F_GETFL);
    pid_t pid = getpid();
    if (flags < 0 || (flags & O_ACCMODE) != O_RDONLY || (flags & O_NONBLOCK) != 0 ||
        fstat(fd, &info) != 0 || !S_ISFIFO(info.st_mode) || getpgrp() != pid || getsid(0) != pid ||
        fcntl(fd, F_SETFD, FD_CLOEXEC) != 0) return -1;
    struct sigaction ignored;
    memset(&ignored, 0, sizeof(ignored));
    ignored.sa_handler = SIG_IGN;
    if (sigemptyset(&ignored.sa_mask) != 0 || sigaction(SIGPIPE, &ignored, NULL) != 0) return -1;
#if defined(__APPLE__)
    if (deadline_ns && (mach_timebase_info(&native_timebase) != KERN_SUCCESS ||
        !native_timebase.numer || !native_timebase.denom)) return -1;
#endif
    guard->enabled = 1; guard->fd = fd; guard->pid = pid; guard->deadline_ns = deadline_ns;
    if (guard_deadline_expired(guard)) stop_own_guarded_group(guard);
    if (pthread_create(&guard->thread, NULL, watch_controller, guard) != 0) return -1;
    return 0;
}

static int finish_controller_guard(controller_guard_t *guard) {
    if (!guard->enabled) return 0;
    void *result = NULL;
    if (pthread_cancel(guard->thread) != 0 || pthread_join(guard->thread, &result) != 0 ||
        result != PTHREAD_CANCELED) return -1;
    /* Joining observes cancellation completion; it does not validate the owner
       or clock across that wait. Keep the original reader until this check. */
    check_controller_guard(guard);
    close(guard->fd);
    guard->enabled = 0;
    return 0;
}

int main(int argc, char **argv) {
    if ((argc != 7 && argc != 9 && argc != 11 && argc != 13) || strcmp(argv[1], "--control-fd") != 0 || strcmp(argv[3], "--gate-fd") != 0 || strcmp(argv[5], "--frame-fd") != 0) return 64;
    int control_fd, gate_fd, frame_fd;
    if (parse_fd_arg(argv[2], &control_fd) || parse_fd_arg(argv[4], &gate_fd) || parse_fd_arg(argv[6], &frame_fd)) return 64;
#if defined(__linux__)
    if (parse_handoff_fd(argv[2], &control_fd) || parse_handoff_fd(argv[4], &gate_fd) ||
        parse_handoff_fd(argv[6], &frame_fd) || control_fd == gate_fd ||
        control_fd == frame_fd || gate_fd == frame_fd) return 64;
#endif
    if (argc == 13) {
#if defined(__linux__)
        if (strcmp(argv[11], "--child-supervision") != 0 ||
            strcmp(argv[12], "linux-subreaper-v1") != 0) return 64;
#else
        return 64;
#endif
    }
    /* All Linux entrypoints in this artifact share the same drain semantics;
       the explicit flag negotiates formal guardian/deadline supervision. */
    if (setup_child_supervision() != 0) return 64;
    controller_guard_t guard; memset(&guard, 0, sizeof(guard)); guard.fd = -1;
    if (argc >= 9) {
        int lifeline_fd;
        uint64_t deadline_ns = 0;
        if (argc >= 11 && (strcmp(argv[9], "--deadline-monotonic-ns") != 0 ||
            parse_deadline_arg(argv[10], &deadline_ns) != 0)) return 64;
        if (strcmp(argv[7], "--controller-lifeline-fd") != 0 || parse_fd_arg(argv[8], &lifeline_fd) != 0)
            return 64;
#if defined(__linux__)
        if (parse_handoff_fd(argv[8], &lifeline_fd)) return 64;
#endif
        if (lifeline_fd == control_fd || lifeline_fd == gate_fd || lifeline_fd == frame_fd ||
            start_controller_guard(&guard, lifeline_fd, deadline_ns) != 0) return 64;
    }
    unsigned char *raw = (unsigned char *)calloc(MAX_CONTROL + 1, 1); if (!raw) return 65;
    size_t used = 0; ssize_t n;
    while (used <= MAX_CONTROL && (n = read(control_fd, raw + used, MAX_CONTROL + 1 - used)) > 0) used += (size_t)n;
    close(control_fd);
    control_t c; memset(&c, 0, sizeof(c));
    if (n < 0 || used > MAX_CONTROL || parse_control(raw, used, &c) != 0) { free(raw); return 66; }
    free(raw);
    if (emit_frame(frame_fd, c.launch, c.intent, 1, "bootstrap_ready", NULL, 0, 0) != 0) { free_control(&c); return 67; }
    unsigned char token;
    if (read_full(gate_fd, &token, 1) != 0 || token != '1') { free_control(&c); return 68; }
    unsigned char extra;
    ssize_t extra_read;
    do { extra_read = read(gate_fd, &extra, 1); } while (extra_read < 0 && errno == EINTR);
    if (extra_read != 0) { free_control(&c); return 68; }
    close(gate_fd);

#if defined(__linux__)
    int broker_r, broker_w;
    int reserved[] = {control_fd, gate_fd, frame_fd, guard.fd, c.target_fd};
    if ((c.target_fd >= 0 && (c.target_fd <= 2 || c.target_fd == control_fd ||
         c.target_fd == gate_fd || c.target_fd == frame_fd || c.target_fd == guard.fd)) ||
        handoff_broker(getenv("LUNAR_PRODUCER_RESPONSE_FD"), getenv("LUNAR_PRODUCER_REQUEST_FD"),
                       reserved, sizeof(reserved) / sizeof(reserved[0]), &broker_r, &broker_w)) {
        emit_frame(frame_fd, c.launch, c.intent, 2, "target_start_failed", NULL, 0, 0);
        free_control(&c); return 73;
    }
#endif

    int target_fd = -1; unsigned char digest[32]; char target_hex[65];
    if (hash_path_or_fd(&c, digest, &target_fd) != 0) { emit_frame(frame_fd, c.launch, c.intent, 2, "target_start_failed", NULL, 0, 0); free_control(&c); return 69; }
    hex_lower(digest, target_hex);
    if (strcmp(target_hex, c.target_sha) != 0) { close(target_fd); emit_frame(frame_fd, c.launch, c.intent, 2, "target_start_failed", NULL, 0, 0); free_control(&c); return 70; }
    int exec_pipe[2];
    if (pipe(exec_pipe) != 0) { close(target_fd); emit_frame(frame_fd, c.launch, c.intent, 2, "target_start_failed", NULL, 0, 0); free_control(&c); return 71; }
    if (fcntl(exec_pipe[1], F_SETFD, FD_CLOEXEC) != 0) {
        close(exec_pipe[0]); close(exec_pipe[1]); close(target_fd);
        emit_frame(frame_fd, c.launch, c.intent, 2, "target_start_failed", NULL, 0, 0);
        free_control(&c); return 71;
    }
    pid_t child = fork();
    if (child < 0) { close(exec_pipe[0]); close(exec_pipe[1]); close(target_fd); emit_frame(frame_fd, c.launch, c.intent, 2, "target_start_failed", NULL, 0, 0); free_control(&c); return 71; }
    if (child == 0) {
#if defined(__linux__)
        /* Check live collisions before closing or dup2 can destroy the error
           channel. Parent validation precedes descriptor number reuse. */
        if (exec_pipe[0] <= 2 || exec_pipe[1] <= 2 || target_fd <= 2 ||
            exec_pipe[0] == exec_pipe[1] || exec_pipe[0] == target_fd || exec_pipe[1] == target_fd ||
            c.target_fd == exec_pipe[0] || c.target_fd == exec_pipe[1] ||
            broker_r == exec_pipe[0] || broker_r == exec_pipe[1] || broker_r == target_fd ||
            broker_w == exec_pipe[0] || broker_w == exec_pipe[1] || broker_w == target_fd)
            child_start_failed(exec_pipe[1], EINVAL, 73);
#endif
        close(exec_pipe[0]);
        if (guard.enabled) {
            /* Cover controller EOF racing fork after the guardian's group signal.
               A just-created child must not exec after missing that signal. */
            struct pollfd owner_pipe = {guard.fd, POLLIN, 0};
            if (guard_deadline_expired(&guard) || poll(&owner_pipe, 1, 0) != 0)
                child_start_failed(exec_pipe[1], ECANCELED, 73);
            close(guard.fd);
            struct sigaction restored;
            memset(&restored, 0, sizeof(restored)); restored.sa_handler = SIG_DFL;
            if (sigemptyset(&restored.sa_mask) != 0 || sigaction(SIGPIPE, &restored, NULL) != 0)
                child_start_failed(exec_pipe[1], errno, 73);
        }
        if (c.target_fd >= 0) {
            if (dup2(target_fd, c.target_fd) < 0) child_start_failed(exec_pipe[1], errno, 73);
        }
        /* The control and gate descriptors are always private to the bootstrap. */
        close(frame_fd);
        /* Only anonymous broker descriptors are forwarded; never the controller
           environment, endpoint, headers, secrets, or journal descriptors. */
        char broker_read[80], broker_write[80];
        char *target_env[] = {"PATH=/usr/bin:/bin", "LANG=C", "LUNAR_BOOTSTRAP_RELEASED=1", NULL, NULL, NULL};
        const char *rpc_read = getenv("LUNAR_PRODUCER_RESPONSE_FD");
        const char *rpc_write = getenv("LUNAR_PRODUCER_REQUEST_FD");
        if (rpc_read || rpc_write) {
            int r, w;
            if (!rpc_read || !rpc_write || parse_fd_arg(rpc_read, &r) || parse_fd_arg(rpc_write, &w))
                child_start_failed(exec_pipe[1], EINVAL, 73);
            snprintf(broker_read, sizeof(broker_read), "LUNAR_PRODUCER_RESPONSE_FD=%d", r);
            snprintf(broker_write, sizeof(broker_write), "LUNAR_PRODUCER_REQUEST_FD=%d", w);
            target_env[3] = broker_read; target_env[4] = broker_write;
        }
        if (target_fd != c.target_fd) close(target_fd);
#if defined(__linux__)
        /* The necessary target descriptor remains inherited: sealed shebang
           interpreters may reopen /proc/self/fd/N. Only the private exec-error
           channel must disappear on exec. Standard streams stay host-controlled. */
        if (handoff_cloexec(exec_pipe[1], 1) ||
            (c.target_fd >= 0 && handoff_cloexec(c.target_fd, 0)) ||
            (broker_r >= 0 && (handoff_cloexec(broker_r, 0) || handoff_cloexec(broker_w, 0))))
            child_start_failed(exec_pipe[1], errno, 73);
        int handoff_error = handoff_close_extra(c.target_fd, exec_pipe[1], broker_r, broker_w);
        if (handoff_error) child_start_failed(exec_pipe[1], handoff_error, 73);
#endif
        if (strcmp(c.profile, "fixture-none") != 0) {
            int isolation = lunar_apply_isolation(c.profile, (const char *const *)c.read_paths, c.read_count,
                                                  (const char *const *)c.write_dirs, c.write_count);
            if (isolation != 0) child_start_failed(exec_pipe[1], isolation, 74);
        }
        if (chdir(c.cwd) != 0) child_start_failed(exec_pipe[1], errno, 74);
        if (c.target_fd >= 0) {
#if defined(__linux__)
            fexecve(c.target_fd, c.argv, target_env);
#else
            execve(c.target_path, c.argv, target_env);
#endif
        } else {
            execve(c.target_path, c.argv, target_env);
        }
        child_start_failed(exec_pipe[1], errno, 75);
    }
    close(target_fd);
    close(exec_pipe[1]);
    int exec_error = 0; ssize_t exec_read;
    do { exec_read = read(exec_pipe[0], &exec_error, sizeof(exec_error)); } while (exec_read < 0 && errno == EINTR);
    close(exec_pipe[0]);
    if (exec_read != 0) {
#if defined(__linux__)
        /* A pre-exec refusal is not exec's close-on-exec EOF. Publish the
           negative frame before the guardian stops our private group. */
        emit_frame(frame_fd, c.launch, c.intent, 2, "target_start_failed", NULL, 0, 0);
#endif
        if (guard.enabled) stop_own_guarded_group(&guard);
        kill(child, SIGKILL); waitpid(child, NULL, 0);
#if !defined(__linux__)
        emit_frame(frame_fd, c.launch, c.intent, 2, "target_start_failed", NULL, 0, 0);
#endif
        free_control(&c); return 76;
    }
    pid_t target_group = getpgid(child);
    if (target_group < 0 || target_group != getpgrp() ||
        emit_frame(frame_fd, c.launch, c.intent, 2, "target_started", target_hex, child, target_group) != 0) {
        if (guard.enabled) stop_own_guarded_group(&guard);
        kill(child, SIGKILL); waitpid(child, NULL, 0); free_control(&c); return 77;
    }
    int status; pid_t waited;
    do { waited = waitpid(child, &status, 0); } while (waited < 0 && errno == EINTR);
    if (waited != child) {
        if (guard.enabled) stop_own_guarded_group(&guard);
        free_control(&c); return 77;
    }
    if (drain_supervised_children(&guard) != 0) {
        if (guard.enabled) stop_own_guarded_group(&guard);
        free_control(&c); return 77;
    }
    /* Keep the guardian active across terminal publication. A frame observed
       just before EOF/deadline cannot turn a failed bootstrap exit into zero. */
    check_controller_guard(&guard);
    if (emit_frame(frame_fd, c.launch, c.intent, 3, "terminal", NULL, 0, 0) != 0) {
        if (guard.enabled) stop_own_guarded_group(&guard);
        free_control(&c); close(frame_fd); return 77;
    }
    check_controller_guard(&guard);
    if (finish_controller_guard(&guard) != 0) stop_own_guarded_group(&guard);
    free_control(&c); close(frame_fd);
    if (WIFEXITED(status)) return WEXITSTATUS(status); if (WIFSIGNALED(status)) return 128 + WTERMSIG(status); return 77;
}
