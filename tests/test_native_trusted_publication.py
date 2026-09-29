from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest

from test_native_trusted_preparation import materialized

from lunar_evolution import native_trusted_publication as publication
from lunar_evolution.native_trusted_preparation import persist_native_trusted_preparation
from lunar_evolution.producer_bundle_transaction import (
    NativeProducerBundleTransactionResult,
)


def _prepared(tmp_path, monkeypatch):
    output, _envelope, arguments = materialized(tmp_path, monkeypatch)
    result = persist_native_trusted_preparation(tmp_path, **arguments)
    authority = publication.build_native_trusted_publication_authority(
        result, intent=arguments["intent"], attestation=arguments["attestation"],
        token="offline-secret-token", nonce="nonce-pub-001",
    )
    return output, arguments, result, authority


def test_build_binds_complete_offline_import_evidence_and_never_serializes_token(
    tmp_path, monkeypatch,
):
    _output, arguments, preparation, authority = _prepared(tmp_path, monkeypatch)
    record = authority.to_dict()
    assert authority.scope == "offline_import"
    assert record["token_sha256"] != "offline-secret-token"
    assert "offline-secret-token" not in str(record)
    assert record["launch_id"] == arguments["intent"].launch_id
    assert record["parent_task_id"] == arguments["intent"].parent_task_id
    assert record["task_id"] == arguments["intent"].task_id
    assert record["attestation_sha256"] == arguments["attestation"].attestation_sha256
    assert record["preparation_sha256"] == preparation.receipt_sha256
    assert authority.authority_sha256 == authority.digest()


def test_offline_import_transaction_consumes_only_terminal_success(
    tmp_path, monkeypatch,
):
    output, arguments, preparation, authority = _prepared(tmp_path, monkeypatch)
    calls = []

    def fake_transaction(*args, **kwargs):
        calls.append((args, kwargs))
        return SimpleNamespace(publication_status="published")

    monkeypatch.setattr(
        "lunar_evolution.producer_bundle_transaction.run_native_producer_bundle_publication_transaction",
        fake_transaction,
    )
    result = publication.run_native_trusted_output_publication_transaction(
        tmp_path, object(), intent=arguments["intent"], attestation=arguments["attestation"],
        artifact=arguments["artifact"], contract=arguments["contract"], groups=arguments["groups"],
        preparation_receipt_sha256=preparation.receipt_sha256, publication_authority=authority,
        authority_token="offline-secret-token", journal_id=arguments["intent"].journal_id,
    )
    assert result.publication_status == "published"
    assert len(calls) == 1
    marker = output.parent / "native-trusted-publication-authority-consumed.json"
    assert marker.is_file()
    assert '"publication_status":"published"' in marker.read_text(encoding="utf-8")
    with pytest.raises(publication.NativeTrustedPublicationError, match="authority_replay"):
        publication.run_native_trusted_output_publication_transaction(
            tmp_path, object(), intent=arguments["intent"], attestation=arguments["attestation"],
            artifact=arguments["artifact"], contract=arguments["contract"], groups=arguments["groups"],
            preparation_receipt_sha256=preparation.receipt_sha256, publication_authority=authority,
            authority_token="offline-secret-token", journal_id=arguments["intent"].journal_id,
        )
    assert len(calls) == 1


def test_transaction_failure_keeps_authority_unconsumed(tmp_path, monkeypatch):
    output, arguments, preparation, authority = _prepared(tmp_path, monkeypatch)

    def failed(*args, **kwargs):
        raise RuntimeError("unknown")

    monkeypatch.setattr(
        "lunar_evolution.producer_bundle_transaction.run_native_producer_bundle_publication_transaction",
        failed,
    )
    with pytest.raises(publication.NativeTrustedPublicationError, match="transaction_failed"):
        publication.run_native_trusted_output_publication_transaction(
            tmp_path, object(), intent=arguments["intent"], attestation=arguments["attestation"],
            artifact=arguments["artifact"], contract=arguments["contract"], groups=arguments["groups"],
            preparation_receipt_sha256=preparation.receipt_sha256, publication_authority=authority,
            authority_token="offline-secret-token", journal_id=arguments["intent"].journal_id,
        )
    assert not (output.parent / "native-trusted-publication-authority-consumed.json").exists()


@pytest.mark.parametrize("bad_token", ["wrong-token", "", "x" * 5000])
def test_wrong_token_rejected_before_transaction(tmp_path, monkeypatch, bad_token):
    output, arguments, preparation, authority = _prepared(tmp_path, monkeypatch)
    with pytest.raises(publication.NativeTrustedPublicationError, match="token_"):
        publication.run_native_trusted_output_publication_transaction(
            tmp_path, object(), intent=arguments["intent"], attestation=arguments["attestation"],
            artifact=arguments["artifact"], contract=arguments["contract"], groups=arguments["groups"],
            preparation_receipt_sha256=preparation.receipt_sha256, publication_authority=authority,
            authority_token=bad_token, journal_id=arguments["intent"].journal_id,
        )
    assert not (output.parent / "native-trusted-publication-authority-consumed.json").exists()


@pytest.mark.parametrize("field", ["parent_task_id", "task_id", "run_id"])
def test_authority_identity_drift_rejected(tmp_path, monkeypatch, field):
    output, arguments, preparation, authority = _prepared(tmp_path, monkeypatch)
    changed = replace(authority)
    object.__setattr__(changed, field, f"changed-{field}")
    object.__setattr__(changed, "authority_sha256", changed.digest())
    with pytest.raises(publication.NativeTrustedPublicationError, match="binding|preparation|attestation|authority_mismatch"):
        publication.run_native_trusted_output_publication_transaction(
            tmp_path, object(), intent=arguments["intent"], attestation=arguments["attestation"],
            artifact=arguments["artifact"], contract=arguments["contract"], groups=arguments["groups"],
            preparation_receipt_sha256=preparation.receipt_sha256, publication_authority=changed,
            authority_token="offline-secret-token", journal_id=arguments["intent"].journal_id,
        )
    assert not (output.parent / "native-trusted-publication-authority-consumed.json").exists()


def test_authority_rejects_production_scope():
    with pytest.raises(publication.NativeTrustedPublicationError, match="scope"):
        publication.NativeTrustedPublicationAuthority(
            **{field: "a" * 64 for field in (
                "attestation_sha256", "preparation_sha256", "intent_sha256",
                "process_terminal_sha256", "output_capture_sha256", "envelope_bytes_sha256",
                "admission_plan_sha256", "broker_evidence_sha256", "executable_sha256",
                "token_sha256",
            )},
            authority_id="authority", launch_id="launch", journal_id="journal", run_id="run",
            parent_task_id="parent", task_id="task", executable_size=1,
            executable_device=1, executable_inode=1, executable_mtime_ns=1,
            executable_ctime_ns=1, nonce="nonce", authority_sha256="a" * 64,
            scope="production",
        )
