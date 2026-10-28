"""The same live input acquisition reaches every native input/material check."""
from __future__ import annotations

from contextlib import contextmanager

import pytest

from lunar_evolution import native_trusted_attempt as attempt
from lunar_evolution import native_whole_scope as whole
from lunar_evolution.native_fixed_u_inputs import NativeFixedUInputError


@pytest.mark.parametrize("with_owner", [False, True])
def test_launch_reobservation_preserves_original_input_owner(monkeypatch, with_owner):
    live = object() if with_owner else None
    original = object()
    calls = []
    intent = type("Intent", (), {"argv": ()})()

    def rsi(workspace, **options):
        calls.append((workspace, options))
        return original

    def producer(workspace, **options):
        calls.append((workspace, options))

    monkeypatch.setattr(attempt, "validate_native_rsi_launch_inputs", rsi)
    monkeypatch.setattr(attempt, "validate_producer_launch_inputs", producer)
    for unexpired in (True, False):
        attempt._revalidate_native_launch_inputs(
            original, "/workspace", intent=intent, attestation=None, artifact=None,
            require_unexpired=unexpired, fixed_u_owner=live,
        )
    assert len(calls) == 4
    assert all(("fixed_u_owner" in options) is with_owner for _, options in calls)
    if with_owner:
        assert all(options["fixed_u_owner"] is live for _, options in calls)
    assert [options["require_unexpired"] for _, options in calls] == [True, True, False, False]


def test_lost_live_input_acquisition_refuses_before_second_protocol(monkeypatch):
    seen = []

    def refuse(*args, **options):
        seen.append(options["fixed_u_owner"])
        raise NativeFixedUInputError("original_changed")

    monkeypatch.setattr(attempt, "validate_native_rsi_launch_inputs", refuse)
    monkeypatch.setattr(attempt, "validate_producer_launch_inputs", lambda *a, **k: pytest.fail("later protocol"))
    live = object()
    with pytest.raises(attempt.NativeTrustedAttemptError):
        attempt._native_launch_inputs(
            "/workspace", intent=type("Intent", (), {"argv": ()})(), attestation=None,
            artifact=None, require_unexpired=True, fixed_u_owner=live,
        )
    assert seen == [live]


def test_input_drift_at_whole_scope_preflight_is_classified_before_claim(tmp_path, monkeypatch):
    from test_native_trusted_attempt import _attempt

    workspace, producer, intent, attestation, artifact, batch = _attempt(tmp_path)
    # Internal token fixture only: no installed root acquisition or S/B launch.
    scope = whole.NativeWholeScopeOwner(whole._TOKEN)
    scope._deadline = attempt.time.monotonic_ns() + 8_000_000_000
    batch.mkdir(parents=True)
    error = NativeFixedUInputError("original_changed")

    def drift(*args, **options):
        raise error

    monkeypatch.setattr(scope, "check_before_launch", drift)
    with pytest.raises(attempt.NativeTrustedAttemptError, match="preflight_invalid") as failure:
        attempt.run_native_trusted_attempt(
            workspace, producer_root=producer, intent=intent, attestation=attestation,
            artifact=artifact, whole_scope=scope,
        )
    assert failure.value.__cause__ is error
    assert not tuple(batch.iterdir())
    scope.close()


@pytest.mark.parametrize("with_owner", [False, True])
def test_grant_reobservation_keeps_same_acquisition_for_extract_and_materials(monkeypatch, with_owner):
    live = object() if with_owner else None
    inputs, materials = object(), object()
    calls = []

    def extract(value, **options):
        assert value is inputs
        calls.append(("extract", options))
        return type("Original", (), {"materials": materials})()

    class Grants:
        def validate_protected_materials(self, value, **options):
            assert value is materials
            calls.append(("materials", options))

    monkeypatch.setattr(attempt, "original_native_grant_inputs", extract)
    attempt._check_original_attempt_grants(Grants(), inputs, fixed_u_owner=live)
    assert [name for name, _ in calls] == ["extract", "materials"]
    assert all(("fixed_u_owner" in options) is with_owner for _, options in calls)
    if with_owner:
        assert all(options["fixed_u_owner"] is live for _, options in calls)


def test_initial_grant_hold_and_followup_use_original_whole_scope_child(monkeypatch, tmp_path):
    live, materials = object(), object()
    original = type("Original", (), {"requests": (), "expected_bindings": (), "materials": materials})()
    scope = object.__new__(attempt.NativeWholeScopeOwner)
    monkeypatch.setattr(attempt.NativeWholeScopeOwner, "original_fixed_u_input_owner", property(lambda self: live))
    monkeypatch.setattr(attempt.NativeWholeScopeOwner, "original_readonly_grant_requests", lambda self: ())
    calls = []

    def extract(inputs, **options):
        assert options == {"fixed_u_owner": live}
        return original

    class Grants:
        def validate_protected_materials(self, value, **options):
            assert value is materials and options == {"fixed_u_owner": live}
            calls.append("materials")

    grants = Grants()

    @contextmanager
    def hold(requests, **options):
        assert options["create_writable_directories"] is False
        assert options["creation_root"] is None
        calls.append("hold")
        yield grants

    monkeypatch.setattr(attempt, "original_native_grant_inputs", extract)
    monkeypatch.setattr(attempt, "hold_producer_grants", hold)
    with attempt._original_attempt_grants(
        None, batch=tmp_path, working=tmp_path / "work", output=tmp_path / "output",
        enabled=True, whole_scope=scope,
    ) as held:
        assert held is grants
        attempt._check_original_attempt_grants(held, None, fixed_u_owner=live)
    assert calls == ["hold", "materials", "materials"]
