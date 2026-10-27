"""Operation-local staging parsing keeps fresh admission observations and refusals."""

from __future__ import annotations

import ast
import copy
import inspect
import sqlite3
import sys
import textwrap
from collections import Counter

import pytest
from test_rsi_python_admission import _register, _setup
from test_rsi_ready_capsule_consumers import _reference, _staging_history

import lunar_evolution.rsi_producer_staging_capsule as capsule
import lunar_evolution.rsi_store as store_module
from lunar_evolution import rsi_brs_publication_lineage as publication
from lunar_evolution import rsi_gateway as gateway_module
from lunar_evolution import rsi_python_scheduler_inputs as scheduler
from lunar_evolution.rsi_gateway import SolverRequest
from lunar_evolution.rsi_learning import MemorySnapshot, RSILearningError
from lunar_evolution.rsi_store import RSILedger

# Frozen differential oracle from 72c2f973, before operation-local reuse.
_ORIGINAL_WALK_SOURCE = r'''
def _validate_python_producer_staging_history_tx(
    self, history: list[tuple[str, dict[str, Any]]], *, run_id: str,
    expected_policy: dict[str, Any] | None = None,
) -> None:
    """Validate the controller-owned staging state without opening another snapshot."""
    if not history:
        raise RSILearningError("rsi_python_admission_checkpoint_missing")
    from .rsi_brs_serial_driver import reserved_brs_staging_mode
    from .rsi_producer_staging_capsule import retained_publication_evidence_bytes

    policy = history[0][1].get("producer_staging_policy")
    staged = policy is not None or "producer_episode_staging" in history[0][1]
    if not staged:
        if any("producer_staging_policy" in state or "producer_episode_staging" in state
               for _, state in history):
            raise RSILearningError("rsi_python_admission_child_proof_history_drift")
        return
    if type(policy) is not dict:
        raise RSILearningError("rsi_python_admission_child_proof_history_drift")
    if expected_policy is not None and policy != expected_policy:
        raise RSILearningError("rsi_python_admission_child_proof_history_drift")
    previous_entries: dict[str, dict[str, Any]] = {}
    previous_digest: str | None = None
    capsule_mode = history[0][1].get("producer_multi_episode_publication")
    if capsule_mode is not None and type(capsule_mode) is not bool:
        raise RSILearningError("rsi_python_admission_child_proof_history_drift")
    states_by_digest = {digest: state for digest, state in history}
    original_state = history[0][1]
    serial = reserved_brs_staging_mode(original_state)
    for digest, state in history:
        if (reserved_brs_staging_mode(state) is not serial
                or serial and (state.get("plan") != original_state.get("plan")
                    or state.get("producer_brs_checkpoint_policy")
                    != original_state.get("producer_brs_checkpoint_policy"))):
            raise RSILearningError("rsi_python_admission_child_proof_history_drift")
        if (state.get("run_id") != run_id or state.get("producer_staging_policy") != policy
                or type(state.get("producer_episode_staging")) is not dict
                or ("producer_multi_episode_publication" in state
                    and type(state["producer_multi_episode_publication"]) is not bool)
                or state.get("producer_multi_episode_publication") != capsule_mode
                or (capsule_mode is True and ((state.get("mode") != "drs"
                    and not reserved_brs_staging_mode(state))
                    or state.get("producer_child_execution") is not True))):
            raise RSILearningError("rsi_python_admission_child_proof_history_drift")
        retained_publication_evidence_bytes(state)
        entries = state["producer_episode_staging"]
        if not set(previous_entries).issubset(entries):
            raise RSILearningError("rsi_python_admission_child_proof_history_drift")
        for episode_id, entry in entries.items():
            if (type(episode_id) is not str or type(entry) is not dict
                    or set(entry) != {"state", "identity", "ready", "failure_code"}
                    or entry["state"] not in {"preparing", "ready", "unknown"}
                    or type(entry["identity"]) is not dict):
                raise RSILearningError("rsi_python_admission_child_proof_history_drift")
            identity = entry["identity"]
            required = {
                "run_id", "episode_id", "original_run_request_sha256", "original_run_record_sha256",
                "origin_checkpoint_sha256", "intent", "request_sha256", "memory",
                "memory_snapshot_sha256", "journal_id", "launch_id", "policy",
            }
            if set(identity) != required or identity["run_id"] != run_id or identity["episode_id"] != episode_id:
                raise RSILearningError("rsi_python_admission_child_proof_history_drift")
            if identity.get("policy") != policy:
                raise RSILearningError("rsi_python_admission_child_proof_history_drift")
            try:
                request = SolverRequest.from_dict(identity["intent"]["request"])
                memory = MemorySnapshot.from_dict(identity["memory"])
                token = hashlib.sha256(canonical_json({
                    "run_id": run_id, "episode_id": episode_id, "request": request.digest(),
                })).hexdigest()[:32]
                if (request.episode_id != episode_id
                        or request.digest() != identity["request_sha256"]
                        or memory.digest() != identity["memory_snapshot_sha256"]
                        or request.memory_snapshot_sha256 != memory.digest()
                        or identity["journal_id"] != "rsi-stage-" + token
                        or identity["launch_id"] != "rsi-launch-" + token):
                    raise ValueError("staging identity changed")
            except (KeyError, TypeError, ValueError, RSILearningError) as exc:
                raise RSILearningError("rsi_python_admission_child_proof_history_drift") from exc
            prior = previous_entries.get(episode_id)
            if prior is None:
                if (entry["state"] != "preparing" or entry["ready"] is not None
                        or entry["failure_code"] is not None
                        or identity["origin_checkpoint_sha256"] != previous_digest):
                    raise RSILearningError("rsi_python_admission_child_proof_history_drift")
                # The intent must already be durable in the immediately preceding checkpoint.
                if previous_digest is None:
                    raise RSILearningError("rsi_python_admission_child_proof_history_drift")
                prior_state = states_by_digest.get(previous_digest)
                if prior_state is None or prior_state.get("intents", {}).get(episode_id) != identity.get("intent"):
                    raise RSILearningError("rsi_python_admission_child_proof_history_drift")
            else:
                if prior["identity"] != identity:
                    raise RSILearningError("rsi_python_admission_child_proof_history_drift")
                allowed = {"preparing": {"preparing", "ready", "unknown"},
                           "ready": {"ready"}, "unknown": {"unknown"}}
                if entry["state"] not in allowed[prior["state"]]:
                    raise RSILearningError("rsi_python_admission_child_proof_history_drift")
                if prior["state"] != "preparing" and entry != prior:
                    raise RSILearningError("rsi_python_admission_child_proof_history_drift")
            if entry["state"] == "preparing" and (entry["ready"] is not None or entry["failure_code"] is not None):
                raise RSILearningError("rsi_python_admission_child_proof_history_drift")
            if entry["state"] == "unknown" and (entry["ready"] is not None or entry["failure_code"] != "staging_failed"):
                raise RSILearningError("rsi_python_admission_child_proof_history_drift")
            if entry["state"] == "ready" and entry["failure_code"] is not None:
                raise RSILearningError("rsi_python_admission_child_proof_history_drift")
        previous_entries = entries
        previous_digest = digest
'''


def _original_walk():
    namespace = dict(vars(store_module))
    # This trusted frozen local baseline is the differential oracle, never input.
    exec(compile(_ORIGINAL_WALK_SOURCE, "<original-staging-history>", "exec"), namespace)  # noqa: S102
    return namespace["_validate_python_producer_staging_history_tx"]


def _history(tmp_path, *, repeated=12):
    episode_id, history = _staging_history(_reference(tmp_path))
    history.extend((f"head-{index + 4}", copy.deepcopy(history[-1][1])) for index in range(repeated))
    return episode_id, history


def _counts(operation):
    functions = {
        SolverRequest.from_dict.__func__.__code__: "request_parse",
        MemorySnapshot.from_dict.__func__.__code__: "memory_parse",
        SolverRequest.digest.__code__: "request_digest",
        MemorySnapshot.digest.__code__: "memory_digest",
    }
    counts = Counter()

    def observe(frame, event, _argument):
        if event == "call" and frame.f_code in functions:
            counts[functions[frame.f_code]] += 1

    previous = sys.getprofile()
    sys.setprofile(observe)
    try:
        operation()
    finally:
        sys.setprofile(previous)
    return counts


def _outcome(walk, ledger, history):
    try:
        walk(ledger, copy.deepcopy(history), run_id="run-1")
    except (TypeError, ValueError) as error:
        return type(error), str(error)
    return None


def test_unchanged_entries_parse_only_twice_per_fresh_history_call(tmp_path):
    _episode_id, history = _history(tmp_path)
    ledger = object.__new__(RSILedger)
    before = copy.deepcopy(history)
    original = _counts(lambda: _original_walk()(ledger, history, run_id="run-1"))
    assert original == {"request_parse": 15, "memory_parse": 15, "request_digest": 30, "memory_digest": 30}
    for _ in range(2):
        current = _counts(lambda: ledger._validate_python_producer_staging_history_tx(history, run_id="run-1"))
        assert current == {"request_parse": 2, "memory_parse": 2, "request_digest": 4, "memory_digest": 4}
    assert history == before


@pytest.mark.parametrize("mutation", ["identity", "ready", "phase", "policy", "remove", "budget"])
def test_changed_history_keeps_original_first_refusal(tmp_path, mutation):
    episode_id, history = _history(tmp_path, repeated=0)
    final = history[-1][1]
    entry = final["producer_episode_staging"][episode_id]
    if mutation == "identity":
        entry["identity"]["request_sha256"] = "f" * 64
    elif mutation == "ready":
        entry["ready"]["file_pin"]["inode"] += 1
    elif mutation == "phase":
        entry["state"] = "preparing"
    elif mutation == "policy":
        final["producer_staging_policy"] = {"changed": True}
    elif mutation == "remove":
        final["producer_episode_staging"].clear()
    else:
        entry["ready"]["file_pin"]["size"] = 64 * 1024 * 1024 + 1
    ledger = object.__new__(RSILedger)
    expected = _outcome(_original_walk(), ledger, history)
    assert expected is not None
    assert _outcome(RSILedger._validate_python_producer_staging_history_tx, ledger, history) == expected


@pytest.mark.parametrize(("owner", "name"), [
    (SolverRequest, "from_dict"), (MemorySnapshot, "from_dict"),
    (SolverRequest, "digest"), (MemorySnapshot, "digest"),
])
def test_foreign_direct_helpers_keep_per_checkpoint_calls(tmp_path, monkeypatch, owner, name):
    _episode_id, history = _history(tmp_path)
    ledger = object.__new__(RSILedger)
    original = getattr(owner, name)
    calls = []
    if name == "from_dict":
        def changed(_cls, value):
            calls.append(value)
            return original(value)
        monkeypatch.setattr(owner, name, classmethod(changed))
    else:
        def changed(value):
            calls.append(value)
            return original(value)
        monkeypatch.setattr(owner, name, changed)
    ledger._validate_python_producer_staging_history_tx(history, run_id="run-1")
    assert len(calls) == (15 if name == "from_dict" else 30)


@pytest.mark.parametrize("mutation", ["code", "defaults", "kwdefaults"])
def test_direct_helper_in_place_drift_disables_reuse(tmp_path, monkeypatch, mutation):
    _episode_id, history = _history(tmp_path)
    ledger = object.__new__(RSILedger)
    function = MemorySnapshot.digest
    if mutation == "code":
        original_code = function.__code__
        monkeypatch.setattr(function, "__code__", original_code.replace(co_name="changed_digest"))
    elif mutation == "defaults":
        monkeypatch.setattr(function, "__defaults__", (None,))
    else:
        monkeypatch.setattr(function, "__kwdefaults__", {"foreign": None})
    assert not store_module._staging_identity_helpers_current()
    counts = _counts(lambda: ledger._validate_python_producer_staging_history_tx(history, run_id="run-1"))
    assert counts["request_parse"] == counts["memory_parse"] == 15


def test_nested_callback_entry_never_reaches_projection_equality(tmp_path):
    episode_id, history = _history(tmp_path, repeated=0)
    observed = []

    class CallbackDict(dict):
        def __eq__(self, _other):
            observed.append("equality")
            raise AssertionError("callback equality")

    request = history[-1][1]["producer_episode_staging"][episode_id]["identity"]["intent"]["request"]
    request["solver_settings"]["callback"] = CallbackDict()
    with pytest.raises(RSILearningError, match="shape_invalid"):
        object.__new__(RSILedger)._validate_python_producer_staging_history_tx(history, run_id="run-1")
    assert observed == []


def test_direct_helper_replaced_after_first_entry_does_not_reuse_prior_result(tmp_path, monkeypatch):
    _episode_id, history = _history(tmp_path, repeated=0)
    original = capsule.retained_publication_evidence_bytes
    calls = []

    def refuse(_memory):
        calls.append("digest")
        raise ValueError("memory digest replaced")

    def observe(state):
        result = original(state)
        if state is history[-1][1]:
            monkeypatch.setattr(MemorySnapshot, "digest", refuse)
        return result

    monkeypatch.setattr(capsule, "retained_publication_evidence_bytes", observe)
    with pytest.raises(RSILearningError, match="child_proof_history_drift"):
        object.__new__(RSILedger)._validate_python_producer_staging_history_tx(history, run_id="run-1")
    assert calls == ["digest"]


def test_every_checkpoint_capacity_gate_stays_fresh(tmp_path, monkeypatch):
    _episode_id, history = _history(tmp_path)
    original = capsule.retained_publication_evidence_bytes
    calls = []

    def observe(state):
        calls.append(state)
        return original(state)

    monkeypatch.setattr(capsule, "retained_publication_evidence_bytes", observe)
    object.__new__(RSILedger)._validate_python_producer_staging_history_tx(history, run_id="run-1")
    assert len(calls) == len(history)


def test_postparse_projection_bound_does_not_add_an_original_path_refusal(tmp_path, monkeypatch):
    original = gateway_module._wire_record
    for walk in (_original_walk(), RSILedger._validate_python_producer_staging_history_tx):
        episode_id, history = _history(tmp_path, repeated=0)
        history = history[:3]
        entry = history[-1][1]["producer_episode_staging"][episode_id]

        def mutate(value, *, original_entry=entry, **arguments):
            result = original(value, **arguments)
            if value is original_entry["identity"]["intent"]["request"]:
                original_entry["post-parse-only"] = "x" * (128 * 1024)
            return result

        with monkeypatch.context() as patch:
            patch.setattr(gateway_module, "_wire_record", mutate)
            walk(object.__new__(RSILedger), history, run_id="run-1")
        assert "post-parse-only" in entry


def test_admission_second_select_discards_staging_helper_mutation(tmp_path, monkeypatch):
    value = _setup(tmp_path)
    retained = _register(value)
    original = value.ledger._validate_python_producer_staging_history_tx
    mutated_states = []

    def mutate(history, **arguments):
        original(history, **arguments)
        for _head, state in history:
            state["private-helper-marker"] = True
            mutated_states.append(state)

    monkeypatch.setattr(value.ledger, "_validate_python_producer_staging_history_tx", mutate)
    with sqlite3.connect(value.ledger.database) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("BEGIN")
        queries = []
        connection.set_trace_callback(queries.append)
        _run, state, _episode_status, _claim_status = value.ledger._python_admission_state_tx(connection, retained)
    assert mutated_states and all(item["private-helper-marker"] for item in mutated_states)
    assert "private-helper-marker" not in state
    assert state is not mutated_states[-1]
    checkpoint_selects = [sql for sql in queries if sql.startswith("SELECT revision, parent_sha256, payload, checkpoint_sha256 ")]
    assert len(checkpoint_selects) == 2


def test_original_admission_fresh_decode_path_remains_in_place():
    source = textwrap.dedent(inspect.getsource(RSILedger._python_admission_state_tx))
    tree = ast.parse(source)
    assignments = [node for node in ast.walk(tree) if isinstance(node, ast.Assign)]
    assert any(
        any(isinstance(target, ast.Name) and target.id == "state" for target in node.targets)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and isinstance(node.value.func.value, ast.Name) and node.value.func.value.id == "json"
        and node.value.func.attr == "loads"
        for node in assignments
    )


def test_staging_projection_helpers_participate_in_scheduler_code_identity(monkeypatch):
    original = scheduler._code_dependencies()
    assert "staging_identity_guard" in original
    assert "staging_history_validator" in original

    def changed():
        raise AssertionError("dependency projection executed a replaced helper")

    monkeypatch.setattr(store_module._staging_identity_helpers_current, "__code__", changed.__code__)
    assert scheduler._code_dependencies()["staging_identity_guard"] != original["staging_identity_guard"]
    monkeypatch.setattr(publication._POLICY_OBSERVATION_LOCAL, "cache", {"policy": {"warm": True}}, raising=False)
    with pytest.raises(RSILearningError, match="rejection_policy_drift"):
        publication._policy()


def test_staging_projection_table_drift_refuses_before_warm_policy_or_foreign_equality(monkeypatch):
    class Foreign:
        def __eq__(self, _other):
            raise AssertionError("foreign staging projection equality")

    monkeypatch.setattr(store_module, "_STAGING_IDENTITY_HELPERS", Foreign())
    monkeypatch.setattr(publication._POLICY_OBSERVATION_LOCAL, "cache", {"policy": {"warm": True}}, raising=False)
    with pytest.raises(RSILearningError, match="staging_identity_policy_drift"):
        publication._policy()
    with pytest.raises(RSILearningError, match="staging_identity_policy_drift"):
        scheduler._code_dependencies()
