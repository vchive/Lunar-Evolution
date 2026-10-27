"""Local once-only assignment/HMAC journal; no worker, model or evaluator runs."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import replace
from types import SimpleNamespace

import pytest

from lunar_evolution import external_worker_assignment as assignment_module
from lunar_evolution.external_worker_assignment import (
    ExternalWorkerAssignments,
    WorkerAssignmentError,
)
from lunar_evolution.external_worker_origin import (
    WorkerOriginContext,
    WorkerOriginKey,
    WorkerOriginRegistry,
    sign_worker_origin,
    verify_worker_origin,
)
from lunar_evolution.rsi_gateway import SolverRequest
from lunar_evolution.rsi_store import RSILedger

_PLAN = "a" * 64
_PROFILE = "e" * 64
_SECRET = b"assignment-fixture-worker-secret-1234567890"
_RECEIPT = b'{"fixture":"exact original receipt bytes"}\n'
_ERROR = r"assignment_|origin_|controller_"


def make_request(episode_id="assignment-episode"):
    return SolverRequest.build(
        episode_id=episode_id, contract_sha256="1" * 64, evaluator_sha256="2" * 64,
        environment_sha256="3" * 64, memory_snapshot_sha256="4" * 64,
        solver_id="fixture", solver_settings={"iterations": 1},
        budget={"wall_timeout_seconds": 10}, practice_charter={"goal": "local fixture"},
    )


def _key():
    return WorkerOriginKey("worker-1", "host-1", "boot-1", "key-1", _SECRET)


def _second_key():
    return WorkerOriginKey("worker-2", "host-2", "boot-2", "key-2", b"second-assignment-worker-secret-123456")


def _book(store, registry, *, controller_id="controller-1", run_id="run-1", task_id="task-1"):
    return ExternalWorkerAssignments(
        store, controller_id=controller_id, run_id=run_id, task_id=task_id, registry=registry,
    )


def _setup(tmp_path, *, claim=True):
    store = RSILedger(tmp_path / "rsi.sqlite3")
    request = make_request()
    key = _key()
    registry = WorkerOriginRegistry([key, _second_key()])
    with store.controller_lock("run-1"):
        checkpoint = store.write_controller_checkpoint(
            "run-1", {"fixture": "original controller state"}, expected_sha256=None,
        )
        expected_claim = store.claim_native_episode(
            request, plan_sha256=_PLAN, controller_run_id="run-1",
            expected_controller_checkpoint_sha256=checkpoint,
        ) if claim else None
    return SimpleNamespace(
        store=store, request=request, key=key, registry=registry,
        claim=expected_claim, original_checkpoint=checkpoint,
        book=_book(store, registry), run_id="run-1",
    )


@pytest.fixture
def harness(tmp_path):
    return _setup(tmp_path)


def _checkpoint(h):
    return h.store.controller_checkpoint(h.run_id)[0]


def _reserve_options(h):
    return {
        "plan_sha256": _PLAN, "profile_sha256": _PROFILE, "worker": h.key,
        "expected_native_claim": h.claim,
        "expected_controller_checkpoint_sha256": _checkpoint(h),
    }


def _reserve(h, **changes):
    options = {**_reserve_options(h), **changes}
    with h.store.controller_lock(h.run_id):
        return h.book.reserve_assignment(h.request, **options)


def _signed(h, snapshot, *, key=None, context=None, profile=_PROFILE, receipt=_RECEIPT):
    return sign_worker_origin(
        key=h.key if key is None else key,
        context=WorkerOriginContext.from_dict(snapshot["context"]) if context is None else context,
        profile_sha256=profile, receipt=receipt,
    )


def _record(h, raw, receipt=_RECEIPT, **changes):
    options = {
        "plan_sha256": _PLAN, "expected_controller_checkpoint_sha256": _checkpoint(h),
        "raw": raw, "receipt": receipt, **changes,
    }
    with h.store.controller_lock(h.run_id):
        return h.book.record_origin_receipt(h.request, **options)


def _unknown(h, reason="worker_disconnected", **changes):
    options = {
        "plan_sha256": _PLAN, "expected_controller_checkpoint_sha256": _checkpoint(h),
        "reason_code": reason, **changes,
    }
    with h.store.controller_lock(h.run_id):
        return h.book.mark_unknown(h.request, **options)


def _reopen(h):
    store = RSILedger(h.store.database)
    return SimpleNamespace(
        **{**vars(h), "store": store, "book": _book(store, h.registry)},
    )


def _rows(store):
    connection = sqlite3.connect(store.database)
    try:
        return tuple(connection.iterdump())
    finally:
        connection.close()


def _assert_no_native_publication(h):
    assert h.store.episode_result(h.request.episode_id) is None
    assert h.store.inspect_native_episode_claim(h.request, plan_sha256=_PLAN) == h.claim
    assert h.claim.status == "started"


def test_original_assignment_context_and_real_hmac_settle_exactly_once(harness):
    h = harness
    assert h.book.inspect(h.request.episode_id) is None
    snapshot = _reserve(h)
    assert set(snapshot) == {
        "status", "assignment_checkpoint_sha256", "binding", "context",
        "settlement_checkpoint_sha256", "settlement",
    }
    assert snapshot["status"] == "assigned"
    assert snapshot["settlement"] is None and snapshot["settlement_checkpoint_sha256"] is None
    context = WorkerOriginContext.from_dict(snapshot["context"])
    assert (context.controller_id, context.run_id, context.task_id, context.episode_id) == (
        "controller-1", "run-1", "task-1", h.request.episode_id,
    )
    assert context.context_kind == "native-claim"
    assert context.context_sha256 == h.claim.claim_sha256
    assert len(context.controller_challenge) == 64 and context.assignment_generation == 1
    raw = _signed(h, snapshot)
    independent = verify_worker_origin(
        raw, registry=h.registry, expected_context=context,
        expected_profile_sha256=_PROFILE, receipt=_RECEIPT,
    )
    result = _record(h, raw)
    assert result == {
        "outcome": "receipt_authenticated",
        "assignment_checkpoint_sha256": snapshot["assignment_checkpoint_sha256"],
        "verified_origin": independent.to_dict(),
    }
    settled = h.book.inspect(h.request.episode_id)
    assert settled["status"] == "receipt_authenticated" and settled["settlement"] == result
    assert settled["settlement_checkpoint_sha256"] is not None
    before = _rows(h.store)
    with pytest.raises(WorkerAssignmentError, match=_ERROR):
        _record(h, raw)
    with pytest.raises(WorkerAssignmentError, match=_ERROR):
        _reserve(h)
    assert _rows(h.store) == before
    _assert_no_native_publication(h)
    visible = json.dumps(settled) + repr(_rows(h.store))
    assert _SECRET.decode() not in visible
    assert _RECEIPT.decode() not in visible


def test_reopen_retains_original_challenge_and_consumed_receipt_gate(harness):
    h = harness
    snapshot = _reserve(h)
    raw = _signed(h, snapshot)
    reopened = _reopen(h)
    assert reopened.book.inspect(h.request.episode_id) == snapshot
    result = _record(reopened, raw)
    again = _reopen(reopened)
    assert again.book.inspect(h.request.episode_id)["settlement"] == result
    before = _rows(again.store)
    with pytest.raises(WorkerAssignmentError, match=_ERROR):
        _record(again, raw)
    with pytest.raises(WorkerAssignmentError, match=_ERROR):
        _reserve(again)
    assert _rows(again.store) == before
    _assert_no_native_publication(again)


def test_inspection_returns_detached_snapshots_without_consuming_or_reserving(harness):
    h = harness
    original = _reserve(h)
    before = _rows(h.store)
    inspected = h.book.inspect(h.request.episode_id)
    inspected["status"] = "unknown"
    inspected["binding"]["worker_id"] = "foreign-worker"
    inspected["context"]["controller_challenge"] = "f" * 64
    assert h.book.inspect(h.request.episode_id) == original
    assert _rows(h.store) == before


def test_unknown_is_a_permanent_gate_across_reopen_and_authentic_late_receipt(harness):
    h = harness
    original = _reserve(h)
    raw = _signed(h, original)
    result = _unknown(h)
    assert result == {
        "outcome": "unknown", "assignment_checkpoint_sha256": original["assignment_checkpoint_sha256"],
        "reason_code": "worker_disconnected",
    }
    reopened = _reopen(h)
    assert reopened.book.inspect(h.request.episode_id)["status"] == "unknown"
    before = _rows(reopened.store)
    for attempt in (lambda: _record(reopened, raw), lambda: _reserve(reopened), lambda: _unknown(reopened)):
        with pytest.raises(WorkerAssignmentError, match=_ERROR):
            attempt()
    assert _rows(reopened.store) == before
    _assert_no_native_publication(reopened)


@pytest.mark.parametrize("mutation", [
    "registered_other_worker", "profile", "context", "receipt", "mac", "noncanonical", "host",
])
def test_bad_origin_binding_or_receipt_refused_without_any_journal_write(harness, mutation):
    h = harness
    snapshot = _reserve(h)
    raw, receipt = _signed(h, snapshot), _RECEIPT
    if mutation == "registered_other_worker":
        raw = _signed(h, snapshot, key=_second_key())
    elif mutation == "profile":
        raw = _signed(h, snapshot, profile="f" * 64)
    elif mutation == "context":
        context = replace(WorkerOriginContext.from_dict(snapshot["context"]), assignment_generation=2)
        raw = _signed(h, snapshot, context=context)
    elif mutation == "receipt":
        receipt = _RECEIPT.rstrip(b"\n")
    elif mutation == "noncanonical":
        raw += b"\n"
    elif mutation == "host":
        raw = _signed(h, snapshot, key=replace(h.key, host_boot_id="foreign-boot"))
    else:
        wire = json.loads(raw)
        wire["mac_sha256"] = "0" * 64
        raw = json.dumps(wire, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    before = _rows(h.store)
    with pytest.raises(ValueError, match=_ERROR):
        _record(h, raw, receipt)
    assert _rows(h.store) == before
    assert h.book.inspect(h.request.episode_id) == snapshot
    _assert_no_native_publication(h)


@pytest.mark.parametrize("operation", ["reserve", "receipt", "unknown"])
def test_every_mutation_requires_original_same_ledger_controller_lock(harness, operation):
    h = harness
    snapshot = _reserve(h) if operation != "reserve" else None
    before = _rows(h.store)
    if operation == "reserve":
        call = lambda: h.book.reserve_assignment(h.request, **_reserve_options(h))
    elif operation == "receipt":
        call = lambda: h.book.record_origin_receipt(
            h.request, plan_sha256=_PLAN, expected_controller_checkpoint_sha256=_checkpoint(h),
            raw=_signed(h, snapshot), receipt=_RECEIPT,
        )
    else:
        call = lambda: h.book.mark_unknown(
            h.request, plan_sha256=_PLAN, expected_controller_checkpoint_sha256=_checkpoint(h),
            reason_code="worker_lost",
        )
    with pytest.raises(ValueError, match=_ERROR):
        call()
    with h.store.controller_lock("another-run"), pytest.raises(ValueError, match=_ERROR):
        call()
    reopened = _reopen(h)
    # A guard on a different RSILedger instance is not this assignment's guard.
    with reopened.store.controller_lock(h.run_id), pytest.raises(ValueError, match=_ERROR):
        call()
    assert _rows(h.store) == before


@pytest.mark.parametrize("operation", ["reserve", "receipt", "unknown"])
def test_stale_controller_checkpoint_refuses_without_mutation(harness, operation):
    h = harness
    snapshot = _reserve(h) if operation != "reserve" else None
    stale = _checkpoint(h)
    with h.store.controller_lock(h.run_id):
        h.store.write_controller_checkpoint(h.run_id, {"fixture": "advanced controller"}, expected_sha256=stale)
    before = _rows(h.store)
    with pytest.raises(ValueError, match=_ERROR):
        if operation == "reserve":
            _reserve(h, expected_controller_checkpoint_sha256=stale)
        elif operation == "receipt":
            _record(h, _signed(h, snapshot), expected_controller_checkpoint_sha256=stale)
        else:
            _unknown(h, expected_controller_checkpoint_sha256=stale)
    assert _rows(h.store) == before


def test_missing_original_controller_checkpoint_refuses_even_with_a_started_claim(tmp_path):
    h = _setup(tmp_path)
    book = _book(h.store, h.registry, run_id="missing-run")
    before = _rows(h.store)
    with h.store.controller_lock("missing-run"), pytest.raises(ValueError, match=_ERROR):
        book.reserve_assignment(
            h.request, **{**_reserve_options(h), "expected_controller_checkpoint_sha256": "c" * 64},
        )
    assert _rows(h.store) == before
    assert h.book.inspect(h.request.episode_id) is None


def test_missing_native_claim_refuses_a_matching_claim_from_another_ledger(tmp_path):
    h = _setup(tmp_path, claim=False)
    other = RSILedger(tmp_path / "another.sqlite3")
    h.claim = other.claim_native_episode(h.request, plan_sha256=_PLAN)
    before = _rows(h.store)
    with pytest.raises(ValueError, match=_ERROR):
        _reserve(h)
    assert _rows(h.store) == before
    assert h.book.inspect(h.request.episode_id) is None


@pytest.mark.parametrize("change", [
    {"status": "completed"}, {"request_sha256": "f" * 64}, {"plan_sha256": "f" * 64},
    {"claim_sha256": "f" * 64}, {"created_at": "changed original claim timestamp"},
])
def test_reservation_requires_exact_original_started_native_claim(harness, change):
    h = harness
    before = _rows(h.store)
    with pytest.raises(ValueError, match=_ERROR):
        _reserve(h, expected_native_claim=replace(h.claim, **change))
    assert _rows(h.store) == before
    assert h.book.inspect(h.request.episode_id) is None


@pytest.mark.parametrize("changed", ["same", "controller", "run", "task", "worker", "profile"])
def test_episode_namespace_cannot_be_reserved_again_through_another_owner_or_profile(harness, changed):
    h = harness
    original = _reserve(h)
    options = _reserve_options(h)
    book, run = h.book, h.run_id
    if changed == "controller":
        book = _book(h.store, h.registry, controller_id="controller-2")
    elif changed == "task":
        book = _book(h.store, h.registry, task_id="task-2")
    elif changed == "run":
        run = "run-2"
        with h.store.controller_lock(run):
            options["expected_controller_checkpoint_sha256"] = h.store.write_controller_checkpoint(
                run, {"fixture": "foreign original run"}, expected_sha256=None,
            )
        book = _book(h.store, h.registry, run_id=run)
    elif changed == "worker":
        options["worker"] = _second_key()
    elif changed == "profile":
        options["profile_sha256"] = "f" * 64
    before = _rows(h.store)
    with h.store.controller_lock(run), pytest.raises(WorkerAssignmentError, match=_ERROR):
        book.reserve_assignment(h.request, **options)
    assert _rows(h.store) == before
    assert h.book.inspect(h.request.episode_id) == original


@pytest.mark.parametrize("reason", ["", "Private secret text", "UPPER", "x" * 129, "has\nnewline", None])
def test_unknown_reason_requires_a_fixed_bounded_code_without_writes(harness, reason):
    h = harness
    snapshot = _reserve(h)
    before = _rows(h.store)
    with pytest.raises(WorkerAssignmentError, match=_ERROR):
        _unknown(h, reason)
    assert _rows(h.store) == before
    assert h.book.inspect(h.request.episode_id) == snapshot


def test_assignment_preparing_crash_keeps_global_recovery_gate_across_reopen(harness, monkeypatch):
    h = harness

    def interrupted():
        raise RuntimeError("injected challenge interruption")

    with monkeypatch.context() as patch:
        patch.setattr(assignment_module, "new_worker_origin_challenge", interrupted)
        with pytest.raises(RuntimeError, match="injected"):
            _reserve(h)
    snapshot = h.book.inspect(h.request.episode_id)
    assert snapshot["status"] == "preparing" and snapshot["context"] is None
    reopened = _reopen(h)
    assert reopened.book.inspect(h.request.episode_id) == snapshot
    before = _rows(reopened.store)
    with pytest.raises(WorkerAssignmentError, match=_ERROR):
        _reserve(reopened)
    with pytest.raises(WorkerAssignmentError, match=_ERROR):
        _unknown(reopened)
    assert _rows(reopened.store) == before
    _assert_no_native_publication(reopened)


def test_settlement_started_crash_never_replays_authentication_or_changes_unknown(harness, monkeypatch):
    h = harness
    assigned = _reserve(h)
    raw = _signed(h, assigned)
    original_write = h.store.write_controller_checkpoint

    def interrupted(run_id, state, *, expected_sha256):
        if (state.get("kind") == "durable_callback" and state.get("status") == "completed"
                and "assignment_checkpoint_sha256" in state.get("binding", {})):
            raise RuntimeError("injected settlement completion interruption")
        return original_write(run_id, state, expected_sha256=expected_sha256)

    with monkeypatch.context() as patch:
        patch.setattr(h.store, "write_controller_checkpoint", interrupted)
        with pytest.raises(RuntimeError, match="injected"):
            _record(h, raw)
    snapshot = h.book.inspect(h.request.episode_id)
    assert snapshot["status"] == "settlement_recovery_required"
    assert snapshot["context"] == assigned["context"] and snapshot["settlement"] is None
    reopened = _reopen(h)
    assert reopened.book.inspect(h.request.episode_id) == snapshot
    before = _rows(reopened.store)
    for attempt in (lambda: _record(reopened, raw), lambda: _unknown(reopened), lambda: _reserve(reopened)):
        with pytest.raises(WorkerAssignmentError, match=_ERROR):
            attempt()
    assert _rows(reopened.store) == before
    _assert_no_native_publication(reopened)


@pytest.mark.parametrize("mutation", ["unknown", "registry_revoked", "host", "boot", "key"])
def test_reservation_registry_preflight_refuses_unusable_worker_without_writes(harness, mutation):
    h = harness
    worker = h.key
    if mutation == "unknown":
        worker = WorkerOriginKey("worker-3", "host-3", "boot-3", "key-3", b"unknown-worker-fixture-secret-123456")
    elif mutation == "registry_revoked":
        h.book = _book(h.store, WorkerOriginRegistry([replace(h.key, revoked=True)]))
    else:
        field = {"host": "host_id", "boot": "host_boot_id", "key": "key_id"}[mutation]
        worker = replace(worker, **{field: "foreign-original-identity"})
    before = _rows(h.store)
    with pytest.raises(ValueError, match=_ERROR):
        _reserve(h, worker=worker)
    assert _rows(h.store) == before
    assert h.book.inspect(h.request.episode_id) is None


def test_registry_public_identity_is_detached_metadata_without_secrets(harness):
    h = harness
    identity = h.registry.worker_identity(h.key.worker_id)
    assert identity == {
        "worker_id": "worker-1", "host_id": "host-1", "host_boot_id": "boot-1", "key_id": "key-1",
    }
    identity["host_boot_id"] = "caller mutation"
    assert h.registry.worker_identity(h.key.worker_id)["host_boot_id"] == "boot-1"
    assert "secret" not in repr(identity) and _SECRET.decode() not in repr(identity)


def test_reservation_uses_registry_public_identity_and_real_signing_uses_registry_secret(harness):
    h = harness
    # Registration selects public identity; a caller-supplied key's secret is
    # neither retained nor adopted as the trusted verification key.
    worker = replace(h.key, secret_key=b"different-caller-secret-1234567890")
    snapshot = _reserve(h, worker=worker)
    authentic = _signed(h, snapshot)
    result = _record(h, authentic)
    assert result["outcome"] == "receipt_authenticated"
    assert result["verified_origin"]["receipt_sha256"] == hashlib.sha256(_RECEIPT).hexdigest()
    assert worker.secret_key.decode() not in repr(_rows(h.store))
    _assert_no_native_publication(h)
