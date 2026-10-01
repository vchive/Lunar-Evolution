"""Crash/reconcile integration for DRS/BRS control-plane callbacks, using local fixtures."""

from __future__ import annotations

import hashlib
from collections import Counter
from copy import deepcopy
from threading import Lock

import pytest

from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.rsi_controller import DeterministicCurriculum, RSILearningController
from lunar_evolution.rsi_gateway import DeterministicMockSolver, LocalExactVerifier
from lunar_evolution.rsi_learning import RSILearningError
from lunar_evolution.rsi_store import RSILedger

HEX = "a" * 64
PINS = {"contract_sha256": HEX, "evaluator_sha256": HEX,
        "environment_sha256": HEX, "solver_id": "mock"}
RUN = "callback-run"


class CallbackCrash(RuntimeError):
    pass


class Gateway:
    def __init__(self):
        self.calls = []
        self.lock = Lock()

    def rsi_fingerprint_config(self):
        return {"fixture": "callback-gateway-v1"}

    def run(self, request):
        with self.lock:
            self.calls.append(request.episode_id)
        return DeterministicMockSolver().run(request)


class Verifier(LocalExactVerifier):
    def __init__(self, crash=False):
        self.crash = crash
        self.calls = []
        self.outputs = {}
        self.version = 1

    def rsi_fingerprint_config(self):
        return {"fixture": "callback-verifier", "version": self.version}

    def verify(self, episode, request, result):
        self.calls.append(episode.episode_id)
        answer = super().verify(episode, request, result)
        self.outputs[episode.episode_id] = answer.to_dict()
        if self.crash:
            raise CallbackCrash("verifier_response_lost")
        return answer


class Judge:
    def __init__(self, crash=False):
        self.crash = crash
        self.calls = []
        self.outputs = {}
        self.version = 1

    def rsi_fingerprint_config(self):
        return {"fixture": "callback-judge", "minimum_wave": 1, "version": self.version}

    def __call__(self, execution):
        episode = execution.episode
        self.calls.append(episode.episode_id)
        answer = {"accepted": bool(execution.passed and episode.wave >= 1),
                  "diagnosis": "practice the original target gap"}
        self.outputs[episode.episode_id] = answer
        if self.crash:
            raise CallbackCrash("judge_response_lost")
        return answer["accepted"], answer["diagnosis"]


class Curriculum(DeterministicCurriculum):
    def __init__(self, crash=False):
        super().__init__()
        self.crash = crash
        self.calls = []
        self.outputs = {}
        self.version = 1

    def rsi_fingerprint_config(self):
        return {"fixture": "callback-curriculum", "version": self.version}

    def choose(self, *, target, diagnosis, wave, ordinal):
        key = f"{target.run_id}-practice-{wave}-{ordinal}"
        self.calls.append(key)
        answer = super().choose(target=target, diagnosis=diagnosis, wave=wave, ordinal=ordinal)
        self.outputs[key] = answer.to_dict()
        if self.crash:
            raise CallbackCrash("curriculum_response_lost")
        return answer


def _fixture(tmp_path, stage=None):
    ledger = RSILedger(tmp_path / "callbacks.sqlite")
    gateway = Gateway()
    verifier = Verifier(stage == "verifier")
    judge = Judge(stage == "judge")
    curriculum = Curriculum(stage == "curriculum")
    components = gateway, verifier, judge, curriculum
    return _controller(ledger, components), ledger, components


def _controller(ledger, components):
    gateway, verifier, judge, curriculum = components
    return RSILearningController(gateway, verifier=verifier, target_judge=judge,
                                 curriculum=curriculum, ledger=ledger)


def _run(learner, *, budget=None):
    return learner.run_drs(run_id=RUN, **PINS, max_practice_rounds=1,
                           max_target_attempts=2, budget=budget)


def _counts(components):
    return tuple(Counter(component.calls) for component in components)


def _digest(value):
    return hashlib.sha256(canonical_json(value, maximum=128 * 1024)).hexdigest()


def _callback_id(stage):
    key = f"{RUN}-practice-0-0" if stage == "curriculum" else f"{RUN}-target-0"
    return f"{stage}:{key}", key


def _result(components, stage):
    component = components[{"verifier": 1, "judge": 2, "curriculum": 3}[stage]]
    return deepcopy(component.outputs[_callback_id(stage)[1]])


def _reconciliation(learner, stage, result):
    callback_id, _ = _callback_id(stage)
    head, state = learner.callback_checkpoint(RUN, callback_id)
    evidence = {
        "source": "local-fixture-result-retained-after-response-loss",
        "binding_sha256": _digest(state["binding"]),
        "result_sha256": _digest(result),
        "receipt_sha256": _digest({"local-retained-result": result}),
    }
    return {"run_id": RUN, "callback_id": callback_id,
            "expected_checkpoint_sha256": head, "result": result, "evidence": evidence}


def _crash(learner):
    with pytest.raises(CallbackCrash, match="response_lost"):
        _run(learner)


@pytest.mark.parametrize("stage", ["verifier", "judge", "curriculum"])
def test_ambiguous_callback_never_reexecutes_and_explicit_result_resumes(tmp_path, stage):
    learner, ledger, components = _fixture(tmp_path, stage)
    _crash(learner)
    before = _counts(components)
    restarted = _controller(RSILedger(ledger.database), components)

    with pytest.raises(RSILearningError, match="callback.*reconcile_required"):
        restarted.resume(RUN)
    assert _counts(components) == before
    kwargs = _reconciliation(restarted, stage, _result(components, stage))
    first = restarted.reconcile_callback(**kwargs)
    reconciled = restarted.callback_checkpoint(RUN, kwargs["callback_id"])
    history = ledger.controller_checkpoint_history(RUN)
    assert history[-1][1]["budget_state"]["consumed"]["unknown_retries"] == 1
    assert restarted.reconcile_callback(**kwargs) == first
    assert restarted.callback_checkpoint(RUN, kwargs["callback_id"]) == reconciled
    assert ledger.controller_checkpoint_history(RUN) == history
    assert _counts(components) == before

    for component in components[1:]:
        component.crash = False
    result = _controller(RSILedger(ledger.database), components).resume(RUN)
    assert result.status == "completed"
    assert len(result.memory_snapshot.items) == 1
    assert all(count == 1 for component in components for count in Counter(component.calls).values())
    assert ledger.get_run(RUN).payload["budget_state"]["consumed"]["unknown_retries"] == 1
    terminal_history = ledger.controller_checkpoint_history(RUN)
    terminal_calls = _counts(components)
    assert _controller(RSILedger(ledger.database), components).reconcile_callback(**kwargs) == first
    assert ledger.controller_checkpoint_history(RUN) == terminal_history
    assert _counts(components) == terminal_calls


@pytest.mark.parametrize("stage,mutation", [
    ("verifier", {"episode_id": "unrelated-episode"}),
    ("verifier", {"contract_sha256": "b" * 64}),
    ("verifier", {"official_evaluation_receipt_sha256": "b" * 64}),
    ("verifier", {"independent_of_actor": False}),
    ("judge", {"accepted": "yes"}),
    ("judge", {"diagnosis": ""}),
    ("judge", {"extra": True}),
    ("curriculum", {"compatible_solvers": ["unrelated-solver"]}),
    ("curriculum", {"strategy": ""}),
])
def test_invalid_callback_result_is_rejected_before_budget_or_journal_write(tmp_path, stage, mutation):
    learner, ledger, components = _fixture(tmp_path, stage)
    _crash(learner)
    result = _result(components, stage) | mutation
    kwargs = _reconciliation(learner, stage, result)
    before = learner.callback_checkpoint(RUN, kwargs["callback_id"])
    history = ledger.controller_checkpoint_history(RUN)
    calls = _counts(components)

    with pytest.raises(RSILearningError):
        learner.reconcile_callback(**kwargs)
    assert learner.callback_checkpoint(RUN, kwargs["callback_id"]) == before
    assert ledger.controller_checkpoint_history(RUN) == history
    assert _counts(components) == calls


@pytest.mark.parametrize("field,value", [
    ("source", ""), ("binding_sha256", "b" * 64),
    ("result_sha256", "b" * 64), ("receipt_sha256", "invalid"),
])
def test_callback_evidence_must_bind_exact_input_and_result(tmp_path, field, value):
    learner, ledger, components = _fixture(tmp_path, "judge")
    _crash(learner)
    kwargs = _reconciliation(learner, "judge", _result(components, "judge"))
    kwargs["evidence"][field] = value
    before = learner.callback_checkpoint(RUN, kwargs["callback_id"])
    history = ledger.controller_checkpoint_history(RUN)
    with pytest.raises(RSILearningError):
        learner.reconcile_callback(**kwargs)
    assert learner.callback_checkpoint(RUN, kwargs["callback_id"]) == before
    assert ledger.controller_checkpoint_history(RUN) == history


@pytest.mark.parametrize("stage", ["verifier", "judge", "curriculum"])
def test_callback_component_drift_rejected_before_reconciliation(tmp_path, stage):
    learner, ledger, components = _fixture(tmp_path, stage)
    _crash(learner)
    kwargs = _reconciliation(learner, stage, _result(components, stage))
    history = ledger.controller_checkpoint_history(RUN)
    component = components[{"verifier": 1, "judge": 2, "curriculum": 3}[stage]]
    component.version += 1
    with pytest.raises(RSILearningError, match="drift|fingerprint"):
        _controller(RSILedger(ledger.database), components).reconcile_callback(**kwargs)
    assert ledger.controller_checkpoint_history(RUN) == history


def test_zero_unknown_budget_rejects_callback_reconcile_without_writes(tmp_path):
    learner, ledger, components = _fixture(tmp_path, "judge")
    with pytest.raises(CallbackCrash):
        _run(learner, budget={"max_unknown_retries": 0})
    kwargs = _reconciliation(learner, "judge", _result(components, "judge"))
    before = learner.callback_checkpoint(RUN, kwargs["callback_id"])
    history = ledger.controller_checkpoint_history(RUN)
    calls = _counts(components)
    with pytest.raises(RSILearningError, match="budget"):
        learner.reconcile_callback(**kwargs)
    assert learner.callback_checkpoint(RUN, kwargs["callback_id"]) == before
    assert ledger.controller_checkpoint_history(RUN) == history
    assert _counts(components) == calls


def test_stale_callback_checkpoint_rejected_without_writes(tmp_path):
    learner, ledger, components = _fixture(tmp_path, "judge")
    _crash(learner)
    kwargs = _reconciliation(learner, "judge", _result(components, "judge"))
    kwargs["expected_checkpoint_sha256"] = "b" * 64
    history = ledger.controller_checkpoint_history(RUN)
    with pytest.raises(RSILearningError):
        learner.reconcile_callback(**kwargs)
    assert ledger.controller_checkpoint_history(RUN) == history


@pytest.mark.parametrize("stage", ["judge", "curriculum"])
def test_persisted_callback_result_replays_after_flow_checkpoint_crash(tmp_path, monkeypatch, stage):
    learner, ledger, components = _fixture(tmp_path)
    save = learner._save_flow

    def crash_after_decision(record, state):
        collection = "judgments" if stage == "judge" else "decisions"
        if _callback_id(stage)[1] in state[collection]:
            raise CallbackCrash("before_flow_checkpoint")
        return save(record, state)

    with monkeypatch.context() as patch:
        patch.setattr(learner, "_save_flow", crash_after_decision)
        with pytest.raises(CallbackCrash, match="before_flow_checkpoint"):
            _run(learner)
    result = _controller(RSILedger(ledger.database), components).resume(RUN)
    assert result.status == "completed"
    assert all(count == 1 for component in components for count in Counter(component.calls).values())
    assert ledger.get_run(RUN).payload["budget_state"]["consumed"]["unknown_retries"] == 0


def test_persisted_verifier_result_replays_before_episode_verdict_append(tmp_path, monkeypatch):
    learner, ledger, components = _fixture(tmp_path)
    append = ledger.append_episode_record

    def crash_before_verdict(episode, **kwargs):
        if episode.verifier is not None:
            raise CallbackCrash("before_episode_verdict")
        return append(episode, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(ledger, "append_episode_record", crash_before_verdict)
        with pytest.raises(CallbackCrash, match="before_episode_verdict"):
            _run(learner)
    result = _controller(RSILedger(ledger.database), components).resume(RUN)
    assert result.status == "completed"
    assert all(count == 1 for component in components for count in Counter(component.calls).values())


def test_brs_unknown_callback_blocks_recovery_of_other_unverified_children(tmp_path, monkeypatch):
    learner, ledger, components = _fixture(tmp_path, "verifier")
    target = learner._target_episode(RUN, f"{RUN}-target-seed", PINS, 0)
    practices = [DeterministicCurriculum().choose(target=target, diagnosis=f"gap-{i}", wave=0, ordinal=i)
                 for i in range(2)]
    save_result = ledger.save_episode_result

    def crash_other_child_after_result(request, result):
        save_result(request, result)
        if request.episode_id.endswith("-1"):
            raise CallbackCrash("second_solver_result_persisted")

    with monkeypatch.context() as patch:
        patch.setattr(ledger, "save_episode_result", crash_other_child_after_result)
        with pytest.raises(CallbackCrash):
            learner.run_brs(run_id=RUN, **PINS, practices=practices, max_workers=2)
    calls = _counts(components)
    assert calls[0] == Counter({f"{RUN}-practice-0-0": 1, f"{RUN}-practice-0-1": 1})
    assert calls[1] == Counter({f"{RUN}-practice-0-0": 1})
    second_before = ledger.get_episode(f"{RUN}-practice-0-1")
    for component in components[1:]:
        component.crash = False

    with pytest.raises(RSILearningError, match="callback.*reconcile_required"):
        _controller(RSILedger(ledger.database), components).resume(RUN)
    assert _counts(components) == calls
    assert ledger.get_episode(f"{RUN}-practice-0-1") == second_before
    assert learner.snapshot.items == ()


def test_callback_reconciliation_obeys_the_run_controller_lock(tmp_path):
    learner, ledger, components = _fixture(tmp_path, "judge")
    _crash(learner)
    kwargs = _reconciliation(learner, "judge", _result(components, "judge"))
    history = ledger.controller_checkpoint_history(RUN)
    checkpoint = learner.callback_checkpoint(RUN, kwargs["callback_id"])
    with ledger.controller_lock(RUN), pytest.raises(RSILearningError, match="controller_busy"):
        _controller(RSILedger(ledger.database), components).reconcile_callback(**kwargs)
    assert ledger.controller_checkpoint_history(RUN) == history
    assert learner.callback_checkpoint(RUN, kwargs["callback_id"]) == checkpoint


@pytest.mark.parametrize("terminal", ["completed", "failed", "cancelled", "budget_exhausted"])
def test_terminal_run_rejects_a_new_callback_reconciliation(tmp_path, terminal):
    learner, ledger, components = _fixture(tmp_path, "judge")
    _crash(learner)
    kwargs = _reconciliation(learner, "judge", _result(components, "judge"))
    head = ledger.get_run(RUN)
    ledger.transition(RUN, state=terminal, expected_record_sha256=head.record_sha256)
    history = ledger.controller_checkpoint_history(RUN)
    checkpoint = learner.callback_checkpoint(RUN, kwargs["callback_id"])
    with pytest.raises(RSILearningError, match="terminal_run"):
        learner.reconcile_callback(**kwargs)
    assert ledger.controller_checkpoint_history(RUN) == history
    assert learner.callback_checkpoint(RUN, kwargs["callback_id"]) == checkpoint


def test_result_evidence_can_be_recorded_after_deadline_without_launching_new_work(tmp_path, monkeypatch):
    learner, ledger, components = _fixture(tmp_path, "judge")
    clock = [100.0]
    monkeypatch.setattr("lunar_evolution.rsi_budget.time.time", lambda: clock[0])
    with pytest.raises(CallbackCrash):
        _run(learner, budget={"deadline_unix": 102.0, "max_unknown_retries": 1})
    kwargs = _reconciliation(learner, "judge", _result(components, "judge"))
    calls = _counts(components)
    clock[0] = 200.0
    learner.reconcile_callback(**kwargs)
    assert learner.callback_checkpoint(RUN, kwargs["callback_id"])[1]["status"] == "completed"
    result = _controller(RSILedger(ledger.database), components).resume(RUN)
    assert result.status == "budget_exhausted"
    assert _counts(components) == calls
    assert ledger.get_run(RUN).payload["budget_state"]["planned"]["deadline_unix"] == 102.0
    assert ledger.get_run(RUN).payload["budget_state"]["consumed"]["unknown_retries"] == 1


@pytest.mark.parametrize("crash_point", ["reservation", "callback_result"])
def test_reconciliation_crash_reuses_reservation_and_original_result(tmp_path, monkeypatch, crash_point):
    learner, ledger, components = _fixture(tmp_path, "judge")
    with pytest.raises(CallbackCrash):
        _run(learner, budget={"max_unknown_retries": 1})
    kwargs = _reconciliation(learner, "judge", _result(components, "judge"))
    save_flow = learner._save_flow
    save_checkpoint = ledger.write_controller_checkpoint

    def crash_after_reservation(record, state):
        save_flow(record, state)
        if kwargs["callback_id"] in state.get("callback_reconciliation_reservations", {}):
            raise CallbackCrash("reconciliation_reservation_persisted")

    def crash_after_callback_result(scope_id, state, **arguments):
        digest = save_checkpoint(scope_id, state, **arguments)
        if state.get("kind") == "durable_callback" and state.get("reconciliation"):
            raise CallbackCrash("reconciliation_result_persisted")
        return digest

    with monkeypatch.context() as patch:
        if crash_point == "reservation":
            patch.setattr(learner, "_save_flow", crash_after_reservation)
        else:
            patch.setattr(ledger, "write_controller_checkpoint", crash_after_callback_result)
        with pytest.raises(CallbackCrash, match="reconciliation_.*_persisted"):
            learner.reconcile_callback(**kwargs)
    calls = _counts(components)
    assert ledger.controller_checkpoint(RUN)[1]["budget_state"]["consumed"]["unknown_retries"] == 1
    restarted = _controller(RSILedger(ledger.database), components)
    assert restarted.reconcile_callback(**kwargs) == kwargs["result"]
    assert _counts(components) == calls
    assert ledger.controller_checkpoint(RUN)[1]["budget_state"]["consumed"]["unknown_retries"] == 1
    for component in components[1:]:
        component.crash = False
    assert restarted.resume(RUN).status == "completed"
    assert all(count == 1 for component in components for count in Counter(component.calls).values())
    assert ledger.get_run(RUN).payload["budget_state"]["consumed"]["unknown_retries"] == 1


def test_changed_result_after_reservation_crash_cannot_reuse_reserved_budget(tmp_path, monkeypatch):
    learner, ledger, components = _fixture(tmp_path, "judge")
    _crash(learner)
    kwargs = _reconciliation(learner, "judge", _result(components, "judge"))
    save_flow = learner._save_flow

    def crash_after_reservation(record, state):
        save_flow(record, state)
        raise CallbackCrash("reservation_persisted")

    with monkeypatch.context() as patch:
        patch.setattr(learner, "_save_flow", crash_after_reservation)
        with pytest.raises(CallbackCrash):
            learner.reconcile_callback(**kwargs)
    history = ledger.controller_checkpoint_history(RUN)
    changed = kwargs["result"] | {"diagnosis": "different local evidence"}
    conflicting = _reconciliation(learner, "judge", changed)
    with pytest.raises(RSILearningError, match="conflict"):
        learner.reconcile_callback(**conflicting)
    assert ledger.controller_checkpoint_history(RUN) == history
    assert learner.reconcile_callback(**kwargs) == kwargs["result"]


def test_reconcile_rejects_valid_hash_chain_that_rolls_back_consumed_budget(tmp_path):
    learner, ledger, components = _fixture(tmp_path, "judge")
    _crash(learner)
    kwargs = _reconciliation(learner, "judge", _result(components, "judge"))
    previous, state = ledger.controller_checkpoint(RUN)
    assert state["budget_state"]["consumed"]["solver_invocations"] == 1
    rolled_back = deepcopy(state)
    rolled_back["budget_state"] = deepcopy(ledger.history(RUN)[0].payload["budget_state"])
    with ledger.controller_lock(RUN):
        ledger.write_controller_checkpoint(RUN, rolled_back, expected_sha256=previous)
    history = ledger.controller_checkpoint_history(RUN)
    checkpoint = learner.callback_checkpoint(RUN, kwargs["callback_id"])
    calls = _counts(components)

    with pytest.raises(RSILearningError, match="budget_drift"):
        _controller(RSILedger(ledger.database), components).reconcile_callback(**kwargs)
    assert ledger.controller_checkpoint_history(RUN) == history
    assert learner.callback_checkpoint(RUN, kwargs["callback_id"]) == checkpoint
    assert _counts(components) == calls


def _emulate_old_callback_protocol(patch, learner, ledger, schema_version):
    create_run = ledger.create_run
    flow_state = learner._flow_state

    def old_create_run(run_id, request_sha256, payload):
        legacy = dict(payload)
        legacy.pop("callback_protocol_version", None)
        return create_run(run_id, _digest(legacy), legacy)

    def old_flow_state(*args, **kwargs):
        state = flow_state(*args, **kwargs)
        state.pop("callback_protocol_version", None)
        state["schema_version"] = schema_version
        return state

    def old_unjournaled_callback(run_id, callback_id, callback_stage, inputs, call, before_call=None):
        if before_call is not None:
            before_call()
        return call()

    patch.setattr(ledger, "create_run", old_create_run)
    patch.setattr(learner, "_flow_state", old_flow_state)
    patch.setattr(learner, "_invoke_callback", old_unjournaled_callback)


@pytest.mark.parametrize("stage,schema_version", [
    ("verifier", "1"), ("verifier", "2"), ("judge", "2"), ("curriculum", "2"),
])
def test_pre_callback_protocol_run_cannot_retry_an_unjournaled_old_callback(
    tmp_path, monkeypatch, stage, schema_version,
):
    learner, ledger, components = _fixture(tmp_path, stage)
    with monkeypatch.context() as patch:
        _emulate_old_callback_protocol(patch, learner, ledger, schema_version)
        _crash(learner)
    assert "callback_protocol_version" not in ledger.get_run(RUN).payload
    assert "callback_protocol_version" not in ledger.controller_checkpoint(RUN)[1]
    assert learner.callback_checkpoint(RUN, _callback_id(stage)[0]) is None
    history = ledger.controller_checkpoint_history(RUN)
    calls = _counts(components)
    for component in components[1:]:
        component.crash = False

    with pytest.raises(RSILearningError, match="callback_migration_required"):
        _controller(RSILedger(ledger.database), components).resume(RUN)
    assert _counts(components) == calls
    assert ledger.controller_checkpoint_history(RUN) == history


@pytest.mark.parametrize("schema_version", ["1", "2"])
def test_pre_callback_protocol_terminal_run_replays_without_migration_or_side_effects(
    tmp_path, monkeypatch, schema_version,
):
    learner, ledger, components = _fixture(tmp_path)
    with monkeypatch.context() as patch:
        _emulate_old_callback_protocol(patch, learner, ledger, schema_version)
        result = _run(learner)
    assert result.status == "completed"
    assert "callback_protocol_version" not in ledger.get_run(RUN).payload
    assert "callback_protocol_version" not in ledger.controller_checkpoint(RUN)[1]
    history = ledger.controller_checkpoint_history(RUN)
    calls = _counts(components)

    replayed = _controller(RSILedger(ledger.database), components).resume(RUN)
    assert replayed == result
    assert _counts(components) == calls
    assert ledger.controller_checkpoint_history(RUN) == history
