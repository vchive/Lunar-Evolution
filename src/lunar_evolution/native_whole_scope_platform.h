/* Original Linux filesystem/profile checks shared by the sealed S and B. */
#ifndef LUNAR_NATIVE_WHOLE_SCOPE_PLATFORM_H
#define LUNAR_NATIVE_WHOLE_SCOPE_PLATFORM_H
#include "native_whole_scope_protocol.h"
#include <dirent.h>
#include <grp.h>
#include <linux/capability.h>
#include <linux/magic.h>
#include <linux/stat.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <sys/statfs.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <sys/xattr.h>

/* Local names deliberately do not collide with native_bootstrap.c SHA code. */
typedef struct {
    uint32_t h[8];
    uint64_t n;
    unsigned char b[64];
    size_t used;
} wq_sha_t;
static const uint32_t wq_k[64] = {
    0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
    0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
    0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
    0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
    0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
    0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2};
static inline uint32_t wq_rr(uint32_t x, int n) {
    return x >> n | x << (32 - n);
}
static inline void wq_sha_block(wq_sha_t *c, const unsigned char *p) {
    uint32_t w[64], a, b, d, e, f, g, h, cc;
    for (int i = 0; i < 16; i++)
        w[i] = (uint32_t)p[4 * i] << 24 | (uint32_t)p[4 * i + 1] << 16 |
               (uint32_t)p[4 * i + 2] << 8 | p[4 * i + 3];
    for (int i = 16; i < 64; i++)
        w[i] = w[i - 16] + (wq_rr(w[i - 15], 7) ^ wq_rr(w[i - 15], 18) ^ (w[i - 15] >> 3)) +
               w[i - 7] + (wq_rr(w[i - 2], 17) ^ wq_rr(w[i - 2], 19) ^ (w[i - 2] >> 10));
    a = c->h[0];
    b = c->h[1];
    cc = c->h[2];
    d = c->h[3];
    e = c->h[4];
    f = c->h[5];
    g = c->h[6];
    h = c->h[7];
    for (int i = 0; i < 64; i++) {
        uint32_t t1 =
            h + (wq_rr(e, 6) ^ wq_rr(e, 11) ^ wq_rr(e, 25)) + ((e & f) ^ (~e & g)) + wq_k[i] + w[i];
        uint32_t t2 = (wq_rr(a, 2) ^ wq_rr(a, 13) ^ wq_rr(a, 22)) + ((a & b) ^ (a & cc) ^ (b & cc));
        h = g;
        g = f;
        f = e;
        e = d + t1;
        d = cc;
        cc = b;
        b = a;
        a = t1 + t2;
    }
    c->h[0] += a;
    c->h[1] += b;
    c->h[2] += cc;
    c->h[3] += d;
    c->h[4] += e;
    c->h[5] += f;
    c->h[6] += g;
    c->h[7] += h;
}
static inline void wq_sha_init(wq_sha_t *c) {
    const uint32_t initial[8] = {0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
                                 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19};
    memcpy(c->h, initial, sizeof(initial));
    c->n = 0;
    c->used = 0;
}
static inline void wq_sha_update(wq_sha_t *c, const unsigned char *data, size_t size) {
    c->n += size;
    while (size) {
        size_t take = 64 - c->used;
        if (take > size)
            take = size;
        memcpy(c->b + c->used, data, take);
        c->used += take;
        data += take;
        size -= take;
        if (c->used == 64) {
            wq_sha_block(c, c->b);
            c->used = 0;
        }
    }
}
static inline void wq_sha_final(wq_sha_t *c, char out[65]) {
    uint64_t bits = c->n * 8;
    c->b[c->used++] = 0x80;
    while (c->used != 56) {
        if (c->used == 64) {
            wq_sha_block(c, c->b);
            c->used = 0;
        }
        c->b[c->used++] = 0;
    }
    for (int i = 0; i < 8; i++)
        c->b[56 + i] = (unsigned char)(bits >> (56 - 8 * i));
    wq_sha_block(c, c->b);
    const char *digits = "0123456789abcdef";
    for (int i = 0; i < 32; i++) {
        unsigned char byte = (unsigned char)(c->h[i / 4] >> (24 - 8 * (i % 4)));
        out[2 * i] = digits[byte >> 4];
        out[2 * i + 1] = digits[byte & 15];
    }
    out[64] = 0;
}
static inline int wq_hash_fd(int fd, char out[65], uint64_t deadline) {
    struct stat before, after;
    unsigned char bytes[8192];
    off_t offset = 0;
    wq_sha_t hash;
    if (fstat(fd, &before) || !S_ISREG(before.st_mode) || before.st_size < 0 ||
        before.st_size > 128 * 1024 * 1024)
        return -1;
    wq_sha_init(&hash);
    while (offset < before.st_size) {
        if (wq_remaining(deadline) < 0)
            return -1;
        size_t n = (size_t)(before.st_size - offset);
        if (n > sizeof(bytes))
            n = sizeof(bytes);
        ssize_t got = pread(fd, bytes, n, offset);
        if (got < 0 && errno == EINTR)
            continue;
        if (got <= 0)
            return -1;
        wq_sha_update(&hash, bytes, (size_t)got);
        offset += got;
    }
    if (fstat(fd, &after) || memcmp(&before.st_mtim, &after.st_mtim, sizeof(before.st_mtim)) ||
        memcmp(&before.st_ctim, &after.st_ctim, sizeof(before.st_ctim)) ||
        before.st_dev != after.st_dev || before.st_ino != after.st_ino ||
        before.st_size != after.st_size || wq_remaining(deadline) < 0)
        return -1;
    wq_sha_final(&hash, out);
    return 0;
}
static inline int wq_root_identity(void) {
    uid_t r, e, s;
    gid_t gr, ge, gs;
    return getresuid(&r, &e, &s) || getresgid(&gr, &ge, &gs) || r || e || s || gr || ge || gs;
}
/* Consume the actual original creator descriptor. These pins alone are never
 * a registration capability, and reopening a matching path cannot supply it. */
static inline int wq_publication_check(int fd, const wq_publication_t *pin, uint64_t deadline) {
    struct stat st;
    char digest[65];
    int flags = fcntl(fd, F_GETFL);
    if (wq_remaining(deadline) < 0 || flags < 0 || flags & O_PATH || fstat(fd, &st) ||
        !S_ISREG(st.st_mode) || st.st_uid || st.st_gid || (st.st_mode & 07777) != 0600 ||
        st.st_nlink != 1 || !pin->inode || !pin->size || (uint64_t)st.st_dev != pin->device ||
        st.st_ino != pin->inode || (uint64_t)st.st_size != pin->size ||
        pin->mtime_ns !=
            (uint64_t)st.st_mtim.tv_sec * 1000000000ULL + (uint64_t)st.st_mtim.tv_nsec ||
        pin->ctime_ns !=
            (uint64_t)st.st_ctim.tv_sec * 1000000000ULL + (uint64_t)st.st_ctim.tv_nsec ||
        wq_digest(pin->sha256) || wq_hash_fd(fd, digest, deadline) ||
        memcmp(digest, pin->sha256, 65))
        return -1;
    return 0;
}
static inline int wq_identity(int fd, wq_identity_t *out, int cgroup) {
    struct stat info;
    struct statfs fs;
    struct statx extended;
    if (fstat(fd, &info) || fstatfs(fd, &fs) || (cgroup && fs.f_type != CGROUP2_SUPER_MAGIC) ||
        syscall(SYS_statx, fd, "", AT_EMPTY_PATH | AT_SYMLINK_NOFOLLOW, STATX_INO | STATX_MNT_ID,
                &extended) ||
        !(extended.stx_mask & STATX_MNT_ID))
        return -1;
    memset(out, 0, sizeof(*out));
    out->device = (uint64_t)info.st_dev;
    out->inode = info.st_ino;
    out->mount_id = extended.stx_mnt_id;
    out->uid = info.st_uid;
    out->gid = info.st_gid;
    out->mode = info.st_mode;
    return 0;
}
static inline int wq_identity_equal(const wq_identity_t *a, const wq_identity_t *b) {
    return !memcmp(a, b, sizeof(*a));
}
static inline int wq_fd_distinct(const int *fds, size_t count) {
    for (size_t i = 0; i < count; i++) {
        struct stat a;
        if (fds[i] <= 2 || fstat(fds[i], &a))
            return -1;
        for (size_t j = 0; j < i; j++) {
            struct stat b;
            if (fds[i] == fds[j] || fstat(fds[j], &b) ||
                (a.st_dev == b.st_dev && a.st_ino == b.st_ino &&
                 ((a.st_mode & S_IFMT) == (b.st_mode & S_IFMT))))
                return -1;
        }
    }
    return 0;
}
static inline int wq_sealed(int fd) {
    struct stat info;
    int required = F_SEAL_WRITE | F_SEAL_GROW | F_SEAL_SHRINK | F_SEAL_SEAL;
    int seals = fcntl(fd, F_GET_SEALS);
    return fstat(fd, &info) || !S_ISREG(info.st_mode) || info.st_nlink || seals < 0 ||
           (seals & required) != required;
}
/* Hold every path component until the caller closes this private chain. */
typedef struct {
    int fds[64];
    char names[64][256];
    wq_identity_t pins[64];
    size_t count;
} wq_chain_t;
static inline void wq_chain_close(wq_chain_t *chain) {
    while (chain->count) {
        size_t i = --chain->count;
        int fd = chain->fds[i];
        chain->fds[i] = -1;
        if (fd >= 0)
            close(fd);
    }
}
static inline int wq_chain_check(const wq_chain_t *chain) {
    for (size_t i = 0; i < chain->count; i++) {
        wq_identity_t current;
        if (wq_identity(chain->fds[i], &current, 0) ||
            !wq_identity_equal(&current, &chain->pins[i]))
            return -1;
        if (i) {
            struct stat named, held;
            if (fstatat(chain->fds[i - 1], chain->names[i], &named, AT_SYMLINK_NOFOLLOW) ||
                fstat(chain->fds[i], &held) || named.st_dev != held.st_dev ||
                named.st_ino != held.st_ino ||
                ((named.st_mode & S_IFMT) != (held.st_mode & S_IFMT)))
                return -1;
        }
    }
    return 0;
}
static inline int wq_chain_open(const char *path, wq_chain_t *chain, int final_directory) {
    memset(chain, 0, sizeof(*chain));
    if (!path || path[0] != '/' || strlen(path) >= WQ_PATH_BYTES)
        return -1;
    chain->fds[0] = open("/", O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (chain->fds[0] < 0)
        return -1;
    chain->count = 1;
    if (wq_identity(chain->fds[0], &chain->pins[0], 0))
        goto fail;
    char copy[WQ_PATH_BYTES];
    memcpy(copy, path, strlen(path) + 1);
    char *part = copy + 1;
    while (*part) {
        char *slash = strchr(part, '/');
        if (slash)
            *slash = 0;
        size_t size = strlen(part);
        if (!size || size > 255 || !strcmp(part, ".") || !strcmp(part, "..") || chain->count >= 64)
            goto fail;
        int directory = slash || final_directory;
        int flags = O_RDONLY | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK;
        if (directory)
            flags |= O_DIRECTORY;
        int fd = openat(chain->fds[chain->count - 1], part, flags);
        if (fd < 0)
            goto fail;
        size_t i = chain->count++;
        chain->fds[i] = fd;
        memcpy(chain->names[i], part, size + 1);
        if (wq_identity(fd, &chain->pins[i], 0))
            goto fail;
        if (slash) {
            part = slash + 1;
            if (!*part)
                goto fail;
        } else
            break;
    }
    for (size_t i = 0; i < chain->count; i++)
        if (chain->pins[i].uid || (chain->pins[i].mode & 0022))
            goto fail;
    if (wq_chain_check(chain))
        goto fail;
    return 0;
fail:
    wq_chain_close(chain);
    return -1;
}
static inline int wq_profile_namespaces(const wq_profile_t *profile) {
    const char *names[4] = {"/proc/self/ns/user", "/proc/self/ns/pid", "/proc/self/ns/mnt",
                            "/proc/self/ns/cgroup"};
    for (size_t i = 0; i < 4; i++) {
        struct stat info;
        if (stat(names[i], &info) || profile->namespaces[i].device != (uint64_t)info.st_dev ||
            profile->namespaces[i].inode != info.st_ino)
            return -1;
    }
    return 0;
}
static inline int wq_path_contains(const char *parent, const char *child) {
    size_t n = strlen(parent);
    return !strncmp(parent, child, n) && (child[n] == 0 || child[n] == '/');
}
static inline int wq_load_profile(int fd, const char expected[65], wq_profile_t *profile,
                                  uint64_t deadline) {
    if (wq_root_identity() || setgroups(0, NULL) || getgroups(0, NULL) != 0 ||
        wq_digest(expected) || wq_sealed(fd))
        return -1;
    char digest[65];
    if (wq_hash_fd(fd, digest, deadline) || memcmp(digest, expected, 65))
        return -1;
    struct stat info;
    if (fstat(fd, &info) || info.st_size != (off_t)sizeof(*profile) ||
        pread(fd, profile, sizeof(*profile), 0) != (ssize_t)sizeof(*profile))
        return -1;
    wq_chain_t chain;
    if (wq_chain_open(WQ_PROFILE_PATH, &chain, 0))
        return -1;
    int original = chain.fds[chain.count - 1];
    char current[65];
    struct stat source;
    int invalid = fstat(original, &source) || !S_ISREG(source.st_mode) || source.st_uid ||
                  source.st_gid || (source.st_mode & 07777) != 0600 || source.st_nlink != 1 ||
                  wq_hash_fd(original, current, deadline) || memcmp(current, expected, 65) ||
                  wq_chain_check(&chain);
    wq_chain_close(&chain);
    if (invalid || profile->magic != WQ_PROFILE_MAGIC || profile->version != WQ_VERSION ||
        profile->size != sizeof(*profile) || profile->flags || !profile->candidate_uid ||
        profile->candidate_uid == UINT_MAX || !profile->candidate_gid ||
        profile->candidate_gid == UINT_MAX || profile->group_count > WQ_MAX_GROUPS ||
        profile->readonly_count > WQ_MAX_ROOTS || wq_digest(profile->bootstrap_sha256) ||
        wq_digest(profile->supervisor_sha256) || wq_profile_namespaces(profile))
        return -1;
    for (size_t i = 0; i < WQ_MAX_GROUPS; i++)
        if (i < profile->group_count ? (!profile->groups[i] || profile->groups[i] == UINT_MAX ||
                                        (i && profile->groups[i - 1] >= profile->groups[i]))
                                     : profile->groups[i])
            return -1;
    const wq_identity_t *roots[WQ_MAX_ROOTS + 2] = {&profile->delegation, &profile->execution_root};
    const char *paths[WQ_MAX_ROOTS + 2] = {profile->delegation_path, profile->execution_path};
    for (size_t i = 0; i < profile->readonly_count; i++) {
        roots[i + 2] = &profile->readonly_roots[i];
        paths[i + 2] = profile->readonly_paths[i];
    }
    for (size_t i = 0; i < (size_t)profile->readonly_count + 2; i++) {
        if (!memchr(paths[i], 0, WQ_PATH_BYTES) || paths[i][0] != '/' || !paths[i][1] ||
            roots[i]->reserved || !S_ISDIR(roots[i]->mode) || roots[i]->uid ||
            roots[i]->mode & 0022)
            return -1;
        if (wq_chain_open(paths[i], &chain, 1))
            return -1;
        wq_identity_t identity;
        invalid = wq_identity(chain.fds[chain.count - 1], &identity, i == 0) ||
                  !wq_identity_equal(&identity, roots[i]) || wq_chain_check(&chain);
        wq_chain_close(&chain);
        if (invalid)
            return -1;
        size_t used = strlen(paths[i]) + 1;
        for (size_t k = used; k < WQ_PATH_BYTES; k++)
            if (paths[i][k])
                return -1;
    }
    for (size_t i = 0; i < (size_t)profile->readonly_count + 2; i++) {
        if (wq_path_contains(paths[i], WQ_PROFILE_PATH))
            return -1;
        for (size_t j = 0; j < i; j++)
            if (wq_path_contains(paths[i], paths[j]) || wq_path_contains(paths[j], paths[i]) ||
                (roots[i]->device == roots[j]->device && roots[i]->inode == roots[j]->inode))
                return -1;
    }
    for (size_t i = profile->readonly_count; i < WQ_MAX_ROOTS; i++) {
        wq_identity_t zero = {0};
        char empty[WQ_PATH_BYTES] = {0};
        if (memcmp(&profile->readonly_roots[i], &zero, sizeof(zero)) ||
            memcmp(profile->readonly_paths[i], empty, sizeof(empty)))
            return -1;
    }
    return wq_remaining(deadline) < 0 ? -1 : 0;
}
static inline int wq_profile_binding(const wq_profile_t *profile, const wq_binding_t *binding) {
    return wq_binding_valid(binding) || profile->candidate_uid != binding->candidate_uid ||
           profile->candidate_gid != binding->candidate_gid ||
           profile->group_count != binding->group_count ||
           memcmp(profile->groups, binding->groups, sizeof(profile->groups)) ||
           memcmp(profile->bootstrap_sha256, binding->bootstrap_sha256, 65) ||
           memcmp(profile->supervisor_sha256, binding->supervisor_sha256, 65);
}
#endif
