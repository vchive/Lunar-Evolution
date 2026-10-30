"""Local read-only facts about one independently installed account profile.

This module never starts a candidate, changes credentials or grants admission.
The trusted installer supplies original identities and independent content pins;
current metadata is never promoted into an original installation pin. Key and
config contents are not read. Unsupported or missing evidence stays unknown.
"""
from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import pwd
import re
import stat
import sys
from dataclasses import dataclass
from typing import NoReturn

_ANCHOR_PATH = "/etc/lunar-evolution/worker-account-anchor.json"
_MAX_PROFILE = 256 * 1024
_MAX_CONTENT = 128 * 1024 * 1024
_MAX_GROUPS = 256
_ROLES = frozenset({"key", "config", "state", "runtime", "helper", "isolation_profile"})
_HASHED = frozenset({"runtime", "helper", "isolation_profile"})
_DIR_FIELDS = frozenset({"dev", "ino", "mode", "uid", "gid"})
_FILE_FIELDS = _DIR_FIELDS | {"nlink", "size", "mtime_ns", "ctime_ns"}
_SCHEMA = "lunar-installed-worker-account-profile-v1"
_ANCHOR_SCHEMA = "lunar-installed-worker-account-anchor-v1"
_REPORT_SCHEMA = "lunar-worker-account-preflight-v1"
_SHA = re.compile(r"[0-9a-f]{64}\Z")


class AccountPreflightError(ValueError):
    """A fixed code; no paths, secret values or underlying OS messages."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__("worker_account_preflight_" + code)


def _fail(code: str) -> NoReturn:
    raise AccountPreflightError(code)


def _object(value: object, fields: set | frozenset) -> dict:
    if type(value) is not dict or set(value) != fields:
        _fail("schema_invalid")
    return value


def _integer(value: object, *, positive: bool = False) -> int:
    if type(value) is not int or not (1 if positive else 0) <= value < 2**64:
        _fail("identity_invalid")
    return value


def _digest(value: object) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None:
        _fail("digest_invalid")
    return value


def _path(value: object) -> tuple[str, ...]:
    if (type(value) is not str or not value.startswith("/") or len(value) > 4096
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        _fail("path_invalid")
    parts = tuple(value.split("/")[1:])
    if not 1 <= len(parts) <= 32 or any(part in {"", ".", ".."} for part in parts):
        _fail("path_invalid")
    return parts


def _identity(info: os.stat_result, *, directory: bool) -> dict[str, int]:
    result = {"dev": info.st_dev, "ino": info.st_ino, "mode": info.st_mode,
              "uid": info.st_uid, "gid": info.st_gid}
    if not directory:
        result.update(nlink=info.st_nlink, size=info.st_size,
                      mtime_ns=info.st_mtime_ns, ctime_ns=info.st_ctime_ns)
    return result


def _pin(value: object, *, directory: bool) -> dict[str, int]:
    row = _object(value, _DIR_FIELDS if directory else _FILE_FIELDS)
    for item in row.values():
        _integer(item)
    if not (stat.S_ISDIR(row["mode"]) if directory else stat.S_ISREG(row["mode"])):
        _fail("identity_invalid")
    if not directory and row["nlink"] != 1:
        _fail("hardlink_refused")
    return row


def _pairs(values: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in values:
        if key in result:
            _fail("schema_invalid")
        result[key] = value
    return result


def _parse(raw: bytes) -> dict:
    try:
        value = json.loads(raw, object_pairs_hook=_pairs,
                           parse_constant=lambda _: _fail("schema_invalid"))
    except (ValueError, UnicodeError, RecursionError):
        _fail("schema_invalid")
    if type(value) is not dict:
        _fail("schema_invalid")
    return value


class _Chain:
    """Hold every no-follow directory and recheck names against original pins."""

    def __init__(self, parts: tuple[str, ...], pins: list[dict] | None = None) -> None:
        self.fds: list[int] = []
        self.links: list[tuple[int, str, int]] = []
        self.pins: list[dict] = []
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        try:
            self.fds.append(os.open("/", flags))
            self.pins.append(_identity(os.fstat(self.fds[0]), directory=True))
            for name in parts:
                parent = self.fds[-1]
                before = os.stat(name, dir_fd=parent, follow_symlinks=False)
                if not stat.S_ISDIR(before.st_mode):
                    _fail("chain_refused")
                child = os.open(name, flags, dir_fd=parent)
                self.fds.append(child)
                self.links.append((parent, name, child))
                current = _identity(os.fstat(child), directory=True)
                if current != _identity(before, directory=True):
                    _fail("identity_drift")
                self.pins.append(current)
            if pins is not None and self.pins != pins:
                _fail("identity_drift")
            self.check()
        except BaseException:
            self.close()
            raise

    def check(self) -> None:
        for index, descriptor in enumerate(self.fds):
            if _identity(os.fstat(descriptor), directory=True) != self.pins[index]:
                _fail("identity_drift")
        for parent, name, child in reversed(self.links):
            named = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if _identity(named, directory=True) != _identity(os.fstat(child), directory=True):
                _fail("identity_drift")
        # The initial filesystem root itself must still name the same held root.
        root_fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            if _identity(os.fstat(root_fd), directory=True) != self.pins[0]:
                _fail("identity_drift")
        finally:
            os.close(root_fd)

    def close(self) -> None:
        while self.fds:
            os.close(self.fds.pop())


class _Entry:
    def __init__(self, path: str, *, directory: bool, chain_pins: list[dict] | None,
                 original: dict | None) -> None:
        self.fd = -1
        self.chain: _Chain | None = None
        self.directory = directory
        self.parts = _path(path)
        try:
            self.chain = _Chain(self.parts[:-1], chain_pins)
            before = os.stat(self.parts[-1], dir_fd=self.chain.fds[-1], follow_symlinks=False)
            good_type = stat.S_ISDIR(before.st_mode) if directory else stat.S_ISREG(before.st_mode)
            if not good_type or not directory and before.st_nlink != 1:
                _fail("entry_refused")
            flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
            if directory:
                flags |= os.O_DIRECTORY
            self.fd = os.open(self.parts[-1], flags, dir_fd=self.chain.fds[-1])
            self.original = _identity(before, directory=directory)
            if original is not None and self.original != original:
                _fail("identity_drift")
            self.check()
        except BaseException:
            self.close()
            raise

    def check(self) -> None:
        assert self.chain is not None
        self.chain.check()
        named = os.stat(self.parts[-1], dir_fd=self.chain.fds[-1], follow_symlinks=False)
        if (_identity(named, directory=self.directory) != self.original
                or _identity(os.fstat(self.fd), directory=self.directory) != self.original):
            _fail("identity_drift")

    def read(self, maximum: int) -> bytes:
        if self.directory or not 0 < self.original["size"] <= maximum:
            _fail("content_size_refused")
        output = bytearray()
        while len(output) <= maximum:
            chunk = os.read(self.fd, min(65536, maximum + 1 - len(output)))
            if not chunk:
                break
            output.extend(chunk)
        self.check()
        if len(output) != self.original["size"]:
            _fail("identity_drift")
        return bytes(output)

    def close(self) -> None:
        if self.fd >= 0:
            os.close(self.fd)
            self.fd = -1
        if self.chain is not None:
            self.chain.close()
            self.chain = None


@dataclass(frozen=True)
class InstalledAccountProfileAnchor:
    """Installer-owned original profile reference, never an execution capability.

    Only a trusted local installation caller supplies this object. The CLI reads
    its fixed root-owned bootstrap file; no remote/channel field selects it.
    The JSON bytes retain all original metadata without exposing mutable dicts.
    """

    canonical_bytes: bytes


def _anchor(raw: bytes) -> tuple[dict, list[dict], dict, dict]:
    value = _object(_parse(raw), {"schema", "profile_path", "profile_sha256",
                                  "profile_identity", "profile_chain", "protected_identities"})
    if value["schema"] != _ANCHOR_SCHEMA:
        _fail("schema_invalid")
    parts = _path(value["profile_path"])
    _digest(value["profile_sha256"])
    pin = _pin(value["profile_identity"], directory=False)
    chain = value["profile_chain"]
    if type(chain) is not list or len(chain) != len(parts):
        _fail("schema_invalid")
    for row in chain:
        _pin(row, directory=True)
    protected = _object(value["protected_identities"], {"key", "config"})
    for row in protected.values():
        _pin(row, directory=False)
    if any((row["dev"], row["ino"]) == (pin["dev"], pin["ino"])
           for row in protected.values()):
        _fail("entry_alias_refused")
    return value, chain, pin, protected


def _account(value: object) -> dict:
    row = _object(value, {"uid", "gid", "groups"})
    _integer(row["uid"])
    _integer(row["gid"])
    if row["uid"] >= 2**32 or row["gid"] >= 2**32:
        _fail("account_invalid")
    groups = row["groups"]
    if (type(groups) is not list or not 1 <= len(groups) <= _MAX_GROUPS
            or any(type(group) is not int or not 0 <= group < 2**32 for group in groups)
            or groups != sorted(set(groups)) or row["gid"] not in groups):
        _fail("account_invalid")
    try:
        current = pwd.getpwuid(row["uid"])
        actual_groups = sorted(set(os.getgrouplist(current.pw_name, current.pw_gid)))
    except (KeyError, OSError, OverflowError):
        _fail("account_unavailable")
    if (current.pw_uid != row["uid"] or current.pw_gid != row["gid"]
            or len(actual_groups) > _MAX_GROUPS or actual_groups != groups):
        _fail("account_drift")
    return row


def _candidate_access(pin: dict, candidate: dict, mask: int) -> bool:
    if candidate["uid"] == 0:
        return True
    shift = 6 if pin["uid"] == candidate["uid"] else 3 if pin["gid"] in candidate["groups"] else 0
    return bool((pin["mode"] >> shift) & mask)


def _xattrs(entry: _Entry) -> tuple[bool, bool]:
    """Absence is a bounded metadata fact, never a complete ACL/access proof."""
    if not hasattr(os, "listxattr"):
        return False, False
    try:
        names = os.listxattr(entry.fd)
    except (OSError, TypeError, NotImplementedError):
        return False, False
    if len(names) > 64 or any(type(name) is not str or len(name) > 255 for name in names):
        _fail("metadata_bounds_refused")
    if any("acl" in name.lower() for name in names):
        _fail("acl_present_refused")
    if "security.capability" in names:
        _fail("file_capability_refused")
    entry.check()
    return True, True


def _report(status: str, codes: list[str], *, profile_sha256: str | None = None,
            files: int = 0, metadata_observed: bool = False) -> dict:
    return {"schema": _REPORT_SCHEMA, "status": status, "codes": codes[:16],
            "profile_sha256": profile_sha256, "files_observed": files,
            "acl_and_file_capability_metadata_observed": metadata_observed,
            "ready_for_acceptance": False, "isolation_accepted": False,
            "native_runtime_accepted": False, "candidate_executed": False,
            "credentials_changed": False, "production_admission": False,
            "remote_cleanup_authority": False}


def inspect_account_isolation(anchor: InstalledAccountProfileAnchor) -> dict:
    """Inspect current local installed facts; always retain absent active evidence.

    No caller-provided acceptance flag exists. A valid profile with matching
    metadata is still unknown until independent runtime, account-transition,
    ACL/access and namespace-operation acceptance consumers are implemented.
    """
    if sys.platform != "linux":
        return _report("unsupported", ["platform_unsupported"])
    opened: list[_Entry] = []
    digest = None
    try:
        if (type(anchor) is not InstalledAccountProfileAnchor
                or type(anchor.canonical_bytes) is not bytes
                or not 0 < len(anchor.canonical_bytes) <= _MAX_PROFILE):
            _fail("anchor_invalid")
        reference, chain, original, protected = _anchor(anchor.canonical_bytes)
        profile_file = _Entry(reference["profile_path"], directory=False,
                              chain_pins=chain, original=original)
        opened.append(profile_file)
        if original["mode"] & 0o077 or original["mode"] & 0o7000:
            _fail("profile_permissions_refused")
        raw = profile_file.read(_MAX_PROFILE)
        digest = hashlib.sha256(raw).hexdigest()
        if digest != reference["profile_sha256"]:
            _fail("profile_digest_drift")
        profile = _object(_parse(raw), {"schema", "accounts", "entries", "isolation"})
        if profile["schema"] != _SCHEMA:
            _fail("schema_invalid")
        isolation = _object(profile["isolation"], {"platform", "transition", "namespaces"})
        if isolation != {"platform": "linux", "transition": "installed-helper-v1",
                         "namespaces": ["mount", "net", "pid", "user"]}:
            _fail("isolation_profile_refused")
        accounts = _object(profile["accounts"], {"wrapper", "candidate"})
        wrapper, candidate = _account(accounts["wrapper"]), _account(accounts["candidate"])
        if (candidate["uid"] in {0, wrapper["uid"]} or candidate["gid"] == wrapper["gid"]
                or os.geteuid() == candidate["uid"]):
            _fail("account_separation_refused")
        if original["uid"] not in {0, wrapper["uid"]}:
            _fail("profile_owner_refused")
        assert profile_file.chain is not None
        for pin in profile_file.chain.pins:
            if pin["uid"] not in {0, wrapper["uid"]} or pin["mode"] & 0o022:
                _fail("profile_chain_permissions_refused")
            if _candidate_access(pin, candidate, 2):
                _fail("candidate_write_refused")
        entries = _object(profile["entries"], _ROLES)
        identities = {(original["dev"], original["ino"])}
        profile_acl, profile_caps = _xattrs(profile_file)
        metadata = profile_acl and profile_caps
        for role in sorted(_ROLES):
            spec = _object(entries[role], {"path", "chain", "identity"}
                           | ({"sha256"} if role in _HASHED else set()))
            parts = _path(spec["path"])
            pins = spec["chain"]
            if type(pins) is not list or len(pins) != len(parts):
                _fail("schema_invalid")
            for pin in pins:
                _pin(pin, directory=True)
            expected = _pin(spec["identity"], directory=role == "state")
            if role in protected and expected != protected[role]:
                _fail("protected_identity_drift")
            if role in _HASHED and any(
                    (expected["dev"], expected["ino"]) == (pin["dev"], pin["ino"])
                    for pin in protected.values()):
                _fail("entry_alias_refused")
            entry = _Entry(spec["path"], directory=role == "state",
                           chain_pins=pins, original=expected)
            opened.append(entry)
            identity = (expected["dev"], expected["ino"])
            if identity in identities:
                _fail("entry_alias_refused")
            identities.add(identity)
            if (expected["uid"] not in {0, wrapper["uid"]}
                    or expected["mode"] & 0o022 or expected["mode"] & 0o7000):
                _fail("entry_permissions_refused")
            if role in {"runtime", "helper"} and not expected["mode"] & 0o111:
                _fail("executable_mode_refused")
            for pin in pins:
                if pin["uid"] not in {0, wrapper["uid"]} or pin["mode"] & 0o022:
                    _fail("chain_permissions_refused")
            for pin in [*pins, expected]:
                if _candidate_access(pin, candidate, 2):
                    _fail("candidate_write_refused")
            if role in {"key", "config", "state"}:
                if (_candidate_access(expected, candidate, 7)
                        or expected["gid"] in candidate["groups"]):
                    _fail("candidate_secret_access_refused")
                if expected["mode"] & 0o077:
                    _fail("private_entry_refused")
            if role in _HASHED and hashlib.sha256(entry.read(_MAX_CONTENT)).hexdigest() != _digest(spec["sha256"]):
                _fail("artifact_digest_drift")
            acl_observed, caps_observed = _xattrs(entry)
            metadata = metadata and acl_observed and caps_observed
        # Pin ancestors too: a permissive ACL/capability observation cannot be
        # inferred from leaf mode bits, nor from an unavailable xattr API.
        for entry in opened:
            assert entry.chain is not None
            for fd in entry.chain.fds:
                try:
                    names = os.listxattr(fd)
                except (AttributeError, OSError, TypeError, NotImplementedError):
                    metadata = False
                    continue
                if len(names) > 64 or any(type(name) is not str or len(name) > 255 for name in names):
                    _fail("metadata_bounds_refused")
                if any("acl" in name.lower() for name in names):
                    _fail("acl_present_refused")
                if "security.capability" in names:
                    _fail("file_capability_refused")
            entry.check()
        codes = ["installed_identity_facts_observed", "runtime_acceptance_unavailable",
                 "account_transition_unverified", "namespace_operations_unverified",
                 "effective_capabilities_unverified", "acl_access_semantics_unverified"]
        if not metadata:
            codes.append("acl_capability_metadata_unknown")
        return _report("unknown", codes, profile_sha256=digest, files=len(identities) - 1,
                       metadata_observed=metadata)
    except AccountPreflightError as exc:
        return _report("refused", [exc.code], profile_sha256=digest)
    except OSError as exc:
        code = "installed_file_unavailable" if exc.errno == errno.ENOENT else "local_observation_refused"
        return _report("refused", [code], profile_sha256=digest)
    finally:
        for entry in reversed(opened):
            entry.close()


def inspect_default_account_isolation() -> dict:
    """Read the one fixed private root-installed bootstrap; no path argument."""
    if sys.platform != "linux":
        return _report("unsupported", ["platform_unsupported"])
    entry = None
    try:
        entry = _Entry(_ANCHOR_PATH, directory=False, chain_pins=None, original=None)
        if entry.original["uid"] != 0 or entry.original["mode"] & 0o7077:
            _fail("anchor_permissions_refused")
        assert entry.chain is not None
        if any(pin["uid"] != 0 or pin["mode"] & 0o022 for pin in entry.chain.pins):
            _fail("anchor_chain_refused")
        anchor = InstalledAccountProfileAnchor(entry.read(_MAX_PROFILE))
        report = inspect_account_isolation(anchor)
        entry.check()
        return report
    except FileNotFoundError:
        return _report("configuration_absent", ["installed_anchor_absent"])
    except AccountPreflightError as exc:
        return _report("refused", [exc.code])
    except OSError:
        return _report("refused", ["local_observation_refused"])
    finally:
        if entry is not None:
            entry.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only installed worker account preflight")
    parser.add_argument("--inspect-installed", action="store_true", required=True)
    parser.parse_args(argv)
    report = inspect_default_account_isolation()
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0 if report["status"] == "ready_for_acceptance" else 2


if __name__ == "__main__":
    raise SystemExit(main())
