"""No candidates or credential changes: provider-free local preflight fixtures."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import lunar_evolution.external_worker_account_preflight as preflight


def _wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _pin(path, *, directory=False):
    return preflight._identity(os.stat(path, follow_symlinks=False), directory=directory)


def _chain(path):
    parts = path.parts
    return [_pin(Path(*parts[:index]), directory=True) for index in range(1, len(parts))]


@pytest.fixture
def installed(monkeypatch):
    # Avoid a world-writable /tmp ancestor. All fixture files are removed, and
    # every production lookup still uses fd-relative no-follow operations.
    base = Path(tempfile.mkdtemp(prefix=".account-preflight-test-", dir=Path.cwd())).resolve()
    wrapper = {"uid": os.geteuid(), "gid": os.getegid(),
               "groups": sorted({os.getegid(), *os.getgroups()})}
    candidate_uid = max(60000, wrapper["uid"] + 1)
    candidate_gid = max(61000, *wrapper["groups"]) + 1
    candidate = {"uid": candidate_uid, "gid": candidate_gid, "groups": [candidate_gid]}

    def account(uid):
        row = wrapper if uid == wrapper["uid"] else candidate if uid == candidate_uid else None
        if row is None:
            raise KeyError(uid)
        return SimpleNamespace(pw_uid=row["uid"], pw_gid=row["gid"], pw_name=str(uid))

    monkeypatch.setattr(preflight.sys, "platform", "linux")
    monkeypatch.setattr(preflight.pwd, "getpwuid", account)
    monkeypatch.setattr(preflight.os, "getgrouplist", lambda name, gid: list(
        wrapper["groups"] if int(name) == wrapper["uid"] else candidate["groups"]))
    monkeypatch.setattr(preflight.os, "listxattr", lambda fd: [], raising=False)
    paths = {}
    for role in sorted(preflight._ROLES):
        path = base / role
        if role == "state":
            path.mkdir(mode=0o700)
        else:
            path.write_bytes(("private-" + role).encode())
            path.chmod(0o700 if role in {"runtime", "helper"} else 0o600)
        paths[role] = path
    profile_path = base / "installed-profile.json"

    def write_profile(profile=None):
        if profile is None:
            profile = {
                "schema": preflight._SCHEMA,
                "accounts": {"wrapper": wrapper, "candidate": candidate},
                "isolation": {"platform": "linux", "transition": "installed-helper-v1",
                              "namespaces": ["mount", "net", "pid", "user"]},
                "entries": {role: {
                    "path": str(path), "chain": _chain(path),
                    "identity": _pin(path, directory=role == "state"),
                    **({"sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                       if role in preflight._HASHED else {}),
                } for role, path in paths.items()},
            }
        profile_path.write_bytes(_wire(profile))
        profile_path.chmod(0o600)
        reference = {
            "schema": preflight._ANCHOR_SCHEMA, "profile_path": str(profile_path),
            "profile_sha256": hashlib.sha256(profile_path.read_bytes()).hexdigest(),
            "profile_identity": _pin(profile_path), "profile_chain": _chain(profile_path),
            "protected_identities": {role: _pin(paths[role]) for role in ("key", "config")},
        }
        return preflight.InstalledAccountProfileAnchor(_wire(reference)), profile

    anchor, profile = write_profile()
    try:
        yield SimpleNamespace(base=base, paths=paths, profile_path=profile_path,
                              anchor=anchor, profile=profile, write=write_profile,
                              wrapper=wrapper, candidate=candidate)
    finally:
        shutil.rmtree(base)


def _assert_no_authority(report):
    for field in ("ready_for_acceptance", "isolation_accepted", "native_runtime_accepted",
                  "candidate_executed", "credentials_changed", "production_admission",
                  "remote_cleanup_authority"):
        assert report[field] is False
    assert len(_wire(report)) < 4096


def test_observed_static_facts_keep_active_acceptance_unknown(installed):
    report = preflight.inspect_account_isolation(installed.anchor)
    assert report["status"] == "unknown"
    assert report["files_observed"] == 6
    assert report["acl_and_file_capability_metadata_observed"] is True
    assert "namespace_operations_unverified" in report["codes"]
    assert "runtime_acceptance_unavailable" in report["codes"]
    assert str(installed.base) not in json.dumps(report)
    _assert_no_authority(report)


def test_key_and_config_contents_are_never_read(installed, monkeypatch):
    protected = {_pin(installed.paths[role])["ino"] for role in ("key", "config")}
    original = os.read

    def observed_read(fd, size):
        assert os.fstat(fd).st_ino not in protected
        return original(fd, size)

    monkeypatch.setattr(preflight.os, "read", observed_read)
    assert preflight.inspect_account_isolation(installed.anchor)["status"] == "unknown"


@pytest.mark.parametrize("role", ["key", "config", "runtime", "helper", "isolation_profile"])
def test_identical_bytes_replaced_inode_refuses(installed, role):
    path = installed.paths[role]
    replacement = installed.base / "replacement"
    replacement.write_bytes(path.read_bytes())
    replacement.chmod(stat.S_IMODE(path.stat().st_mode))
    os.replace(replacement, path)
    report = preflight.inspect_account_isolation(installed.anchor)
    assert report["status"] == "refused"
    assert report["codes"] == ["identity_drift"]
    _assert_no_authority(report)


def test_leaf_symlink_refuses_without_read(installed):
    path = installed.paths["key"]
    path.unlink()
    path.symlink_to(installed.paths["runtime"])
    assert preflight.inspect_account_isolation(installed.anchor)["status"] == "refused"


def test_hardlinked_original_refuses(installed):
    os.link(installed.paths["key"], installed.base / "extra-key-name")
    report = preflight.inspect_account_isolation(installed.anchor)
    assert report["status"] == "refused"


def test_parent_rename_and_same_bytes_cannot_rebind_original(installed):
    path = installed.paths["key"]
    nested = installed.base / "nested"
    nested.mkdir(mode=0o700)
    path.rename(nested / "key")
    installed.paths["key"] = nested / "key"
    anchor, _ = installed.write()
    moved = installed.base / "original-nested"
    nested.rename(moved)
    nested.mkdir(mode=0o700)
    (nested / "key").write_bytes((moved / "key").read_bytes())
    (nested / "key").chmod(0o600)
    assert preflight.inspect_account_isolation(anchor)["codes"] == ["identity_drift"]


def test_supplementary_group_drift_refuses(installed, monkeypatch):
    original = preflight.os.getgrouplist
    monkeypatch.setattr(preflight.os, "getgrouplist", lambda name, gid: [
        *original(name, gid), 777777])
    assert preflight.inspect_account_isolation(installed.anchor)["codes"] == ["account_drift"]


def test_shared_primary_group_refuses(installed):
    profile = installed.profile
    profile["accounts"]["candidate"]["gid"] = installed.wrapper["gid"]
    profile["accounts"]["candidate"]["groups"] = [installed.wrapper["gid"]]
    anchor, _ = installed.write(profile)
    assert preflight.inspect_account_isolation(anchor)["status"] == "refused"


@pytest.mark.parametrize("name,code", [("system.posix_acl_access", "acl_present_refused"),
                                     ("security.capability", "file_capability_refused")])
def test_extended_access_metadata_refuses(installed, monkeypatch, name, code):
    monkeypatch.setattr(preflight.os, "listxattr", lambda fd: [name], raising=False)
    assert preflight.inspect_account_isolation(installed.anchor)["codes"] == [code]


def test_unavailable_acl_evidence_is_unknown(installed, monkeypatch):
    def unavailable(fd):
        raise OSError("private host detail must not escape")

    monkeypatch.setattr(preflight.os, "listxattr", unavailable, raising=False)
    report = preflight.inspect_account_isolation(installed.anchor)
    assert report["status"] == "unknown"
    assert "acl_capability_metadata_unknown" in report["codes"]
    assert "private host detail" not in json.dumps(report)
    _assert_no_authority(report)


def test_profile_bytes_drift_refuses(installed):
    installed.profile_path.write_bytes(b"different profile")
    assert preflight.inspect_account_isolation(installed.anchor)["codes"] == ["identity_drift"]


@pytest.mark.parametrize("field", ["isolation_accepted", "accepted", "uid", "argv"])
def test_boolean_or_command_bypass_is_not_a_profile_field(installed, field):
    profile = installed.profile
    profile[field] = True
    anchor, _ = installed.write(profile)
    assert preflight.inspect_account_isolation(anchor)["codes"] == ["schema_invalid"]


def test_artifact_hash_is_rechecked_not_only_inode(installed):
    profile = installed.profile
    profile["entries"]["runtime"]["sha256"] = "0" * 64
    anchor, _ = installed.write(profile)
    assert preflight.inspect_account_isolation(anchor)["codes"] == ["artifact_digest_drift"]


def test_candidate_mode_access_refuses(installed):
    installed.paths["key"].chmod(0o644)
    anchor, _ = installed.write()
    report = preflight.inspect_account_isolation(anchor)
    assert report["status"] == "refused"
    assert report["codes"] == ["candidate_secret_access_refused"]


def test_original_chain_rechecked_after_metadata_observation(installed, monkeypatch):
    real = preflight._xattrs
    changed = False

    def replace_after_observation(entry):
        nonlocal changed
        result = real(entry)
        if not changed:
            changed = True
            path = installed.paths["helper"]
            path.chmod(0o600)
        return result

    monkeypatch.setattr(preflight, "_xattrs", replace_after_observation)
    assert preflight.inspect_account_isolation(installed.anchor)["status"] == "refused"


def test_unsupported_platform_does_not_open_files(monkeypatch):
    monkeypatch.setattr(preflight.sys, "platform", "darwin")
    monkeypatch.setattr(preflight.os, "open", lambda *args, **kwargs: pytest.fail("unexpected open"))
    report = preflight.inspect_account_isolation(None)
    assert report["status"] == "unsupported"
    _assert_no_authority(report)


def test_default_missing_configuration_is_explicit(monkeypatch):
    monkeypatch.setattr(preflight.sys, "platform", "linux")
    monkeypatch.setattr(preflight, "_ANCHOR_PATH", "/lunar-profile-absent-9f918a/anchor.json")
    report = preflight.inspect_default_account_isolation()
    assert report["status"] == "configuration_absent"
    _assert_no_authority(report)


def test_cli_requires_explicit_inspection_and_has_no_execution_options(monkeypatch, capsys):
    with pytest.raises(SystemExit) as exc:
        preflight.main([])
    assert exc.value.code == 2
    with pytest.raises(SystemExit):
        preflight.main(["--inspect-installed", "--runtime", "/arbitrary"])
    monkeypatch.setattr(preflight, "inspect_default_account_isolation",
                        lambda: preflight._report("unknown", ["namespace_operations_unverified"]))
    assert preflight.main(["--inspect-installed"]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "unknown"
    _assert_no_authority(report)


def test_parent_symlink_refuses(installed):
    nested = installed.base / "nested"
    nested.mkdir(mode=0o700)
    installed.paths["key"].rename(nested / "key")
    installed.paths["key"] = nested / "key"
    anchor, _ = installed.write()
    moved = installed.base / "held-original"
    nested.rename(moved)
    nested.symlink_to(moved, target_is_directory=True)
    report = preflight.inspect_account_isolation(anchor)
    assert report["status"] == "refused"
    assert report["codes"] == ["chain_refused"]


def test_hash_role_cannot_read_a_protected_inode(installed, monkeypatch):
    profile = installed.profile
    key = dict(profile["entries"]["key"])
    key["sha256"] = "0" * 64
    profile["entries"]["isolation_profile"] = key
    anchor, _ = installed.write(profile)
    protected = {_pin(installed.paths[role])["ino"] for role in ("key", "config")}
    original = os.read

    def observed_read(fd, size):
        assert os.fstat(fd).st_ino not in protected
        return original(fd, size)

    monkeypatch.setattr(preflight.os, "read", observed_read)
    report = preflight.inspect_account_isolation(anchor)
    assert report["codes"] == ["entry_alias_refused"]
    _assert_no_authority(report)


def test_fifo_leaf_refuses_before_open(installed):
    path = installed.paths["key"]
    path.unlink()
    os.mkfifo(path, 0o600)
    assert preflight.inspect_account_isolation(installed.anchor)["status"] == "refused"
