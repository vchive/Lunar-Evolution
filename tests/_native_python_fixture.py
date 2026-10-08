"""Trusted-host-only CPython compatibility fixture, never production admission.

The original-v2 native boundary seals the static launcher. The launcher execs
explicit installed CPython/loader/stdlib bytes which remain trusted host files.
No runtime inventory DTO or fixture grant becomes production launch authority.
"""
from __future__ import annotations

import os
import selectors
import signal
import subprocess
import sys
import sysconfig
import time
from contextlib import ExitStack, contextmanager
from pathlib import Path
from types import SimpleNamespace

from _native_target_fixture import compile_native_target
from test_native_bootstrap import _launch
from test_native_fd_handoff import _sealed
from test_native_grant_objects import _graph, _wire

from lunar_evolution.native_bootstrap import NativeBootstrapError, build_native_bootstrap_artifact

LAUNCHER = r'''
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <unistd.h>
int main(int argc, char **argv) {
    /* interpreter/script/sdk/decoy/output/deadline/target/mode */
    if (argc != 9) return 20;
    const char *read_arg = getenv("LUNAR_PRODUCER_RESPONSE_FD");
    const char *write_arg = getenv("LUNAR_PRODUCER_REQUEST_FD");
    if (!read_arg || !write_arg) return 21;
    int r = atoi(read_arg), w = atoi(write_arg), target = atoi(argv[7]);
    if (r <= 2 || w <= 2 || target <= 2 || r == w || r == target || w == target) return 22;
    for (int fd = 3; fd < 4096; ++fd) {
        if (fd == r || fd == w || fd == target) continue;
        errno = 0;
        if (fcntl(fd, F_GETFD) != -1 || errno != EBADF) return 23;
    }
    if (close(target)) return 24;
    /* A test-only hostile Python environment projection proves -I ignores it.
       Native bootstrap itself never forwards caller Python/provider settings. */
    if (setenv("PYTHONPATH", argv[4], 1) || setenv("PYTHONUSERBASE", argv[4], 1)) return 25;
    char *args[] = {argv[1], "-I", "-S", "-B", argv[2], argv[3], argv[4], argv[5], argv[6], argv[8], NULL};
    execv(argv[1], args);
    return 26;
}
'''


def prepare_python_fixture(root):
    if sys.implementation.name != "cpython":
        raise RuntimeError("fixture requires explicitly installed CPython")
    interpreter = Path(sys.executable).resolve(strict=True)
    if interpreter.parent.name != "bin" or not interpreter.is_file():
        raise RuntimeError("unsupported explicit CPython fixture layout")
    # Only named CI layout choices: no home/root scans, ldd, imports discovery,
    # package manager or runtime inventory interpreted as a read permission.
    selected = {interpreter.parent, Path(sysconfig.get_path("stdlib")).resolve(strict=True)}
    prefix_lib = interpreter.parent.parent / "lib"
    if prefix_lib.is_dir():
        selected.add(prefix_lib.resolve(strict=True))
    for name in ("/lib", "/lib64", "/usr/lib", "/usr/lib64"):
        path = Path(name)
        if path.is_dir():
            selected.add(path.resolve(strict=True))
    if any(path == Path("/") or path == Path.home() for path in selected):
        raise RuntimeError("overbroad fixture runtime root")
    directories = tuple(sorted((path for path in selected if not any(
        path != other and path.is_relative_to(other) for other in selected)), key=str))
    if len(directories) > 8:
        raise RuntimeError("unbounded fixture runtime roots")
    files = tuple(Path(name).resolve(strict=True) for name in ("/etc/ld.so.cache",)
                  if Path(name).is_file())
    sdk = root / "sdk"
    source_package = Path(__file__).resolve().parents[1] / "src/lunar_evolution"
    sources = tuple(sorted(source_package.rglob("*.py")))
    if not sources or len(sources) > 1024:
        raise RuntimeError("unbounded fixture SDK source")
    copied = 0
    for source in sources:
        if "__pycache__" in source.parts or source.is_symlink():
            raise RuntimeError("unsafe fixture SDK source")
        relative = source.relative_to(source_package)
        destination = sdk / "lunar_evolution" / relative
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        content = source.read_bytes()
        copied += len(content)
        if len(content) > 8 * 1024 * 1024 or copied > 64 * 1024 * 1024:
            raise RuntimeError("unbounded fixture SDK bytes")
        destination.write_bytes(content)
        destination.chmod(0o400)
    launcher_source, launcher = root / "launcher.c", root / "launcher"
    launcher_source.write_text(LAUNCHER, encoding="utf-8")
    try:
        compile_native_target(launcher_source, launcher)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        (root / "launcher-first-compile.stdout").write_bytes(exc.stdout or b"")
        (root / "launcher-first-compile.stderr").write_bytes(exc.stderr or b"")
        raise
    try:
        artifact = build_native_bootstrap_artifact(root / "bootstrap")
    except NativeBootstrapError as exc:
        cause = exc.__cause__
        (root / "bootstrap-first-compile.stdout").write_bytes(getattr(cause, "stdout", None) or b"")
        (root / "bootstrap-first-compile.stderr").write_bytes(getattr(cause, "stderr", None) or b"")
        raise
    return SimpleNamespace(interpreter=interpreter, runtime_directories=directories,
                           runtime_files=files, sdk=sdk, launcher=launcher, artifact=artifact)


@contextmanager
def start_python_fixture(tmp_path, prepared, script, *, mode="plain", endpoint_fault=None):
    working, output, inputs, decoy = (tmp_path / name for name in ("work", "output", "input", "decoy"))
    for path in (working, output, inputs, decoy):
        path.mkdir(mode=0o700)
    script_path = inputs / "fixture.py"
    script_path.write_text(script, encoding="utf-8")
    script_path.chmod(0o400)
    for directory in (working, inputs, decoy):
        for name in ("lunar_decoy", "sitecustomize", "usercustomize"):
            (directory / f"{name}.py").write_text(
                f"from pathlib import Path\nPath({str(working / (name + '-loaded'))!r}).write_text('loaded')\nVALUE = 42\n",
                encoding="utf-8",
            )
    outside = tmp_path / "ungranted-sentinel"
    outside.write_bytes(b"private fixture bytes")
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
        request_r, request_w = pipe()
        response_r, response_w = pipe()
        target_fd = stack.enter_context(_sealed(prepared.launcher))
        bootstrap_fd = stack.enter_context(_sealed(prepared.artifact.path))
        sentinel = owned(os.open(outside, os.O_RDONLY | os.O_CLOEXEC))
        # Keep the hostile PYTHONPATH directory readable: -I, rather than
        # Landlock denying its bytes, must exclude the import decoy.
        roles = {path: 2 for path in (*prepared.runtime_directories, prepared.sdk, inputs, decoy)}
        roles.update({path: 1 for path in prepared.runtime_files})
        roles.update({working: 12, output: 4})
        paths = sorted(roles, key=str)
        nodes, indexes = _graph(paths)
        grants = []
        for path in paths:
            fd = owned(os.open(path, os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC
                               | (os.O_DIRECTORY if roles[path] != 1 else 0)))
            grants.append({"node": indexes[str(path)], "role": roles[path], "fd": fd})
        deadline_ns = time.monotonic_ns() + 20_000_000_000
        data = SimpleNamespace(
            launch=_launch(prepared.launcher), target=prepared.launcher,
            target_fd=target_fd, bootstrap_fd=bootstrap_fd, nodes=nodes, grants=grants,
            cwd_index=next(i for i, grant in enumerate(grants) if grant["role"] == 12),
            isolation_kind=1,
            argv=[str(prepared.launcher), str(prepared.interpreter), str(script_path), str(prepared.sdk),
                  str(decoy), str(output), str(deadline_ns), str(target_fd), mode],
        )
        env = {"PATH": os.defpath, "LANG": "C", "LUNAR_PRODUCER_REQUEST_FD": str(request_w),
               "LUNAR_PRODUCER_RESPONSE_FD": str(response_r)}
        if endpoint_fault == "reversed":
            env.update(LUNAR_PRODUCER_REQUEST_FD=str(response_r), LUNAR_PRODUCER_RESPONSE_FD=str(request_w))
        elif endpoint_fault == "same":
            env["LUNAR_PRODUCER_REQUEST_FD"] = str(response_r)
        elif endpoint_fault == "regular":
            env["LUNAR_PRODUCER_RESPONSE_FD"] = str(sentinel)
        inherited = (control_r, gate_r, frame_w, owner_r, request_w, response_r,
                     target_fd, bootstrap_fd, sentinel, *(grant["fd"] for grant in grants))
        process = subprocess.Popen(
            [str(prepared.artifact.path), "--control-fd", str(control_r), "--gate-fd", str(gate_r),
             "--frame-fd", str(frame_w), "--controller-lifeline-fd", str(owner_r),
             "--deadline-monotonic-ns", str(deadline_ns), "--child-supervision", "linux-subreaper-v1",
             "--grant-object-binding", "linux-held-grants-v1"],
            executable=f"/proc/self/fd/{bootstrap_fd}", pass_fds=inherited,
            close_fds=True, start_new_session=True, cwd="/", env=env,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        try:
            for fd in (control_r, gate_r, frame_w, owner_r, request_w, response_r):
                close(fd)
            payload = _wire(data)
            offset = 0
            while offset < len(payload):
                try:
                    offset += os.write(control_w, payload[offset:])
                except BrokenPipeError:
                    break
            close(control_w)
            yield SimpleNamespace(process=process, frame=frame_r, gate=gate_w, close=close,
                                  request=request_r, response=response_w, working=working,
                                  output=output, inputs=inputs, decoy=decoy, script=script_path,
                                  deadline_ns=deadline_ns, owned_fds=descriptors, sentinel=outside,
                                  target_request_fd=request_w, target_response_fd=response_r,
                                  launch=data.launch)
        finally:
            active = sys.exc_info()[1]
            if process.poll() is None:
                # This unreaped original Popen child still owns its private PGID.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            try:
                stdout, stderr = process.communicate(timeout=3)
                if process.returncode != 0 or active is not None:
                    (tmp_path / "first-startup.stdout").write_bytes(stdout)
                    (tmp_path / "first-startup.stderr").write_bytes(stderr)
            finally:
                process.stdout.close()
                process.stderr.close()


def read_request(fixture):
    os.set_blocking(fixture.request, False)
    data = bytearray()
    with selectors.DefaultSelector() as watcher:
        watcher.register(fixture.request, selectors.EVENT_READ)
        while not data.endswith(b"\n"):
            remaining = (fixture.deadline_ns - time.monotonic_ns()) / 1_000_000_000
            if remaining <= 0 or not watcher.select(min(remaining, 5)):
                raise AssertionError("private Python request deadline")
            chunk = os.read(fixture.request, 1025 - len(data))
            if not chunk:
                raise AssertionError("private Python request missing")
            data.extend(chunk)
            if len(data) > 1024:
                raise AssertionError("unbounded private Python request")
    return bytes(data)


def respond(fixture, content):
    os.set_blocking(fixture.response, False)
    offset = 0
    with selectors.DefaultSelector() as watcher:
        watcher.register(fixture.response, selectors.EVENT_WRITE)
        while offset < len(content):
            remaining = (fixture.deadline_ns - time.monotonic_ns()) / 1_000_000_000
            if remaining <= 0 or not watcher.select(min(remaining, 5)):
                raise AssertionError("private Python response deadline")
            try:
                offset += os.write(fixture.response, content[offset:offset + 65536])
            except BrokenPipeError:
                break  # The deliberately oversized negative receiver has exited.
    fixture.close(fixture.response)


def collect_python(fixture):
    stdout, stderr = fixture.process.communicate(timeout=5)
    if fixture.process.returncode != 0:
        (fixture.working.parent / "first-startup.stdout").write_bytes(stdout)
        (fixture.working.parent / "first-startup.stderr").write_bytes(stderr)
    return stdout, stderr
