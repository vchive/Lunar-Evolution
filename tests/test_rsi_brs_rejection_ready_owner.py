"""A genuine waiting original owner captures once without arming or ACK."""

from __future__ import annotations

import json
import sqlite3
import time
from threading import Thread

import pytest
import test_rsi_brs_rejection_provenance as fixture

from lunar_evolution import rsi_brs_publication_lineage as brs
from lunar_evolution import rsi_brs_rejection_ready_owner as ready_owner
from lunar_evolution import rsi_brs_rejection_ready_policy as ready_policy
from lunar_evolution.rsi_brs_rejection_ready_ledger import assert_rejection_ready_rows
from lunar_evolution.rsi_learning import RSILearningError

inert_only = fixture.inert_only
sealed_launch = fixture.sealed_launch
tmp_path = fixture.tmp_path


def _retain(value):
    value.owner.retain_rejected_terminal(value.terminal)
    value.owner.retain_rejection_provenance()


@pytest.mark.parametrize("count", [1, 2])
def test_original_owner_captures_reference_materials_and_rows_without_ready(tmp_path, monkeypatch, count):
    with fixture.c1._waiting(tmp_path, monkeypatch, count=count) as value:
        _retain(value)
        original = fixture.c1.owner_fixture._capture(value)
        files = fixture.c1._native_material_snapshot(value)
        custody = ready_owner._custody(value.owner)

        assert value.owner.retain_rejection_ready_capture() is None

        capture = value.owner._rejection_ready_capture
        assert type(capture) is tuple and len(capture) == 6
        held, rows, sync, scope, existing, payload = capture
        assert all(item is original for item, original in zip(held[:-2], custody[:-2], strict=True))
        assert held[-2] is value.owner._rejection_ready_locks_capture
        assert held[-2][:3] == (value.controller, value.ledger, value.owner._before_control)
        assert held[-1] is sync and value.owner._rejection_ready_sync_capture is sync
        assert sync[0] is value.owner._before_channel_condition
        assert scope[:2] == (value.binding.run_id, value.episode_id)
        assert scope[4:] == (value.wave.episode_ids, value.owner._thread)
        assert json.loads(existing[0]) == value.wave.state["python_admission_refs"][value.episode_id]
        assert existing[2] == json.loads(existing[0])["record_sha256"]
        assert existing[3] == rows[2]
        wire = json.loads(payload)
        assert wire == {"native_plan": value.plan.to_dict(), "prepared_journal": value.journal.to_dict(),
                        "expected_anchor_sha256": value.anchor.anchor_sha256}
        assert_rejection_ready_rows(str(value.ledger.database), rows)
        fixture.c1.owner_fixture._unchanged(value, original)
        assert fixture.c1._native_material_snapshot(value) == files
        assert value.owner._phase == "rejected-provenance" and value.owner._poisoned is False
        assert value.owner._rejection_ready_capture_started is True
        fixture.c1._quiet(value)


@pytest.mark.parametrize("target", ["controller", "ledger", "control"])
def test_original_native_lock_replacement_during_callback_refuses_without_refresh(
        tmp_path, monkeypatch, target):
    from threading import RLock

    active = {}

    def cancelled():
        value = active.get("value")
        if value is not None and not active.get("changed"):
            active["changed"] = True
            owner = value.owner
            obj, name = {
                "controller": (value.controller, "_python_admission_brs_observation_lock"),
                "ledger": (value.ledger, "_controller_guards_lock"),
                "control": (owner._before_control, "_lock"),
            }[target]
            active["object"], active["name"], active["original"] = obj, name, getattr(obj, name)
            setattr(obj, name, RLock())
        return False

    monkeypatch.setattr(fixture.c1, "_unlocked_cancelled", cancelled)
    with fixture.c1._waiting(tmp_path, monkeypatch) as value:
        _retain(value)
        assert value.owner._before_control is not None
        active["value"] = value
        try:
            # The pre-existing control fingerprint detects its replaced native
            # lock before the later retained-lock custody comparison.
            reason = "before_control_drift" if target == "control" else "locks_custody_drift"
            with pytest.raises(RSILearningError, match=reason):
                value.owner.retain_rejection_ready_capture()
            assert active["changed"] is True
            assert value.owner._poisoned is True and value.owner._rejection_ready_capture is None
            capture = value.owner._rejection_ready_locks_capture
            assert capture[{"controller": 3, "ledger": 4, "control": 5}[target]] is active["original"]
            fixture.c1._quiet(value)
        finally:
            if active.get("changed"):
                setattr(active["object"], active["name"], active["original"])


def test_successful_capture_cannot_be_refreshed_or_retried(tmp_path, monkeypatch):
    with fixture.c1._waiting(tmp_path, monkeypatch) as value:
        _retain(value)
        value.owner.retain_rejection_ready_capture()
        original = value.owner._rejection_ready_capture
        with pytest.raises(RSILearningError, match="capture_already_consumed"):
            value.owner.retain_rejection_ready_capture()
        assert value.owner._rejection_ready_capture is original and value.owner._poisoned is True
        fixture.c1._quiet(value)


def test_capture_requires_original_confirmed_c2_and_consumes_failure(tmp_path, monkeypatch):
    with fixture.c1._waiting(tmp_path, monkeypatch) as value:
        value.owner.retain_rejected_terminal(value.terminal)
        with pytest.raises(RSILearningError):
            value.owner.retain_rejection_ready_capture()
        assert value.owner._rejection_ready_capture is None
        assert value.owner._rejection_ready_capture_started is True and value.owner._poisoned is True
        fixture.c1._quiet(value)


def test_foreign_thread_cannot_capture_or_refresh_original_owner(tmp_path, monkeypatch):
    with fixture.c1._waiting(tmp_path, monkeypatch) as value:
        _retain(value)
        errors = []

        def attempt():
            try:
                value.owner.retain_rejection_ready_capture()
            except BaseException as exc:  # noqa: BLE001 - report every thread outcome.
                errors.append(exc)

        thread = Thread(target=attempt)
        thread.start()
        thread.join(20)
        assert not thread.is_alive() and len(errors) == 1 and isinstance(errors[0], RSILearningError)
        assert value.owner._rejection_ready_capture is None and value.owner._poisoned is True
        fixture.c1._quiet(value)


@pytest.mark.parametrize("fault", ["source", "head", "p-inode", "closed"])
def test_preexisting_drift_never_becomes_a_new_ready_baseline(tmp_path, monkeypatch, fault):
    with fixture.c1._waiting(tmp_path, monkeypatch) as value:
        _retain(value)
        if fault == "source":
            value.gateway.fingerprint = "foreign-ready-source"
        elif fault == "head":
            value.ledger.write_controller_checkpoint(value.binding.run_id, value.wave.state,
                                                     expected_sha256=value.owner._head)
        elif fault == "p-inode":
            path = fixture._path(value)
            raw = path.read_bytes()
            path.rename(path.with_suffix(".original"))
            path.write_bytes(raw)
            path.chmod(0o400)
        else:
            value.wave.channel.close()
        with pytest.raises((RSILearningError, ValueError)):
            value.owner.retain_rejection_ready_capture()
        assert value.owner._rejection_ready_capture is None and value.owner._poisoned is True
        assert not value.wave.channel._queue and not value.wave.channel._requests
        assert value.messages.empty() and not value.ready.is_set()


def test_raw_drift_during_unlocked_callback_refuses_without_new_baseline(tmp_path, monkeypatch):
    active = {}

    def cancelled():
        if active.get("value") is not None and not active.get("changed"):
            active["changed"] = True
            with sqlite3.connect(active["value"].ledger.database) as connection:
                connection.execute("UPDATE rsi_records SET created_at = ? WHERE logical_id = ?",
                    ("fixture-changed-raw-metadata", active["value"].binding.run_id))
        return False

    monkeypatch.setattr(fixture.c1, "_unlocked_cancelled", cancelled)
    with fixture.c1._waiting(tmp_path, monkeypatch) as value:
        _retain(value)
        active["value"] = value
        with pytest.raises(RSILearningError, match="rows_changed"):
            value.owner.retain_rejection_ready_capture()
        assert active["changed"] is True
        assert value.owner._rejection_ready_capture is None and value.owner._poisoned is True
        fixture.c1._quiet(value)


def test_foreign_or_reconstructed_owner_is_refused():
    class Foreign(brs._BRSLineageCheckpointOwner):
        pass

    for owner in (object(), object.__new__(Foreign)):
        with pytest.raises(RSILearningError, match="owner_invalid"):
            brs._BRSLineageCheckpointOwner.retain_rejection_ready_capture(owner)


def test_early_naturally_queued_ready_is_refused_without_ack(tmp_path, monkeypatch):
    with fixture.c1._waiting(tmp_path, monkeypatch) as value:
        _retain(value)
        value.ready.set()
        expiry = time.monotonic() + 10
        while time.monotonic() < expiry:
            with value.wave.channel._condition:
                if value.wave.channel._queue:
                    break
            time.sleep(.01)
        with value.wave.channel._condition:
            assert len(value.wave.channel._queue) == 1
            pending = value.wave.channel._queue[0]
        with pytest.raises(RSILearningError):
            value.owner.retain_rejection_ready_capture()
        assert value.owner._rejection_ready_capture is None and value.owner._poisoned is True
        assert pending.ack is None and pending.ack_fields is None and pending.state == "queued"
        assert value.wave.channel._requests[value.episode_id] is pending
        assert value.messages.empty()


def test_instance_reader_shadow_is_refused_before_its_callback(tmp_path, monkeypatch):
    with fixture.c1._waiting(tmp_path, monkeypatch) as value:
        _retain(value)
        calls = []

        def shadow(*_args, **_kwargs):
            calls.append("shadow")
            raise AssertionError("pre-arm gate executed an instance reader shadow")

        monkeypatch.setattr(value.controller, "_python_admission_flow_payload", shadow)
        with pytest.raises(RSILearningError, match="reader_shadow"):
            value.owner.retain_rejection_ready_capture()
        assert calls == []
        assert value.owner._rejection_ready_capture is None and value.owner._poisoned is True


def test_enclosing_policy_independently_refuses_capture_guard_closure_drift():
    # The guard cannot authenticate a replacement of its own retained state.
    cell = ready_policy.rejection_ready_capture_policy.__closure__[0]
    original = cell.cell_contents
    cell.cell_contents = object()
    try:
        with pytest.raises(RSILearningError, match="rejection_policy_drift"):
            brs._policy()
    finally:
        cell.cell_contents = original


@pytest.mark.parametrize("field", ["_policy_bytes", "_payload", "_head"])
def test_capture_primitive_types_refuse_before_foreign_equality(field):
    calls = []

    class Foreign:
        def __eq__(self, _other):
            calls.append("eq")
            raise AssertionError("capture invoked a foreign primitive equality")

        __ne__ = __eq__

    owner = object.__new__(brs._BRSLineageCheckpointOwner)
    owner._poisoned = False
    owner._policy_bytes, owner._payload, owner._head = b"{}", b"{}", "a" * 64
    setattr(owner, field, Foreign())
    with pytest.raises(RSILearningError, match="capture_type_invalid"):
        owner.retain_rejection_ready_capture()
    assert calls == [] and owner._poisoned is True
