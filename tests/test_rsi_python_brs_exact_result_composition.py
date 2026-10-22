"""Original owner/worker exact response composition over the inert native kernel.

Detached callbacks are deliberately not controller settlement. Publication, result
delivery and callback completion never fabricate solver/process terminal evidence.
"""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from threading import get_ident
from types import FunctionType

import pytest
import test_rsi_python_brs_native_dispatch as native_fixture
from test_rsi_python_admission import OTHER, _rows
from test_rsi_python_brs_owner_bridge_reconcile import _mailbox_worker, _retained

from lunar_evolution import RSILearningError
from lunar_evolution import rsi_brs_publication_lineage as lineage
from lunar_evolution import rsi_python_brs_handoff as handoff_module
from lunar_evolution import rsi_python_brs_owner_bridge as bridge
from lunar_evolution import rsi_python_brs_publication_mailbox as mailbox_module
from lunar_evolution import rsi_python_brs_result_delivery as delivery
from lunar_evolution.producer_bundle_publication import ProducerBundlePublicationJournal
from lunar_evolution.producer_bundle_rejection import ProducerBundleRejectionError
from lunar_evolution.rsi_fingerprint import RSIFingerprintContract, RSIFingerprintError
from lunar_evolution.rsi_python_brs_publication_mailbox import (
    BRSOwnerPublicationMailbox,
    build_brs_owner_publication_request,
)

inert_only = native_fixture.inert_only
tmp_path = native_fixture.tmp_path


def _assert_unsettled_controller(value):
    _retained(value)
    assert value.ledger.get_episode(value.episode_id).state == "running"
    assert value.ledger.inspect_native_episode_claim(
        value.request, plan_sha256=value.plan.plan_sha256,
    ).status == "started"
    assert value.ledger.episode_result(value.episode_id) is None
    assert value.ledger.get_episode(value.sibling_id) is None


def test_real_worker_parses_exact_published_response_and_detached_callback_is_one_shot(tmp_path, monkeypatch):
    observations = []

    def consume(value, response):
        assert get_ident() == value.worker_thread != value.owner_thread
        request, handoff = value.request_message, value.wave.selected_handoff
        journal = ProducerBundlePublicationJournal.from_dict(json.loads(
            (value.batch / "journal.published.json").read_bytes(),
        ))
        evidence_before = _rows(value)
        payload = json.loads(response.payload)
        assert payload["selected_request_sha256"] == value.request.digest()
        assert payload["request_sha256"] == request.request_sha256
        assert payload["native_plan_sha256"] == value.plan.plan_sha256
        assert payload["journal_sha256"] == journal.digest()

        settlement = delivery.deliver_brs_owner_result(
            response, request, handoff, expected_native_plan_sha256=value.plan.plan_sha256,
            expected_journal_sha256=journal.digest(),
        )
        callback_values = []

        def callback(item):
            assert get_ident() == value.worker_thread
            assert item is not settlement.delivery
            callback_values.append(item.to_dict())
            # Detached callback mutation cannot rewrite the gate's retained result.
            object.__setattr__(item, "publication_status", "all_rejected")
            return "fixture_callback_completed"

        assert settlement.settle(callback) == "fixture_callback_completed"
        assert settlement.status == "settled" and len(callback_values) == 1
        assert settlement.delivery.publication_status == "published"
        with pytest.raises(delivery.BRSOwnerResultDeliveryError, match="settlement_unavailable"):
            settlement.settle(callback)
        assert len(callback_values) == 1

        # Independent one-shot gate over the same detached observation: a failed
        # callback is unknown and its own gate never retries that callback.
        unknown = delivery.deliver_brs_owner_result(
            response, request, handoff, expected_native_plan_sha256=value.plan.plan_sha256,
            expected_journal_sha256=journal.digest(),
        )
        failed_calls = []

        def fail(item):
            failed_calls.append(item)
            raise RuntimeError("fixture_detached_callback_unknown")

        with pytest.raises(delivery.BRSOwnerResultDeliveryError, match="settlement_unknown"):
            unknown.settle(fail)
        assert unknown.status == "unknown" and len(failed_calls) == 1
        with pytest.raises(delivery.BRSOwnerResultDeliveryError, match="settlement_unavailable"):
            unknown.settle(fail)
        assert len(failed_calls) == 1

        for changed, code in (({"expected_native_plan_sha256": OTHER}, "preparation_mismatch"),
                              ({"expected_journal_sha256": OTHER}, "journal_mismatch")):
            with pytest.raises(delivery.BRSOwnerResultDeliveryError, match=code):
                delivery.deliver_brs_owner_result(response, request, handoff, **changed)
        foreign_handoff = replace(handoff, lease_nonce="foreign-result-capture" * 2)
        with pytest.raises(delivery.BRSOwnerResultDeliveryError, match="request_handoff_mismatch"):
            delivery.deliver_brs_owner_result(response, request, foreign_handoff)
        foreign_request = build_brs_owner_publication_request(
            handoff, request.payload.replace(value.plan.plan_sha256.encode(), OTHER.encode()),
        )
        with pytest.raises(delivery.BRSOwnerResultDeliveryError, match="response_binding_mismatch"):
            delivery.deliver_brs_owner_result(response, foreign_request, handoff)

        assert _rows(value) == evidence_before
        _assert_unsettled_controller(value)
        observations.append((response, callback_values[0], journal.digest()))

    with _mailbox_worker(tmp_path, monkeypatch, on_response=consume) as (value, mailbox, responses):
        budget = deepcopy(value.wave.state["budget_state"])
        value.ready.set()
        result = bridge.run_brs_owner_publication_mailbox(
            value.owner, mailbox, value.preparation, check=lambda: None, timeout=10,
        )
        response = responses.get(timeout=20)
        assert not isinstance(response, BaseException), repr(response)
        assert len(observations) == 1 and observations[0][0] is response
        assert result.response_payload == response.payload
        assert result.transaction.published_journal.digest() == observations[0][2]
        assert observations[0][1]["admitted_candidate_ids"] == list(result.transaction.admitted_candidate_ids)
        assert mailbox.status == "delivered"
        assert value.owner._phase == "terminal" and not value.owner._poisoned
        assert value.wave.state["budget_state"] == budget
        _assert_unsettled_controller(value)

    before = value.ledger.controller_checkpoint_history(value.binding.run_id), _rows(value)
    with pytest.raises(RSILearningError, match="^rsi_brs_reconcile_required$"):
        value.controller.resume(value.binding.run_id)
    assert (value.ledger.controller_checkpoint_history(value.binding.run_id), _rows(value)) == before


def test_real_all_rejected_kernel_still_refuses_response_and_retains_fence(tmp_path, monkeypatch):
    callbacks = []
    with _mailbox_worker(tmp_path, monkeypatch, validity=0,
                         on_response=lambda *_args: callbacks.append(True)) as (value, mailbox, responses):
        value.ready.set()
        # The native kernel now supports the all-rejected C1/P/C2 path. This
        # intentionally inert fixture omits the durable rejection evidence, so
        # the owner must fail closed on the fixed evidence error instead of
        # silently downgrading it to the former unsupported-mode sentinel.
        with pytest.raises(ProducerBundleRejectionError, match="producer_bundle_rejection_evidence_invalid"):
            bridge.run_brs_owner_publication_mailbox(
                value.owner, mailbox, value.preparation, check=lambda: None, timeout=10,
            )
        assert isinstance(responses.get(timeout=20), RSILearningError)
        assert callbacks == [] and mailbox.status == "abandoned"
        terminal = json.loads((value.batch / "journal.json").read_bytes())
        assert terminal["state"] == "all_rejected"
        assert value.owner._phase == "prepared-evidence" and value.owner._poisoned
        assert not (value.batch / "journal.published.json").exists()
        _assert_unsettled_controller(value)


@pytest.mark.parametrize("entry", ["builder-alias", "builder-and-module", "_journal", "_canonical_payload"])
def test_result_projection_rejects_same_code_foreign_globals_without_fixture(monkeypatch, entry):
    name = "build_brs_owner_result_payload" if entry.startswith("builder-") else entry
    original = getattr(delivery, name)
    clone = FunctionType(original.__code__, dict(original.__globals__), original.__name__,
                         original.__defaults__, original.__closure__)
    clone.__qualname__, clone.__kwdefaults__ = original.__qualname__, original.__kwdefaults__
    if entry != "builder-alias":
        monkeypatch.setattr(delivery, name, clone)
    if entry.startswith("builder-"):
        monkeypatch.setattr(bridge, name, clone)
    with pytest.raises(RSILearningError, match="native_reader_(?:binding|globals)_drift"):
        lineage._policy()


def _forbidden_result_builder(*_args, **_kwargs):
    raise AssertionError("substituted result builder executed")


@pytest.mark.parametrize("name", ["_STATUSES", "_FIELDS", "_ID", "_SHA"])
def test_result_policy_rejects_foreign_constants_before_executing_hooks(monkeypatch, name):
    class Foreign:
        def __iter__(self):
            pytest.fail("foreign policy iterator executed")

        def __getattr__(self, _name):
            pytest.fail("foreign policy attribute hook executed")

    monkeypatch.setattr(delivery, name, Foreign())
    with pytest.raises(RSILearningError, match="^rsi_brs_publication_lineage_owner_result_policy_drift$"):
        lineage._policy()


@pytest.mark.parametrize("entry", ["mailbox-class", "handoff-class", "handoff-canonical", "mailbox-filepin"])
def test_result_policy_rejects_substituted_class_and_reader_aliases(monkeypatch, entry):
    if entry == "mailbox-class":
        class ForeignMailbox(mailbox_module.BRSOwnerPublicationMailbox):
            pass

        monkeypatch.setattr(bridge, "BRSOwnerPublicationMailbox", ForeignMailbox)
    elif entry == "handoff-class":
        class ForeignHandoff(handoff_module.BRSSelectedChildHandoff):
            pass

        monkeypatch.setattr(bridge, "BRSSelectedChildHandoff", ForeignHandoff)
    else:
        module, name = ((handoff_module, "canonical_json") if entry == "handoff-canonical"
                        else (mailbox_module, "parse_python_producer_admission_handoff_file_pin"))
        original = getattr(module, name)
        # Same implementation and canonical globals still cannot replace an
        # imported alias's original identity at this boundary.
        clone = FunctionType(original.__code__, original.__globals__, original.__name__,
                             original.__defaults__, original.__closure__)
        clone.__qualname__, clone.__kwdefaults__ = original.__qualname__, original.__kwdefaults__
        monkeypatch.setattr(module, name, clone)
    with pytest.raises(RSILearningError, match="^rsi_brs_publication_lineage_native_reader_binding_drift$"):
        lineage._policy()


def test_original_result_policy_keeps_public_admission_disabled():
    policy = lineage._policy()
    assert policy["online_publication"] is False
    assert policy["production_admission"] is False
    # Exercise the controller's actual policy nesting and bounded identity
    # normalization, rather than accepting a policy which only builds as a dict.
    contract = RSIFingerprintContract.build(
        contract_sha256=OTHER, evaluator_sha256=OTHER, environment_sha256=OTHER,
        memory_snapshot_sha256=OTHER, solver_id="inert-brs-policy",
        solver_settings={"producer_brs_checkpoint_policy": policy},
        actor_fingerprint=OTHER, verifier_fingerprint=OTHER,
        curriculum_fingerprint=OTHER, target_judge_fingerprint=OTHER,
    )
    assert contract.to_dict()["solver_settings"]["producer_brs_checkpoint_policy"] == policy
    assert RSIFingerprintContract.from_dict(contract.to_dict()) == contract


def test_result_builder_source_drift_refuses_before_reconcile_write_or_publication(tmp_path, monkeypatch):
    with native_fixture._waiting(tmp_path, monkeypatch) as value:
        before = value.ledger.controller_checkpoint_history(value.binding.run_id), _rows(value)
        changed = FunctionType(_forbidden_result_builder.__code__, vars(delivery), _forbidden_result_builder.__name__)
        monkeypatch.setattr(delivery, "build_brs_owner_result_payload", changed)
        monkeypatch.setattr(bridge, "build_brs_owner_result_payload", changed)
        mailbox = BRSOwnerPublicationMailbox(value.wave.selected_handoff, worker_thread=value.worker_thread)
        try:
            with pytest.raises((RSILearningError, RSIFingerprintError)):
                bridge.run_brs_owner_publication_mailbox(
                    value.owner, mailbox, value.preparation, check=lambda: None, timeout=0,
                )
            assert (value.ledger.controller_checkpoint_history(value.binding.run_id), _rows(value)) == before
            assert not value.ledger.controller_brs_reconcile_obligations(value.binding.run_id)
            assert not (value.batch / "journal.prepared.json").exists()
        finally:
            mailbox.close()


def test_postpublication_result_dependency_drift_refuses_delivery_and_keeps_fence(tmp_path, monkeypatch):
    callbacks = []
    with _mailbox_worker(tmp_path, monkeypatch,
                         on_response=lambda *_args: callbacks.append(True)) as (value, mailbox, responses):
        checks = []

        def check():
            checks.append(True)
            if len(checks) == 2:
                changed = FunctionType(
                    _forbidden_result_builder.__code__, vars(delivery), _forbidden_result_builder.__name__,
                )
                monkeypatch.setattr(delivery, "build_brs_owner_result_payload", changed)
                monkeypatch.setattr(bridge, "build_brs_owner_result_payload", changed)

        value.ready.set()
        with pytest.raises((RSILearningError, RSIFingerprintError)):
            bridge.run_brs_owner_publication_mailbox(
                value.owner, mailbox, value.preparation, check=check, timeout=10,
            )
        assert len(checks) == 2 and callbacks == []
        assert isinstance(responses.get(timeout=20), RSILearningError)
        assert mailbox.status == "abandoned"
        assert (value.batch / "journal.published.json").exists()
        assert value.owner._phase == "terminal"
        _assert_unsettled_controller(value)
