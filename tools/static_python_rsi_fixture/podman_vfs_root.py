"""Private bounded VFS acquisition through the original local service root.

The controlled /proc/PID/{root,ns/mnt} magic links are the only followed links.
All storage, OCI and workspace paths are walked beneath the held service root
with O_NOFOLLOW. These observations do not establish immutable custody.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import select
import stat
from collections.abc import Callable
from pathlib import Path

from tools.static_python_rsi_fixture.execution_backend import BuildExecutionError, _fail

BACKEND = "podman-snapshots-source-data-vfs-v1"
SCHEMA = "lunar-podman-vfs-root-acquisition-v1"
MAX_METADATA_BYTES = 2 * 1024**2
MAX_RECORDS = 4096
_ID = re.compile(r"[a-f0-9]{64}\Z")
_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _pairs(rows):
    result = {}
    for key, value in rows:
        if key in result:
            _fail("custody_vfs_metadata")
        result[key] = value
    return result


def decode(raw: bytes):
    if type(raw) is not bytes or len(raw) > MAX_METADATA_BYTES:
        _fail("custody_vfs_metadata")
    try:
        return json.loads(raw, object_pairs_hook=_pairs,
                          parse_constant=lambda _value: _fail("custody_vfs_metadata"))
    except (ValueError, UnicodeError, RecursionError):
        _fail("custody_vfs_metadata")


def absolute(value: object) -> Path:
    if (type(value) is not str or not value.startswith("/") or len(value) > 4096
            or any(part in {"", ".", ".."} for part in value.split("/")[1:])
            or any(char in value for char in ":\n\r\0\\")):
        _fail("custody_vfs_path")
    return Path(value)


def identity(info: os.stat_result) -> dict:
    return {"device": info.st_dev, "inode": info.st_ino, "mode": info.st_mode,
            "uid": info.st_uid, "gid": info.st_gid}


def _open_at(root_fd: int, path: Path, *, directory: bool = False,
             checkpoint: Callable[[], None] = lambda: None) -> int:
    parts = absolute(str(path)).parts[1:]
    descriptor = os.dup(root_fd)
    try:
        for index, part in enumerate(parts):
            checkpoint()
            flags = _DIRECTORY if directory or index < len(parts) - 1 else (
                os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
            child = os.open(part, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return os.dup(descriptor)
    finally:
        os.close(descriptor)


def directory_at(root_fd: int, path: Path, checkpoint: Callable[[], None]) -> dict:
    checkpoint()
    descriptor = _open_at(root_fd, path, directory=True, checkpoint=checkpoint)
    try:
        return identity(os.fstat(descriptor))
    finally:
        os.close(descriptor)


def read_at(root_fd: int, path: Path, maximum: int, checkpoint: Callable[[], None],
            *, snapshots=None, role=None, phase=None) -> bytes:
    descriptor = _open_at(root_fd, path, checkpoint=checkpoint)
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_size > maximum:
            _fail("custody_vfs_metadata")
        chunks, count = [], 0
        while True:
            checkpoint()
            block = os.read(descriptor, min(65536, maximum + 1 - count))
            if not block:
                break
            chunks.append(block)
            count += len(block)
            if count > maximum:
                _fail("custody_vfs_metadata")
        after = os.fstat(descriptor)
        fields = ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_size",
                  "st_mtime_ns", "st_ctime_ns")
        if count != before.st_size or any(getattr(before, key) != getattr(after, key) for key in fields):
            _fail("custody_vfs_drift")
        # Reopen the same no-follow name to reject replacement during read.
        reopened = _open_at(root_fd, path, checkpoint=checkpoint)
        try:
            if any(getattr(before, key) != getattr(os.fstat(reopened), key) for key in fields):
                _fail("custody_vfs_drift")
        finally:
            os.close(reopened)
        raw = b"".join(chunks)
        if snapshots is not None:
            snapshots.record(role, phase, raw, {**identity(before), "size": before.st_size,
                                               "mtime_ns": before.st_mtime_ns, "ctime_ns": before.st_ctime_ns})
        return raw
    finally:
        os.close(descriptor)


def file_identity_at(root_fd: int, path: Path, checkpoint: Callable[[], None] = lambda: None) -> dict:
    descriptor = _open_at(root_fd, path, checkpoint=checkpoint)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            _fail("custody_vfs_metadata")
        return {**identity(info), "size": info.st_size, "mtime_ns": info.st_mtime_ns,
                "ctime_ns": info.st_ctime_ns}
    finally:
        os.close(descriptor)


def _proc_bytes(path: str, maximum: int = 1024**2) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        chunks, count = [], 0
        while True:
            block = os.read(descriptor, min(65536, maximum + 1 - count))
            if not block:
                return b"".join(chunks)
            count += len(block)
            if count > maximum:
                _fail("custody_vfs_service")
            chunks.append(block)
    finally:
        os.close(descriptor)


def _start_ticks(pid: int) -> int:
    raw = _proc_bytes(f"/proc/{pid}/stat", 65536)
    try:
        prefix, remainder = raw.rsplit(b")", 1)
        ticks = int(remainder.split()[19])
        valid = int(prefix.split(b"(", 1)[0]) == pid and ticks > 0
    except (ValueError, IndexError):
        valid = False
    if not valid:
        _fail("custody_vfs_service")
    if os.stat(f"/proc/{pid}").st_uid != os.geteuid():
        _fail("custody_vfs_service")
    return ticks


def _namespace(descriptor: int) -> dict:
    info = os.fstat(descriptor)
    return {"device": info.st_dev, "inode": info.st_ino}


def _socket_owner(pid: int, socket: Path, checkpoint: Callable[[], None]) -> dict:
    info = socket.lstat()
    if not stat.S_ISSOCK(info.st_mode) or info.st_uid != os.geteuid():
        _fail("custody_vfs_service")
    rows = _proc_bytes(f"/proc/{pid}/net/unix").decode("ascii").splitlines()[1:]
    matching = []
    for row in rows:
        checkpoint()
        fields = row.split()
        if len(fields) == 8 and fields[7] == str(socket):
            if fields[3] != "00010000" or fields[4] != "0001" or not fields[6].isdigit():
                _fail("custody_vfs_service")
            matching.append(int(fields[6]))
    if len(matching) != 1:
        _fail("custody_vfs_service")
    owned = False
    with os.scandir(f"/proc/{pid}/fd") as entries:
        for count, entry in enumerate(entries, 1):
            checkpoint()
            if count > MAX_RECORDS:
                _fail("custody_vfs_service")
            try:
                owned |= os.readlink(entry.path) == f"socket:[{matching[0]}]"
            except FileNotFoundError:
                continue
    if not owned:
        _fail("custody_vfs_service")
    return {"path": str(socket), "identity": identity(info), "kernel_inode": matching[0]}


def parse_mount_table(raw: bytes, checkpoint: Callable[[], None]) -> list[Path]:
    """Parse one bounded original kernel table without querying a live process."""
    if type(raw) is not bytes or len(raw) > 1024**2:
        _fail("custody_vfs_mountinfo")
    rows = raw.splitlines()
    if not rows or len(rows) > MAX_RECORDS:
        _fail("custody_vfs_mountinfo")
    paths = []
    for row in rows:
        checkpoint()
        before, separator, after = row.partition(b" - ")
        fields, filesystem = before.split(), after.split()
        if (not separator or len(fields) < 6 or len(filesystem) != 3
                or not fields[0].isdigit() or int(fields[0]) <= 0 or not fields[1].isdigit()
                or re.fullmatch(rb"[0-9]+:[0-9]+", fields[2]) is None):
            _fail("custody_vfs_mountinfo")
        try:
            encoded = fields[4].decode("ascii")
            decoded = re.sub(r"\\(040|011|012|134)", lambda match: chr(int(match[1], 8)), encoded)
            path = Path("/") if decoded == "/" else absolute(decoded)
        except (ValueError, UnicodeError, BuildExecutionError):
            _fail("custody_vfs_mountinfo")
        paths.append(path)
    return paths


def mount_table(pid: int | None, checkpoint: Callable[[], None], *, snapshots=None,
                role: str = "service", phase: str = "acquire-before") -> tuple[str, list[Path]]:
    """Read only bounded kernel mount topology, without exposing its path rows."""
    checkpoint()
    raw = _proc_bytes(f"/proc/{pid if pid is not None else 'self'}/mountinfo")
    if snapshots is not None:
        snapshots.record("mountinfo-" + role, phase, raw)
    return _digest(raw), parse_mount_table(raw, checkpoint)


def check_mount_tables(service: ServiceRoot, protected: list[Path],
                       checkpoint: Callable[[], None], *, snapshots=None,
                       phase: str = "acquire-before") -> dict:
    """The supported profile refuses subordinate mounts in either namespace."""
    result = {}
    for role, pid in (("service", service.pid), ("client", None)):
        options = {"snapshots": snapshots, "role": role, "phase": phase} if snapshots is not None else {}
        digest, mounts = mount_table(pid, checkpoint, **options)
        for mount in mounts:
            checkpoint()
            if any(mount == path or path in mount.parents for path in protected):
                _fail("custody_vfs_namespace_mount")
        result[role + "_sha256"] = digest
    return result


class ServiceRoot:
    """Held original service process/root/namespace, not a reusable authority token."""

    def __init__(self, pid: int, checkpoint: Callable[[], None]):
        if type(pid) is not int or not 0 < pid < 2**31:
            _fail("custody_vfs_service")
        self.checkpoint, self.pid = checkpoint, pid
        self.descriptors: list[int] = []
        try:
            self.pid_fd = os.pidfd_open(pid, 0)
            self.descriptors.append(self.pid_fd)
            self.start = _start_ticks(pid)
            # These two controlled kernel magic links are deliberate exceptions.
            self.root_fd = os.open(f"/proc/{pid}/root", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
            self.descriptors.append(self.root_fd)
            self.namespace_fd = os.open(f"/proc/{pid}/ns/mnt", os.O_RDONLY | os.O_CLOEXEC)
            self.descriptors.append(self.namespace_fd)
            client = os.open("/proc/self/ns/mnt", os.O_RDONLY | os.O_CLOEXEC)
            try:
                client_namespace = _namespace(client)
            finally:
                os.close(client)
            self.socket = Path(f"/run/user/{os.geteuid()}/podman/podman.sock")
            self.proof = {"pid": pid, "start_ticks": self.start,
                          "root_identity": identity(os.fstat(self.root_fd)),
                          "mount_namespace": _namespace(self.namespace_fd),
                          "client_mount_namespace": client_namespace,
                          "socket": _socket_owner(pid, self.socket, checkpoint)}
            self.verify()
        except BaseException:
            self.close()
            raise

    def verify(self) -> None:
        self.checkpoint()
        poller = select.poll()
        poller.register(self.pid_fd, select.POLLIN)
        if poller.poll(0) or _start_ticks(self.pid) != self.start:
            _fail("custody_vfs_service_drift")
        for path, expected, namespace in (
            (f"/proc/{self.pid}/root", self.proof["root_identity"], False),
            (f"/proc/{self.pid}/ns/mnt", self.proof["mount_namespace"], True),
            ("/proc/self/ns/mnt", self.proof["client_mount_namespace"], True),
        ):
            descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
            try:
                observed = _namespace(descriptor) if namespace else identity(os.fstat(descriptor))
                if observed != expected:
                    _fail("custody_vfs_service_drift")
            finally:
                os.close(descriptor)
        if _socket_owner(self.pid, self.socket, self.checkpoint) != self.proof["socket"]:
            _fail("custody_vfs_service_drift")

    def close(self) -> None:
        for descriptor in reversed(self.descriptors):
            os.close(descriptor)
        self.descriptors.clear()


def _records(raw: bytes) -> list[dict]:
    rows = decode(raw)
    if (type(rows) is not list or not 0 < len(rows) <= MAX_RECORDS
            or any(type(row) is not dict or type(row.get("id")) is not str
                   or _ID.fullmatch(row["id"]) is None for row in rows)
            or len({row["id"] for row in rows}) != len(rows)):
        _fail("custody_vfs_metadata")
    return rows


def acquire(service: ServiceRoot, info_raw: bytes, selected: dict, container: str,
            image: str, expected_mounts: dict, checkpoint: Callable[[], None],
            *, snapshots=None) -> tuple[bytes, dict]:
    """Join fresh independent service metadata to one actual initialized OCI root."""
    info = decode(info_raw)
    if (type(info) is not dict or set(info) != {"driver", "graph_root", "run_root"}
            or info["driver"] != "vfs" or selected.get("container_id") != container
            or any(type(selected.get(key)) is not str for key in (
                "container_id", "image", "oci", "resolver", "hostname", "hosts"))
            or selected["image"].removeprefix("sha256:") != image):
        _fail("custody_vfs_metadata")
    graph, run = absolute(info["graph_root"]), absolute(info["run_root"])
    if graph == run or graph in run.parents or run in graph.parents:
        _fail("custody_vfs_path")
    protected = [graph, run, *(absolute(row["source"]) for row in expected_mounts.values())]
    capture = {"snapshots": snapshots} if snapshots is not None else {}
    mount_tables = check_mount_tables(service, protected, checkpoint, **capture)
    directory_at(service.root_fd, run, checkpoint)
    container_path, layer_path = graph / "vfs-containers/containers.json", graph / "vfs-layers/layers.json"
    container_identity = file_identity_at(service.root_fd, container_path, checkpoint)
    layer_identity = file_identity_at(service.root_fd, layer_path, checkpoint)
    def captured(role, phase):
        return {"snapshots": snapshots, "role": role, "phase": phase} if snapshots is not None else {}

    containers_raw = read_at(service.root_fd, container_path, MAX_METADATA_BYTES, checkpoint,
                             **captured("containers", "before"))
    layers_raw = read_at(service.root_fd, layer_path, MAX_METADATA_BYTES, checkpoint,
                         **captured("layers", "before"))
    containers, layers = _records(containers_raw), _records(layers_raw)
    matches = [row for row in containers if row["id"] == container]
    if len(matches) != 1:
        _fail("custody_vfs_metadata")
    record = matches[0]
    layer = record.get("layer")
    if (record.get("image") != image or type(layer) is not str or _ID.fullmatch(layer) is None
            or sum(row["id"] == layer for row in layers) != 1
            or sum(row.get("layer") == layer for row in containers) != 1):
        _fail("custody_vfs_metadata")
    layer_record = next(row for row in layers if row["id"] == layer)
    parent = layer_record.get("parent")
    if parent is not None and parent != "" and (type(parent) is not str or _ID.fullmatch(parent) is None):
        _fail("custody_vfs_metadata")
    root = graph / "vfs/dir" / layer
    root_identity = directory_at(service.root_fd, root, checkpoint)
    host = os.open("/", _DIRECTORY)
    try:
        if directory_at(host, root, checkpoint) != root_identity:
            _fail("custody_vfs_namespace_view")
    finally:
        os.close(host)
    for row in expected_mounts.values():
        if directory_at(service.root_fd, absolute(row["source"]), checkpoint) != row["identity"]:
            _fail("custody_vfs_namespace_view")
    oci = absolute(selected.get("oci"))
    if oci != graph / "vfs-containers" / container / "userdata/config.json":
        _fail("custody_vfs_metadata")
    oci_identity = file_identity_at(service.root_fd, oci, checkpoint)
    oci_raw = read_at(service.root_fd, oci, 1024**2, checkpoint, **captured("oci", "acquire"))
    spec = decode(oci_raw)
    if (type(spec) is not dict or type(spec.get("root")) is not dict
            or spec["root"].get("path") != str(root)):
        _fail("custody_vfs_root")
    ancillary = []
    selected_mounts = spec.get("mounts", [])
    if type(selected_mounts) is not list:
        _fail("custody_vfs_metadata")
    host = os.open("/", _DIRECTORY)
    try:
        for destination in ("/etc/resolv.conf", "/etc/passwd", "/etc/group", "/run/.containerenv"):
            rows = [row for row in selected_mounts if type(row) is dict and row.get("destination") == destination]
            if not rows:
                continue
            if len(rows) != 1 or rows[0].get("type") != "bind":
                _fail("custody_vfs_namespace_view")
            source = absolute(rows[0].get("source"))
            ceiling = 1 if destination == "/etc/resolv.conf" else 16384
            actual_identity = file_identity_at(service.root_fd, source, checkpoint)
            host_identity = file_identity_at(host, source, checkpoint)
            if actual_identity != host_identity:
                _fail("custody_vfs_namespace_view")
            role = "ancillary-" + {"/etc/resolv.conf": "resolver", "/etc/passwd": "passwd",
                                    "/etc/group": "group", "/run/.containerenv": "containerenv"}[destination]
            actual_bytes = read_at(service.root_fd, source, ceiling, checkpoint, **captured(role, "service"))
            host_bytes = read_at(host, source, ceiling, checkpoint, **captured(role, "host"))
            if actual_bytes != host_bytes:
                _fail("custody_vfs_namespace_view")
            if actual_identity != file_identity_at(service.root_fd, source, checkpoint):
                _fail("custody_vfs_drift")
            ancillary.append({"destination": destination, "source": str(source), "identity": actual_identity,
                              "size": len(actual_bytes), "sha256": _digest(actual_bytes)})
    finally:
        os.close(host)
    # Re-read original metadata names; a consistent replacement is still drift.
    containers_after = read_at(service.root_fd, container_path, MAX_METADATA_BYTES, checkpoint,
                               **captured("containers", "after"))
    # Keep the original short-circuit: a changed first body does not permit extra reads.
    if containers_after != containers_raw:
        _fail("custody_vfs_drift")
    layers_after = read_at(service.root_fd, layer_path, MAX_METADATA_BYTES, checkpoint,
                           **captured("layers", "after"))
    if (layers_after != layers_raw
            or file_identity_at(service.root_fd, container_path, checkpoint) != container_identity
            or file_identity_at(service.root_fd, layer_path, checkpoint) != layer_identity
            or file_identity_at(service.root_fd, oci, checkpoint) != oci_identity):
        _fail("custody_vfs_drift")
    after_options = {"snapshots": snapshots, "phase": "acquire-after"} if snapshots is not None else {}
    if check_mount_tables(service, protected, checkpoint, **after_options) != mount_tables:
        _fail("custody_vfs_namespace_mount_drift")
    service.verify()
    proof = {"schema": SCHEMA, "backend": BACKEND, "container_id": container,
             "image_id": image, "layer_id": layer, "graph_root": str(graph), "run_root": str(run),
             "root": {"path": str(root), "identity": root_identity}, "service": service.proof,
             "mount_tables": mount_tables, "ancillary_mounts": ancillary,
             "metadata": {"info_sha256": _digest(info_raw), "containers_sha256": _digest(containers_raw),
                          "layers_sha256": _digest(layers_raw), "oci_sha256": _digest(oci_raw),
                          "containers_identity": container_identity, "layers_identity": layer_identity,
                          "oci_identity": oci_identity}}
    return oci_raw, proof


def validate_proof(value: object, *, container: str, root: dict, oci_sha256: str) -> bool:
    """Strict detached proof shape/cross-pins; this does not reacquire a service."""
    try:
        if (type(value) is not dict or set(value) != {"schema", "backend", "container_id", "image_id",
                "layer_id", "graph_root", "run_root", "root", "service", "metadata", "mount_tables",
                "ancillary_mounts"}
                or value["schema"] != SCHEMA or value["backend"] != BACKEND
                or value["container_id"] != container or type(value["root"]) is not dict
                or set(value["root"]) != {"path", "identity"}
                or value["root"] != {"path": root["path"], "identity": root["identity"]}
                or any(type(value[key]) is not str or _ID.fullmatch(value[key]) is None
                       for key in ("container_id", "image_id", "layer_id"))):
            return False
        graph, run = absolute(value["graph_root"]), absolute(value["run_root"])
        if (graph == run or graph in run.parents or run in graph.parents
                or value["root"]["path"] != str(graph / "vfs/dir" / value["layer_id"])):
            return False
        metadata, service = value["metadata"], value["service"]
        tables, ancillary = value["mount_tables"], value["ancillary_mounts"]
        if (type(tables) is not dict or set(tables) != {"service_sha256", "client_sha256"}
                or any(type(item) is not str or _ID.fullmatch(item) is None for item in tables.values())
                or type(ancillary) is not list or len(ancillary) > 4):
            return False
        seen = set()
        for row in ancillary:
            if (type(row) is not dict or set(row) != {"destination", "source", "identity", "size", "sha256"}
                    or type(row["destination"]) is not str or row["destination"] in seen
                    or row["destination"] not in {"/etc/resolv.conf", "/etc/passwd", "/etc/group", "/run/.containerenv"}
                    or type(row["sha256"]) is not str or _ID.fullmatch(row["sha256"]) is None
                    or type(row["size"]) is not int or not 0 <= row["size"] <= (
                        1 if row["destination"] == "/etc/resolv.conf" else 16384)):
                return False
            absolute(row["source"])
            item = row["identity"]
            if (type(item) is not dict or set(item) != {"device", "inode", "mode", "uid", "gid",
                    "size", "mtime_ns", "ctime_ns"}
                    or any(type(number) is not int or number < 0 for number in item.values())
                    or not stat.S_ISREG(item["mode"]) or item["size"] != row["size"]):
                return False
            seen.add(row["destination"])
        if (type(metadata) is not dict or set(metadata) != {"info_sha256", "containers_sha256",
                "layers_sha256", "oci_sha256", "containers_identity", "layers_identity", "oci_identity"}
                or metadata["oci_sha256"] != oci_sha256
                or any(type(metadata[key]) is not str or _ID.fullmatch(metadata[key]) is None
                       for key in ("info_sha256", "containers_sha256", "layers_sha256", "oci_sha256"))
                or type(service) is not dict or set(service) != {"pid", "start_ticks", "root_identity",
                    "mount_namespace", "client_mount_namespace", "socket"}
                or any(type(service[key]) is not int or service[key] <= 0 for key in ("pid", "start_ticks"))):
            return False
        for key in ("mount_namespace", "client_mount_namespace"):
            item = service[key]
            if (type(item) is not dict or set(item) != {"device", "inode"}
                    or any(type(number) is not int or number < 0 for number in item.values())):
                return False
        for key in ("containers_identity", "layers_identity", "oci_identity"):
            item = metadata[key]
            if (type(item) is not dict or set(item) != {"device", "inode", "mode", "uid", "gid",
                    "size", "mtime_ns", "ctime_ns"}
                    or any(type(number) is not int or number < 0 for number in item.values())
                    or not stat.S_ISREG(item["mode"]) or item["size"] > MAX_METADATA_BYTES):
                return False
        for item in (service["root_identity"], service["socket"].get("identity"), value["root"]["identity"]):
            if (type(item) is not dict or set(item) != {"device", "inode", "mode", "uid", "gid"}
                    or any(type(number) is not int or number < 0 for number in item.values())):
                return False
        socket = service["socket"]
        return (type(socket) is dict and set(socket) == {"path", "identity", "kernel_inode"}
                and socket["path"] == f"/run/user/{socket['identity']['uid']}/podman/podman.sock"
                and type(socket["kernel_inode"]) is int and socket["kernel_inode"] > 0
                and stat.S_ISSOCK(socket["identity"]["mode"])
                and stat.S_ISDIR(service["root_identity"]["mode"])
                and stat.S_ISDIR(value["root"]["identity"]["mode"]))
    except (KeyError, TypeError, AttributeError, ValueError, BuildExecutionError):
        return False
