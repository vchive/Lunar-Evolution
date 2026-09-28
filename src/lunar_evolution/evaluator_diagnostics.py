"""Bounded controller observations of local evaluator preparation failures."""
from __future__ import annotations

from dataclasses import dataclass

RESPONSE_STAGES = frozenset({"compiler_response", "auditor_response"})
PREFLIGHT_STAGES = frozenset({"compiler_preflight", "auditor_preflight"})
LOCAL_FAILURE_STAGES = RESPONSE_STAGES | PREFLIGHT_STAGES
_PROBE_REASONS = frozenset({
    "output_schema_invalid", "file_set_invalid", "process_failed", "report_invalid",
    "validity_mismatch", "constraint_code_missing",
})
_KEYS = frozenset({"schema_version", "stage", "reason", "probe_index", "input_index", "order_index"})


@dataclass(frozen=True)
class EvaluatorPreparationDiagnostic:
    """Indices are one-based suite/contract positions, never generated identifiers."""

    stage: str
    reason: str
    probe_index: int | None = None
    input_index: int | None = None
    order_index: int | None = None

    def __post_init__(self) -> None:
        if type(self.stage) is not str or self.stage not in LOCAL_FAILURE_STAGES:
            raise ValueError("invalid evaluator diagnostic stage")
        if type(self.reason) is not str:
            raise ValueError("invalid evaluator diagnostic reason")
        for value, maximum in ((self.probe_index, 64), (self.input_index, 32), (self.order_index, 64)):
            if value is not None and (type(value) is not int or not 1 <= value <= maximum):
                raise ValueError("invalid evaluator diagnostic index")
        if self.stage in RESPONSE_STAGES:
            reasons = ({"response_invalid", "response_envelope_invalid",
                        "response_probes_invalid", "response_suite_invalid"}
                       if self.stage == "auditor_response" else {"response_invalid"})
            valid = (self.reason in reasons and self.probe_index is None
                     and self.input_index is None and self.order_index is None)
        elif self.reason == "input_format_invalid":
            valid = self.probe_index is not None and self.input_index is not None and self.order_index is None
        elif self.reason in _PROBE_REASONS:
            valid = self.probe_index is not None and self.input_index is None and self.order_index is None
        elif self.reason == "score_order_mismatch":
            valid = self.probe_index is None and self.input_index is None and self.order_index is not None
        elif self.reason in {"evidence_changed", "preflight_failed"}:
            valid = self.input_index is None and self.order_index is None
        else:
            valid = False
        if not valid:
            raise ValueError("invalid evaluator diagnostic fields")

    def to_dict(self) -> dict[str, object]:
        # Revalidate even a frozen instance before publishing optional observations.
        self.__post_init__()
        return {"schema_version": "1", "stage": self.stage, "reason": self.reason,
                "probe_index": self.probe_index, "input_index": self.input_index,
                "order_index": self.order_index}

    @classmethod
    def from_dict(cls, value: object) -> EvaluatorPreparationDiagnostic:
        if type(value) is not dict or set(value) != _KEYS or value.get("schema_version") != "1":
            raise ValueError("invalid evaluator diagnostic shape")
        return cls(**{key: value[key] for key in _KEYS - {"schema_version"}})


__all__ = ["LOCAL_FAILURE_STAGES", "EvaluatorPreparationDiagnostic"]
