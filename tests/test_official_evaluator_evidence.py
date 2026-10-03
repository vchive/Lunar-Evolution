from __future__ import annotations

from dataclasses import replace

import pytest

from lunar_evolution.official_evaluator_evidence import (
    OfficialEvaluationReceipt,
    OfficialEvaluatorEvidenceError,
    OfficialEvaluatorProfile,
    verify_official_evaluation,
)

H = "a" * 64

def profile() -> OfficialEvaluatorProfile:
    return OfficialEvaluatorProfile("local-evaluator", "1", H, "b" * 64, "c" * 64, "d" * 64, "e" * 64, "f" * 64)

def receipt(outcome="pass") -> OfficialEvaluationReceipt:
    return OfficialEvaluationReceipt(profile(), H, "1" * 64, "2" * 64, "3" * 64, outcome, "4" * 64)

def test_receipt_roundtrip_and_exact_binding():
    item = receipt()
    assert OfficialEvaluationReceipt.from_dict(item.to_dict()) == item
    verify_official_evaluation(item, request_sha256=H, contract_sha256="c" * 64, evaluator_sha256=H,
                               candidate_source_sha256="1" * 64, execution_receipt_sha256="2" * 64,
                               publication_receipt_sha256="3" * 64, holdout_sha256="e" * 64)

def test_score_or_raw_verdict_drift_cannot_change_authority():
    item = receipt()
    with pytest.raises(OfficialEvaluatorEvidenceError, match="binding_mismatch"):
        verify_official_evaluation(item, request_sha256=H, contract_sha256="9" * 64, evaluator_sha256=H,
                                   candidate_source_sha256="1" * 64, execution_receipt_sha256="2" * 64,
                                   publication_receipt_sha256="3" * 64)
    with pytest.raises(OfficialEvaluatorEvidenceError, match="receipt_digest_mismatch"):
        replace(item, raw_verdict_sha256="5" * 64)

def test_nonpass_and_holdout_drift_fail_closed():
    with pytest.raises(OfficialEvaluatorEvidenceError, match="not_pass"):
        verify_official_evaluation(receipt("fail"), request_sha256=H, contract_sha256="c" * 64,
                                   evaluator_sha256=H, candidate_source_sha256="1" * 64,
                                   execution_receipt_sha256="2" * 64, publication_receipt_sha256="3" * 64)
    with pytest.raises(OfficialEvaluatorEvidenceError, match="holdout_mismatch"):
        verify_official_evaluation(receipt(), request_sha256=H, contract_sha256="c" * 64,
                                   evaluator_sha256=H, candidate_source_sha256="1" * 64,
                                   execution_receipt_sha256="2" * 64, publication_receipt_sha256="3" * 64,
                                   holdout_sha256="9" * 64)
