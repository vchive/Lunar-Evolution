"""Local private, create-only retention of the original bounded VFS buffers.

The detached reader never queries Podman, /proc, or storage source paths. These
artifacts support inspection of observations, not immutable or remote custody.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path

from tools.static_python_rsi_fixture import podman_vfs_root as vfs

SCHEMA = "lunar-podman-vfs-raw-snapshots-v1"
MAX_STORED_BYTES = 512 * 1024**2
MAX_RECORDS = 24
MAX_COMMANDS = 512
MAX_MANIFEST_BYTES = 65536
MAX_RECEIPT_BYTES = 4096
_DIRECTORY = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_ID = re.compile(r"[a-f0-9]{64}\Z")
_STAGES = {"configure", "freeze", "compile", "link"}
_BINDING = {"recipe_sha256", "stage", "index", "container_id", "image_id", "root_acquisition_sha256"}
_IDENTITY = {"device", "inode", "mode", "uid", "gid", "size", "mtime_ns", "ctime_ns"}
_ANCILLARY = {"/etc/resolv.conf": "resolver", "/etc/passwd": "passwd",
              "/etc/group": "group", "/run/.containerenv": "containerenv"}


def _refuse():
    raise ValueError("podman_vfs_snapshots")


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii") + b"\n"


def _file_identity(info):
    return {"device": info.st_dev, "inode": info.st_ino, "mode": info.st_mode,
            "uid": info.st_uid, "gid": info.st_gid, "size": info.st_size,
            "mtime_ns": info.st_mtime_ns, "ctime_ns": info.st_ctime_ns}


def _identity_ok(value, size):
    return (type(value) is dict and set(value) == _IDENTITY
            and all(type(number) is int and number >= 0 for number in value.values())
            and stat.S_ISREG(value["mode"]) and value["size"] == size)


def _command(stage, index):
    if type(stage) is not str or stage not in _STAGES or type(index) is not int or not 0 <= index < MAX_COMMANDS:
        _refuse()
    return f"custody/{stage}-{index}/vfs-raw"


def _parts(relative):
    if (type(relative) is not str or len(relative) > 4096 or relative.startswith("/")
            or any(part in {"", ".", ".."} for part in relative.split("/"))
            or any(char in relative for char in "\\\n\r\0")):
        _refuse()
    return relative.split("/")


def _root(path, checkpoint):
    path = Path(path)
    if not path.is_absolute():
        _refuse()
    descriptor = os.open("/", _DIRECTORY)
    try:
        for part in path.parts[1:]:
            checkpoint()
            if part in {"", ".", ".."}:
                _refuse()
            child = os.open(part, _DIRECTORY, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return os.dup(descriptor)
    finally:
        os.close(descriptor)


def _parent(root_fd, relative, checkpoint):
    parts = _parts(relative)
    descriptor = os.dup(root_fd)
    try:
        for part in parts[:-1]:
            checkpoint()
            child = os.open(part, _DIRECTORY, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return os.dup(descriptor), parts[-1]
    finally:
        os.close(descriptor)


def _private_dir(root_fd, relative, checkpoint, *, create):
    parent, name = _parent(root_fd, relative, checkpoint)
    try:
        checkpoint()
        if create:
            os.mkdir(name, 0o700, dir_fd=parent)
            os.fsync(parent)
        descriptor = os.open(name, _DIRECTORY, dir_fd=parent)
        try:
            info = os.fstat(descriptor)
            if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
                _refuse()
            return vfs.identity(info)
        finally:
            os.close(descriptor)
    finally:
        os.close(parent)


def _directory_identity(root_fd, relative, checkpoint):
    if relative == "":
        return vfs.identity(os.fstat(root_fd))
    parent, name = _parent(root_fd, relative, checkpoint)
    try:
        checkpoint()
        descriptor = os.open(name, _DIRECTORY, dir_fd=parent)
        try:
            return vfs.identity(os.fstat(descriptor))
        finally:
            os.close(descriptor)
    finally:
        os.close(parent)


def _read(root_fd, relative, size, digest, maximum, checkpoint, expected=None):
    if (type(size) is not int or not 0 <= size <= maximum
            or type(digest) is not str or _ID.fullmatch(digest) is None):
        _refuse()
    parent, name = _parent(root_fd, relative, checkpoint)
    try:
        checkpoint()
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent)
        try:
            before = os.fstat(descriptor)
            original = _file_identity(before)
            if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                    or before.st_uid != os.geteuid() or stat.S_IMODE(before.st_mode) != 0o600
                    or before.st_size != size or expected is not None and original != expected):
                _refuse()
            blocks, count = [], 0
            while True:
                checkpoint()
                block = os.read(descriptor, min(65536, size + 1 - count))
                if not block:
                    break
                blocks.append(block)
                count += len(block)
                if count > size:
                    _refuse()
            raw = b"".join(blocks)
            if count != size or _sha(raw) != digest or _file_identity(os.fstat(descriptor)) != original:
                _refuse()
            checkpoint()
            repeated = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent)
            try:
                if _file_identity(os.fstat(repeated)) != original or os.fstat(repeated).st_nlink != 1:
                    _refuse()
            finally:
                os.close(repeated)
            return raw, original
        finally:
            os.close(descriptor)
    finally:
        os.close(parent)


def _decode(raw):
    def pairs(rows):
        value = {}
        for key, item in rows:
            if key in value:
                _refuse()
            value[key] = item
        return value

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=lambda _item: _refuse())


def _limit(role, phase):
    if role in {"info", "inspect"} and phase == "selection":
        return 16384 if role == "info" else 32768
    if role in {"containers", "layers"} and phase in {"before", "after"}:
        return 2 * 1024**2
    if role == "oci" and phase == "acquire":
        return 1024**2
    if role in {"mountinfo-service", "mountinfo-client"} and phase in {
            "acquire-before", "acquire-after", "final-view"}:
        return 1024**2
    if role in {"ancillary-" + item for item in _ANCILLARY.values()} and phase in {"service", "host"}:
        return 1 if role == "ancillary-resolver" else 16384
    _refuse()


def _binding(value):
    if type(value) is not dict or set(value) != _BINDING:
        _refuse()
    _command(value["stage"], value["index"])
    for key in _BINDING - {"stage", "index"}:
        if type(value[key]) is not str or _ID.fullmatch(value[key]) is None:
            _refuse()


class VfsSnapshotStore:
    """One attempt's bounded CAS; only this instance's blobs may be reused."""

    def __init__(self, destination, checkpoint):
        self.destination, self.checkpoint = Path(destination), checkpoint
        self.stored_bytes, self.blobs, self.commands = 0, {}, {}
        self.directories = {}
        root_fd = _root(self.destination, checkpoint)
        try:
            self.directories[""] = _directory_identity(root_fd, "", checkpoint)
            self.directories["custody"] = _private_dir(root_fd, "custody", checkpoint, create=False)
            for relative in ("custody/vfs-raw", "custody/vfs-raw/blobs"):
                self.directories[relative] = _private_dir(root_fd, relative, checkpoint, create=True)
        finally:
            os.close(root_fd)
        self._check_names()

    def _open_checked(self):
        descriptor = _root(self.destination, self.checkpoint)
        try:
            for relative, expected in self.directories.items():
                if _directory_identity(descriptor, relative, self.checkpoint) != expected:
                    _refuse()
            return os.dup(descriptor)
        finally:
            os.close(descriptor)

    def _check_names(self):
        descriptor = self._open_checked()
        os.close(descriptor)

    def _write(self, relative, raw, maximum):
        self.checkpoint()
        if len(raw) > maximum or self.stored_bytes + len(raw) > MAX_STORED_BYTES:
            _refuse()
        self.stored_bytes += len(raw)
        root_fd = self._open_checked()
        try:
            parent, name = _parent(root_fd, relative, self.checkpoint)
            try:
                self.checkpoint()
                descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                                     0o600, dir_fd=parent)
                try:
                    offset = 0
                    while offset < len(raw):
                        self.checkpoint()
                        written = os.write(descriptor, raw[offset:offset + 65536])
                        if written <= 0:
                            _refuse()
                        offset += written
                    self.checkpoint()
                    os.fsync(descriptor)
                    expected = _file_identity(os.fstat(descriptor))
                finally:
                    os.close(descriptor)
                self.checkpoint()
                os.fsync(parent)
            finally:
                os.close(parent)
            identity = _read(root_fd, relative, len(raw), _sha(raw), maximum, self.checkpoint, expected)[1]
            self._check_names()
            return identity
        finally:
            os.close(root_fd)

    def command(self, stage, index):
        relative = _command(stage, index)
        if (stage, index) in self.commands or len(self.commands) >= MAX_COMMANDS:
            _refuse()
        root_fd = self._open_checked()
        try:
            parent = relative.rsplit("/", 1)[0]
            self.directories[parent] = _directory_identity(root_fd, parent, self.checkpoint)
            self.directories[relative] = _private_dir(root_fd, relative, self.checkpoint, create=True)
        finally:
            os.close(root_fd)
        self._check_names()
        value = _Capture(self, stage, index, relative)
        self.commands[stage, index] = value
        return value

    def _lifetime(self, stage, index, *, worker_input_view=False):
        """Separate opt-in roles sharing this original attempt's CAS ledger."""
        from tools.static_python_rsi_fixture.podman_vfs_lifetime import _LifetimeCapture

        if type(worker_input_view) is not bool or (stage, index) not in self.commands:
            _refuse()
        # Do not create any additional directories/attributes on legacy routes.
        if not hasattr(self, "_lifetimes"):
            self._lifetimes = {}
        if (stage, index) in self._lifetimes:
            _refuse()
        capture = (_LifetimeCapture(self, stage, index, worker_input_view=True) if worker_input_view
                   else _LifetimeCapture(self, stage, index))
        self._lifetimes[stage, index] = capture
        return capture


class _Capture:
    def __init__(self, store, stage, index, relative):
        self.store, self.stage, self.index, self.relative = store, stage, index, relative
        self.records, self.keys, self.completed = [], set(), False

    def record(self, role, phase, raw, identity=None):
        maximum = _limit(role, phase)
        if (self.completed or type(raw) is not bytes or len(raw) > maximum
                or (role, phase) in self.keys or len(self.records) >= MAX_RECORDS):
            _refuse()
        source_required = role in {"containers", "layers", "oci"} or role.startswith("ancillary-")
        if source_required and not _identity_ok(identity, len(raw)) or not source_required and identity is not None:
            _refuse()
        digest = _sha(raw)
        relative = "custody/vfs-raw/blobs/" + digest + ".bin"
        if digest not in self.store.blobs:
            stored = self.store._write(relative, raw, maximum)
            self.store.blobs[digest] = stored
        else:
            root_fd = self.store._open_checked()
            try:
                _read(root_fd, relative, len(raw), digest, maximum, self.store.checkpoint, self.store.blobs[digest])
                self.store._check_names()
            finally:
                os.close(root_fd)
        row = {"role": role, "phase": phase, "size": len(raw), "sha256": digest,
               "source_identity": None if identity is None else dict(identity),
               "blob_identity": dict(self.store.blobs[digest])}
        receipt = _json(row)
        self.store._write(f"{self.relative}/record-{len(self.records):02d}.json", receipt, MAX_RECEIPT_BYTES)
        self.records.append(row)
        self.keys.add((role, phase))

    def complete(self, binding):
        _binding(binding)
        if self.completed or binding["stage"] != self.stage or binding["index"] != self.index:
            _refuse()
        # The final marker is emitted only once, after all original start gates.
        expected = {("info", "selection"), ("inspect", "selection"), ("oci", "acquire")}
        expected |= {(role, phase) for role in ("containers", "layers") for phase in ("before", "after")}
        expected |= {(role, phase) for role in ("mountinfo-service", "mountinfo-client")
                     for phase in ("acquire-before", "acquire-after", "final-view")}
        if not expected <= self.keys:
            _refuse()
        for role in {key[0] for key in self.keys if key[0].startswith("ancillary-")}:
            if {(role, "service"), (role, "host")} - self.keys:
                _refuse()
        directory_paths = {"", "custody", "custody/vfs-raw", "custody/vfs-raw/blobs",
                           self.relative, self.relative.rsplit("/", 1)[0]}
        directory_identities = {path: dict(self.store.directories[path]) for path in sorted(directory_paths)}
        value = {"schema": SCHEMA, "binding": dict(binding), "records": self.records, "complete": True,
                 "directory_identities": directory_identities,
                 "production_admission": False, "online_publication": False}
        raw = _json(value)
        relative = self.relative + "/manifest.json"
        self.store._write(relative, raw, MAX_MANIFEST_BYTES)
        self.completed = True
        return {"path": relative, "size": len(raw), "sha256": _sha(raw)}


def _verify(workspace, pin, binding, proof, operations, checkpoint):
    _binding(binding)
    relative = _command(binding["stage"], binding["index"])
    if (type(pin) is not dict or set(pin) != {"path", "size", "sha256"}
            or pin["path"] != relative + "/manifest.json"
            or type(proof) is not dict or _sha(_json(proof)) != binding["root_acquisition_sha256"]
            or proof.get("container_id") != binding["container_id"] or proof.get("image_id") != binding["image_id"]
            or not vfs.validate_proof(proof, container=binding["container_id"], root=proof.get("root", {}),
                                      oci_sha256=proof.get("metadata", {}).get("oci_sha256"))):
        _refuse()
    root_fd = _root(workspace, checkpoint)
    try:
        for directory in ("custody", "custody/vfs-raw", "custody/vfs-raw/blobs", relative):
            _private_dir(root_fd, directory, checkpoint, create=False)
        raw, _ = _read(root_fd, pin["path"], pin["size"], pin["sha256"], MAX_MANIFEST_BYTES, checkpoint)
        manifest = _decode(raw)
        if (type(manifest) is not dict or set(manifest) != {"schema", "binding", "records", "complete",
                "directory_identities", "production_admission", "online_publication"} or manifest["schema"] != SCHEMA
                or manifest["binding"] != binding or manifest["complete"] is not True
                or manifest["production_admission"] is not False or manifest["online_publication"] is not False
                or type(manifest["records"]) is not list or not 13 <= len(manifest["records"]) <= MAX_RECORDS):
            _refuse()
        directory_paths = {"", "custody", "custody/vfs-raw", "custody/vfs-raw/blobs",
                           relative, relative.rsplit("/", 1)[0]}
        directory_identities = manifest["directory_identities"]
        if type(directory_identities) is not dict or set(directory_identities) != directory_paths:
            _refuse()
        for path, original in directory_identities.items():
            if (type(original) is not dict or set(original) != {"device", "inode", "mode", "uid", "gid"}
                    or any(type(value) is not int or value < 0 for value in original.values())
                    or not stat.S_ISDIR(original["mode"])
                    or _directory_identity(root_fd, path, checkpoint) != original):
                _refuse()
        bodies, records = {}, {}
        for index, row in enumerate(manifest["records"]):
            checkpoint()
            if type(row) is not dict or set(row) != {"role", "phase", "size", "sha256", "source_identity", "blob_identity"}:
                _refuse()
            role, phase = row["role"], row["phase"]
            maximum = _limit(role, phase)
            key = role, phase
            if key in records or not _identity_ok(row["blob_identity"], row["size"]):
                _refuse()
            required = role in {"containers", "layers", "oci"} or role.startswith("ancillary-")
            if required and not _identity_ok(row["source_identity"], row["size"]) or not required and row["source_identity"] is not None:
                _refuse()
            body, _ = _read(root_fd, "custody/vfs-raw/blobs/" + row["sha256"] + ".bin",
                            row["size"], row["sha256"], maximum, checkpoint, row["blob_identity"])
            receipt = _json(row)
            _read(root_fd, f"{relative}/record-{index:02d}.json", len(receipt), _sha(receipt), MAX_RECEIPT_BYTES, checkpoint)
            bodies[key], records[key] = body, row
        expected = {("info", "selection"), ("inspect", "selection"), ("oci", "acquire")}
        expected |= {(role, phase) for role in ("containers", "layers") for phase in ("before", "after")}
        expected |= {(role, phase) for role in ("mountinfo-service", "mountinfo-client")
                     for phase in ("acquire-before", "acquire-after", "final-view")}
        for ancillary in proof["ancillary_mounts"]:
            expected |= {("ancillary-" + _ANCILLARY[ancillary["destination"]], phase) for phase in ("service", "host")}
        if set(records) != expected or type(operations) is not list:
            _refuse()
        for role, operation in (("info", "vfs-store-selection"), ("inspect", "runtime-selection")):
            matches = [item for item in operations if type(item) is dict and item.get("operation") == operation]
            if len(matches) != 1:
                _refuse()
            log = matches[0]["logs"]["stdout"]
            body = bodies[role, "selection"]
            if type(log) is not dict or log.get("size") != len(body) or log.get("sha256") != _sha(body):
                _refuse()
            # Read the fixed original control artifact, never an arbitrary path in a log record.
            parent, name = _parent(root_fd, relative.rsplit("/", 1)[0] + "/" + operation + "/stdout.log", checkpoint)
            try:
                fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent)
                try:
                    before = _file_identity(os.fstat(fd))
                    if not stat.S_ISREG(before["mode"]) or before["size"] != len(body) or os.fstat(fd).st_nlink != 1:
                        _refuse()
                    blocks, count = [], 0
                    while True:
                        checkpoint()
                        block = os.read(fd, min(65536, len(body) + 1 - count))
                        if not block:
                            break
                        blocks.append(block)
                        count += len(block)
                        if count > len(body):
                            _refuse()
                    if b"".join(blocks) != body or _file_identity(os.fstat(fd)) != before:
                        _refuse()
                    repeated = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK, dir_fd=parent)
                    try:
                        if _file_identity(os.fstat(repeated)) != before:
                            _refuse()
                    finally:
                        os.close(repeated)
                finally:
                    os.close(fd)
            finally:
                os.close(parent)
        metadata = proof["metadata"]
        info, selected = _decode(bodies["info", "selection"]), _decode(bodies["inspect", "selection"])
        if (info != {"driver": "vfs", "graph_root": proof["graph_root"], "run_root": proof["run_root"]}
                or _sha(bodies["info", "selection"]) != metadata["info_sha256"]
                or type(selected) is not dict or set(selected) != {"container_id", "image", "oci", "resolver", "hostname", "hosts"}
                or any(type(value) is not str for value in selected.values())
                or selected["hostname"] != "" or selected["hosts"] != ""
                or selected["container_id"] != binding["container_id"]
                or selected["image"].removeprefix("sha256:") != binding["image_id"]
                or selected["oci"] != str(Path(proof["graph_root"]) / "vfs-containers" / binding["container_id"] / "userdata/config.json")):
            _refuse()
        for role in ("containers", "layers"):
            before, after = records[role, "before"], records[role, "after"]
            if (bodies[role, "before"] != bodies[role, "after"] or before["sha256"] != metadata[role + "_sha256"]
                    or before["source_identity"] != after["source_identity"]
                    or before["source_identity"] != metadata[role + "_identity"]):
                _refuse()
        containers, layers = vfs._records(bodies["containers", "before"]), vfs._records(bodies["layers", "before"])
        matches = [row for row in containers if row["id"] == binding["container_id"]]
        layer = proof["layer_id"]
        if (len(matches) != 1 or matches[0].get("image") != binding["image_id"] or matches[0].get("layer") != layer
                or sum(row.get("layer") == layer for row in containers) != 1
                or sum(row["id"] == layer for row in layers) != 1):
            _refuse()
        parent = next(row for row in layers if row["id"] == layer).get("parent")
        if parent not in (None, "") and (type(parent) is not str or _ID.fullmatch(parent) is None):
            _refuse()
        oci = _decode(bodies["oci", "acquire"])
        if (records["oci", "acquire"]["sha256"] != metadata["oci_sha256"]
                or records["oci", "acquire"]["source_identity"] != metadata["oci_identity"]
                or type(oci) is not dict or type(oci.get("root")) is not dict
                or oci["root"].get("path") != proof["root"]["path"] or type(oci.get("mounts", [])) is not list):
            _refuse()
        protected = [vfs.absolute(proof["graph_root"]), vfs.absolute(proof["run_root"])]
        for row in oci.get("mounts", []):
            if type(row) is dict and row.get("destination") in {"/source", "/toolchain", "/work", "/out"}:
                protected.append(vfs.absolute(row.get("source")))
        for role in ("service", "client"):
            for phase in ("acquire-before", "acquire-after", "final-view"):
                body = bodies["mountinfo-" + role, phase]
                if _sha(body) != proof["mount_tables"][role + "_sha256"]:
                    _refuse()
                for mount in vfs.parse_mount_table(body, checkpoint):
                    if any(mount == path or path in mount.parents for path in protected):
                        _refuse()
        oci_ancillary = [row for row in oci.get("mounts", []) if type(row) is dict and row.get("destination") in _ANCILLARY]
        if len(oci_ancillary) != len(proof["ancillary_mounts"]):
            _refuse()
        for ancillary in proof["ancillary_mounts"]:
            selected_mount = [row for row in oci_ancillary if row["destination"] == ancillary["destination"]]
            if len(selected_mount) != 1 or selected_mount[0].get("type") != "bind" or selected_mount[0].get("source") != ancillary["source"]:
                _refuse()
            role = "ancillary-" + _ANCILLARY[ancillary["destination"]]
            for phase in ("service", "host"):
                row = records[role, phase]
                if row["source_identity"] != ancillary["identity"] or row["sha256"] != ancillary["sha256"] or row["size"] != ancillary["size"]:
                    _refuse()
            if bodies[role, "service"] != bodies[role, "host"]:
                _refuse()
        repeated_root = _root(workspace, checkpoint)
        try:
            for path, original in directory_identities.items():
                if _directory_identity(repeated_root, path, checkpoint) != original:
                    _refuse()
        finally:
            os.close(repeated_root)
        return oci
    finally:
        os.close(root_fd)


def verify_snapshots(workspace, pin, binding, proof, operations, checkpoint):
    """Verify original retained artifacts only; return the already verified OCI."""
    try:
        return _verify(workspace, pin, binding, proof, operations, checkpoint)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError, vfs.BuildExecutionError) as error:
        raise ValueError("podman_vfs_snapshots") from error
