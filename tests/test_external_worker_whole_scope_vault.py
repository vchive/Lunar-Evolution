"""Original pre-gate vault composition with real publisher/creator descriptions.

The actual inert native attempt uses its existing portable backend. The v3
scope is a separate software fixture: only custody metadata/ancestors are root
projected, with no cgroup, credential drop or installed-runtime claim. Darwin
also projects the mount/ACL mechanism; Linux uses actual statx/xattr checks.
"""
from __future__ import annotations

import base64
import errno
import hashlib
import hmac
import json
import os
import stat
import struct
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
import test_external_worker_native_lifecycle as native_fixture
import test_external_worker_native_vault as installed_fixture
from test_external_worker_native_lifecycle import _same_bytes, _tree
from test_external_worker_native_vault import PROFILE, _run

from lunar_evolution import external_worker_guardian_vault as shared
from lunar_evolution import external_worker_native_bridge as bridge
from lunar_evolution import external_worker_native_vault as native_vault
from lunar_evolution import external_worker_whole_scope_vault as vault
from lunar_evolution import external_worker_wrapper as wrapper
from lunar_evolution import native_trusted_attempt as native_runner
from lunar_evolution import native_whole_scope as whole
from lunar_evolution import native_whole_scope_custody as custody
from lunar_evolution.native_original_publication import hold_native_original_publications

h = native_fixture.h
installed = installed_fixture.installed
SCOPE_PROFILE = "d" * 64
pytestmark = pytest.mark.skipif(sys.platform not in {"darwin", "linux"}, reason="native bootstrap platform")


class _MetadataOS:
    """Confine root metadata projection to the two custody modules only."""

    def __init__(self, originals, ancestors):
        self.originals, self.ancestors = originals, ancestors

    def __getattr__(self, name):
        return getattr(os, name)

    def _project(self, info):
        identity = (info.st_dev, info.st_ino)
        if identity not in self.originals and identity not in self.ancestors:
            return info
        fields = {name: getattr(info, name) for name in dir(info) if name.startswith("st_")}
        fields.update(st_uid=0, st_gid=0)
        if identity in self.ancestors:
            fields["st_mode"] &= ~0o022
        return SimpleNamespace(**fields)

    def stat(self, *args, **kwargs):
        return self._project(os.stat(*args, **kwargs))

    def fstat(self, fd):
        return self._project(os.fstat(fd))

    def mkdir(self, path, *args, **kwargs):
        os.mkdir(path, *args, **kwargs)
        info = os.stat(path, dir_fd=kwargs.get("dir_fd"), follow_symlinks=False)
        self.originals.add((info.st_dev, info.st_ino))


def _project_modules(monkeypatch, originals, ancestors):
    proxy = _MetadataOS(originals, ancestors)
    monkeypatch.setattr(whole, "os", proxy)
    monkeypatch.setattr(custody, "os", proxy)
    if sys.platform == "darwin":
        # Explicit software mechanism projection, never Linux mount/ACL acceptance.
        monkeypatch.setattr(whole, "_mount_id", lambda fd, name=None: os.fstat(fd).st_dev)
        monkeypatch.setattr(custody, "_no_acl", lambda _fd: None)
    return proxy


def _scope_fixture(g, publications, monkeypatch):
    root = g.scope_root
    root.mkdir(mode=0o700)
    attempt = root / ("lunar-" + "a" * 64)
    attempt.mkdir(mode=0o700)
    for path in (root, attempt):
        info = path.stat()
        g.projected.add((info.st_dev, info.st_ino))
    owner = whole.NativeWholeScopeOwner(whole._TOKEN)
    owner._profile = {"paths": (str(root.parent / "delegation-fixture"), str(root)),
                      "uid": 65534, "gid": 65534, "groups": (),
                      "bootstrap_sha256": g.h.artifact.artifact_sha256,
                      "supervisor_sha256": "c" * 64}
    owner._profile_sha256 = SCOPE_PROFILE
    # A conservative software-fixture binding inside the original native budget;
    # this is not a claim to reconstruct the runner's actual native clock sample.
    owner._deadline = int(json.loads(g.native.deadline_json)["deadline_monotonic"] * 1e9) - 1000
    owner._preparation_key = "a" * 64
    parent = owner._own(os.open(attempt, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC))
    owner._published = (parent,)
    owner._publication_pins = ((whole._kernel_identity(parent), None),)
    monkeypatch.setattr(owner, "_check_published_grants", lambda: None)
    monkeypatch.setattr(owner, "_check_installation", lambda: None)
    child = owner.acquire_custody_owner(profile=custody.CUSTODY_V3_PROFILE)
    child._borrow_for_start()
    owner._binding = owner._core(launch=g.native.launch_sha256, intent=g.native.intent_sha256,
                                 target=g.h.intent.executable_sha256, deadline_ns=owner.deadline_ns)
    owner._scope = whole._IDENTITY.pack(31, 41, 51, 0, 0, stat.S_IFDIR | 0o700, 0)
    owner._target_pid = 123
    owner._original_publications = publications
    pins = publications._borrow_for_native_transfer()[1]
    raw_pins = b"".join(whole._PUBLICATION.pack(dev, ino, size, mtime, ctime, digest.encode() + b"\0")
                        for digest, size, dev, ino, mtime, ctime in pins)
    registration = (whole._HEADER.pack(0x3151574C, 3, 22, 1, 0, 0) + owner._binding
                    + owner._scope + struct.pack("<Q", owner._target_pid) + raw_pins)
    creators = []
    try:
        for name, raw in zip(custody._V3_NAMES, (registration, b""), strict=True):
            fd = os.open(Path(child._path) / name,
                         os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC, 0o600)
            creators.append(fd)
            info = os.fstat(fd)
            g.projected.add((info.st_dev, info.st_ino))
            assert os.write(fd, raw) == len(raw)
            os.fsync(fd)
        os.fsync(child._directory)
        child._adopt_creator_descriptions(whole._TOKEN, owner, tuple(creators), raw_pins)
        owner._registered = True
    finally:
        for fd in reversed(creators):
            os.close(fd)
    g.scope, g.child = owner, child
    g.registration, g.raw_pins = registration, raw_pins


def _false(report):
    for name in ("native_success", "production_admission", "publication_authority", "cleanup_authority",
                 "online_publication", "whole_group_cleanup_verified", "durable_acknowledgement_verified",
                 "original_quiescence_observed"):
        assert report[name] is False
    assert report["cleanup_status"] == report["execution_status"] == "unknown"


@pytest.fixture
def s(installed, tmp_path, monkeypatch):
    g = installed
    g.scope_root = tmp_path / "scope-execution"
    g.projected, g.ancestors = set(), set()
    for path in (tmp_path, *tmp_path.parents):
        info = path.stat()
        g.ancestors.add((info.st_dev, info.st_ino))
    _project_modules(monkeypatch, g.projected, g.ancestors)
    g.scope = g.child = None
    g.observations, g.contexts, g.retained = [], [], []
    g.before_retain = g.after_retain = lambda _g: None
    g.retention_check = lambda: None
    real_deadline = native_runner._persist_deadline
    real_publish = native_runner.publish_trusted_bootstrap_registration
    real_run = bridge.run_native_trusted_attempt
    real_anchor = bridge.retain_installed_native_anchor
    with hold_native_original_publications() as publications:
        g.publications = publications

        def deadline(*args, **kwargs):
            assert kwargs.get("publications") is None
            return real_deadline(*args, **{**kwargs, "publications": publications})

        def publish(*args, **kwargs):
            assert kwargs.get("retain_creation_owner") is None
            return real_publish(*args, **{**kwargs, "retain_creation_owner": publications})

        def run(*args, **kwargs):
            observer = kwargs["registered_observer"]

            def capture(context):
                g.native = context
                g.contexts.append(context)
                return observer(context)

            observation = real_run(*args, **{**kwargs, "registered_observer": capture})
            g.observations.append(observation)
            return observation

        def retain(*args, **kwargs):
            assert not (g.h.batch / "work" / "marker").exists()
            real_anchor(*args, **kwargs)
            g.anchor = args[1]
            _scope_fixture(g, publications, monkeypatch)
            g.native_record_before = g.record.read_bytes()
            g.packet_before = (g.h.job / "native-restart-packet.json").read_bytes()
            g.before_retain(g)
            vault.retain_installed_whole_scope_reference(
                g.installation, g.scope, g.anchor, g.h.lookup, native_context=g.native,
                key=g.key, expected_context=g.h.context, expected_mapping=g.h.mapping,
                expected_profile_sha256=PROFILE, expected_whole_scope_profile_sha256=SCOPE_PROFILE,
                check=g.retention_check,
            )
            assert not (g.h.batch / "work" / "marker").exists()
            g.retained.append(g.child.reference)
            g.after_retain(g)

        monkeypatch.setattr(native_runner, "_persist_deadline", deadline)
        monkeypatch.setattr(native_runner, "publish_trusted_bootstrap_registration", publish)
        monkeypatch.setattr(bridge, "run_native_trusted_attempt", run)
        monkeypatch.setattr(bridge, "retain_installed_native_anchor", retain)
        g.whole_record = g.directory / vault._name(g.h.lookup)

        def inspect(**changes):
            return vault.inspect_installed_whole_scope_reference(
                changes.pop("raw", g.h.lookup), installation=changes.pop("installation", g.installation),
                key=changes.pop("key", g.key), expected_context=changes.pop("context", g.h.context),
                expected_mapping=changes.pop("mapping", g.h.mapping),
                expected_profile_sha256=changes.pop("profile", PROFILE),
                expected_whole_scope_profile_sha256=changes.pop("scope_profile", SCOPE_PROFILE), **changes,
            )

        g.whole_inspect = inspect
        try:
            yield g
        finally:
            if g.scope is not None:
                g.scope.close()


def test_real_original_publishers_and_v3_creators_are_durable_while_target_is_gated(s):
    observed = []

    def after(g):
        report = g.whole_inspect()
        assert report["status"] == "custody_observed"
        assert report["whole_scope_reference_custody_observed"] is True
        assert report["state"] == "registration_prefix_observed"
        _false(report)
        observed.append(report)

    s.after_retain = after
    _run(s)
    assert len(observed) == len(s.retained) == len(s.contexts) == 1
    assert s.observations[0].gate_released and s.observations[0].target_started
    assert (s.h.batch / "work" / "marker").read_bytes() == b"started"
    assert s.record.read_bytes() == s.native_record_before
    assert (s.h.job / "native-restart-packet.json").read_bytes() == s.packet_before
    value = json.loads(s.whole_record.read_bytes())
    assert value["profile_sha256"] == PROFILE and value["whole_scope_profile_sha256"] == SCOPE_PROFILE
    assert PROFILE != SCOPE_PROFILE
    assert value["whole_scope_reference"] == json.loads(s.child.reference.canonical_bytes)
    assert value["native_vault_sha256"] == hashlib.sha256(s.native_record_before).hexdigest()
    assert vault._publications(s.native) == s.publications._borrow_for_native_transfer()[1]
    assert bytes.fromhex(value["whole_scope_reference"]["registration"])[-3 * whole._PUBLICATION.size:] == s.raw_pins
    assert "whole_scope_reference" not in json.loads(s.native_record_before)
    assert not any("whole_scope" in key for key in json.loads(s.packet_before)["native"])
    _false(s.whole_inspect())


@pytest.mark.parametrize("stage", ["before-write", "partial-pending", "file-fsync", "directory-fsync", "after-durable"])
def test_storage_fault_keeps_actual_gate_closed_and_preserves_failed_attempt(s, monkeypatch, stage):
    real_create, real_fsync = shared._create, os.fsync

    def create(chain, name, raw, checkpoint):
        if stage == "partial-pending":
            fd = os.open(name + ".pending", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=chain.fd)
            try:
                os.write(fd, raw[:13])
                real_fsync(fd)
            finally:
                os.close(fd)
        elif stage in {"file-fsync", "directory-fsync"}:
            with monkeypatch.context() as changed:
                def fail(fd):
                    if stat.S_ISDIR(os.fstat(fd).st_mode) == (stage == "directory-fsync"):
                        raise OSError(errno.EIO, "synthetic storage failure")
                    return real_fsync(fd)
                changed.setattr(shared.os, "fsync", fail)
                return real_create(chain, name, raw, checkpoint)
        elif stage == "after-durable":
            real_create(chain, name, raw, checkpoint)
        raise OSError(errno.EIO, "synthetic storage failure")

    monkeypatch.setattr(shared, "_create", create)
    _run(s)
    assert len(s.observations) == 1
    assert not s.observations[0].gate_released and not s.observations[0].target_started
    assert not (s.h.batch / "work" / "marker").exists()
    assert not (s.h.job / "response.json").exists()
    if stage == "partial-pending":
        assert s.whole_record.with_name(s.whole_record.name + ".pending").stat().st_size == 13
    if stage not in {"after-durable", "directory-fsync"}:
        assert s.whole_inspect()["status"] == "context_unavailable"
    _false(s.whole_inspect())
    before = _tree(s.h.workspace), _tree(s.h.job), _tree(s.directory), _tree(s.scope_root)
    _run(s)
    assert len(s.observations) == 1
    assert (_tree(s.h.workspace), _tree(s.h.job), _tree(s.directory), _tree(s.scope_root)) == before


@pytest.mark.parametrize("original", ["packet", "complete"])
def test_original_packet_drift_during_sidecar_write_refuses_actual_gate_without_repair(s, monkeypatch, original):
    real_create = shared._create
    changed = []

    def create(chain, name, raw, checkpoint):
        pin = real_create(chain, name, raw, checkpoint)
        if name == vault._name(s.h.lookup):
            path = s.h.job / f"native-restart-{original}.json"
            before = path.read_bytes()
            # Keep valid JSON and the same inode. The exact original bytes/pin
            # must still refuse after storage returns and before the real gate.
            path.write_bytes(before + b" ")
            changed.append((path, before + b" "))
        return pin

    monkeypatch.setattr(shared, "_create", create)
    _run(s)
    assert len(changed) == len(s.observations) == 1
    assert not s.observations[0].gate_released and not s.observations[0].target_started
    assert not (s.h.batch / "work" / "marker").exists()
    assert not (s.h.job / "response.json").exists()
    assert s.whole_record.exists()
    assert changed[0][0].read_bytes() == changed[0][1]
    assert s.record.read_bytes() == s.native_record_before
    report = s.whole_inspect()
    assert report["status"] == "context_unavailable"
    _false(report)
    before = _tree(s.h.workspace), _tree(s.h.job), _tree(s.directory), _tree(s.scope_root)
    _run(s)
    assert len(changed) == len(s.observations) == 1
    assert (_tree(s.h.workspace), _tree(s.h.job), _tree(s.directory), _tree(s.scope_root)) == before


@pytest.mark.parametrize("drift", ["launch", "intent", "scope-profile", "deadline", "publication",
                                   "released", "creator-write-truncate", "reference"])
def test_original_scope_context_and_creator_drift_refuse_before_actual_gate(s, drift):
    def change(g):
        if drift in {"launch", "intent", "scope-profile", "deadline"}:
            binding = bytearray(g.scope._binding)
            offset = {"deadline": 0, "launch": 8, "intent": 73, "scope-profile": 333}[drift]
            binding[offset] ^= 1
            g.scope._binding = bytes(binding)
        elif drift == "publication":
            descriptor = g.publications._borrow_for_native_transfer()[0][2]
            info = os.fstat(descriptor)
            os.utime(descriptor, ns=(info.st_atime_ns, info.st_mtime_ns + 1))
        elif drift == "released":
            g.scope._released = True
        elif drift == "creator-write-truncate":
            descriptor = g.child._creators[1]
            os.pwrite(descriptor, b"x", 0)
            os.ftruncate(descriptor, 0)
        else:
            object.__setattr__(g.child.reference, "canonical_bytes", b"{}")

    s.before_retain = change
    _run(s)
    assert len(s.observations) == 1 and not s.observations[0].gate_released
    assert not (s.h.batch / "work" / "marker").exists()
    assert not s.whole_record.exists()
    _false(s.whole_inspect())


@pytest.mark.parametrize("drift", ["context", "mapping", "profile", "scope-profile", "key-id", "key-secret", "installation"])
def test_restart_requires_both_independent_profiles_and_original_worker_assignment(s, drift):
    _run(s)
    changes = {}
    if drift == "context":
        changes["context"] = replace(s.h.context, controller_challenge="f" * 64)
    elif drift == "mapping":
        changes["mapping"] = replace(s.h.mapping, native_task_id="different-task")
    elif drift in {"profile", "scope-profile"}:
        changes[drift.replace("-", "_")] = "f" * 64
    elif drift == "key-id":
        changes["key"] = replace(s.key, key_id="rotated")
    elif drift == "key-secret":
        changes["key"] = replace(s.key, secret_key=b"z" * 32)
    else:
        changes["installation"] = None
    before = _tree(s.h.workspace), _tree(s.h.job), _tree(s.directory), _tree(s.scope_root)
    report = s.whole_inspect(**changes)
    assert report["status"] == "context_unavailable"
    assert not report["whole_scope_reference_custody_observed"]
    _false(report)
    assert (_tree(s.h.workspace), _tree(s.h.job), _tree(s.directory), _tree(s.scope_root)) == before


@pytest.mark.parametrize("missing", ["sidecar", "native-anchor", "packet", "complete"])
def test_missing_original_never_discovers_reference_from_valid_current_custody_files(s, missing):
    _run(s)
    path = {"sidecar": s.whole_record, "native-anchor": s.record,
            "packet": s.h.job / "native-restart-packet.json",
            "complete": s.h.job / "native-restart-complete.json"}[missing]
    path.unlink()
    before = _tree(s.h.workspace), _tree(s.h.job), _tree(s.directory), _tree(s.scope_root)
    report = s.whole_inspect()
    assert report["status"] == "context_unavailable"
    assert not report["whole_scope_reference_custody_observed"]
    _false(report)
    assert (_tree(s.h.workspace), _tree(s.h.job), _tree(s.directory), _tree(s.scope_root)) == before


@pytest.mark.parametrize("target", ["registration", "terminal", "packet"])
def test_same_byte_inode_replacement_does_not_recreate_originals(s, target):
    _run(s)
    path = (Path(s.child._path) / custody._V3_NAMES[0 if target == "registration" else 1]
            if target != "packet" else s.h.job / "native-restart-packet.json")
    _same_bytes(path)
    report = s.whole_inspect()
    assert report["status"] == "context_unavailable"
    _false(report)


@pytest.mark.parametrize("reason,facts", [(0, 10), (1, 15), (2, 1), (3, 3)])
def test_persisted_terminal_is_only_a_record_observation_without_ack_or_cleanup_authority(s, reason, facts):
    _run(s)
    raw = bytearray(s.registration)
    struct.pack_into("<III", raw, 4, 3, 25 if reason == 0 else 26, 2)
    raw.extend(custody._EVENT_FACTS.pack(reason, facts, s.scope.deadline_ns - 1))
    descriptor = s.child._creators[1]
    assert os.pwrite(descriptor, raw, 0) == len(raw)
    os.fsync(descriptor)
    report = s.whole_inspect()
    assert report["status"] == "custody_observed"
    assert report["state"] == ("terminal_record_observed" if reason == 0 else "abnormal_record_observed")
    assert report["recorded_reason"] == custody._REASONS[reason]
    _false(report)


@pytest.mark.parametrize("tamper", ["domain", "native-binding", "authority", "deadline-bool", "publication-pin"])
def test_resigned_or_cross_domain_sidecar_cannot_bypass_original_semantic_binding(s, tamper):
    _run(s)
    row = json.loads(s.whole_record.read_bytes())
    if tamper == "native-binding":
        row["native_binding_sha256"] = "f" * 64
    elif tamper == "authority":
        row["cleanup_authority"] = True
    elif tamper == "deadline-bool":
        row["native_deadline_ns"] = True
    elif tamper == "publication-pin":
        original = bytearray.fromhex(row["whole_scope_reference"]["registration"])
        original[-3 * whole._PUBLICATION.size] ^= 1
        row["whole_scope_reference"]["registration"] = original.hex()
    unsigned = {key: value for key, value in row.items() if key != "mac_sha256"}
    domain = shared._DOMAIN if tamper == "domain" else vault._DOMAIN
    row["mac_sha256"] = hmac.new(s.key.secret_key, domain + wrapper.worker_json(unsigned), hashlib.sha256).hexdigest()
    s.whole_record.write_bytes(wrapper.worker_json(row))
    report = s.whole_inspect()
    assert report["status"] == "context_unavailable"
    _false(report)


@pytest.mark.parametrize("drift", ["key", "installation", "assignment"])
def test_final_private_chain_read_cannot_hide_drift_before_returning_custody(s, monkeypatch, drift):
    _run(s)
    real_private = native_vault._private_chain
    outer_open = native_vault._open
    outer_chain = []
    checks = []

    def opened(*args, **kwargs):
        value, chain = outer_open(*args, **kwargs)
        if not outer_chain:
            outer_chain.append(chain)
        return value, chain

    def private(chain):
        real_private(chain)
        if outer_chain and chain is outer_chain[0]:
            checks.append(chain)
            if drift == "key":
                object.__setattr__(s.key, "secret_key", b"x" * 32)
            elif drift == "installation":
                row = json.loads(s.installation.canonical_bytes)
                row["profile_sha256"] = "f" * 64
                object.__setattr__(s.installation, "canonical_bytes", wrapper.worker_json(row))
            else:
                object.__setattr__(s.h.mapping, "native_task_id", "changed-after-last-comparison")

    monkeypatch.setattr(native_vault, "_open", opened)
    monkeypatch.setattr(native_vault, "_private_chain", private)
    report = s.whole_inspect()
    assert len(checks) == 1
    assert report["status"] == "context_unavailable"
    _false(report)


def test_fresh_process_only_inspects_independently_retained_originals(s):
    _run(s)
    s.scope.close()
    s.publications.close()
    before = _tree(s.h.workspace), _tree(s.h.job), _tree(s.directory), _tree(s.scope_root)
    payload = wrapper.worker_json({
        "installation": base64.b64encode(s.installation.canonical_bytes).decode(),
        "key": {name: getattr(s.key, name) for name in ("worker_id", "host_id", "host_boot_id", "key_id")},
        "secret": base64.b64encode(s.key.secret_key).decode(),
        "context": s.h.context.to_dict(), "mapping": s.h.mapping.to_dict(),
        "lookup": base64.b64encode(s.h.lookup).decode(), "profile": PROFILE, "scope_profile": SCOPE_PROFILE,
        "projected": sorted(s.projected), "ancestors": sorted(s.ancestors),
    })
    script = """
import base64,json,os,subprocess,sys
from lunar_evolution import external_worker_whole_scope_vault as vault
from lunar_evolution import external_worker_guardian_vault as shared
from lunar_evolution import external_worker_native_lifecycle as lifecycle
from lunar_evolution import external_worker_native_restart as restart
from lunar_evolution import external_worker_wrapper as wrapper
from lunar_evolution import native_whole_scope as whole
from lunar_evolution import native_whole_scope_custody as custody
from lunar_evolution.external_worker_native_lifecycle import WorkerNativeTaskMapping
from lunar_evolution.external_worker_native_vault import InstalledWorkerNativeVault
from lunar_evolution.external_worker_origin import WorkerOriginContext,WorkerOriginKey
from test_external_worker_whole_scope_vault import _MetadataOS
p=json.loads(sys.stdin.buffer.read())
proxy=_MetadataOS(set(map(tuple,p['projected'])),set(map(tuple,p['ancestors'])))
whole.os=custody.os=proxy
if sys.platform=='darwin':
 whole._mount_id=lambda fd,name=None:os.fstat(fd).st_dev
 custody._no_acl=lambda fd:None
def forbidden(*a,**k):raise AssertionError('restart attempted a write/process/owner action')
lifecycle.WorkerNativeLifecycleResolver.prepare_observer=forbidden
wrapper._publish=restart._publish=shared._create=forbidden
whole.NativeWholeScopeOwner.acquire_custody_owner=forbidden
os.kill=os.killpg=subprocess.Popen=forbidden
report=vault.inspect_installed_whole_scope_reference(base64.b64decode(p['lookup']),
 installation=InstalledWorkerNativeVault(base64.b64decode(p['installation'])),
 key=WorkerOriginKey(**p['key'],secret_key=base64.b64decode(p['secret'])),
 expected_context=WorkerOriginContext.from_dict(p['context']),
 expected_mapping=WorkerNativeTaskMapping(**p['mapping']),expected_profile_sha256=p['profile'],
 expected_whole_scope_profile_sha256=p['scope_profile'])
sys.stdout.buffer.write(wrapper.worker_json(report))
"""
    script = (f"import sys\nsys.path[:0]={list(map(str, (Path(wrapper.__file__).resolve().parents[1], Path(__file__).resolve().parent)))!r}\n"
              + script)
    process = subprocess.run([sys.executable, "-B", "-c", script], input=payload,
                             capture_output=True, timeout=20, check=False)
    assert process.returncode == 0, process.stderr.decode(errors="replace")
    report = json.loads(process.stdout)
    assert report["status"] == "custody_observed"
    assert report["whole_scope_reference_custody_observed"] is True
    assert report["state"] == "registration_prefix_observed"
    _false(report)
    assert (_tree(s.h.workspace), _tree(s.h.job), _tree(s.directory), _tree(s.scope_root)) == before
    assert s.h.attestation.nonce not in process.stdout.decode()
    assert s.key.secret_key.decode() not in process.stdout.decode()
