"""Original owner recovery fences over a naturally running inert selected worker.

The first gateway invocation creates its original native claim before the real
owner is constructed. No terminal claim is retrofitted and no external execution
or inferred process-cleanup evidence is involved.
"""

from __future__ import annotations

import sqlite3
from copy import deepcopy
from types import FunctionType

import pytest
import test_rsi_brs_publication_lineage_owner as fixture
import test_rsi_python_brs_native_dispatch as native_fixture
from test_rsi_python_admission import OTHER, _rows
from test_rsi_python_brs_selected_service import _evidence_files

from lunar_evolution import RSILearningError, SolverResult
from lunar_evolution import rsi_brs_publication_lineage as lineage
from lunar_evolution import rsi_python_brs_owner_bridge as bridge
from lunar_evolution.rsi_brs_reconcile import FIELD, BRSReconcileObligation
from lunar_evolution.rsi_fingerprint import RSIFingerprintError
from lunar_evolution.rsi_learning import PracticeEpisode

inert_only = fixture.inert_only
tmp_path = fixture.tmp_path


@pytest.mark.parametrize("name", ["_original_control", "_run_original_brs_native_publication"])
def test_bridge_dispatch_alias_rejects_same_code_with_foreign_globals(monkeypatch, name):
    original = getattr(bridge, name)
    clone = FunctionType(
        original.__code__, dict(original.__globals__), original.__name__,
        original.__defaults__, original.__closure__,
    )
    clone.__qualname__ = original.__qualname__
    clone.__kwdefaults__ = original.__kwdefaults__
    monkeypatch.setattr(bridge, name, clone)
    with pytest.raises(RSILearningError, match="^rsi_brs_publication_lineage_native_reader_globals_drift$"):
        lineage._policy()


def test_original_owner_retains_one_exact_adjacent_obligation_and_resume_stays_fenced(tmp_path, monkeypatch):
    with fixture._waiting(tmp_path, monkeypatch) as value:
        owner, wave, ledger = value.owner, value.wave, value.ledger
        run_id = value.binding.run_id
        head, payload, state = fixture._capture(value)
        history, rows, files = ledger.controller_checkpoint_history(run_id), _rows(value), _evidence_files(value)
        handoff, context = owner._handoff_bytes, owner._selected_context_bytes
        claim = ledger.inspect_native_episode_claim(value.request, plan_sha256=value.plan.plan_sha256)
        assert claim is not None and claim.status == "started"
        assert ledger.episode_result(value.episode_id) is None

        retained_head = owner.retain_reconcile_obligation()

        durable = ledger.controller_checkpoint(run_id)
        obligation = BRSReconcileObligation.from_dict(durable[1][FIELD][value.episode_id])
        assert obligation.controller_checkpoint_sha256 == head == owner._handoff.head_sha256
        assert obligation.episode_record_sha256 == owner._episode_head
        assert obligation.native_claim_sha256 == claim.claim_sha256
        assert obligation.native_plan_sha256 == value.plan.plan_sha256
        assert obligation.handoff_sha256 == wave.selected_handoff.sha256
        assert durable == (retained_head, state | {FIELD: {value.episode_id: obligation.to_dict()}})
        assert retained_head != head
        assert ledger.controller_checkpoint_history(run_id) == [*history, durable]
        assert owner._head == wave.checkpoint_sha256 == retained_head
        assert owner._payload == wave.payload == value.controller._python_admission_flow_payload(durable[1])
        assert owner._payload != payload and wave.state == durable[1]
        assert owner._handoff_bytes == handoff and owner._selected_context_bytes == context
        assert owner._phase == "new" and not owner._poisoned
        assert wave.state["budget_state"] == state["budget_state"]
        assert wave.state["root_snapshot"] == state["root_snapshot"]
        after = _rows(value)
        assert after["rsi_controller_journal"][:-1] == rows["rsi_controller_journal"]
        assert {key: item for key, item in after.items() if key != "rsi_controller_journal"} == {
            key: item for key, item in rows.items() if key != "rsi_controller_journal"
        }
        assert _evidence_files(value) == files
        assert ledger.inspect_native_episode_claim(value.request, plan_sha256=value.plan.plan_sha256) == claim
        assert ledger.episode_result(value.episode_id) is None
        with pytest.raises(RSILearningError, match="^rsi_brs_publication_lineage_"):
            owner.retain_reconcile_obligation()
        assert ledger.controller_checkpoint_history(run_id) == [*history, durable]

    before = ledger.controller_checkpoint_history(run_id), ledger.history(run_id), value.gateway.calls
    with pytest.raises(RSILearningError, match="^rsi_brs_reconcile_required$"):
        value.controller.resume(run_id)
    assert (ledger.controller_checkpoint_history(run_id), ledger.history(run_id), value.gateway.calls) == before
    assert ledger.get_episode(value.sibling_id) is None


@pytest.mark.parametrize("after_append", [False, True])
def test_registration_append_uncertainty_poison_keeps_capture_without_retry(tmp_path, monkeypatch, after_append):
    with fixture._waiting(tmp_path, monkeypatch) as value:
        owner, ledger, run_id = value.owner, value.ledger, value.binding.run_id
        before = fixture._capture(value)
        original = ledger.write_brs_reconcile_obligation
        calls = []

        def append(*args, **kwargs):
            calls.append(True)
            if after_append:
                original(*args, **kwargs)
            raise RuntimeError("fixture_registration_append_unknown")

        monkeypatch.setattr(ledger, "write_brs_reconcile_obligation", append)
        with pytest.raises(RuntimeError, match="fixture_registration_append_unknown"):
            owner.retain_reconcile_obligation()
        fixture._unchanged(value, before)
        assert owner._poisoned
        durable = ledger.controller_checkpoint(run_id)
        assert bool(durable[1].get(FIELD)) is after_append
        assert (durable[0] != before[0]) is after_append
        with pytest.raises(RSILearningError, match="^rsi_brs_publication_lineage_"):
            owner.retain_reconcile_obligation()
        assert calls == [True]
        assert ledger.controller_checkpoint(run_id) == durable
        assert ledger.episode_result(value.episode_id) is None
        assert ledger.get_episode(value.sibling_id) is None


@pytest.mark.parametrize("fault", ["readback", "source", "control"])
def test_postappend_drift_keeps_durable_obligation_and_original_local_capture(tmp_path, monkeypatch, fault):
    waiting = native_fixture._waiting if fault == "control" else fixture._waiting
    with waiting(tmp_path, monkeypatch) as value:
        ledger, run_id = value.ledger, value.binding.run_id
        before = fixture._capture(value)
        original, original_history = ledger.write_brs_reconcile_obligation, ledger.controller_checkpoint_history
        calls = []

        def append(*args, **kwargs):
            head = original(*args, **kwargs)
            calls.append(head)
            if fault == "source":
                value.gateway.fingerprint = "foreign-postappend-source"
            elif fault == "control":
                value.control.deadline += 1
            else:
                def drifted_history(selected):
                    history = original_history(selected)
                    return [*history[:-1], (OTHER, history[-1][1])]

                patch.setattr(ledger, "controller_checkpoint_history", drifted_history)
            return head

        with monkeypatch.context() as patch:
            patch.setattr(ledger, "write_brs_reconcile_obligation", append)
            with pytest.raises((RSILearningError, RSIFingerprintError)):
                value.owner.retain_reconcile_obligation()
        assert len(calls) == 1
        fixture._unchanged(value, before)
        assert value.owner._poisoned
        durable = ledger.controller_checkpoint(run_id)
        assert durable[0] == calls[0] != before[0]
        assert set(durable[1][FIELD]) == {value.episode_id}
        with pytest.raises(RSILearningError, match="^rsi_brs_publication_lineage_"):
            value.owner.retain_reconcile_obligation()
        assert ledger.controller_checkpoint(run_id) == durable
        assert ledger.episode_result(value.episode_id) is None


@pytest.mark.parametrize("fault", ["source", "budget", "channel"])
def test_registration_rechecks_original_source_budget_and_channel_without_writes(tmp_path, monkeypatch, fault):
    with fixture._waiting(tmp_path, monkeypatch) as value:
        if fault == "source":
            value.gateway.fingerprint = "foreign-reconcile-source"
        elif fault == "budget":
            value.wave.budget_state["planned"]["deadline_unix"] += 1
        else:
            value.wave.channel.close()
        before = value.ledger.controller_checkpoint_history(value.binding.run_id), _rows(value)
        with pytest.raises((RSILearningError, RSIFingerprintError)):
            value.owner.retain_reconcile_obligation()
        assert (value.ledger.controller_checkpoint_history(value.binding.run_id), _rows(value)) == before
        assert not value.ledger.controller_brs_reconcile_obligations(value.binding.run_id)


@pytest.mark.parametrize("fault", ["run", "episode", "claim", "result"])
def test_registration_sqlite_boundary_rechecks_original_running_facts(tmp_path, monkeypatch, fault):
    with fixture._waiting(tmp_path, monkeypatch) as value:
        ledger, run_id = value.ledger, value.binding.run_id
        original = ledger.write_brs_reconcile_obligation
        checkpoint = ledger.controller_checkpoint_history(run_id)
        changed = []

        def append(*args, **kwargs):
            if fault == "run":
                run = ledger.get_run(run_id)
                ledger.transition(run_id, state="running", expected_record_sha256=run.record_sha256)
            elif fault == "episode":
                current = ledger.get_episode(value.episode_id)
                episode = PracticeEpisode.from_dict(current.payload)
                ledger.append_episode_record(
                    episode.transition("failed", terminal_reason="fixture_worker_failed"),
                    expected_record_sha256=current.record_sha256,
                )
            elif fault == "claim":
                with sqlite3.connect(ledger.database) as connection:
                    connection.execute(
                        "UPDATE rsi_native_episode_claims SET plan_sha256=?,claim_sha256=? WHERE episode_id=?",
                        (OTHER, ledger._native_claim_digest(value.episode_id, value.request.digest(), OTHER),
                         value.episode_id),
                    )
            else:
                ledger.save_episode_result(value.request, SolverResult(
                    value.episode_id, value.request.digest(), "failed", None, None, None, OTHER,
                    terminal_reason="fixture_saved_result",
                ))
            changed.append(deepcopy(_rows(value)))
            return original(*args, **kwargs)

        monkeypatch.setattr(ledger, "write_brs_reconcile_obligation", append)
        with pytest.raises(RSILearningError, match="rsi_brs_reconcile_"):
            value.owner.retain_reconcile_obligation()
        assert len(changed) == 1 and _rows(value) == changed[0]
        assert ledger.controller_checkpoint_history(run_id) == checkpoint
        assert not ledger.controller_brs_reconcile_obligations(run_id)
        assert value.owner._poisoned
