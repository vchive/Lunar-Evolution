"""Provider-free BRS rejection C1/P/C2 composition adapter."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_rsi_native_rejection import rejection_evidence

from lunar_evolution import rsi_python_brs_rejection as composition
from lunar_evolution.rsi_brs_publication_lineage import _BRSLineageCheckpointOwner
from lunar_evolution.rsi_native_rejection import NativeRSIRejectionFilePin
from lunar_evolution.rsi_publication_lineage import RSIPublicationLineage


def _owner(evidence, tmp_path):
    owner = object.__new__(_BRSLineageCheckpointOwner)
    raw_policy = json.dumps({
        "protocol": "lunar-rsi-brs-lineage-checkpoint-v1", "mode": "brs", "max_workers": 1,
        "online_publication": False, "production_admission": False,
    }, separators=(",", ":")).encode()
    state = {"producer_publication_lineage": {"head": None}}
    gateway = SimpleNamespace(_ledger_identity=evidence.ledger_identity)
    for name, value in {
        "_policy_bytes": raw_policy, "_run_id": evidence.plan.run_id, "_request": evidence.plan.request,
        "_plan": evidence.plan, "_ledger": object(), "_gateway": gateway, "_workspace": Path(tmp_path),
        "_head": evidence.lineage.checkpoint_sha256, "_state": state, "_phase": "rejected",
    }.items():
        object.__setattr__(owner, name, value)
    lineage = object.__new__(RSIPublicationLineage)
    for name, value in {
        "_run_id": evidence.plan.run_id, "_request": evidence.plan.request, "_plan": evidence.plan,
        "_ledger": owner._ledger, "_gateway": gateway, "_workspace": Path(tmp_path),
        "_head": evidence.lineage.checkpoint_sha256, "_claim": evidence.claim,
    }.items():
        object.__setattr__(lineage, name, value)
    return owner, lineage


def test_private_adapter_orders_c1_p_c2_and_keeps_public_policy_disabled(tmp_path, monkeypatch):
    evidence = rejection_evidence()
    owner, lineage = _owner(evidence, tmp_path)
    pin = NativeRSIRejectionFilePin("native-rsi.rejection-provenance.json", "b" * 64, 64,
                                    1, 2, 1, 3)
    persisted = replace(evidence)
    object.__setattr__(persisted, "provenance_sha256", "b" * 64)
    object.__setattr__(persisted, "provenance_file_pin", pin)
    events = []
    monkeypatch.setattr(RSIPublicationLineage, "rejection_provenance_binding",
                        lambda _self: events.append("C1") or evidence.lineage)
    monkeypatch.setattr(composition, "persist_native_rsi_rejection_provenance",
                        lambda _batch, _evidence, *, retained_bytes: events.append(("P", retained_bytes))
                        or ("b" * 64, pin))
    monkeypatch.setattr(composition, "read_native_rsi_rejection_provenance",
                        lambda _batch, *, expected_file_pin: events.append("P-read") or persisted)
    monkeypatch.setattr(RSIPublicationLineage, "acknowledge_rejection_provenance",
                        lambda _self, _evidence, _pin: events.append("C2"))
    monkeypatch.setattr(RSIPublicationLineage, "rejection_provenance_file_pin",
                        lambda _self: events.append("C2-read") or pin)

    result = composition.compose_brs_rejection_c1_p_c2(owner, lineage, evidence)

    assert events == ["C1", ("P", evidence.lineage.retained_bytes), "P-read", "C2", "C2-read"]
    assert result.lineage == evidence.lineage
    assert result.evidence == persisted
    assert result.file_pin == pin
    assert json.loads(owner._policy_bytes)["online_publication"] is False


@pytest.mark.parametrize("mutation", ["owner", "lineage", "head", "ledger", "policy", "published"])
def test_adapter_refuses_foreign_owner_or_drift_before_p(tmp_path, monkeypatch, mutation):
    evidence = rejection_evidence()
    owner, lineage = _owner(evidence, tmp_path)
    if mutation == "owner":
        owner = object()
    elif mutation == "lineage":
        lineage = object()
    elif mutation == "head":
        owner._head = "c" * 64
    elif mutation == "ledger":
        lineage._ledger = object()
    elif mutation == "policy":
        owner._policy_bytes = b'{"mode":"brs","max_workers":1,"online_publication":true,"production_admission":false}'
    elif mutation == "published":
        owner._state = {"producer_publication_lineage": {"head": {"journal_id": "foreign"}}}
    touched = []
    monkeypatch.setattr(composition, "persist_native_rsi_rejection_provenance",
                        lambda *_args, **_kwargs: touched.append("P"))
    with pytest.raises(composition.BRSRejectionCompositionError):
        composition.compose_brs_rejection_c1_p_c2(owner, lineage, evidence)
    assert touched == []


def test_adapter_shape_checks_p_readback_before_callback_methods(tmp_path, monkeypatch):
    evidence = rejection_evidence()
    owner, lineage = _owner(evidence, tmp_path)
    pin = NativeRSIRejectionFilePin("native-rsi.rejection-provenance.json", "b" * 64, 64,
                                    1, 2, 1, 3)
    called = []
    callback = SimpleNamespace(to_dict=lambda: called.append("readback") or evidence.to_dict())
    monkeypatch.setattr(RSIPublicationLineage, "rejection_provenance_binding",
                        lambda _self: evidence.lineage)
    monkeypatch.setattr(composition, "persist_native_rsi_rejection_provenance",
                        lambda *_args, **_kwargs: ("b" * 64, pin))
    monkeypatch.setattr(composition, "read_native_rsi_rejection_provenance",
                        lambda *_args, **_kwargs: callback)

    with pytest.raises(composition.BRSRejectionCompositionError):
        composition.compose_brs_rejection_c1_p_c2(owner, lineage, evidence)
    assert called == []
