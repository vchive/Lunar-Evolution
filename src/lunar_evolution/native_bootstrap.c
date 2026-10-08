/*
 * Lunar Evolution trusted producer bootstrap.
 *
 * This is intentionally a small, dependency-free executable.  It reads one
 * bounded binary control record, announces readiness, waits for one release
 * byte, and only then forks/execs the already-bound target. Version2 independently
 * checks original inherited grant and protocol bindings before announcing readiness.
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
#define MAX_GRANT_NODES 256u
#define MAX_GRANTS 81u

typedef struct {
    uint32_t parent, kind, depth;
    uint64_t device, inode;
    char *name, *path;
} grant_node_t;

typedef struct { uint32_t node, role; int fd; } grant_t;

typedef struct {
    char launch[65], intent[65], target_sha[65];
    uint32_t version, node_count, grant_count, cwd_grant;
    int bootstrap_fd;
    grant_node_t *nodes;
    grant_t *grants;
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

#if defined(__linux__)
static uint64_t be64(const unsigned char *p) {
    return ((uint64_t)be32(p) << 32) | be32(p + 4);
}
#endif

static int utf8_valid(const char *value) {
    const unsigned char *p = (const unsigned char *)value;
    while (*p) {
        uint32_t point; unsigned int follow;
        if (*p < 0x80) { ++p; continue; }
        if (*p >= 0xc2 && *p <= 0xdf) { point = *p & 31; follow = 1; }
        else if (*p >= 0xe0 && *p <= 0xef) { point = *p & 15; follow = 2; }
        else if (*p >= 0xf0 && *p <= 0xf4) { point = *p & 7; follow = 3; }
        else return 0;
        unsigned int count = follow;
        ++p;
        while (follow--) { if ((*p & 0xc0) != 0x80) return 0; point = (point << 6) | (*p++ & 63); }
        if ((count == 1 && point < 0x80) || (count == 2 && point < 0x800) ||
            (count == 3 && point < 0x10000) || point > 0x10ffff ||
            (point >= 0xd800 && point <= 0xdfff)) return 0;
    }
    return 1;
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
    if (c->nodes) for (uint32_t i = 0; i < c->node_count; ++i) { free(c->nodes[i].name); free(c->nodes[i].path); }
    free(c->nodes); free(c->grants);
    free(c->argv); free(c->read_paths); free(c->write_dirs); memset(c, 0, sizeof(*c));
}

#if defined(__linux__)
static int node_identity_equal(const grant_node_t *a, const grant_node_t *b) {
    return a->device == b->device && a->inode == b->inode;
}

static int grant_under(const control_t *c, uint32_t node, uint32_t root) {
    for (;;) {
        if (node_identity_equal(&c->nodes[node], &c->nodes[root])) return 1;
        if (node == 0) return 0;
        node = c->nodes[node].parent;
    }
}

static int path_under(const char *path, const char *root) {
    size_t size = strlen(root);
    return strcmp(path, root) == 0 || (size == 1 && root[0] == '/') ||
           (strncmp(path, root, size) == 0 && path[size] == '/');
}

static int parse_control_v2(const unsigned char *buf, size_t total, size_t *position, control_t *c) {
    size_t pos = *position;
    if (pos + 4 > total) return -1;
    uint32_t bootstrap = be32(buf + pos); pos += 4;
    if (c->target_fd <= 2 || bootstrap <= 2 || bootstrap > INT_MAX || bootstrap == (uint32_t)c->target_fd) return -1;
    c->bootstrap_fd = (int)bootstrap;
    if (read_string(buf, total, &pos, &c->target_path, MAX_PATH_BYTES) ||
        c->target_path[0] != '/' || !utf8_valid(c->target_path) || pos + 8 > total || be32(buf + pos) != 1) return -1;
    pos += 4; c->node_count = be32(buf + pos); pos += 4;
    if (!c->node_count || c->node_count > MAX_GRANT_NODES) return -1;
    c->nodes = calloc(c->node_count, sizeof(*c->nodes)); if (!c->nodes) return -1;
    for (uint32_t i = 0; i < c->node_count; ++i) {
        if (pos + 28 > total) return -1;
        grant_node_t *node = &c->nodes[i];
        node->parent = be32(buf + pos); node->kind = be32(buf + pos + 4);
        node->device = be64(buf + pos + 8); node->inode = be64(buf + pos + 16);
        uint32_t size = be32(buf + pos + 24); pos += 28;
        if (!node->inode || (node->kind != 1 && node->kind != 2) || size > MAX_PATH_BYTES || size > total - pos) return -1;
        node->name = calloc((size_t)size + 1, 1); if (!node->name) return -1;
        memcpy(node->name, buf + pos, size); pos += size;
        if (memchr(node->name, 0, size) || !utf8_valid(node->name)) return -1;
        if (!i) {
            if (node->parent != UINT32_MAX || node->kind != 1 || size) return -1;
            node->path = strdup("/");
        } else {
            if (node->parent >= i || c->nodes[node->parent].kind != 1 || !size ||
                strchr(node->name, '/') || !strcmp(node->name, ".") || !strcmp(node->name, "..")) return -1;
            grant_node_t *parent = &c->nodes[node->parent];
            node->depth = parent->depth + 1;
            size_t length = strlen(parent->path) + size + (node->parent ? 1 : 0);
            if (node->depth > 64 || length > MAX_PATH_BYTES) return -1;
            node->path = calloc(length + 1, 1);
            if (node->path) snprintf(node->path, length + 1, "%s%s%s", parent->path, node->parent ? "/" : "", node->name);
        }
        if (!node->path || (i && strcmp(c->nodes[i - 1].path, node->path) >= 0)) return -1;
    }
    if (pos + 4 > total) return -1;
    c->grant_count = be32(buf + pos); pos += 4;
    if (!c->grant_count || c->grant_count > MAX_GRANTS) return -1;
    c->grants = calloc(c->grant_count, sizeof(*c->grants)); if (!c->grants) return -1;
    unsigned char used[MAX_GRANT_NODES] = {0}; uint32_t cwd_count = 0;
    size_t path_bytes = 0;
    for (uint32_t i = 0; i < c->grant_count; ++i) {
        if (pos + 12 > total) return -1;
        grant_t *grant = &c->grants[i];
        grant->node = be32(buf + pos); grant->role = be32(buf + pos + 4);
        uint32_t fd = be32(buf + pos + 8); pos += 12;
        if (grant->node >= c->node_count || fd <= 2 || fd > INT_MAX ||
            (grant->role != 1 && grant->role != 2 && grant->role != 4 && grant->role != 12)) return -1;
        grant->fd = (int)fd;
        grant_node_t *node = &c->nodes[grant->node];
        if (node->kind != (grant->role == 1 ? 2u : 1u) ||
            ((grant->role & 4) && (!grant->node || node_identity_equal(node, &c->nodes[0]))) ||
            (i && strcmp(c->nodes[c->grants[i - 1].node].path, node->path) >= 0)) return -1;
        if (grant->role & 4) ++c->write_count; else ++c->read_count;
        if (grant->role & 8) ++cwd_count;
        path_bytes += strlen(node->path) * ((grant->role & 8) ? 2 : 1);
        for (uint32_t current = grant->node;; current = c->nodes[current].parent) { used[current] = 1; if (!current) break; }
        for (uint32_t j = 0; j < i; ++j) {
            if (c->grants[j].fd == grant->fd || node_identity_equal(node, &c->nodes[c->grants[j].node])) return -1;
        }
    }
    if (c->read_count > 64 || c->write_count > 16 || cwd_count != 1 ||
        c->read_count + c->write_count + cwd_count > 81 || path_bytes > MAX_CONTROL) return -1;
    for (uint32_t i = 0; i < c->node_count; ++i) if (!used[i]) return -1;
    for (uint32_t i = 0; i < c->grant_count; ++i) {
        grant_t *read = &c->grants[i]; if (read->role & 4) continue;
        for (uint32_t j = 0; j < c->grant_count; ++j) {
            grant_t *write = &c->grants[j]; if (!(write->role & 4)) continue;
            const char *rp = c->nodes[read->node].path, *wp = c->nodes[write->node].path;
            if (path_under(rp, wp) || grant_under(c, read->node, write->node) ||
                (read->role == 2 && (path_under(wp, rp) || grant_under(c, write->node, read->node)))) return -1;
        }
    }
    if (pos + 4 > total) return -1;
    c->cwd_grant = be32(buf + pos); pos += 4;
    if (c->cwd_grant >= c->grant_count || c->grants[c->cwd_grant].role != 12) return -1;
    c->cwd = strdup(c->nodes[c->grants[c->cwd_grant].node].path);
    if (!c->cwd) return -1;
    *position = pos; return 0;
}
#endif

static int parse_control(const unsigned char *buf, size_t total, control_t *c) {
    if (total > MAX_CONTROL || total < 4 + 2 + 2 + 64 * 3 + 4 || memcmp(buf, MAGIC, 4) != 0) return -1;
    /* version and flags are two-byte values; version is encoded at offsets 4..5. */
    if (buf[4] != 0 || (buf[5] != 1 && buf[5] != 2) || buf[6] != 0 || buf[7] != 0) return -1;
    c->version = buf[5];
    size_t pos = 8;
    memcpy(c->launch, buf + pos, 64); c->launch[64] = 0; pos += 64;
    memcpy(c->intent, buf + pos, 64); c->intent[64] = 0; pos += 64;
    memcpy(c->target_sha, buf + pos, 64); c->target_sha[64] = 0; pos += 64;
    if (!hex64(c->launch) || !hex64(c->intent) || !hex64(c->target_sha) || pos + 4 > total) return -1;
    c->target_fd = (int32_t)be32(buf + pos); pos += 4;
    if (c->version == 2) {
#if defined(__linux__)
        if (parse_control_v2(buf, total, &pos, c)) return -1;
#else
        return -1;
#endif
    } else {
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
    }
    if (pos + 4 > total) return -1;
    c->argc = be32(buf + pos); pos += 4;
    if (c->argc == 0 || c->argc > MAX_ARGC) return -1;
    c->argv = (char **)calloc(c->argc + 1, sizeof(char *));
    if (!c->argv) return -1;
    for (uint32_t i = 0; i < c->argc; i++) {
        if (read_string(buf, total, &pos, &c->argv[i], MAX_ARG_BYTES) != 0 ||
            (c->version == 2 && !utf8_valid(c->argv[i]))) return -1;
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

static int grant_protocol_pipe(int fd, int access) {
    struct stat info; int flags = fcntl(fd, F_GETFL);
    return flags < 0 || (flags & O_ASYNC) || handoff_pipe(fd, access, &info);
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

static int handoff_close_keep(int *keep, size_t count);

static int handoff_close_extra(int target_fd, int error_fd, int broker_r, int broker_w) {
    int keep[4]; size_t count = 0;
    keep[count++] = error_fd;
    if (target_fd >= 0) keep[count++] = target_fd;
    if (broker_r >= 0) { keep[count++] = broker_r; keep[count++] = broker_w; }
    return handoff_close_keep(keep, count);
}

static int handoff_close_keep(int *keep, size_t count) {
    if (!count || count > MAX_GRANTS + 4) return EINVAL;
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

static int grant_fds_disjoint(const control_t *c, const int *reserved, size_t count) {
    for (uint32_t i = 0; i < c->grant_count; ++i) {
        int fd = c->grants[i].fd;
        if (fd <= 2) return EINVAL;
        for (size_t j = 0; j < count; ++j) if (fd == reserved[j]) return EINVAL;
    }
    return 0;
}

static int grant_close_phase1(const control_t *c, int error_fd, int broker_r, int broker_w) {
    int keep[MAX_GRANTS + 4]; size_t count = 0;
    keep[count++] = error_fd; keep[count++] = c->target_fd;
    if (broker_r >= 0) { keep[count++] = broker_r; keep[count++] = broker_w; }
    for (uint32_t i = 0; i < c->grant_count; ++i) keep[count++] = c->grants[i].fd;
    return handoff_close_keep(keep, count);
}

static int sealed_exec_fd(int fd) {
    struct stat st; int flags = fcntl(fd, F_GETFL);
    int seals = fcntl(fd, F_GET_SEALS);
    int required = F_SEAL_WRITE | F_SEAL_GROW | F_SEAL_SHRINK | F_SEAL_SEAL;
    return fd > 2 && flags >= 0 && (flags & O_ACCMODE) != O_WRONLY && !(flags & O_PATH) &&
        fstat(fd, &st) == 0 && S_ISREG(st.st_mode) && st.st_nlink == 0 &&
        st.st_size > 0 && st.st_size <= 128 * 1024 * 1024 && (st.st_mode & 0111) &&
        seals >= 0 && (seals & required) == required;
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

#if defined(__linux__)
static int grant_stat_matches(const grant_node_t *node, const struct stat *info) {
    return (uint64_t)info->st_dev == node->device && (uint64_t)info->st_ino == node->inode &&
        (node->kind == 1 ? S_ISDIR(info->st_mode) : S_ISREG(info->st_mode));
}

static int validate_grant_graph(const control_t *c, const controller_guard_t *guard) {
    int walked[MAX_GRANT_NODES];
    for (uint32_t i = 0; i < MAX_GRANT_NODES; ++i) walked[i] = -1;
    int error = EINVAL;
    for (uint32_t i = 0; i < c->node_count; ++i) {
        if (guard->enabled && getpid() == guard->pid) check_controller_guard(guard);
        if (guard_deadline_expired(guard)) { error = ECANCELED; goto done; }
        const grant_node_t *node = &c->nodes[i]; struct stat before, opened, after;
        int flags = O_PATH | O_NOFOLLOW | O_CLOEXEC;
        if (node->kind == 1) flags |= O_DIRECTORY;
        if (!i) {
            if (lstat("/", &before)) { error = errno; goto done; }
            walked[i] = open("/", flags);
        } else {
            if (fstatat(walked[node->parent], node->name, &before, AT_SYMLINK_NOFOLLOW)) { error = errno; goto done; }
            walked[i] = openat(walked[node->parent], node->name, flags);
        }
        if (walked[i] < 0 || fstat(walked[i], &opened)) { error = errno; goto done; }
        if ((!i ? lstat("/", &after) : fstatat(walked[node->parent], node->name, &after, AT_SYMLINK_NOFOLLOW))) {
            error = errno; goto done;
        }
        if (!grant_stat_matches(node, &before) || !grant_stat_matches(node, &opened) || !grant_stat_matches(node, &after)) goto done;
    }
    for (uint32_t i = 0; i < c->grant_count; ++i) {
        const grant_t *grant = &c->grants[i]; struct stat info;
        int flags = fcntl(grant->fd, F_GETFL);
        if (flags < 0 || (flags & O_ACCMODE) != O_RDONLY || (flags & O_ASYNC) || fstat(grant->fd, &info) ||
            !grant_stat_matches(&c->nodes[grant->node], &info) || (grant->role == 1 && info.st_nlink != 1)) goto done;
    }
    /* Check every retained original parent link again, not merely the leaf. */
    for (uint32_t i = 0; i < c->node_count; ++i) {
        const grant_node_t *node = &c->nodes[i]; struct stat info;
        if ((!i ? lstat("/", &info) : fstatat(walked[node->parent], node->name, &info, AT_SYMLINK_NOFOLLOW)) ||
            !grant_stat_matches(node, &info)) goto done;
    }
    if (guard->enabled && getpid() == guard->pid) check_controller_guard(guard);
    error = guard_deadline_expired(guard) ? ECANCELED : 0;
done:
    for (uint32_t i = c->node_count; i > 0; --i) if (walked[i - 1] >= 0) close(walked[i - 1]);
    return error ? error : 0;
}

static void close_original_grants(const control_t *c) {
    for (uint32_t i = 0; i < c->grant_count; ++i) close(c->grants[i].fd);
}
#endif

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

#if defined(__linux__)
/* Linux6.9 introduced the process-group signal scope. Header availability is
   not runtime support: the private watcher must actually probe signal0/flag4.
   These syscall entries are shared by all supported native ABIs. */
#if defined(__x86_64__) || defined(__aarch64__) || defined(__i386__)
#ifndef __NR_pidfd_send_signal
#define __NR_pidfd_send_signal 424
#endif
#define LUNAR_PIDFD_SIGNAL_PROCESS_GROUP 4U
#endif

typedef struct {
    int group_fd, owner_fd, finish_fd, ack_fd;
    pid_t self;
    uint64_t deadline_ns;
} independent_guard_t;

static int independent_group_signal(int fd, int sig) {
#if defined(__x86_64__) || defined(__aarch64__) || defined(__i386__)
    return (int)syscall(__NR_pidfd_send_signal, fd, sig, NULL, LUNAR_PIDFD_SIGNAL_PROCESS_GROUP);
#else
    (void)fd; (void)sig; errno = ENOTSUP; return -1;
#endif
}

static _Noreturn void independent_stop(const independent_guard_t *guard) {
    /* This original pidfd references the original group even after its leader
       is reaped. Empty-group ESRCH never causes numeric PGID lookup/retry. */
    (void)independent_group_signal(guard->group_fd, SIGKILL);
    _exit(78);
}

static int guardian_timeout(uint64_t deadline_ns) {
    uint64_t now;
    if (!deadline_ns || native_monotonic_ns(&now) || now >= deadline_ns) return -1;
    uint64_t left = deadline_ns - now;
    return left >= 100000000 ? 100 : (int)((left + 999999) / 1000000);
}

static int guardian_nonblock(int fd) {
    int flags = fcntl(fd, F_GETFL);
    return flags < 0 || fcntl(fd, F_SETFL, flags | O_NONBLOCK) || handoff_cloexec(fd, 1);
}

static int guardian_distinct_pipes(const int *fds, const int *access, size_t count) {
    struct stat info[6];
    if (!count || count > 6) return -1;
    for (size_t i = 0; i < count; ++i) {
        if (grant_protocol_pipe(fds[i], access[i]) || fstat(fds[i], &info[i])) return -1;
        for (size_t j = 0; j < i; ++j)
            if (fds[i] == fds[j] || (info[i].st_dev == info[j].st_dev && info[i].st_ino == info[j].st_ino)) return -1;
    }
    return 0;
}

static void independent_check(const independent_guard_t *guard) {
    if (getpid() != guard->self || getpgrp() != guard->self || getsid(0) != guard->self ||
        guardian_timeout(guard->deadline_ns) < 0) independent_stop(guard);
    struct pollfd observed[2] = {{guard->owner_fd, POLLIN, 0}, {guard->group_fd, POLLIN, 0}};
    int result;
    do { result = poll(observed, 2, 0); } while (result < 0 && errno == EINTR);
    if (result != 0 || guardian_timeout(guard->deadline_ns) < 0) independent_stop(guard);
}

static void independent_poll(const independent_guard_t *guard, int fd, short events) {
    independent_check(guard);
    struct pollfd observed[3] = {{guard->owner_fd, POLLIN, 0}, {guard->group_fd, POLLIN, 0}, {fd, events, 0}};
    int timeout = guardian_timeout(guard->deadline_ns);
    if (timeout < 0) independent_stop(guard);
    int result = poll(observed, 3, timeout);
    if (result < 0 && errno == EINTR) return;
    if (result < 0 || observed[0].revents || observed[1].revents ||
        (observed[2].revents & (POLLERR | POLLNVAL))) independent_stop(guard);
    independent_check(guard);
}

static void independent_write(const independent_guard_t *guard, unsigned char value, int check_after) {
    for (;;) {
        independent_check(guard);
        ssize_t result = write(guard->ack_fd, &value, 1);
        if (result == 1) { if (check_after) independent_check(guard); return; }
        if (result < 0 && errno == EINTR) continue;
        if (result < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
            independent_poll(guard, guard->ack_fd, POLLOUT); continue;
        }
        independent_stop(guard);
    }
}

static int independent_watch_main(int argc, char **argv) {
    independent_guard_t guard; memset(&guard, 0, sizeof(guard));
    if (argc != 11 || strcmp(argv[1], "--group-pidfd") || strcmp(argv[3], "--controller-lifeline-fd") ||
        strcmp(argv[5], "--guardian-finish-fd") || strcmp(argv[7], "--guardian-ack-fd") ||
        strcmp(argv[9], "--deadline-monotonic-ns") ||
        parse_handoff_fd(argv[2], &guard.group_fd) || parse_handoff_fd(argv[4], &guard.owner_fd) ||
        parse_handoff_fd(argv[6], &guard.finish_fd) || parse_handoff_fd(argv[8], &guard.ack_fd) ||
        parse_deadline_arg(argv[10], &guard.deadline_ns)) return 64;
    int pipes[] = {guard.owner_fd, guard.finish_fd, guard.ack_fd};
    int access[] = {O_RDONLY, O_RDONLY, O_WRONLY};
    guard.self = getpid();
    if (getpgrp() != guard.self || getsid(0) != guard.self ||
        guardian_distinct_pipes(pipes, access, 3)) return 64;
    for (size_t i = 0; i < 3; ++i) if (pipes[i] == guard.group_fd) return 64;
    /* Wrong/non-pid descriptors and unsupported kernels refuse before R. No
       numeric-PGID or flags0 group fallback exists. Host owns exact pre-ready
       bootstrap/watcher Popen cleanup, including this allocation/probe failure. */
    if (independent_group_signal(guard.group_fd, 0)) return 64;
    struct sigaction ignored;
    memset(&ignored, 0, sizeof(ignored)); ignored.sa_handler = SIG_IGN;
    if (sigemptyset(&ignored.sa_mask) || sigaction(SIGPIPE, &ignored, NULL) ||
        guardian_nonblock(guard.finish_fd) || guardian_nonblock(guard.ack_fd)) independent_stop(&guard);
    independent_check(&guard);
    int keep[] = {guard.group_fd, guard.owner_fd, guard.finish_fd, guard.ack_fd};
    if (handoff_close_keep(keep, 4)) independent_stop(&guard);
    for (int fd = 0; fd <= 2; ++fd) if (close(fd) && errno != EBADF) independent_stop(&guard);
    independent_write(&guard, 'R', 1);
    int received = 0;
    for (;;) {
        independent_check(&guard);
        unsigned char bytes[2]; ssize_t size = read(guard.finish_fd, bytes, sizeof(bytes));
        if (size > 0) {
            if (received || size != 1 || bytes[0] != 'F') independent_stop(&guard);
            received = 1;
        } else if (!size) {
            if (!received) independent_stop(&guard);
            break;
        } else if (errno != EINTR && errno != EAGAIN && errno != EWOULDBLOCK) independent_stop(&guard);
        independent_poll(&guard, guard.finish_fd, POLLIN);
    }
    independent_check(&guard);
    /* Once the exact D byte is accepted, bootstrap is allowed to retire. A
       post-write pidfd poll would race that expected clean exit and falsely
       classify normal watcher retirement as bootstrap death. */
    independent_write(&guard, 'D', 0);
    if (close(guard.ack_fd)) independent_stop(&guard);
    /* Nothing may block here after retiring independent supervision. Bootstrap
       has drained targets and still observes its original pthread/lifeline. */
    return 0;
}

static void bootstrap_guardian_poll(const controller_guard_t *guard, int fd, short events) {
    check_controller_guard(guard);
    int timeout = guardian_timeout(guard->deadline_ns);
    if (timeout < 0) stop_own_guarded_group(guard);
    struct pollfd observed[2] = {{guard->fd, POLLIN, 0}, {fd, events, 0}};
    int result = poll(observed, 2, timeout);
    if (result < 0 && errno == EINTR) return;
    if (result < 0 || observed[0].revents || (observed[1].revents & (POLLERR | POLLNVAL)))
        stop_own_guarded_group(guard);
    check_controller_guard(guard);
}

static void finish_independent_guardian(const controller_guard_t *guard, int finish_fd, int ack_fd) {
    for (;;) {
        check_controller_guard(guard);
        unsigned char value = 'F'; ssize_t size = write(finish_fd, &value, 1);
        if (size == 1) break;
        if (size < 0 && errno == EINTR) continue;
        if (size < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
            bootstrap_guardian_poll(guard, finish_fd, POLLOUT); continue;
        }
        stop_own_guarded_group(guard);
    }
    if (close(finish_fd)) stop_own_guarded_group(guard);
    int received = 0;
    for (;;) {
        check_controller_guard(guard);
        unsigned char bytes[2]; ssize_t size = read(ack_fd, bytes, sizeof(bytes));
        if (size > 0) {
            if (received || size != 1 || bytes[0] != 'D') stop_own_guarded_group(guard);
            received = 1;
        } else if (!size) {
            if (!received) stop_own_guarded_group(guard);
            break;
        } else if (errno != EINTR && errno != EAGAIN && errno != EWOULDBLOCK) stop_own_guarded_group(guard);
        bootstrap_guardian_poll(guard, ack_fd, POLLIN);
    }
    if (close(ack_fd)) stop_own_guarded_group(guard);
    check_controller_guard(guard);
}
#endif

int main(int argc, char **argv) {
#if defined(__linux__)
    if (argc > 1 && !strcmp(argv[1], "--group-pidfd")) return independent_watch_main(argc, argv);
#endif
    if ((argc != 7 && argc != 9 && argc != 11 && argc != 13 && argc != 15 && argc != 19) || strcmp(argv[1], "--control-fd") != 0 || strcmp(argv[3], "--gate-fd") != 0 || strcmp(argv[5], "--frame-fd") != 0) return 64;
    int control_fd, gate_fd, frame_fd;
    int guardian_finish_fd = -1, guardian_ack_fd = -1;
    if (parse_fd_arg(argv[2], &control_fd) || parse_fd_arg(argv[4], &gate_fd) || parse_fd_arg(argv[6], &frame_fd)) return 64;
#if defined(__linux__)
    if (parse_handoff_fd(argv[2], &control_fd) || parse_handoff_fd(argv[4], &gate_fd) ||
        parse_handoff_fd(argv[6], &frame_fd) || control_fd == gate_fd ||
        control_fd == frame_fd || gate_fd == frame_fd) return 64;
#endif
    if (argc >= 13) {
#if defined(__linux__)
        if (strcmp(argv[11], "--child-supervision") != 0 ||
            strcmp(argv[12], "linux-subreaper-v1") != 0) return 64;
#else
        return 64;
#endif
    }
    if (argc == 15 || argc == 19) {
#if defined(__linux__)
        if (strcmp(argv[13], "--grant-object-binding") || strcmp(argv[14], "linux-held-grants-v1")) return 64;
        int original_lifeline;
        /* Negotiate v2 before reading or closing any protocol handle. A regular
           file/FIFO or wrong direction must not become a blocking control route. */
        if (parse_handoff_fd(argv[8], &original_lifeline) ||
            grant_protocol_pipe(control_fd, O_RDONLY) || grant_protocol_pipe(gate_fd, O_RDONLY) ||
            grant_protocol_pipe(frame_fd, O_WRONLY) || grant_protocol_pipe(original_lifeline, O_RDONLY)) return 64;
        if (argc == 19) {
            if (strcmp(argv[15], "--guardian-finish-fd") || strcmp(argv[17], "--guardian-ack-fd") ||
                parse_handoff_fd(argv[16], &guardian_finish_fd) || parse_handoff_fd(argv[18], &guardian_ack_fd)) return 64;
            int pipes[] = {control_fd, gate_fd, frame_fd, original_lifeline, guardian_finish_fd, guardian_ack_fd};
            int access[] = {O_RDONLY, O_RDONLY, O_WRONLY, O_RDONLY, O_WRONLY, O_RDONLY};
            if (guardian_distinct_pipes(pipes, access, 6) || guardian_nonblock(guardian_finish_fd) ||
                guardian_nonblock(guardian_ack_fd)) return 64;
        }
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
    control_t c; memset(&c, 0, sizeof(c));
    if (n < 0 || used > MAX_CONTROL || parse_control(raw, used, &c) != 0) { free(raw); free_control(&c); return 66; }
    free(raw);
#if defined(__linux__)
    int broker_r = -1, broker_w = -1;
    if ((c.version == 2) != (argc == 15 || argc == 19)) { free_control(&c); return 66; }
    if (c.version == 2) {
        int reserved[] = {control_fd, gate_fd, frame_fd, guard.fd, guardian_finish_fd, guardian_ack_fd,
                          c.target_fd, c.bootstrap_fd};
        for (size_t i = 0; i < 6; ++i) {
            if (c.target_fd == reserved[i] || c.bootstrap_fd == reserved[i]) { free_control(&c); return 73; }
        }
        struct stat executable, bootstrap;
        if (!sealed_exec_fd(c.target_fd) || !sealed_exec_fd(c.bootstrap_fd) ||
            stat("/proc/self/exe", &executable) || fstat(c.bootstrap_fd, &bootstrap) ||
            executable.st_dev != bootstrap.st_dev || executable.st_ino != bootstrap.st_ino ||
            handoff_broker(getenv("LUNAR_PRODUCER_RESPONSE_FD"), getenv("LUNAR_PRODUCER_REQUEST_FD"),
                           reserved, sizeof(reserved) / sizeof(reserved[0]), &broker_r, &broker_w) ||
            grant_fds_disjoint(&c, reserved, sizeof(reserved) / sizeof(reserved[0]))) {
            free_control(&c); return 73;
        }
        int broker_reserved[] = {broker_r, broker_w};
        if ((broker_r >= 0 && (grant_protocol_pipe(broker_r, O_RDONLY) || grant_protocol_pipe(broker_w, O_WRONLY))) ||
            grant_fds_disjoint(&c, broker_reserved, 2) || validate_grant_graph(&c, &guard)) { free_control(&c); return 73; }
    }
#endif
    close(control_fd);
    if (emit_frame(frame_fd, c.launch, c.intent, 1, "bootstrap_ready", NULL, 0, 0) != 0) { free_control(&c); return 67; }
    unsigned char token;
    if (read_full(gate_fd, &token, 1) != 0 || token != '1') { free_control(&c); return 68; }
    unsigned char extra;
    ssize_t extra_read;
    do { extra_read = read(gate_fd, &extra, 1); } while (extra_read < 0 && errno == EINTR);
    if (extra_read != 0) { free_control(&c); return 68; }
    if (c.version == 2) {
#if defined(__linux__)
        if (validate_grant_graph(&c, &guard)) {
            emit_frame(frame_fd, c.launch, c.intent, 2, "target_start_failed", NULL, 0, 0);
            free_control(&c); return 73;
        }
#endif
    }
    close(gate_fd);

#if defined(__linux__)
    if (c.version == 1) {
    int reserved[] = {control_fd, gate_fd, frame_fd, guard.fd, c.target_fd};
    if ((c.target_fd >= 0 && (c.target_fd <= 2 || c.target_fd == control_fd ||
         c.target_fd == gate_fd || c.target_fd == frame_fd || c.target_fd == guard.fd)) ||
        handoff_broker(getenv("LUNAR_PRODUCER_RESPONSE_FD"), getenv("LUNAR_PRODUCER_REQUEST_FD"),
                       reserved, sizeof(reserved) / sizeof(reserved[0]), &broker_r, &broker_w)) {
        emit_frame(frame_fd, c.launch, c.intent, 2, "target_start_failed", NULL, 0, 0);
        free_control(&c); return 73;
    }
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
#if defined(__linux__)
    if (c.version == 2) {
        int dynamic[] = {target_fd, exec_pipe[0], exec_pipe[1], c.target_fd, c.bootstrap_fd,
                         frame_fd, guard.fd, broker_r, broker_w, guardian_finish_fd, guardian_ack_fd};
        if (grant_fds_disjoint(&c, dynamic, sizeof(dynamic) / sizeof(dynamic[0])) ||
            validate_grant_graph(&c, &guard)) {
            close(exec_pipe[0]); close(exec_pipe[1]); close(target_fd);
            emit_frame(frame_fd, c.launch, c.intent, 2, "target_start_failed", NULL, 0, 0);
            free_control(&c); return 73;
        }
    }
#endif
    pid_t child = fork();
    if (child < 0) { close(exec_pipe[0]); close(exec_pipe[1]); close(target_fd); emit_frame(frame_fd, c.launch, c.intent, 2, "target_start_failed", NULL, 0, 0); free_control(&c); return 71; }
    if (child == 0) {
#if defined(__linux__)
        if (c.version == 2) {
            int dynamic[] = {target_fd, exec_pipe[0], exec_pipe[1], c.target_fd, c.bootstrap_fd,
                             frame_fd, guard.fd, broker_r, broker_w, guardian_finish_fd, guardian_ack_fd};
            if (grant_fds_disjoint(&c, dynamic, sizeof(dynamic) / sizeof(dynamic[0])))
                child_start_failed(exec_pipe[1], EINVAL, 73);
        }
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
        int handoff_error = c.version == 2 ? grant_close_phase1(&c, exec_pipe[1], broker_r, broker_w) :
            handoff_close_extra(c.target_fd, exec_pipe[1], broker_r, broker_w);
        if (handoff_error) child_start_failed(exec_pipe[1], handoff_error, 73);
        if (c.version == 2) {
            int checked = validate_grant_graph(&c, &guard);
            if (checked) child_start_failed(exec_pipe[1], checked, 74);
            if (fchdir(c.grants[c.cwd_grant].fd)) child_start_failed(exec_pipe[1], errno, 74);
            lunar_grant_fd_t original[MAX_GRANTS];
            for (uint32_t i = 0; i < c.grant_count; ++i) {
                original[i].fd = c.grants[i].fd; original[i].role = c.grants[i].role;
            }
            int isolation = lunar_apply_grant_isolation(original, c.grant_count);
            if (isolation) child_start_failed(exec_pipe[1], isolation, 74);
            close_original_grants(&c);
            handoff_error = handoff_close_extra(c.target_fd, exec_pipe[1], broker_r, broker_w);
            if (handoff_error) child_start_failed(exec_pipe[1], handoff_error, 73);
            if (guard_deadline_expired(&guard)) child_start_failed(exec_pipe[1], ECANCELED, 74);
        } else {
#endif
        if (strcmp(c.profile, "fixture-none") != 0) {
            int isolation = lunar_apply_isolation(c.profile, (const char *const *)c.read_paths, c.read_count,
                                                  (const char *const *)c.write_dirs, c.write_count);
            if (isolation != 0) child_start_failed(exec_pipe[1], isolation, 74);
        }
        if (chdir(c.cwd) != 0) child_start_failed(exec_pipe[1], errno, 74);
#if defined(__linux__)
        }
#endif
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
#if defined(__linux__)
    if (c.version == 2) { close_original_grants(&c); close(c.bootstrap_fd); }
#endif
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
#if defined(__linux__)
    if (guardian_finish_fd >= 0) finish_independent_guardian(&guard, guardian_finish_fd, guardian_ack_fd);
#else
    (void)guardian_finish_fd; (void)guardian_ack_fd;
#endif
    if (finish_controller_guard(&guard) != 0) stop_own_guarded_group(&guard);
    free_control(&c); close(frame_fd);
    if (WIFEXITED(status)) return WEXITSTATUS(status); if (WIFSIGNALED(status)) return 128 + WTERMSIG(status); return 77;
}
