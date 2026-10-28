"""Consume the production B input helpers through real descriptors and Linux ACLs.

These finite C helper tests install no profile, drop no credentials, release no
candidate and establish no whole-scope acceptance. Root positives use only an
already-root test process and a private, disposable directory under /run.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from lunar_evolution.native_bootstrap import native_bootstrap_source_paths

pytestmark = pytest.mark.skipif(
    sys.platform != "linux" or platform.machine().lower() not in {"x86_64", "amd64"},
    reason="actual Linux x86-64 bootstrap and POSIX ACL consumption",
)

_HARNESS = r'''
#define main installed_bootstrap_main
#include "native_bootstrap.c"
#undef main
#include <assert.h>

static uint64_t allowance(void) {
    uint64_t now;
    assert(!wq_now(&now));
    return now + 5000000000ULL;
}

static void path_join(char out[WQ_PATH_BYTES], const char *parent, const char *name) {
    size_t a = strlen(parent), b = strlen(name);
    assert(a + b + 2 < WQ_PATH_BYTES);
    memcpy(out, parent, a);
    out[a] = '/';
    memcpy(out + a + 1, name, b + 1);
}

static void put_acl(int fd, uint32_t uid, uint16_t permission, const char *change,
                    const char *attribute) {
    struct __attribute__((packed)) {
        uint32_t version;
        wq_b_acl_entry_t entries[6];
    } raw = {2, {{1, permission, UINT_MAX}, {2, permission, uid},
        {4, 0, UINT_MAX}, {16, permission, UINT_MAX}, {32, 0, UINT_MAX}, {0, 0, 0}}};
    size_t count = 5;
    if (!strcmp(change, "owner")) raw.entries[0].permissions |= 2;
    if (!strcmp(change, "named")) raw.entries[1].permissions ^= 1;
    if (!strcmp(change, "uid")) raw.entries[1].id += 1;
    if (!strcmp(change, "group")) raw.entries[2].permissions = 1;
    if (!strcmp(change, "mask")) raw.entries[3].permissions |= 2;
    if (!strcmp(change, "other")) raw.entries[4].permissions = 4;
    if (!strcmp(change, "extra")) {
        memmove(&raw.entries[3], &raw.entries[2], 3 * sizeof(raw.entries[0]));
        raw.entries[2] = (wq_b_acl_entry_t){2, permission, uid + 1};
        count = 6;
    }
    if (fsetxattr(fd, attribute, &raw, sizeof(raw.version) + count * sizeof(raw.entries[0]), 0)) {
        if (errno == EOPNOTSUPP || errno == ENOSYS) {
            fprintf(stderr, "test filesystem does not support real POSIX ACL xattrs\n");
            exit(77);
        }
        perror("fsetxattr actual test ACL");
        abort();
    }
}

static int acl_case(const char *path, uint16_t permission, const char *change) {
    int directory = permission == 5;
    if (directory) assert(!mkdir(path, 0700));
    int fd = open(path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW |
                        (directory ? O_DIRECTORY : O_CREAT | O_EXCL), 0600);
    assert(fd >= 0);
    uint32_t uid = getuid() == 65534 ? 65533 : 65534;
    if (strcmp(change, "missing")) put_acl(fd, uid, permission, change, "system.posix_acl_access");
    int expected = !strcmp(change, "exact") || !strcmp(change, "original-fd");
    if (!strcmp(change, "default")) {
        assert(directory);
        put_acl(fd, uid, permission, "exact", "system.posix_acl_default");
    }
    if (!strcmp(change, "removed")) assert(!fremovexattr(fd, "system.posix_acl_access"));
    if (!strcmp(change, "chmod")) assert(!fchmod(fd, directory ? 0500 : 0400));
    if (!strcmp(change, "zero-uid")) uid = 0;
    if (!strcmp(change, "opath")) {
        int original = fd;
        fd = open(path, O_PATH | O_NOFOLLOW | O_CLOEXEC);
        assert(fd >= 0);
        assert(!close(original));
    }
    if (!strcmp(change, "closed")) {
        assert(!close(fd));
        assert(wq_b_input_acl(fd, uid, permission));
        return 0;
    }
    if (!strcmp(change, "original-fd")) {
        assert(!directory);
        char retained[WQ_PATH_BYTES];
        size_t length = strlen(path);
        assert(length + 6 < sizeof(retained));
        memcpy(retained, path, length);
        memcpy(retained + length, ".held", 6);
        assert(!rename(path, retained));
        int replacement = open(path, O_RDONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
        assert(replacement >= 0 && wq_b_input_acl(replacement, uid, permission));
        assert(!close(replacement));
    }
    assert((wq_b_input_acl(fd, uid, permission) == 0) == expected);
    assert(!close(fd));
    return 0;
}

typedef struct {
    control_t control;
    wq_profile_t profile;
    grant_node_t nodes[MAX_GRANT_NODES];
    grant_t grants[MAX_GRANTS];
    char root[WQ_PATH_BYTES], batch[WQ_PATH_BYTES], work[WQ_PATH_BYTES], output[WQ_PATH_BYTES];
    char input[WQ_PATH_BYTES], files[2][WQ_PATH_BYTES], digest[65];
    char *arguments[3];
} layout_t;

static uint32_t add_node(layout_t *layout, const char *path) {
    uint32_t parent = 0;
    char prefix[WQ_PATH_BYTES] = "/";
    const char *cursor = path + 1;
    for (;;) {
        uint32_t found = UINT_MAX;
        for (uint32_t i = 0; i < layout->control.node_count; ++i)
            if (!strcmp(layout->nodes[i].path, prefix)) found = i;
        if (found == UINT_MAX) {
            struct stat info;
            assert(!lstat(prefix, &info));
            found = layout->control.node_count++;
            assert(found < MAX_GRANT_NODES);
            layout->nodes[found] = (grant_node_t){found ? parent : UINT32_MAX, S_ISDIR(info.st_mode) ? 1u : 2u,
                found ? layout->nodes[parent].depth + 1 : 0, info.st_dev, info.st_ino,
                strdup(strrchr(prefix, '/') + 1), strdup(prefix)};
            assert(layout->nodes[found].name && layout->nodes[found].path);
        }
        parent = found;
        if (!*cursor) return found;
        const char *slash = strchr(cursor, '/');
        size_t length = slash ? (size_t)(slash - cursor) : strlen(cursor);
        size_t used = strlen(prefix);
        if (used > 1) prefix[used++] = '/';
        assert(used + length < sizeof(prefix));
        memcpy(prefix + used, cursor, length);
        prefix[used + length] = 0;
        cursor += length;
        if (*cursor == '/') cursor++;
    }
}

static void add_grant(layout_t *layout, const char *path, uint32_t role, int flags) {
    int fd = open(path, flags | O_NOFOLLOW | O_CLOEXEC);
    assert(fd >= 0 && layout->control.grant_count < MAX_GRANTS);
    uint32_t node = add_node(layout, path);
    layout->grants[layout->control.grant_count++] = (grant_t){node, role, fd};
}

static int node_path_order(const void *left, const void *right) {
    return strcmp(((const grant_node_t *)left)->path, ((const grant_node_t *)right)->path);
}

static void canonical_layout(layout_t *layout) {
    const char *paths[MAX_GRANTS];
    for (uint32_t i = 0; i < layout->control.grant_count; ++i)
        paths[i] = layout->nodes[layout->grants[i].node].path;
    qsort(layout->nodes, layout->control.node_count, sizeof(layout->nodes[0]), node_path_order);
    assert(!strcmp(layout->nodes[0].path, "/"));
    layout->nodes[0].parent = UINT32_MAX;
    for (uint32_t i = 1; i < layout->control.node_count; ++i) {
        const char *path = layout->nodes[i].path;
        size_t parent_length = (size_t)(strrchr(path, '/') - path);
        uint32_t parent = 0;
        if (parent_length) {
            for (parent = 1; parent < i; ++parent)
                if (strlen(layout->nodes[parent].path) == parent_length &&
                    !strncmp(path, layout->nodes[parent].path, parent_length)) break;
            assert(parent < i);
        }
        layout->nodes[i].parent = parent;
    }
    for (uint32_t i = 0; i < layout->control.grant_count; ++i) {
        uint32_t node = 0;
        while (node < layout->control.node_count && strcmp(paths[i], layout->nodes[node].path)) node++;
        assert(node < layout->control.node_count);
        layout->grants[i].node = node;
    }
    for (uint32_t i = 1; i < layout->control.grant_count; ++i)
        for (uint32_t j = i; j && strcmp(layout->nodes[layout->grants[j].node].path,
                layout->nodes[layout->grants[j - 1].node].path) < 0; --j) {
            grant_t previous = layout->grants[j - 1];
            layout->grants[j - 1] = layout->grants[j];
            layout->grants[j] = previous;
        }
    layout->control.read_count = layout->control.write_count = 0;
    for (uint32_t i = 0; i < layout->control.grant_count; ++i) {
        if (layout->grants[i].role & 4) layout->control.write_count++;
        else layout->control.read_count++;
        if (layout->grants[i].role & 8) layout->control.cwd_grant = i;
    }
}

static void remove_grant(layout_t *layout, uint32_t index) {
    assert(index < layout->control.grant_count);
    memmove(&layout->grants[index], &layout->grants[index + 1],
            (layout->control.grant_count - index - 1) * sizeof(layout->grants[0]));
    layout->control.grant_count--;
}

static uint32_t input_grant_index(const layout_t *layout, const char *path) {
    for (uint32_t i = 0; i < layout->control.grant_count; ++i)
        if (!strcmp(layout->nodes[layout->grants[i].node].path, path)) return i;
    abort();
}

static void begin_layout(layout_t *layout, const char *root, int kind) {
    memset(layout, 0, sizeof(*layout));
    assert(strlen(root) < sizeof(layout->root));
    strcpy(layout->root, root);
    char name[71];
    memcpy(name, "lunar-", 6);
    memset(name + 6, 'a', 64);
    name[70] = 0;
    path_join(layout->batch, root, name);
    path_join(layout->work, layout->batch, "work");
    path_join(layout->output, layout->batch, "output");
    assert(!mkdir(layout->batch, 0700) && !mkdir(layout->work, 0700) && !mkdir(layout->output, 0700));
    layout->profile.candidate_uid = geteuid() ? geteuid() : 65534;
    layout->profile.candidate_gid = getegid() ? getegid() : 65534;
    if (!geteuid()) {
        assert(!chown(layout->work, layout->profile.candidate_uid, layout->profile.candidate_gid));
        assert(!chown(layout->output, layout->profile.candidate_uid, layout->profile.candidate_gid));
    }
    strcpy(layout->profile.execution_path, root);
    int root_fd = open(root, O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    assert(root_fd >= 0 && !wq_identity(root_fd, &layout->profile.execution_root, 0));
    assert(!close(root_fd));
    layout->control.nodes = layout->nodes;
    layout->control.grants = layout->grants;
    layout->control.cwd = layout->work;
    add_grant(layout, layout->work, 12, O_RDONLY | O_DIRECTORY);
    add_grant(layout, layout->output, 4, O_RDONLY | O_DIRECTORY);
    canonical_layout(layout);
    memset(layout->digest, 'a', 64);
    layout->digest[64] = 0;
    layout->arguments[0] = "/candidate";
    layout->arguments[1] = kind == 1 ? "--lunar-producer-input-v1" : "--lunar-rsi-input-v1";
    layout->arguments[2] = layout->digest;
    layout->control.argv = layout->arguments;
    layout->control.argc = kind ? 3 : 1;
}

static void make_input(layout_t *layout, int kind) {
    path_join(layout->input, layout->batch, kind == 1 ? ".producer-input" : ".rsi-input");
    assert(!mkdir(layout->input, 0700));
    int directory = open(layout->input, O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    assert(directory >= 0);
    for (int i = 0; i < (kind == 1 ? 1 : 2); ++i) {
        path_join(layout->files[i], layout->input, kind == 1 ? "config.json" : i ? "memory.json" : "request.json");
        int fd = open(layout->files[i], O_RDWR | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
        assert(fd >= 0 && write(fd, "{}", 2) == 2);
        put_acl(fd, layout->profile.candidate_uid, 4, "exact", "system.posix_acl_access");
        assert(!close(fd));
        add_grant(layout, layout->files[i], 1, O_PATH);
    }
    put_acl(directory, layout->profile.candidate_uid, 5, "exact", "system.posix_acl_access");
    assert(!close(directory));
}

static int profile_layout_case(const char *root, const char *change) {
    layout_t layout;
    int kind = !strncmp(change, "producer-", 9) ? 1 : !strncmp(change, "rsi-", 4) ? 2 : 0;
    begin_layout(&layout, root, kind);
    if (!strcmp(change, "legacy")) {
        assert(!wq_b_profile_grants(&layout.control, &layout.profile, allowance()));
        return 0;
    }
    if (!strcmp(change, "producer-missing") || !strcmp(change, "rsi-missing")) {
        assert(wq_b_profile_grants(&layout.control, &layout.profile, allowance()));
        return 0;
    }
    const char *suffix = !strcmp(change, "manifest") ? ".producer-input/manifest.json" :
        !strcmp(change, "dynamic") ? ".producer-input/runtime.json" :
        !strcmp(change, "directory") ? ".producer-input" :
        !strcmp(change, "other-attempt") ? "../other/.producer-input/config.json" :
        ".rsi-input/manifest.json";
    char path[WQ_PATH_BYTES];
    path_join(path, layout.batch, suffix);
    /* Only the lexical path gate is under test: the actual descriptor remains
     * the original work directory, and no input helper can accept this grant. */
    uint32_t node = layout.control.node_count++;
    layout.nodes[node].path = path;
    layout.grants[layout.control.grant_count++] = (grant_t){node, 1,
        dup(layout.grants[layout.control.cwd_grant].fd)};
    assert(layout.grants[layout.control.grant_count - 1].fd >= 0);
    assert(wq_b_profile_grants(&layout.control, &layout.profile, allowance()));
    return 0;
}

static int descriptor_count(void) {
    DIR *directory = opendir("/proc/self/fd");
    assert(directory);
    int count = 0;
    struct dirent *entry;
    while ((entry = readdir(directory)))
        if (strcmp(entry->d_name, ".") && strcmp(entry->d_name, "..")) count++;
    assert(!closedir(directory));
    return count;
}

static int root_case(const char *root, const char *change, int kind) {
    assert(!geteuid() && !getegid());
    layout_t layout;
    begin_layout(&layout, root, kind);
    make_input(&layout, kind);
    canonical_layout(&layout);
    int baseline = descriptor_count();
    assert(!wq_b_profile_grants(&layout.control, &layout.profile, allowance()));
    assert(descriptor_count() == baseline);
    uint32_t input_index = input_grant_index(&layout, layout.files[0]);
    grant_t *input = &layout.grants[input_index];
    assert(!wq_b_input_grant(&layout.control, input, &layout.profile, allowance()));
    assert(fcntl(input->fd, F_GETFL) & O_PATH);
    assert(descriptor_count() == baseline);
    if (!strcmp(change, "exact")) return 0;
    if (!strcmp(change, "missing"))
        remove_grant(&layout, input_grant_index(&layout, layout.files[kind == 2 ? 1 : 0]));
    else if (!strcmp(change, "missing-request")) remove_grant(&layout, input_index);
    else if (!strcmp(change, "mixed-files")) {
        make_input(&layout, kind == 1 ? 2 : 1);
        baseline = descriptor_count();
    }
    else if (!strcmp(change, "duplicate")) {
        layout.grants[layout.control.grant_count++] = *input;
    } else if (!strcmp(change, "mixed")) {
        layout.arguments[1] = kind == 1 ? "--lunar-rsi-input-v1" : "--lunar-producer-input-v1";
    } else if (!strcmp(change, "no-marker")) layout.control.argc = 1;
    else if (!strcmp(change, "node-pin")) layout.nodes[input->node].inode++;
    else if (!strcmp(change, "root-pin")) layout.profile.execution_root.inode++;
    else if (!strcmp(change, "role")) input->role = 2;
    else if (!strcmp(change, "fd")) input->fd = layout.grants[layout.control.cwd_grant].fd;
    else if (!strcmp(change, "replace")) {
        char retained[WQ_PATH_BYTES];
        path_join(retained, layout.input, "retained.json");
        assert(!rename(layout.files[0], retained));
        int fresh = open(layout.files[0], O_RDWR | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
        assert(fresh >= 0);
        put_acl(fresh, layout.profile.candidate_uid, 4, "exact", "system.posix_acl_access");
        assert(!close(fresh));
    } else if (!strcmp(change, "hardlink")) {
        char alias[WQ_PATH_BYTES];
        path_join(alias, layout.input, "alias.json");
        assert(!link(layout.files[0], alias));
    } else if (!strcmp(change, "directory-mode")) assert(!chmod(layout.input, 0500));
    else if (!strcmp(change, "file-mode")) assert(!chmod(layout.files[0], 0400));
    else if (!strcmp(change, "default") || !strcmp(change, "extra")) {
        int fd = open(!strcmp(change, "default") ? layout.input : layout.files[0], O_RDONLY | O_CLOEXEC);
        assert(fd >= 0);
        put_acl(fd, layout.profile.candidate_uid, !strcmp(change, "default") ? 5 : 4,
                change, !strcmp(change, "default") ? "system.posix_acl_default" : "system.posix_acl_access");
        assert(!close(fd));
    } else if (!strcmp(change, "expired")) {
        assert(wq_b_profile_grants(&layout.control, &layout.profile, 1));
        assert(wq_b_input_grant(&layout.control, input, &layout.profile, 1));
        assert(descriptor_count() == baseline);
        return 0;
    } else abort();
    assert(wq_b_profile_grants(&layout.control, &layout.profile, allowance()));
    assert(descriptor_count() == baseline);
    return 0;
}

int main(int argc, char **argv) {
    assert(argc >= 3);
    if (!strcmp(argv[1], "kind")) {
        control_t control;
        memset(&control, 0, sizeof(control));
        control.argc = (uint32_t)(argc - 3);
        control.argv = argv + 3;
        assert(wq_b_input_kind(&control) == atoi(argv[2]));
        return 0;
    }
    assert(argc >= 4);
    if (!strcmp(argv[1], "acl")) return acl_case(argv[2], 4, argv[3]);
    if (!strcmp(argv[1], "acl-directory")) return acl_case(argv[2], 5, argv[3]);
    if (!strcmp(argv[1], "layout")) return profile_layout_case(argv[2], argv[3]);
    assert(argc == 5 && !strcmp(argv[1], "root"));
    return root_case(argv[2], argv[3], atoi(argv[4]));
}
'''


@pytest.fixture(scope="module")
def native_input_helper(tmp_path_factory):
    compiler = shutil.which("clang") or shutil.which("cc")
    if compiler is None:
        pytest.skip("native C compiler unavailable")
    paths = native_bootstrap_source_paths()
    assert {path.name for path in paths} == {
        "native_bootstrap.c", "native_producer_isolation.h", "native_whole_scope_bootstrap.h",
        "native_whole_scope_platform.h", "native_whole_scope_protocol.h",
        "native_whole_scope_successor_protocol.h", "native_whole_scope_successor_bootstrap.h",
    }
    directory = tmp_path_factory.mktemp("fixed-u-input-native")
    source = directory / "input.c"
    source.write_text(_HARNESS, encoding="ascii")
    executable = directory / "input"
    subprocess.run(
        [compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-O2", "-pthread", "-I",
         str(paths[0].parent), str(source), "-o", str(executable)],
        check=True, capture_output=True, timeout=30, env={"PATH": os.defpath, "LANG": "C"},
    )
    return executable


def _run(executable, *arguments):
    result = subprocess.run(
        [str(executable), *map(str, arguments)], stdin=subprocess.DEVNULL,
        capture_output=True, check=False, timeout=10, env={"PATH": os.defpath, "LANG": "C"},
    )
    if result.returncode == 77:
        pytest.skip(result.stderr.decode("utf-8", errors="replace").strip())
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")


_PRODUCER = "--lunar-producer-input-v1"
_RSI = "--lunar-rsi-input-v1"
_SHA = "a" * 64


@pytest.mark.parametrize("arguments,expected", [
    (("/candidate",), 0),
    (("/candidate", _PRODUCER, _SHA), 1),
    (("/candidate", _RSI, _SHA), 2),
    (("/candidate", _PRODUCER), -1),
    (("/candidate", _RSI, ""), -1),
    (("/candidate", _PRODUCER, "a" * 63), -1),
    (("/candidate", _PRODUCER, "a" * 65), -1),
    (("/candidate", _RSI, "A" * 64), -1),
    (("/candidate", _RSI, "g" * 64), -1),
    (("/candidate", _PRODUCER, _SHA, "trailing"), -1),
    (("/candidate", _RSI, _SHA, _RSI, _SHA), -1),
    (("/candidate", _PRODUCER, _SHA, _RSI, _SHA), -1),
    (("/candidate", _RSI, _SHA, _PRODUCER, _SHA), -1),
])
def test_actual_c_marker_is_unique_with_one_terminal_lowercase_sha(native_input_helper, arguments, expected):
    _run(native_input_helper, "kind", expected, *arguments)


@pytest.mark.parametrize("kind", ["acl", "acl-directory"])
@pytest.mark.parametrize("change", [
    "exact", "missing", "owner", "named", "uid", "group", "mask", "other",
    "extra", "removed", "chmod", "zero-uid", "opath", "closed",
])
def test_actual_acl_descriptor_rejects_every_permission_or_entry_drift(native_input_helper, tmp_path, kind, change):
    _run(native_input_helper, kind, tmp_path / "original", change)


def test_actual_original_acl_fd_survives_path_replacement(native_input_helper, tmp_path):
    _run(native_input_helper, "acl", tmp_path / "original", "original-fd")


def test_actual_directory_default_acl_is_refused(native_input_helper, tmp_path):
    _run(native_input_helper, "acl-directory", tmp_path / "original", "default")


@pytest.mark.parametrize("change", [
    "legacy", "producer-missing", "rsi-missing", "manifest", "dynamic",
    "directory", "other-attempt", "rsi-manifest",
])
def test_actual_profile_layout_keeps_legacy_and_refuses_unselected_input_domains(native_input_helper, tmp_path, change):
    _run(native_input_helper, "layout", tmp_path, change)


@pytest.mark.skipif(os.geteuid() != 0 or os.getegid() != 0, reason="root-owned original input prerequisite; never elevate")
@pytest.mark.parametrize("kind", [1, 2], ids=["producer", "rsi"])
@pytest.mark.parametrize("change", [
    "exact", "missing", "missing-request", "mixed-files", "duplicate", "mixed", "no-marker", "node-pin", "root-pin", "role",
    "fd", "replace", "hardlink", "directory-mode", "file-mode", "default", "extra", "expired",
])
def test_actual_root_input_grants_bind_original_fd_acl_and_exact_combinations(native_input_helper, kind, change):
    run = Path("/run")
    if not run.is_dir() or run.is_symlink() or run.stat().st_uid != 0 or run.stat().st_mode & 0o022:
        pytest.skip("root-owned nonwritable /run prerequisite; never alter its policy")
    with tempfile.TemporaryDirectory(prefix="lunar-fixed-u-test-", dir=run) as directory:
        _run(native_input_helper, "root", directory, change, kind)
