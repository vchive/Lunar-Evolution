"""Provider-free generation provenance, callback recovery, and quarantine coverage."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.rsi_callbacks import DurableCallbackJournal
from lunar_evolution.rsi_governance_coordinator import (
    GenerationGovernanceError,
    GenerationGovernancePolicy,
    RSIGovernanceCoordinator,
)
from lunar_evolution.rsi_identity import component_fingerprint
from lunar_evolution.rsi_learning import (
    EMPTY_MEMORY_SNAPSHOT,
    MemoryItem,
    MemorySnapshot,
    RSILearningError,
    VerifierCheck,
    VerifierDecision,
)
from lunar_evolution.rsi_memory_governance import MemoryGovernanceError, MemoryGovernanceStore
from lunar_evolution.rsi_store import RSILedger
from lunar_evolution.rsi_transfer_regression import (
    TransferObservation,
    TransferRegressionSuite,
    TransferTask,
)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


PINS = {"contract": digest("contract"), "evaluator": digest("evaluator"),
        "environment": digest("environment"), "solver": "fixture"}
TASKS = (TransferTask("seen", "family-a", "seen", "seen-target", digest("seen")),
         TransferTask("unseen-a", "family-a", "unseen", "target-a", digest("unseen-a")),
         TransferTask("unseen-b", "family-b", "unseen", "target-b", digest("unseen-b")))


def item(identity: str) -> MemoryItem:
    return MemoryItem(identity, "fixture", "condition", "action", "result", "boundary",
                      (PINS["contract"],), ("fixture",), "pass", digest(identity + ":receipt"),
                      identity + ":episode")


def proof(entry: MemoryItem) -> VerifierDecision:
    return VerifierDecision(entry.episode_id, "pass", entry.receipt_sha256, "independent fixture pass",
                            digest("verifier"), (VerifierCheck("contract", "pass", digest("check")),),
                            contract_sha256=PINS["contract"], evaluator_sha256=PINS["evaluator"],
                            environment_sha256=PINS["environment"])


def candidate(parent=EMPTY_MEMORY_SNAPSHOT, identity="generation-1", entries=None):
    return MemorySnapshot(identity, parent.digest(), tuple(entries or (item("memory-1"),)))


class FixtureRegression:
    def __init__(self, *, rejected=False, fail=False, malformed=False, contamination=False):
        self.rejected = rejected
        self.fail = fail
        self.malformed = malformed
        self.contamination = contamination
        self.calls = 0
        self.request = None

    def rsi_fingerprint_config(self):
        return {"rejected": self.rejected, "malformed": self.malformed,
                "contamination": self.contamination, "manifest": [task.to_dict() for task in TASKS]}

    def __call__(self, request):
        self.calls += 1
        self.request = request
        if self.fail:
            raise RuntimeError("uncertain local callback")
        report = self.report(request)
        return replace(report, holdout_receipt_sha256=digest("forged")) if self.malformed else report

    def report(self, request):
        def trial(task, memory, repetition):
            current = memory.digest() == request.current_memory.digest()
            score = 0.1 if self.rejected else (0.9 if current else 0.3)
            return TransferObservation(not self.rejected, score, 1.0,
                                       (task.task_id,), ("foreign",) if self.contamination else
                                       tuple(entry.memory_id for entry in memory.items))
        return TransferRegressionSuite(policy=request.policy).run(
            TASKS, old_memory=request.parent_memory, current_memory=request.current_memory, runner=trial,
        )


@pytest.fixture
def coordinator(tmp_path: Path):
    ledger = RSILedger(tmp_path / "rsi.sqlite3")
    governance = MemoryGovernanceStore(tmp_path / "governance.sqlite3")
    return RSIGovernanceCoordinator(governance, ledger=ledger, scope="fixture",
                                    compatibility=PINS, policy=GenerationGovernancePolicy())


def activate(coordinator, parent=EMPTY_MEMORY_SNAPSHOT, identity="generation-1", entries=None, runner=None):
    snapshot = candidate(parent, identity, entries)
    old_ids = {entry.memory_id for entry in parent.items}
    result = coordinator.admit_generation(identity, snapshot, parent,
                                          {entry.memory_id: proof(entry) for entry in snapshot.items
                                           if entry.memory_id not in old_ids}, runner or FixtureRegression())
    return snapshot, result


def test_full_generation_activation_and_read_only_terminal_replay(coordinator):
    runner = FixtureRegression()
    initial_fingerprint = component_fingerprint(coordinator)
    snapshot, result = activate(coordinator, runner=runner, entries=(item("m1"), item("m2")))
    assert result.status == "active"
    assert result.effective_snapshot == snapshot
    coordinator.validate(snapshot)
    journal = coordinator.inspect("generation-1")
    histories = [coordinator.governance.history(identity) for identity in result.admissions.values()]
    assert all([record.state for record in history] ==
               ["observed", "verified", "candidate", "shadow", "approved", "active"] for history in histories)
    activate(coordinator, runner=runner, entries=(item("m1"), item("m2")))
    assert runner.calls == 1
    assert coordinator.inspect("generation-1") == journal
    assert component_fingerprint(coordinator) == initial_fingerprint
    assert RSIGovernanceCoordinator.deserialize_report(
        RSIGovernanceCoordinator.serialize_report(result.report),
    ).to_dict() == result.report.to_dict()


def test_second_generation_re_admits_inherited_items_and_source_revocation_blocks_it(coordinator):
    parent, first = activate(coordinator)
    current, second = activate(coordinator, parent, "generation-2", (*parent.items, item("memory-2")))
    coordinator.validate(current)
    assert first.admissions["memory-1"] != second.admissions["memory-1"]
    origin = coordinator.inspect("generation-2")[1]["intent"]["provenance"]["memory-1"]
    assert origin["kind"] == "inherited"
    assert origin["parent_admission_id"] == first.admissions["memory-1"]
    source = coordinator.governance.get(first.admissions["memory-1"])
    coordinator.governance.revoke(source.admission_id, expected_record_sha256=source.record_sha256,
                                 reason="source invalidated")
    with pytest.raises(GenerationGovernanceError, match="revoked"):
        coordinator.validate(current)


@pytest.mark.parametrize("kind", ["missing", "receipt", "contract", "evaluator", "environment", "fail"])
def test_invalid_source_proofs_fail_before_admission_or_callback(coordinator, kind):
    snapshot = candidate()
    decision = proof(snapshot.items[0])
    changes = {"receipt": {"receipt_sha256": digest("other")}, "contract": {"contract_sha256": digest("other")},
               "evaluator": {"evaluator_sha256": None}, "environment": {"environment_sha256": None},
               "fail": {"outcome": "fail"}}
    proofs = {} if kind == "missing" else {"memory-1": replace(decision, **changes[kind])}
    runner = FixtureRegression()
    with pytest.raises(GenerationGovernanceError, match="proof_mapping|source_verifier"):
        coordinator.admit_generation("generation-1", snapshot, EMPTY_MEMORY_SNAPSHOT, proofs, runner)
    assert coordinator.inspect("generation-1") is None
    assert runner.calls == 0


def test_inherited_item_id_cannot_be_reused_for_changed_content(coordinator):
    parent, _result = activate(coordinator)
    changed = candidate(parent, "generation-2", (replace(parent.items[0], strategy="changed"),))
    runner = FixtureRegression()
    with pytest.raises(GenerationGovernanceError, match="inherited_item_drift"):
        coordinator.admit_generation("generation-2", changed, parent, {}, runner)
    assert runner.calls == 0


def test_rejected_report_keeps_parent_and_shadow_items(coordinator):
    parent, _result = activate(coordinator)
    runner = FixtureRegression(rejected=True)
    current, result = activate(coordinator, parent, "generation-2", (*parent.items, item("new")), runner)
    assert result.status == "rejected"
    assert result.effective_snapshot == parent
    assert all(coordinator.governance.get(identity).state == "shadow" for identity in result.admissions.values())
    with pytest.raises(GenerationGovernanceError, match="inactive"):
        coordinator.validate(current)
    activate(coordinator, parent, "generation-2", (*parent.items, item("new")), runner)
    assert runner.calls == 1


def reconcile(coordinator, runner, generation_id="generation-1", validation_id=None):
    callback_id = "holdout" if validation_id is None else "revalidation:" + validation_id
    head, callback = coordinator.callbacks.inspect(coordinator._namespace(generation_id), callback_id)
    report = runner.report(runner.request)
    result = coordinator.serialize_report(report)
    evidence = {"source": "trusted-local-fixture", "binding_sha256": callback["binding_sha256"],
                "result_sha256": DurableCallbackJournal.digest(result), "receipt_sha256": digest("local-evidence")}
    return coordinator.reconcile_holdout(generation_id, expected_checkpoint_sha256=head,
                                         report=report, evidence=evidence, validation_id=validation_id)


def test_unknown_never_retries_and_bound_reconcile_activates(coordinator):
    runner = FixtureRegression(fail=True)
    snapshot, result = activate(coordinator, runner=runner)
    assert result.status == "unknown"
    assert result.effective_snapshot == EMPTY_MEMORY_SNAPSHOT
    runner.fail = False
    activate(coordinator, runner=runner)
    assert runner.calls == 1
    result = reconcile(coordinator, runner)
    assert result.status == "active"
    coordinator.validate(snapshot)
    result = reconcile(coordinator, runner)
    assert result.status == "active"
    assert runner.calls == 1


def test_unknown_reconcile_refuses_unbound_evidence(coordinator):
    runner = FixtureRegression(fail=True)
    snapshot, result = activate(coordinator, runner=runner)
    head, _callback = coordinator.callbacks.inspect(coordinator._namespace("generation-1"), "holdout")
    report = runner.report(runner.request)
    evidence = {"source": "fixture", "binding_sha256": digest("wrong"),
                "result_sha256": DurableCallbackJournal.digest(coordinator.serialize_report(report)),
                "receipt_sha256": digest("local")}
    with pytest.raises(ValueError, match="evidence_invalid"):
        coordinator.reconcile_holdout("generation-1", expected_checkpoint_sha256=head, report=report,
                                      evidence=evidence)
    assert coordinator.inspect("generation-1")[1]["phase"] == "unknown"
    assert all(coordinator.governance.get(identity).state == "shadow" for identity in result.admissions.values())
    with pytest.raises(GenerationGovernanceError, match="inactive"):
        coordinator.validate(snapshot)


@pytest.mark.parametrize("crash_at", ["verified", "shadow", "approved", "active"])
def test_mid_lifecycle_crash_resumes_without_duplicate_edges_or_holdout(coordinator, monkeypatch, crash_at):
    transition = coordinator.governance.transition
    crashed = False

    def interrupt(admission_id, state, **kwargs):
        nonlocal crashed
        record = transition(admission_id, state, **kwargs)
        if state == crash_at and not crashed:
            crashed = True
            raise KeyboardInterrupt("fixture crash after durable append")
        return record

    monkeypatch.setattr(coordinator.governance, "transition", interrupt)
    runner = FixtureRegression()
    with pytest.raises(KeyboardInterrupt):
        activate(coordinator, runner=runner)
    monkeypatch.setattr(coordinator.governance, "transition", transition)
    snapshot, result = activate(coordinator, runner=runner)
    assert result.status == "active"
    coordinator.validate(snapshot)
    assert runner.calls == 1
    assert len(coordinator.governance.history(result.admissions["memory-1"])) == 6


def test_completed_callback_reused_after_missing_generation_report(coordinator, monkeypatch):
    finish = coordinator._finish

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt("fixture crash before report persistence")

    monkeypatch.setattr(coordinator, "_finish", interrupt)
    runner = FixtureRegression()
    with pytest.raises(KeyboardInterrupt):
        activate(coordinator, runner=runner)
    monkeypatch.setattr(coordinator, "_finish", finish)
    _snapshot, result = activate(coordinator, runner=runner)
    assert result.status == "active"
    assert runner.calls == 1


def test_active_revalidation_rejection_quarantines_all_items_and_is_durable(coordinator):
    snapshot, initial = activate(coordinator, entries=(item("one"), item("two")))
    runner = FixtureRegression(rejected=True)
    result = coordinator.revalidate_generation("generation-1", "scheduled-1", runner)
    assert result.status == "quarantined"
    assert result.effective_snapshot == EMPTY_MEMORY_SNAPSHOT
    assert all(coordinator.governance.get(identity).state == "revoked" for identity in initial.admissions.values())
    with pytest.raises(GenerationGovernanceError, match="inactive"):
        coordinator.validate(snapshot)
    before = coordinator.inspect("generation-1")
    coordinator.revalidate_generation("generation-1", "scheduled-1", runner)
    assert coordinator.inspect("generation-1") == before
    assert runner.calls == 1


def test_unknown_active_revalidation_blocks_current_until_reconciled(coordinator):
    snapshot, _result = activate(coordinator)
    runner = FixtureRegression(fail=True)
    result = coordinator.revalidate_generation("generation-1", "scheduled-1", runner)
    assert result.status == "revalidating"
    assert result.effective_snapshot == EMPTY_MEMORY_SNAPSHOT
    with pytest.raises(GenerationGovernanceError, match="inactive"):
        coordinator.validate(snapshot)
    coordinator.revalidate_generation("generation-1", "scheduled-1", runner)
    assert runner.calls == 1
    result = reconcile(coordinator, runner, validation_id="scheduled-1")
    assert result.status == "active"
    coordinator.validate(snapshot)


def test_partial_quarantine_crash_finishes_remaining_revocations(coordinator, monkeypatch):
    snapshot, initial = activate(coordinator, entries=(item("one"), item("two")))
    revoke = coordinator.governance.revoke
    crashed = False

    def interrupt(*args, **kwargs):
        nonlocal crashed
        record = revoke(*args, **kwargs)
        if not crashed:
            crashed = True
            raise KeyboardInterrupt("fixture revoke crash")
        return record

    monkeypatch.setattr(coordinator.governance, "revoke", interrupt)
    runner = FixtureRegression(rejected=True)
    with pytest.raises(KeyboardInterrupt):
        coordinator.revalidate_generation("generation-1", "scheduled-1", runner)
    with pytest.raises(GenerationGovernanceError, match="inactive"):
        coordinator.validate(snapshot)
    monkeypatch.setattr(coordinator.governance, "revoke", revoke)
    result = coordinator.revalidate_generation("generation-1", "scheduled-1", runner)
    assert result.status == "quarantined"
    assert runner.calls == 1
    assert all(coordinator.governance.get(identity).state == "revoked" for identity in initial.admissions.values())


def test_runner_drift_and_missing_explicit_hook_do_not_dispatch(coordinator):
    runner = FixtureRegression(fail=True)
    activate(coordinator, runner=runner)
    changed = FixtureRegression(rejected=True)
    with pytest.raises(GenerationGovernanceError, match="intent_drift"):
        activate(coordinator, runner=changed)
    assert changed.calls == 0
    with pytest.raises(GenerationGovernanceError, match="runner_hook_required"):
        coordinator.admit_generation("other", candidate(identity="other"), EMPTY_MEMORY_SNAPSHOT,
                                      {"memory-1": proof(item("memory-1"))}, lambda *_: None)


def test_policy_or_database_replacement_blocks_resume(coordinator):
    _snapshot, _result = activate(coordinator)
    coordinator.policy = replace(coordinator.policy, max_lineage_depth=3)
    with pytest.raises(GenerationGovernanceError, match="fingerprint_drift"):
        coordinator.inspect("generation-1")
    coordinator.policy = GenerationGovernancePolicy()
    original = coordinator.governance.database
    replacement = original.with_suffix(".replacement")
    replacement.write_bytes(original.read_bytes())
    replacement.replace(original)
    with pytest.raises(GenerationGovernanceError, match="database_changed"):
        coordinator.inspect("generation-1")


def test_malformed_report_cannot_activate_and_cannot_retry(coordinator):
    runner = FixtureRegression(malformed=True)
    with pytest.raises(GenerationGovernanceError, match="report_invalid"):
        activate(coordinator, runner=runner)
    assert coordinator.inspect("generation-1")[1]["phase"] == "unknown"
    _snapshot, result = activate(coordinator, runner=runner)
    assert result.status == "unknown"
    assert runner.calls == 1


def test_raw_trials_must_roundtrip_and_contamination_cannot_be_erased(coordinator):
    runner = FixtureRegression(contamination=True)
    _snapshot, result = activate(coordinator, runner=runner)
    assert result.status == "rejected"
    encoded = coordinator.serialize_report(result.report)
    encoded["trials"][0]["observation"]["score"] = 0.99
    with pytest.raises(GenerationGovernanceError, match="report_invalid"):
        coordinator.deserialize_report(encoded)


def test_old_completed_revalidation_cannot_unblock_a_new_unknown_call(coordinator):
    snapshot, _result = activate(coordinator)
    good = FixtureRegression()
    coordinator.revalidate_generation("generation-1", "completed-1", good)
    uncertain = FixtureRegression(fail=True)
    coordinator.revalidate_generation("generation-1", "pending-2", uncertain)
    with pytest.raises(GenerationGovernanceError, match="revalidation_pending"):
        coordinator.revalidate_generation("generation-1", "completed-1", good)
    with pytest.raises(GenerationGovernanceError, match="inactive"):
        coordinator.validate(snapshot)
    assert good.calls == 1
    assert uncertain.calls == 1


def test_durable_resume_with_reconstructed_coordinator(coordinator):
    runner = FixtureRegression(fail=True)
    snapshot, result = activate(coordinator, runner=runner)
    recovered = RSIGovernanceCoordinator(
        MemoryGovernanceStore(coordinator.governance.database),
        ledger=RSILedger(coordinator.ledger.database), scope="fixture", compatibility=PINS,
        policy=GenerationGovernancePolicy(),
    )
    assert component_fingerprint(coordinator) == component_fingerprint(recovered)
    _snapshot, replay = activate(recovered, runner=runner)
    assert result == replay
    assert runner.calls == 1
    runner.fail = False
    reconcile(recovered, runner)
    recovered.validate(snapshot)


def test_cas_conflict_before_holdout_preserves_resume_without_dispatch(coordinator, monkeypatch):
    transition = coordinator.governance.transition

    def conflict(*args, **kwargs):
        raise MemoryGovernanceError("rsi_memory_governance_cas_conflict")

    monkeypatch.setattr(coordinator.governance, "transition", conflict)
    runner = FixtureRegression()
    with pytest.raises(MemoryGovernanceError, match="cas_conflict"):
        activate(coordinator, runner=runner)
    assert runner.calls == 0
    monkeypatch.setattr(coordinator.governance, "transition", transition)
    _snapshot, result = activate(coordinator, runner=runner)
    assert result.status == "active"
    assert runner.calls == 1


def test_non_independent_mutated_pass_proof_is_rejected(coordinator):
    snapshot = candidate()
    decision = proof(snapshot.items[0])
    object.__setattr__(decision, "independent_of_actor", False)
    with pytest.raises(GenerationGovernanceError, match="source_verifier_invalid"):
        coordinator.admit_generation("generation-1", snapshot, EMPTY_MEMORY_SNAPSHOT,
                                      {"memory-1": decision}, FixtureRegression())


def test_foreign_current_memory_cannot_be_hidden_by_forged_aggregate_report(coordinator):
    snapshot = candidate()
    runner = FixtureRegression()

    class ForgedRegression(FixtureRegression):
        def __call__(self, request):
            self.calls += 1

            def trial(task, memory, repetition):
                current = memory.digest() == request.current_memory.digest()
                return TransferObservation(True, 0.9 if current else 0.3, accessed_task_ids=(task.task_id,),
                                           memory_ids_used=("foreign",) if current else ())

            report = TransferRegressionSuite(policy=request.policy).run(
                TASKS, old_memory=request.parent_memory, current_memory=request.current_memory, runner=trial,
            )
            forged = replace(report, contamination=(), promotion_eligible=True, rejection_reasons=())
            payload = forged.to_dict()
            for key in ("protocol", "schema_version", "report_sha256"):
                payload.pop(key)
            forged = replace(forged, report_sha256=hashlib.sha256(canonical_json(payload, maximum=128 * 1024)).hexdigest())
            forged.validate_policy_evidence()
            return forged

    runner = ForgedRegression()
    with pytest.raises(GenerationGovernanceError, match="report_contamination_drift"):
        coordinator.admit_generation("generation-1", snapshot, EMPTY_MEMORY_SNAPSHOT,
                                      {"memory-1": proof(snapshot.items[0])}, runner)
    assert coordinator.inspect("generation-1")[1]["phase"] == "unknown"
    assert runner.calls == 1


def test_lineage_depth_bound_stops_new_generation_before_callback(coordinator):
    coordinator.policy = replace(coordinator.policy, max_lineage_depth=1)
    # Construct a fresh static policy rather than mutating an already pinned coordinator.
    bounded = RSIGovernanceCoordinator(coordinator.governance, ledger=coordinator.ledger, scope="bounded",
                                       compatibility=PINS, policy=coordinator.policy)
    parent, _result = activate(bounded)
    runner = FixtureRegression()
    with pytest.raises(GenerationGovernanceError, match="lineage_limit"):
        activate(bounded, parent, "generation-2", (*parent.items, item("new")), runner)
    assert runner.calls == 0


@pytest.mark.parametrize("code", ["rsi_budget_exhausted", "rsi_parent_budget_unavailable", "rsi_regression_intent_drift"])
def test_budget_or_identity_stop_is_propagated_with_outer_started_gate(coordinator, code):
    class StoppedRegression(FixtureRegression):
        def __call__(self, request):
            self.calls += 1
            raise RSILearningError(code)

    runner = StoppedRegression()
    with pytest.raises(RSILearningError, match=code):
        activate(coordinator, runner=runner)
    assert coordinator.inspect("generation-1")[1]["phase"] == "unknown"
    callback = coordinator.callbacks.inspect(coordinator._namespace("generation-1"), "holdout")
    assert callback[1]["status"] == "started"
    _snapshot, result = activate(coordinator, runner=runner)
    assert result.status == "unknown"
    assert runner.calls == 1


def test_standard_manifest_is_frozen_and_substitute_report_refused(coordinator):
    class SubstituteManifest(FixtureRegression):
        def report(self, request):
            substitute = tuple(replace(task, input_sha256=digest("substitute:" + task.task_id)) for task in TASKS)
            return TransferRegressionSuite(policy=request.policy).run(
                substitute, old_memory=request.parent_memory, current_memory=request.current_memory,
                runner=lambda _task, memory, _repeat: TransferObservation(
                    True, 0.9 if memory.digest() == request.current_memory.digest() else 0.3,
                ),
            )

    runner = SubstituteManifest()
    with pytest.raises(GenerationGovernanceError, match="report_binding_drift"):
        activate(coordinator, runner=runner)
    assert coordinator.inspect("generation-1")[1]["intent"]["runner_manifest"] == [task.to_dict() for task in TASKS]
    assert runner.request.manifest == TASKS
    assert runner.calls == 1


def test_unknown_reconcile_must_match_frozen_standard_manifest(coordinator):
    runner = FixtureRegression(fail=True)
    activate(coordinator, runner=runner)
    head, callback = coordinator.callbacks.inspect(coordinator._namespace("generation-1"), "holdout")
    substitute = tuple(replace(task, input_sha256=digest("changed:" + task.task_id)) for task in TASKS)
    report = TransferRegressionSuite(policy=runner.request.policy).run(
        substitute, old_memory=runner.request.parent_memory, current_memory=runner.request.current_memory,
        runner=lambda _task, memory, _repeat: TransferObservation(
            True, 0.9 if memory.digest() == runner.request.current_memory.digest() else 0.3,
        ),
    )
    evidence = {"source": "fixture", "binding_sha256": callback["binding_sha256"],
                "result_sha256": DurableCallbackJournal.digest(coordinator.serialize_report(report)),
                "receipt_sha256": digest("local")}
    with pytest.raises(GenerationGovernanceError, match="report_binding_drift"):
        coordinator.reconcile_holdout("generation-1", expected_checkpoint_sha256=head,
                                      report=report, evidence=evidence)
    assert coordinator.inspect("generation-1")[1]["phase"] == "unknown"
    assert runner.calls == 1


def test_explicit_local_legacy_hook_without_standard_manifest_preserves_contract(coordinator):
    class LegacyLocalFixture(FixtureRegression):
        def rsi_fingerprint_config(self):
            return {"legacy-fixture": True}

    runner = LegacyLocalFixture()
    _snapshot, result = activate(coordinator, runner=runner)
    assert result.status == "active"
    assert runner.request.manifest is None


def test_standard_manifest_policy_coverage_refused_before_journal_or_callback(coordinator):
    class IncompleteManifest(FixtureRegression):
        def rsi_fingerprint_config(self):
            return {"manifest": [TASKS[0].to_dict()]}

    runner = IncompleteManifest()
    with pytest.raises(GenerationGovernanceError, match="manifest_invalid"):
        activate(coordinator, runner=runner)
    assert coordinator.inspect("generation-1") is None
    assert runner.calls == 0
