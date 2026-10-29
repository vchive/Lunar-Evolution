"""Actual local file vectors for bounded service-root VFS metadata acquisition.

The service is inert and synthetic; no Podman, namespace entry or target runs.
"""

from __future__ import annotations

import copy
import os
import socket
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.static_python_rsi_fixture import podman_vfs_root as vfs
from tools.static_python_rsi_fixture.execution_backend import BuildExecutionError
from tools.static_python_rsi_fixture.runtime_closure import canonical

CID, IMAGE, LAYER = "b" * 64, "a" * 64, "c" * 64


def vfs_vector(tmp_path):
    tmp_path = tmp_path.resolve()
    graph, run = tmp_path / "graph", tmp_path / "run"
    run.mkdir()
    containers = graph / "vfs-containers/containers.json"
    layers = graph / "vfs-layers/layers.json"
    oci = graph / "vfs-containers" / CID / "userdata/config.json"
    root = graph / "vfs/dir" / LAYER
    for path in (containers, layers, oci):
        path.parent.mkdir(parents=True, exist_ok=True)
    root.mkdir(parents=True)
    containers.write_bytes(canonical([{"id": CID, "image": IMAGE, "layer": LAYER}]))
    layers.write_bytes(canonical([{"id": LAYER, "parent": ""}]))
    oci.write_bytes(canonical({"root": {"path": str(root), "readonly": True}}))
    root_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    proof = {"pid": 1234, "start_ticks": 5678,
             "root_identity": vfs.identity(os.fstat(root_fd)),
             "mount_namespace": {"device": 4, "inode": 100},
             "client_mount_namespace": {"device": 4, "inode": 101},
             "socket": {"path": f"/run/user/{os.geteuid()}/podman/podman.sock",
                        "identity": {"device": 2, "inode": 40, "mode": stat.S_IFSOCK | 0o600,
                                     "uid": os.geteuid(), "gid": os.getegid()}, "kernel_inode": 123}}
    service = SimpleNamespace(root_fd=root_fd, proof=proof, pid=1234, verify=lambda: None)
    selected = {"container_id": CID, "image": IMAGE, "oci": str(oci), "resolver": "",
                "hostname": "", "hosts": ""}
    info = {"driver": "vfs", "graph_root": str(graph), "run_root": str(run)}
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    mounts = {"source": {"source": str(workspace), "identity": vfs.identity(workspace.stat())}}
    return SimpleNamespace(graph=graph, run=run, containers=containers, layers=layers, oci=oci,
                           root=root, service=service, selected=selected, info=info, mounts=mounts)


def acquire(vector):
    return vfs.acquire(vector.service, canonical(vector.info), vector.selected, CID, IMAGE,
                       vector.mounts, lambda: None)


@pytest.fixture
def vector(tmp_path, monkeypatch):
    monkeypatch.setattr(vfs, "mount_table", lambda _pid, _checkpoint: ("e" * 64, [Path("/")]))
    value = vfs_vector(tmp_path)
    try:
        yield value
    finally:
        os.close(value.service.root_fd)


def test_vfs_acquisition_joins_independent_metadata_and_actual_root(vector):
    raw, proof = acquire(vector)
    assert raw == vector.oci.read_bytes()
    assert proof["root"] == {"path": str(vector.root), "identity": vfs.identity(vector.root.stat())}
    assert proof["service"]["mount_namespace"] != proof["service"]["client_mount_namespace"]
    assert vfs.validate_proof(proof, container=CID, root=proof["root"],
                              oci_sha256=proof["metadata"]["oci_sha256"])


@pytest.mark.parametrize("change", [
    "driver", "run-overlap", "container", "image", "image-type", "missing-container", "duplicate-container",
    "shared-layer", "missing-layer", "duplicate-layer", "bad-layer", "bad-parent", "oci-location", "oci-root",
    "metadata-symlink", "root-symlink", "workspace-symlink",
])
def test_vfs_acquisition_refuses_metadata_alias_and_identity_drift(vector, change):
    if change == "driver":
        vector.info["driver"] = "overlay"
    elif change == "run-overlap":
        vector.info["run_root"] = str(vector.graph / "run")
    elif change == "container":
        vector.selected["container_id"] = "d" * 64
    elif change == "image":
        vector.selected["image"] = "d" * 64
    elif change == "image-type":
        vector.selected["image"] = None
    elif change == "missing-container":
        vector.containers.write_bytes(canonical([{"id": "d" * 64, "image": IMAGE, "layer": LAYER}]))
    elif change == "duplicate-container":
        row = {"id": CID, "image": IMAGE, "layer": LAYER}
        vector.containers.write_bytes(canonical([row, row]))
    elif change == "shared-layer":
        vector.containers.write_bytes(canonical([
            {"id": CID, "image": IMAGE, "layer": LAYER},
            {"id": "d" * 64, "image": IMAGE, "layer": LAYER}]))
    elif change == "missing-layer":
        vector.layers.write_bytes(canonical([{"id": "d" * 64}]))
    elif change == "duplicate-layer":
        vector.layers.write_bytes(canonical([{"id": LAYER}, {"id": LAYER}]))
    elif change == "bad-layer":
        vector.containers.write_bytes(canonical([{"id": CID, "image": IMAGE, "layer": "../escape"}]))
    elif change == "bad-parent":
        vector.layers.write_bytes(canonical([{"id": LAYER, "parent": True}]))
    elif change == "oci-location":
        vector.selected["oci"] = str(vector.oci.parent / "other.json")
    elif change == "oci-root":
        vector.oci.write_bytes(canonical({"root": {"path": str(vector.run)}}))
    elif change == "metadata-symlink":
        other = vector.containers.with_name("other.json")
        vector.containers.rename(other)
        vector.containers.symlink_to(other)
    elif change == "root-symlink":
        vector.root.rmdir()
        vector.root.symlink_to(vector.run, target_is_directory=True)
    else:
        workspace = vector.mounts["source"]["source"]
        Path(workspace).rmdir()
        Path(workspace).symlink_to(vector.run, target_is_directory=True)
    with pytest.raises((BuildExecutionError, OSError)):
        acquire(vector)


@pytest.mark.parametrize("target", ["containers", "layers", "oci"])
def test_same_byte_metadata_replacement_is_detected_across_acquisition(vector, monkeypatch, target):
    original = vfs.read_at
    replaced = []

    def replace(root_fd, path, maximum, checkpoint):
        raw = original(root_fd, path, maximum, checkpoint)
        if path == vector.oci and not replaced:
            selected = getattr(vector, target)
            replacement = selected.with_name("replacement.json")
            replacement.write_bytes(selected.read_bytes())
            replacement.replace(selected)
            replaced.append(selected)
        return raw

    monkeypatch.setattr(vfs, "read_at", replace)
    with pytest.raises(BuildExecutionError, match="custody_vfs_drift"):
        acquire(vector)


def test_service_namespace_workspace_substitution_is_rejected(vector, monkeypatch):
    original = vfs.directory_at

    def substitute(root_fd, path, checkpoint):
        value = original(root_fd, path, checkpoint)
        if root_fd == vector.service.root_fd and str(path) == vector.mounts["source"]["source"]:
            value["inode"] += 1
        return value

    monkeypatch.setattr(vfs, "directory_at", substitute)
    with pytest.raises(BuildExecutionError, match="custody_vfs_namespace_view"):
        acquire(vector)


@pytest.mark.parametrize("raw", [b'{"driver":"vfs","driver":"vfs"}', b"[]" * 2,
                                 b"x" * (vfs.MAX_METADATA_BYTES + 1),
                                 b'{"unused":NaN}', b'{"unused":Infinity}', b'{"unused":-Infinity}'])
def test_metadata_json_is_bounded_and_duplicate_keys_are_rejected(raw):
    with pytest.raises(BuildExecutionError, match="custody_vfs_metadata"):
        vfs.decode(raw)


@pytest.mark.parametrize("change", ["backend", "container", "layer", "metadata", "service", "root", "extra"])
def test_detached_vfs_proof_rejects_cross_pin_shape_drift(vector, change):
    _raw, proof = acquire(vector)
    original = copy.deepcopy(proof)
    if change == "backend":
        proof["backend"] = "podman-snapshots-source-data-v2"
    elif change == "container":
        proof["container_id"] = "d" * 64
    elif change == "layer":
        proof["layer_id"] = "d" * 64
    elif change == "metadata":
        proof["metadata"]["containers_identity"]["inode"] = True
    elif change == "service":
        proof["service"]["start_ticks"] = True
    elif change == "root":
        proof["root"]["identity"]["mode"] = stat.S_IFREG | 0o444
    else:
        proof["accepted"] = True
    assert not vfs.validate_proof(proof, container=CID, root=original["root"],
                                  oci_sha256=original["metadata"]["oci_sha256"])


def test_path_component_walk_observes_original_checkpoint(vector):
    calls = []
    vfs.directory_at(vector.service.root_fd, vector.root, lambda: calls.append(1))
    assert len(calls) >= len(vector.root.parts)


def test_cancel_in_component_walk_has_no_followup_reads(vector):
    calls = []

    def cancelled():
        calls.append(1)
        raise RuntimeError("cancelled")

    with pytest.raises(RuntimeError, match="cancelled"):
        vfs.read_at(vector.service.root_fd, vector.containers, vfs.MAX_METADATA_BYTES, cancelled)
    assert calls == [1]


def test_proc_reader_preserves_every_short_read_until_actual_eof(tmp_path, monkeypatch):
    path = tmp_path / "kernel-sequence-vector"
    payload = b"first-row\nsecond-row\nlast-row\n"
    path.write_bytes(payload)
    original_read = os.read
    reads = []

    def short_read(descriptor, size):
        block = original_read(descriptor, min(size, 3))
        reads.append(block)
        return block

    monkeypatch.setattr(vfs.os, "read", short_read)
    assert vfs._proc_bytes(str(path), len(payload)) == payload
    assert len(reads) > 2 and reads[-1] == b""
    assert b"".join(reads) == payload and path.read_bytes() == payload


def test_proc_reader_enforces_cumulative_bound_across_short_reads_and_closes_fd(tmp_path, monkeypatch):
    path = tmp_path / "over-bound-kernel-sequence-vector"
    path.write_bytes(b"123456789")
    original_read = os.read
    descriptors, returned = [], []

    def short_read(descriptor, size):
        descriptors.append(descriptor)
        block = original_read(descriptor, min(size, 2))
        returned.append(block)
        return block

    monkeypatch.setattr(vfs.os, "read", short_read)
    with pytest.raises(BuildExecutionError, match="custody_vfs_service"):
        vfs._proc_bytes(str(path), 5)
    assert b"".join(returned) == b"123456"
    with pytest.raises(OSError):
        os.fstat(descriptors[0])
    assert path.read_bytes() == b"123456789"


@pytest.fixture
def service_root_double(tmp_path, monkeypatch):
    """Real held descriptors behind explicit process/namespace/socket doubles.

    A pipe models pidfd readiness; ordinary files model namespace handles.
    Nothing in these cases observes a real service or grants process authority.
    """
    base = tmp_path.resolve()
    root, other_root = base / "root", base / "other-root"
    root.mkdir()
    other_root.mkdir()
    namespace, client_namespace, other_namespace = (base / name for name in ("mnt", "client-mnt", "other-mnt"))
    for path in (namespace, client_namespace, other_namespace):
        path.write_bytes(b"inert namespace handle double")
    read_end, write_end = os.pipe()
    pid = 1234
    mappings = {f"/proc/{pid}/root": root, f"/proc/{pid}/ns/mnt": namespace,
                "/proc/self/ns/mnt": client_namespace}
    selected_socket = {"path": f"/run/user/{os.geteuid()}/podman/podman.sock",
                       "identity": {"device": 2, "inode": 40, "mode": stat.S_IFSOCK | 0o600,
                                    "uid": os.geteuid(), "gid": os.getegid()}, "kernel_inode": 123}
    state = {"ticks": 5678, "write_end": write_end}
    opened, instances = [], []
    original_open = os.open

    def open_proc(path, flags, *args, **kwargs):
        descriptor = original_open(mappings.get(str(path), path), flags, *args, **kwargs)
        opened.append(descriptor)
        return descriptor

    def open_pidfd(selected_pid, flags):
        assert selected_pid == pid and flags == 0
        descriptor = os.dup(read_end)
        opened.append(descriptor)
        return descriptor

    monkeypatch.setattr(vfs.os, "open", open_proc)
    monkeypatch.setattr(vfs.os, "pidfd_open", open_pidfd, raising=False)
    monkeypatch.setattr(vfs, "_start_ticks", lambda selected_pid: state["ticks"])
    monkeypatch.setattr(vfs, "_socket_owner", lambda *_args: copy.deepcopy(selected_socket))

    def create(checkpoint=lambda: None):
        value = vfs.ServiceRoot(pid, checkpoint)
        instances.append(value)
        return value

    value = SimpleNamespace(create=create, state=state, mappings=mappings, socket=selected_socket,
                            opened=opened, root=root, other_root=other_root,
                            other_namespace=other_namespace, pid=pid)
    try:
        yield value
    finally:
        for instance in instances:
            instance.close()
        os.close(read_end)
        if state["write_end"] is not None:
            os.close(state["write_end"])


def test_service_root_holds_original_descriptors_and_closes_them(service_root_double):
    fixture = service_root_double
    service = fixture.create()
    held = tuple(service.descriptors)
    assert len(held) == 3
    assert service.proof["root_identity"] == vfs.identity(fixture.root.stat())
    assert service.proof["mount_namespace"] != service.proof["client_mount_namespace"]
    service.verify()
    service.close()
    assert service.descriptors == []
    service.close()
    for descriptor in held:
        with pytest.raises(OSError):
            os.fstat(descriptor)


@pytest.mark.parametrize("drift", ["pid-exit", "start", "root", "service-namespace", "client-namespace", "socket"])
def test_service_root_refuses_original_process_or_view_drift(service_root_double, drift):
    fixture = service_root_double
    service = fixture.create()
    if drift == "pid-exit":
        os.close(fixture.state["write_end"])
        fixture.state["write_end"] = None
    elif drift == "start":
        fixture.state["ticks"] += 1
    elif drift == "root":
        fixture.mappings[f"/proc/{fixture.pid}/root"] = fixture.other_root
    elif drift == "service-namespace":
        fixture.mappings[f"/proc/{fixture.pid}/ns/mnt"] = fixture.other_namespace
    elif drift == "client-namespace":
        fixture.mappings["/proc/self/ns/mnt"] = fixture.other_namespace
    else:
        fixture.socket["identity"]["inode"] += 1
    with pytest.raises(BuildExecutionError, match="custody_vfs_service_drift"):
        service.verify()


def test_service_root_initialization_failure_closes_all_opened_descriptors(service_root_double, monkeypatch):
    fixture = service_root_double

    def refuse(*_args):
        raise BuildExecutionError("custody_vfs_service")

    monkeypatch.setattr(vfs, "_socket_owner", refuse)
    with pytest.raises(BuildExecutionError, match="custody_vfs_service"):
        fixture.create()
    for descriptor in set(fixture.opened):
        with pytest.raises(OSError):
            os.fstat(descriptor)


def test_service_root_verification_keeps_original_checkpoint(service_root_double):
    calls = []

    def checkpoint():
        calls.append(1)
        if len(calls) > 1:
            raise BuildExecutionError("deadline_expired")

    service = service_root_double.create(checkpoint)
    with pytest.raises(BuildExecutionError, match="deadline_expired"):
        service.verify()
    assert calls == [1, 1]


@pytest.mark.parametrize("case", ["valid", "missing-owned-fd", "duplicate-listener", "wrong-flags"])
def test_socket_binding_requires_exact_original_listener_and_owned_fd(monkeypatch, case):
    # This is a real temporary Unix socket, with an explicitly synthetic proc
    # table/fd listing. It does not establish an installed Podman service.
    with (tempfile.TemporaryDirectory(prefix="lvfs-", dir="/tmp") as directory,
          socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener):
        endpoint = Path(directory).resolve() / "podman.sock"
        listener.bind(str(endpoint))
        flags = "00000000" if case == "wrong-flags" else "00010000"
        row = f"0000: 00000002 00000000 {flags} 0001 01 12345 {endpoint}\n"
        raw = ("Num RefCount Protocol Flags Type St Inode Path\n" + row
               + (row if case == "duplicate-listener" else "")).encode()

        @contextmanager
        def entries(_path):
            yield iter([SimpleNamespace(path="/synthetic-proc-fd/4")])

        with monkeypatch.context() as proc:
            proc.setattr(vfs, "_proc_bytes", lambda _path: raw)
            proc.setattr(vfs.os, "scandir", entries)
            proc.setattr(vfs.os, "readlink", lambda _path: (
                "socket:[99999]" if case == "missing-owned-fd" else "socket:[12345]"))
            if case == "valid":
                proof = vfs._socket_owner(1234, endpoint, lambda: None)
                assert proof["kernel_inode"] == 12345
                assert proof["identity"] == vfs.identity(endpoint.lstat())
            else:
                with pytest.raises(BuildExecutionError, match="custody_vfs_service"):
                    vfs._socket_owner(1234, endpoint, lambda: None)



def test_mount_table_decodes_supported_escape_and_keeps_original_raw_pin(monkeypatch):
    raw = (b"1 0 0:1 / / rw - rootfs rootfs rw\n"
           b"2 1 0:2 / /space\\040path rw - tmpfs tmpfs rw\n")
    calls = []
    monkeypatch.setattr(vfs, "_proc_bytes", lambda _path, maximum=0: raw)
    digest, points = vfs.mount_table(None, lambda: calls.append(1))
    assert digest == vfs._digest(raw)
    assert points == [Path("/"), Path("/space path")]
    assert len(calls) >= 2


def test_mount_table_refuses_unsupported_escape(monkeypatch):
    raw = b"1 0 0:1 / /invalid\\041escape rw - tmpfs tmpfs rw\n"
    monkeypatch.setattr(vfs, "_proc_bytes", lambda _path, maximum=0: raw)
    with pytest.raises(BuildExecutionError, match="custody_vfs_"):
        vfs.mount_table(None, lambda: None)


def test_mount_table_has_finite_record_bound(monkeypatch):
    raw = (b"1 0 0:1 / / rw - rootfs rootfs rw\n"
           b"2 1 0:2 / /elsewhere rw - tmpfs tmpfs rw\n")
    monkeypatch.setattr(vfs, "_proc_bytes", lambda _path, maximum=0: raw)
    monkeypatch.setattr(vfs, "MAX_RECORDS", 1)
    with pytest.raises(BuildExecutionError, match="custody_vfs_"):
        vfs.mount_table(None, lambda: None)


@pytest.mark.parametrize("alias", ["exact", "descendant"])
def test_service_mount_alias_at_or_inside_original_protected_root_is_refused(vector, monkeypatch, alias):
    mount = vector.root if alias == "exact" else vector.root / "nested-helper"
    monkeypatch.setattr(vfs, "mount_table", lambda _pid, _checkpoint: ("e" * 64, [Path("/"), mount]))
    with pytest.raises(BuildExecutionError, match="custody_vfs_"):
        vfs.check_mount_tables(vector.service, [vector.root], lambda: None)


def test_service_mount_table_uses_path_components_for_prefix_sibling(vector, monkeypatch):
    sibling = vector.root.with_name(vector.root.name + "-sibling")
    monkeypatch.setattr(vfs, "mount_table", lambda _pid, _checkpoint: ("e" * 64, [Path("/"), sibling]))
    assert vfs.check_mount_tables(vector.service, [vector.root], lambda: None) == {
        "service_sha256": "e" * 64, "client_sha256": "e" * 64}


def test_mount_table_preserves_original_checkpoint_before_parse(monkeypatch):
    monkeypatch.setattr(vfs, "_proc_bytes", lambda _path, maximum=0:
                        b"1 0 0:1 / / rw - rootfs rootfs rw\n")

    def cancelled():
        raise BuildExecutionError("deadline_expired")

    with pytest.raises(BuildExecutionError, match="deadline_expired"):
        vfs.mount_table(None, cancelled)


def test_acquisition_refuses_mount_table_drift_before_return(vector, monkeypatch):
    calls = []

    def mount_table(_pid, _checkpoint):
        calls.append(1)
        return ("e" * 64 if len(calls) <= 2 else "f" * 64, [Path("/")])

    monkeypatch.setattr(vfs, "mount_table", mount_table)
    with pytest.raises(BuildExecutionError, match="custody_vfs_"):
        acquire(vector)
    assert len(calls) >= 3
