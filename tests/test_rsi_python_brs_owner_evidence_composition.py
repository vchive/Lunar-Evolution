"""Read retained native evidence, then pin under the same real waiting BRS owner."""

from __future__ import annotations

import socket
import subprocess
from copy import deepcopy
from threading import get_ident

import pytest
import test_rsi_brs_publication_lineage_owner as owner_fixture
import test_rsi_python_brs_publication_recovery as retained

from lunar_evolution import bundle_evolution
from lunar_evolution import producer_bundle_transaction as transaction


@pytest.fixture
def tmp_path(tmp_path_factory):
    return tmp_path_factory.mktemp("c")


@pytest.fixture(autouse=True)
def inert_only(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("owner evidence composition invoked execution or evaluation")

    for module, names in (
        (subprocess, ("Popen", "run")),
        (socket, ("create_connection",)),
        (transaction, ("run_native_producer_bundle_publication_transaction",)),
        (bundle_evolution, ("evaluate_candidate_execution",)),
    ):
        for name in names:
            monkeypatch.setattr(module, name, forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(bundle_evolution.MultiFileCandidatePipeline,
                        "evaluate_draft_non_publishing", forbidden)


def test_retained_reader_and_owner_reference_and_evidence_cas_compose(tmp_path, monkeypatch):
    with retained._waiting(tmp_path, monkeypatch) as value:
        run_id, episode_id = value.binding.run_id, value.episode_id
        initial = owner_fixture._capture(value)
        history = value.ledger.controller_checkpoint_history(run_id)
        budget = deepcopy(value.wave.state["budget_state"])
        memory = deepcopy(value.wave.state["root_snapshot"])
        recovered = retained._reader(value).recover(value.request_message)
        assert recovered.output.publication_eligible is False
        assert recovered.receipt == value.preparation.run.receipt
        assert recovered.output.admission_plan == value.admission
        owner_fixture._unchanged(value, initial)
        assert value.ledger.controller_checkpoint_history(run_id) == history

        before_head = value.owner.checkpoint_before(owner_fixture._before(value))
        original_pin, writes = value.ledger.pin_python_admission_record, []

        def pin(record, **kwargs):
            assert get_ident() == value.owner_thread != value.worker_thread
            assert value.ledger.controller_lock_held(run_id)
            assert kwargs["expected_checkpoint_sha256"] == before_head
            writes.append(record.record_sha256)
            return original_pin(record, **kwargs)

        monkeypatch.setattr(value.ledger, "pin_python_admission_record", pin)
        record_sha256 = value.controller._pin_python_admission_for_original_brs_owner(
            value.owner, expected_anchor_sha256=value.anchor.anchor_sha256,
        )
        reference_head = value.wave.checkpoint_sha256
        assert value.owner._head == before_head
        evidence_head = value.owner.acknowledge_prepared(value.journal, record_sha256)
        assert len({before_head, reference_head, evidence_head}) == 3
        assert writes == [record_sha256]
        assert value.owner._phase == "prepared-evidence" and not value.owner._poisoned
        assert value.owner._head == value.wave.checkpoint_sha256 == evidence_head
        assert value.ledger.get_episode(episode_id).state == "running"
        assert value.ledger.inspect_native_episode_claim(
            value.request, plan_sha256=value.plan.plan_sha256,
        ).status == "started"
        assert value.ledger.episode_result(episode_id) is None
        assert value.wave.state["budget_state"] == budget
        assert value.wave.state["root_snapshot"] == memory
        assert not value.ready.is_set() and value.messages.empty()
        assert not value.wave.channel._requests and not value.wave.channel._queue
        assert value.controller.producer_multi_episode_publication is False
