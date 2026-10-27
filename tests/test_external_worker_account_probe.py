"""No privilege requests or account transitions: installed probe software fixtures.

Positive composition uses an in-process pipe peer and mocked numeric root facts.
It is not real account, accepted runtime, namespace or isolation acceptance.
"""
from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_static_python_elf import _image

from lunar_evolution import external_worker_account_preflight as preflight
from lunar_evolution import external_worker_account_probe as probe


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _result(*, uid=60001, gid=61001, errors=None, **changes):
    values = {"uid": uid, "euid": uid, "suid": uid, "gid": gid, "egid": gid, "sgid": gid,
              "groups": 0, "nnp": 1, "key": errno.EACCES, "config": errno.EPERM,
              "state": errno.EACCES, "caps": 1, "env": 1, "fds": 1}
    values.update(changes)
    if errors is not None:
        values.update(zip(("key", "config", "state"), errors))
    return probe._RESULT.pack(b"LAPROB1\0", *values.values())


def _authority_false(report):
    for name in ("candidate_executed", "namespace_operations_accepted", "native_runtime_accepted",
                 "isolation_accepted", "production_admission", "online_publication",
                 "remote_cleanup_authority", "secret_contents_read"):
        assert report[name] is False
    assert len(_wire(report)) < 4096


@pytest.fixture
def installed(monkeypatch):
    base = Path(tempfile.mkdtemp(prefix=".account-probe-", dir=Path.cwd())).resolve()
    original_identity = preflight._identity

    def root_owned(info, *, directory):
        result = original_identity(info, directory=directory)
        result.update(uid=0, gid=0)
        return result

    monkeypatch.setattr(preflight, "_identity", root_owned)
    monkeypatch.setattr(probe.sys, "platform", "linux")
    monkeypatch.setattr(probe.os, "getresuid", lambda: (0, 0, 0), raising=False)
    monkeypatch.setattr(preflight.os, "listxattr", lambda fd: [], raising=False)
    monkeypatch.setattr(preflight.pwd, "getpwuid", lambda uid: SimpleNamespace(
        pw_uid=uid, pw_gid=0 if uid == 0 else 61001, pw_name=str(uid)))
    monkeypatch.setattr(preflight.os, "getgrouplist", lambda name, gid: [gid])
    paths = {}
    for role in sorted(preflight._ROLES):
        path = base / role
        if role == "state":
            path.mkdir(mode=0o700)
        else:
            path.write_bytes(_image() if role == "helper" else ("private-" + role).encode())
            path.chmod(0o755 if role in {"helper", "runtime"} else 0o600)
        paths[role] = path

    def pin(path, directory=False):
        return root_owned(path.stat(follow_symlinks=False), directory=directory)

    def chain(path):
        return [pin(Path(*path.parts[:index]), True) for index in range(1, len(path.parts))]

    profile = {"schema": preflight._SCHEMA,
               "accounts": {"wrapper": {"uid": 0, "gid": 0, "groups": [0]},
                            "candidate": {"uid": 60001, "gid": 61001, "groups": [61001]}},
               "isolation": {"platform": "linux", "transition": "installed-helper-v1",
                             "namespaces": ["mount", "net", "pid", "user"]},
               "entries": {role: {"path": str(path), "chain": chain(path),
                                  "identity": pin(path, role == "state"),
                                  **({"sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                                     if role in preflight._HASHED else {})}
                           for role, path in paths.items()}}
    profile_path = base / "profile.json"
    profile_path.write_bytes(_wire(profile))
    profile_path.chmod(0o600)
    anchor = preflight.InstalledAccountProfileAnchor(_wire({
        "schema": preflight._ANCHOR_SCHEMA, "profile_path": str(profile_path),
        "profile_sha256": hashlib.sha256(profile_path.read_bytes()).hexdigest(),
        "profile_identity": pin(profile_path), "profile_chain": chain(profile_path),
        "protected_identities": {role: pin(paths[role]) for role in ("key", "config")},
    }))
    reference = probe.InstalledAccountProbeAnchor(
        anchor, hashlib.sha256(paths["helper"].read_bytes()).hexdigest(),
        hashlib.sha256(probe._SOURCE.read_bytes()).hexdigest())
    value = SimpleNamespace(reference=reference, base=base, paths=paths, profile=profile,
                            peer_threads=[], sent=[], calls=[], output=_result(), returncode=0,
                            mutate=None)

    def fake_popen(args, **kwargs):
        value.calls.append((args, kwargs))
        fd = kwargs["pass_fds"][0]
        assert kwargs["executable"] == f"/proc/self/fd/{fd}"
        assert os.fstat(fd).st_ino == paths["helper"].stat().st_ino
        assert args[:2] == ("lunar-account-probe", "--fixed-no-secret-probe-v1")
        assert kwargs["env"] == {} and kwargs["close_fds"] is True
        assert kwargs["user"] == 60001 and kwargs["group"] == 61001
        assert kwargs["extra_groups"] == () and kwargs["cwd"] == "/"
        assert kwargs["stderr"] == subprocess.DEVNULL
        assert len(kwargs["pass_fds"]) == 1
        input_read, input_write = os.pipe()
        output_read, output_write = os.pipe()
        process = SimpleNamespace(stdin=os.fdopen(input_write, "wb", buffering=0),
                                  stdout=os.fdopen(output_read, "rb", buffering=0),
                                  returncode=value.returncode, killed=False)
        process.poll = lambda: process.returncode
        process.wait = lambda **kwargs: process.returncode
        process.kill = lambda: setattr(process, "killed", True)

        def peer():
            raw = bytearray()
            try:
                while chunk := os.read(input_read, 65536):
                    raw.extend(chunk)
                value.sent.append(bytes(raw))
                if value.mutate is not None:
                    value.mutate()
                offset = 0
                while offset < len(value.output):
                    offset += os.write(output_write, value.output[offset:])
            except BrokenPipeError:
                pass  # Expected on bounded-output refusal.
            finally:
                os.close(input_read)
                os.close(output_write)

        thread = threading.Thread(target=peer, daemon=True)
        thread.start()
        value.peer_threads.append(thread)
        return process

    monkeypatch.setattr(probe, "_POPEN", fake_popen)
    try:
        yield value
    finally:
        for thread in value.peer_threads:
            thread.join(timeout=2)
            assert not thread.is_alive()
        shutil.rmtree(base)


def _inspect(installed):
    return probe.inspect_installed_account_transition(
        installed.reference, original_deadline=time.monotonic() + 5)


def test_composition_observes_only_fixed_diagnostic_and_retains_all_authority_false(installed):
    report = _inspect(installed)
    assert report["status"] == "observed", report
    assert report["account_transition_observed"] is True
    assert report["protected_access_denied"] is True
    assert report["probe_executed"] is True
    assert len(installed.calls) == 1
    raw = installed.sent[0]
    magic, deadline, *sizes = probe._INPUT.unpack_from(raw)
    assert magic == b"LAPIN1\0\0"
    assert str(deadline) == installed.calls[0][0][2]
    assert raw[probe._INPUT.size:] == b"".join(
        str(installed.paths[role]).encode() for role in ("key", "config", "state"))
    assert sum(sizes) + probe._INPUT.size == len(raw)
    assert str(installed.base) not in json.dumps(report)
    _authority_false(report)


def test_private_contents_and_state_are_never_read(installed, monkeypatch):
    forbidden = {installed.paths[role].stat().st_ino for role in ("key", "config", "state")}
    original_read = os.read

    def checked_read(fd, maximum):
        assert os.fstat(fd).st_ino not in forbidden
        return original_read(fd, maximum)

    monkeypatch.setattr(os, "read", checked_read)
    assert _inspect(installed)["status"] == "observed"


@pytest.mark.parametrize("changes", [
    {"uid": 0}, {"euid": 0}, {"suid": 0}, {"gid": 0}, {"egid": 0}, {"sgid": 0},
    {"groups": 1}, {"nnp": 0}, {"caps": 0}, {"env": 0}, {"fds": 0},
])
def test_bad_transition_never_promotes_observation(installed, changes):
    installed.output = _result(**changes)
    report = _inspect(installed)
    assert report["status"] == "refused"
    assert report["codes"] == ["probe_transition_refused"]
    assert report["account_transition_observed"] is False
    _authority_false(report)


@pytest.mark.parametrize("code", [0, errno.ENOENT, errno.ELOOP, errno.ENOTDIR, errno.EIO])
@pytest.mark.parametrize("role", [0, 1, 2])
def test_unproven_denial_in_any_protected_role_refuses(installed, code, role):
    errors = [errno.EACCES] * 3
    errors[role] = code
    installed.output = _result(errors=errors)
    assert _inspect(installed)["codes"] == ["protected_access_not_denied"]


@pytest.mark.parametrize("output,reason", [
    (b"", "probe_output_invalid"), (_result()[:-1], "probe_output_invalid"),
    (b"X" + _result()[1:], "probe_output_invalid"),
    (_result() + b"x", "probe_output_bounds_refused"),
])
def test_incomplete_wrong_or_excess_output_refuses(installed, output, reason):
    installed.output = output
    assert _inspect(installed)["codes"] == [reason]


def test_nonzero_exit_is_not_a_probe_receipt(installed):
    installed.returncode = 74
    assert _inspect(installed)["codes"] == ["probe_exit_refused"]


def test_matching_bytes_under_replaced_inode_do_not_rebind_helper(installed):
    helper = installed.paths["helper"]
    replaced = installed.base / "replacement"
    replaced.write_bytes(helper.read_bytes())
    replaced.chmod(0o755)
    os.replace(replaced, helper)
    report = _inspect(installed)
    assert report["status"] == "refused"
    assert not installed.calls


def test_post_probe_identity_drift_is_not_an_observation(installed):
    installed.mutate = lambda: installed.paths["key"].chmod(0o640)
    report = _inspect(installed)
    assert report["status"] == "refused"
    assert report["account_transition_observed"] is False


@pytest.mark.parametrize("field", ["helper_sha256", "source_sha256"])
def test_independent_installer_pin_cannot_be_replaced_by_current_hash(installed, field):
    from dataclasses import replace
    installed.reference = replace(installed.reference, **{field: "0" * 64})
    report = _inspect(installed)
    assert report["status"] == "refused"
    assert not installed.calls


def test_dynamic_helper_is_not_launched(installed, monkeypatch):
    def reject(_):
        raise probe.StaticPythonELFError("static_python_elf_interp_forbidden")

    monkeypatch.setattr(probe, "inspect_static_python_elf", reject)
    assert _inspect(installed)["codes"] == ["probe_static_helper_required"]
    assert not installed.calls


def test_unprivileged_linux_refuses_without_opening_installation(monkeypatch):
    monkeypatch.setattr(probe.sys, "platform", "linux")
    monkeypatch.setattr(probe.os, "getresuid", lambda: (1000, 1000, 1000), raising=False)
    monkeypatch.setattr(probe, "_source_digest", lambda: pytest.fail("must not open source"))
    report = probe.inspect_installed_account_transition(None, original_deadline=time.monotonic() + 5)
    assert report["codes"] == ["installed_root_transition_unavailable"]
    _authority_false(report)


def test_mac_is_unsupported_without_inspecting_files(monkeypatch):
    monkeypatch.setattr(probe.sys, "platform", "darwin")
    monkeypatch.setattr(probe, "_source_digest", lambda: pytest.fail("must not open source"))
    report = probe.inspect_installed_account_transition(None, original_deadline=time.monotonic() + 5)
    assert report["status"] == "unsupported"
    _authority_false(report)


@pytest.mark.parametrize("deadline", [
    True, None, "1", float("inf"), float("nan"), -1, 2**64,
    pytest.param(10**1000, id="huge-int"),
])
def test_invalid_or_expired_original_budget_never_launches(installed, deadline):
    report = probe.inspect_installed_account_transition(installed.reference, original_deadline=deadline)
    assert report["codes"] == ["original_deadline_invalid"]
    assert not installed.calls


def test_no_fresh_budget_is_created_after_preflight(installed, monkeypatch):
    original = preflight.inspect_account_isolation
    clock = [10.0]
    monkeypatch.setattr(probe.time, "monotonic", lambda: clock[0])

    def observes_then_expires(anchor):
        result = original(anchor)
        clock[0] = 15.0
        return result

    monkeypatch.setattr(preflight, "inspect_account_isolation", observes_then_expires)
    report = probe.inspect_installed_account_transition(installed.reference, original_deadline=14.0)
    assert report["codes"] == ["original_deadline_expired"]
    assert not installed.calls


@pytest.mark.skipif(sys.platform != "linux", reason="fixed Linux native negative smoke")
def test_compiled_native_probe_rejects_nonfixed_argv_and_expired_origin(tmp_path):
    compiler = shutil.which("cc")
    if compiler is None:
        pytest.skip("C compiler unavailable")
    target = tmp_path / "probe-negative-smoke"
    compiled = subprocess.run([compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
                               str(probe._SOURCE), "-o", str(target)],
                              capture_output=True, check=False, timeout=30)
    assert compiled.returncode == 0, compiled.stderr.decode()
    # This dynamic smoke binary is never passed to the installed execution API.
    # No valid account transition, protected path or candidate is requested.
    assert subprocess.run([target], check=False, timeout=5).returncode == 70
    assert subprocess.run([target, "--fixed-no-secret-probe-v1", "1"],
                          check=False, timeout=5).returncode == 77
