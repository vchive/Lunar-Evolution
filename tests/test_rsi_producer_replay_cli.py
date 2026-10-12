from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from lunar_evolution.algorithm import AlgorithmProblemContract
from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.cli import main
from lunar_evolution.official_evaluator_evidence import (
    OfficialEvaluationReceipt,
    OfficialEvaluatorProfile,
)
from lunar_evolution.producer_handoff import ProducerMaterial, ProducerResultEnvelope
from lunar_evolution.rsi_gateway import SolverRequest
from lunar_evolution.rsi_learning import EMPTY_MEMORY_SNAPSHOT
from lunar_evolution.rsi_native_candidate import (
    NativeCandidateRecord,
    NativeEvaluationReceipt,
    NativeExecutionReceipt,
    NativePublicationReceipt,
)

HEX = "a" * 64
PRODUCER = "b" * 64
EVALUATOR = "c" * 64
ENVIRONMENT = "d" * 64
SOURCE = b"def solve():\n    return 3\n"


def _contract() -> AlgorithmProblemContract:
    return AlgorithmProblemContract.from_dict({
        "schema_version": "1", "problem_id": "replay-fixture", "problem_type": "routing",
        "statement": "Find a route.", "inputs": [{"path": "items.csv", "format": "csv", "fields": {"id": "item id"}}],
        "decision_variables": ["route"], "objective": {"name": "quality", "direction": "maximize"},
        "hard_constraints": [], "soft_constraints": [], "success_criteria": ["All items are served."],
        "deliverables": ["route source"], "evolution": {"strategy": "population", "max_rounds": 1, "stagnation_rounds": 1},
    })


def _write(path: Path, value: object) -> str:
    raw = canonical_json(value, maximum=1024 * 1024)
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _fixture(tmp_path: Path, *, solver: str = "openevolve") -> dict[str, object]:
    contract = _contract()
    contract_raw = contract.to_dict()
    contract_path = tmp_path / "contract.json"
    contract_pin = _write(contract_path, contract_raw)
    root = tmp_path / "producer"
    root.mkdir()
    source_path = root / "candidate.py"
    source_path.write_bytes(SOURCE)
    source_sha = hashlib.sha256(SOURCE).hexdigest()
    envelope = ProducerResultEnvelope(
        schema_version="1", producer_id=solver, producer_fingerprint=PRODUCER,
        status="completed", contract_sha256=contract.digest(), budget={"iterations": 1},
        materials=(ProducerMaterial("candidate_source", "candidate.py", len(SOURCE), source_sha),),
        producer_run_id="replay-run",
    )
    envelope_pin = _write(root / "producer-result.json", envelope.to_dict())
    request = SolverRequest.build(
        episode_id="replay-episode", contract_sha256=contract.digest(), evaluator_sha256=EVALUATOR,
        environment_sha256=ENVIRONMENT, memory_snapshot_sha256=EMPTY_MEMORY_SNAPSHOT.digest(), solver_id=solver,
    )
    request_path = tmp_path / "request.json"
    request_pin = _write(request_path, request.to_dict())
    memory_path = tmp_path / "memory.json"
    memory_pin = _write(memory_path, EMPTY_MEMORY_SNAPSHOT.to_dict())
    common = {
        "candidate_id": "candidate-1", "request_sha256": request.digest(),
        "contract_sha256": contract.digest(), "evaluator_sha256": EVALUATOR,
        "environment_sha256": ENVIRONMENT,
        "memory_snapshot_sha256": EMPTY_MEMORY_SNAPSHOT.digest(),
    }
    candidate = NativeCandidateRecord(**common, candidate_receipt_sha256=HEX, candidate_source_sha256=source_sha)
    execution = NativeExecutionReceipt(**common, receipt_sha256="e" * 64, trace_digest="f" * 64)
    evaluation = NativeEvaluationReceipt(**common, receipt_sha256="1" * 64)
    publication = NativePublicationReceipt(**common, receipt_sha256="2" * 64)
    profile = OfficialEvaluatorProfile(
        "replay-evaluator", "1", EVALUATOR, "3" * 64, contract.digest(), "4" * 64, "5" * 64, "6" * 64,
    )
    official = OfficialEvaluationReceipt(
        profile, request.digest(), source_sha, execution.receipt_sha256, publication.receipt_sha256,
        "pass", evaluation.receipt_sha256,
    )
    receipts = {
        "candidate": candidate.to_dict(), "execution": execution.to_dict(),
        "evaluation": evaluation.to_dict(), "publication": publication.to_dict(),
        "official_evaluator_receipt": official.to_dict(), "worker_terminal_status": "completed",
        "provenance_sha256": "7" * 64,
    }
    receipts_path = tmp_path / "receipts.json"
    receipts_pin = _write(receipts_path, receipts)
    return {
        "root": root, "contract": contract_path, "request": request_path, "memory": memory_path,
        "receipts": receipts_path, "solver": solver, "contract_pin": contract_pin,
        "envelope_pin": envelope_pin, "request_pin": request_pin, "memory_pin": memory_pin,
        "receipts_pin": receipts_pin, "producer": PRODUCER, "receipts_value": receipts,
    }


def _args(case: dict[str, object], home: Path | None = None) -> list[str]:
    args = [
        "rsi", "replay", str(case["root"]), "--contract", str(case["contract"]),
        "--request", str(case["request"]), "--memory-snapshot", str(case["memory"]),
        "--receipts", str(case["receipts"]), "--solver", str(case["solver"]),
        "--producer-fingerprint", str(case["producer"]), "--contract-sha256", str(case["contract_pin"]),
        "--request-sha256", str(case["request_pin"]), "--memory-sha256", str(case["memory_pin"]),
        "--receipts-sha256", str(case["receipts_pin"]), "--envelope-sha256", str(case["envelope_pin"]), "--json",
    ]
    if home is not None:
        args.extend(["--home", str(home)])
    return args


@pytest.mark.parametrize("solver", ["openevolve", "shinka"])
def test_matching_replay_is_read_only_and_maps_existing_solver_result(tmp_path: Path, capsys, solver: str) -> None:
    case = _fixture(tmp_path, solver=solver)
    before = {path: path.read_bytes() for path in (case["contract"], case["request"], case["memory"], case["receipts"], case["root"] / "producer-result.json", case["root"] / "candidate.py")}
    home = tmp_path / "home"
    assert main(_args(case, home)) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "completed" and payload["production_admission"] is False
    assert payload["result"]["status"] == "completed"
    assert not home.exists()
    assert {path: path.read_bytes() for path in before} == before


def test_missing_terminal_is_unknown_without_controller_or_writes(tmp_path: Path, capsys) -> None:
    case = _fixture(tmp_path)
    value = dict(case["receipts_value"])
    value.pop("worker_terminal_status")
    case["receipts_pin"] = _write(case["receipts"], value)
    assert main(_args(case)) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "unknown" and payload["result"] is None


def test_binding_drift_is_refused_without_execution(tmp_path: Path, capsys) -> None:
    case = _fixture(tmp_path)
    value = dict(case["receipts_value"])
    candidate = dict(value["candidate"])
    candidate["request_sha256"] = "8" * 64
    value["candidate"] = candidate
    case["receipts_pin"] = _write(case["receipts"], value)
    assert main(_args(case)) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "drifted"


def test_missing_receipts_is_fixed_unknown_and_does_not_create_home(tmp_path: Path, capsys) -> None:
    case = _fixture(tmp_path)
    case["receipts"] = tmp_path / "missing.json"
    assert main(_args(case)) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "unknown"


def test_rsi_run_fixture_backend_is_explicitly_marked_non_production(tmp_path: Path, capsys) -> None:
    case = _fixture(tmp_path)
    home = tmp_path / "fixture-home"
    assert main([
        "rsi", "run", str(case["contract"]), "--solver", "openevolve", "--run-id", "fixture-run",
        "--home", str(home), "--json",
    ]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["solver_execution"] == "provider_free_fixture"
    assert payload["production_admission"] is False
    assert payload["producer_replay_required"] is True
    assert payload["warning"] == "rsi_producer_replay_required"
