"""Explicit independent v4 worker bridge selection and pre-gate ordering.

This fixture intercepts the native runner and executes no whole-scope target.
It proves exact scope/session/child forwarding and fail-closed local dispatch;
actual publisher/creator descriptions use the companion v4 vault fixture.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
import test_external_worker_native_lifecycle as native_fixture
import test_external_worker_native_vault as installed_fixture
import test_external_worker_whole_scope_bridge as legacy_bridge_fixture
from test_external_worker_native_vault import PROFILE, _run
from test_external_worker_whole_scope_successor_vault import SCOPE_PROFILE, _project_modules

from lunar_evolution import external_worker_native_bridge as bridge
from lunar_evolution import external_worker_whole_scope_successor_vault as vault
from lunar_evolution import native_whole_scope as whole
from lunar_evolution import native_whole_scope_custody as legacy_custody
from lunar_evolution import native_whole_scope_successor as wire
from lunar_evolution.native_guardian_registration import NativeGuardianCustodyRequest

h = native_fixture.h
installed = installed_fixture.installed
legacy_b = legacy_bridge_fixture.b
pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="installed bridge requires Linux fd-bound artifact")


@pytest.fixture
def b(installed, tmp_path, monkeypatch):
    g = installed
    projected, ancestors = set(), set()
    for path in (tmp_path, *tmp_path.parents):
        info = path.stat()
        ancestors.add((info.st_dev, info.st_ino))
    _project_modules(monkeypatch, projected, ancestors)
    execution = tmp_path / "bridge-scope-execution"
    attempt = execution / g.h.intent.journal_id
    execution.mkdir(mode=0o700)
    attempt.mkdir(mode=0o700)
    for path in (execution, attempt):
        info = path.stat()
        projected.add((info.st_dev, info.st_ino))
    scope = whole.NativeWholeScopeOwner(whole._TOKEN)
    scope._profile = {"paths": (str(tmp_path / "delegation-fixture"), str(execution)),
                      "uid": 65534, "gid": 65534, "groups": (),
                      "bootstrap_sha256": g.h.artifact.artifact_sha256,
                      "supervisor_sha256": "c" * 64}
    scope._profile_sha256 = SCOPE_PROFILE
    scope._deadline = time.monotonic_ns() + 20_000_000_000
    scope._preparation_key = "a" * 64
    # Project the selected journal assignment only for this acquisition; the
    # portable inert fixture's previously authorized journal is not renamed.
    original_journal = whole.NativeWholeScopeOwner.journal_id
    monkeypatch.setattr(whole.NativeWholeScopeOwner, "journal_id", property(
        lambda owner: g.h.intent.journal_id if owner is scope else original_journal.fget(owner)))
    parent = scope._own(os.open(attempt, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC))
    scope._published = (parent,)
    scope._publication_pins = ((whole._kernel_identity(parent), None),)
    monkeypatch.setattr(scope, "_check_published_grants", lambda: None)
    monkeypatch.setattr(scope, "_check_installation", lambda: None)
    scope._successor_session = wire._SuccessorSession(wire._SESSION_TOKEN, scope)
    child = scope.acquire_custody_owner(profile=wire.PROFILE_NAME)
    launch = bridge.InstalledWorkerNativeLaunch(
        g.h.context, g.h.request, g.h.mapping, g.h.intent, g.h.attestation,
        g.h.artifact, g.h.workspace, g.h.producer_root,
    )

    def selected(**changes):
        return bridge.WorkerInstalledNativeBridge(
            launch, installation=g.installation, key=g.key, profile_sha256=PROFILE,
            **{"whole_scope": scope, "whole_scope_profile_sha256": SCOPE_PROFILE,
               "whole_scope_custody_profile": wire.PROFILE_NAME, **changes},
        )

    g.scope, g.child, g.selected, g.launch = scope, child, selected, launch
    try:
        yield g
    finally:
        scope.close()


def _intercept(g, monkeypatch, *, failure=False, selected=True):
    events, observed = [], []
    native_context, anchor = object(), object()

    class Resolver:
        def prepare_observer(self, **kwargs):
            events.append("prepare")
            assert kwargs["mapping"] is g.h.mapping and kwargs["context"] is g.h.context

            def registered(context):
                assert context is native_context
                events.append("registered")

            return registered

        def close(self):
            events.append("resolver-close")

    def native_anchor(*args, **kwargs):
        assert args[0] is g.installation and args[1] is anchor
        assert kwargs["expected_profile_sha256"] == PROFILE
        events.append("native-anchor")

    def whole_reference(*args, **kwargs):
        assert args[:3] == (g.installation, g.scope, anchor)
        assert kwargs["native_context"] is native_context
        assert kwargs["expected_profile_sha256"] == PROFILE
        assert kwargs["expected_whole_scope_profile_sha256"] == SCOPE_PROFILE
        assert kwargs["expected_mapping"] is g.h.mapping
        assert kwargs["check"]() is None
        events.append("whole-reference")
        if failure:
            raise vault.WorkerWholeScopeSuccessorVaultError("synthetic pre-gate storage failure")

    def run(*args, **kwargs):
        events.append("runner")
        assert ("whole_scope" in kwargs) is selected
        if selected:
            assert kwargs["whole_scope"] is g.scope
        assert "guardian_custody" not in kwargs
        assert not (g.h.batch / "work" / "marker").exists()
        observed.append(kwargs)
        assert kwargs["registered_observer"](native_context) is None
        events.append("native-gate")
        # The interception deliberately executes no target and establishes no
        # whole-scope completion, kernel containment or native result authority.
        return object()

    monkeypatch.setattr(bridge, "WorkerNativeLifecycleResolver", Resolver)
    monkeypatch.setattr(bridge, "WorkerNativeRestartWriter", lambda **kwargs: SimpleNamespace(anchor=anchor))
    monkeypatch.setattr(bridge, "retain_installed_native_anchor", native_anchor)
    monkeypatch.setattr(bridge, "retain_installed_whole_scope_successor_reference", whole_reference)
    monkeypatch.setattr(bridge, "run_native_trusted_attempt", run)
    monkeypatch.setattr(bridge, "retain_installed_whole_scope_reference",
                        lambda *_a, **_k: pytest.fail("v4 selection entered the v3 vault"))
    return events, observed


def test_explicit_bridge_forwards_same_owner_and_durably_retains_before_returning_observer(b, monkeypatch):
    b.bridge = b.selected()
    events, observed = _intercept(b, monkeypatch)
    _run(b)
    assert events == ["prepare", "runner", "registered", "native-anchor", "whole-reference",
                      "native-gate", "resolver-close"]
    assert len(observed) == 1
    assert not (b.h.batch / "work" / "marker").exists()
    assert not (b.h.job / "response.json").exists()
    _run(b)
    assert len(observed) == 1


def test_whole_scope_retention_failure_propagates_before_intercepted_gate_and_never_replays(b, monkeypatch):
    b.bridge = b.selected()
    events, observed = _intercept(b, monkeypatch, failure=True)
    with pytest.raises(vault.WorkerWholeScopeSuccessorVaultError, match="synthetic pre-gate storage failure"):
        _run(b)
    assert events == ["prepare", "runner", "registered", "native-anchor", "whole-reference", "resolver-close"]
    assert len(observed) == 1 and "native-gate" not in events
    assert not (b.h.batch / "work" / "marker").exists()
    _run(b)
    assert len(observed) == 1


def test_default_bridge_keeps_optional_native_call_seam_omitted(b, monkeypatch):
    events, observed = _intercept(b, monkeypatch, selected=False)
    _run(b)
    assert events == ["prepare", "runner", "registered", "native-anchor", "native-gate", "resolver-close"]
    assert len(observed) == 1 and "whole_scope" not in observed[0]
    assert "whole-reference" not in events


@pytest.mark.parametrize("changes", [
    {"whole_scope": None}, {"whole_scope_profile_sha256": None}, {"whole_scope": object()},
    {"whole_scope_profile_sha256": "f" * 64}, {"whole_scope_profile_sha256": True},
    {"whole_scope_profile_sha256": "D" * 64},
])
def test_explicit_selection_requires_exact_original_owner_and_independent_profile(b, changes):
    with pytest.raises(bridge.WorkerNativeBridgeError):
        b.selected(**changes)
    assert not b.h.job.exists() and not b.h.batch.exists()


def test_guardian_and_whole_scope_selections_are_mutually_exclusive(b):
    request = object.__new__(NativeGuardianCustodyRequest)
    with pytest.raises(bridge.WorkerNativeBridgeError, match="originals_required"):
        b.selected(guardian_custody=request)


@pytest.mark.parametrize("profile", [legacy_custody.CUSTODY_PROFILE,
                                     legacy_custody.CUSTODY_V2_PROFILE,
                                     legacy_custody.CUSTODY_V3_PROFILE])
def test_legacy_custody_selection_does_not_silently_upgrade_actual_v4(b, profile):
    with pytest.raises(bridge.WorkerNativeBridgeError):
        b.selected(whole_scope_custody_profile=profile)
    assert not b.h.job.exists() and not b.h.batch.exists()


def test_default_v3_profile_refuses_actual_v4_scope(b):
    with pytest.raises(bridge.WorkerNativeBridgeError, match="whole_scope_refused"):
        bridge.WorkerInstalledNativeBridge(
            b.launch, installation=b.installation, key=b.key, profile_sha256=PROFILE,
            whole_scope=b.scope, whole_scope_profile_sha256=SCOPE_PROFILE,
        )


def test_explicit_v4_selection_refuses_actual_legacy_v3_scope(legacy_b):
    with pytest.raises(bridge.WorkerNativeBridgeError, match="whole_scope_refused"):
        legacy_b.selected(whole_scope_custody_profile=wire.PROFILE_NAME)


@pytest.mark.parametrize("profile", [None, True, "", wire.PROFILE_NAME.upper()])
def test_v4_selection_requires_exact_profile_literal_before_any_worker_action(b, profile):
    with pytest.raises(bridge.WorkerNativeBridgeError, match="originals_required"):
        b.selected(whole_scope_custody_profile=profile)
    assert not b.h.job.exists() and not b.h.batch.exists()


@pytest.mark.parametrize("drift", ["deadline-enlargement", "closed", "released", "finished", "owner-replacement"])
def test_same_acquisition_and_non_enlarging_original_deadline_are_checked_each_use(b, drift):
    selected = b.selected()
    if drift == "deadline-enlargement":
        b.scope._deadline += 1
    elif drift == "owner-replacement":
        other = whole.NativeWholeScopeOwner(whole._TOKEN)
        other.__dict__.update(b.scope.__dict__)
        selected._whole_scope = other
    else:
        setattr(b.scope, "_" + drift, True)
    with pytest.raises(bridge.WorkerNativeBridgeError, match="whole_scope_refused"):
        selected.check_wrapper(b.config)
    # Do not bypass fixture descriptor retirement when testing the closed bit.
    if drift == "closed":
        b.scope._closed = False
    assert not b.h.job.exists() and not b.h.batch.exists()


def test_nested_vault_and_scope_roots_are_refused_before_native_launch(b):
    b.scope._profile["paths"] = (str(b.directory / "nested-delegation"), str(Path(b.child._path).parent))
    with pytest.raises(bridge.WorkerNativeBridgeError, match="whole_scope_refused"):
        b.selected()
    assert not b.h.batch.exists()


@pytest.mark.parametrize("drift", ["scope-session", "child-session", "session-owner", "child", "profile-selection"])
def test_v4_bridge_rejects_replaced_original_session_or_child_each_use(b, drift):
    selected = b.selected()
    session, child = b.scope._successor_session, b.child
    try:
        if drift == "scope-session":
            b.scope._successor_session = wire._SuccessorSession(wire._SESSION_TOKEN, b.scope)
        elif drift == "child-session":
            child._session = wire._SuccessorSession(wire._SESSION_TOKEN, b.scope)
        elif drift == "session-owner":
            session.owner = object()
        elif drift == "child":
            b.scope._custody_owner = SimpleNamespace(profile=wire.PROFILE_NAME)
        else:
            selected._whole_scope_custody_profile = legacy_custody.CUSTODY_V3_PROFILE
        with pytest.raises(bridge.WorkerNativeBridgeError, match="whole_scope_refused"):
            selected.check_wrapper(b.config)
    finally:
        b.scope._successor_session = session
        b.scope._custody_owner = child
        child._session = session
        session.owner = b.scope
    assert not b.h.job.exists() and not b.h.batch.exists()
