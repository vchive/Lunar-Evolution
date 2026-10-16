"""Original BRS policy persistence over inert real controller/SQLite lifecycles."""

from __future__ import annotations

import json
import socket
import sqlite3
import subprocess
from copy import deepcopy

import pytest
import test_rsi_brs_publication_lineage_owner as checkpoint
import test_rsi_python_brs_selected_service as selected
from test_rsi_python_admission import DIGEST, _NoSolverGateway, _rows, _setup

from lunar_evolution import RSILearningController, RSILearningError, RSILedger
from lunar_evolution import rsi_brs_publication_lineage as brs
from lunar_evolution.rsi_fingerprint import RSIFingerprintContract, RSIFingerprintError

FIELD = "producer_brs_checkpoint_policy"


@pytest.fixture
def tmp_path(tmp_path_factory):
    return tmp_path_factory.mktemp("p")


@pytest.fixture(autouse=True)
def inert_only(monkeypatch):
    def forbidden(*_args, **_kwargs):
        pytest.fail("pre-wave policy fixture invoked external execution")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)


def _fingerprint(value, *, context=True):
    original = value.ledger.history(value.binding.run_id)[0].payload
    return value.controller._run_fingerprint(
        **value.state["pins"], memory_snapshot_sha256=original["fingerprints"]["run_fingerprint"]["memory_snapshot_sha256"],
        **({"mode": original["mode"], "plan": original["plan"]} if context else {}),
    )[0].to_dict()


def _rewrite_history(value, *, table, target, mutate):
    """Keep a valid immutable-chain encoding while injecting one historical fault."""
    with sqlite3.connect(value.ledger.database) as connection:
        connection.row_factory = sqlite3.Row
        if table == "run":
            rows = connection.execute(
                "SELECT * FROM rsi_records WHERE logical_id=? ORDER BY revision", (value.binding.run_id,),
            ).fetchall()
        else:
            rows = connection.execute(
                "SELECT * FROM rsi_controller_journal WHERE run_id=? ORDER BY revision", (value.binding.run_id,),
            ).fetchall()
        assert 0 <= target < len(rows)
        parent = None
        for index, row in enumerate(rows):
            payload = json.loads(row["payload"])
            if index == target:
                mutate(payload)
            if table == "run":
                digest = value.ledger._record_digest(
                    logical_id=row["logical_id"], revision=row["revision"], kind=row["kind"],
                    state=row["state"], request_sha256=row["request_sha256"],
                    parent_record_sha256=parent, payload=payload,
                )
                connection.execute(
                    "UPDATE rsi_records SET payload=?,parent_record_sha256=?,record_sha256=? "
                    "WHERE logical_id=? AND revision=?",
                    (json.dumps(payload, sort_keys=True), parent, digest, value.binding.run_id, row["revision"]),
                )
            else:
                digest = value.ledger._checkpoint_digest(value.binding.run_id, row["revision"], parent, payload)
                connection.execute(
                    "UPDATE rsi_controller_journal SET payload=?,parent_sha256=?,checkpoint_sha256=? "
                    "WHERE run_id=? AND revision=?",
                    (json.dumps(payload, sort_keys=True), parent, digest, value.binding.run_id, row["revision"]),
                )
            parent = digest


def test_original_policy_precedes_any_worker_and_matches_every_fingerprint_and_checkpoint(tmp_path, monkeypatch):
    value = selected._fixture(tmp_path, monkeypatch)
    history = value.ledger.history(value.binding.run_id)
    original = history[0].payload
    policy = original[FIELD]
    assert history[0].state == "created"
    assert policy == brs._policy()
    assert policy["mode"] == "brs" and policy["max_workers"] == 1
    assert policy["online_publication"] is False and policy["production_admission"] is False
    assert all(record.payload[FIELD] == policy for record in history)
    assert all(record.payload["fingerprints"]["run_fingerprint"]["solver_settings"][FIELD] == policy
               for record in history)
    assert all(state[FIELD] == policy for _head, state in value.ledger.controller_checkpoint_history(value.binding.run_id))
    assert value.gateway.calls == 0
    assert value.ledger.get_episode(value.episode_id) is None
    assert value.controller.producer_multi_episode_publication is False
    assert value.controller.producer_child_execution is False
    assert "producer_publication_lineage" not in value.state
    assert _fingerprint(value) == original["fingerprints"]["run_fingerprint"]
    default = _fingerprint(value, context=False)
    assert FIELD not in default["solver_settings"]
    assert {key: item for key, item in default.items() if key not in {"solver_settings", "fingerprint_sha256"}} == {
        key: item for key, item in original["fingerprints"]["run_fingerprint"].items()
        if key not in {"solver_settings", "fingerprint_sha256"}
    }


@pytest.mark.parametrize("boundary", ["existing-run", "resume-identity", "selected-pins", "flow-state"])
def test_original_run_recomputes_same_policy_at_each_existing_identity_boundary(tmp_path, monkeypatch, boundary):
    value = selected._fixture(tmp_path, monkeypatch)
    record = value.ledger.get_run(value.binding.run_id)
    policy = record.payload[FIELD]
    rows = _rows(value)
    if boundary == "existing-run":
        value.controller._assert_existing_run_request(
            record, mode="brs", budget=record.payload["budget"], **value.state["pins"],
        )
    elif boundary == "resume-identity":
        value.controller._validate_resume_identity(record, None, record.payload["budget"])
    elif boundary == "selected-pins":
        with selected._wave(value) as wave:
            handoff = value.controller._python_admission_bind_selected_brs_handoff(wave)
            assert handoff.episode_id == value.episode_id
            assert wave.selected_context.source_sha256 == RSIFingerprintContract.from_dict(_fingerprint(value)).digest()
    else:
        state = value.controller._flow_state(
            record, run_id=value.binding.run_id, plan=value.state["plan"], pins=value.state["pins"],
            budget=record.payload["budget"],
        )
        assert state[FIELD] == policy
    assert _rows(value) == rows
    assert value.gateway.calls == 0


@pytest.mark.parametrize("fault", ["original", "original-fingerprint", "intermediate-checkpoint", "latest-checkpoint"])
@pytest.mark.parametrize("missing", [False, True])
def test_owner_checks_every_original_policy_pin_before_its_next_write(tmp_path, monkeypatch, fault, missing):
    with checkpoint._waiting(tmp_path, monkeypatch) as value:
        wire = checkpoint._before(value)
        captured = checkpoint._capture(value)

        def change(payload):
            container = payload["fingerprints"]["run_fingerprint"]["solver_settings"] if fault == "original-fingerprint" else payload
            if missing:
                container.pop(FIELD)
            else:
                container[FIELD]["online_publication"] = True

        if fault in {"original", "original-fingerprint"}:
            _rewrite_history(value, table="run", target=0, mutate=change)
        else:
            count = len(value.ledger.controller_checkpoint_history(value.binding.run_id))
            assert count > 2
            _rewrite_history(value, table="checkpoint", target=1 if fault == "intermediate-checkpoint" else count - 1, mutate=change)
        rows = _rows(value)
        with pytest.raises(RSILearningError, match="rsi_brs_publication_lineage_persisted_policy"):
            value.owner.checkpoint_before(wire)
        checkpoint._unchanged(value, captured)
        assert _rows(value) == rows
        assert value.owner._poisoned


@pytest.mark.parametrize("boundary", ["history-validator", "selected-handoff", "resume"])
def test_old_run_missing_original_pin_is_refused_without_backfill(tmp_path, monkeypatch, boundary):
    with monkeypatch.context() as legacy:
        legacy.setattr(brs, "_run_policy", lambda *_args, **_kwargs: None)
        legacy.setattr(brs, "_validate_persisted_policy", lambda *_args, **_kwargs: None)
        value = selected._fixture(tmp_path, monkeypatch)
    assert FIELD not in value.ledger.history(value.binding.run_id)[0].payload
    rows = _rows(value)
    if boundary == "history-validator":
        operation = lambda: value.controller._validate_producer_staging(value.ledger.get_run(value.binding.run_id), value.state)
    elif boundary == "resume":
        operation = lambda: value.controller.resume(value.binding.run_id)
    else:
        def operation():
            with selected._wave(value) as wave:
                value.controller._python_admission_bind_selected_brs_handoff(wave)
                pytest.fail("old run acquired selected handoff authority")
    with pytest.raises((RSILearningError, RSIFingerprintError), match="persisted_policy|fingerprint_drift"):
        operation()
    assert _rows(value) == rows
    assert value.gateway.calls == 0
    assert FIELD not in value.ledger.history(value.binding.run_id)[0].payload


def test_locked_historical_policy_check_does_not_execute_fingerprint_hooks(tmp_path, monkeypatch):
    value = selected._fixture(tmp_path, monkeypatch)

    def forbidden():
        pytest.fail("durable JSON comparison invoked source/configuration hooks under observation mutex")

    monkeypatch.setattr(brs, "_policy", forbidden)
    with value.controller._python_admission_brs_observations():
        value.controller._validate_producer_staging(value.ledger.get_run(value.binding.run_id), value.state)


def test_pin_only_selected_service_keeps_policy_without_lineage_or_publication_grant(tmp_path, monkeypatch):
    value = selected._fixture(tmp_path, monkeypatch)
    policy = deepcopy(value.state[FIELD])
    record = value.ledger.get_run(value.binding.run_id)
    with selected._wave(value) as wave:
        result = value.controller._python_admission_run_selected_brs_intent(wave)
        value.controller._python_admission_settle_selected_brs_execution(record, wave, result)
    assert value.state[FIELD] == policy
    assert value.gateway.calls == 1
    assert "producer_publication_lineage" not in value.state
    assert value.controller.producer_multi_episode_publication is False
    assert value.controller.producer_child_execution is False


@pytest.mark.parametrize("case", ["drs-sidecar", "brs-multiworker", "brs-provider-free"])
def test_unselected_real_runs_keep_policy_out_of_original_payload_and_checkpoints(tmp_path, monkeypatch, case):
    if case == "drs-sidecar":
        value = _setup(tmp_path)
        ledger, run_id = value.ledger, value.binding.run_id
    elif case == "brs-multiworker":
        value = selected._fixture(tmp_path, monkeypatch, max_workers=2)
        ledger, run_id = value.ledger, value.binding.run_id
    else:
        ledger, run_id = RSILedger(tmp_path / "plain.sqlite3"), "plain-brs"
        controller = RSILearningController(_NoSolverGateway(), ledger=ledger)

        def stop(_state, _episode_id):
            raise selected._PreparationCaptured()

        monkeypatch.setattr(controller, "_execute_intent", stop)
        with pytest.raises(selected._PreparationCaptured):
            controller.run_brs(
                run_id=run_id, contract_sha256=DIGEST, evaluator_sha256=DIGEST,
                environment_sha256=DIGEST, solver_id="inert",
                practices=selected._decisions(controller, run_id, 1), max_workers=1,
            )
    assert all(FIELD not in record.payload and FIELD not in record.payload["fingerprints"]["run_fingerprint"]["solver_settings"]
               for record in ledger.history(run_id))
    assert all(FIELD not in state for _head, state in ledger.controller_checkpoint_history(run_id))
