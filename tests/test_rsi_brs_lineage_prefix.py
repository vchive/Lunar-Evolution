"""Pure comparisons of bounded historical observations; no real native work."""
from __future__ import annotations

import hashlib
import itertools
import json
from copy import deepcopy
from dataclasses import replace

import pytest

from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.producer_bundle_lineage import (
    MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES,
    MAX_LINEAGE_SNAPSHOT_BYTES,
    LineageSnapshotPin,
    ProducerLineageBeforeIntent,
    ProducerLineageStagedTransition,
    ProducerLineageTerminal,
)
from lunar_evolution.producer_bundle_lineage_v2 import (
    ProducerLineageBeforeIntentV2,
    ProducerLineageRejectedTerminalV2,
)
from lunar_evolution.rsi_brs_lineage_prefix import (
    MAX_BRS_PREFIX_BYTES,
    validate_brs_reserved_append,
    validate_brs_reserved_prefix,
)
from lunar_evolution.rsi_controller import PracticeEpisodeRunner
from lunar_evolution.rsi_gateway import LocalExactVerifier, SolverRequest, SolverResult
from lunar_evolution.rsi_learning import (
    EMPTY_MEMORY_SNAPSHOT,
    PracticeEpisode,
    RSILearningError,
    VerifierCheck,
    VerifierDecision,
)


def _sha(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


def _wave(outcomes, *, candidates=1):
    run, wave, memory = "prefix-run", 1, EMPTY_MEMORY_SNAPSHOT
    requests = [SolverRequest.build(episode_id=f"{run}-practice-{wave}-{i}", contract_sha256=_sha("contract"),
                                   evaluator_sha256=_sha("evaluator"), environment_sha256=_sha("environment"),
                                   memory_snapshot_sha256=memory.digest(), solver_id="fixture")
                for i in range(len(outcomes))]
    domain = {"run_id": run, "wave": wave, "episode_ids": tuple(request.episode_id for request in requests),
              "request_sha256s": tuple(request.digest() for request in requests), "root_snapshot_sha256": memory.digest(),
              "base_checkpoint_sha256": _sha("base")}
    inodes, batches, executions = itertools.count(10), [], {}

    def pin(name, digest, size):
        return LineageSnapshotPin(name, digest, size, 1, next(inodes), 1, 2)

    def envelope(descriptor):
        raw = descriptor.to_json()
        return {"descriptor": descriptor.to_dict(), "file_pin": pin(descriptor.kind + ".json",
                hashlib.sha256(raw).hexdigest(), len(raw)).to_dict()}

    previous = published = None
    archive, state, head = (_sha("archive-0"), 1), (_sha("state-0"), 1), domain["base_checkpoint_sha256"]
    for i, (request, outcome) in enumerate(zip(requests, outcomes, strict=True)):
        jid, eid, status = f"journal-{i}", request.episode_id, "completed" if outcome == "published" else "failed"
        verifier = VerifierDecision(eid, "fail", _sha("verify"), "fixture", _sha("verifier"),
                                    (VerifierCheck("diagnosis", "fail", _sha("check")),))
        receipts = (_sha("candidate"), _sha("execution"), _sha("evaluation")) if status == "completed" else (None, None, None)
        result = SolverResult(eid, request.digest(), status, *receipts, _sha(f"trace-{i}"))
        episode = PracticeEpisode(eid, run, request.contract_sha256, request.evaluator_sha256,
                                  request.environment_sha256, memory.digest(), "fixture", status,
                                  verifier if status == "completed" else None, wave=wave, ordinal=i,
                                  request_sha256=request.digest(), trace_digest=result.trace_digest,
                                  candidate_receipt_sha256=receipts[0], execution_receipt_sha256=receipts[1],
                                  official_evaluation_receipt_sha256=receipts[2],
                                  terminal_reason="inert-failed" if status == "failed" else None)
        execution = {"episode": episode.to_record_dict(), "request": request.to_dict(),
                     "result": result.to_dict(), "verifier": verifier.to_dict()}
        archive_pin, state_pin = pin("archive-before.snapshot", *archive), pin("state-before.snapshot", *state)
        if i == 0:
            before = ProducerLineageBeforeIntent(run, jid, i, None, None, archive_pin, state_pin)
        else:
            before = ProducerLineageBeforeIntentV2(run, jid, i, *previous,
                                                   *(published if published else (None, None, None)), archive_pin, state_pin)
        snapshots = {"archive-before": archive_pin.to_dict(), "state-before": state_pin.to_dict()}
        staged = None
        ids = tuple(f"candidate-{i}-{j}" for j in range(candidates))
        if outcome == "published":
            archive, state = (_sha(f"archive-{i + 1}"), i + 2), (_sha(f"state-{i + 1}"), i + 2)
            snapshots.update({"archive-after": pin("archive-after.snapshot", *archive).to_dict(),
                              "state-after": pin("state-after.snapshot", *state).to_dict()})
            staged = ProducerLineageStagedTransition(run, jid, i, before.digest(), _sha(f"staged-{i}"),
                                                     _sha(f"manifest-{i}"), archive[0], state[0], ids)
            terminal = ProducerLineageTerminal(run, jid, i, staged.digest(), _sha(f"marker-{i}"), archive[0], state[0])
            previous = (jid, outcome, terminal.terminal_sha256, terminal.digest())
            published = (jid, terminal.terminal_sha256, terminal.digest())
        else:
            terminal = ProducerLineageRejectedTerminalV2(run, jid, eid, i, before.digest(), _sha(f"prepared-{i}"),
                _sha(f"rejected-{i}"), _sha(f"manifest-{i}"), _sha(f"marker-{i}"), ids, archive[0], state[0])
            previous = (jid, outcome, terminal.terminal_marker_sha256, terminal.digest())
        before_wire, terminal_wire = envelope(before), envelope(terminal)
        staged_wire = envelope(staged) if staged else None
        required = [before_wire["file_pin"], terminal_wire["file_pin"], *snapshots.values()]
        if staged_wire:
            required.append(staged_wire["file_pin"])
        materials = tuple({"relative_path": f"evolution/producer-batches/{jid}/lineage/{item['name']}",
                           "file_pin": item} for item in required)
        plan = _sha(f"plan-{i}")
        claim = {"episode_id": eid, "request_sha256": request.digest(), "plan_sha256": plan,
                 "status": status, "created_at": "2026-10-18T00:00:00Z"}
        claim["claim_sha256"] = hashlib.sha256(canonical_json({"protocol": "lunar-rsi-native-episode-claim-v1",
                    "episode_id": eid, "request_sha256": request.digest(), "plan_sha256": plan})).hexdigest()
        executions[eid] = execution
        root = {"run_id": run, "mode": "brs", "status": "running", "phase": "evaluated", "current_episode_id": eid,
                "root_snapshot": memory.to_dict(), "executions": deepcopy(executions),
                "intents": {r.episode_id: {"request": r.to_dict()} for r in requests}}
        root_head = _sha(f"root-{i}")
        batches.append({"ordinal": i, "episode_id": eid, "request_sha256": request.digest(), "native_plan_sha256": plan,
                        "outcome": outcome, "execution_bytes": canonical_json(execution), "entry_checkpoint_sha256": head,
                        "root_checkpoint": (root_head, root), "claim": claim, "before": before_wire,
                        "staged": staged_wire, "terminal": terminal_wire, "snapshots": snapshots, "materials": materials})
        head = root_head
    return domain, tuple(batches)


@pytest.mark.parametrize("outcomes", list(itertools.product(("published", "all_rejected"), repeat=2)) + [
    ("published", "all_rejected", "published"), ("all_rejected", "published", "all_rejected")])
def test_mixed_outcomes_append_genuine_distinct_descriptor_formats_and_preserve_history(outcomes):
    domain, batches = _wave(outcomes)
    saved = deepcopy(batches)
    prefix = validate_brs_reserved_prefix(**domain, batches=())
    assert prefix.settled_prefix == () and prefix.tail_checkpoint_sha256 == domain["base_checkpoint_sha256"]
    for count in range(1, len(batches) + 1):
        old = prefix
        prefix = validate_brs_reserved_append(prefix, batches=batches[:count])
        assert prefix.batch_bytes[:-1] == old.batch_bytes
    assert [row[1] for row in prefix.settled_prefix] == list(outcomes)
    assert prefix.previous_attempt[0] == f"journal-{len(outcomes) - 1}"
    published = [i for i, outcome in enumerate(outcomes) if outcome == "published"]
    assert (prefix.published_predecessor[0] if prefix.published_predecessor else None) == (
        f"journal-{published[-1]}" if published else None)
    assert prefix.tail_checkpoint_sha256 == batches[-1]["root_checkpoint"][0]
    assert batches == saved


def test_max_eight_children_and_thirty_two_candidates_fit_without_recharging():
    domain, batches = _wave(("published", "all_rejected") * 4, candidates=4)
    prefix = validate_brs_reserved_prefix(**domain, batches=batches)
    assert len(prefix.settled_prefix) == 8
    assert json.loads(prefix.canonical_bytes)["candidate_count"] == 32
    domain9 = {**domain, "episode_ids": (*domain["episode_ids"], "prefix-run-practice-1-8"),
               "request_sha256s": (*domain["request_sha256s"], _sha("ninth"))}
    with pytest.raises(RSILearningError, match="domain_invalid"):
        validate_brs_reserved_prefix(**domain9, batches=batches)


def test_thirty_third_candidate_refuses_without_changing_the_original_domain():
    domain, batches = _wave(("published",) * 3, candidates=11)
    with pytest.raises(RSILearningError, match="candidate_capacity_or_duplicate"):
        validate_brs_reserved_prefix(**domain, batches=batches)


@pytest.mark.parametrize("decision", ["pass", "fail", "unresolved"])
def test_actual_runner_keeps_published_completion_separate_from_rsi_verifier_decision(decision):
    domain, batches = _wave(("published",))
    wire = json.loads(batches[0]["execution_bytes"])
    request, result = SolverRequest.from_dict(wire["request"]), SolverResult.from_dict(wire["result"])
    planned = PracticeEpisode(request.episode_id, domain["run_id"], request.contract_sha256,
                              request.evaluator_sha256, request.environment_sha256,
                              request.memory_snapshot_sha256, request.solver_id,
                              "planned", wave=domain["wave"], ordinal=0)

    class InertGateway:
        calls = 0

        def run(self, actual):
            assert actual == request
            self.calls += 1
            return result

    class IndependentVerifier:
        def verify(self, episode, actual, observed):
            assert episode.status == "completed" and actual == request and observed == result
            if decision == "pass":
                return LocalExactVerifier().verify(episode, actual, observed)
            return VerifierDecision(request.episode_id, decision, _sha("verify"), "fixture", _sha("verifier"),
                                    (VerifierCheck("diagnosis", decision, _sha("check")),))

    gateway = InertGateway()
    execution = PracticeEpisodeRunner(gateway, IndependentVerifier()).run(planned, request)
    wire = {"episode": execution.episode.to_record_dict(), "request": execution.request.to_dict(),
            "result": execution.result.to_dict(), "verifier": execution.verifier.to_dict()}
    assert execution.episode.status == execution.result.status == "completed"
    assert execution.episode.verifier.outcome == decision
    batches[0]["execution_bytes"] = canonical_json(wire)
    batches[0]["root_checkpoint"][1]["executions"][request.episode_id] = wire
    prefix = validate_brs_reserved_prefix(**domain, batches=batches)
    assert prefix.settled_prefix[0][1] == "published" and gateway.calls == 1


@pytest.mark.parametrize("fault", ["candidate_receipt_sha256", "execution_receipt_sha256",
                                  "official_evaluation_receipt_sha256", "missing_episode_verifier"])
def test_published_execution_requires_matching_episode_result_receipts_and_attached_verifier(fault):
    domain, batches = _wave(("published",))
    wire = json.loads(batches[0]["execution_bytes"])
    if fault == "missing_episode_verifier":
        episode = PracticeEpisode.from_dict(wire["episode"])
        wire["episode"] = replace(episode, verifier=None).to_record_dict()
    else:
        wire["result"][fault] = _sha("foreign-receipt")
    batches[0]["execution_bytes"] = canonical_json(wire)
    batches[0]["root_checkpoint"][1]["executions"][domain["episode_ids"][0]] = wire
    with pytest.raises(RSILearningError, match="execution_invalid"):
        validate_brs_reserved_prefix(**domain, batches=batches)


@pytest.mark.parametrize("fault", ["ordinal", "episode", "request", "entry_head", "root_head", "root_execution", "claim", "memory"])
def test_association_drift_never_changes_original_observations(fault):
    domain, batches = _wave(("published", "all_rejected"))
    changed = deepcopy(batches)
    if fault == "ordinal":
        changed[0]["ordinal"] = True
    elif fault == "episode":
        changed[0]["episode_id"] = domain["episode_ids"][1]
    elif fault == "request":
        changed[0]["request_sha256"] = domain["request_sha256s"][1]
    elif fault == "entry_head":
        changed[1]["entry_checkpoint_sha256"] = domain["base_checkpoint_sha256"]
    elif fault == "root_head":
        changed[1]["root_checkpoint"] = (changed[0]["root_checkpoint"][0], changed[1]["root_checkpoint"][1])
    elif fault == "root_execution":
        changed[1]["root_checkpoint"][1]["executions"][domain["episode_ids"][0]]["result"]["trace_digest"] = _sha("changed")
    elif fault == "claim":
        changed[0]["claim"]["status"] = "started"
    else:
        domain = {**domain, "root_snapshot_sha256": _sha("foreign-memory")}
    with pytest.raises(RSILearningError):
        validate_brs_reserved_prefix(**domain, batches=changed)
    assert batches != changed or fault == "memory"


@pytest.mark.parametrize("axis", ["attempt", "published"])
def test_previous_attempt_and_older_published_axes_are_independently_required(axis):
    domain, batches = _wave(("published", "all_rejected", "published"))
    changed = deepcopy(batches)
    before = ProducerLineageBeforeIntentV2.from_dict(changed[2]["before"]["descriptor"])
    if axis == "attempt":
        before = replace(before, previous_attempt_terminal_sha256=_sha("false-attempt"), descriptor_sha256=None)
    else:
        before = replace(before, published_predecessor_journal_id=None, published_predecessor_terminal_sha256=None,
                         published_predecessor_lineage_sha256=None, descriptor_sha256=None)
    changed[2]["before"]["descriptor"] = before.to_dict()
    changed[2]["before"]["file_pin"].update(sha256=hashlib.sha256(before.to_json()).hexdigest(), size=len(before.to_json()))
    with pytest.raises(RSILearningError, match="predecessor_drift"):
        validate_brs_reserved_prefix(**domain, batches=changed)


def test_unchanged_content_on_new_historical_snapshot_inodes_is_legitimate():
    domain, batches = _wave(("published", "all_rejected"))
    assert batches[0]["snapshots"]["archive-after"]["inode"] != batches[1]["snapshots"]["archive-before"]["inode"]
    assert batches[0]["snapshots"]["archive-after"]["sha256"] == batches[1]["snapshots"]["archive-before"]["sha256"]
    assert len(validate_brs_reserved_prefix(**domain, batches=batches).settled_prefix) == 2


def test_same_bytes_replaced_original_pin_cannot_rebase_an_existing_prefix():
    domain, batches = _wave(("published", "all_rejected"))
    prefix = validate_brs_reserved_prefix(**domain, batches=batches[:1])
    changed = deepcopy(batches)
    pin = changed[0]["before"]["file_pin"]
    pin["inode"] += 10000
    with pytest.raises(RSILearningError, match="historical_prefix_drift"):
        validate_brs_reserved_append(prefix, batches=changed)


@pytest.mark.parametrize("selection", [(1,), (1, 0), (0, 0)])
def test_holes_reorder_and_duplicate_ordinals_refuse(selection):
    domain, batches = _wave(("published", "all_rejected"))
    with pytest.raises(RSILearningError):
        validate_brs_reserved_prefix(**domain, batches=tuple(batches[i] for i in selection))


def _extra(batch, sizes):
    return batch["materials"] + tuple({"relative_path": f"retained/extra-{i}",
        "file_pin": LineageSnapshotPin(f"extra-{i}", _sha("same-content"), size, 2, i + 1000, 2, 3).to_dict()}
        for i, size in enumerate(sizes))


def test_equal_digest_distinct_retained_files_are_both_charged_and_aggregate_bound_is_exact():
    domain, batches = _wave(("all_rejected",))
    required = sum(row["file_pin"]["size"] for row in batches[0]["materials"])
    padding = MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES - required
    chunks = [MAX_LINEAGE_SNAPSHOT_BYTES] * 3 + [padding - MAX_LINEAGE_SNAPSHOT_BYTES * 3]
    batches[0]["materials"] = _extra(batches[0], chunks)
    proof = validate_brs_reserved_prefix(**domain, batches=batches)
    assert json.loads(proof.canonical_bytes)["retained_material_bytes"] == MAX_LINEAGE_AGGREGATE_SNAPSHOT_BYTES
    changed = deepcopy(batches)
    changed[0]["materials"][-1]["file_pin"]["size"] += 1
    with pytest.raises(RSILearningError, match="material_capacity_exhausted"):
        validate_brs_reserved_prefix(**domain, batches=changed)


@pytest.mark.parametrize("fault", ["bool", "missing_field", "subclass", "oversized", "duplicate_path", "physical_alias", "missing_original"])
def test_original_material_table_refuses_bad_full_pins_and_aliases(fault):
    domain, batches = _wave(("all_rejected",))
    row = batches[0]["materials"][0]
    if fault == "bool":
        row["file_pin"]["device"] = True
    elif fault == "missing_field":
        row["file_pin"].pop("ctime_ns")
    elif fault == "subclass":
        class Foreign(dict):
            def items(self):
                pytest.fail("foreign pin hook executed")
        row["file_pin"] = Foreign(row["file_pin"])
    elif fault == "oversized":
        row["file_pin"]["size"] = MAX_LINEAGE_SNAPSHOT_BYTES + 1
    elif fault == "duplicate_path":
        batches[0]["materials"] += (deepcopy(row),)
    elif fault == "physical_alias":
        batches[0]["materials"] += ({"relative_path": "alias/" + row["file_pin"]["name"], "file_pin": deepcopy(row["file_pin"])},)
    else:
        batches[0]["materials"] = batches[0]["materials"][1:]
    with pytest.raises(RSILearningError):
        validate_brs_reserved_prefix(**domain, batches=batches)


def test_actual_projection_ceiling_is_checked_with_original_limits():
    domain, batches = _wave(("all_rejected",))
    batches[0]["materials"] = _extra(batches[0], [1] * 500)
    with pytest.raises(RSILearningError, match="capacity_exhausted"):
        validate_brs_reserved_prefix(**domain, batches=batches)


def test_prefix_is_frozen_detached_and_append_revalidates_its_entire_old_value():
    domain, batches = _wave(("published", "all_rejected"))
    prefix = validate_brs_reserved_prefix(**domain, batches=batches[:1])
    digest, settled = prefix.digest(), prefix.settled_prefix
    batches[0]["root_checkpoint"][1]["phase"] = "foreign"
    assert prefix.digest() == digest and prefix.settled_prefix == settled
    with pytest.raises(RSILearningError):
        validate_brs_reserved_append(prefix, batches=batches)


@pytest.mark.parametrize("fault", ["noncanonical", "wave", "ordinal", "unknown", "verifier", "trace"])
def test_actual_execution_bytes_are_checked_beyond_their_supplied_root_association(fault):
    domain, batches = _wave(("published",))
    execution = json.loads(batches[0]["execution_bytes"])
    if fault == "noncanonical":
        raw = json.dumps(execution, indent=2).encode()
    else:
        if fault == "wave":
            execution["episode"]["wave"] += 1
        elif fault == "ordinal":
            execution["episode"]["ordinal"] = 3
        elif fault == "unknown":
            execution["result"]["status"] = "unknown"
        elif fault == "verifier":
            execution["verifier"]["contract_sha256"] = _sha("foreign-contract")
        else:
            execution["result"]["trace_digest"] = _sha("foreign-trace")
        raw = canonical_json(execution)
    batches[0]["execution_bytes"] = raw
    batches[0]["root_checkpoint"][1]["executions"][domain["episode_ids"][0]] = execution
    with pytest.raises(RSILearningError):
        validate_brs_reserved_prefix(**domain, batches=batches)


@pytest.mark.parametrize("path", ["/absolute/file", "../parent/file", "nested/../file", "nested//file", "nested\\file", "bad\x00/file"])
def test_retained_material_paths_cannot_escape_or_alias_their_original_relative_spelling(path):
    domain, batches = _wave(("all_rejected",))
    batches[0]["materials"] = _extra(batches[0], [1])
    batches[0]["materials"][-1]["relative_path"] = path
    with pytest.raises(RSILearningError):
        validate_brs_reserved_prefix(**domain, batches=batches)


def test_foreign_mapping_hooks_are_never_executed_and_helper_performs_no_io(monkeypatch):
    import builtins
    import sqlite3

    domain, batches = _wave(("all_rejected",))

    def forbidden(*_args, **_kwargs):
        pytest.fail("pure prefix helper attempted IO or a foreign hook")

    class Foreign(dict):
        items = forbidden
        values = forbidden
        __iter__ = forbidden

    with pytest.raises(RSILearningError):
        validate_brs_reserved_prefix(**domain, batches=(Foreign(batches[0]),))
    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", forbidden)
        patch.setattr(sqlite3, "connect", forbidden)
        assert len(validate_brs_reserved_prefix(**domain, batches=batches).settled_prefix) == 1


def test_original_root_depth_and_descriptor_bytes_limits_are_preserved():
    domain, batches = _wave(("all_rejected",))
    nested = None
    for _ in range(34):
        nested = {"nested": nested}
    batches[0]["root_checkpoint"][1]["extra"] = nested
    with pytest.raises(RSILearningError, match="shape_invalid"):
        validate_brs_reserved_prefix(**domain, batches=batches)
    domain, batches = _wave(("all_rejected",))
    batches[0]["before"]["descriptor"]["extra"] = "x" * (32 * 1024)
    with pytest.raises(RSILearningError, match="capacity_exhausted"):
        validate_brs_reserved_prefix(**domain, batches=batches)


@pytest.mark.parametrize("count", [0, 1, 3])
def test_append_requires_exactly_one_new_adjacent_observation(count):
    domain, batches = _wave(("all_rejected",) * 3)
    prefix = validate_brs_reserved_prefix(**domain, batches=batches[:1])
    with pytest.raises(RSILearningError, match="append_invalid"):
        validate_brs_reserved_append(prefix, batches=batches[:count])


@pytest.mark.parametrize("fault", ["domain", "canonical", "batches", "batch_member", "oversized_domain",
                                  "oversized_canonical", "oversized_batch_member", "ninth_batch"])
def test_mutated_frozen_prefix_shape_is_bounded_before_any_equality_hook(fault):
    domain, batches = _wave(("published", "all_rejected"))
    prefix = validate_brs_reserved_prefix(**domain, batches=batches[:1])

    class Foreign:
        def __eq__(self, other):
            pytest.fail("foreign prefix equality hook executed")

        def __len__(self):
            raise AssertionError("foreign prefix length hook executed")

    if fault in {"domain", "canonical", "batches"}:
        field = {"domain": "domain_bytes", "canonical": "canonical_bytes", "batches": "batch_bytes"}[fault]
        value = Foreign()
    elif fault == "batch_member":
        field, value = "batch_bytes", (Foreign(),)
    elif fault in {"oversized_domain", "oversized_canonical"}:
        field = "domain_bytes" if fault == "oversized_domain" else "canonical_bytes"
        value = b"x" * (MAX_BRS_PREFIX_BYTES + 1)
    elif fault == "oversized_batch_member":
        field, value = "batch_bytes", (b"x" * (MAX_BRS_PREFIX_BYTES + 1),)
    else:
        field, value = "batch_bytes", prefix.batch_bytes * 9
        batches += (batches[1],) * 8
    object.__setattr__(prefix, field, value)
    with pytest.raises(RSILearningError, match="append_invalid"):
        validate_brs_reserved_append(prefix, batches=batches)
