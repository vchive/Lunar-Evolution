"""Provider-free create-only single-attempt claim tests."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_acceptance_launch import _registered_origin

from lunar_evolution.acceptance_attempt_gate import (
    AcceptanceAttemptGateError,
    claim_acceptance_attempt,
    verify_acceptance_attempt_claim,
)
from lunar_evolution.acceptance_launch import (
    prepare_acceptance_campaign,
    revalidate_acceptance_campaign,
)


def _ready(tmp_path: Path):
    fixture = _registered_origin(tmp_path)
    checkout, parent, _manifest, registration_path, seal_path, _origin = fixture
    prepared = prepare_acceptance_campaign(
        registration_path, seal_path, checkout_root=checkout, campaign_parent=parent,
    )
    ready = revalidate_acceptance_campaign(
        registration_path, seal_path, checkout_root=checkout, campaign_parent=parent,
    )
    return fixture, prepared, ready


def test_claim_is_create_only_and_provider_free(tmp_path: Path) -> None:
    fixture, prepared, ready = _ready(tmp_path)
    _checkout, parent, manifest, _registration, _seal, _origin = fixture
    claim = claim_acceptance_attempt(ready, campaign_parent=parent)
    root = parent / manifest["campaign_root"]
    assert claim["status"] == "attempt_started"
    assert claim["attempt_claimed"] is True
    assert claim["provider_started"] is False
    assert claim["provider_call_made"] is False
    assert claim["admission_sha256"] == prepared["admission_sha256"]
    raw = (root / "attempt-started.json").read_bytes()
    assert raw == json.dumps(claim, sort_keys=True, separators=(",", ":")).encode()
    assert verify_acceptance_attempt_claim(claim, campaign_parent=parent) == claim
    with pytest.raises(AcceptanceAttemptGateError, match="^attempt_claim_exists$"):
        claim_acceptance_attempt(ready, campaign_parent=parent)
    assert (root / "attempt-started.json").read_bytes() == raw


def test_claim_requires_exact_revalidated_admission(tmp_path: Path) -> None:
    fixture, _prepared, ready = _ready(tmp_path)
    _checkout, parent, _manifest, _registration, _seal, _origin = fixture
    forged = dict(ready)
    forged["admission"] = dict(ready["admission"])
    forged["admission"]["remote_commit"] = "f" * 40
    with pytest.raises(AcceptanceAttemptGateError, match="^attempt_admission_mismatch$"):
        claim_acceptance_attempt(forged, campaign_parent=parent)


def test_claim_rejects_without_ready_gate(tmp_path: Path) -> None:
    _fixture, _prepared, ready = _ready(tmp_path)
    with pytest.raises(AcceptanceAttemptGateError, match="^attempt_revalidation_required$"):
        claim_acceptance_attempt({**ready, "launch_allowed": False}, campaign_parent=tmp_path)


@pytest.mark.parametrize("tamper", ["claim", "material", "extra", "symlink"])
def test_postclaim_inspection_fails_closed_on_changed_evidence(tmp_path: Path, tamper: str) -> None:
    fixture, _prepared, ready = _ready(tmp_path)
    _checkout, parent, manifest, _registration, _seal, _origin = fixture
    claim = claim_acceptance_attempt(ready, campaign_parent=parent)
    root = parent / manifest["campaign_root"]
    if tamper == "claim":
        (root / "attempt-started.json").write_bytes(b"{}")
    elif tamper == "material":
        (root / "materials/task.bin").write_bytes(b"changed")
    elif tamper == "extra":
        (root / "unexpected").write_bytes(b"extra")
    else:
        target = root / "materials/task.bin"
        target.unlink()
        target.symlink_to(root / "registration.json")
    with pytest.raises(AcceptanceAttemptGateError):
        verify_acceptance_attempt_claim(claim, campaign_parent=parent)


def test_postclaim_inspection_requires_original_claim(tmp_path: Path) -> None:
    fixture, _prepared, ready = _ready(tmp_path)
    _checkout, parent, _manifest, _registration, _seal, _origin = fixture
    claim = claim_acceptance_attempt(ready, campaign_parent=parent)
    with pytest.raises(AcceptanceAttemptGateError, match="^attempt_claim_invalid$"):
        verify_acceptance_attempt_claim({**claim, "provider_started": True}, campaign_parent=parent)
