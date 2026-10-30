"""Private original VFS execution owners and detached finite observations.

Held objects span the original command, not a continuous mount/process monitor.
No immutable-input, driver, runtime, namespace-drain or admission authority is
conferred. The original raw-snapshot roles and verifier remain separate.
"""

from __future__ import annotations

import os
import select
import stat
from pathlib import Path

from tools.static_python_rsi_fixture import podman_vfs_root as vfs
from tools.static_python_rsi_fixture import podman_vfs_snapshots as raw_store

BACKEND = "podman-snapshots-source-data-vfs-lifetime-v1"
SCHEMA = "lunar-podman-vfs-execution-lifetime-v1"
PHASES = ("initialized", "before-start", "original-exit", "before-readback", "after-readback")
MAX_RECORDS = 32
CLAIMS = {name: False for name in (
    "immutable_custody_verified", "driver_inputs_verified", "implicit_link_inputs_verified",
    "configured_closure_verified", "installation_accepted", "runtime_execution_performed",
    "complete_namespace_disappearance_verified", "descendant_cleanup_verified",
    "production_admission", "online_publication",
)}
_ROLES = {"source": "/source", "toolchain": "/toolchain", "work": "/work", "current_output": "/out"}


def _refuse():
    raise ValueError("podman_vfs_lifetime")


def _limit(role, phase):
    if phase not in PHASES:
        _refuse()
    if role in {"mountinfo-service", "mountinfo-client"}:
        return 1024**2
    if role == "worker-mountinfo" and phase in PHASES[:2]:
        return 1024**2
    if role == "worker-stat" and phase in PHASES[:2]:
        return 65536
    if role == "state" and phase in {"initialized", "original-exit"}:
        return 32768
    if role in {"wait", "attach"} and phase == "original-exit":
        return 32768
    _refuse()


def _keys():
    return set(_order())


def _order():
    rows = [("state", "initialized")]
    for phase in PHASES:
        if phase in PHASES[:2]:
            rows.extend((role, phase) for role in ("worker-stat", "worker-mountinfo"))
        if phase == "original-exit":
            rows.extend((role, phase) for role in ("attach", "wait", "state"))
        rows.extend((role, phase) for role in ("mountinfo-service", "mountinfo-client"))
    return tuple(rows)


def _initialized(raw):
    if type(raw) is not bytes or len(raw) > 32768:
        _refuse()
    value = vfs.decode(raw)
    if (type(value) is not dict or value.get("Status") != "initialized"
            or value.get("Running") is not False or type(value.get("Pid")) is not int
            or not 0 < value["Pid"] < 2**31 or value.get("OOMKilled") is not False
            or value.get("Error") not in (None, "")):
        _refuse()
    return value["Pid"]


def _terminal(raw):
    from tools.static_python_rsi_fixture.podman_custody import _successful_terminal_state

    if type(raw) is not bytes or len(raw) > 32768:
        _refuse()
    value = vfs.decode(raw)
    if not _successful_terminal_state(value):
        _refuse()


def _ticks(raw, pid):
    if type(raw) is not bytes or len(raw) > 65536:
        _refuse()
    try:
        prefix, rest = raw.rsplit(b")", 1)
        original = int(prefix.split(b"(", 1)[0])
        ticks = int(rest.split()[19])
    except (ValueError, IndexError):
        _refuse()
    if original != pid or ticks <= 0:
        _refuse()
    return ticks


def _namespace(fd):
    info = os.fstat(fd)
    return {"device": info.st_dev, "inode": info.st_ino}


def _exited(fd):
    poller = select.poll()
    poller.register(fd, select.POLLIN)
    events = poller.poll(0)
    if not events:
        return False
    if (len(events) != 1 or events[0][0] != fd
            or not events[0][1] & select.POLLIN
            or events[0][1] & ~(select.POLLIN | select.POLLHUP)):
        _refuse()
    return True


def _proc_read(pid, name, maximum, checkpoint):
    checkpoint()
    fd = os.open(f"/proc/{pid}/{name}", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        blocks, count = [], 0
        while True:
            checkpoint()
            block = os.read(fd, min(65536, maximum + 1 - count))
            checkpoint()
            if not block:
                return b"".join(blocks)
            count += len(block)
            if count > maximum:
                _refuse()
            blocks.append(block)
    finally:
        os.close(fd)


class _LifetimeCapture:
    """Separate roles using the original store's owned CAS and write ledger."""

    def __init__(self, store, stage, index):
        self.store, self.stage, self.index = store, stage, index
        self.relative = raw_store._command(stage, index).replace("/vfs-raw", "/vfs-lifetime")
        self.records, self.keys, self.phases, self.completed = [], set(), [], False
        root = store._open_checked()
        try:
            store.directories[self.relative] = raw_store._private_dir(
                root, self.relative, store.checkpoint, create=True)
        finally:
            os.close(root)

    def record(self, role, phase, raw):
        maximum = _limit(role, phase)
        if (self.completed or type(raw) is not bytes or len(raw) > maximum
                or (role, phase) in self.keys or len(self.records) >= len(_order())
                or _order()[len(self.records)] != (role, phase)):
            _refuse()
        digest = raw_store._sha(raw)
        path = "custody/vfs-raw/blobs/" + digest + ".bin"
        if digest not in self.store.blobs:
            self.store.blobs[digest] = self.store._write(path, raw, maximum)
        else:
            root = self.store._open_checked()
            try:
                raw_store._read(root, path, len(raw), digest, maximum, self.store.checkpoint,
                                self.store.blobs[digest])
            finally:
                os.close(root)
        row = {"role": role, "phase": phase, "size": len(raw), "sha256": digest,
               "blob_identity": dict(self.store.blobs[digest])}
        self.store._write(f"{self.relative}/record-{len(self.records):02d}.json",
                          raw_store._json(row), raw_store.MAX_RECEIPT_BYTES)
        self.records.append(row)
        self.keys.add((role, phase))

    def complete(self, binding):
        if type(binding) is not dict or set(binding) != raw_store._BINDING | {"vfs_snapshots"}:
            _refuse()
        raw_store._binding({key: binding[key] for key in raw_store._BINDING})
        if (self.completed or self.keys != _keys() or len(self.phases) != len(PHASES)
                or binding["stage"] != self.stage or binding["index"] != self.index):
            _refuse()
        paths = {"", "custody", "custody/vfs-raw", "custody/vfs-raw/blobs",
                 self.relative, self.relative.rsplit("/", 1)[0]}
        payload = {"schema": SCHEMA, "binding": binding, "phases": self.phases,
                   "records": self.records, "complete": True, "claims": CLAIMS,
                   "directory_identities": {key: dict(self.store.directories[key]) for key in sorted(paths)}}
        raw = raw_store._json(payload)
        self.store._write(self.relative + "/manifest.json", raw, raw_store.MAX_MANIFEST_BYTES)
        self.completed = True
        return {"path": self.relative + "/manifest.json", "size": len(raw), "sha256": raw_store._sha(raw)}


class _VfsExecutionLifetime:
    """One original service and initialized worker, owned only by custody.run."""

    def __init__(self, service, state_raw, proof, view, capture, checkpoint):
        self.service = service if type(service) is vfs.ServiceRoot else None
        self.capture, self.checkpoint = capture, checkpoint
        self.fds, self.expected_fds, self.phase, self.closed = [], {}, 0, False
        try:
            self._proof_raw, self._view_raw = raw_store._json(proof), raw_store._json(view)
            self.proof, self.view = vfs.decode(self._proof_raw), vfs.decode(self._view_raw)
            if self.service is None or service.proof != self.proof["service"]:
                _refuse()
            service.verify()
            self.service_pidns = self._keep(os.open(f"/proc/{service.pid}/ns/pid", os.O_RDONLY | os.O_CLOEXEC), namespace=True)
            self.client_pidns = self._keep(os.open("/proc/self/ns/pid", os.O_RDONLY | os.O_CLOEXEC), namespace=True)
            if _namespace(self.service_pidns) != _namespace(self.client_pidns):
                _refuse()
            self.pid = _initialized(state_raw)
            self.pidfd = self._keep(os.pidfd_open(self.pid, 0), namespace=True)
            self.root = self._keep(os.open(f"/proc/{self.pid}/root", vfs._DIRECTORY & ~os.O_NOFOLLOW))
            self.mountns = self._keep(os.open(f"/proc/{self.pid}/ns/mnt", os.O_RDONLY | os.O_CLOEXEC), namespace=True)
            self.pidns = self._keep(os.open(f"/proc/{self.pid}/ns/pid", os.O_RDONLY | os.O_CLOEXEC), namespace=True)
            if (_namespace(self.pidns) == _namespace(self.client_pidns)
                    or _namespace(self.mountns) == service.proof["mount_namespace"]
                    or vfs.identity(os.fstat(self.root)) != proof["root"]["identity"]):
                _refuse()
            self.roles = {row["role"]: row for row in self.view["mounts"]}
            if set(self.roles) != set(_ROLES):
                _refuse()
            self.role_fds = {role: self._keep(vfs._open_at(
                self.root, Path(destination), directory=True, checkpoint=checkpoint))
                for role, destination in _ROLES.items()}
            self.ticks = _ticks(_proc_read(self.pid, "stat", 65536, checkpoint), self.pid)
            self.owner = {"service": self.proof["service"], "service_pid_namespace": _namespace(self.service_pidns),
                          "client_pid_namespace": _namespace(self.client_pidns), "worker_pid": self.pid,
                          "worker_start_ticks": self.ticks, "root": vfs.identity(os.fstat(self.root)),
                          "mount_namespace": _namespace(self.mountns), "pid_namespace": _namespace(self.pidns),
                          "roles": {role: vfs.identity(os.fstat(fd)) for role, fd in self.role_fds.items()}}
            self._owner_raw = raw_store._json(self.owner)
            capture.record("state", "initialized", state_raw)
            self._phase("initialized", {})
        except BaseException as error:
            try:
                self.close()
            except BaseException:  # noqa: BLE001 - preserve the acquisition failure and unknown close
                error.add_note("podman_vfs_lifetime_close_unknown")
            raise

    def _keep(self, fd, *, namespace=False):
        self.fds.append(fd)
        self.expected_fds[fd] = (namespace, _namespace(fd) if namespace else vfs.identity(os.fstat(fd)))
        return fd

    def _check(self, *, live):
        if self.closed:
            _refuse()
        self.checkpoint()
        if (raw_store._json(self.proof) != self._proof_raw
                or raw_store._json(self.view) != self._view_raw
                or raw_store._json(self.owner) != self._owner_raw
                or self.service.proof != self.proof["service"]):
            _refuse()
        self.service.verify()
        for fd, (namespace, original) in self.expected_fds.items():
            if (_namespace(fd) if namespace else vfs.identity(os.fstat(fd))) != original:
                _refuse()
        if _exited(self.pidfd) is live:
            _refuse()
        for pid, fd in ((self.service.pid, self.service_pidns), ("self", self.client_pidns)):
            current = os.open(f"/proc/{pid}/ns/pid", os.O_RDONLY | os.O_CLOEXEC)
            try:
                if _namespace(current) != _namespace(fd):
                    _refuse()
            finally:
                os.close(current)
        for role, row in self.roles.items():
            expected = self.owner["roles"][role]
            if (row["destination"] != _ROLES[role] or row["identity"] != expected
                    or vfs.directory_at(self.service.root_fd, Path(row["source"]), self.checkpoint) != expected
                    or vfs.directory_at(self.root, Path(_ROLES[role]), self.checkpoint) != expected):
                _refuse()
            client = os.open("/", vfs._DIRECTORY)
            try:
                if vfs.directory_at(client, Path(row["source"]), self.checkpoint) != expected:
                    _refuse()
            finally:
                os.close(client)
        if vfs.directory_at(self.service.root_fd, Path(self.proof["root"]["path"]), self.checkpoint) != self.owner["root"]:
            _refuse()
        if live:
            for path, descriptor, namespace in (("root", self.root, False), ("ns/mnt", self.mountns, True),
                                                 ("ns/pid", self.pidns, True)):
                current = os.open(f"/proc/{self.pid}/{path}", os.O_RDONLY | os.O_CLOEXEC)
                try:
                    original = _namespace(descriptor) if namespace else vfs.identity(os.fstat(descriptor))
                    if (_namespace(current) if namespace else vfs.identity(os.fstat(current))) != original:
                        _refuse()
                finally:
                    os.close(current)

    def _phase(self, name, links):
        if self.phase >= len(PHASES) or PHASES[self.phase] != name:
            _refuse()
        live = self.phase < 2
        self._check(live=live)
        if live:
            body = _proc_read(self.pid, "stat", 65536, self.checkpoint)
            if _ticks(body, self.pid) != self.ticks:
                _refuse()
            self.capture.record("worker-stat", name, body)
            self.capture.record("worker-mountinfo", name, _proc_read(self.pid, "mountinfo", 1024**2, self.checkpoint))
        protected = [Path(self.proof["graph_root"]), Path(self.proof["run_root"]),
                     Path(self.proof["root"]["path"]), *(Path(row["source"]) for row in self.roles.values())]
        mounts = vfs.check_mount_tables(self.service, protected, self.checkpoint, snapshots=self.capture, phase=name)
        self._check(live=live)
        self.capture.phases.append({"ordinal": self.phase, "phase": name, "owner": vfs.decode(self._owner_raw),
                                    "pidfd_exited": not live, "mount_tables": mounts, "links": links})
        self.phase += 1

    def before_start(self):
        self._phase("before-start", {})

    def observe_original_exit(self, attach, wait_raw, state_raw):
        if (type(attach) is not dict or attach.get("status") != "complete"
                or type(attach.get("returncode")) is not int or attach["returncode"] != 0
                or attach.get("direct_child_reaped") is not True
                or type(wait_raw) is not bytes or wait_raw.strip() != b"0"):
            _refuse()
        _terminal(state_raw)
        self.capture.record("attach", "original-exit", raw_store._json(attach))
        self.capture.record("wait", "original-exit", wait_raw)
        self.capture.record("state", "original-exit", state_raw)
        self._phase("original-exit", {"attach_sha256": raw_store._sha(raw_store._json(attach)),
                                      "wait_sha256": raw_store._sha(wait_raw), "state_sha256": raw_store._sha(state_raw)})

    def before_readback(self):
        self._phase("before-readback", {})

    def finish_readback(self, outputs, binding):
        self._phase("after-readback", {"readback_outputs_sha256": raw_store._sha(raw_store._json(outputs))})
        return self.capture.complete(binding)

    def close(self):
        if self.closed:
            return
        self.closed = True
        failure = None
        for fd in reversed(self.fds):
            try:
                os.close(fd)
            except OSError as error:
                failure = error
        self.fds.clear()
        if self.service is not None:
            try:
                _close_service(self.service)
            except OSError as error:
                failure = error
        if failure is not None:
            _refuse()


def _close_service(service):
    """Release every original descriptor even when an earlier close fails."""
    descriptors = list(service.descriptors)
    service.descriptors.clear()
    failure = None
    for descriptor in reversed(descriptors):
        try:
            os.close(descriptor)
        except OSError as error:
            failure = error
    if failure is not None:
        raise failure


def _identity(value, *, namespace=False):
    fields = {"device", "inode"} if namespace else {"device", "inode", "mode", "uid", "gid"}
    if (type(value) is not dict or set(value) != fields
            or any(type(item) is not int or not 0 <= item < 2**64 for item in value.values())
            or not namespace and not stat.S_ISDIR(value["mode"])):
        _refuse()


def _read_log(workspace, relative, pin, maximum, checkpoint):
    from tools.static_python_rsi_fixture.execution_backend import _open_beneath

    if (type(pin) is not dict or set(pin) != {"size", "sha256"}
            or type(pin["size"]) is not int or not 0 <= pin["size"] <= maximum
            or type(pin["sha256"]) is not str or raw_store._ID.fullmatch(pin["sha256"]) is None):
        _refuse()
    fd = _open_beneath(Path(workspace), relative)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_size != pin["size"]:
            _refuse()
        blocks, count = [], 0
        while True:
            checkpoint()
            block = os.read(fd, min(65536, pin["size"] + 1 - count))
            if not block:
                break
            count += len(block)
            if count > pin["size"]:
                _refuse()
            blocks.append(block)
        raw = b"".join(blocks)
        original = raw_store._file_identity(before)
        repeated = _open_beneath(Path(workspace), relative)
        try:
            if (count != pin["size"] or raw_store._sha(raw) != pin["sha256"]
                    or raw_store._file_identity(os.fstat(fd)) != original
                    or raw_store._file_identity(os.fstat(repeated)) != original):
                _refuse()
        finally:
            os.close(repeated)
        return raw
    finally:
        os.close(fd)


def _verify(workspace, pin, binding, proof, view, vfs_pin, operations, outputs, checkpoint):
    raw_store._binding(binding)
    if type(proof) is not dict or raw_store._sha(raw_store._json(proof)) != binding["root_acquisition_sha256"]:
        _refuse()
    expected_binding = {**binding, "vfs_snapshots": vfs_pin}
    relative = raw_store._command(binding["stage"], binding["index"]).replace("/vfs-raw", "/vfs-lifetime")
    if (type(pin) is not dict or set(pin) != {"path", "size", "sha256"}
            or pin["path"] != relative + "/manifest.json"):
        _refuse()
    root = raw_store._root(workspace, checkpoint)
    try:
        raw, _ = raw_store._read(root, pin["path"], pin["size"], pin["sha256"], raw_store.MAX_MANIFEST_BYTES, checkpoint)
        payload = raw_store._decode(raw)
        if (raw_store._json(payload) != raw
                or type(payload) is not dict or set(payload) != {"schema", "binding", "phases", "records", "complete", "claims", "directory_identities"}
                or payload["schema"] != SCHEMA or payload["binding"] != expected_binding
                or payload["complete"] is not True or type(payload["claims"]) is not dict
                or set(payload["claims"]) != set(CLAIMS) or any(value is not False for value in payload["claims"].values())
                or type(payload["phases"]) is not list or len(payload["phases"]) != 5
                or type(payload["records"]) is not list or len(payload["records"]) != len(_keys())):
            _refuse()
        paths = {"", "custody", "custody/vfs-raw", "custody/vfs-raw/blobs", relative, relative.rsplit("/", 1)[0]}
        directories = payload["directory_identities"]
        if type(directories) is not dict or set(directories) != paths:
            _refuse()
        for path, original in directories.items():
            _identity(original)
            if raw_store._directory_identity(root, path, checkpoint) != original:
                _refuse()
            if path and path != relative.rsplit("/", 1)[0]:
                raw_store._private_dir(root, path, checkpoint, create=False)
        bodies = {}
        for index, row in enumerate(payload["records"]):
            if type(row) is not dict or set(row) != {"role", "phase", "size", "sha256", "blob_identity"}:
                _refuse()
            role, phase = row["role"], row["phase"]
            maximum = _limit(role, phase)
            if ((role, phase) != _order()[index] or (role, phase) in bodies
                    or not raw_store._identity_ok(row["blob_identity"], row["size"])):
                _refuse()
            bodies[role, phase] = raw_store._read(root, "custody/vfs-raw/blobs/" + row["sha256"] + ".bin",
                row["size"], row["sha256"], maximum, checkpoint, row["blob_identity"])[0]
            receipt = raw_store._json(row)
            raw_store._read(root, f"{relative}/record-{index:02d}.json", len(receipt), raw_store._sha(receipt),
                            raw_store.MAX_RECEIPT_BYTES, checkpoint)
        if set(bodies) != _keys():
            _refuse()
        phases = payload["phases"]
        owner = phases[0].get("owner") if type(phases[0]) is dict else None
        fields = {"service", "service_pid_namespace", "client_pid_namespace", "worker_pid", "worker_start_ticks",
                  "root", "mount_namespace", "pid_namespace", "roles"}
        if (type(owner) is not dict or set(owner) != fields or owner["service"] != proof["service"]
                or type(owner["worker_pid"]) is not int or not 0 < owner["worker_pid"] < 2**31
                or type(owner["worker_start_ticks"]) is not int or owner["worker_start_ticks"] <= 0
                or _initialized(bodies["state", "initialized"]) != owner["worker_pid"]
                or type(owner["roles"]) is not dict or set(owner["roles"]) != set(_ROLES)):
            _refuse()
        for key in ("service_pid_namespace", "client_pid_namespace", "pid_namespace", "mount_namespace"):
            _identity(owner[key], namespace=True)
        _identity(owner["root"])
        roles = {row["role"]: row for row in view["mounts"]}
        if (owner["service_pid_namespace"] != owner["client_pid_namespace"]
                or owner["pid_namespace"] == owner["client_pid_namespace"]
                or owner["mount_namespace"] == proof["service"]["mount_namespace"]
                or owner["root"] != proof["root"]["identity"] or set(roles) != set(_ROLES)):
            _refuse()
        for role, original in owner["roles"].items():
            _identity(original)
            if roles[role]["identity"] != original or roles[role]["destination"] != _ROLES[role]:
                _refuse()
        protected = [Path(proof["graph_root"]), Path(proof["run_root"]), Path(proof["root"]["path"]),
                     *(Path(row["source"]) for row in roles.values())]
        for index, (phase, name) in enumerate(zip(phases, PHASES, strict=True)):
            if (type(phase) is not dict or set(phase) != {"ordinal", "phase", "owner", "pidfd_exited", "mount_tables", "links"}
                    or type(phase["ordinal"]) is not int or phase["ordinal"] != index
                    or phase["phase"] != name or phase["owner"] != owner
                    or phase["pidfd_exited"] is not (index >= 2)):
                _refuse()
            tables = {}
            for role in ("service", "client"):
                body = bodies["mountinfo-" + role, name]
                for mount in vfs.parse_mount_table(body, checkpoint):
                    if any(mount == path or path in mount.parents for path in protected):
                        _refuse()
                tables[role + "_sha256"] = raw_store._sha(body)
            if phase["mount_tables"] != tables:
                _refuse()
            if index < 2:
                if _ticks(bodies["worker-stat", name], owner["worker_pid"]) != owner["worker_start_ticks"]:
                    _refuse()
                vfs.parse_mount_table(bodies["worker-mountinfo", name], checkpoint)
            links = ({"attach_sha256": raw_store._sha(bodies["attach", name]),
                      "wait_sha256": raw_store._sha(bodies["wait", name]),
                      "state_sha256": raw_store._sha(bodies["state", name])} if index == 2 else
                     {"readback_outputs_sha256": raw_store._sha(raw_store._json(outputs))} if index == 4 else {})
            if phase["links"] != links:
                _refuse()
        _terminal(bodies["state", "original-exit"])
        if bodies["wait", "original-exit"].strip() != b"0":
            _refuse()
        names = ("init", "lifetime-initial-state", "start-attach", "wait", "state")
        positions = []
        selected = {}
        for name in names:
            matching = [(index, row) for index, row in enumerate(operations) if row.get("operation") == name]
            if len(matching) != 1:
                _refuse()
            position, operation = matching[0]
            positions.append(position)
            selected[name] = operation.get("evidence") if name == "start-attach" else operation
            evidence = selected[name]
            if (type(evidence) is not dict or evidence.get("status") != "complete"
                    or type(evidence.get("returncode")) is not int or evidence["returncode"] != 0
                    or evidence.get("direct_child_reaped") is not True):
                _refuse()
        if positions != sorted(positions):
            _refuse()
        command_root = f"custody/{binding['stage']}-{binding['index']}"
        for name, key in (("lifetime-initial-state", ("state", "initialized")),
                          ("wait", ("wait", "original-exit")), ("state", ("state", "original-exit"))):
            if _read_log(workspace, f"{command_root}/{name}/stdout.log", selected[name]["logs"]["stdout"],
                         _limit(*key), checkpoint) != bodies[key]:
                _refuse()
        attach = selected["start-attach"]
        if raw_store._json(attach) != bodies["attach", "original-exit"]:
            _refuse()
        from tools.static_python_rsi_fixture.execution_backend import MAX_LOG_BYTES

        for name in ("stdout", "stderr"):
            _read_log(workspace, f"logs/{binding['stage']}/{binding['index']}/{name}.log", attach["logs"][name],
                      MAX_LOG_BYTES, checkpoint)
        for path, original in directories.items():
            if raw_store._directory_identity(root, path, checkpoint) != original:
                _refuse()
        repeated_root = raw_store._root(workspace, checkpoint)
        try:
            for path, original in directories.items():
                if raw_store._directory_identity(repeated_root, path, checkpoint) != original:
                    _refuse()
        finally:
            os.close(repeated_root)
    finally:
        os.close(root)


def verify_lifetime(workspace, pin, binding, proof, view, vfs_pin, operations, outputs, checkpoint):
    """Read original files only; never query a service, /proc or execution owner."""
    from tools.static_python_rsi_fixture.execution_backend import BuildExecutionError

    failed = False
    try:
        _verify(workspace, pin, binding, proof, view, vfs_pin, operations, outputs, checkpoint)
    except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError, RecursionError,
            BuildExecutionError):
        failed = True
    if failed:
        _refuse()
