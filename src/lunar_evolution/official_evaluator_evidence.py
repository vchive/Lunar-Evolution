"""Independent official-evaluator receipt boundary for local RSI fixtures."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any

from .candidate_evaluation_spec import canonical_json, strict_json

_PROTOCOL = "lunar-official-evaluator-receipt-v1"
_SHA = re.compile(r"^[0-9a-f]{64}$")
_MAX = 512 * 1024


class OfficialEvaluatorEvidenceError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = "official_evaluator_evidence_" + code
        super().__init__(self.code)


def _sha(value: object, field: str) -> str:
    if type(value) is not str or _SHA.fullmatch(value) is None:
        raise OfficialEvaluatorEvidenceError(f"{field}_invalid")
    return value


def _canonical(value: object) -> bytes:
    try:
        return canonical_json(value, maximum=_MAX)
    except Exception as exc:
        raise OfficialEvaluatorEvidenceError("canonical_invalid") from exc


@dataclass(frozen=True, slots=True)
class OfficialEvaluatorProfile:
    evaluator_id: str
    evaluator_version: str
    code_sha256: str
    config_sha256: str
    contract_sha256: str
    task_input_sha256: str
    holdout_sha256: str
    seed_sha256: str

    def __post_init__(self) -> None:
        for value, field in ((self.code_sha256, "code"), (self.config_sha256, "config"),
                             (self.contract_sha256, "contract"), (self.task_input_sha256, "task_input"),
                             (self.holdout_sha256, "holdout"), (self.seed_sha256, "seed")):
            _sha(value, field)
        if any(type(value) is not str or not value or len(value) > 256 or any(c in value for c in "\x00\r\n")
               for value in (self.evaluator_id, self.evaluator_version)):
            raise OfficialEvaluatorEvidenceError("identity_invalid")

    def to_dict(self) -> dict[str, str]:
        return {"evaluator_id": self.evaluator_id, "evaluator_version": self.evaluator_version,
                "code_sha256": self.code_sha256, "config_sha256": self.config_sha256,
                "contract_sha256": self.contract_sha256, "task_input_sha256": self.task_input_sha256,
                "holdout_sha256": self.holdout_sha256, "seed_sha256": self.seed_sha256}

    def digest(self) -> str:
        return hashlib.sha256(_canonical(self.to_dict())).hexdigest()


@dataclass(frozen=True, slots=True)
class OfficialEvaluationReceipt:
    profile: OfficialEvaluatorProfile
    request_sha256: str
    candidate_source_sha256: str
    execution_receipt_sha256: str
    publication_receipt_sha256: str
    outcome: str
    raw_verdict_sha256: str
    receipt_sha256: str | None = None

    def __post_init__(self) -> None:
        _sha(self.request_sha256, "request")
        for value, field in ((self.candidate_source_sha256, "candidate_source"),
                             (self.execution_receipt_sha256, "execution_receipt"),
                             (self.publication_receipt_sha256, "publication_receipt"),
                             (self.raw_verdict_sha256, "raw_verdict")):
            _sha(value, field)
        if self.outcome not in {"pass", "fail", "unresolved"}:
            raise OfficialEvaluatorEvidenceError("outcome_invalid")
        expected = self.digest()
        if self.receipt_sha256 is not None and self.receipt_sha256 != expected:
            raise OfficialEvaluatorEvidenceError("receipt_digest_mismatch")
        if self.receipt_sha256 is None:
            object.__setattr__(self, "receipt_sha256", expected)

    def to_dict(self) -> dict[str, Any]:
        return {"schema_version": "1", "protocol": _PROTOCOL, "profile": self.profile.to_dict(),
                "profile_sha256": self.profile.digest(), "request_sha256": self.request_sha256,
                "candidate_source_sha256": self.candidate_source_sha256,
                "execution_receipt_sha256": self.execution_receipt_sha256,
                "publication_receipt_sha256": self.publication_receipt_sha256,
                "outcome": self.outcome, "raw_verdict_sha256": self.raw_verdict_sha256,
                "receipt_sha256": self.receipt_sha256}

    def digest(self) -> str:
        return hashlib.sha256(_canonical({k: v for k, v in self.to_dict().items() if k != "receipt_sha256"})).hexdigest()

    @classmethod
    def from_dict(cls, value: object) -> OfficialEvaluationReceipt:
        if type(value) is not dict or set(value) != {"schema_version", "protocol", "profile", "profile_sha256", "request_sha256", "candidate_source_sha256", "execution_receipt_sha256", "publication_receipt_sha256", "outcome", "raw_verdict_sha256", "receipt_sha256"}:
            raise OfficialEvaluatorEvidenceError("wire_invalid")
        if value["schema_version"] != "1" or value["protocol"] != _PROTOCOL:
            raise OfficialEvaluatorEvidenceError("wire_invalid")
        profile = OfficialEvaluatorProfile(**value["profile"])
        if value["profile_sha256"] != profile.digest():
            raise OfficialEvaluatorEvidenceError("profile_drift")
        receipt = cls(profile, value["request_sha256"], value["candidate_source_sha256"], value["execution_receipt_sha256"], value["publication_receipt_sha256"], value["outcome"], value["raw_verdict_sha256"], value["receipt_sha256"])
        if strict_json(_canonical(receipt.to_dict()), maximum=_MAX) != receipt.to_dict():
            raise OfficialEvaluatorEvidenceError("noncanonical")
        return receipt


def verify_official_evaluation(
    receipt: OfficialEvaluationReceipt, *, request_sha256: str, contract_sha256: str,
    evaluator_sha256: str, candidate_source_sha256: str, execution_receipt_sha256: str,
    publication_receipt_sha256: str, holdout_sha256: str | None = None,
) -> None:
    if not isinstance(receipt, OfficialEvaluationReceipt):
        raise OfficialEvaluatorEvidenceError("receipt_invalid")
    expected = (request_sha256, contract_sha256, evaluator_sha256, candidate_source_sha256,
                execution_receipt_sha256, publication_receipt_sha256)
    for value, field in zip(expected, ("request", "contract", "evaluator", "candidate_source", "execution_receipt", "publication_receipt")):
        _sha(value, field)
    if receipt.request_sha256 != request_sha256 or receipt.profile.contract_sha256 != contract_sha256:
        raise OfficialEvaluatorEvidenceError("binding_mismatch")
    if receipt.profile.code_sha256 != evaluator_sha256 or receipt.candidate_source_sha256 != candidate_source_sha256:
        raise OfficialEvaluatorEvidenceError("binding_mismatch")
    if receipt.execution_receipt_sha256 != execution_receipt_sha256 or receipt.publication_receipt_sha256 != publication_receipt_sha256:
        raise OfficialEvaluatorEvidenceError("binding_mismatch")
    if holdout_sha256 is not None and receipt.profile.holdout_sha256 != holdout_sha256:
        raise OfficialEvaluatorEvidenceError("holdout_mismatch")
    if receipt.outcome != "pass":
        raise OfficialEvaluatorEvidenceError("not_pass")


__all__ = ["OfficialEvaluationReceipt", "OfficialEvaluatorEvidenceError", "OfficialEvaluatorProfile", "verify_official_evaluation"]
