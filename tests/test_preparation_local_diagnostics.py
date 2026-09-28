"""Automatic solve exposes only bound, controller-owned local preparation observations."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from test_conversational_automatic_bundle import automatic_setup
from test_preparation_recovery_cli import followup, observations, run_cli, runtime_calls, snapshot

from lunar_evolution import automatic_solve_bundle as automatic
from lunar_evolution import cli
from lunar_evolution.algorithm import AlgorithmProblemContract
from lunar_evolution.evaluator_bundle import EvaluatorPreparationError
from lunar_evolution.evaluator_diagnostics import EvaluatorPreparationDiagnostic
from lunar_evolution.runtime import RuntimeResult
from lunar_evolution.store import Store

PRIVATE = "fresh-private-generated-probe-or-provider-content"
DETAIL_KEYS = {"schema_version", "stage", "reason", "probe_index", "input_index", "order_index"}


def setup_failure(tmp_path, monkeypatch, *, role="compiler", failure="input"):
    """Fresh JSON input and native response admission; no historical response replay."""
    runtime, args = automatic_setup(tmp_path, monkeypatch)
    contract = runtime.contract.to_dict()
    contract["inputs"][0]["format"] = "json"
    contract["inputs"][0]["fields"] = {"limit": "Upper bound."}
    runtime.contract = AlgorithmProblemContract.from_dict(contract)
    (tmp_path / "inputs/value").write_text('{"limit":10}')
    original = runtime.run

    def run(prompt, workspace, timeout=None):
        result = original(prompt, workspace, timeout)
        current = (
            "compiler" if "frozen local evaluator bundle" in prompt else
            "auditor" if "adversarial evaluator auditor" in prompt else None
        )
        if current is None:
            return result
        if current == role and failure == "response":
            return RuntimeResult('{"' + PRIVATE + '":')
        payload = json.loads(result.text)
        for probe in payload["probes"]:
            probe["files"][0]["content"] = '{"limit":10}'
        if current == "compiler":
            payload["evaluator_source"] = payload["evaluator_source"].replace(
                'int(Path("inputs/value").read_text())',
                'json.loads(Path("inputs/value").read_text())["limit"]',
            )
        if current == role and failure == "input":
            payload["probes"][2]["name"] = PRIVATE
            payload["probes"][2]["files"][0]["content"] = "10"
        return RuntimeResult(json.dumps(payload))

    monkeypatch.setattr(runtime, "run", run)
    return runtime, args


def failed_run(tmp_path, monkeypatch, capsys, *, role="compiler", failure="input"):
    runtime, args = setup_failure(tmp_path, monkeypatch, role=role, failure=failure)
    code, failed, stderr = run_cli(capsys, args)
    assert code == 1 and stderr == ""
    store = Store(tmp_path / "home/state.db")
    return runtime, failed, store, Path(failed["workspace"])


def replace_payload(store, event, payload):
    with store._connect() as connection:
        connection.execute("UPDATE events SET payload = ? WHERE id = ?", (json.dumps(payload), event["id"]))


def check_status(tmp_path, capsys, runtime, store, failed, workspace):
    before, calls = snapshot(store, failed["run_id"], workspace), runtime_calls(runtime)
    args = ["status", failed["run_id"], "--home", str(tmp_path / "home")]
    code, status, stderr = run_cli(capsys, [*args, "--json"])
    assert code == 0 and stderr == ""
    preparation = status["evolution"]["preparation"]
    assert automatic.automatic_bundle_preparation_status(store, failed["run_id"]) == preparation
    assert cli.main(args) == 0
    text = capsys.readouterr()
    assert text.err == "" and PRIVATE not in text.out
    assert PRIVATE not in json.dumps(status)
    assert snapshot(store, failed["run_id"], workspace) == before
    assert runtime_calls(runtime) == calls
    return preparation, text.out


@pytest.mark.parametrize("role", ["compiler", "auditor"])
@pytest.mark.parametrize("failure", ["response", "input"])
def test_native_local_failure_is_durable_and_visible_without_reexecution(
    tmp_path, monkeypatch, capsys, role, failure,
):
    runtime, failed, store, workspace = failed_run(
        tmp_path, monkeypatch, capsys, role=role, failure=failure,
    )
    stage = role + ("_response" if failure == "response" else "_preflight")
    expected_detail = {
        "schema_version": "1", "stage": stage,
        "reason": ("response_envelope_invalid" if role == "auditor" else "response_invalid")
        if failure == "response" else "input_format_invalid",
        "probe_index": None if failure == "response" else 3,
        "input_index": None if failure == "response" else 1, "order_index": None,
    }
    preparation = failed["evolution"]["preparation"]
    assert preparation == {
        "schema_version": "2", "parent_run_id": failed["run_id"],
        "attempt_id": preparation["attempt_id"], "status": "failed", "stage": stage,
        "error_category": "validation_error", "recoverable": False, "local_failure": expected_detail,
    }
    records = observations(store, failed["run_id"])
    assert [row["type"] for row in records] == ["bundle_preparation_started", "bundle_preparation_failed"]
    assert records[0]["payload"]["schema_version"] == "2"
    assert records[0]["payload"]["preparation_budgets"] == {
        "candidate_timeout_seconds": 3.0,
        "request_timeout_seconds": 3.0,
        "wall_timeout_seconds": 66.0,
    }
    assert records[0]["payload"]["attempt_id"] == preparation["attempt_id"]
    assert records[1]["payload"] == preparation
    assert set(preparation["local_failure"]) == DETAIL_KEYS
    assert PRIVATE not in json.dumps([failed, records])
    assert runtime_calls(runtime) == (1, 1, int(role == "auditor"), 0, 2 + int(role == "auditor"))
    assert not (workspace / "evaluator-bundle").exists()
    assert not (workspace / "bundle-profile.json").exists()
    assert not (workspace / "evolution-run").exists()
    assert not list(workspace.glob(".evaluator-bundle-*"))
    restored, text = check_status(tmp_path, capsys, runtime, store, failed, workspace)
    assert restored == preparation
    assert f"{stage}: validation_error" in text
    assert f"preparation_local_failure: {expected_detail['reason']}" in text
    if failure == "input":
        assert "probe_index=3 input_index=1" in text
    else:
        assert "probe_index=" not in text and "input_index=" not in text
    assert f"preparation_local_failure: {expected_detail['reason']}" in text
    if failure == "input":
        assert "probe_index=3" in text and "input_index=1" in text


CORRUPTIONS = [
    "detail_missing", "detail_null", "detail_string", "detail_extra", "detail_missing_key",
    "detail_version", "unknown_stage", "unknown_reason", "stage_binding", "reason_stage",
    "bool_probe", "float_probe", "zero_probe", "large_probe", "negative_input", "large_input",
    "missing_input", "extra_order", "outer_version", "outer_extra", "outer_status",
    "outer_category", "outer_recoverable", "outer_stage", "parent", "attempt", "no_start",
    "duplicate_start", "start_extra", "start_version", "start_stage", "start_parent", "start_attempt",
]


@pytest.mark.parametrize("corruption", CORRUPTIONS)
def test_status_discards_malformed_or_unbound_local_failure_without_echo_or_calls(
    tmp_path, monkeypatch, capsys, corruption,
):
    runtime, failed, store, workspace = failed_run(tmp_path, monkeypatch, capsys)
    records = observations(store, failed["run_id"])
    event, start = records[1], records[0]
    payload = copy.deepcopy(event["payload"])
    detail = payload["local_failure"]
    if corruption == "detail_missing":
        del payload["local_failure"]
    elif corruption == "detail_null":
        payload["local_failure"] = None
    elif corruption == "detail_string":
        payload["local_failure"] = PRIVATE
    elif corruption == "detail_extra":
        detail["provider_error"] = PRIVATE
    elif corruption == "detail_missing_key":
        del detail["order_index"]
    elif corruption == "detail_version":
        detail["schema_version"] = "9"
    elif corruption == "unknown_stage":
        detail["stage"] = PRIVATE
    elif corruption == "unknown_reason":
        detail["reason"] = PRIVATE
    elif corruption == "stage_binding":
        detail["stage"] = "auditor_preflight"
    elif corruption == "reason_stage":
        detail["reason"] = "response_invalid"
    elif corruption in {"bool_probe", "float_probe", "zero_probe", "large_probe"}:
        detail["probe_index"] = {"bool_probe": True, "float_probe": 1.0, "zero_probe": 0, "large_probe": 65}[corruption]
    elif corruption in {"negative_input", "large_input", "missing_input"}:
        detail["input_index"] = {"negative_input": -1, "large_input": 33, "missing_input": None}[corruption]
    elif corruption == "extra_order":
        detail["order_index"] = 1
    elif corruption == "outer_version":
        payload["schema_version"] = "1"
    elif corruption == "outer_extra":
        payload["source"] = PRIVATE
    elif corruption == "outer_status":
        payload["status"] = "started"
    elif corruption == "outer_category":
        payload["error_category"] = "runtime_error"
    elif corruption == "outer_recoverable":
        payload["recoverable"] = True
    elif corruption == "outer_stage":
        payload["stage"] = "evaluator_compile"
    elif corruption == "parent":
        payload["parent_run_id"] = "different-parent"
    elif corruption == "attempt":
        payload["attempt_id"] = "preparation-" + "f" * 32
    elif corruption == "no_start":
        with store._connect() as connection:
            connection.execute("DELETE FROM events WHERE id = ?", (start["id"],))
    elif corruption == "duplicate_start":
        # Keep the original failed event as the latest observation.
        with store._connect() as connection:
            columns = [row[1] for row in connection.execute("PRAGMA table_info(events)")]
            source = dict(connection.execute("SELECT * FROM events WHERE id = ?", (start["id"],)).fetchone())
            source["id"] = "duplicate-start"
            connection.execute(
                f"INSERT INTO events ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                tuple(source[key] for key in columns),
            )
    else:
        altered = copy.deepcopy(start["payload"])
        field, value = {
            "start_extra": ("message", PRIVATE), "start_version": ("schema_version", "invalid"),
            "start_stage": ("stage", "compiler_preflight"), "start_parent": ("parent_run_id", "other"),
            "start_attempt": ("attempt_id", "preparation-" + "e" * 32),
        }[corruption]
        altered[field] = value
        replace_payload(store, start, altered)
    replace_payload(store, event, payload)
    preparation, text = check_status(tmp_path, capsys, runtime, store, failed, workspace)
    assert preparation["schema_version"] == "1"
    assert preparation["status"] == "failed" and preparation["error_category"] == "validation_error"
    assert preparation["recoverable"] is False
    assert "local_failure" not in preparation and "resume_hint" not in preparation
    assert "preparation_local_failure:" not in text
    assert "input_format_invalid" not in text


def test_legacy_coarse_validation_observation_remains_compatible(tmp_path, monkeypatch, capsys):
    runtime, failed, store, workspace = failed_run(tmp_path, monkeypatch, capsys)
    event = observations(store, failed["run_id"])[1]
    payload = {key: value for key, value in event["payload"].items() if key != "local_failure"}
    payload.update(schema_version="1", stage="preparation")
    replace_payload(store, event, payload)
    preparation, _ = check_status(tmp_path, capsys, runtime, store, failed, workspace)
    assert preparation == payload


@pytest.mark.parametrize("new_state", ["cancelled", "failed", "succeeded", "input_drift"])
def test_stronger_parent_or_input_state_hides_stale_diagnostic(tmp_path, monkeypatch, capsys, new_state):
    runtime, failed, store, workspace = failed_run(tmp_path, monkeypatch, capsys)
    if new_state == "cancelled":
        assert store.cancel_run(failed["run_id"])
    elif new_state == "input_drift":
        (workspace / "data/raw/value").write_bytes(b'{"limit":20}')
    else:
        with store._connect() as connection:
            connection.execute("UPDATE runs SET status = ? WHERE id = ?", (new_state, failed["run_id"]))
    preparation, text = check_status(tmp_path, capsys, runtime, store, failed, workspace)
    assert preparation["error_category"] == ("cancelled" if new_state == "cancelled" else "validation_error")
    assert preparation["recoverable"] is False and "local_failure" not in preparation
    assert "input_format_invalid" not in text


def test_prepared_bundle_takes_precedence_over_later_stale_failure(tmp_path, monkeypatch, capsys):
    runtime, args = automatic_setup(tmp_path, monkeypatch)
    code, completed, stderr = run_cli(capsys, args)
    assert code == 0 and stderr == ""
    store, workspace = Store(tmp_path / "home/state.db"), Path(completed["workspace"])
    start = observations(store, completed["run_id"])[0]["payload"]
    store.append_event(completed["run_id"], "bundle_preparation_failed", {
        **start, "schema_version": "2", "status": "failed", "stage": "compiler_preflight",
        "error_category": "validation_error",
        "local_failure": EvaluatorPreparationDiagnostic(
            "compiler_preflight", "input_format_invalid", probe_index=1, input_index=1,
        ).to_dict(),
    })
    preparation, _ = check_status(tmp_path, capsys, runtime, store, completed, workspace)
    assert preparation == {
        "schema_version": "1", "parent_run_id": completed["run_id"], "attempt_id": None,
        "status": "prepared", "stage": "profile_publish", "error_category": None, "recoverable": False,
    }


@pytest.mark.parametrize("source", ["dictionary", "attribute", "typed_runtime_exception"])
def test_runtime_cannot_supply_local_diagnostic(tmp_path, monkeypatch, capsys, source):
    runtime, args = automatic_setup(tmp_path, monkeypatch)
    original = runtime.run
    detail = EvaluatorPreparationDiagnostic("compiler_response", "response_invalid")

    def run(prompt, workspace, timeout=None):
        if "frozen local evaluator bundle" not in prompt:
            return original(prompt, workspace, timeout)
        if source == "dictionary":
            return {"diagnostic": {
                **detail.to_dict(), "stage": "auditor_preflight", "reason": PRIVATE,
            }, "text": PRIVATE}
        if source == "attribute":
            error = RuntimeError(PRIVATE)
            error.diagnostic = detail
            error.local_failure = detail.to_dict()
            raise error
        raise EvaluatorPreparationError(PRIVATE, detail)

    monkeypatch.setattr(runtime, "run", run)
    code, failed, stderr = run_cli(capsys, args)
    assert code == 1 and stderr == ""
    preparation = failed["evolution"]["preparation"]
    if source == "dictionary":
        # A non-RuntimeResult is independently rejected by the controller response boundary.
        assert preparation["local_failure"] == detail.to_dict()
        assert preparation["recoverable"] is False
    else:
        assert preparation["schema_version"] == "1"
        assert preparation["error_category"] == "runtime_error" and preparation["recoverable"] is True
        assert "local_failure" not in preparation
    records = observations(Store(tmp_path / "home/state.db"), failed["run_id"])
    assert PRIVATE not in json.dumps([failed, records])
    assert runtime.generator_calls == 0


@pytest.mark.parametrize("source", ["dict_attribute", "typed_attribute", "subclass", "mutated_typed"])
def test_generic_or_malformed_exception_attributes_are_not_diagnostic_authority(
    tmp_path, monkeypatch, capsys, source,
):
    runtime, args = automatic_setup(tmp_path, monkeypatch)
    detail = EvaluatorPreparationDiagnostic("compiler_response", "response_invalid")

    class DerivedPreparationError(EvaluatorPreparationError):
        pass

    def compile_failure(*args, **kwargs):
        if source == "subclass":
            raise DerivedPreparationError(PRIVATE, detail)
        if source == "mutated_typed":
            error = EvaluatorPreparationError(PRIVATE, detail)
            error.diagnostic = {**detail.to_dict(), "reason": PRIVATE}
        else:
            error = RuntimeError(PRIVATE)
            error.diagnostic = detail if source == "typed_attribute" else detail.to_dict()
        raise error

    monkeypatch.setattr(automatic, "compile_evaluator_bundle", compile_failure)
    code, failed, stderr = run_cli(capsys, args)
    assert code == 1 and stderr == ""
    preparation = failed["evolution"]["preparation"]
    assert preparation["schema_version"] == "1" and preparation["stage"] == "preparation"
    assert preparation["error_category"] == "validation_error" and preparation["recoverable"] is False
    assert "local_failure" not in preparation
    records = observations(Store(tmp_path / "home/state.db"), failed["run_id"])
    assert PRIVATE not in json.dumps([failed, records])
    assert runtime_calls(runtime) == (1, 0, 0, 0, 1)


def test_new_interrupted_attempt_does_not_inherit_prior_local_failure(tmp_path, monkeypatch, capsys):
    runtime, failed, store, workspace = failed_run(tmp_path, monkeypatch, capsys)
    previous_start = observations(store, failed["run_id"])[0]["payload"]
    store.append_event(failed["run_id"], "bundle_preparation_started", {
        **previous_start, "attempt_id": "preparation-" + "a" * 32,
        "local_failure": {"reason": PRIVATE},
    })
    preparation, text = check_status(tmp_path, capsys, runtime, store, failed, workspace)
    assert preparation["status"] == "unknown" and preparation["error_category"] == "interrupted"
    assert preparation["recoverable"] is False and "local_failure" not in preparation
    assert "input_format_invalid" not in text


@pytest.mark.parametrize("role", ["compiler", "auditor"])
def test_explicit_continuation_after_local_response_failure_remains_compatible(
    tmp_path, monkeypatch, capsys, role,
):
    runtime, args = automatic_setup(tmp_path, monkeypatch)
    original = runtime.run
    marker = "frozen local evaluator bundle" if role == "compiler" else "adversarial evaluator auditor"

    def malformed(prompt, workspace, timeout=None):
        result = original(prompt, workspace, timeout)
        return RuntimeResult("not JSON " + PRIVATE) if marker in prompt else result

    monkeypatch.setattr(runtime, "run", malformed)
    code, failed, stderr = run_cli(capsys, args)
    assert code == 1 and stderr == ""
    assert failed["evolution"]["preparation"]["local_failure"]["stage"] == role + "_response"
    assert failed["evolution"]["preparation"]["recoverable"] is False
    assert runtime.generator_calls == 0
    monkeypatch.setattr(runtime, "run", original)
    code, recovered, stderr = run_cli(capsys, followup(tmp_path, failed["run_id"]))
    assert code == 0 and stderr == "" and recovered["status"] == "succeeded"
    assert recovered["evolution"]["result"]["best_score"] == 9
    assert recovered["evolution"]["preparation"]["status"] == "prepared"
    assert "local_failure" not in recovered["evolution"]["preparation"]
    assert runtime_calls(runtime) == (1, 2, 1 + int(role == "auditor"), 4, 4 + int(role == "auditor"))
    store, workspace = Store(tmp_path / "home/state.db"), Path(recovered["workspace"])
    before, calls = snapshot(store, failed["run_id"], workspace), runtime_calls(runtime)
    code, repeated, stderr = run_cli(capsys, followup(tmp_path, failed["run_id"]))
    assert code == 0 and stderr == "" and repeated["evolution"] == recovered["evolution"]
    assert snapshot(store, failed["run_id"], workspace) == before and runtime_calls(runtime) == calls
