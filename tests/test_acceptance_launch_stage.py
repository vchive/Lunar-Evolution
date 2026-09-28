"""The controller's provider-free one-attempt launch stage."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from test_acceptance_launch import _registered_origin

from lunar_evolution import acceptance_launch_stage, stage_acceptance_attempt
from lunar_evolution.acceptance_attempt_gate import AcceptanceAttemptGateError
from lunar_evolution.acceptance_launch import AcceptanceCampaignError


def _stage(fixture):
    checkout, parent, _manifest, registration_path, seal_path, _origin = fixture
    return stage_acceptance_attempt(
        registration_path, seal_path, checkout_root=checkout, campaign_parent=parent,
    )


def test_stage_retains_single_provider_free_claim(tmp_path: Path) -> None:
    fixture = _registered_origin(tmp_path)
    _checkout, parent, manifest, _registration, _seal, _origin = fixture
    result = _stage(fixture)
    root = parent / manifest["campaign_root"]
    assert result["status"] == "attempt_started"
    assert result["attempt_claimed"] is True
    assert result["provider_started"] is False
    assert result["provider_call_made"] is False
    assert json.loads((root / "attempt-started.json").read_bytes()) == result
    assert json.loads((root / "admission.json").read_bytes())["admission_sha256"] == result["admission_sha256"]
    retained = (root / "attempt-started.json").read_bytes()

    with pytest.raises(AcceptanceCampaignError, match="^campaign_root_not_fresh$"):
        _stage(fixture)
    assert (root / "attempt-started.json").read_bytes() == retained


def test_stage_pre_admission_failure_does_not_reserve_campaign(tmp_path: Path) -> None:
    fixture = _registered_origin(tmp_path)
    checkout, parent, manifest, _registration, _seal, _origin = fixture
    (checkout / "unexpected").write_bytes(b"dirty")
    with pytest.raises(AcceptanceCampaignError):
        _stage(fixture)
    assert not os.path.lexists(parent / manifest["campaign_root"])


def test_stage_revalidation_failure_keeps_reserved_campaign(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = _registered_origin(tmp_path)
    _checkout, parent, manifest, _registration, _seal, _origin = fixture
    revalidate = acceptance_launch_stage.revalidate_acceptance_campaign

    def tamper_then_revalidate(*args, **kwargs):
        root = parent / manifest["campaign_root"]
        (root / "materials" / "task.bin").write_bytes(b"changed")
        return revalidate(*args, **kwargs)

    monkeypatch.setattr(acceptance_launch_stage, "revalidate_acceptance_campaign", tamper_then_revalidate)
    with pytest.raises(AcceptanceCampaignError, match="^campaign_admission_incomplete$"):
        _stage(fixture)
    root = parent / manifest["campaign_root"]
    assert root.exists()
    assert not (root / "attempt-started.json").exists()
    with pytest.raises(AcceptanceCampaignError, match="^campaign_root_not_fresh$"):
        _stage(fixture)


def test_stage_claim_failure_keeps_reserved_campaign(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = _registered_origin(tmp_path)
    _checkout, parent, manifest, _registration, _seal, _origin = fixture
    claim = acceptance_launch_stage.claim_acceptance_attempt

    def occupied_claim(*args, **kwargs):
        root = parent / manifest["campaign_root"]
        (root / "attempt-started.json").write_bytes(b"occupied")
        return claim(*args, **kwargs)

    monkeypatch.setattr(acceptance_launch_stage, "claim_acceptance_attempt", occupied_claim)
    with pytest.raises(AcceptanceAttemptGateError, match="^attempt_claim_exists$"):
        _stage(fixture)
    root = parent / manifest["campaign_root"]
    assert (root / "attempt-started.json").read_bytes() == b"occupied"
    with pytest.raises(AcceptanceCampaignError, match="^campaign_root_not_fresh$"):
        _stage(fixture)


def test_stage_rechecks_post_claim_inventory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fixture = _registered_origin(tmp_path)
    _checkout, parent, manifest, _registration, _seal, _origin = fixture
    claim = acceptance_launch_stage.claim_acceptance_attempt

    def claim_then_tamper(*args, **kwargs):
        result = claim(*args, **kwargs)
        (parent / manifest["campaign_root"] / "unexpected").write_bytes(b"changed")
        return result

    monkeypatch.setattr(acceptance_launch_stage, "claim_acceptance_attempt", claim_then_tamper)
    with pytest.raises(AcceptanceAttemptGateError, match="^attempt_inventory_changed$"):
        _stage(fixture)
    root = parent / manifest["campaign_root"]
    assert (root / "attempt-started.json").exists()
    assert (root / "unexpected").read_bytes() == b"changed"
