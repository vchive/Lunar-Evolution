"""Explicit root-installed no-secret account transition/access observations.

Only trusted installation code supplies the original probe and account anchors.
The held static helper executes after the child drops credentials. This is an
active diagnostic, not a candidate, namespace/runtime acceptance or admission.
"""
from __future__ import annotations

import errno
import hashlib
import math
import os
import select
import struct
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import external_worker_account_preflight as preflight
from .static_python_elf import StaticPythonELFError, inspect_static_python_elf

_SOURCE = Path(__file__).with_suffix(".c")
_RESULT = struct.Struct("<8s14I")
_INPUT = struct.Struct("<8sQ3I")
_MAX_HELPER = 8 * 1024 * 1024
_MAX_SOURCE = 32 * 1024
_POPEN = subprocess.Popen


@dataclass(frozen=True, slots=True)
class InstalledAccountProbeAnchor:
    """Independent trusted installation pins, never current-state capture.

    The installer must have reviewed the exact helper/source relationship. This
    object and matching static ELF bytes are not accepted build-input custody.
    No helper path, command, UID or acceptance flag comes from a worker channel.
    """

    account_anchor: preflight.InstalledAccountProfileAnchor = field(repr=False)
    helper_sha256: str
    source_sha256: str


class _ProbeRefused(ValueError):
    pass


def _refuse(code: str) -> None:
    raise _ProbeRefused(code)


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if not math.isfinite(remaining) or remaining <= 0:
        _refuse("original_deadline_expired")
    return remaining


def _source_digest() -> str:
    fd = os.open(_SOURCE, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        original = preflight._identity(os.fstat(fd), directory=False)
        preflight._pin(original, directory=False)
        if not 0 < original["size"] <= _MAX_SOURCE:
            _refuse("probe_source_refused")
        raw = os.read(fd, _MAX_SOURCE + 1)
        named = preflight._identity(os.stat(_SOURCE, follow_symlinks=False), directory=False)
        if (len(raw) != original["size"] or named != original
                or preflight._identity(os.fstat(fd), directory=False) != original):
            _refuse("probe_source_drift")
        return hashlib.sha256(raw).hexdigest()
    finally:
        os.close(fd)


def _report(status: str, code: str, *, profile_sha256: str | None = None,
            executed: bool = False, observed: bool = False) -> dict:
    return {
        "schema": "lunar-installed-account-probe-v1", "status": status, "codes": [code],
        "profile_sha256": profile_sha256, "probe_executed": executed,
        "account_transition_observed": observed, "protected_access_denied": observed,
        "supplementary_groups_cleared": observed, "secret_contents_read": False,
        "candidate_executed": False, "namespace_operations_accepted": False,
        "native_runtime_accepted": False, "isolation_accepted": False,
        "production_admission": False, "online_publication": False,
        "remote_cleanup_authority": False,
    }


def _exchange(process: subprocess.Popen, body: bytes, deadline: float) -> bytes:
    """Bound pipe bytes and every wait by the original absolute deadline.

    This is a pipe protocol, not durable evidence or a hard bound on filesystem
    operations/Popen. It never supplies guardian cleanup or restart authority.
    """
    assert process.stdin is not None and process.stdout is not None
    write_fd, read_fd = process.stdin.fileno(), process.stdout.fileno()
    os.set_blocking(write_fd, False)
    os.set_blocking(read_fd, False)
    waiter = select.poll()
    waiter.register(write_fd, select.POLLOUT)
    waiter.register(read_fd, select.POLLIN)
    offset, output = 0, bytearray()
    complete = False
    try:
        while not complete:
            timeout = math.ceil(min(_remaining(deadline), 2_147_483.647) * 1000)
            events = waiter.poll(timeout)
            _remaining(deadline)
            if not events:
                continue
            for descriptor, flags in events:
                if flags & (select.POLLERR | select.POLLNVAL):
                    _refuse("probe_pipe_refused")
                if descriptor == write_fd:
                    if flags & select.POLLOUT:
                        try:
                            offset += os.write(write_fd, body[offset:])
                        except BlockingIOError:
                            continue
                        if offset == len(body):
                            waiter.unregister(write_fd)
                            process.stdin.close()
                    elif flags & select.POLLHUP:
                        _refuse("probe_input_incomplete")
                elif descriptor == read_fd and flags & (select.POLLIN | select.POLLHUP):
                    try:
                        chunk = os.read(read_fd, _RESULT.size + 1 - len(output))
                    except BlockingIOError:
                        continue
                    output.extend(chunk)
                    if len(output) > _RESULT.size:
                        _refuse("probe_output_bounds_refused")
                    if not chunk:
                        complete = True
                        break
        if offset != len(body):
            _refuse("probe_input_incomplete")
        return bytes(output)
    finally:
        if not process.stdin.closed:
            process.stdin.close()
        process.stdout.close()


def _validate_result(raw: bytes, candidate: dict) -> None:
    if type(raw) is not bytes or len(raw) != _RESULT.size:
        _refuse("probe_output_invalid")
    magic, *values = _RESULT.unpack(raw)
    if magic != b"LAPROB1\0":
        _refuse("probe_output_invalid")
    uid, euid, suid, gid, egid, sgid, groups, nnp, *rest = values
    if ((uid, euid, suid) != (candidate["uid"],) * 3
            or (gid, egid, sgid) != (candidate["gid"],) * 3
            or groups != 0 or nnp != 1 or rest[3:] != [1, 1, 1]):
        _refuse("probe_transition_refused")
    if any(code not in {errno.EACCES, errno.EPERM} for code in rest[:3]):
        _refuse("protected_access_not_denied")


def inspect_installed_account_transition(
    installation: InstalledAccountProbeAnchor, *, original_deadline: float,
) -> dict:
    """Run only the installed fixed no-secret helper under a distinct identity.

    This API does not request privileges. It refuses unless the calling wrapper
    is already real/effective/saved root and independently installed account pins
    match. No candidate, key body, config body or state body is consumed.
    """
    if sys.platform != "linux":
        return _report("unsupported", "platform_unsupported")
    if (type(original_deadline) not in {int, float} or not 0 < original_deadline < 2**64
            or not math.isfinite(original_deadline)
            or original_deadline <= time.monotonic()
            or original_deadline * 1_000_000_000 >= 2**64):
        return _report("refused", "original_deadline_invalid")
    if (not hasattr(os, "getresuid") or os.getresuid() != (0, 0, 0)):
        return _report("unsupported", "installed_root_transition_unavailable")
    opened: list[preflight._Entry] = []
    process = None
    executed = False
    digest = None
    try:
        _remaining(original_deadline)
        if (type(installation) is not InstalledAccountProbeAnchor
                or type(installation.account_anchor) is not preflight.InstalledAccountProfileAnchor):
            _refuse("installed_probe_anchor_required")
        for value in (installation.helper_sha256, installation.source_sha256):
            preflight._digest(value)
        if _source_digest() != installation.source_sha256:
            _refuse("probe_source_drift")
        baseline = preflight.inspect_account_isolation(installation.account_anchor)
        if (baseline["status"] != "unknown"
                or "installed_identity_facts_observed" not in baseline["codes"]
                or not baseline["acl_and_file_capability_metadata_observed"]):
            _refuse("installed_preflight_unavailable")
        reference, chain, original, _ = preflight._anchor(installation.account_anchor.canonical_bytes)
        profile_file = preflight._Entry(reference["profile_path"], directory=False,
                                       chain_pins=chain, original=original)
        opened.append(profile_file)
        raw = profile_file.read(preflight._MAX_PROFILE)
        digest = hashlib.sha256(raw).hexdigest()
        if digest != reference["profile_sha256"] or digest != baseline["profile_sha256"]:
            _refuse("installed_profile_drift")
        profile = preflight._parse(raw)
        wrapper = preflight._account(profile["accounts"]["wrapper"])
        candidate = preflight._account(profile["accounts"]["candidate"])
        if wrapper["uid"] != 0 or candidate["uid"] in {0, wrapper["uid"]}:
            _refuse("root_installed_profile_required")
        entries = {}
        for role in sorted(preflight._ROLES):
            spec = profile["entries"][role]
            entry = preflight._Entry(spec["path"], directory=role == "state",
                                     chain_pins=spec["chain"], original=spec["identity"])
            opened.append(entry)
            entries[role] = entry
        helper = entries["helper"]
        if (helper.original["uid"] != 0 or helper.original["mode"] & 0o7022
                or not helper.original["mode"] & 0o001):
            _refuse("probe_helper_permissions_refused")
        image = helper.read(_MAX_HELPER)
        if (hashlib.sha256(image).hexdigest() != installation.helper_sha256
                or installation.helper_sha256 != profile["entries"]["helper"]["sha256"]):
            _refuse("probe_helper_digest_drift")
        elf = inspect_static_python_elf(image)
        if elf.dynamic_table_count:
            _refuse("probe_static_helper_required")
        paths = [profile["entries"][role]["path"].encode("utf-8")
                 for role in ("key", "config", "state")]
        if any(len(path) > 4096 for path in paths):
            _refuse("probe_path_bounds_refused")
        deadline_ns = int(original_deadline * 1_000_000_000)
        body = _INPUT.pack(b"LAPIN1\0\0", deadline_ns, *(len(path) for path in paths)) + b"".join(paths)
        for entry in opened:
            entry.check()
        _remaining(original_deadline)
        # exec resolves the original held helper inode, not its replaceable name.
        # No protected entry FD, environment, PATH, shell or interpreter crosses.
        process = _POPEN(
            ("lunar-account-probe", "--fixed-no-secret-probe-v1", str(deadline_ns)),
            executable=f"/proc/self/fd/{helper.fd}", stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0,
            close_fds=True, pass_fds=(helper.fd,), cwd="/", env={},
            user=candidate["uid"], group=candidate["gid"], extra_groups=(),
            umask=0o077, start_new_session=True,
        )
        executed = True
        output = _exchange(process, body, original_deadline)
        if process.wait(timeout=_remaining(original_deadline)) != 0:
            _refuse("probe_exit_refused")
        _remaining(original_deadline)
        _validate_result(output, candidate)
        for entry in opened:
            entry.check()
        if _source_digest() != installation.source_sha256:
            _refuse("probe_source_drift")
        final = preflight.inspect_account_isolation(installation.account_anchor)
        if final != baseline:
            _refuse("installed_preflight_drift")
        _remaining(original_deadline)
        return _report("observed", "fixed_account_transition_access_observed",
                       profile_sha256=digest, executed=True, observed=True)
    except _ProbeRefused as exc:
        return _report("refused", str(exc), profile_sha256=digest, executed=executed)
    except preflight.AccountPreflightError:
        return _report("refused", "installed_identity_refused", profile_sha256=digest,
                       executed=executed)
    except StaticPythonELFError:
        return _report("refused", "probe_static_helper_required", profile_sha256=digest,
                       executed=executed)
    except (OSError, ValueError, subprocess.SubprocessError):
        return _report("unknown", "probe_observation_unavailable", profile_sha256=digest,
                       executed=executed)
    finally:
        if process is not None:
            try:
                if process.poll() is None:
                    process.kill()  # Exact original child, not a durable PID lookup.
                process.wait(timeout=max(0, original_deadline - time.monotonic()))
            except (OSError, subprocess.SubprocessError):
                pass  # No renewed cleanup grace or cleanup authority.
            for stream in (process.stdin, process.stdout):
                if stream is not None and not stream.closed:
                    stream.close()
        for entry in reversed(opened):
            entry.close()
