from __future__ import annotations

import json
from pathlib import Path

from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.cli import main
from lunar_evolution.producer_lifecycle_diagnostics import LIFECYCLE_PHASES


def _phase(outcome: str = "completed", **overrides: bool) -> dict[str, object]:
    value: dict[str, object] = {
        "outcome": outcome,
        "owner_verified": True,
        "terminal_persisted": True,
        "cleanup_verified": True,
        "recovery_read_only": True,
        "relaunch_performed": False,
        "execution_performed": False,
    }
    value.update(overrides)
    return value


def _observations() -> dict[str, dict[str, object]]:
    return {
        "startup": _phase(),
        "cancellation": _phase("cancelled"),
        "timeout": _phase("timeout"),
        "parent_loss": _phase("unknown", terminal_persisted=False),
        "cleanup": _phase(),
        "restart_recovery": _phase("unknown", terminal_persisted=False),
    }


def test_cli_projects_complete_observations_without_initializing_home(
    tmp_path: Path, capsys,
) -> None:
    observations_path = tmp_path / "observations.json"
    observations_path.write_bytes(canonical_json(_observations()))
    home = tmp_path / "unused-home"
    assert main([
        "rsi", "producer-lifecycle-diagnostics", str(observations_path),
        "--home", str(home), "--json",
    ]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "offline_verified"
    assert payload["missing_phases"] == []
    assert payload["production_admission"] is False
    assert payload["online_publication"] is False
    assert not home.exists()


def test_cli_returns_blocked_for_missing_phase_and_preserves_fixed_shape(
    tmp_path: Path, capsys,
) -> None:
    observations = _observations()
    del observations["parent_loss"]
    observations_path = tmp_path / "observations.json"
    observations_path.write_bytes(canonical_json(observations))
    assert main([
        "rsi", "producer-lifecycle-diagnostics", str(observations_path), "--json",
    ]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "blocked"
    assert payload["missing_phases"] == ["parent_loss"]
    assert set(payload["phase_status"]) == set(LIFECYCLE_PHASES)
    assert payload["execution_performed"] is False
    assert payload["production_admission"] is False


def test_cli_rejects_noncanonical_observations_before_home_initialization(
    tmp_path: Path, capsys,
) -> None:
    observations_path = tmp_path / "observations.json"
    observations_path.write_text(json.dumps(_observations(), indent=2), encoding="utf-8")
    home = tmp_path / "must-not-exist"
    assert main([
        "rsi", "producer-lifecycle-diagnostics", str(observations_path),
        "--home", str(home), "--json",
    ]) == 2
    assert "invalid" in capsys.readouterr().err
    assert not home.exists()

