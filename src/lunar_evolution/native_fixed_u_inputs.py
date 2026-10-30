"""Original input custody for the explicit fixed-U whole-scope profile.

Only the live installed whole-scope owner can create this child owner. Its
canonical security description is an observation, never a transferable grant.
The default input protocols continue to require their original 0400/0500 modes.
"""
from __future__ import annotations

import errno
import hashlib
import os
import stat
import struct
import sys
from pathlib import Path

FIXED_U_INPUT_PROFILE = "linux-fixed-u-input-acl-v1"
_TOKEN = object()
_ACCESS = "system.posix_acl_access"
_DEFAULT = "system.posix_acl_default"
_NAMES = {".rsi-input": ("request.json", "memory.json"), ".producer-input": ("config.json",)}
_MAXIMUM = 512 * 1024


class NativeFixedUInputError(ValueError):
    def __init__(self, reason="unavailable"):
        self.code = "native_fixed_u_inputs_" + reason
        super().__init__(self.code)


def _fail(reason="unavailable"):
    raise NativeFixedUInputError(reason)


def _acl(uid, permission):
    if type(uid) is not int or not 0 < uid < 2**32 - 1 or permission not in (4, 5):
        _fail("profile_invalid")
    return struct.pack("<I", 2) + b"".join(struct.pack("<HHI", *entry) for entry in (
        (1, permission, 2**32 - 1), (2, permission, uid), (4, 0, 2**32 - 1),
        (16, permission, 2**32 - 1), (32, 0, 2**32 - 1),
    ))


def _no_acl(fd, name):
    try:
        os.getxattr(fd, name)
    except OSError as exc:
        if exc.errno == errno.ENODATA:
            return
        raise
    _fail("acl_changed")


def _info(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid,
            info.st_nlink, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _identity_wire(identity):
    return dict(zip(("device", "inode", "mount_id", "uid", "gid", "mode"), identity[:6], strict=True))


class NativeFixedUInputOwner:
    """One noncopyable creation transaction beneath its original published attempt.

    Creator descriptors remain private to trusted A and never appear in pass_fds.
    Rechecking them supplies logical input custody, not kernel-immutable storage,
    accepted build custody, quiescence or production admission.
    """

    __slots__ = ("_batch", "_closed", "_deadline", "_directory", "_directory_name",
                 "_directory_pin", "_frozen", "_origin", "_records", "_scope", "_workspace")

    def __init__(self, token, scope):
        if token is not _TOKEN:
            _fail("owner_invalid")
        self._scope = scope
        self._closed = False
        self._origin = self._origin_context()
        self._deadline = scope.deadline_ns
        self._directory = None
        self._directory_name = None
        self._directory_pin = None
        self._records = {}
        self._workspace = self._batch = None
        self._frozen = False

    def __copy__(self):
        _fail("owner_invalid")

    def __deepcopy__(self, memo):
        _fail("owner_invalid")

    def __reduce_ex__(self, protocol):
        _fail("owner_invalid")

    def _origin_context(self):
        scope = self._scope
        profile = scope._profile
        return (scope._profile_sha256, profile["uid"], profile["gid"], tuple(profile["groups"]),
                tuple(profile["namespaces"]), profile["identities"][1], scope._publication_pins[0][0],
                scope.journal_id, tuple(profile["paths"]))

    def _check_origin(self, *, require_unexpired=True):
        from .native_whole_scope import NativeWholeScopeOwner

        scope = self._scope
        if (type(require_unexpired) is not bool or self._closed or type(scope) is not NativeWholeScopeOwner
                or scope._fixed_u_input_owner is not self or sys.platform != "linux"):
            _fail("owner_invalid")
        scope._check_installation()
        scope._check_published_grants()
        if require_unexpired:
            scope._remaining()
        if self._origin_context() != self._origin or scope.deadline_ns > self._deadline:
            _fail("original_changed")

    @property
    def security_binding(self):
        return self.binding()

    def binding(self, *, require_unexpired=True):
        self._check_origin(require_unexpired=require_unexpired)
        profile, uid, gid, groups, namespaces, execution, attempt, journal, _paths = self._origin
        return {
            "profile": FIXED_U_INPUT_PROFILE, "whole_scope_profile_sha256": profile,
            "candidate_uid": uid, "candidate_gid": gid, "candidate_groups": list(groups),
            "namespaces": [list(identity) for identity in namespaces],
            "execution_root_identity": _identity_wire(execution),
            "attempt_identity": _identity_wire(attempt), "journal_id": journal,
            "deadline_monotonic_ns": self._deadline,
        }

    def check_context(self, workspace, batch, directory_name, *, require_unexpired=True):
        self._check_origin(require_unexpired=require_unexpired)
        root, attempt = Path(workspace), Path(batch)
        if (directory_name not in _NAMES or attempt != root / "evolution" / "producer-batches" / self._scope.journal_id
                or attempt != self._scope.working_directory.parent
                or attempt.parent != Path(self._scope._profile["paths"][1])):
            _fail("layout_invalid")
        if self._directory_name is not None and (
                directory_name != self._directory_name or root != self._workspace or attempt != self._batch):
            _fail("layout_invalid")

    def _pin(self, fd):
        from .native_whole_scope import _mount_id

        return (*_info(os.fstat(fd)), _mount_id(fd))

    def _check_named(self, fd, parent, name, pin):
        from .native_whole_scope import _mount_id

        if (self._pin(fd) != pin or (*_info(os.stat(name, dir_fd=parent, follow_symlinks=False)),
                _mount_id(parent, os.fsencode(name))) != pin or pin[-1] != self._origin[6][2]):
            _fail("original_changed")

    def _check_acl(self, fd, *, directory=False, manifest=False):
        info = os.fstat(fd)
        if (info.st_uid or info.st_gid or stat.S_IMODE(info.st_mode) != (
                0o550 if directory else 0o400 if manifest else 0o440)):
            _fail("acl_changed")
        if manifest:
            _no_acl(fd, _ACCESS)
        elif os.getxattr(fd, _ACCESS) != _acl(self._origin[1], 5 if directory else 4):
            _fail("acl_changed")
        _no_acl(fd, _DEFAULT)

    def prepare(self, workspace, batch, directory_name, contents, manifest_builder):
        """Create exact data and a root-only manifest; freeze only after final ACLs."""
        self.check_context(workspace, batch, directory_name)
        if self._directory_name is not None or self._scope._channels_prepared or self._scope._final_intent is not None:
            _fail("already_started")
        if (type(contents) is not tuple or tuple(name for name, _ in contents) != _NAMES[directory_name]
                or any(type(data) is not bytes or len(data) > _MAXIMUM for _, data in contents)):
            _fail("inputs_invalid")
        self._workspace, self._batch, self._directory_name = Path(workspace), Path(batch), directory_name
        parent = self._scope._published[0]
        os.mkdir(directory_name, 0o700, dir_fd=parent)
        created = os.stat(directory_name, dir_fd=parent, follow_symlinks=False)
        self._directory = os.open(directory_name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                  dir_fd=parent)
        opened = os.fstat(self._directory)
        if (_info(created) != _info(opened) or opened.st_uid or opened.st_gid
                or not stat.S_ISDIR(opened.st_mode) or stat.S_IMODE(opened.st_mode) != 0o700):
            _fail("original_changed")
        _no_acl(self._directory, _ACCESS)
        _no_acl(self._directory, _DEFAULT)
        files = [self._write_new(name, data) for name, data in contents]
        manifest_fd = self._create("manifest.json")
        info = os.fstat(manifest_fd)
        raw = manifest_builder(files, {"device": info.st_dev, "inode": info.st_ino}, self.security_binding)
        if type(raw) is not bytes or not 0 < len(raw) <= _MAXIMUM:
            _fail("manifest_invalid")
        self._write_created("manifest.json", manifest_fd, raw, manifest=True)
        os.fchmod(self._directory, 0o500)
        os.setxattr(self._directory, _ACCESS, _acl(self._origin[1], 5), flags=os.XATTR_CREATE)
        self._check_acl(self._directory, directory=True)
        os.fsync(self._directory)
        os.fsync(parent)
        self._directory_pin = self._pin(self._directory)
        self._frozen = True
        self.check()

    def _create(self, name):
        self._check_origin()
        if name in self._records:
            _fail("already_started")
        fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=self._directory)
        try:
            self._records[name] = {"fd": fd, "pin": None, "bytes": None}
        except BaseException:
            os.close(fd)
            raise
        info = os.fstat(fd)
        if info.st_uid or info.st_gid or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            _fail("original_changed")
        _no_acl(fd, _ACCESS)
        _no_acl(fd, _DEFAULT)
        return fd

    def _write_new(self, name, raw):
        return self._write_created(name, self._create(name), raw)

    def _write_created(self, name, fd, raw, *, manifest=False):
        self._check_origin()
        offset = 0
        while offset < len(raw):
            self._check_origin()
            size = os.write(fd, raw[offset:])
            if size <= 0:
                _fail("write_failed")
            offset += size
        os.fchmod(fd, 0o400)
        if not manifest:
            os.setxattr(fd, _ACCESS, _acl(self._origin[1], 4), flags=os.XATTR_CREATE)
        self._check_acl(fd, manifest=manifest)
        os.fsync(fd)
        pin = self._pin(fd)
        self._check_named(fd, self._directory, name, pin)
        if pin[5] != 1 or pin[6] != len(raw) or os.pread(fd, len(raw) + 1, 0) != raw:
            _fail("original_changed")
        self._records[name].update(pin=pin, bytes=raw)
        return {"name": name, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                "device": pin[0], "inode": pin[1], "mtime_ns": pin[7], "ctime_ns": pin[8]}

    def check(self, *, require_unexpired=True):
        self._check_origin(require_unexpired=require_unexpired)
        if self._directory_name is None:
            return
        if not self._frozen or self._directory_pin is None:
            _fail("inputs_incomplete")
        self._check_named(self._directory, self._scope._published[0], self._directory_name, self._directory_pin)
        self._check_acl(self._directory, directory=True)
        with os.scandir(self._directory) as entries:
            if {entry.name for entry in entries} != {*_NAMES[self._directory_name], "manifest.json"}:
                _fail("original_changed")
        for name, record in self._records.items():
            fd, pin, raw = record["fd"], record["pin"], record["bytes"]
            if pin is None or raw is None:
                _fail("inputs_incomplete")
            self._check_named(fd, self._directory, name, pin)
            self._check_acl(fd, manifest=name == "manifest.json")
            if os.pread(fd, len(raw) + 1, 0) != raw:
                _fail("original_changed")
            self._check_named(fd, self._directory, name, pin)
        self._check_origin(require_unexpired=require_unexpired)

    def check_file_info(self, path, info, *, require_unexpired=True):
        self.check(require_unexpired=require_unexpired)
        path = Path(path)
        if (not self._frozen or path.parent != self._batch / self._directory_name
                or path.name not in self._records or _info(info) != self._records[path.name]["pin"][:-1]):
            _fail("original_changed")

    def check_manifest(self, workspace, path, raw, *, require_unexpired=True):
        self.check(require_unexpired=require_unexpired)
        if (not self._frozen or Path(workspace) != self._workspace
                or Path(path) != self._batch / self._directory_name
                or raw != self._records["manifest.json"]["bytes"]):
            _fail("manifest_changed")

    def check_materials(self, materials, *, require_unexpired=False):
        self.check(require_unexpired=require_unexpired)
        if not self._frozen or type(materials) is not tuple:
            _fail("materials_invalid")
        expected = {str(self._batch / self._directory_name / name): self._records[name]
                    for name in _NAMES[self._directory_name]}
        if len(materials) != len(expected) or {material.path for material in materials} != set(expected):
            _fail("materials_invalid")
        for material in materials:
            record = expected[material.path]
            pin = record["pin"]
            if ((material.identity.device, material.identity.inode, material.identity.kind) != (pin[0], pin[1], "file")
                    or material.content != record["bytes"] or material.mtime_ns != pin[7] or material.ctime_ns != pin[8]):
                _fail("materials_invalid")

    def close(self):
        if self._closed:
            return
        self._closed = True
        failure = None
        for record in self._records.values():
            try:
                os.close(record["fd"])
            except OSError as exc:
                failure = failure or exc
        if self._directory is not None:
            try:
                os.close(self._directory)
            except OSError as exc:
                failure = failure or exc
        if failure is not None:
            raise failure


def checked_fixed_u_input_owner(value, *, require_unexpired=True):
    if type(value) is not NativeFixedUInputOwner:
        _fail("owner_invalid")
    try:
        value.check(require_unexpired=require_unexpired)
    except NativeFixedUInputError:
        raise
    except (TypeError, AttributeError, KeyError, OverflowError) as exc:
        raise NativeFixedUInputError("owner_invalid") from exc
    except (OSError, ValueError) as exc:
        raise NativeFixedUInputError("original_changed") from exc
    return value


def _acquire_fixed_u_input_owner(scope):
    from .native_whole_scope import NativeWholeScopeOwner

    if (type(scope) is not NativeWholeScopeOwner or scope._fixed_u_input_owner is not None
            or scope._published is None or scope._channels_prepared or scope._final_intent is not None):
        _fail("owner_invalid")
    scope._check_installation()
    scope._check_published_grants()
    scope._remaining()
    owner = NativeFixedUInputOwner(_TOKEN, scope)
    scope._fixed_u_input_owner = owner
    try:
        owner.check()
    except BaseException:
        owner.close()
        raise
    return owner


__all__ = ["FIXED_U_INPUT_PROFILE", "NativeFixedUInputError", "NativeFixedUInputOwner"]
