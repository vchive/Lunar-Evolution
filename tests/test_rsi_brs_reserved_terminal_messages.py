"""Pure reserved terminal descriptions; no owner, provider or file authority."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace

import pytest
from test_rsi_brs_reserved_rejection import _fixture
from test_rsi_python_brs_publication_mailbox import _handoff, _json, _wire
from test_rsi_python_brs_result_delivery import _response, _transaction

from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.producer_bundle_lineage import ProducerLineageTerminal
from lunar_evolution.producer_bundle_lineage_v2 import ProducerLineageRejectedTerminalV2
from lunar_evolution.producer_bundle_publication import ProducerBundlePublicationJournal
from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_python_brs_publication_mailbox import build_brs_owner_publication_request
from lunar_evolution.rsi_python_brs_terminal_lifecycle import _messages


def _description(outcomes, active="all_rejected"):
    _initial, _c1, lineage, _kwargs = _fixture((*outcomes, "published") if active == "published" else outcomes)
    if active == "published":
        lineage["batches"].pop()
        lineage["rejections"].pop()
    entry = lineage["batches"][-1]
    selected = replace(_handoff(), run_id=lineage["run_id"], wave=1, ordinal=entry["ordinal"],
        episode_id=entry["episode_id"], request_sha256=entry["request_sha256"],
        root_snapshot_sha256=entry["memory_snapshot_sha256"])
    transaction = _transaction(selected, state=active)
    if active == "all_rejected":
        journal = replace(ProducerBundlePublicationJournal.from_dict(entry["rejected_journal"]),
                          native_execution_receipt_sha256="b" * 64, journal_sha256=None)
        rejected = replace(ProducerLineageRejectedTerminalV2.from_dict(entry["rejected"]),
                           terminal_journal_sha256=journal.digest(), descriptor_sha256=None)
        entry["rejected"], entry["rejected_journal"] = rejected.to_dict(), journal.to_dict()
        lineage["rejections"][-1]["rejected_sha256"] = rejected.digest()
        manifest = None
    else:
        terminal = ProducerLineageTerminal.from_dict(entry["terminal"])
        journal = replace(transaction.published_journal, journal_id=entry["journal_id"],
            terminal_marker_sha256=terminal.terminal_sha256,
            archive_after_sha256=terminal.archive_after_sha256,
            state_after_sha256=terminal.state_after_sha256, journal_sha256=None)
        entry["published_journal"] = journal.to_dict()
        lineage["head"] = {"journal_id": terminal.journal_id, "terminal_sha256": terminal.terminal_sha256,
                           "lineage_sha256": terminal.digest()}
        manifest = {"journal_id": journal.journal_id, "archive_after_sha256": journal.archive_after_sha256,
                    "state_after_sha256": journal.state_after_sha256}
        import hashlib

        manifest["manifest_sha256"] = hashlib.sha256(canonical_json(manifest)).hexdigest()
    transaction = replace(transaction, journal=journal, terminal_journal=journal,
                          published_journal=journal if active == "published" else None)
    wire = _wire(selected)
    wire["native_plan_sha256"] = entry["native_plan_sha256"]
    message = build_brs_owner_publication_request(selected, _json(wire))
    response = _response(transaction, message, selected)
    binding = {"mailbox_binding": {"run_id": selected.run_id, "episode_id": selected.episode_id,
        "selected_request_sha256": selected.request_sha256, "native_plan_sha256": entry["native_plan_sha256"],
        "handoff": selected.to_dict()}}
    facts = {"request_fields": [message.run_id, message.episode_id, message.handoff_sha256,
                                message.payload.decode(), message.request_sha256],
        "response_fields": [response.run_id, response.episode_id, response.handoff_sha256,
                            response.request_sha256, response.payload.decode(), response.response_sha256],
        "publication": {"journal": journal.to_dict(), "lineage": lineage, "manifest": manifest}}
    return facts, binding


@pytest.mark.parametrize("outcomes", [(), ("published",), ("all_rejected",),
                                     ("published", "all_rejected"), ("all_rejected", "published")])
@pytest.mark.parametrize("active", ["published", "all_rejected"])
def test_explicit_reserved_descriptions_keep_actual_ordinal_prefix_head_and_rejection_index(outcomes, active):
    facts, binding = _description(outcomes, active)
    before = deepcopy((facts, binding))
    message, response = _messages(facts, binding, reserved=True)
    assert message.episode_id == binding["mailbox_binding"]["episode_id"]
    assert response.request_sha256 == message.request_sha256
    assert (facts, binding) == before
    if outcomes:
        with pytest.raises(RSILearningError, match="publication_invalid"):
            _messages(facts, binding)


@pytest.mark.parametrize("fault", ["ordinal", "request", "plan", "m0", "head", "index", "prefix_order",
                                    "missing_prefix", "duplicate_journal", "active_journal"])
def test_reserved_descriptions_refuse_mixed_or_replaced_associations(fault):
    facts, binding = _description(("published", "all_rejected"))
    wire = facts["publication"]["lineage"]
    entry = wire["batches"][-1]
    if fault == "ordinal":
        entry["ordinal"] = True
    elif fault == "request":
        entry["request_sha256"] = "f" * 64
    elif fault == "plan":
        entry["native_plan_sha256"] = "f" * 64
    elif fault == "m0":
        entry["memory_snapshot_sha256"] = "f" * 64
    elif fault == "head":
        wire["head"] = None
    elif fault == "index":
        wire["rejections"].reverse()
    elif fault == "prefix_order":
        wire["batches"][:2] = list(reversed(wire["batches"][:2]))
    elif fault == "missing_prefix":
        wire["batches"].pop(0)
    elif fault == "duplicate_journal":
        entry["journal_id"] = wire["batches"][0]["journal_id"]
    else:
        entry["rejected_journal"]["journal_id"] = "foreign"
    with pytest.raises((RSILearningError, ValueError)):
        _messages(facts, binding, reserved=True)


@pytest.mark.parametrize("reserved", [1, None, "true", object()])
def test_reserved_mode_must_be_exact_bool_before_any_message_hook(reserved):
    with pytest.raises(RSILearningError, match="reserved_mode_invalid"):
        _messages(object(), object(), reserved=reserved)
