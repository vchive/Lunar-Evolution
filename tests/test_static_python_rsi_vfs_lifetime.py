"""Finite lifetime observations with explicitly doubled kernel/runtime boundaries.

Directory walks, held descriptors, CAS writes, receipts and detached replay use
real local files. PID namespaces, pidfd readiness and original Podman controls
are inert doubles; these tests confer no original-container or runtime authority.
"""

from __future__ import annotations

import copy
import os
import shutil
import stat
from types import SimpleNamespace

import pytest

from tests import test_static_python_podman_vfs_root as root_tests
from tests import test_static_python_source_data_vfs_retained_custody as legacy_tests
from tools.static_python_rsi_fixture import podman_custody as custody
from tools.static_python_rsi_fixture import podman_vfs_lifetime as lifetime
from tools.static_python_rsi_fixture import podman_vfs_root as vfs
from tools.static_python_rsi_fixture import podman_vfs_snapshots as retained
from tools.static_python_rsi_fixture.execution_backend import BuildExecutionError

PID = 4242
MOUNTINFO = b"1 0 0:1 / / rw - tmpfs tmpfs rw\n"
INITIAL = {"Status": "initialized", "Running": False, "Pid": PID,
           "ExitCode": 0, "OOMKilled": False, "Error": ""}
TERMINAL = {"Status": "stopped", "Running": False, "Pid": 0,
            "ExitCode": 0, "OOMKilled": False, "Error": ""}
original_vector = legacy_tests.original_vector
retained_vector = legacy_tests.vector
service_root_double = root_tests.service_root_double


def proc_stat(pid=PID, ticks=77):
    return f"{pid} (inert worker) ".encode() + b" ".join(
        [b"S", *([b"0"] * 18), str(ticks).encode()]) + b"\n"


def pin(path, raw):
    return {"path": path, "size": len(raw), "sha256": retained._sha(raw)}


def log_pin(raw):
    return {"size": len(raw), "sha256": retained._sha(raw)}


@pytest.fixture
def owner_vector(tmp_path, monkeypatch):
    """Real directory FDs, with named /proc objects and readiness doubled."""
    root, destination = tmp_path / "worker-root", tmp_path / "attempt"
    root.mkdir()
    destination.mkdir()
    (destination / "custody").mkdir(mode=0o700)
    (destination / "custody/compile-0").mkdir()
    for name in ("source", "toolchain", "work", "out"):
        (root / name).mkdir()
    namespaces = {}
    for name in ("service-pid", "other-pid", "worker-pid", "worker-mnt", "service-mnt", "pidfd"):
        path = tmp_path / name
        path.write_bytes(name.encode())
        namespaces[name] = path
    service = object.__new__(vfs.ServiceRoot)
    service.pid = 1234
    service.root_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    service.descriptors = [service.root_fd]
    service.proof = {"pid": service.pid, "start_ticks": 56,
                     "mount_namespace": {"device": namespaces["service-mnt"].stat().st_dev,
                                         "inode": namespaces["service-mnt"].stat().st_ino}}
    proof = {"service": copy.deepcopy(service.proof), "graph_root": str(tmp_path / "graph"),
             "run_root": str(tmp_path / "run"),
             "root": {"path": str(root), "identity": vfs.identity(root.stat())}}
    roles = {"source": "source", "toolchain": "toolchain", "work": "work", "current_output": "out"}
    view = {"mounts": [{"role": role, "source": str(root / name), "destination": "/" + name,
                         "identity": vfs.identity((root / name).stat())} for role, name in roles.items()]}
    state = SimpleNamespace(exited=False, worker_visible=True, namespace_mismatch=False,
                            close_error=False, proc_error=None, checkpoint_error=None,
                            events=[], owners=[], service_closed=False)
    real_open = os.open
    original_close_service = lifetime._close_service

    def checkpoint():
        if state.checkpoint_error is not None:
            raise state.checkpoint_error

    def service_verify():
        state.events.append("service-verify")
        if state.service_closed:
            raise ValueError("inert_service_closed")

    def close_service(original_service):
        assert original_service is service
        state.events.append("service-close")
        if not state.service_closed:
            try:
                original_close_service(service)
            finally:
                state.service_closed = True
        if state.close_error:
            raise OSError("inert close failure")

    def open_kernel(path, flags, *args, **kwargs):
        name = os.fspath(path)
        targets = {f"/proc/{service.pid}/ns/pid": namespaces["service-pid"],
                   "/proc/self/ns/pid": namespaces["other-pid" if state.namespace_mismatch else "service-pid"],
                   f"/proc/{PID}/root": root, f"/proc/{PID}/ns/mnt": namespaces["worker-mnt"],
                   f"/proc/{PID}/ns/pid": namespaces["worker-pid"]}
        if name in targets:
            state.events.append(name)
            if name.startswith(f"/proc/{PID}/") and not state.worker_visible:
                raise FileNotFoundError(name)
            return real_open(targets[name], flags, *args, **kwargs)
        if str(name).startswith("/proc/"):
            pytest.fail("unexpected original kernel path: " + name)
        return real_open(path, flags, *args, **kwargs)

    def pidfd_open(pid, flags):
        assert (pid, flags) == (PID, 0)
        state.events.append("worker-pidfd")
        return real_open(namespaces["pidfd"], os.O_RDONLY)

    def proc_read(pid, name, maximum, original_checkpoint):
        assert pid == PID and original_checkpoint is checkpoint
        original_checkpoint()
        state.events.append("worker-" + name)
        if state.proc_error is not None:
            raise state.proc_error
        if not state.worker_visible:
            pytest.fail("exited worker was queried by numeric PID")
        raw = proc_stat() if name == "stat" else MOUNTINFO
        assert len(raw) <= maximum
        return raw

    service.verify, service.close = service_verify, lambda: close_service(service)
    monkeypatch.setattr(lifetime, "_close_service", close_service)
    monkeypatch.setattr(lifetime.os, "open", open_kernel)
    monkeypatch.setattr(lifetime.os, "pidfd_open", pidfd_open, raising=False)
    monkeypatch.setattr(lifetime, "_exited", lambda _fd: state.exited)
    monkeypatch.setattr(lifetime, "_proc_read", proc_read)
    monkeypatch.setattr(vfs, "_proc_bytes", lambda *_args, **_kwargs: MOUNTINFO)
    store = retained.VfsSnapshotStore(destination, checkpoint)
    store.command("compile", 0)
    capture = store._lifetime("compile", 0)
    binding = {"recipe_sha256": "f" * 64, "stage": "compile", "index": 0,
               "container_id": "b" * 64, "image_id": "a" * 64,
               "root_acquisition_sha256": retained._sha(retained._json(proof))}
    vfs_pin = {"path": "custody/compile-0/vfs-raw/manifest.json", "size": 1, "sha256": "e" * 64}

    def create(raw=None):
        owner = lifetime._VfsExecutionLifetime(service, retained._json(INITIAL) if raw is None else raw,
                                               proof, view, capture, checkpoint)
        state.owners.append(owner)
        return owner

    value = SimpleNamespace(root=root, destination=destination, service=service, proof=proof,
                            view=view, state=state, store=store, capture=capture,
                            binding=binding, vfs_pin=vfs_pin, checkpoint=checkpoint, create=create)
    try:
        yield value
    finally:
        state.close_error = False
        for owner in state.owners:
            owner.close()
        if not state.service_closed:
            service.close()


def control(vector, name, raw):
    path = vector.destination / "custody/compile-0" / name
    path.mkdir()
    (path / "stdout.log").write_bytes(raw)
    return {"operation": name, "status": "complete", "returncode": 0,
            "direct_child_reaped": True, "logs": {"stdout": log_pin(raw)}}


def complete(vector, *, status="stopped"):
    owner = vector.create()
    initial = retained._json(INITIAL)
    terminal = retained._json({**TERMINAL, "Status": status})
    logs = vector.destination / "logs/compile/0"
    logs.mkdir(parents=True)
    for name in ("stdout", "stderr"):
        (logs / (name + ".log")).write_bytes(b"")
    attach = {"status": "complete", "returncode": 0, "direct_child_reaped": True,
              "logs": {"stdout": log_pin(b""), "stderr": log_pin(b"")}}
    vector.operations = [control(vector, "init", b""), control(vector, "lifetime-initial-state", initial),
                         {"operation": "start-attach", "evidence": attach},
                         control(vector, "wait", b"0\n"), control(vector, "state", terminal)]
    vector.outputs = [{"path": "result.o", "size": 3, "sha256": retained._sha(b"obj"), "executable": False}]
    owner.before_start()
    vector.state.exited, vector.state.worker_visible = True, False
    owner.observe_original_exit(attach, b"0\n", terminal)
    owner.before_readback()
    vector.pin = owner.finish_readback(vector.outputs, {**vector.binding, "vfs_snapshots": vector.vfs_pin})
    owner.close()
    return owner


def replay(vector, **changes):
    args = {"workspace": vector.destination, "pin": vector.pin, "binding": vector.binding,
            "proof": vector.proof, "view": vector.view, "vfs_pin": vector.vfs_pin,
            "operations": vector.operations, "outputs": vector.outputs, "checkpoint": vector.checkpoint}
    args.update(changes)
    return lifetime.verify_lifetime(**args)


def manifest(vector):
    return vfs.decode((vector.destination / vector.pin["path"]).read_bytes())


def rewrite_manifest(vector, value):
    raw = retained._json(value)
    (vector.destination / vector.pin["path"]).write_bytes(raw)
    vector.pin = pin(vector.pin["path"], raw)


@pytest.mark.parametrize("options", [
    {"vfs_lifetime": None}, {"vfs_lifetime": 1}, {"vfs_lifetime": "yes"},
    {"vfs_lifetime": True}, {"vfs_lifetime": True, "vfs_retained": True},
    {"vfs_lifetime": True, "vfs_retained": True, "vfs_roots": True},
], ids=["none", "integer", "string", "missing-retention", "missing-vfs", "missing-source-data"])
def test_lifetime_mode_is_exact_and_refuses_before_creating_custody(tmp_path, options):
    with pytest.raises(BuildExecutionError):
        custody.PodmanCustody(destination=tmp_path, prefix=["inert"], recipe_sha256="f" * 64,
                             checkpoint=lambda: None, **options)
    assert not list(tmp_path.iterdir())


def test_legacy_retained_mode_does_not_create_lifetime_owner_or_directories(tmp_path):
    subject = custody.PodmanCustody(destination=tmp_path, prefix=["inert"], recipe_sha256="f" * 64,
                                   checkpoint=lambda: None, snapshot_mounts=True, source_data=True,
                                   vfs_roots=True, vfs_retained=True)
    assert subject.vfs_lifetime is False
    assert not hasattr(subject.snapshot_store, "_lifetimes")
    assert not list(tmp_path.rglob("vfs-lifetime"))


@pytest.mark.parametrize("field,value", [
    ("Status", "running"), ("Status", "created"), ("Pid", None), ("Pid", 0),
    ("Pid", -1), ("Pid", True), ("Pid", 2**31), ("Running", True),
    ("Running", 0), ("OOMKilled", True), ("OOMKilled", 0), ("Error", "failed"),
], ids=["running-state", "created-state", "missing-pid", "zero-pid", "negative-pid", "bool-pid",
        "oversized-pid", "running", "integer-running", "oom", "integer-oom", "runtime-error"])
def test_original_initialized_state_is_required_before_worker_acquisition(owner_vector, field, value):
    vector = owner_vector
    with pytest.raises(ValueError, match="^podman_vfs_lifetime$"):
        vector.create(retained._json({**INITIAL, field: value}))
    assert "worker-pidfd" not in vector.state.events
    assert vector.state.service_closed


def test_client_and_service_pid_views_are_compared_before_interpreting_worker_pid(owner_vector):
    vector = owner_vector
    vector.state.namespace_mismatch = True
    with pytest.raises(ValueError, match="^podman_vfs_lifetime$"):
        vector.create()
    assert "worker-pidfd" not in vector.state.events
    assert vector.state.service_closed


def test_original_owner_keeps_handles_and_performs_namespace_checks_before_pidfd(owner_vector):
    vector = owner_vector
    owner = vector.create()
    events = vector.state.events
    assert events.index(f"/proc/{vector.service.pid}/ns/pid") < events.index("worker-pidfd")
    assert events.index("/proc/self/ns/pid") < events.index("worker-pidfd")
    assert owner.phase == 1 and len(owner.role_fds) == 4
    held = list(owner.fds)
    for fd in held:
        os.fstat(fd)
    owner.close()
    owner.close()
    assert events.count("service-close") == 1
    for fd in held:
        with pytest.raises(OSError):
            os.fstat(fd)


def test_partial_acquisition_releases_all_original_fds_and_keeps_first_failure(owner_vector, monkeypatch):
    vector = owner_vector
    acquired = []
    original = lifetime._VfsExecutionLifetime._keep

    def keep(owner, fd, **options):
        acquired.append(fd)
        return original(owner, fd, **options)

    monkeypatch.setattr(lifetime._VfsExecutionLifetime, "_keep", keep)
    primary = BuildExecutionError("deadline_expired")
    vector.state.proc_error, vector.state.close_error = primary, True
    with pytest.raises(BuildExecutionError) as caught:
        vector.create()
    assert caught.value is primary
    assert "podman_vfs_lifetime_close_unknown" in caught.value.__notes__
    assert acquired and vector.state.service_closed
    for fd in acquired:
        with pytest.raises(OSError):
            os.fstat(fd)


@pytest.mark.parametrize("change", ["proof", "view", "owner", "service", "role", "root", "namespace"])
def test_held_original_object_and_named_view_substitution_refuses(owner_vector, change):
    vector = owner_vector
    owner = vector.create()
    if change == "proof":
        owner.proof["graph_root"] += "-replacement"
    elif change == "view":
        owner.view["mounts"][0]["source"] += "-replacement"
    elif change == "owner":
        owner.owner["worker_start_ticks"] += 1
    elif change == "service":
        vector.service.proof["start_ticks"] += 1
    elif change == "role":
        (vector.root / "source").rename(vector.root / "original-source")
        (vector.root / "source").mkdir()
    elif change == "root":
        vector.root.rename(vector.root.with_name("original-root"))
        vector.root.mkdir()
        for name in ("source", "toolchain", "work", "out"):
            (vector.root / name).mkdir()
    else:
        vector.state.namespace_mismatch = True
    with pytest.raises(ValueError, match="^podman_vfs_lifetime$"):
        owner.before_start()
    assert owner.phase == 1


@pytest.mark.parametrize("action", ["exit-before-start", "readback-before-exit", "repeat-start", "after-close"])
def test_phase_machine_refuses_omission_repetition_and_use_after_close(owner_vector, action):
    vector = owner_vector
    owner = vector.create()
    attach = {"status": "complete", "returncode": 0, "direct_child_reaped": True}
    with pytest.raises(ValueError, match="^podman_vfs_lifetime$"):
        if action == "exit-before-start":
            owner.observe_original_exit(attach, b"0", retained._json(TERMINAL))
        elif action == "readback-before-exit":
            owner.before_readback()
        elif action == "repeat-start":
            owner.before_start()
            owner.before_start()
        else:
            owner.close()
            owner.before_start()


@pytest.mark.parametrize("status", ["exited", "stopped"])
def test_fast_normal_exit_needs_no_running_sample_or_postexit_numeric_pid(owner_vector, status):
    vector = owner_vector
    owner = complete(vector, status=status)
    assert owner.phase == 5 and owner.closed
    assert [phase["phase"] for phase in vector.capture.phases] == list(lifetime.PHASES)
    assert [phase["pidfd_exited"] for phase in vector.capture.phases] == [False, False, True, True, True]
    assert [(row["role"], row["phase"]) for row in vector.capture.records] == list(lifetime._order())
    assert len({id(phase["owner"]) for phase in vector.capture.phases}) == 5
    assert vector.state.events.count("worker-stat") == 3
    assert vector.state.events.count("worker-mountinfo") == 2
    with pytest.raises(ValueError, match="^podman_vfs_lifetime$"):
        owner.finish_readback(vector.outputs, {**vector.binding, "vfs_snapshots": vector.vfs_pin})


@pytest.mark.parametrize("gate", ["exited-before-start", "live-at-terminal", "deadline"])
def test_original_readiness_and_deadline_gate_cannot_be_replaced_by_reported_state(owner_vector, gate):
    vector = owner_vector
    owner = vector.create()
    if gate == "exited-before-start":
        vector.state.exited = True
        operation = owner.before_start
    elif gate == "deadline":
        primary = BuildExecutionError("deadline_expired")
        vector.state.checkpoint_error = primary
        with pytest.raises(BuildExecutionError) as caught:
            owner.before_start()
        assert caught.value is primary and owner.phase == 1
        return
    else:
        owner.before_start()
        operation = lambda: owner.observe_original_exit(
            {"status": "complete", "returncode": 0, "direct_child_reaped": True},
            b"0", retained._json(TERMINAL))
    with pytest.raises(ValueError, match="^podman_vfs_lifetime$"):
        operation()
    assert not (vector.destination / "custody/compile-0/vfs-lifetime/manifest.json").exists()


def test_close_attempts_every_held_descriptor_and_service_even_after_one_close_error(owner_vector, monkeypatch):
    vector = owner_vector
    owner = vector.create()
    held = list(owner.fds)
    original = os.close
    closed = []

    def close(fd):
        closed.append(fd)
        original(fd)
        if fd == held[-1]:
            raise OSError("inert descriptor close failure")

    monkeypatch.setattr(lifetime.os, "close", close)
    with pytest.raises(ValueError, match="^podman_vfs_lifetime$"):
        owner.close()
    assert closed[:len(held)] == list(reversed(held))
    assert vector.state.service_closed and owner.closed and not owner.fds


@pytest.mark.parametrize("events,expected", [
    ([], False), ([(9, 1)], True), ([(9, 17)], True), ([(9, 16)], None),
    ([(8, 1)], None), ([(9, 8)], None), ([(9, 33)], None), ([(9, 1), (9, 1)], None),
], ids=["live", "readable", "readable-hup", "hup-only", "other-fd", "error", "unknown", "duplicate"])
def test_pidfd_readiness_accepts_only_original_readable_event(monkeypatch, events, expected):
    registrations = []
    poller = SimpleNamespace(register=lambda fd, flags: registrations.append((fd, flags)),
                             poll=lambda timeout: events if timeout == 0 else pytest.fail("blocking poll"))
    monkeypatch.setattr(lifetime, "select", SimpleNamespace(poll=lambda: poller, POLLIN=1, POLLHUP=16))
    if expected is None:
        with pytest.raises(ValueError, match="^podman_vfs_lifetime$"):
            lifetime._exited(9)
    else:
        assert lifetime._exited(9) is expected
    assert registrations == [(9, 1)]


@pytest.mark.parametrize("raw,maximum", [(b"short body", 10), (b"one byte too long", 16)],
                         ids=["short-reads", "ceiling"])
def test_original_proc_reader_keeps_short_reads_and_closes_bounded_descriptor(tmp_path, monkeypatch, raw, maximum):
    body = tmp_path / "kernel-double"
    body.write_bytes(raw)
    original_open, original_read, original_close = os.open, os.read, os.close
    opened, closed, checks = [], [], []

    def open_original(path, flags):
        assert path == f"/proc/{PID}/stat"
        assert flags & os.O_NOFOLLOW
        fd = original_open(body, flags)
        opened.append(fd)
        return fd

    def close(fd):
        closed.append(fd)
        original_close(fd)

    monkeypatch.setattr(lifetime.os, "open", open_original)
    monkeypatch.setattr(lifetime.os, "read", lambda fd, count: original_read(fd, min(count, 2)))
    monkeypatch.setattr(lifetime.os, "close", close)
    if len(raw) <= maximum:
        assert lifetime._proc_read(PID, "stat", maximum, lambda: checks.append(True)) == raw
    else:
        with pytest.raises(ValueError, match="^podman_vfs_lifetime$"):
            lifetime._proc_read(PID, "stat", maximum, lambda: checks.append(True))
    assert opened == closed and len(opened) == 1 and len(checks) >= 3


def test_original_proc_reader_obeys_cancellation_before_any_followup_read(monkeypatch):
    primary = BuildExecutionError("deadline_expired")

    def checkpoint():
        raise primary

    monkeypatch.setattr(lifetime.os, "open", lambda *_args, **_kwargs: pytest.fail("opened after cancellation"))
    with pytest.raises(BuildExecutionError) as caught:
        lifetime._proc_read(PID, "stat", 64, checkpoint)
    assert caught.value is primary


@pytest.mark.parametrize("boundary", ["namespace-open", "initial-verify"])
def test_lifetime_service_partial_acquisition_closes_every_fd_and_preserves_primary(
        service_root_double, monkeypatch, boundary):
    vector = service_root_double
    primary = BuildExecutionError("inert_original_service_acquisition")
    original_open, original_close = os.open, os.close
    state = {"failed": False, "close_fault": False, "expected": []}
    closed = []

    def open_original(path, flags, *args, **kwargs):
        if boundary == "namespace-open" and str(path) == f"/proc/{vector.pid}/ns/mnt":
            state["expected"] = list(vector.opened)
            state["failed"] = True
            raise primary
        return original_open(path, flags, *args, **kwargs)

    def verify_original(service):
        state["expected"] = list(service.descriptors)
        state["failed"] = True
        raise primary

    def close(fd):
        original_close(fd)
        if state["failed"]:
            closed.append(fd)
            if not state["close_fault"]:
                state["close_fault"] = True
                raise OSError("inert first release failure")

    monkeypatch.setattr(vfs.os, "open", open_original)
    monkeypatch.setattr(vfs.os, "close", close)
    if boundary == "initial-verify":
        monkeypatch.setattr(vfs.ServiceRoot, "verify", verify_original)
    with pytest.raises(BuildExecutionError) as caught:
        vfs.ServiceRoot(vector.pid, lambda: None, _release_all=True)
    assert caught.value is primary
    assert "podman_vfs_lifetime_close_unknown" in primary.__notes__
    assert closed == list(reversed(state["expected"]))
    for fd in state["expected"]:
        with pytest.raises(OSError):
            os.fstat(fd)


def test_capture_and_detached_replay_use_original_private_bytes_without_live_queries(owner_vector, monkeypatch):
    vector = owner_vector
    complete(vector)

    def forbidden(*_args, **_kwargs):
        pytest.fail("detached lifetime replay queried a live kernel/runtime object")

    monkeypatch.setattr(lifetime, "_proc_read", forbidden)
    monkeypatch.setattr(lifetime, "_exited", forbidden)
    monkeypatch.setattr(vfs, "_proc_bytes", forbidden)
    monkeypatch.setattr(lifetime.os, "pidfd_open", forbidden)
    assert replay(vector) is None
    value = manifest(vector)
    assert value["complete"] is True
    assert all(claim is False for claim in value["claims"].values())
    assert len(value["records"]) == 18
    assert len({row["sha256"] for row in value["records"]}) < len(value["records"])
    assert stat.S_IMODE((vector.destination / vector.pin["path"]).stat().st_mode) == 0o600
    assert stat.S_IMODE((vector.destination / vector.pin["path"]).parent.stat().st_mode) == 0o700
    for row in value["records"]:
        path = vector.destination / "custody/vfs-raw/blobs" / (row["sha256"] + ".bin")
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_detached_replay_refuses_whole_workspace_name_replacement_after_original_open(owner_vector, monkeypatch):
    vector = owner_vector
    complete(vector)
    original_read = retained._read
    replaced = []

    def read_original(*args, **kwargs):
        result = original_read(*args, **kwargs)
        if args[1] == vector.pin["path"] and not replaced:
            previous = vector.destination.with_name("original-attempt")
            vector.destination.rename(previous)
            shutil.copytree(previous, vector.destination)
            replaced.append(previous)
        return result

    def forbidden(*_args, **_kwargs):
        pytest.fail("workspace-root refusal queried live state")

    monkeypatch.setattr(retained, "_read", read_original)
    monkeypatch.setattr(lifetime, "_proc_read", forbidden)
    monkeypatch.setattr(lifetime, "_exited", forbidden)
    monkeypatch.setattr(vfs, "_proc_bytes", forbidden)
    with pytest.raises(ValueError, match="^podman_vfs_lifetime$"):
        replay(vector)
    assert len(replaced) == 1 and replaced[0].is_dir()


@pytest.mark.parametrize("change", ["missing-phase", "repeat-phase", "phase-order", "phase-extra", "owner",
                                     "live-terminal", "raw-order", "raw-extra", "claim", "schema", "incomplete"])
def test_resigned_selected_manifest_cannot_replace_original_phase_and_raw_contract(owner_vector, change):
    vector = owner_vector
    complete(vector)
    value = manifest(vector)
    if change == "missing-phase":
        value["phases"].pop()
    elif change == "repeat-phase":
        value["phases"][1] = copy.deepcopy(value["phases"][0])
    elif change == "phase-order":
        value["phases"][1], value["phases"][2] = value["phases"][2], value["phases"][1]
    elif change == "phase-extra":
        value["phases"][1]["replacement"] = False
    elif change == "owner":
        value["phases"][3]["owner"]["worker_pid"] += 1
    elif change == "live-terminal":
        value["phases"][2]["pidfd_exited"] = False
    elif change == "raw-order":
        value["records"][0], value["records"][1] = value["records"][1], value["records"][0]
        for index, row in enumerate(value["records"]):
            receipt = vector.destination / "custody/compile-0/vfs-lifetime" / f"record-{index:02d}.json"
            receipt.write_bytes(retained._json(row))
    elif change == "raw-extra":
        value["records"][0]["source_identity"] = {}
    elif change == "claim":
        value["claims"]["production_admission"] = True
    elif change == "schema":
        value["schema"] = retained.SCHEMA
    else:
        value["complete"] = False
    rewrite_manifest(vector, value)
    with pytest.raises(ValueError, match="^podman_vfs_lifetime$"):
        replay(vector)


@pytest.mark.parametrize("change", ["bytes", "same-byte-inode", "symlink", "hardlink", "public-mode", "missing"])
def test_original_cas_object_cannot_be_substituted_even_with_equal_bytes(owner_vector, change):
    vector = owner_vector
    complete(vector)
    row = manifest(vector)["records"][0]
    path = vector.destination / "custody/vfs-raw/blobs" / (row["sha256"] + ".bin")
    raw = path.read_bytes()
    if change == "bytes":
        path.write_bytes(raw + b" ")
    elif change == "public-mode":
        path.chmod(0o644)
    elif change == "hardlink":
        os.link(path, path.with_name("alias"))
    else:
        path.rename(path.with_name("original"))
        if change == "same-byte-inode":
            path.write_bytes(raw)
            path.chmod(0o600)
        elif change == "symlink":
            path.symlink_to(path.with_name("original"))
    with pytest.raises(ValueError, match="^podman_vfs_lifetime$"):
        replay(vector)


@pytest.mark.parametrize("change", ["ticks", "initial-pid", "protected-mount", "wait"])
def test_replay_reparses_resigned_raw_bytes_instead_of_trusting_selected_fields(owner_vector, change):
    vector = owner_vector
    complete(vector)
    value = manifest(vector)
    role, phase, raw = {
        "ticks": ("worker-stat", "before-start", proc_stat(ticks=78)),
        "initial-pid": ("state", "initialized", retained._json({**INITIAL, "Pid": PID + 1})),
        "protected-mount": ("mountinfo-client", "before-readback",
                            f"2 1 0:2 / {vector.root}/nested rw - tmpfs tmpfs rw\n".encode()),
        "wait": ("wait", "original-exit", b"1\n"),
    }[change]
    index = next(i for i, row in enumerate(value["records"]) if (row["role"], row["phase"]) == (role, phase))
    row = value["records"][index]
    digest = retained._sha(raw)
    body = vector.destination / "custody/vfs-raw/blobs" / (digest + ".bin")
    body.write_bytes(raw)
    body.chmod(0o600)
    row.update(size=len(raw), sha256=digest, blob_identity=retained._file_identity(body.stat()))
    (vector.destination / "custody/compile-0/vfs-lifetime" / f"record-{index:02d}.json").write_bytes(retained._json(row))
    if change == "protected-mount":
        value["phases"][3]["mount_tables"]["client_sha256"] = digest
    elif change == "wait":
        value["phases"][2]["links"]["wait_sha256"] = digest
    rewrite_manifest(vector, value)
    with pytest.raises(ValueError, match="^podman_vfs_lifetime$"):
        replay(vector)


@pytest.mark.parametrize("change", ["order", "duplicate", "attach-reap", "control-body", "control-pin", "output-vector", "cross-command"])
def test_original_attach_controls_and_readback_vector_remain_bound(owner_vector, change):
    vector = owner_vector
    complete(vector)
    if change == "order":
        vector.operations[0], vector.operations[2] = vector.operations[2], vector.operations[0]
    elif change == "duplicate":
        vector.operations.append(copy.deepcopy(vector.operations[0]))
    elif change == "attach-reap":
        vector.operations[2]["evidence"]["direct_child_reaped"] = False
    elif change == "control-body":
        (vector.destination / "custody/compile-0/state/stdout.log").write_bytes(b"{}\n")
    elif change == "control-pin":
        vector.operations[4]["logs"]["stdout"]["sha256"] = "d" * 64
    elif change == "output-vector":
        vector.outputs[0]["size"] += 1
    else:
        vector.binding["index"] = 1
    with pytest.raises(ValueError, match="^podman_vfs_lifetime$"):
        replay(vector)


def test_lifetime_capture_cannot_adopt_preexisting_same_hash_or_complete_partial_phases(owner_vector):
    vector = owner_vector
    raw = retained._json(INITIAL)
    body = vector.destination / "custody/vfs-raw/blobs" / (retained._sha(raw) + ".bin")
    body.write_bytes(raw)
    body.chmod(0o600)
    with pytest.raises(FileExistsError):
        vector.capture.record("state", "initialized", raw)
    assert not vector.capture.records and not vector.store.blobs
    with pytest.raises(ValueError, match="^podman_vfs_lifetime$"):
        vector.capture.complete({**vector.binding, "vfs_snapshots": vector.vfs_pin})


def test_shared_attempt_budget_keeps_partial_body_and_does_not_refund_failed_receipt(owner_vector, monkeypatch):
    vector = owner_vector
    raw = retained._json(INITIAL)
    monkeypatch.setattr(retained, "MAX_STORED_BYTES", len(raw))
    with pytest.raises(ValueError, match="^podman_vfs_snapshots$"):
        vector.capture.record("state", "initialized", raw)
    assert vector.store.stored_bytes == len(raw)
    assert len(vector.store.blobs) == 1 and not vector.capture.records
    assert not (vector.destination / "custody/compile-0/vfs-lifetime/manifest.json").exists()


@pytest.mark.parametrize("role,phase,raw", [
    ("state", "initialized", b"x" * 32769),
    ("state", "initialized", "{}"),
    ("worker-stat", "initialized", b"x" * 65537),
    ("mountinfo-client", "initialized", b"x" * (1024**2 + 1)),
    ("state", "before-start", b"{}"),
], ids=["state-cap", "nonbytes", "stat-cap", "mount-cap", "wrong-phase"])
def test_capture_bounds_refuse_before_cas_write(owner_vector, role, phase, raw):
    vector = owner_vector
    with pytest.raises(ValueError, match="^podman_vfs_lifetime$"):
        vector.capture.record(role, phase, raw)
    assert vector.store.stored_bytes == 0 and not vector.store.blobs


def test_original_raw_snapshot_reader_refuses_new_lifetime_manifest(owner_vector):
    vector = owner_vector
    complete(vector)
    with pytest.raises(ValueError, match="^podman_vfs_snapshots$"):
        retained.verify_snapshots(vector.destination, vector.pin, vector.binding, vector.proof,
                                  vector.operations, vector.checkpoint)


@pytest.mark.parametrize("schema,backend", [
    ("lunar-podman-build-command-observation-v4", custody.SOURCE_DATA_VFS_RETAINED_BACKEND),
    ("lunar-podman-build-command-observation-v5", custody.SOURCE_DATA_VFS_RETAINED_BACKEND),
    ("lunar-podman-build-command-observation-v4", lifetime.BACKEND),
], ids=["old", "mixed-backend", "mixed-schema"])
def test_new_custody_reader_refuses_old_or_mixed_schema_before_old_replay(tmp_path, monkeypatch, schema, backend):
    monkeypatch.setattr(custody, "validate_custody_observation_v4",
                        lambda *_args, **_kwargs: pytest.fail("old replay reached before new version gate"))
    command = {"custody": {"schema": schema, "input_layout": backend, "lifetime_profile": lifetime.SCHEMA}}
    with pytest.raises(ValueError, match="^podman_custody_original_observation_v5$"):
        custody.validate_custody_observation_v5(command, {}, "compile", 0, "f" * 64, {},
                                                inputs={}, prior=[], workspace=tmp_path)


def test_old_custody_reader_refuses_new_observation(tmp_path):
    command = {"custody": {"schema": "lunar-podman-build-command-observation-v5",
                            "input_layout": lifetime.BACKEND, "lifetime_profile": lifetime.SCHEMA}}
    with pytest.raises(ValueError, match="^podman_custody_original_observation_v4$"):
        custody.validate_custody_observation_v4(command, {}, "compile", 0, "f" * 64, {},
                                                inputs={}, prior=[], workspace=tmp_path)


def original_runner(retained_vector, monkeypatch, *, failure=None, status="stopped"):
    """Keep the original run/policy/seccomp/readback; double owner and Podman."""
    base, capture = retained_vector
    original, data, events = base
    subject, readonly = original[0], original[6]
    subject.vfs_lifetime = True
    run, evidence, work, root, _spec = legacy_tests.lifecycle(
        retained_vector, monkeypatch, terminal_state={**TERMINAL, "Status": status})
    current = root / "current"
    prior_control, prior_image = subject._control, subject._prepare_image
    prior_scan, prior_observe = custody._scan_outputs, custody._observe
    prior_service = vfs.ServiceRoot
    token, owners = object(), []

    def control(args, name, command_root, operations):
        if name == "lifetime-initial-state":
            assert args == ["inspect", "--type", "container", "--format", '{{json .State}}', "b" * 64]
            events.append(name)
            return retained._json(INITIAL)
        return prior_control(args, name, command_root, operations)

    def image(**options):
        result = prior_image(**options)
        options["observation"]["input_layout"] = lifetime.BACKEND
        return result

    def select_capture(stage, index):
        assert (stage, index) == ("compile", 0)
        events.append("lifetime-capture")
        return token

    def service(pid, checkpoint, *, _release_all=False, _connected_streams=False):
        assert _release_all is True and _connected_streams is True
        return prior_service(pid, checkpoint)

    class OriginalOwnerDouble:
        def __init__(self, service, raw, proof, view, original_capture, checkpoint):
            assert service is data.service and original_capture is token
            assert raw == retained._json(INITIAL)
            assert proof["service"] == data.service.proof
            assert {row["role"] for row in view["mounts"]} == set(lifetime._ROLES)
            assert "init" in events and "service-close" not in events
            self.checkpoint = checkpoint
            owners.append(self)
            self.gate("acquire")

        def gate(self, name):
            self.checkpoint()
            events.append("lifetime-" + name)
            if failure == name:
                raise BuildExecutionError("inert_lifetime_" + name)

        def before_start(self):
            assert capture.binding is not None
            self.gate("before-start")

        def observe_original_exit(self, attach, wait_raw, state_raw):
            assert attach["status"] == "complete" and attach["direct_child_reaped"] is True
            assert wait_raw == b"0\n" and retained._json({**TERMINAL, "Status": status}) == state_raw
            self.gate("original-exit")

        def before_readback(self):
            self.gate("before-readback")

        def finish_readback(self, outputs, binding):
            assert outputs == evidence["custody"]["readback_outputs"] and len(outputs) == 1
            assert binding["vfs_snapshots"] == evidence["custody"]["vfs_snapshots"]
            assert (work / "result.o").read_bytes() == b"original completed output"
            self.gate("after-readback")
            return {"path": "custody/compile-0/vfs-lifetime/manifest.json", "size": 123, "sha256": "d" * 64}

        def close(self):
            events.append("lifetime-close")
            data.service.close()
            if failure == "close":
                raise ValueError("inert lifetime close failure")

    def attach(args, **options):
        subject.checkpoint()
        assert args[-3:] == ["start", "--attach", "b" * 64]
        assert events[-1] == "lifetime-before-start" and "service-close" not in events
        events.append("start-attach")
        (current / "result.o").write_bytes(b"original completed output")
        options["evidence"].update(status="complete", returncode=0, direct_child_reaped=True, logs={})

    def scan(*args, **options):
        events.append("scan-outputs")
        return prior_scan(*args, **options)

    def observe(observed_root, path, *args, **options):
        if path == "result.o":
            events.append("observe-promoted" if observed_root == work else "observe-current")
        return prior_observe(observed_root, path, *args, **options)

    if failure == "retention":
        capture.failure = "complete"
    monkeypatch.setattr(subject, "_control", control)
    monkeypatch.setattr(subject, "_prepare_image", image)
    monkeypatch.setattr(subject.snapshot_store, "_lifetime", select_capture, raising=False)
    monkeypatch.setattr(vfs, "ServiceRoot", service)
    monkeypatch.setattr(lifetime, "_VfsExecutionLifetime", OriginalOwnerDouble)
    monkeypatch.setattr(lifetime, "_close_service", lambda service: service.close())
    monkeypatch.setattr(custody, "_command", attach)
    monkeypatch.setattr(custody, "_scan_outputs", scan)
    monkeypatch.setattr(custody, "_observe", observe)
    assert all(role in readonly for role in ("source", "toolchain", "work"))
    return run, evidence, work, events, owners


@pytest.mark.parametrize("status", ["exited", "stopped"])
def test_original_custody_run_spans_attach_wait_and_real_output_promotion_with_same_owner(
        retained_vector, monkeypatch, status):
    run, evidence, work, events, owners = original_runner(retained_vector, monkeypatch, status=status)
    run()
    ordered = ["init", "lifetime-initial-state", "lifetime-acquire", "capture-complete",
               "lifetime-before-start", "start-attach", "wait", "state", "lifetime-original-exit",
               "lifetime-before-readback", "scan-outputs", "observe-current", "observe-promoted",
               "lifetime-after-readback", "lifetime-close", "service-close"]
    positions = [events.index(name) for name in ordered]
    assert positions == sorted(positions) and len(owners) == 1
    assert events.count("start-attach") == events.count("lifetime-close") == events.count("service-close") == 1
    assert evidence["status"] == "complete"
    observation = evidence["custody"]
    assert observation["schema"] == "lunar-podman-build-command-observation-v5"
    assert observation["input_layout"] == lifetime.BACKEND
    assert observation["lifetime_profile"] == lifetime.SCHEMA
    assert observation["vfs_lifetime"]["path"] == "custody/compile-0/vfs-lifetime/manifest.json"
    assert (work / "result.o").read_bytes() == b"original completed output"
    assert all(observation[name] is False for name in (
        "immutable_custody_verified", "driver_inputs_verified", "installation_accepted",
        "configured_closure_verified", "production_admission", "online_publication"))


@pytest.mark.parametrize("failure", ["acquire", "retention", "before-start", "original-exit",
                                    "before-readback", "after-readback", "close"])
def test_original_custody_run_refuses_each_lifetime_gate_without_retry_or_early_promotion(
        retained_vector, monkeypatch, failure):
    run, evidence, work, events, owners = original_runner(retained_vector, monkeypatch, failure=failure)
    with pytest.raises(BuildExecutionError):
        run()
    assert evidence["status"] == "partial" and len(owners) == 1
    assert events.count("start-attach") == (0 if failure in {"acquire", "retention", "before-start"} else 1)
    assert (work / "result.o").exists() is (failure in {"after-readback", "close"})
    assert events.count("service-close") == 1
    if failure == "close":
        assert evidence["custody"]["lifetime_close_unknown"] is True
        assert evidence["custody"]["first_failure"] == "custody_vfs_lifetime_close_unknown"
        assert "vfs_lifetime" in evidence["custody"]
    else:
        expected = "custody_vfs_snapshot_write" if failure == "retention" else "inert_lifetime_" + failure
        assert evidence["custody"]["first_failure"] == BuildExecutionError(expected).code
        assert "vfs_lifetime" not in evidence["custody"]
