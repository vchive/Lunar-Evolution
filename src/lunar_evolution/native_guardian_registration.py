"""Explicit original native registration to independent guardian custody pairing.

The returned reference must be retained independently by trusted installation
code. Current receiver files cannot create it, and it grants no live capability.
"""
from __future__ import annotations

import hashlib
import os
import stat
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ._candidate_workspace_io import DirectoryChain
from .linux_executable_binding import LinuxSealedExecutable
from .native_guardian import _remaining
from .native_guardian_custody import (
    DurableNativeGuardianOwner,
    GuardianCustodyReference,
    _digest,
    _elf,
    _json,
    _parse,
    _private_chain,
    inspect_native_guardian_custody,
    start_durable_native_guardian,
)

_PROTOCOL = "lunar-native-guardian-registration-binding-v1"
_NAME = "guardian-native-registration-v1.json"
_MAX = 32768


class NativeGuardianRegistrationError(ValueError):
    """Fixed pairing errors without private paths or original authorization."""

    code = "native_guardian_registration_binding_invalid"


def _fail() -> None:
    raise NativeGuardianRegistrationError("native_guardian_registration_binding_invalid")


def _path(value: object) -> Path:
    if (type(value) is not str or not value.startswith("/") or len(value) > 4096
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
            or len(value.split("/")) > 128
            or any(part in {"", ".", ".."} for part in value.split("/")[1:])):
        _fail()
    return Path(value)


def _pin(info: os.stat_result, raw: bytes) -> tuple[str | int, ...]:
    return (hashlib.sha256(raw).hexdigest(), info.st_size, info.st_dev, info.st_ino,
            info.st_mtime_ns, info.st_ctime_ns)


def _record_shape(info: os.stat_result) -> bool:
    return (stat.S_ISREG(info.st_mode) and stat.S_IMODE(info.st_mode) == 0o600
            and info.st_uid == os.geteuid() and info.st_nlink == 1)


def _bound(chain: DirectoryChain, raw: bytes, pin: tuple | list) -> None:
    if (type(raw) is not bytes or not 0 < len(raw) <= _MAX
            or type(pin) not in {tuple, list} or len(pin) != 6
            or any(type(v) is not int or v < 0 for v in pin[1:])
            or pin[0] != hashlib.sha256(raw).hexdigest() or pin[1] != len(raw)):
        _fail()
    chain.check()
    named = os.stat(_NAME, dir_fd=chain.fd, follow_symlinks=False)
    fd = os.open(_NAME, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                 dir_fd=chain.fd)
    try:
        for info in (named, os.fstat(fd)):
            if not _record_shape(info) or _pin(info, raw) != tuple(pin):
                _fail()
        if os.read(fd, _MAX + 1) != raw:
            _fail()
        for info in (os.fstat(fd), os.stat(_NAME, dir_fd=chain.fd, follow_symlinks=False)):
            if not _record_shape(info) or _pin(info, raw) != tuple(pin):
                _fail()
        chain.check()
    finally:
        os.close(fd)


def _native_projection(context) -> dict:
    # Imported here to avoid a module cycle at the explicit trusted runner seam.
    from .native_trusted_attempt import NativeTrustedRegisteredContext

    if type(context) is not NativeTrustedRegisteredContext or context.publication_eligible is not False:
        _fail()
    registration = _parse(context.registration_json, _MAX)
    handoff = _parse(context.handoff_json, _MAX)
    deadline = _parse(context.deadline_json, _MAX)
    for pin in (context.registration_file_identity, context.handoff_file_identity):
        if (type(pin) is not tuple or len(pin) != 6
                or any(type(v) is not int or v < 0 for v in pin[1:])):
            _fail()
        _digest(pin[0])
    if (context.registration_file_identity[0] != hashlib.sha256(context.registration_json).hexdigest()
            or context.handoff_file_identity[0] != hashlib.sha256(context.handoff_json).hexdigest()
            or type(context.recovery_lock_identity) is not tuple
            or len(context.recovery_lock_identity) != 2
            or any(type(v) is not int or v < 0 for v in context.recovery_lock_identity)):
        _fail()
    return {
        **{name: _digest(getattr(context, name)) for name in (
            "launch_sha256", "intent_sha256", "attestation_sha256",
            "bootstrap_descriptor_sha256", "bootstrap_artifact_sha256",
        )},
        "registration_sha256": _digest(registration.get("registration_sha256")),
        "handoff_sha256": _digest(handoff.get("handoff_sha256")),
        "deadline_sha256": _digest(deadline.get("deadline_sha256")),
        "deadline_binding_bytes_sha256": hashlib.sha256(context.deadline_binding_json).hexdigest(),
        "registration_file_identity": list(context.registration_file_identity),
        "handoff_file_identity": list(context.handoff_file_identity),
        "recovery_lock_identity": list(context.recovery_lock_identity),
    }


def _native(context) -> dict:
    try:
        return _native_projection(context)
    except NativeGuardianRegistrationError:
        raise
    except Exception as exc:  # Malformed detached data never leaks a parser error.
        raise NativeGuardianRegistrationError(
            "native_guardian_registration_binding_invalid",
        ) from exc


@dataclass(frozen=True, slots=True)
class GuardianNativeRegistrationReference:
    """Original creator-delivered reference; trusted caller retains it separately."""

    canonical_bytes: bytes = field(repr=False)


def inspect_registered_native_guardian_custody(reference: GuardianNativeRegistrationReference) -> dict:
    """Read original private pairing and independent event; never launch or repair.

    This proves a recorded pairing, not current native registration freshness or
    group cleanup. It cannot discover an original reference from current files.
    """
    report = {"state": "unavailable", "native_registration_binding_observed": False,
              "native_success": False, "publication_authority": False,
              "cleanup_authority": False, "production_admission": False,
              "cleanup_status": "unknown", "signal_result_known": False}
    chain = None
    try:
        if type(reference) is not GuardianNativeRegistrationReference:
            _fail()
        baseline = reference.canonical_bytes
        value = _parse(baseline, _MAX)
        if (set(value) != {"protocol", "directory", "receiver_reference", "native_binding", "binding_identity"}
                or value["protocol"] != _PROTOCOL or _json(value) != baseline
                or type(value["native_binding"]) is not dict
                or value["native_binding"].get("protocol") != _PROTOCOL):
            _fail()
        chain = DirectoryChain(_path(value["directory"]), "native_guardian_registration_directory_drift")
        receiver = GuardianCustodyReference(_json(value["receiver_reference"]))
        original_pins = value["receiver_reference"]["directory_chain"]
        if _private_chain(chain) != original_pins:
            _fail()
        binding = value["native_binding"]
        if (set(binding) != {"protocol", "receiver_reference_sha256", "native"}
                or binding["receiver_reference_sha256"] != hashlib.sha256(receiver.canonical_bytes).hexdigest()
                or type(binding["native"]) is not dict
                or binding["native"].get("launch_sha256") != value["receiver_reference"].get("launch_sha256")
                or binding["native"].get("bootstrap_artifact_sha256") != value["receiver_reference"].get("guardian_sha256")):
            _fail()
        raw = _json(binding)
        _bound(chain, raw, value["binding_identity"])
        result = inspect_native_guardian_custody(receiver, original_directory_chain=chain)
        if result["state"] not in {"registered", "watcher_exit_observed"}:
            _fail()
        _bound(chain, raw, value["binding_identity"])
        if reference.canonical_bytes != baseline or _private_chain(chain) != original_pins:
            _fail()
        return {**result, "native_registration_binding_observed": True,
                "registration_sha256": binding["native"]["registration_sha256"]}
    except Exception:  # noqa: BLE001 - partial/current-file substitution remains unavailable
        return report
    finally:
        if chain is not None:
            chain.close()


class NativeGuardianCustodyRequest:
    """Trusted opt-in originals for one native attempt, never a channel DTO.

    The caller owns the sealed image and held directory lifetimes. Its original
    registered observer can independently retain ``reference`` before the gate.
    Missing independent retention remains a deployment gap, never auto-attested.
    """

    def __init__(self, *, receiver: LinuxSealedExecutable, original_directory: Path,
                 original_directory_chain: DirectoryChain, original_context_sha256: str,
                 original_launch_sha256: str, original_profile_sha256: str) -> None:
        if type(receiver) is not LinuxSealedExecutable or type(original_directory_chain) is not DirectoryChain:
            _fail()
        self._receiver = receiver
        self._chain = original_directory_chain
        self._directory = _path(str(original_directory))
        if tuple(link[1] for link in self._chain.links) != self._directory.parts[1:]:
            _fail()
        self._pins = _private_chain(self._chain)
        self._digests = tuple(_digest(value) for value in (
            original_context_sha256, original_launch_sha256, original_profile_sha256,
        ))
        self._attempted = False
        self._binding_attempted = False
        self._receiver_reference: GuardianCustodyReference | None = None
        self._receiver_bytes: bytes | None = None
        self._reference: GuardianNativeRegistrationReference | None = None
        self._reference_bytes: bytes | None = None
        self._deadline = 0.0
        self._monotonic: Callable[[], float] = time.monotonic

    @property
    def reference(self) -> GuardianNativeRegistrationReference | None:
        return self._reference

    def check_installed_assignment(
        self, *, original_context_sha256: str, original_launch_sha256: str,
        original_profile_sha256: str,
    ) -> Path:
        """Trusted bridge only: compare originals without creating/replaying a launch.

        The returned original private directory is for installation-separation
        checks, never a path selected by a public worker packet.
        """
        try:
            expected = tuple(_digest(value) for value in (
                original_context_sha256, original_launch_sha256, original_profile_sha256,
            ))
            if expected != self._digests or _private_chain(self._chain) != self._pins:
                _fail()
            _elf(self._receiver)
            return self._directory
        except NativeGuardianRegistrationError:
            raise
        except Exception as exc:
            raise NativeGuardianRegistrationError(
                "native_guardian_registration_binding_invalid",
            ) from exc

    def check_launch(self, launch_sha256: str) -> None:
        try:
            if (self._attempted or _digest(launch_sha256) != self._digests[1]
                    or _private_chain(self._chain) != self._pins):
                _fail()
            _elf(self._receiver)
        except NativeGuardianRegistrationError:
            raise
        except Exception as exc:  # Original image/chain drift uses the fixed attempt contract.
            raise NativeGuardianRegistrationError(
                "native_guardian_registration_binding_invalid",
            ) from exc

    def start_original(self, *, bootstrap: LinuxSealedExecutable, launch_sha256: str, **arguments):
        self.check_launch(launch_sha256)
        self._attempted = True
        self._deadline, self._monotonic = arguments["deadline"], arguments["monotonic"]
        owner = start_durable_native_guardian(
            receiver=self._receiver, bootstrap=bootstrap, original_directory_chain=self._chain,
            original_context_sha256=self._digests[0], original_launch_sha256=self._digests[1],
            original_profile_sha256=self._digests[2], **arguments,
        )
        self._receiver_reference = owner.reference
        self._receiver_bytes = owner.reference.canonical_bytes
        return owner

    def _check(self, owner: DurableNativeGuardianOwner) -> None:
        _remaining(self._deadline, self._monotonic, "native_guardian_registration_deadline_expired")
        try:
            pins = _private_chain(self._chain)
        except Exception as exc:  # Directory drift must not escape the original attempt contract.
            raise NativeGuardianRegistrationError(
                "native_guardian_registration_binding_invalid",
            ) from exc
        if (type(owner) is not DurableNativeGuardianOwner or self._receiver_reference is None
                or owner.reference is not self._receiver_reference
                or owner.reference.canonical_bytes != self._receiver_bytes
                or pins != self._pins):
            _fail()
        result = inspect_native_guardian_custody(self._receiver_reference, original_directory_chain=self._chain)
        if result["state"] != "registered":
            _fail()
        _remaining(self._deadline, self._monotonic, "native_guardian_registration_deadline_expired")

    def bind_original_registration(self, context, owner: DurableNativeGuardianOwner) -> None:
        """Create once from actual pre-gate publisher pins; retain every partial."""
        if self._binding_attempted:
            _fail()
        self._binding_attempted = True
        self._check(owner)
        if self._reference is not None:
            _fail()
        receiver_raw = self._receiver_reference.canonical_bytes
        receiver = _parse(receiver_raw, _MAX)
        native = _native(context)
        deadline = _parse(context.deadline_json, _MAX)
        if (type(deadline.get("deadline_monotonic")) not in {int, float}
                or deadline["deadline_monotonic"] != self._deadline
                or native["launch_sha256"] != self._digests[1]
                or native["bootstrap_artifact_sha256"] != receiver["guardian_sha256"]):
            _fail()
        value = {"protocol": _PROTOCOL, "receiver_reference_sha256": hashlib.sha256(receiver_raw).hexdigest(),
                 "native": native}
        raw = _json(value)
        if len(raw) > _MAX:
            _fail()
        fd = os.open(_NAME, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=self._chain.fd)
        try:
            created = os.fstat(fd)
            offset = 0
            while offset < len(raw):
                self._check(owner)
                count = os.write(fd, raw[offset:])
                if count <= 0:
                    _fail()
                offset += count
                self._check(owner)
            os.fsync(fd)
            self._check(owner)
            written = os.fstat(fd)
            if ((written.st_dev, written.st_ino) != (created.st_dev, created.st_ino)
                    or not _record_shape(written)
                    or written.st_size != len(raw)):
                _fail()
            pin = _pin(written, raw)
            _bound(self._chain, raw, pin)
            os.fsync(self._chain.fd)
            self._check(owner)
            # Keep the actual creation descriptor through directory fsync and
            # readback. A pathname reopen never establishes the original pin.
            if _pin(os.fstat(fd), raw) != pin:
                _fail()
            _bound(self._chain, raw, pin)
            reference = GuardianNativeRegistrationReference(_json({
                "protocol": _PROTOCOL, "directory": str(self._directory),
                "receiver_reference": receiver, "native_binding": value, "binding_identity": list(pin),
            }))
            if inspect_registered_native_guardian_custody(reference)["state"] != "registered":
                _fail()
            self._check(owner)
            self._reference = reference
            self._reference_bytes = reference.canonical_bytes
        finally:
            os.close(fd)

    def check_registered(self, context, owner: DurableNativeGuardianOwner) -> None:
        self._check(owner)
        if (self._reference is None or self._reference.canonical_bytes != self._reference_bytes
                or _parse(self._reference_bytes, _MAX)["native_binding"]["native"] != _native(context)
                or inspect_registered_native_guardian_custody(self._reference)["state"] != "registered"):
            _fail()
        self._check(owner)
