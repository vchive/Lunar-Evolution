"""Exact storage budgets for private reserved checkpoints; never write authority."""

from __future__ import annotations

from .candidate_evaluation_spec import canonical_json
from .rsi_brs_rejection_ready_ledger import _TABLES, _row_size
from .rsi_learning import RSILearningError

MAX_RESERVED_CHECKPOINT_ROW_BYTES = 128 * 1024
_MAX_CHECKPOINT_PAYLOAD_BYTES = 8 * 1024 * 1024
# The existing raw reader counts 16 bytes per row and eight per column.
# A subsequent checkpoint additionally contains an eight-byte revision, two
# 64-byte digests and its original run ID. These are reservations for future
# fields, not substituted observations of an existing row.
_CHECKPOINT_FIXED_TAIL_BYTES = 192
# A subsequent run record has nine columns, an integer and three digests.
# utc_now() uses UTC ISO format, at most 32 ASCII bytes including microseconds.
_RUN_FIXED_TAIL_BYTES = 320


def canonical_checkpoint_text(state: object) -> str:
    """Use the same compact UTF-8 representation as checkpoint hash inputs."""
    return canonical_json(state, maximum=_MAX_CHECKPOINT_PAYLOAD_BYTES).decode("utf-8")


def reserved_checkpoint_payload_limit(run_id: str) -> int:
    """Reserve the complete metadata of a future noninitial checkpoint row."""
    if type(run_id) is not str:
        raise RSILearningError("rsi_controller_checkpoint_invalid")
    return MAX_RESERVED_CHECKPOINT_ROW_BYTES - _CHECKPOINT_FIXED_TAIL_BYTES - len(run_id.encode("utf-8"))


def reserved_run_payload_limit(run_id: str, state: str = "completed") -> int:
    """Reserve known run fields and the bounded future UTC timestamp."""
    if type(run_id) is not str or type(state) is not str:
        raise RSILearningError("rsi_controller_checkpoint_invalid")
    return (MAX_RESERVED_CHECKPOINT_ROW_BYTES - _RUN_FIXED_TAIL_BYTES
            - len(run_id.encode("utf-8")) - len("run") - len(state.encode("utf-8")))


def _validate_row(row: tuple, specification: tuple) -> int:
    try:
        return _row_size(row, specification)
    except RSILearningError as exc:
        if str(exc).endswith("_capacity_exceeded"):
            raise RSILearningError("rsi_controller_checkpoint_capacity_exceeded") from exc
        raise


def validate_reserved_checkpoint_row(
    run_id: str, revision: int, parent_sha256: str | None, payload_text: str, checkpoint_sha256: str,
) -> int:
    """Check the actual pending SQL row using the unchanged raw reader meter."""
    return _validate_row((run_id, revision, parent_sha256, payload_text, checkpoint_sha256), _TABLES[1])


def validate_reserved_record_row(
    logical_id: str, revision: int, kind: str, state: str, request_sha256: str,
    parent_record_sha256: str | None, payload_text: str, record_sha256: str, created_at: str,
) -> int:
    """Keep original and terminal reserved run rows readable by the same meter."""
    return _validate_row((logical_id, revision, kind, state, request_sha256, parent_record_sha256,
                          payload_text, record_sha256, created_at), _TABLES[0])
