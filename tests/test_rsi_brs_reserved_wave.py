"""Reserved progress uses actual controller checkpoint/request/episode shapes."""

from __future__ import annotations

import hashlib
from copy import deepcopy
from dataclasses import FrozenInstanceError, replace

import pytest

from lunar_evolution import DeterministicCurriculum, RSILearningController, fixture_solver_gateway
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.rsi_brs_reserved_wave import (
    BRSReservedWaveError,
    project_reserved_brs_wave,
    select_reserved_brs_child,
)
from lunar_evolution.rsi_budget import RSIRunBudget
from lunar_evolution.rsi_controller import EpisodeExecution, PracticeEpisodeRunner
from lunar_evolution.rsi_gateway import LocalExactVerifier, SolverRequest, SolverResult
from lunar_evolution.rsi_learning import (
    PracticeEpisode,
    TraceEvent,
    VerifierCheck,
    VerifierDecision,
)
from lunar_evolution.rsi_python_brs_child_policy import MAX_BRS_CHILD_AGGREGATE_BYTES

HEX = "a" * 64
DEADLINE = 4_000_000_000.125


def _raw(value):
    return canonical_json(value, maximum=128 * 1024)


def _sha(value):
    return hashlib.sha256(_raw(value)).hexdigest()


def _fixture(count=2, outcomes=()):
    controller = RSILearningController(fixture_solver_gateway("mock"))
    run_id = "reserved-brs"
    pins = {"contract_sha256": HEX, "evaluator_sha256": HEX,
            "environment_sha256": HEX, "solver_id": "mock"}
    target = controller._target_episode(run_id, run_id + "-target", pins, 0)
    curriculum = DeterministicCurriculum()
    decisions = [curriculum.choose(target=target, diagnosis=f"gap-{i}", wave=3, ordinal=i)
                 for i in range(count)]
    plan = {"mode": "brs", "wave": 3, "max_workers": 1,
            "practices": [item.to_dict() for item in decisions]}
    budget = {"max_practice_rounds": count, "max_practice_episodes": count,
              "max_solver_invocations": count, "max_evaluator_invocations": count,
              "max_verifier_invocations": count, "deadline_unix": DEADLINE}
    original = controller._flow_state(None, run_id=run_id, plan=plan, pins=pins, budget=budget)
    for ordinal, decision in enumerate(decisions):
        key = f"{run_id}-practice-3-{ordinal}"
        episode = PracticeEpisode(
            key, run_id, HEX, HEX, HEX, controller.snapshot.digest(), "mock", "planned",
            wave=3, ordinal=ordinal, parent_target_episode_id=f"{run_id}-target-seed",
        )
        request = controller._request(
            episode, budget=original["budget_state"]["planned"],
            charter={**decision.to_dict(), "decision_sha256": decision.digest()},
        )
        controller._prepare_intent(None, original, episode, request)
    state = deepcopy(original)
    state["python_admission_refs"] = {}
    traces = {key: {"episode": None, "claim": None, "result": None,
                    "material_sha256s": [], "reference_sha256": None,
                    "obligation_sha256": None} for key in original["intents"]}
    prefix, materials = [], []
    for ordinal, outcome in enumerate(outcomes):
        key = f"{run_id}-practice-3-{ordinal}"
        intent = original["intents"][key]
        planned = PracticeEpisode.from_dict(intent["episode"])
        request = SolverRequest.from_dict(intent["request"])
        passed = outcome == "published"
        status, decision = ("completed", "pass") if passed else ("failed", "fail")
        verifier = VerifierDecision(
            key, decision, HEX, "inert verified observation", HEX,
            (VerifierCheck("official_evaluator", decision, HEX),),
        )
        result = SolverResult(
            key, request.digest(), status, HEX if passed else None, HEX if passed else None,
            HEX if passed else None, HEX, terminal_reason="" if passed else "inert-all-rejected",
        )
        episode = replace(
            planned, status=status, request_sha256=request.digest(), trace_digest=HEX,
            verifier=verifier if passed else None,
            candidate_receipt_sha256=result.candidate_receipt_sha256,
            execution_receipt_sha256=result.execution_receipt_sha256,
            official_evaluation_receipt_sha256=result.official_evaluation_receipt_sha256,
            terminal_reason=None if passed else result.terminal_reason,
        )
        execution = controller._serialize_execution(EpisodeExecution(episode, request, result, verifier))
        state["executions"][key] = execution
        reference = {"native_plan": {"request": request.to_dict(), "plan_sha256": HEX},
                     "prepared_journal": {"candidates": [{"candidate_id": f"candidate-{ordinal}"}]}}
        state["python_admission_refs"][key] = reference
        claim = {"episode_id": key, "request_sha256": request.digest(), "plan_sha256": HEX,
                 "status": status, "created_at": "2026-10-18T00:00:00Z"}
        claim["claim_sha256"] = _sha({
            "protocol": "lunar-rsi-native-episode-claim-v1", "episode_id": key,
            "request_sha256": request.digest(), "plan_sha256": HEX,
        })
        traces[key] = {"episode": episode.to_record_dict(), "claim": claim,
                       "result": result.to_dict(), "material_sha256s": [HEX],
                       "reference_sha256": _sha(reference), "obligation_sha256": None}
        prefix.append((key, outcome, _sha(execution)))
        materials.append((f"original-material-{ordinal}", 128))
    return original, state, {"attempt_traces": traces, "settled_prefix": tuple(prefix),
                             "retained_materials": tuple(materials), "candidate_count": len(outcomes)}


@pytest.mark.parametrize("outcomes", [(), ("published",), ("all_rejected",),
                                      ("published", "all_rejected"),
                                      ("all_rejected", "published")])
def test_original_reservation_is_separate_from_progress_and_never_recharged(outcomes):
    original, state, options = _fixture(3, outcomes)
    before = deepcopy((original, state, options))
    projection = project_reserved_brs_wave(original, state, **options)
    selected = select_reserved_brs_child(projection)
    assert projection.reservation_count == 3
    assert projection.completion_count == len(outcomes)
    assert selected.ordinal == len(outcomes)
    assert selected.budget_bytes == _raw(original["budget_state"])
    assert selected.deadline_unix == DEADLINE
    assert selected.request_bytes == _raw(original["intents"][selected.episode_id]["request"])
    assert selected.episode_bytes == _raw(original["intents"][selected.episode_id]["episode"])
    assert projection.original_state_sha256 == _sha(original)
    assert projection.episode_ids == tuple(original["intents"])
    assert projection.request_sha256s == tuple(_sha(item["request"]) for item in original["intents"].values())
    expected_published = next((item for item in reversed(options["settled_prefix"]) if item[1] == "published"), None)
    assert projection.latest_published_predecessor == expected_published
    assert (original, state, options) == before
    assert project_reserved_brs_wave(original, state, **options) == projection


@pytest.mark.parametrize("outcomes", [("published", "published"), ("published", "all_rejected"),
                                      ("all_rejected", "published"), ("all_rejected", "all_rejected")])
def test_complete_outcome_pairs_select_no_fresh_child(outcomes):
    original, state, options = _fixture(2, outcomes)
    projection = project_reserved_brs_wave(original, state, **options)
    assert select_reserved_brs_child(projection) is None
    assert projection.completion_count == projection.reservation_count == 2
    assert state["budget_state"] == original["budget_state"]


@pytest.mark.parametrize("decision", ["pass", "fail", "unresolved"])
def test_actual_published_runner_outcomes_remain_settled_without_memory_promotion_or_replay(decision):
    original, state, options = _fixture(2, ("published",))
    key = options["settled_prefix"][0][0]
    planned = PracticeEpisode.from_dict(original["intents"][key]["episode"])
    request = SolverRequest.from_dict(original["intents"][key]["request"])
    result = SolverResult.from_dict(state["executions"][key]["result"])

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
            return VerifierDecision(key, decision, HEX, "independent observation", HEX,
                                    (VerifierCheck("diagnosis", decision, HEX),))

    gateway = InertGateway()
    execution = PracticeEpisodeRunner(gateway, IndependentVerifier()).run(planned, request)
    assert execution.episode.verifier.outcome == decision
    assert execution.passed is (decision == "pass")
    wire = RSILearningController._serialize_execution(execution)
    state["executions"][key] = wire
    options["attempt_traces"][key]["episode"] = wire["episode"]
    options["attempt_traces"][key]["result"] = wire["result"]
    options["settled_prefix"] = ((key, "published", _sha(wire)),)
    saved = deepcopy((original, state, options))
    for _ in range(2):
        projection = project_reserved_brs_wave(original, state, **options)
        assert projection.completion_count == 1
        assert select_reserved_brs_child(projection).ordinal == 1
        assert projection.latest_published_predecessor == options["settled_prefix"][0]
    assert gateway.calls == 1
    assert state["memory_snapshot"] == state["root_snapshot"] == original["root_snapshot"]
    assert (original, state, options) == saved


@pytest.mark.parametrize("field", ["candidate_receipt_sha256", "execution_receipt_sha256",
                                   "official_evaluation_receipt_sha256", "trace_digest",
                                   "candidate_source_sha256", "dependency_sha256", "trace_events",
                                   "actor_fingerprint", "missing_episode_verifier"])
def test_matching_external_digest_cannot_hide_episode_result_evidence_or_attachment_mismatch(field):
    original, state, options = _fixture(2, ("published",))
    key = options["settled_prefix"][0][0]
    execution = state["executions"][key]
    if field == "missing_episode_verifier":
        episode = PracticeEpisode.from_dict(execution["episode"])
        execution["episode"] = replace(episode, verifier=None).to_record_dict()
    else:
        result = SolverResult.from_dict(execution["result"])
        changed = (TraceEvent(0, "observation", "foreign", "b" * 64),) if field == "trace_events" else "b" * 64
        execution["result"] = replace(result, **{field: changed}).to_dict()
    options["attempt_traces"][key]["episode"] = execution["episode"]
    options["attempt_traces"][key]["result"] = execution["result"]
    options["settled_prefix"] = ((key, "published", _sha(execution)),)
    with pytest.raises(BRSReservedWaveError, match="execution_identity_invalid"):
        project_reserved_brs_wave(original, state, **options)


def test_eight_exact_reserved_attempts_allow_untouched_suffix_and_no_ninth():
    original, state, options = _fixture(8, ("published", "all_rejected") * 3)
    projection = project_reserved_brs_wave(original, state, **options)
    assert projection.reservation_count == 8
    assert select_reserved_brs_child(projection).ordinal == 6
    original["plan"]["practices"].append(deepcopy(original["plan"]["practices"][0]))
    state["plan"] = deepcopy(original["plan"])
    with pytest.raises(BRSReservedWaveError, match="plan_invalid"):
        project_reserved_brs_wave(original, state, **options)


@pytest.mark.parametrize("trace_field", ["episode", "claim", "result", "material_sha256s",
                                        "reference_sha256", "obligation_sha256"])
def test_any_suffix_attempt_trace_blocks_even_without_a_root_fence(trace_field):
    original, state, options = _fixture(3, ("published",))
    key = list(original["intents"])[2]
    options["attempt_traces"][key][trace_field] = (
        [HEX] if trace_field == "material_sha256s" else
        {"status": "started"} if trace_field in {"episode", "claim", "result"} else HEX
    )
    assert not state.get("brs_reconcile_obligations")
    with pytest.raises(BRSReservedWaveError, match="attempt_requires_reconcile"):
        project_reserved_brs_wave(original, state, **options)


@pytest.mark.parametrize("change", ["missing_trace", "foreign_trace", "boolean_trace", "hole", "reordered_prefix",
                                    "unknown_outcome", "execution_digest", "extra_fence"])
def test_incomplete_domain_or_prefix_and_unknown_are_refused(change):
    original, state, options = _fixture(3, ("published", "all_rejected"))
    keys = list(original["intents"])
    if change == "missing_trace":
        options["attempt_traces"].pop(keys[-1])
    elif change == "foreign_trace":
        options["attempt_traces"]["foreign"] = deepcopy(options["attempt_traces"][keys[-1]])
    elif change == "boolean_trace":
        options["attempt_traces"][keys[-1]] = True
    elif change == "hole":
        state["executions"].pop(keys[0])
    elif change == "reordered_prefix":
        options["settled_prefix"] = tuple(reversed(options["settled_prefix"]))
    elif change == "unknown_outcome":
        options["settled_prefix"] = ((keys[0], "unknown", HEX),)
    elif change == "execution_digest":
        options["settled_prefix"] = ((keys[0], "published", HEX), options["settled_prefix"][1])
    elif change == "extra_fence":
        state["brs_reconcile_obligations"] = {keys[-1]: {"phase": "selected"}}
    with pytest.raises(BRSReservedWaveError):
        project_reserved_brs_wave(original, state, **options)


@pytest.mark.parametrize("field", ["plan", "pins", "root_snapshot", "intents", "budget_state",
                                   "producer_checkpoint_binding", "producer_brs_checkpoint_policy"])
def test_original_identity_and_whole_budget_drift_refuse(field):
    original, state, options = _fixture()
    if field in {"producer_checkpoint_binding", "producer_brs_checkpoint_policy"}:
        state[field] = {"changed": True}
    elif field == "budget_state":
        state[field]["planned"]["deadline_unix"] += 60
    else:
        state[field]["changed"] = True
    with pytest.raises(BRSReservedWaveError, match="original_drift"):
        project_reserved_brs_wave(original, state, **options)


@pytest.mark.parametrize("counter", ["practice_rounds", "practice_episodes", "solver_invocations",
                                     "evaluator_invocations", "verifier_invocations"])
def test_incomplete_original_reservation_cannot_be_repaired_by_selection(counter):
    original, state, options = _fixture()
    for checkpoint in (original, state):
        checkpoint["budget_state"]["consumed"][counter] -= 1
        checkpoint["budget_state"]["remaining"][counter] += 1
    with pytest.raises(BRSReservedWaveError, match="reservation_invalid"):
        project_reserved_brs_wave(original, state, **options)


@pytest.mark.parametrize("field", ["run_id", "ordinal", "wave", "memory_snapshot_sha256", "contract_sha256"])
def test_mutually_matching_external_digest_cannot_hide_wrong_execution_identity(field):
    original, state, options = _fixture(2, ("published",))
    key = options["settled_prefix"][0][0]
    raw_episode = state["executions"][key]["episode"]
    episode = PracticeEpisode.from_dict(raw_episode)
    changed = {field: 7 if field in {"ordinal", "wave"} else "foreign" if field == "run_id" else "b" * 64}
    changed_episode = replace(episode, **changed).to_record_dict()
    state["executions"][key]["episode"] = changed_episode
    options["attempt_traces"][key]["episode"] = changed_episode
    options["settled_prefix"] = ((key, "published", _sha(state["executions"][key])),)
    with pytest.raises(BRSReservedWaveError, match="execution_identity_invalid"):
        project_reserved_brs_wave(original, state, **options)


@pytest.mark.parametrize("what", ["claim", "reference", "result", "obligation"])
def test_settled_claim_result_reference_and_obligation_must_match(what):
    original, state, options = _fixture(2, ("all_rejected",))
    key = options["settled_prefix"][0][0]
    trace = options["attempt_traces"][key]
    if what == "claim":
        trace["claim"]["status"] = "started"
    elif what == "reference":
        trace["reference_sha256"] = "b" * 64
    elif what == "result":
        trace["result"]["terminal_reason"] = "changed"
    else:
        trace["obligation_sha256"] = HEX
    with pytest.raises(BRSReservedWaveError):
        project_reserved_brs_wave(original, state, **options)


def test_retained_files_with_equal_digests_still_charge_separate_sizes():
    original, state, options = _fixture(2, ("all_rejected",))
    options["retained_materials"] = (("first-pin", MAX_BRS_CHILD_AGGREGATE_BYTES // 2),
                                      ("second-pin", MAX_BRS_CHILD_AGGREGATE_BYTES // 2))
    result = project_reserved_brs_wave(original, state, **options)
    assert result.aggregate_bytes == MAX_BRS_CHILD_AGGREGATE_BYTES
    options["retained_materials"] += (("third-pin", 1),)
    with pytest.raises(BRSReservedWaveError, match="aggregate_exceeded"):
        project_reserved_brs_wave(original, state, **options)


@pytest.mark.parametrize("what", ["candidates", "candidate_mismatch", "duplicate_material", "negative_size",
                                  "checkpoint_bytes", "depth"])
def test_capacity_and_shape_boundaries_refuse(what):
    original, state, options = _fixture(2, ("published",))
    if what == "candidates":
        options["candidate_count"] = 33
    elif what == "candidate_mismatch":
        options["candidate_count"] = 0
    elif what == "duplicate_material":
        options["retained_materials"] *= 2
    elif what == "negative_size":
        options["retained_materials"] = (("bad-pin", -1),)
    elif what == "checkpoint_bytes":
        state["oversized"] = "x" * (128 * 1024)
    else:
        nested = None
        for _ in range(34):
            nested = [nested]
        state["deep"] = nested
    with pytest.raises(BRSReservedWaveError):
        project_reserved_brs_wave(original, state, **options)


def test_observers_cannot_execute_subclass_or_object_hooks():
    original, state, options = _fixture()
    calls = []

    class Trap(dict):
        def items(self):
            calls.append("items")
            raise AssertionError("must not invoke supplied mapping hook")

        def __iter__(self):
            calls.append("iter")
            raise AssertionError("must not invoke supplied mapping hook")

        def __deepcopy__(self, memo):
            calls.append("deepcopy")
            raise AssertionError("must not copy a supplied subclass")

    state["pins"] = Trap(state["pins"])
    with pytest.raises(BRSReservedWaveError, match="shape_invalid"):
        project_reserved_brs_wave(original, state, **options)
    with pytest.raises(BRSReservedWaveError):
        project_reserved_brs_wave(Trap(original), original, **options)
    assert calls == []


def test_projection_reads_no_clock_and_calls_no_reservation_claim_or_io(monkeypatch):
    original, state, options = _fixture()

    def trap(*args, **kwargs):
        pytest.fail("pure projection attempted a side effect")

    monkeypatch.setattr(RSIRunBudget, "reserve_launch_with_stages", trap)
    monkeypatch.setattr("lunar_evolution.rsi_store.RSILedger.claim_native_episode", trap)
    monkeypatch.setattr("lunar_evolution.rsi_python_brs_successor.advance_brs_ordinal", trap)
    monkeypatch.setattr("lunar_evolution.rsi_python_brs_successor.dispatch_brs_successor", trap)
    monkeypatch.setattr("time.time", trap)
    monkeypatch.setattr("builtins.open", trap)
    projection = project_reserved_brs_wave(original, state, **options)
    assert select_reserved_brs_child(projection).deadline_unix == DEADLINE
    with pytest.raises(FrozenInstanceError):
        projection.wave = 9
    original["plan"]["wave"] = 9
    assert select_reserved_brs_child(projection).wave == 3


def test_old_absolute_deadline_is_preserved_without_a_now_based_refresh():
    original, state, options = _fixture()
    for checkpoint in (original, state):
        checkpoint["budget_state"]["planned"]["deadline_unix"] = 1.125
        for intent in checkpoint["intents"].values():
            intent["request"]["budget"]["deadline_unix"] = 1.125
    projection = project_reserved_brs_wave(original, state, **options)
    assert projection.deadline_unix == select_reserved_brs_child(projection).deadline_unix == 1.125
    # Descriptive selection does not grant permission to run after expiry. The
    # controller must apply its original live deadline/control gate before launch.


@pytest.mark.parametrize("field", ["aggregate_bytes", "candidate_count", "retained_materials",
                                   "intents", "settled_prefix", "budget_bytes", "deadline_unix"])
def test_selection_revalidates_mutated_projection_fields(field):
    original, state, options = _fixture()
    projection = project_reserved_brs_wave(original, state, **options)
    changes = {
        "aggregate_bytes": 1,
        "candidate_count": True,
        "retained_materials": (("duplicate", 1), ("duplicate", 1)),
        "intents": tuple(reversed(projection.intents)),
        "settled_prefix": (("foreign", "published", HEX),),
        "budget_bytes": projection.budget_bytes + b" ",
        "deadline_unix": DEADLINE + 1,
    }
    object.__setattr__(projection, field, changes[field])
    with pytest.raises(BRSReservedWaveError):
        select_reserved_brs_child(projection)


@pytest.mark.parametrize("field", ["budget_bytes", "episode_bytes", "request_bytes"])
def test_selection_caps_mutated_dto_bytes_before_decoding_them(field, monkeypatch):
    import lunar_evolution.rsi_brs_reserved_wave as module

    original, state, options = _fixture()
    projection = project_reserved_brs_wave(original, state, **options)
    oversized = b'{"padding":"' + b'x' * (128 * 1024) + b'"}'
    if field == "budget_bytes":
        object.__setattr__(projection, field, oversized)
    else:
        changed = list(projection.intents)
        key, episode, request = changed[0]
        changed[0] = (key, oversized if field == "episode_bytes" else episode,
                      oversized if field == "request_bytes" else request)
        object.__setattr__(projection, "intents", tuple(changed))
    decoder = module.json.loads

    def bounded_decoder(raw, *args, **kwargs):
        assert len(raw) <= 128 * 1024, "oversized DTO bytes reached the decoder"
        return decoder(raw, *args, **kwargs)

    monkeypatch.setattr(module.json, "loads", bounded_decoder)
    with pytest.raises(BRSReservedWaveError, match="projection_invalid"):
        select_reserved_brs_child(projection)


@pytest.mark.parametrize("field", ["ordinal", "run_id", "wave", "memory_snapshot_sha256", "solver_id"])
def test_original_matching_current_is_insufficient_if_intent_body_is_wrong(field):
    original, state, options = _fixture()
    key = next(iter(original["intents"]))
    planned = PracticeEpisode.from_dict(original["intents"][key]["episode"])
    changed = 7 if field in {"ordinal", "wave"} else "foreign" if field in {"run_id", "solver_id"} else "b" * 64
    wrong = replace(planned, **{field: changed}).to_record_dict()
    original["intents"][key]["episode"] = wrong
    state["intents"][key]["episode"] = deepcopy(wrong)
    with pytest.raises(BRSReservedWaveError, match="intent_identity_invalid"):
        project_reserved_brs_wave(original, state, **options)


@pytest.mark.parametrize("where", ["original", "state"])
def test_boolean_empty_fence_cannot_masquerade_as_empty_obligation_map(where):
    original, state, options = _fixture()
    (original if where == "original" else state)["brs_reconcile_obligations"] = False
    with pytest.raises(BRSReservedWaveError):
        project_reserved_brs_wave(original, state, **options)


def test_projection_byte_ceiling_is_stricter_than_checkpoint_record_limit():
    original, state, options = _fixture(8)
    for checkpoint in (original, state):
        for intent in checkpoint["intents"].values():
            intent["request"]["solver_settings"]["retained-original-setting"] = "x" * 12000
    assert len(_raw(original)) < 128 * 1024
    assert len(_raw(state)) < 128 * 1024
    with pytest.raises(BRSReservedWaveError, match="bytes_exceeded"):
        project_reserved_brs_wave(original, state, **options)


def test_candidate_boundary_uses_actual_retained_reference_inventory():
    original, state, options = _fixture(2, ("published",))
    key = options["settled_prefix"][0][0]
    reference = state["python_admission_refs"][key]
    reference["prepared_journal"]["candidates"] = [{"candidate_id": f"c-{i}"} for i in range(32)]
    options["attempt_traces"][key]["reference_sha256"] = _sha(reference)
    options["candidate_count"] = 32
    assert project_reserved_brs_wave(original, state, **options).candidate_count == 32
    reference["prepared_journal"]["candidates"].append({"candidate_id": "c-32"})
    options["attempt_traces"][key]["reference_sha256"] = _sha(reference)
    options["candidate_count"] = 33
    with pytest.raises(BRSReservedWaveError, match="capacity_invalid"):
        project_reserved_brs_wave(original, state, **options)


@pytest.mark.parametrize("change", ["missing_intent", "request_root", "charter", "request_budget", "foreign_pins"])
def test_identical_original_current_still_requires_valid_original_request_association(change):
    original, state, options = _fixture()
    for checkpoint in (original, state):
        key = next(iter(checkpoint["intents"]))
        if change == "missing_intent":
            checkpoint["intents"].pop(key)
        else:
            request = checkpoint["intents"][key]["request"]
            if change == "request_root":
                request["memory_snapshot_sha256"] = "b" * 64
            elif change == "charter":
                request["practice_charter"]["decision_sha256"] = "b" * 64
            elif change == "request_budget":
                request["budget"]["deadline_unix"] += 60
            else:
                request["contract_sha256"] = "b" * 64
    with pytest.raises(BRSReservedWaveError):
        project_reserved_brs_wave(original, state, **options)


@pytest.mark.parametrize("status", ["unknown", "cancelled", "failed", "budget_exhausted"])
def test_non_running_root_never_yields_a_suffix_selection(status):
    original, state, options = _fixture()
    state["status"] = status
    with pytest.raises(BRSReservedWaveError, match="control_invalid"):
        project_reserved_brs_wave(original, state, **options)
