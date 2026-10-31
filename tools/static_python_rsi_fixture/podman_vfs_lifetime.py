"""Private original VFS execution owners and detached finite observations.

Held objects span the original command, not a continuous mount/process monitor.
No immutable-input, driver, runtime, namespace-drain or admission authority is
conferred. The original raw-snapshot roles and verifier remain separate.
"""

from __future__ import annotations

import hashlib
import os
import select
import stat
from pathlib import Path

from lunar_evolution.static_python_elf import (
    StaticPythonELFError,
    inspect_static_python_relocatable_elf,
)
from lunar_evolution.static_python_link_objects import (
    MAX_LINK_ARCHIVE_BYTES,
    StaticPythonLinkObjectError,
    inspect_static_python_link_archive,
)
from tools.static_python_rsi_fixture import podman_vfs_root as vfs
from tools.static_python_rsi_fixture import podman_vfs_snapshots as raw_store

BACKEND = "podman-snapshots-source-data-vfs-lifetime-v1"
SCHEMA = "lunar-podman-vfs-execution-lifetime-v1"
WORKER_INPUT_SCHEMA = "lunar-podman-vfs-execution-lifetime-v2"
WORKER_INPUT_PROFILE = "lunar-podman-worker-input-view-v1"
PHASES = ("initialized", "before-start", "original-exit", "before-readback", "after-readback")
MAX_RECORDS = 32
CLAIMS = {name: False for name in (
    "immutable_custody_verified", "driver_inputs_verified", "implicit_link_inputs_verified",
    "configured_closure_verified", "installation_accepted", "runtime_execution_performed",
    "complete_namespace_disappearance_verified", "descendant_cleanup_verified",
    "production_admission", "online_publication",
)}
_ROLES = {"source": "/source", "toolchain": "/toolchain", "work": "/work", "current_output": "/out"}


def _inventory_tree(records, checkpoint=lambda: None, *, maximum=None):
    """Derive the complete directory vocabulary from existing finite records."""
    from tools.static_python_rsi_fixture.execution_backend import (
        MAX_INPUT_FILE_BYTES,
        MAX_V3_INPUT_RECORDS,
        _path,
    )

    checkpoint()
    if maximum is None:
        maximum = MAX_INPUT_FILE_BYTES
    if type(records) is not list or len(records) > MAX_V3_INPUT_RECORDS:
        _refuse()
    tree, directories, total = {}, 1, 0
    for record in records:
        checkpoint()
        if (type(record) is not dict or set(record) != {"path", "size", "sha256", "executable"}
                or type(record["size"]) is not int or not 0 <= record["size"] <= maximum
                or type(record["executable"]) is not bool or type(record["sha256"]) is not str
                or raw_store._ID.fullmatch(record["sha256"]) is None):
            _refuse()
        parts = _path(record["path"]).split("/")
        node = tree
        for part in parts[:-1]:
            checkpoint()
            if part not in node:
                node[part] = {}
                directories += 1
            node = node[part]
            if type(node) is not dict:
                _refuse()
        if parts[-1] in node:
            _refuse()
        node[parts[-1]] = (record,)
        total += record["size"]
    checkpoint()
    inventory_sha256 = raw_store._sha(raw_store._json(records))
    checkpoint()
    return tree, {"inventory_sha256": inventory_sha256,
                  "file_count": len(records), "directory_count": directories,
                  "total_bytes": total}


def _stat_pin(info):
    return tuple(getattr(info, field) for field in (
        "st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_nlink", "st_size", "st_mtime_ns", "st_ctime_ns"))


def _worker_link_inputs(argv, inventories, checkpoint=lambda: None):
    """Select only this original command's explicit prior objects and archives.

    Selection cannot discover a pin or grant a same-command output an input.
    The complete finite command graph remains the executor's earlier gate.
    """
    from tools.static_python_rsi_fixture.link_dependency_capture import _link

    checkpoint()
    if (type(argv) is not list or not 0 < len(argv) <= 512
            or any(type(arg) is not str or not 0 < len(arg) <= 4096 or "\x00" in arg for arg in argv)
            or type(inventories) is not dict or set(inventories) != {"source", "toolchain", "work"}):
        _refuse()
    if argv[:2] == ["@toolchain/zig", "ar"]:
        if (len(argv) < 5 or argv[2] != "rcsD"
                or not argv[3].startswith("@work/libraries/") or not argv[3].endswith(".a")
                or any(not ref.startswith("@work/") or not ref.endswith(".o") for ref in argv[4:])):
            _refuse()
        references = argv[4:]
    else:
        try:
            link = _link({"argv": argv})
        except (ValueError, KeyError, IndexError, TypeError):
            _refuse()
        references = [] if link is None else link[1]
    if len(references) != len(set(references)):
        _refuse()
    selected = {role: [] for role in ("source", "toolchain", "work")}
    if not references:
        # The owner separately validates and walks every role inventory. A
        # compile/freezer command has no selected link bodies to index again.
        checkpoint()
        return selected
    rows = {}
    for role, records in inventories.items():
        _inventory_tree(records, checkpoint)
        rows[role] = {}
        for row in records:
            checkpoint()
            rows[role][row["path"]] = row
    for reference in references:
        checkpoint()
        if not reference.startswith(("@toolchain/", "@work/")) or not reference.endswith((".o", ".a")):
            _refuse()
        role, path = reference[1:].split("/", 1)
        record = rows[role].get(path)
        if (record is None or record["executable"] is not False
                or not 0 < record["size"] <= MAX_LINK_ARCHIVE_BYTES):
            _refuse()
        selected[role].append(path)
    return {role: sorted(paths) for role, paths in selected.items()}


def _observe_worker_inventory(role_fd, records, checkpoint, *, link_inputs=None, maximum=None):
    """One exact member/hash walk through a borrowed original worker role FD.

    Finite equality is not writer exclusion. No descriptor number or caller
    summary is accepted as persistent authority, and this function owns only
    its nested opened descriptors.
    """
    tree, summary = _inventory_tree(records, checkpoint, maximum=maximum)
    selected = set()
    if link_inputs is not None:
        if (type(link_inputs) is not list or any(type(path) is not str for path in link_inputs)
                or len(link_inputs) != len(set(link_inputs))):
            _refuse()
        rows = {record["path"]: record for record in records}
        for path in link_inputs:
            checkpoint()
            record = rows.get(path)
            if (record is None or not path.endswith((".o", ".a"))
                    or record["executable"] is not False
                    or not 0 < record["size"] <= MAX_LINK_ARCHIVE_BYTES):
                _refuse()
            selected.add(path)

    def walk(descriptor, expected):
        checkpoint()
        before = os.fstat(descriptor)
        if not stat.S_ISDIR(before.st_mode):
            _refuse()
        names = set()
        with os.scandir(descriptor) as entries:
            for entry in entries:
                checkpoint()
                if entry.name in names or entry.name not in expected:
                    _refuse()
                names.add(entry.name)
                if len(names) > len(expected):
                    _refuse()
        if names != set(expected):
            _refuse()
        for name in sorted(expected):
            checkpoint()
            node = expected[name]
            directory = type(node) is dict
            record = None if directory else node[0]
            flags = vfs._DIRECTORY if directory else (
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
            named = os.stat(name, dir_fd=descriptor, follow_symlinks=False)
            if (not (stat.S_ISDIR(named.st_mode) if directory else stat.S_ISREG(named.st_mode))
                    or not directory and named.st_nlink != 1):
                _refuse()
            child = os.open(name, flags, dir_fd=descriptor)
            try:
                original = os.fstat(child)
                if _stat_pin(original) != _stat_pin(named) or not directory and original.st_nlink != 1:
                    _refuse()
                if directory:
                    walk(child, node)
                else:
                    if (not stat.S_ISREG(original.st_mode) or original.st_size != record["size"]
                            or bool(original.st_mode & 0o111) is not record["executable"]):
                        _refuse()
                    digest, count = hashlib.sha256(), 0
                    retained = [] if record["path"] in selected else None
                    while True:
                        checkpoint()
                        block = os.read(child, min(65536, record["size"] + 1 - count))
                        checkpoint()
                        if not block:
                            break
                        count += len(block)
                        if count > record["size"]:
                            _refuse()
                        digest.update(block)
                        if retained is not None:
                            retained.append(block)
                    if count != record["size"] or digest.hexdigest() != record["sha256"]:
                        _refuse()
                    if retained is not None:
                        if _stat_pin(os.fstat(child)) != _stat_pin(original):
                            _refuse()
                        image = b"".join(retained)
                        retained.clear()
                        try:
                            if record["path"].endswith(".a"):
                                inspect_static_python_link_archive(image, checkpoint=checkpoint)
                            else:
                                inspect_static_python_relocatable_elf(image, checkpoint=checkpoint)
                        except (StaticPythonELFError, StaticPythonLinkObjectError):
                            _refuse()
                        finally:
                            del image
                if _stat_pin(os.fstat(child)) != _stat_pin(original):
                    _refuse()
                repeated = os.open(name, flags, dir_fd=descriptor)
                try:
                    if _stat_pin(os.fstat(repeated)) != _stat_pin(original):
                        _refuse()
                finally:
                    os.close(repeated)
            finally:
                os.close(child)
        if _stat_pin(os.fstat(descriptor)) != _stat_pin(before):
            _refuse()

    walk(role_fd, tree)
    return summary


def _worker_input_summary(owner, inventories, checkpoint=lambda: None):
    from tools.static_python_rsi_fixture.execution_backend import (
        MAX_INPUT_FILE_BYTES,
        MAX_OUTPUT_BYTES,
    )

    checkpoint()
    if type(inventories) is not dict or set(inventories) != {"source", "toolchain", "work"}:
        _refuse()
    roles = {}
    for role in ("source", "toolchain", "work"):
        roles[role] = {"root_identity": owner["roles"][role],
                       **_inventory_tree(inventories[role], checkpoint,
                           maximum=MAX_OUTPUT_BYTES if role == "work" else MAX_INPUT_FILE_BYTES)[1]}
    checkpoint()
    return {"schema": WORKER_INPUT_PROFILE, "phase": "before-start",
            "owner_sha256": raw_store._sha(raw_store._json(owner)), "roles": roles,
            "claims": dict(CLAIMS)}


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

    def __init__(self, store, stage, index, *, worker_input_view=False):
        if type(worker_input_view) is not bool:
            _refuse()
        self.store, self.stage, self.index = store, stage, index
        self.worker_input_view, self.input_view = worker_input_view, None
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
        if self.worker_input_view and self.input_view is None:
            _refuse()
        payload = {"schema": WORKER_INPUT_SCHEMA if self.worker_input_view else SCHEMA,
                   "binding": binding, "phases": self.phases,
                   "records": self.records, "complete": True, "claims": CLAIMS,
                   "directory_identities": {key: dict(self.store.directories[key]) for key in sorted(paths)}}
        if self.worker_input_view:
            payload["worker_input_view"] = self.input_view
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
            if self.capture.worker_input_view:
                from tools.static_python_rsi_fixture.podman_worker_init import (
                    verify_worker_namespace_init,
                )

                verify_worker_namespace_init(
                    _proc_read(self.pid, "status", 65536, self.checkpoint), self.pid,
                    checkpoint=self.checkpoint,
                )
            self.capture.record("worker-stat", name, body)
            self.capture.record("worker-mountinfo", name, _proc_read(self.pid, "mountinfo", 1024**2, self.checkpoint))
        protected = [Path(self.proof["graph_root"]), Path(self.proof["run_root"]),
                     Path(self.proof["root"]["path"]), *(Path(row["source"]) for row in self.roles.values())]
        mounts = vfs.check_mount_tables(self.service, protected, self.checkpoint, snapshots=self.capture, phase=name)
        self._check(live=live)
        self.capture.phases.append({"ordinal": self.phase, "phase": name, "owner": vfs.decode(self._owner_raw),
                                    "pidfd_exited": not live, "mount_tables": mounts, "links": links})
        self.phase += 1

    def _bind_worker_inputs(self, inputs, prior, *, argv=None):
        """Bind only the original run's inventories, before its start boundary."""
        if (self.closed or self.phase != 1 or not self.capture.worker_input_view
                or hasattr(self, "_worker_inputs") or type(inputs) is not dict
                or set(inputs) != {"source", "toolchain"}):
            _refuse()
        self._check(live=True)
        inventories = {**inputs, "work": prior}
        _worker_input_summary(self.owner, inventories, self.checkpoint)
        if argv is not None:
            _worker_link_inputs(argv, inventories, self.checkpoint)
            self._worker_argv = raw_store._json(argv)
        self.checkpoint()
        self._worker_inputs = raw_store._json(inventories)
        self.checkpoint()

    def _bind_worker_filesystem(self, outputs, *, runtime_metadata, kernel_mounts):
        """Freeze the original checked policy and output graph, without a wire claim."""
        if (self.closed or self.phase != 1 or not self.capture.worker_input_view
                or not hasattr(self, "_worker_inputs") or hasattr(self, "_worker_filesystem")):
            _refuse()
        self._check(live=True)
        self._worker_filesystem = raw_store._json({
            "outputs": outputs, "runtime_metadata": runtime_metadata, "kernel_mounts": kernel_mounts,
        })
        self.checkpoint()

    def before_start(self):
        links = {}
        if self.capture.worker_input_view:
            if self.closed or self.phase != 1 or not hasattr(self, "_worker_inputs"):
                _refuse()
            self._check(live=True)
            if hasattr(self, "_worker_argv"):
                if not hasattr(self, "_worker_filesystem"):
                    _refuse()
                from tools.static_python_rsi_fixture.podman_worker_filesystem import (
                    verify_worker_filesystem,
                )

                verify_worker_filesystem(self.root, checkpoint=self.checkpoint,
                                         **raw_store._decode(self._worker_filesystem))
            inventories = raw_store._decode(self._worker_inputs)
            summary = _worker_input_summary(self.owner, inventories, self.checkpoint)
            link_inputs = (_worker_link_inputs(raw_store._decode(self._worker_argv), inventories, self.checkpoint)
                           if hasattr(self, "_worker_argv") else None)
            for role in ("source", "toolchain", "work"):
                options = {"link_inputs": link_inputs[role]} if link_inputs is not None else {}
                observed = _observe_worker_inventory(
                    self.role_fds[role], inventories[role], self.checkpoint, **options)
                if observed != {key: value for key, value in summary["roles"][role].items()
                                if key != "root_identity"}:
                    _refuse()
            self._check(live=True)
            self.capture.input_view = summary
            links["worker_input_view_sha256"] = raw_store._sha(raw_store._json(summary))
        self._phase("before-start", links)

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
        output_raw = raw_store._json(outputs)
        if self.capture.worker_input_view:
            from tools.static_python_rsi_fixture.podman_worker_outputs import verify_worker_outputs

            if self.closed or self.phase != 4:
                _refuse()
            self._check(live=False)
            original_outputs = raw_store._decode(output_raw)
            summary = verify_worker_outputs(self.role_fds["current_output"], original_outputs, self.checkpoint)
            if (summary["inventory_sha256"] != raw_store._sha(output_raw)
                    or raw_store._json(original_outputs) != output_raw):
                _refuse()
            self._check(live=False)
            if raw_store._json(outputs) != output_raw:
                _refuse()
        self._phase("after-readback", {"readback_outputs_sha256": raw_store._sha(output_raw)})
        if self.capture.worker_input_view and raw_store._json(outputs) != output_raw:
            _refuse()
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


def _verify(workspace, pin, binding, proof, view, vfs_pin, operations, outputs, checkpoint,
            *, worker_inputs=None):
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
        fields = {"schema", "binding", "phases", "records", "complete", "claims", "directory_identities"}
        if worker_inputs is not None:
            fields.add("worker_input_view")
        if (raw_store._json(payload) != raw
                or type(payload) is not dict or set(payload) != fields
                or payload["schema"] != (WORKER_INPUT_SCHEMA if worker_inputs is not None else SCHEMA)
                or payload["binding"] != expected_binding
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
        input_view_sha256 = None
        if worker_inputs is not None:
            expected_input_view = _worker_input_summary(owner, worker_inputs, checkpoint)
            if raw_store._json(payload["worker_input_view"]) != raw_store._json(expected_input_view):
                _refuse()
            input_view_sha256 = raw_store._sha(raw_store._json(expected_input_view))
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
            if index == 1 and input_view_sha256 is not None:
                links = {"worker_input_view_sha256": input_view_sha256}
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


def verify_worker_input_lifetime(workspace, pin, binding, proof, view, vfs_pin, operations,
                                 outputs, checkpoint, *, inputs, prior):
    """Strict successor reader; retain finite observations, never live authority."""
    from tools.static_python_rsi_fixture.execution_backend import BuildExecutionError

    failed = False
    try:
        if type(inputs) is not dict or set(inputs) != {"source", "toolchain"}:
            _refuse()
        _verify(workspace, pin, binding, proof, view, vfs_pin, operations, outputs, checkpoint,
                worker_inputs={**inputs, "work": prior})
    except (OSError, ValueError, TypeError, KeyError, AttributeError, IndexError, RecursionError,
            BuildExecutionError):
        failed = True
    if failed:
        _refuse()
