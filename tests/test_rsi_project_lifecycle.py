from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from lunar_evolution.candidate_evaluation_spec import canonical_json
from lunar_evolution.cli import main
from lunar_evolution.rsi_project_lifecycle import (
    PROJECT_LIFECYCLE_PROTOCOL,
    ProjectLifecyclePreflightError,
    ProjectLifecycleProfile,
    preflight_project_lifecycle,
)

H = "a" * 64


def _profile(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "schema_version": "1",
        "protocol": PROJECT_LIFECYCLE_PROTOCOL,
        "producer_id": "openevolve",
        "project_id": "demo-project",
        "entrypoint": "project/main.py",
        "source_sha256": H,
        "runtime_sha256": "b" * 64,
        "toolchain_sha256": "c" * 64,
        "request_schema_sha256": "d" * 64,
        "result_schema_sha256": "e" * 64,
        "launch_mode": "native_bootstrap",
        "cancel_mode": "owner_group",
        "resume_mode": "retained_read_only",
    }
    value.update(overrides)
    return value


def _write_profile(path: Path, value: dict[str, object], *, canonical: bool = True) -> bytes:
    raw = canonical_json(value) if canonical else json.dumps(value).encode()
    path.write_bytes(raw)
    return raw


def test_profile_roundtrip_and_digest() -> None:
    profile = ProjectLifecycleProfile.from_dict(_profile())
    assert profile.producer_id == "openevolve"
    assert profile.entrypoint == "project/main.py"
    assert len(profile.digest()) == 64
    assert ProjectLifecycleProfile.from_dict(profile.to_dict()) == profile


def test_preflight_is_fail_closed_and_never_admits_runtime(tmp_path: Path) -> None:
    path = tmp_path / "profile.json"
    raw = _write_profile(path, _profile())
    result = preflight_project_lifecycle(
        path, expected_profile_sha256=hashlib.sha256(raw).hexdigest(),
    )
    assert result["status"] == "blocked"
    assert result["reason"] == "runtime_acceptance_required"
    assert result["execution_performed"] is False
    assert result["evaluator_invoked"] is False
    assert result["production_admission"] is False
    assert result["online_publication"] is False
    assert result["missing_gates"]


def test_preflight_rejects_digest_drift_before_returning_report(tmp_path: Path) -> None:
    path = tmp_path / "profile.json"
    _write_profile(path, _profile())
    with pytest.raises(ProjectLifecyclePreflightError, match="profile_digest_drift"):
        preflight_project_lifecycle(path, expected_profile_sha256="f" * 64)


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("producer_id", "unknown", "producer_invalid"),
        ("entrypoint", "../main.py", "entrypoint_invalid"),
        ("launch_mode", "shell", "launch_mode_invalid"),
        ("cancel_mode", "cooperative", "cancel_mode_invalid"),
        ("resume_mode", "retry", "resume_mode_invalid"),
    ],
)
def test_profile_rejects_unsafe_lifecycle_declarations(field: str, value: str, code: str) -> None:
    with pytest.raises(ProjectLifecyclePreflightError, match=code):
        ProjectLifecycleProfile.from_dict(_profile(**{field: value}))


def test_cli_preflight_does_not_initialize_home(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    profile_path = tmp_path / "profile.json"
    _write_profile(profile_path, _profile())
    home = tmp_path / "should-not-exist"
    exit_code = main([
        "rsi", "project-preflight", str(profile_path), "--home", str(home), "--json",
    ])
    assert exit_code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "blocked"
    assert payload["evidence_scope"] == "detached_profile_preflight"
    assert not home.exists()
