"""Explicit same-UID guardian fault observations; never production admission.

Uses installed native images and the existing original-reference inspector. No
credential, attestation, account transition, protocol or default CLI is added.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import select
import signal
import stat
import subprocess
import sys
import time
from contextlib import ExitStack
from pathlib import Path

_SCHEMA = "lunar-local-guardian-fault-fixture-v1"
_FAULTS = ("controller-exit", "receiver-kill")
_TARGET = Path("/usr/bin/sleep")
_UUTILS_TARGET = Path("/usr/lib/cargo/bin/coreutils/sleep")
_NANOSLEEP_PROFILE = "compiled-nanosleep-fixture-v1"
_NANOSLEEP_SOURCE = Path(__file__).with_name("native_guardian_nanosleep_fixture.c")
_NANOSLEEP_SOURCE_BYTES = 691
_NANOSLEEP_SOURCE_SHA256 = "a4620a7d6f02bf8f12e7c544164aff2f25099086bd3ae3306d03109ea96550e4"
_TARGET_PROFILES = ("system-sleep", "ubuntu-uutils-sleep", _NANOSLEEP_PROFILE)
_ERROR_REASONS = frozenset({
    "original_fixture_deadline", "original_reference_missing", "original_reference_invalid",
    "original_reference_oversize", "fixture_file_path_invalid", "fixture_file_invalid",
    "fixture_file_drift", "installed_fixture_root_owner_required", "installed_fixture_elf_required",
    "fixture_target_profile_invalid", "fixture_target_profile_path_invalid",
    "installed_fixture_image_drift", "fixture_sleep_snapshot_invalid", "fixture_tool_drift",
    "fixture_target_profile_sealed_incompatible", "fixture_target_profile_configuration_invalid",
    "fixture_nanosleep_source_invalid", "fixture_nanosleep_image_digest_mismatch",
})
_HARD_EXIT = 79
_MAX_FILE = 32 * 1024 * 1024
_FALSE = ("native_success", "production_admission", "publication_authority",
          "cleanup_authority", "whole_group_cleanup_verified", "isolation_accepted",
          "immutable_custody_verified", "signal_result_known")


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _remaining(deadline_ns):
    remaining = (deadline_ns - time.monotonic_ns()) / 1e9
    if remaining <= 0:
        raise TimeoutError("original_fixture_deadline")
    return remaining


def _budget(value):
    if type(value) is bool:
        raise argparse.ArgumentTypeError("budget must be numeric")
    number = float(value)
    if not math.isfinite(number) or not 5 <= number <= 60:
        raise argparse.ArgumentTypeError("budget must be finite and between 5 and 60 seconds")
    return number


def _close_fd(fd, primary, operation):
    """Close once; preserve an earlier read/write/fsync failure and both facts."""
    try:
        os.close(fd)
    except OSError as exc:
        if primary is None:
            raise
        errors = list(getattr(primary, "_fixture_close_errors", ()))
        errors.append({"operation": operation, "error_kind": type(exc).__name__,
                       "error_errno": exc.errno})
        primary._fixture_close_errors = errors


def _pin(path, *, elf=False, root_owned=False, include_bytes=False):
    """Read only explicit fixture files, refusing links, devices and large files."""
    path = Path(path)
    if not path.is_absolute() or path.name == ".env":
        raise ValueError("fixture_file_path_invalid")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    primary = None
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or not 0 <= before.st_size <= _MAX_FILE:
            raise ValueError("fixture_file_invalid")
        if root_owned and before.st_uid != 0:
            raise ValueError("installed_fixture_root_owner_required")
        if elf and (not before.st_mode & 0o111 or os.pread(fd, 4, 0) != b"\x7fELF"):
            raise ValueError("installed_fixture_elf_required")
        raw = bytearray()
        while len(raw) <= before.st_size:
            chunk = os.read(fd, min(65536, before.st_size + 1 - len(raw)))
            if not chunk:
                break
            raw.extend(chunk)
        after = os.fstat(fd)
        named = os.stat(path, follow_symlinks=False)
        fields = ("st_dev", "st_ino", "st_mode", "st_uid", "st_gid", "st_nlink",
                  "st_size", "st_mtime_ns", "st_ctime_ns")
        if (len(raw) != before.st_size
                or any(getattr(before, key) != getattr(after, key)
                       or getattr(before, key) != getattr(named, key) for key in fields)):
            raise ValueError("fixture_file_drift")
        identity = {"sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw),
                    "device": before.st_dev, "inode": before.st_ino,
                    "mtime_ns": before.st_mtime_ns, "ctime_ns": before.st_ctime_ns}
        return (identity, bytes(raw)) if include_bytes else identity
    except BaseException as exc:
        primary = exc
        raise
    finally:
        _close_fd(fd, primary, "pin.close")


def _create(path, raw, *, mode=0o600):
    """Preserve partial failures: never overwrite, unlink or retry a publication."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, mode)
    primary = None
    try:
        view = memoryview(raw)
        while view:
            count = os.write(fd, view)
            if count <= 0:
                raise OSError("fixture_write_incomplete")
            view = view[count:]
        os.fsync(fd)
    except BaseException as exc:
        primary = exc
        raise
    finally:
        _close_fd(fd, primary, "create.close")
    parent = os.open(Path(path).parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    primary = None
    try:
        os.fsync(parent)
    except BaseException as exc:
        primary = exc
        raise
    finally:
        _close_fd(parent, primary, "create.parent.close")


def _save(root, name, value):
    _create(root / name, _wire(value) + b"\n")


def _target_path(profile, *, fixture_target=None, fixture_target_sha256=None):
    """Select an explicit trusted-local image; never resolve or fall back."""
    if type(profile) is not str or profile not in _TARGET_PROFILES:
        raise ValueError("fixture_target_profile_invalid")
    if profile == "ubuntu-uutils-sleep":
        # An original sealed-image diagnostic observed uutils reject its memfd
        # executable name even with argv[0]=sleep. Never disable that self-check.
        raise ValueError("fixture_target_profile_sealed_incompatible")
    if profile == _NANOSLEEP_PROFILE:
        if (not isinstance(fixture_target, (str, Path))
                or not Path(fixture_target).is_absolute()
                or type(fixture_target_sha256) is not str or len(fixture_target_sha256) != 64
                or any(value not in "0123456789abcdef" for value in fixture_target_sha256)):
            raise ValueError("fixture_target_profile_configuration_invalid")
        return Path(fixture_target)
    if fixture_target is not None or fixture_target_sha256 is not None:
        raise ValueError("fixture_target_profile_configuration_invalid")
    return _TARGET


def _nanosleep_source_pin():
    identity = _pin(_NANOSLEEP_SOURCE)
    if (identity["size"] != _NANOSLEEP_SOURCE_BYTES
            or identity["sha256"] != _NANOSLEEP_SOURCE_SHA256):
        raise ValueError("fixture_nanosleep_source_invalid")
    return identity


def _snapshot_sleep_image(source, identity, destination, *, root_owned, deadline_ns):
    """Copy the fixed source's held, verified bytes into one fresh owned inode."""
    _remaining(deadline_ns)
    observed, raw = _pin(source, elf=True, root_owned=root_owned, include_bytes=True)
    if observed != identity:
        raise ValueError("installed_fixture_image_drift")
    _remaining(deadline_ns)
    _create(destination, raw, mode=0o700)
    _remaining(deadline_ns)
    copied = _pin(destination, elf=True)
    if (copied["sha256"] != identity["sha256"] or copied["size"] != identity["size"]
            or (copied["device"], copied["inode"]) == (identity["device"], identity["inode"])):
        raise ValueError("fixture_sleep_snapshot_invalid")
    _remaining(deadline_ns)
    return copied


def _start_target(target, deadline_ns, *, target_profile="system-sleep"):
    if target_profile not in {"system-sleep", _NANOSLEEP_PROFILE}:
        raise ValueError("fixture_target_profile_sealed_incompatible")
    name = "lunar-guardian-nanosleep-fixture" if target_profile == _NANOSLEEP_PROFILE else "sleep"
    # Exactly one original remaining duration, never a caller program/argv.
    return subprocess.Popen(
        [name, str(_remaining(deadline_ns))], executable=target.executable,
        pass_fds=(target.fd,), close_fds=True, start_new_session=True, cwd="/",
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env={"PATH": os.defpath, "LANG": "C"},
    )


def _product():
    # This tool intentionally observes this checkout's existing implementation.
    source = str(Path(__file__).resolve().parents[1] / "src")
    if source not in sys.path:
        sys.path.insert(0, source)
    from lunar_evolution._candidate_workspace_io import DirectoryChain
    from lunar_evolution.linux_executable_binding import sealed_linux_executable
    from lunar_evolution.native_guardian_custody import (
        GuardianCustodyReference,
        inspect_native_guardian_custody,
        start_durable_native_guardian,
    )
    return (DirectoryChain, sealed_linux_executable, GuardianCustodyReference,
            inspect_native_guardian_custody, start_durable_native_guardian)


def _request(path):
    value = json.loads(Path(path).read_bytes())
    if (value["schema"] != _SCHEMA or value["fault"] not in _FAULTS
            or value["uid"] != os.geteuid()
            or value["deadline_monotonic_ns"] - value["origin_monotonic_ns"]
            != value["budget_nanoseconds"]
            or not 5_000_000_000 <= value["budget_nanoseconds"] <= 60_000_000_000):
        raise ValueError("fixture_request_invalid")
    _remaining(value["deadline_monotonic_ns"])
    profile = value.get("target_profile")
    source = value.get("target_source")
    target = value["images"]["target"]
    selected = _target_path(profile, fixture_target=value.get("fixture_target"),
                            fixture_target_sha256=value.get("fixture_target_sha256"))
    if (type(source) is not dict or source.get("path") != str(selected)
            or target["path"] != str(Path(value["output"]) / "sleep-image")):
        raise ValueError("fixture_target_profile_path_invalid")
    if profile == _NANOSLEEP_PROFILE:
        fixed_source = value.get("fixture_source")
        if (type(fixed_source) is not dict
                or set(fixed_source) != {"path", "identity", "build_authenticity_verified"}
                or fixed_source["path"] != str(_NANOSLEEP_SOURCE)
                or fixed_source["identity"] != _nanosleep_source_pin()
                or fixed_source["build_authenticity_verified"] is not False):
            raise ValueError("fixture_nanosleep_source_invalid")
        if source["identity"]["sha256"] != value["fixture_target_sha256"]:
            raise ValueError("fixture_nanosleep_image_digest_mismatch")
    if _pin(Path(source["path"]), elf=True,
            root_owned=profile == "ubuntu-uutils-sleep") != source["identity"]:
        raise ValueError("installed_fixture_image_drift")
    for item in value["images"].values():
        if _pin(Path(item["path"]), elf=True) != item["identity"]:
            raise ValueError("installed_fixture_image_drift")
    if (any(target["identity"][key] != source["identity"][key] for key in ("sha256", "size"))
            or (target["identity"]["device"], target["identity"]["inode"])
            == (source["identity"]["device"], source["identity"]["inode"])):
        raise ValueError("fixture_sleep_snapshot_invalid")
    if _pin(Path(__file__).resolve()) != value["tool_identity"]:
        raise ValueError("fixture_tool_drift")
    return value


def _startup_failure(root, error, process, owner, deadline_ns):
    """Retain exact child exit observations before teardown can change them."""
    observation = {
        "phase": "guardian-readiness", "deadline_monotonic_ns": deadline_ns,
        "observed_monotonic_ns": time.monotonic_ns(), "retries": 0,
        "target_returncode": None, "receiver_returncode": None,
        "error_kind": type(error).__name__, **{key: False for key in _FALSE},
    }
    for name, child in (("target", process), ("receiver", getattr(owner, "_watcher", None))):
        if child is not None:
            try:
                observation[name + "_returncode"] = child.poll()
            except (OSError, ValueError) as exc:
                observation[name + "_observation_error"] = type(exc).__name__
    try:
        _save(root, "controller-startup-failure.json", observation)
    except (OSError, ValueError) as exc:
        # Diagnostic persistence must not replace the original startup error.
        error.add_note("fixture_startup_observation_persistence_" + type(exc).__name__)


def _controller(request_path):
    request = _request(request_path)
    chain_type, sealed, _, _, start = _product()
    deadline_ns = request["deadline_monotonic_ns"]
    deadline = deadline_ns / 1e9
    process = owner = None
    cleanup_attempted = False
    descriptors = set()

    def pipe():
        ends = os.pipe()
        descriptors.update(ends)
        return ends

    def close(fd):
        if fd in descriptors:
            descriptors.remove(fd)
            os.close(fd)

    try:
        with ExitStack() as stack:
            chain = chain_type(Path(request["output"]) / "custody", "fixture_custody_drift")
            stack.callback(chain.close)
            images = {}
            for role, item in request["images"].items():
                images[role] = stack.enter_context(sealed(
                    Path(item["path"]), item["identity"], deadline=deadline,
                ))
            life_r, life_w = pipe()
            finish_r, _finish_w = pipe()
            ack_r, ack_w = pipe()
            target = images["target"]
            # The fixed inert command receives only the original remaining
            # duration; this does not promise a hard OS scheduling time bound.
            process = _start_target(target, deadline_ns, target_profile=request["target_profile"])
            context = hashlib.sha256(_wire({
                "schema": _SCHEMA, "fault": request["fault"], "uid": request["uid"],
                "origin_monotonic_ns": request["origin_monotonic_ns"],
                "deadline_monotonic_ns": deadline_ns,
            })).hexdigest()
            try:
                owner = start(
                    process=process, receiver=images["receiver"], bootstrap=images["guardian"],
                    lifeline_fd=life_r, finish_fd=finish_r, ack_fd=ack_w, ack_read_fd=ack_r,
                    original_directory_chain=chain, original_context_sha256=context,
                    original_launch_sha256=hashlib.sha256(_wire(request["images"])).hexdigest(),
                    original_profile_sha256=hashlib.sha256(_SCHEMA.encode()).hexdigest(),
                    deadline=deadline, deadline_ns=deadline_ns,
                )
            except Exception as exc:
                owner = getattr(exc, "guardian_owner", None)
                _startup_failure(Path(request["output"]), exc, process, owner, deadline_ns)
                raise
            for fd in (life_r, finish_r, ack_w, ack_r):
                close(fd)
            # Parent must independently retain these exact original bytes and
            # fsync them before authorizing the one fault. No current-file lookup.
            sys.stdout.buffer.write(owner.reference.canonical_bytes + b"\n")
            sys.stdout.buffer.flush()
            waiter = select.poll()
            waiter.register(sys.stdin.fileno(), select.POLLIN | select.POLLHUP)
            if not waiter.poll(math.ceil(_remaining(deadline_ns) * 1000)):
                raise TimeoutError("original_fixture_deadline")
            _remaining(deadline_ns)
            if os.read(sys.stdin.fileno(), 2) != b"G":
                raise ValueError("fixture_trigger_invalid")
            if request["fault"] == "controller-exit":
                # Deliberately no finally, normal finish, owner cleanup or new
                # guardian. The sole lifeline writer closes on real process death.
                os._exit(_HARD_EXIT)
            owner._watcher.kill()  # exact original owned receiver, never a saved PID
            receiver_status = owner._watcher.wait(timeout=_remaining(deadline_ns))
            close(life_w)
            cleanup_attempted = True
            cleanup = owner.cleanup(timeout=_remaining(deadline_ns))
            process.wait(timeout=_remaining(deadline_ns))
            sys.stdout.buffer.write(_wire({
                "fault": "receiver-kill", "receiver_returncode": receiver_status,
                "cleanup_authority": False, "owner_cleanup_returned": cleanup,
                "deadline_monotonic_ns": deadline_ns, "uid": os.geteuid(),
            }) + b"\n")
            sys.stdout.buffer.flush()
        return 0
    finally:
        for fd in tuple(descriptors):
            close(fd)
        if owner is not None and not cleanup_attempted:
            try:
                owner.cleanup(timeout=_remaining(deadline_ns))
            except (TimeoutError, ValueError, OSError):
                pass
        if process is not None and process.poll() is None:
            process.kill()  # still the exact original live Popen on this path
            try:
                process.wait(timeout=_remaining(deadline_ns))
            except (TimeoutError, subprocess.TimeoutExpired):
                pass


def _inspect(request_path):
    # Inspection receives the caller-retained original reference, never invents
    # one from current custody files. No image reinstallation or owner recovery.
    request = json.loads(Path(request_path).read_bytes())
    _remaining(request["deadline_monotonic_ns"])
    chain_type, _, reference_type, inspect, _ = _product()

    def forbidden(*args, **kwargs):
        raise RuntimeError("readonly_recovery_attempted_effect")

    os.kill = os.killpg = subprocess.Popen = forbidden
    root = Path(request["output"])
    chain = chain_type(root / "custody", "fixture_custody_drift")
    try:
        reference = reference_type((root / "original-reference.json").read_bytes())
        report = inspect(reference, original_directory_chain=chain)
    finally:
        chain.close()
    _remaining(request["deadline_monotonic_ns"])
    sys.stdout.buffer.write(_wire(report) + b"\n")
    return 0


def _custody_pins(root):
    result = {}
    for name in ("guardian-registration-v1.json", "guardian-event-v1.json"):
        path = root / "custody" / name
        try:
            result[name] = _pin(path)
        except FileNotFoundError:
            result[name] = None
    return result


def _read_reference(process, deadline_ns, captured):
    waiter = select.poll()
    waiter.register(process.stdout.fileno(), select.POLLIN | select.POLLHUP)
    while len(captured) <= 32768:
        if not waiter.poll(math.ceil(_remaining(deadline_ns) * 1000)):
            raise TimeoutError("original_fixture_deadline")
        _remaining(deadline_ns)
        chunk = os.read(process.stdout.fileno(), 1)
        if not chunk:
            raise ValueError("original_reference_missing")
        captured.extend(chunk)
        if chunk == b"\n":
            raw = bytes(captured[:-1])
            value = json.loads(raw)
            if _wire(value) != raw or value.get("deadline_monotonic_ns") != deadline_ns:
                raise ValueError("original_reference_invalid")
            return raw
    raise ValueError("original_reference_oversize")


def _classify(fault, controller, recovery, reader_returncode, before, after, child=None):
    result = {"schema": _SCHEMA, "fault": fault, "status": "failed_or_unknown",
              "fixture_observed": False, "retries": 0, "cleanup_status": "unknown",
              "execution_status": "unknown", **{key: False for key in _FALSE}}
    conservative = (type(recovery) is dict
                    and all(recovery.get(key) is False for key in _FALSE)
                    and recovery.get("cleanup_status") == "unknown")
    if not conservative:
        return result
    common = (not controller.get("timed_out", True) and reader_returncode == 0
              and before == after and bool(before.get("guardian-registration-v1.json")))
    if fault == "controller-exit":
        observed = (controller.get("returncode") == _HARD_EXIT
                    and recovery.get("state") == "watcher_exit_observed"
                    and recovery.get("native_d_observed") is False
                    and recovery.get("watcher_exit_kind") == 1
                    and recovery.get("watcher_exit_value") == 78)
    elif fault == "receiver-kill":
        observed = (controller.get("returncode") == 0 and type(child) is dict
                    and child.get("receiver_returncode") == -signal.SIGKILL
                    and child.get("owner_cleanup_returned") is False
                    and recovery.get("state") == "registered")
    else:
        observed = False
    if common and observed:
        result.update(status="fixture_observed", fixture_observed=True)
    return result


def _child_command(mode, request):
    return [sys.executable, "-B", str(Path(__file__).resolve()), mode, str(request)]


def _communicate(process, deadline_ns, *, trigger=None):
    """Drain this exact child only; teardown receives no replacement timeout."""
    try:
        stdout, stderr = process.communicate(input=trigger, timeout=_remaining(deadline_ns))
        return stdout, stderr, {"returncode": process.returncode, "timed_out": False}
    except (TimeoutError, subprocess.TimeoutExpired) as exc:
        stdout = getattr(exc, "stdout", None) or b""
        stderr = getattr(exc, "stderr", None) or b""
        if process.poll() is None:
            process.kill()
        remaining = max(0, (deadline_ns - time.monotonic_ns()) / 1e9)
        try:
            stdout, stderr = process.communicate(timeout=remaining)
        except subprocess.TimeoutExpired as last:
            stdout = last.stdout if last.stdout is not None else stdout
            stderr = last.stderr if last.stderr is not None else stderr
        return stdout, stderr, {"returncode": process.poll(), "timed_out": True}


def _retire_reader(reader, deadline_ns):
    """Retire only this original reader; output already lives in retained files."""
    result = {"returncode": None, "cleanup_status": "unknown", "retries": 0,
              "deadline_monotonic_ns": deadline_ns}
    try:
        if reader.poll() is None:
            reader.kill()
        # This is output/reap settlement for the same process, not a new reader
        # or a renewed execution budget. Zero remains zero after expiry.
        reader.communicate(timeout=max(0, (deadline_ns - time.monotonic_ns()) / 1e9))
    except (OSError, KeyboardInterrupt, subprocess.TimeoutExpired) as exc:
        result["retirement_error_kind"] = type(exc).__name__
    try:
        result["returncode"] = reader.poll()
    except OSError:
        result["returncode"] = None
    return result


def _close_reader_streams(streams):
    """Attempt every original stream once, without masking a primary failure."""
    errors = []
    for stream in streams:
        try:
            os.fsync(stream.fileno())
        except (OSError, ValueError) as exc:
            errors.append({"phase": "fsync", "error_kind": type(exc).__name__})
        finally:
            try:
                stream.close()
            except (OSError, ValueError) as exc:
                errors.append({"phase": "close", "error_kind": type(exc).__name__})
    return errors


def run(*, output, receiver, guardian, fault, budget_seconds, target_profile="system-sleep",
        fixture_target=None, fixture_target_sha256=None):
    """One explicit attempt; retain its full directory even on any failure."""
    if sys.platform != "linux" or not hasattr(os, "pidfd_open"):
        raise ValueError("linux_original_pidfd_required")
    if fault not in _FAULTS:
        raise ValueError("fixture_fault_invalid")
    target_path = _target_path(target_profile, fixture_target=fixture_target,
                               fixture_target_sha256=fixture_target_sha256)
    budget_seconds = _budget(budget_seconds)
    origin_ns = time.monotonic_ns()
    budget_ns = int(budget_seconds * 1e9)
    deadline_ns = origin_ns + budget_ns
    output = Path(output)
    if not output.is_absolute():
        raise ValueError("absolute_create_only_output_required")
    output.mkdir(mode=0o700)  # no exist_ok, cleanup or reuse, including failed runs
    (output / "custody").mkdir(mode=0o700)
    request = {"schema": _SCHEMA, "fault": fault, "uid": os.geteuid(), "output": str(output),
               "target_profile": target_profile,
               "origin_monotonic_ns": origin_ns, "deadline_monotonic_ns": deadline_ns,
               "budget_nanoseconds": budget_ns, "retries": 0,
               "tool_identity": _pin(Path(__file__).resolve()), "images": {}}
    process = None
    prefix = bytearray()
    controller_captured = False
    reader = None
    reader_captured = False
    reader_streams = []
    result = {"schema": _SCHEMA, "fault": fault, "status": "failed_or_unknown",
              "fixture_observed": False, "retries": 0, "cleanup_status": "unknown",
              "execution_status": "unknown", **{key: False for key in _FALSE}}
    environment = {"PATH": os.defpath, "LANG": "C", "PYTHONDONTWRITEBYTECODE": "1"}
    phase = "pin-images"
    try:
        if target_profile == _NANOSLEEP_PROFILE:
            phase = "pin-fixture-source"
            request.update(fixture_target=str(target_path), fixture_target_sha256=fixture_target_sha256,
                           fixture_source={"path": str(_NANOSLEEP_SOURCE), "identity": _nanosleep_source_pin(),
                                           "build_authenticity_verified": False})
        phase = "pin-images"
        for role, path in (("receiver", receiver), ("guardian", guardian)):
            request["images"][role] = {"path": str(path), "identity": _pin(Path(path), elf=True)}
            _remaining(deadline_ns)
        root_owned = target_profile == "ubuntu-uutils-sleep"
        source_identity = _pin(target_path, elf=True, root_owned=root_owned)
        if (target_profile == _NANOSLEEP_PROFILE
                and source_identity["sha256"] != fixture_target_sha256):
            raise ValueError("fixture_nanosleep_image_digest_mismatch")
        request["target_source"] = {"path": str(target_path), "identity": source_identity}
        phase = "snapshot-sleep"
        snapshot = output / "sleep-image"
        request["images"]["target"] = {
            "path": str(snapshot),
            "identity": _snapshot_sleep_image(target_path, source_identity, snapshot,
                                               root_owned=root_owned, deadline_ns=deadline_ns),
        }
        phase = "persist-request"
        _save(output, "request.json", request)
        command = _child_command("_controller", output / "request.json")
        _save(output, "launch.json", {"command": command, "environment_overrides": environment,
                                     "deadline_monotonic_ns": deadline_ns, "retries": 0})
        phase = "controller"
        process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, bufsize=0, env=environment)
        reference = _read_reference(process, deadline_ns, prefix)
        _create(output / "original-reference.json", reference)
        _remaining(deadline_ns)
        stdout, stderr, controller = _communicate(process, deadline_ns, trigger=b"G")
        controller_captured = True
        _create(output / "controller.stdout", bytes(prefix) + stdout)
        _create(output / "controller.stderr", stderr)
        controller.update(deadline_monotonic_ns=deadline_ns, retries=0)
        _save(output, "controller-result.json", controller)
        if controller["timed_out"]:
            raise TimeoutError("original_fixture_deadline")
        phase = "custody-observation"
        if fault == "controller-exit":
            # Reserve reader time inside the SAME original absolute deadline.
            cutoff = deadline_ns - 1_000_000_000
            event = output / "custody/guardian-event-v1.json"
            while time.monotonic_ns() < cutoff:
                if event.stat().st_size:
                    break
                time.sleep(min(0.01, max(0, (cutoff - time.monotonic_ns()) / 1e9)))
        before = _custody_pins(output)
        _save(output, "custody-before-read.json", before)
        _remaining(deadline_ns)
        phase = "reader"
        # Direct create-only files preserve every reader output byte even if
        # communicate raises before returning its pipe buffers to this caller.
        for name in ("read-only-recovery.stdout", "read-only-recovery.stderr"):
            fd = os.open(output / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                         | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
            reader_streams.append(os.fdopen(fd, "wb", buffering=0))
        reader = subprocess.Popen(_child_command("_inspect", output / "request.json"),
                                  stdin=subprocess.DEVNULL, stdout=reader_streams[0],
                                  stderr=reader_streams[1], env=environment)
        _, _, reader_result = _communicate(reader, deadline_ns)
        reader_captured = True
        for stream in reader_streams:
            os.fsync(stream.fileno())
        reader_stdout = (output / "read-only-recovery.stdout").read_bytes()
        reader_result.update(deadline_monotonic_ns=deadline_ns, retries=0)
        _save(output, "read-only-recovery-result.json", reader_result)
        after = _custody_pins(output)
        _save(output, "custody-after-read.json", after)
        recovery = json.loads(reader_stdout) if reader_result["returncode"] == 0 else {}
        child = json.loads(stdout) if stdout.strip() else None
        if reader_result["timed_out"]:
            raise TimeoutError("original_fixture_deadline")
        phase = "classification"
        result = _classify(fault, controller, recovery, reader_result["returncode"],
                           before, after, child)
        _remaining(deadline_ns)
    except (OSError, ValueError, TimeoutError, subprocess.TimeoutExpired) as exc:
        result.update(status="failed_or_unknown", fixture_observed=False)
        result["error_kind"] = type(exc).__name__
        result["error_phase"] = phase
        if exc.args and type(exc.args[0]) is str and exc.args[0] in _ERROR_REASONS:
            result["error_reason"] = exc.args[0]
        if isinstance(exc, OSError):
            result["error_errno"] = exc.errno
        if getattr(exc, "_fixture_close_errors", None):
            result["io_cleanup_errors"] = list(exc._fixture_close_errors)
        result["timed_out"] = isinstance(exc, (TimeoutError, subprocess.TimeoutExpired))
        if isinstance(exc, subprocess.TimeoutExpired):
            _create(output / "timeout.stdout", exc.stdout or b"")
            _create(output / "timeout.stderr", exc.stderr or b"")
    except KeyboardInterrupt as exc:
        result.update(status="failed_or_unknown", fixture_observed=False,
                      error_kind="KeyboardInterrupt", interrupted=True, error_phase=phase)
        if getattr(exc, "_fixture_close_errors", None):
            result["io_cleanup_errors"] = list(exc._fixture_close_errors)
        raise
    finally:
        if reader is not None and not reader_captured:
            retirement = _retire_reader(reader, deadline_ns)
            _save(output, "failed-read-only-recovery-result.json", retirement)
        persistence_errors = _close_reader_streams(reader_streams)
        if persistence_errors:
            result.update(status="failed_or_unknown", fixture_observed=False,
                          reader_output_persistence_errors=persistence_errors)
        if process is not None and not controller_captured:
            # A header failure must also retain partial stdout/stderr, including
            # a controller which already exited before readiness was delivered.
            if process.poll() is None:
                process.kill()
            stdout, stderr, failed = _communicate(process, deadline_ns)
            _create(output / "failed-controller.stdout", bytes(prefix) + stdout)
            _create(output / "failed-controller.stderr", stderr)
            failed.update(deadline_monotonic_ns=deadline_ns, retries=0)
            _save(output, "failed-controller-result.json", failed)
        result.update(origin_monotonic_ns=origin_ns, deadline_monotonic_ns=deadline_ns,
                      target_profile=target_profile,
                      observed_elapsed_seconds=(time.monotonic_ns() - origin_ns) / 1e9,
                      same_uid_fixture=True, account_transition_performed=False,
                      attestation_created=False, model_executed=False,
                      filesystem_hard_time_bound_proven=False)
        _save(output, "result.json", result)
        files = {str(path.relative_to(output)): _pin(path)
                 for path in sorted(output.iterdir()) if path.is_file()}
        files.update({"custody/" + name: item for name, item in _custody_pins(output).items()
                      if item is not None})
        _save(output, "evidence-manifest.json", files)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    explicit = commands.add_parser("run", help="one same-UID inert fault observation")
    explicit.add_argument("--fault", required=True, choices=_FAULTS)
    explicit.add_argument("--receiver", required=True, type=Path)
    explicit.add_argument("--guardian", required=True, type=Path)
    explicit.add_argument("--output", required=True, type=Path)
    explicit.add_argument("--budget-seconds", required=True, type=_budget)
    explicit.add_argument("--target-profile", choices=_TARGET_PROFILES, default="system-sleep")
    explicit.add_argument("--fixture-target", type=Path)
    explicit.add_argument("--fixture-target-sha256")
    for name in ("_controller", "_inspect"):
        commands.add_parser(name, help=argparse.SUPPRESS).add_argument("request", type=Path)
    args = parser.parse_args(argv)
    if args.command == "_controller":
        return _controller(args.request)
    if args.command == "_inspect":
        return _inspect(args.request)
    report = run(output=args.output, receiver=args.receiver, guardian=args.guardian,
                 fault=args.fault, budget_seconds=args.budget_seconds,
                 target_profile=args.target_profile, fixture_target=args.fixture_target,
                 fixture_target_sha256=args.fixture_target_sha256)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["fixture_observed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
