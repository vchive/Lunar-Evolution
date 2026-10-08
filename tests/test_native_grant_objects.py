"""Inert Linux original-object wire, Landlock, CWD and descriptor closure fixtures.

Raw fixture tables intentionally bypass the host encoder to exercise C refusal paths.
They confer no production admission authority; native targets are disposable local C.
"""
from __future__ import annotations

import fcntl
import json
import os
import shutil
import signal
import struct
import subprocess
import sys
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest
from _native_target_fixture import compile_native_target
from test_native_bootstrap import _launch
from test_native_fd_handoff import _fault_bootstrap, _sealed
from test_native_trusted_controller_death import _frame

from lunar_evolution.native_bootstrap import (
    build_native_bootstrap_artifact,
    native_bootstrap_source_path,
)

pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="actual Linux original-grant boundary")

_TARGET = r'''
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>
int main(int argc, char **argv) {
    if (argc < 8) return 2;
    struct stat cwd;
    if (stat(".", &cwd) || (unsigned long long)cwd.st_dev != strtoull(argv[3], NULL, 10) ||
        (unsigned long long)cwd.st_ino != strtoull(argv[4], NULL, 10)) return 3;
    int target = atoi(argv[5]), r = -1, w = -1;
    const char *response = getenv("LUNAR_PRODUCER_RESPONSE_FD");
    const char *request = getenv("LUNAR_PRODUCER_REQUEST_FD");
    if (response && request) { r = atoi(response); w = atoi(request); }
    for (int fd = 3; fd < 4096; ++fd) {
        if (fd == target || fd == r || fd == w) continue;
        errno = 0; if (fcntl(fd, F_GETFD) != -1 || errno != EBADF) return 4;
    }
    if (!strcmp(argv[7], "noexec")) {
        if (argc != 9) return 10;
        pid_t child = fork(); if (child < 0) return 11;
        if (!child) {
            char *args[] = {argv[8], NULL}; char *env[] = {NULL};
            errno = 0; execve(argv[8], args, env); _exit(errno == EACCES ? 0 : 12);
        }
        int status;
        if (waitpid(child, &status, 0) != child || !WIFEXITED(status) || WEXITSTATUS(status)) return 13;
    }
    int approved = open(argv[1], O_RDONLY); char bytes[8];
    if (approved < 0 || read(approved, bytes, sizeof(bytes)) != 8 || memcmp(bytes, "approved", 8)) return 5;
    close(approved);
    errno = 0; int denied = open(argv[2], O_RDONLY);
    if (denied >= 0 || errno != EACCES) return 6;
    int marker = open("marker", O_CREAT | O_WRONLY, 0600);
    if (marker < 0 || write(marker, "ran", 3) != 3 || close(marker)) return 7;
    int output = open(argv[6], O_CREAT | O_WRONLY, 0600);
    if (output < 0 || write(output, "out", 3) != 3 || close(output)) return 8;
    if (!strcmp(argv[7], "broker")) {
        char reply[4];
        if (r < 0 || w < 0 || write(w, "ping", 4) != 4 || read(r, reply, 4) != 4 || memcmp(reply, "pong", 4)) return 9;
    }
    puts("{\"original_cwd\":true,\"original_read\":true,\"closed\":true}");
    return 0;
}
'''


@pytest.fixture(scope="module")
def compiled(tmp_path_factory):
    root = tmp_path_factory.mktemp("grant-objects-native")
    source, target = root / "target.c", root / "target"
    source.write_text(_TARGET)
    compile_native_target(source, target)
    return target, build_native_bootstrap_artifact(root / "install")


@pytest.fixture(scope="module")
def parser(tmp_path_factory):
    root = tmp_path_factory.mktemp("grant-objects-parser")
    source, target = root / "parser.c", root / "parser"
    source.write_text('#define main bootstrap_fixture_main\n'
                      f'#include "{native_bootstrap_source_path()}"\n#undef main\n'
                      'int main(void) { unsigned char raw[MAX_CONTROL+1]; size_t size=fread(raw,1,sizeof(raw),stdin);'
                      'control_t c; memset(&c,0,sizeof(c)); int status=parse_control(raw,size,&c);'
                      'free_control(&c); printf("%d\\n",status); return 0; }\n')
    compiler = shutil.which("clang") or shutil.which("cc")
    assert compiler
    result = subprocess.run([compiler, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-pthread",
                             str(source), "-o", str(target)], capture_output=True, check=False, timeout=30)
    (root / "compiler.stderr").write_bytes(result.stderr)
    assert result.returncode == 0, result.stderr
    return target


def _parsed(parser, data):
    result = subprocess.run([str(parser)], input=_wire(data), capture_output=True, check=False, timeout=3)
    assert result.returncode == 0, result.stderr
    return int(result.stdout)


def _graph(paths):
    names = {"/"}
    for path in paths:
        names.update(str(item) for item in (path, *path.parents))
    ordered = sorted(names)
    indexes = {name: index for index, name in enumerate(ordered)}
    nodes = []
    for name in ordered:
        path = Path(name)
        info = path.stat(follow_symlinks=False)
        nodes.append({"parent": 0xFFFFFFFF if name == "/" else indexes[str(path.parent)],
                      "kind": 1 if path.is_dir() else 2, "device": info.st_dev,
                      "inode": info.st_ino, "name": "" if name == "/" else path.name,
                      "path": name})
    return nodes, indexes


def _string(value):
    value = value.encode() if isinstance(value, str) else value
    return struct.pack(">I", len(value)) + value


def _wire(data):
    launch = data.launch
    result = bytearray(b"LNB1\x00\x02\x00\x00")
    for value in (launch.launch_sha256, launch.intent_sha256, launch.target_executable_identity):
        result.extend(value.encode())
    result.extend(struct.pack(">II", data.target_fd, data.bootstrap_fd))
    result.extend(_string(str(data.target)))
    result.extend(struct.pack(">II", data.isolation_kind, len(data.nodes)))
    for node in data.nodes:
        result.extend(struct.pack(">IIQQ", node["parent"], node["kind"], node["device"], node["inode"]))
        result.extend(_string(node["name"]))
    result.extend(struct.pack(">I", len(data.grants)))
    for grant in data.grants:
        result.extend(struct.pack(">III", grant["node"], grant["role"], grant["fd"]))
    result.extend(struct.pack(">II", data.cwd_index, len(data.argv)))
    for item in data.argv:
        result.extend(_string(item))
    return bytes(result)


@contextmanager
def _start(tmp_path, compiled, *, mutate=None, raw=None, anchors="opath", broker=False,
           bootstrap=None, flag=True, shared_output=False, noexec=False, wrong_bootstrap=False,
           readonly_directory=False):
    target, artifact = compiled
    selected = bootstrap or artifact.path
    working, output, inputs = tmp_path / "work", tmp_path / "output", tmp_path / "inputs"
    for path in (working, output, inputs):
        path.mkdir(mode=0o700)
    if shared_output:
        output = working
    approved, secret = inputs / "config.json", tmp_path / "secret"
    approved.write_bytes(b"approved")
    approved.chmod(0o600 if anchors == "readwrite" else 0o400)
    secret.write_bytes(b"private")
    probe = None
    if noexec:
        probe = inputs / "probe"
        probe.write_bytes(target.read_bytes())
        probe.chmod(0o700)
    with ExitStack() as stack:
        descriptors = set()

        def close(fd):
            if fd in descriptors:
                os.close(fd)
                descriptors.remove(fd)

        def owned(fd):
            descriptors.add(fd)
            stack.callback(close, fd)
            return fd

        def pipe():
            return tuple(owned(fd) for fd in os.pipe())

        control_r, control_w = pipe()
        gate_r, gate_w = pipe()
        frame_r, frame_w = pipe()
        owner_r, _owner_w = pipe()
        target_fd = stack.enter_context(_sealed(target))
        bootstrap_fd = stack.enter_context(_sealed(selected))
        declared_bootstrap = stack.enter_context(_sealed(target)) if wrong_bootstrap else bootstrap_fd
        sentinel_fd = owned(os.open(secret, os.O_RDONLY | os.O_CLOEXEC))
        paths = sorted({inputs if readonly_directory else approved, working, output,
                        *((probe,) if probe else ())}, key=str)
        nodes, indexes = _graph(paths)
        grants = []
        for path in paths:
            is_file = path in {approved, probe}
            access = os.O_PATH if anchors == "opath" else (os.O_RDWR if is_file and anchors == "readwrite" else os.O_RDONLY)
            fd = owned(os.open(path, access | os.O_NOFOLLOW | os.O_CLOEXEC | (0 if is_file else os.O_DIRECTORY)))
            grants.append({"node": indexes[str(path)], "fd": fd,
                           "role": 1 if is_file else (2 if path == inputs else (12 if path == working else 4))})
        inherited = [control_r, gate_r, frame_w, owner_r, target_fd, bootstrap_fd, sentinel_fd,
                     *(grant["fd"] for grant in grants)]
        if wrong_bootstrap:
            inherited.append(declared_bootstrap)
        env = {"PATH": os.defpath, "LANG": "C"}
        broker_request = broker_response = None
        if broker:
            request_r, request_w = pipe()
            response_r, response_w = pipe()
            inherited.extend((request_w, response_r))
            env.update(LUNAR_PRODUCER_REQUEST_FD=str(request_w), LUNAR_PRODUCER_RESPONSE_FD=str(response_r))
            broker_request, broker_response = request_r, response_w
        info = working.stat()
        data = SimpleNamespace(
            launch=_launch(target), target=target, target_fd=target_fd, bootstrap_fd=declared_bootstrap,
            nodes=nodes, grants=grants, cwd_index=next(i for i, grant in enumerate(grants) if grant["role"] == 12),
            isolation_kind=1, argv=[str(target), str(approved), str(secret), str(info.st_dev), str(info.st_ino),
                                    str(target_fd), str(output / "output-marker"), "broker" if broker else "plain"],
            reserved={"control": control_r, "gate": gate_r, "frame": frame_w, "owner": owner_r,
                      "target": target_fd, "bootstrap": bootstrap_fd, "stdin": 0, "stdout": 1, "stderr": 2},
        )
        if noexec:
            data.argv[7] = "noexec"
            data.argv.append(str(probe))
        if broker:
            data.reserved.update(broker_r=response_r, broker_w=request_w)
        if mutate:
            mutate(data)
        payload = raw(data, _wire(data)) if raw else _wire(data)
        command = [str(selected), "--control-fd", str(control_r), "--gate-fd", str(gate_r), "--frame-fd", str(frame_w),
                   "--controller-lifeline-fd", str(owner_r), "--deadline-monotonic-ns", str(time.monotonic_ns() + 15_000_000_000),
                   "--child-supervision", "linux-subreaper-v1"]
        if flag:
            command.extend(("--grant-object-binding", "linux-held-grants-v1"))
        process = subprocess.Popen(command, executable=f"/proc/self/fd/{bootstrap_fd}",
                                   pass_fds=tuple(inherited), close_fds=True, start_new_session=True,
                                   env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   cwd="/")
        close(control_r)
        close(gate_r)
        close(frame_w)
        close(owner_r)
        try:
            offset = 0
            while offset < len(payload):
                try:
                    offset += os.write(control_w, payload[offset:])
                except BrokenPipeError:
                    break
            close(control_w)
            yield SimpleNamespace(process=process, frame=frame_r, gate=gate_w, close=close,
                                  working=working, output=output, approved=approved, inputs=inputs,
                                  data=data, request=broker_request, response=broker_response)
        finally:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.wait(timeout=3)
            process.stdout.close()
            process.stderr.close()


def _release(fixture):
    assert _frame(fixture.frame).kind == "bootstrap_ready"
    os.write(fixture.gate, b"1")
    fixture.close(fixture.gate)


def _refused(fixture, *, ready=False):
    if ready:
        assert _frame(fixture.frame).kind == "target_start_failed"
    stdout, stderr = fixture.process.communicate(timeout=5)
    assert fixture.process.returncode != 0, stderr
    assert stdout == b""
    assert not (fixture.working / "marker").exists()
    assert not (fixture.output / "output-marker").exists()


@pytest.mark.parametrize("anchors", ["opath", "readonly"])
@pytest.mark.parametrize("broker", [False, True])
@pytest.mark.parametrize("shared_output", [False, True])
def test_actual_original_landlock_cwd_and_two_phase_fd_closure(tmp_path, compiled, anchors, broker, shared_output):
    with _start(tmp_path, compiled, anchors=anchors, broker=broker, shared_output=shared_output) as fixture:
        if broker:
            os.write(fixture.response, b"pong")
        _release(fixture)
        assert _frame(fixture.frame).kind == "target_started"
        assert _frame(fixture.frame).kind == "terminal"
        stdout, stderr = fixture.process.communicate(timeout=5)
        assert fixture.process.returncode == 0, stderr
        assert json.loads(stdout) == {"original_cwd": True, "original_read": True, "closed": True}
        assert (fixture.working / "marker").read_bytes() == b"ran"
        if broker:
            assert os.read(fixture.request, 4) == b"ping"


@pytest.mark.parametrize("alias", ["control", "gate", "frame", "owner", "target", "bootstrap", "stdin", "stdout", "stderr",
                                  "broker_r", "broker_w"])
def test_static_grant_alias_refused_while_protocol_numbers_still_live(tmp_path, compiled, alias):
    def mutate(data):
        data.grants[0]["fd"] = data.reserved[alias]
    with _start(tmp_path, compiled, mutate=mutate, broker=alias.startswith("broker")) as fixture:
        _refused(fixture)


@pytest.mark.parametrize("channel", ["broker_r", "broker_w"])
def test_v2_broker_endpoints_cannot_arrive_armed_for_async_notification(tmp_path, compiled, channel):
    def mutate(data):
        descriptor = data.reserved[channel]
        fcntl.fcntl(descriptor, fcntl.F_SETFL, fcntl.fcntl(descriptor, fcntl.F_GETFL) | os.O_ASYNC)
    with _start(tmp_path, compiled, mutate=mutate, broker=True) as fixture:
        _refused(fixture)


@pytest.mark.parametrize("role", [0, 3, 5, 8, 15, 16, 0xFFFFFFFF])
def test_unknown_or_conflicting_role_masks_refused(tmp_path, compiled, role):
    with _start(tmp_path, compiled, mutate=lambda data: data.grants[0].update(role=role)) as fixture:
        _refused(fixture)


@pytest.mark.parametrize("case", ["parent-forward", "parent-file", "kind", "inode-zero", "device", "inode",
                                  "component-dot", "component-dotdot", "component-slash", "component-nul", "component-utf8",
                                  "root-parent", "root-component", "grant-index", "cwd-index", "missing-cwd", "duplicate-fd",
                                  "unknown-isolation", "argv-nul", "argv-utf8"])
def test_graph_and_fixed_field_malformations_refuse_before_ready(tmp_path, compiled, case):
    def mutate(data):
        index = data.grants[0]["node"]
        node = data.nodes[index]
        if case == "parent-forward":
            node["parent"] = index
        elif case == "parent-file":
            data.nodes[node["parent"]]["kind"] = 2
        elif case == "kind":
            node["kind"] = 3
        elif case == "inode-zero":
            node["inode"] = 0
        elif case in {"device", "inode"}:
            node[case] += 1
        elif case.startswith("component-"):
            node["name"] = {"component-dot": ".", "component-dotdot": "..", "component-slash": "a/b",
                            "component-nul": b"a\0b", "component-utf8": b"\xc0\x80"}[case]
        elif case == "root-parent":
            data.nodes[0]["parent"] = 0
        elif case == "root-component":
            data.nodes[0]["name"] = "root"
        elif case == "grant-index":
            data.grants[0]["node"] = len(data.nodes)
        elif case == "cwd-index":
            data.cwd_index = len(data.grants)
        elif case == "missing-cwd":
            data.grants[data.cwd_index]["role"] = 4
        elif case == "duplicate-fd":
            data.grants[1]["fd"] = data.grants[0]["fd"]
        elif case == "unknown-isolation":
            data.isolation_kind = 2
        elif case == "argv-nul":
            data.argv.append(b"a\0b")
        elif case == "argv-utf8":
            data.argv.append(b"\xed\xa0\x80")
    with _start(tmp_path, compiled, mutate=mutate) as fixture:
        _refused(fixture)


@pytest.mark.parametrize("raw_case", ["version", "flags", "truncated", "suffix", "oversize", "node-count", "grant-count", "argc"])
def test_raw_bounds_and_exact_frame_end(tmp_path, compiled, raw_case):
    def raw(data, encoded):
        if raw_case == "version":
            return encoded[:5] + b"\x03" + encoded[6:]
        if raw_case == "flags":
            return encoded[:7] + b"\x01" + encoded[8:]
        if raw_case == "truncated":
            return encoded[:-1]
        if raw_case == "suffix":
            return encoded + b"x"
        if raw_case == "oversize":
            return encoded + b"x" * (65537 - len(encoded))
        if raw_case == "node-count":
            position = 208 + len(_string(str(data.target))) + 4
            return encoded[:position] + struct.pack(">I", 257) + encoded[position + 4:]
        if raw_case == "grant-count":
            position = 208 + len(_string(str(data.target))) + 8
            position += sum(24 + len(_string(node["name"])) for node in data.nodes)
            return encoded[:position] + struct.pack(">I", 82) + encoded[position + 4:]
        data.argv = [str(data.target)] * 65
        return _wire(data)
    with _start(tmp_path, compiled, raw=raw) as fixture:
        _refused(fixture)


def test_v2_without_explicit_binding_flag_is_not_a_formal_upgrade(tmp_path, compiled):
    with _start(tmp_path, compiled, flag=False) as fixture:
        _refused(fixture)


def test_declared_sealed_bootstrap_must_be_actual_executing_object(tmp_path, compiled):
    with _start(tmp_path, compiled, wrong_bootstrap=True) as fixture:
        _refused(fixture)


def test_protected_readable_executable_does_not_gain_execute_authority(tmp_path, compiled):
    with _start(tmp_path, compiled, noexec=True) as fixture:
        _release(fixture)
        assert _frame(fixture.frame).kind == "target_started"
        assert _frame(fixture.frame).kind == "terminal"
        stdout, stderr = fixture.process.communicate(timeout=5)
        assert fixture.process.returncode == 0, stderr
        assert json.loads(stdout)["original_read"] is True


@pytest.mark.parametrize("anchors", ["opath", "readonly"])
def test_readonly_directory_rule_keeps_scope_and_closes_the_original_dir_fd(tmp_path, compiled, anchors):
    with _start(tmp_path, compiled, anchors=anchors, readonly_directory=True) as fixture:
        _release(fixture)
        assert _frame(fixture.frame).kind == "target_started"
        assert _frame(fixture.frame).kind == "terminal"
        stdout, stderr = fixture.process.communicate(timeout=5)
        assert fixture.process.returncode == 0, stderr
        assert json.loads(stdout)["closed"] is True


def test_readwrite_protected_anchor_is_not_accepted_as_a_read_grant(tmp_path, compiled):
    with _start(tmp_path, compiled, anchors="readwrite") as fixture:
        _refused(fixture)


def test_protected_hardlink_refuses_before_ready(tmp_path, compiled):
    def mutate(data):
        protected = data.nodes[data.grants[0]["node"]]["path"]
        os.link(protected, str(Path(protected).with_name("alias")))
    with _start(tmp_path, compiled, mutate=mutate) as fixture:
        _refused(fixture)


@pytest.mark.parametrize("case", ["protected-under-write", "read-directory-above-write", "read-directory-below-write",
                                  "same-object-grants", "orphan-node", "noncanonical-nodes", "noncanonical-grants", "root-write-alias"])
def test_parser_independently_refuses_authority_overlap_and_unused_graph(tmp_path, compiled, parser, case):
    with _start(tmp_path, compiled) as fixture:
        data = fixture.data
        assert _parsed(parser, data) == 0
        read = data.grants[0]
        write = data.grants[-1]
        if case == "root-write-alias":
            # No read grants remain: an independent whole-root write refusal is needed.
            data.grants = [grant for grant in data.grants if grant["role"] & 4]
            nodes, indexes = _graph([fixture.working, fixture.output])
            for grant in data.grants:
                grant["node"] = indexes[data.nodes[grant["node"]]["path"]]
            data.nodes = nodes
            data.cwd_index = next(i for i, grant in enumerate(data.grants) if grant["role"] == 12)
            assert _parsed(parser, data) == 0
            root = nodes[0]
            nodes[data.grants[-1]["node"]].update(device=root["device"], inode=root["inode"])
        elif case == "protected-under-write":
            parent = data.nodes[data.nodes[read["node"]]["parent"]]
            data.nodes[write["node"]].update(device=parent["device"], inode=parent["inode"])
        elif case == "read-directory-above-write":
            # Promote its whole original parent to a read directory in a minimal graph.
            read["node"] = data.nodes[read["node"]]["parent"]
            read["role"] = 2
            orphan = next(i for i, node in enumerate(data.nodes) if node["path"] == str(fixture.approved))
            data.nodes.pop(orphan)
            for grant in data.grants:
                if grant["node"] > orphan:
                    grant["node"] -= 1
            for node in data.nodes:
                if node["parent"] != 0xFFFFFFFF and node["parent"] > orphan:
                    node["parent"] -= 1
            original_parent = data.nodes[data.nodes[write["node"]]["parent"]]
            data.nodes[read["node"]].update(device=original_parent["device"], inode=original_parent["inode"])
        elif case == "read-directory-below-write":
            read["node"] = data.nodes[read["node"]]["parent"]
            read["role"] = 2
            # An orphan alone refuses too; remove it before proving the identity intersection.
            orphan = next(i for i, node in enumerate(data.nodes) if node["path"] == str(fixture.approved))
            data.nodes.pop(orphan)
            for grant in data.grants:
                if grant["node"] > orphan:
                    grant["node"] -= 1
            for node in data.nodes:
                if node["parent"] != 0xFFFFFFFF and node["parent"] > orphan:
                    node["parent"] -= 1
            read_parent = data.nodes[data.nodes[read["node"]]["parent"]]
            data.nodes[write["node"]].update(device=read_parent["device"], inode=read_parent["inode"])
        elif case == "same-object-grants":
            approved = data.nodes[read["node"]]
            data.nodes[write["node"]].update(device=approved["device"], inode=approved["inode"])
        elif case == "orphan-node":
            node = dict(data.nodes[-1])
            node.update(name="zz-orphan", path="unused")
            data.nodes.append(node)
        elif case == "noncanonical-nodes":
            data.nodes[-1]["name"] = "aaa"
        elif case == "noncanonical-grants":
            data.grants[0], data.grants[1] = data.grants[1], data.grants[0]
        assert _parsed(parser, data) == -1


@pytest.mark.parametrize("subject", ["input", "work", "ancestor"])
@pytest.mark.parametrize("replacement", ["directory-or-file", "symlink"])
def test_original_binding_drift_between_ready_and_release_refuses(tmp_path, compiled, subject, replacement):
    with _start(tmp_path, compiled) as fixture:
        assert _frame(fixture.frame).kind == "bootstrap_ready"
        path = {"input": fixture.approved, "work": fixture.working, "ancestor": fixture.inputs}[subject]
        moved = path.with_name(path.name + "-original")
        path.rename(moved)
        if replacement == "symlink":
            path.symlink_to(moved, target_is_directory=subject != "input")
        elif subject == "input":
            path.write_bytes(b"approved")
        else:
            path.mkdir()
        os.write(fixture.gate, b"1")
        fixture.close(fixture.gate)
        _refused(fixture, ready=True)


@pytest.mark.parametrize("collision", ["target_fd", "exec_pipe[0]", "exec_pipe[1]"])
def test_dynamic_grant_fd_collision_refuses_before_child_closes_or_dup2(tmp_path, compiled, collision):
    bootstrap = _fault_bootstrap(tmp_path, "", ("pid_t child = fork();", f"c.grants[0].fd = {collision}; pid_t child = fork();"))
    with _start(tmp_path, compiled, bootstrap=bootstrap) as fixture:
        _release(fixture)
        _refused(fixture, ready=True)


@pytest.mark.parametrize("failure_phase", [1, 2])
def test_each_close_phase_is_a_mandatory_pre_exec_boundary(tmp_path, compiled, failure_phase):
    # Only replace the named wrapper body, leaving the other closure phase intact.
    if failure_phase == 1:
        anchor = "return handoff_close_keep(keep, count);\n}\n\nstatic int sealed_exec_fd"
        changed = "return handoff_close_keep(keep, count) ? EIO : EIO;\n}\n\nstatic int sealed_exec_fd"
    else:
        anchor = "return handoff_close_keep(keep, count);\n}\n\nstatic int handoff_close_keep"
        changed = "return handoff_close_keep(keep, count) ? EIO : EIO;\n}\n\nstatic int handoff_close_keep"
    bootstrap = _fault_bootstrap(tmp_path, "", (anchor, changed))
    with _start(tmp_path, compiled, bootstrap=bootstrap) as fixture:
        _release(fixture)
        _refused(fixture, ready=True)


@pytest.mark.parametrize("subject", ["control", "gate", "frame", "lifeline"])
@pytest.mark.parametrize("kind", ["regular-file", "named-fifo", "wrong-direction", "async"])
def test_explicit_v2_static_channels_have_anonymous_pipe_type_and_direction_before_read(tmp_path, compiled, subject, kind):
    with ExitStack() as stack:
        pipes = {}
        for role in ("control", "gate", "frame", "lifeline"):
            ends = os.pipe()
            for fd in ends:
                stack.callback(os.close, fd)
            pipes[role] = ends
        declared = {role: ends[1] if role == "frame" else ends[0] for role, ends in pipes.items()}
        expected_access = os.O_WRONLY if subject == "frame" else os.O_RDONLY
        inherited = list(declared.values())
        if kind == "wrong-direction":
            declared[subject] = pipes[subject][0 if subject == "frame" else 1]
        elif kind == "async":
            descriptor = declared[subject]
            fcntl.fcntl(descriptor, fcntl.F_SETFL, fcntl.fcntl(descriptor, fcntl.F_GETFL) | os.O_ASYNC)
        else:
            path = tmp_path / "invalid-protocol"
            if kind == "named-fifo":
                os.mkfifo(path, 0o600)
                support = os.open(path, os.O_RDWR | os.O_NONBLOCK)
                stack.callback(os.close, support)
            else:
                path.write_bytes(b"inert regular bytes")
            descriptor = os.open(path, expected_access | os.O_NONBLOCK | os.O_CLOEXEC)
            stack.callback(os.close, descriptor)
            declared[subject] = descriptor
        inherited.append(declared[subject])
        command = [str(compiled[1].path), "--control-fd", str(declared["control"]),
                   "--gate-fd", str(declared["gate"]), "--frame-fd", str(declared["frame"]),
                   "--controller-lifeline-fd", str(declared["lifeline"]), "--deadline-monotonic-ns",
                   str(time.monotonic_ns() + 15_000_000_000), "--child-supervision", "linux-subreaper-v1",
                   "--grant-object-binding", "linux-held-grants-v1"]
        process = subprocess.Popen(command, pass_fds=tuple(set(inherited)), close_fds=True, start_new_session=True,
                                   env={"PATH": os.defpath, "LANG": "C"}, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            # No control bytes and all fixture writers remain open: attempting
            # to read rather than validate this handle would block and time out.
            stdout, stderr = process.communicate(timeout=3)
            assert process.returncode == 64, stderr
            assert stdout == b""
        finally:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            process.wait(timeout=3)
            process.stdout.close()
            process.stderr.close()
