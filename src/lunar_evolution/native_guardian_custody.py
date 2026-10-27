"""Explicit native receiver launch and read-only private guardian diagnostics.

This opt-in API executes an original verified sealed receiver FD, which becomes
the existing native guardian's direct parent. It is not wired into the default
trusted attempt, grants no attestation, and establishes no cleanup authority.
"""
from __future__ import annotations

import json
import math
import os
import stat
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ._candidate_workspace_io import DirectoryChain
from .linux_executable_binding import LinuxSealedExecutable, _validate_original_linux_executable
from .native_guardian import (
    NativeGuardianError,
    NativeGuardianOwner,
    _pipe,
    _remaining,
    _wait_ready,
)

_PROTOCOL = "lunar-native-guardian-custody-v1"
_REGISTRATION = "guardian-registration-v1.json"
_EVENT = "guardian-event-v1.json"
_DIGESTS = ("context_sha256", "launch_sha256", "profile_sha256",
            "guardian_sha256", "receiver_sha256")
_FALSE = ("native_success", "publication_authority", "cleanup_authority", "production_admission",
          "isolation_accepted", "immutable_custody_verified", "whole_group_cleanup_verified")
_POPEN = subprocess.Popen
_MAX_RECORD = 2048


@dataclass(frozen=True, slots=True)
class GuardianCustodyReference:
    """Original trusted caller's reference, retained outside the receiver store.

    There is intentionally no discovery/from-current-records constructor. The
    trusted installation must preserve these original bytes for a later reader.
    This is private filesystem custody, not an independently attested reference.
    """

    canonical_bytes: bytes = field(repr=False)


class DurableNativeGuardianOwner(NativeGuardianOwner):
    """Own the exact live receiver child and original group FD, never stored IDs."""

    __slots__ = ("reference",)

    def __init__(self, process, receiver, group_fd, deadline, monotonic, reference):
        super().__init__(process, receiver, group_fd, deadline, monotonic)
        self.reference = reference

    def cleanup(self, timeout: float = 2.0) -> bool:
        """Retire exact owned handles; abnormal nested-child cleanup stays unknown.

        A receiver killed while blocked in fsync may leave its original native
        guardian alive until that guardian's original deadline. Reaping only
        the receiver cannot establish retirement of that nested child.
        """
        normally_finished = self._finished
        retired = super().cleanup(timeout)
        return retired and normally_finished


def native_guardian_receiver_source_path() -> Path:
    """Source location for explicit build/install tooling; this does not build it."""
    return Path(__file__).with_name("native_guardian_receiver.c")


def _digest(value: object) -> str:
    if (type(value) is not str or len(value) != 64
            or any(c not in "0123456789abcdef" for c in value)):
        raise ValueError("guardian_custody_digest_invalid")
    return value


def _json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _parse(raw: bytes, maximum: int) -> dict:
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("guardian_custody_duplicate")
            result[key] = value
        return result

    if type(raw) is not bytes or not 0 < len(raw) <= maximum:
        raise ValueError("guardian_custody_wire_invalid")
    value = json.loads(raw, object_pairs_hook=pairs,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    if type(value) is not dict:
        raise ValueError("guardian_custody_wire_invalid")
    return value


def _private_chain(chain: DirectoryChain) -> list[list[int]]:
    if type(chain) is not DirectoryChain or not 0 < len(chain.fds) <= 128:
        raise ValueError("guardian_custody_directory_required")
    chain.check()
    pins = []
    for fd in chain.fds:
        info = os.fstat(fd)
        sticky_root = info.st_uid == 0 and info.st_mode & stat.S_ISVTX
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid not in {0, os.geteuid()}
                or (info.st_mode & 0o022 and not sticky_root)):
            raise ValueError("guardian_custody_directory_invalid")
        pins.append([info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid])
    leaf = os.fstat(chain.fd)
    if leaf.st_uid != os.geteuid() or stat.S_IMODE(leaf.st_mode) != 0o700:
        raise ValueError("guardian_custody_directory_invalid")
    return pins


def _elf(binding: LinuxSealedExecutable) -> None:
    # A same-value DTO does not pass the existing original live-owner verifier.
    _validate_original_linux_executable(binding)
    if os.pread(binding.fd, 4, 0) != b"\x7fELF":
        raise ValueError("guardian_custody_native_image_required")


def start_durable_native_guardian(
    *, process: subprocess.Popen, receiver: LinuxSealedExecutable,
    bootstrap: LinuxSealedExecutable, lifeline_fd: int, finish_fd: int,
    ack_fd: int, ack_read_fd: int, original_directory_chain: DirectoryChain,
    original_context_sha256: str, original_launch_sha256: str, original_profile_sha256: str,
    deadline: float, deadline_ns: int, monotonic: Callable[[], float] = time.monotonic,
) -> DurableNativeGuardianOwner:
    """Opt in to the real independent native custody/ACK boundary.

    Caller-created borrowed endpoints stay caller-owned. The original private
    directory is exclusively reserved for this one attempt; existing records
    refuse. No account, file mode, runtime, attestation or fresh deadline is
    provisioned here. Missing installed images refuse; no host Python fallback.
    """
    code = "native_guardian_custody_start_invalid"
    if sys.platform != "linux" or not hasattr(os, "pidfd_open"):
        raise NativeGuardianError("native_guardian_custody_unsupported")
    try:
        finite = type(deadline) in {int, float} and math.isfinite(deadline)
    except OverflowError:
        finite = False
    if (not finite or not callable(monotonic) or type(deadline_ns) is not int
            or not 0 < deadline_ns <= 0xFFFFFFFFFFFFFFFF
            or not isinstance(process, _POPEN) or type(process.pid) is not int or process.pid <= 1
            or process.returncode is not None):
        raise NativeGuardianError(code)
    _remaining(deadline, monotonic, code)
    owner = None
    group_fd = -1
    error = None
    try:
        _elf(receiver)
        _elf(bootstrap)
        pins = _private_chain(original_directory_chain)
        reference_value = {
            "protocol": _PROTOCOL, "directory_chain": pins,
            "context_sha256": _digest(original_context_sha256),
            "launch_sha256": _digest(original_launch_sha256),
            "profile_sha256": _digest(original_profile_sha256),
            "guardian_sha256": _digest(bootstrap.sha256),
            "receiver_sha256": _digest(receiver.sha256),
            "deadline_monotonic_ns": deadline_ns,
        }
        reference = GuardianCustodyReference(_json(reference_value))
        descriptors = (receiver.fd, bootstrap.fd, lifeline_fd, finish_fd, ack_fd,
                       ack_read_fd, original_directory_chain.fd)
        if (any(type(fd) is not int or fd <= 2 for fd in descriptors)
                or len(set(descriptors)) != len(descriptors)
                or process.poll() is not None or os.getpgid(process.pid) != process.pid
                or os.getsid(process.pid) != process.pid):
            raise ValueError("guardian_custody_original_process_required")
        for fd, direction in ((lifeline_fd, os.O_RDONLY), (finish_fd, os.O_RDONLY),
                              (ack_fd, os.O_WRONLY), (ack_read_fd, os.O_RDONLY)):
            _pipe(fd, direction)
        pipe_pins = [(os.fstat(fd).st_dev, os.fstat(fd).st_ino)
                     for fd in (lifeline_fd, finish_fd, ack_fd, ack_read_fd)]
        if pipe_pins[2] != pipe_pins[3] or len(set(pipe_pins[:3])) != 3:
            raise ValueError("guardian_custody_pipe_binding_invalid")
        # Both exact immutable images and the original native group are live
        # creator-owned capabilities. No numeric PID is retained for restart.
        group_fd = os.pidfd_open(process.pid, 0)
        if group_fd <= 2 or group_fd in descriptors or process.poll() is not None:
            raise ValueError("guardian_custody_original_group_required")
        _remaining(deadline, monotonic, code)
        command = [
            receiver.executable, "--bootstrap-fd", str(bootstrap.fd), "--group-pidfd", str(group_fd),
            "--controller-lifeline-fd", str(lifeline_fd), "--guardian-finish-fd", str(finish_fd),
            "--guardian-ack-fd", str(ack_fd), "--custody-dir-fd", str(original_directory_chain.fd),
            "--context-sha256", reference_value["context_sha256"],
            "--launch-sha256", reference_value["launch_sha256"],
            "--profile-sha256", reference_value["profile_sha256"],
            "--guardian-sha256", bootstrap.sha256, "--receiver-sha256", receiver.sha256,
            "--deadline-monotonic-ns", str(deadline_ns),
        ]
        watcher = subprocess.Popen(
            command, executable=receiver.executable,
            pass_fds=(receiver.fd, bootstrap.fd, group_fd, lifeline_fd, finish_fd, ack_fd,
                      original_directory_chain.fd),
            close_fds=True, start_new_session=True, cwd="/",
            env={"PATH": os.defpath, "LANG": "C"}, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        owner = DurableNativeGuardianOwner(process, watcher, group_fd, deadline, monotonic, reference)
        _wait_ready(ack_read_fd, deadline, monotonic)
        if (watcher.poll() is not None or process.poll() is not None
                or _private_chain(original_directory_chain) != pins):
            raise ValueError("guardian_custody_ready_invalid")
        _elf(receiver)
        _elf(bootstrap)
        _remaining(deadline, monotonic, code)
        # R alone is not trusted: independently read the exact created private
        # registration before returning the gate-enabling live owner.
        if inspect_native_guardian_custody(
            reference, original_directory_chain=original_directory_chain,
        )["state"] != "registered":
            raise ValueError("guardian_custody_registration_invalid")
        _remaining(deadline, monotonic, code)
        return owner
    except BaseException:  # noqa: BLE001 - interrupts also preserve the original live cleanup owner
        error = NativeGuardianError(code)
        raise error from None
    finally:
        if sys.exc_info()[0] is not None:
            if owner is not None and error is not None:
                error.guardian_owner = owner
            elif group_fd >= 0:
                os.close(group_fd)


def _stat_pin(info: os.stat_result) -> tuple:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_uid, info.st_gid, info.st_nlink,
            info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _read(directory: DirectoryChain, name: str) -> tuple[dict | None, os.stat_result]:
    named = os.stat(name, dir_fd=directory.fd, follow_symlinks=False)
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                 dir_fd=directory.fd)
    try:
        before = os.fstat(fd)
        if (not stat.S_ISREG(before.st_mode) or stat.S_IMODE(before.st_mode) != 0o600
                or before.st_uid != os.geteuid() or before.st_nlink != 1
                or not 0 <= before.st_size <= _MAX_RECORD or _stat_pin(before) != _stat_pin(named)):
            raise ValueError("guardian_custody_record_invalid")
        raw = os.read(fd, _MAX_RECORD + 1)
        if (len(raw) != before.st_size or _stat_pin(os.fstat(fd)) != _stat_pin(before)
                or _stat_pin(os.stat(name, dir_fd=directory.fd, follow_symlinks=False)) != _stat_pin(before)):
            raise ValueError("guardian_custody_record_drift")
        return (_parse(raw, _MAX_RECORD) if raw else None), before
    finally:
        os.close(fd)


def inspect_native_guardian_custody(
    reference: GuardianCustodyReference, *, original_directory_chain: DirectoryChain,
) -> dict:
    """Read this original installation/context without launching, signaling or repair.

    The independently retained original reference and trusted private filesystem
    are required. Terminal filesystem bytes are not immutable consumed-bytecode
    custody, and the watcher exit remains cleanup unknown even after D/exit0.
    """
    report = {"state": "unavailable", "codes": ["guardian_custody_unknown"],
              "signal_result_known": False, "cleanup_status": "unknown",
              **{name: False for name in _FALSE}}
    try:
        if type(reference) is not GuardianCustodyReference:
            raise ValueError("guardian_custody_original_required")
        baseline = reference.canonical_bytes
        original = _parse(baseline, 32768)
        if set(original) != {"protocol", "directory_chain", "deadline_monotonic_ns", *_DIGESTS}:
            raise ValueError("guardian_custody_original_invalid")
        if (original["protocol"] != _PROTOCOL or _json(original) != baseline
                or type(original["deadline_monotonic_ns"]) is not int
                or not 0 < original["deadline_monotonic_ns"] <= 0xFFFFFFFFFFFFFFFF):
            raise ValueError("guardian_custody_original_invalid")
        for name in _DIGESTS:
            _digest(original[name])
        if (type(original["directory_chain"]) is not list
                or any(type(pin) is not list or len(pin) != 5
                       or any(type(item) is not int or item < 0 for item in pin)
                       for pin in original["directory_chain"])):
            raise ValueError("guardian_custody_original_invalid")
        pins = _private_chain(original_directory_chain)
        if original["directory_chain"] != pins:
            raise ValueError("guardian_custody_directory_drift")
        common = {name: original[name] for name in (*_DIGESTS, "deadline_monotonic_ns")}
        common.update({"protocol": _PROTOCOL, "directory_device": pins[-1][0],
                       "directory_inode": pins[-1][1], "native_ready_observed": True,
                       "signal_result_known": False, "cleanup_status": "unknown",
                       **{name: False for name in _FALSE}})

        def checked(name: str, kind: str):
            value, info = _read(original_directory_chain, name)
            if value is None:
                return None
            fields = {"kind", "record_device", "record_inode", "native_d_observed",
                      "watcher_exit_kind", "watcher_exit_value"}
            if (set(value) != set(common) | fields or value["kind"] != kind
                    or type(value["record_device"]) is not int or type(value["record_inode"]) is not int
                    or (value["record_device"], value["record_inode"]) != (info.st_dev, info.st_ino)
                    or type(value["native_d_observed"]) is not bool
                    or any(type(value[k]) is not type(v) or value[k] != v for k, v in common.items())
                    or type(value["watcher_exit_kind"]) is not int
                    or type(value["watcher_exit_value"]) is not int):
                raise ValueError("guardian_custody_binding_invalid")
            if kind == "custody-registration":
                if (value["native_d_observed"] is not False or value["watcher_exit_kind"] != 0
                        or value["watcher_exit_value"] != 0):
                    raise ValueError("guardian_custody_registration_invalid")
            elif (value["watcher_exit_kind"] not in {1, 2}
                  or not 0 <= value["watcher_exit_value"] <= 255):
                raise ValueError("guardian_custody_event_invalid")
            return value

        registration = checked(_REGISTRATION, "custody-registration")
        if registration is None:
            return report
        event = checked(_EVENT, "watcher-exit")
        if reference.canonical_bytes != baseline or _private_chain(original_directory_chain) != pins:
            raise ValueError("guardian_custody_original_drift")
        if checked(_REGISTRATION, "custody-registration") != registration:
            raise ValueError("guardian_custody_registration_drift")
        if checked(_EVENT, "watcher-exit") != event:
            raise ValueError("guardian_custody_event_drift")
        report.update({"state": "watcher_exit_observed" if event is not None else "registered",
                       "codes": [], "context_sha256": original["context_sha256"],
                       "deadline_monotonic_ns": original["deadline_monotonic_ns"]})
        if event is not None:
            report.update({name: event[name] for name in (
                "native_d_observed", "watcher_exit_kind", "watcher_exit_value",
            )})
        return report
    except Exception:  # noqa: BLE001 - partial, missing, drifted and malformed state stay unknown
        return report
