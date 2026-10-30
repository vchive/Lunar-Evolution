"""Origin-only late evidence preserves the original unknown/native work fence."""

import pytest
from external_worker_fixtures import (
    PLAN,
    PROFILE,
    RECEIPT,
    assert_no_native_authority,
    worker_harness,
)

from lunar_evolution.external_worker_assignment import WorkerAssignmentError
from lunar_evolution.external_worker_origin import WorkerOriginContext, sign_worker_origin


def test_explicit_unknown_reconciliation_appends_once_without_native_completion(tmp_path):
    h = worker_harness(tmp_path)
    raw = sign_worker_origin(key=h.key,
        context=WorkerOriginContext.from_dict(h.assignment["context"]),
        profile_sha256=PROFILE, receipt=RECEIPT)
    with h.ledger.controller_lock("run-local"):
        original = h.book.mark_unknown(h.request, plan_sha256=PLAN,
            expected_controller_checkpoint_sha256=h.checkpoint, reason_code="channel_lost")
        h.book.reconcile_origin_receipt(h.request, plan_sha256=PLAN,
            expected_controller_checkpoint_sha256=h.checkpoint, raw=raw, receipt=RECEIPT)
        with pytest.raises(WorkerAssignmentError, match="original_unknown_required"):
            h.book.reconcile_origin_receipt(h.request, plan_sha256=PLAN,
                expected_controller_checkpoint_sha256=h.checkpoint, raw=raw, receipt=RECEIPT)
    state = h.book.inspect(h.request.episode_id)
    assert state["status"] == "receipt_authenticated_after_unknown"
    assert state["settlement"] == original
    assert state["reconciliation"]["verified_origin"]["receipt_sha256"] != "0" * 64
    assert_no_native_authority(h)


def test_reconciliation_refuses_ordinary_assigned_work(tmp_path):
    h = worker_harness(tmp_path)
    raw = sign_worker_origin(key=h.key,
        context=WorkerOriginContext.from_dict(h.assignment["context"]),
        profile_sha256=PROFILE, receipt=RECEIPT)
    with (
        h.ledger.controller_lock("run-local"),
        pytest.raises(WorkerAssignmentError, match="original_unknown_required"),
    ):
        h.book.reconcile_origin_receipt(h.request, plan_sha256=PLAN,
            expected_controller_checkpoint_sha256=h.checkpoint, raw=raw, receipt=RECEIPT)
    assert h.book.inspect(h.request.episode_id)["status"] == "assigned"
