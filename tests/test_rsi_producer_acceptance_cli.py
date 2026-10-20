from __future__ import annotations

import json
from pathlib import Path

import pytest

from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.cli import main
from lunar_evolution.python_producer_lifecycle import build_python_producer_terminal
from lunar_evolution.rsi_producer_acceptance import (
    ProducerAcceptanceEnvelopeError,
    build_producer_acceptance_envelope,
)
from lunar_evolution.rsi_project_lifecycle import (
    PROJECT_LIFECYCLE_PROTOCOL,
    preflight_project_lifecycle,
)

D = "a" * 64


def _profile(**changes: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "1",
        "protocol": PROJECT_LIFECYCLE_PROTOCOL,
        "producer_id": "openevolve",
        "project_id": "demo-project",
        "entrypoint": "project/main.py",
        "source_sha256": D,
        "runtime_sha256": "b" * 64,
        "toolchain_sha256": "c" * 64,
        "request_schema_sha256": "d" * 64,
        "result_schema_sha256": "e" * 64,
        "launch_mode": "native_bootstrap",
        "cancel_mode": "owner_group",
        "resume_mode": "retained_read_only",
    }
    value.update(changes)
    return value


def _terminal(*, status: str = "completed", **changes: object):
    value: dict[str, object] = {
        "binding_sha256": D,
        "run_id": "run-1",
        "journal_id": "journal-1",
        "launch_id": "launch-1",
        "process_registration_sha256": D if status == "completed" else None,
        "owner_identity_sha256": D if status == "completed" else None,
        "executable_sha256": D if status == "completed" else None,
        "executable_size": 10 if status == "completed" else None,
        "executable_device": 1 if status == "completed" else None,
        "executable_inode": 2 if status == "completed" else None,
        "started_unix": 10.0,
        "released_unix": 11.0 if status == "completed" else None,
        "exited_unix": 12.0 if status == "completed" else None,
        "deadline_unix": 100.0,
        "status": status,
        "exit_code": 0 if status == "completed" else None,
        "signal": None,
        "cleanup_status": "cleaned" if status == "completed" else "missing",
        "request_journal_sha256": D if status == "completed" else None,
        "request_count": 1 if status == "completed" else 0,
        "stdout_sha256": D,
        "stderr_sha256": D,
        "publication_eligible": False,
    }
    value.update(changes)
    return build_python_producer_terminal(**value)


def _write(path: Path, value: object) -> bytes:
    raw = canonical_json(value)
    path.write_bytes(raw)
    return raw


def _write_inputs(tmp_path: Path, *, terminal_status: str = "completed") -> tuple[Path, Path]:
    profile_path = tmp_path / "profile.json"
    terminal_path = tmp_path / "terminal.json"
    _write(profile_path, _profile())
    terminal_path.write_bytes(_terminal(status=terminal_status).to_json())
    return profile_path, terminal_path


def test_acceptance_cli_composes_retained_evidence_but_stays_blocked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile_path, terminal_path = _write_inputs(tmp_path)
    monkeypatch.setattr("lunar_evolution.cli._config", lambda _args: pytest.fail("state initialized"))
    exit_code = main([
        "rsi", "producer-acceptance", str(profile_path), str(terminal_path),
        "--binding-sha256", D, "--json",
    ])
    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "blocked"
    assert payload["reason"] == "runtime_acceptance_required"
    assert payload["terminal_status"] == "completed"
    assert "retained_replay_completed" in payload["missing_gates"]
    assert payload["execution_performed"] is False
    assert payload["evaluator_invoked"] is False
    assert payload["production_admission"] is False
    assert payload["online_publication"] is False
    assert not (tmp_path / ".lunar-evolution").exists()


def test_unknown_terminal_keeps_reconcile_gate(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    profile_path, terminal_path = _write_inputs(tmp_path, terminal_status="unknown")
    assert main([
        "rsi", "producer-acceptance", str(profile_path), str(terminal_path),
        "--binding-sha256", D, "--json",
    ]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["terminal_status"] == "unknown"
    assert "terminal_reconcile" in payload["missing_gates"]


@pytest.mark.parametrize("cleanup_status", ["unknown", "missing"])
def test_known_terminal_with_unresolved_cleanup_is_rejected(
    tmp_path: Path, cleanup_status: str,
) -> None:
    """A detached terminal cannot turn uncertain owner cleanup into acceptance."""
    profile_path, terminal_path = _write_inputs(tmp_path)
    retained = json.loads(terminal_path.read_bytes())
    terminal = {
        "status": "completed", "reason": "retained_terminal_valid",
        "terminal_sha256": retained["terminal_sha256"], "binding_sha256": D,
        "run_id": "run-1", "journal_id": "journal-1", "launch_id": "launch-1",
        "cleanup_status": cleanup_status, "request_count": 1,
        "reconcile_required": False, "read_only": True,
        "evidence_scope": "retained_python_terminal",
        "production_admission": False, "online_publication": False,
    }
    with pytest.raises(ProducerAcceptanceEnvelopeError, match="terminal_cleanup_unverified"):
        build_producer_acceptance_envelope(
            preflight_project_lifecycle(profile_path), terminal,
        )


def test_terminal_cleanup_label_is_closed_before_composition(tmp_path: Path) -> None:
    profile_path, terminal_path = _write_inputs(tmp_path)
    retained = json.loads(terminal_path.read_bytes())
    terminal = {
        "status": "completed", "reason": "retained_terminal_valid",
        "terminal_sha256": retained["terminal_sha256"], "binding_sha256": D,
        "run_id": "run-1", "journal_id": "journal-1", "launch_id": "launch-1",
        "cleanup_status": "cleanup_unverified", "request_count": 1,
        "reconcile_required": False, "read_only": True,
        "evidence_scope": "retained_python_terminal",
        "production_admission": False, "online_publication": False,
    }
    with pytest.raises(ProducerAcceptanceEnvelopeError, match="terminal_cleanup_invalid"):
        build_producer_acceptance_envelope(
            preflight_project_lifecycle(profile_path), terminal,
        )


def test_completed_replay_removes_only_replay_gate(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    profile_path, terminal_path = _write_inputs(tmp_path)
    replay_path = tmp_path / "replay.json"
    _write(replay_path, {
        "status": "completed", "evidence_scope": "retained_local_comparison",
        "read_only": True, "production_admission": False,
    })
    assert main([
        "rsi", "producer-acceptance", str(profile_path), str(terminal_path),
        "--binding-sha256", D, "--replay-report", str(replay_path), "--json",
    ]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["replay_status"] == "completed"
    assert "retained_replay_completed" not in payload["missing_gates"]
    assert payload["production_admission"] is False


@pytest.mark.parametrize("option", ["--binding-sha256", "--deadline-unix"])
def test_terminal_binding_or_deadline_drift_fails_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], option: str,
) -> None:
    profile_path, terminal_path = _write_inputs(tmp_path)
    value = "b" * 64 if option == "--binding-sha256" else "101"
    extra = ["--binding-sha256", D] if option == "--deadline-unix" else []
    assert main([
        "rsi", "producer-acceptance", str(profile_path), str(terminal_path),
        "--binding-sha256", D, option, value, *extra, "--json",
    ]) == 2
    assert "python_producer" in capsys.readouterr().err


def test_replay_authority_or_scope_drift_fails_closed(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    profile_path, terminal_path = _write_inputs(tmp_path)
    replay_path = tmp_path / "replay.json"
    _write(replay_path, {
        "status": "completed", "evidence_scope": "wrong",
        "read_only": True, "production_admission": True,
    })
    assert main([
        "rsi", "producer-acceptance", str(profile_path), str(terminal_path),
        "--binding-sha256", D, "--replay-report", str(replay_path), "--json",
    ]) == 2
    assert "rsi_producer_acceptance_replay" in capsys.readouterr().err


@pytest.mark.parametrize(
    "change",
    [
        {"extra": "ignored"},
        {"status": ["completed"]},
        {"evidence_scope": {"value": "retained_local_comparison"}},
    ],
)
def test_replay_report_schema_is_closed_and_types_are_fixed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], change: dict[str, object],
) -> None:
    profile_path, terminal_path = _write_inputs(tmp_path)
    replay_path = tmp_path / "replay.json"
    replay = {
        "status": "completed", "evidence_scope": "retained_local_comparison",
        "read_only": True, "production_admission": False,
    }
    replay.update(change)
    _write(replay_path, replay)
    assert main([
        "rsi", "producer-acceptance", str(profile_path), str(terminal_path),
        "--binding-sha256", D, "--replay-report", str(replay_path), "--json",
    ]) == 2
    assert "rsi_producer_acceptance_replay" in capsys.readouterr().err


def test_envelope_authority_mutation_and_digest_roundtrip(tmp_path: Path) -> None:
    profile_path, _terminal_path = _write_inputs(tmp_path)
    profile = preflight_project_lifecycle(profile_path)
    terminal = json.loads(_terminal().to_json())
    envelope = build_producer_acceptance_envelope(profile, {
        "status": "completed", "reason": "retained_terminal_valid",
        "terminal_sha256": terminal["terminal_sha256"], "binding_sha256": D,
        "run_id": "run-1", "journal_id": "journal-1", "launch_id": "launch-1",
        "cleanup_status": "cleaned", "request_count": 1, "reconcile_required": False,
        "read_only": True, "evidence_scope": "retained_python_terminal",
        "production_admission": False, "online_publication": False,
    })
    assert envelope.from_dict(envelope.to_dict()).digest() == envelope.digest()
    with pytest.raises(ProducerAcceptanceEnvelopeError, match="authority_invalid"):
        build_producer_acceptance_envelope(profile | {"production_admission": True}, {
            "status": "completed", "reason": "retained_terminal_valid",
            "terminal_sha256": terminal["terminal_sha256"], "binding_sha256": D,
            "run_id": "run-1", "journal_id": "journal-1", "launch_id": "launch-1",
            "cleanup_status": "cleaned", "request_count": 1, "reconcile_required": False,
            "read_only": True, "evidence_scope": "retained_python_terminal",
            "production_admission": False, "online_publication": False,
        })
