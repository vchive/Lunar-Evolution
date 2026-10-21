from __future__ import annotations

import json

import pytest

import lunar_evolution as lunar
from lunar_evolution.producer_lifecycle_diagnostics import build_producer_lifecycle_diagnostic
from lunar_evolution.project_entrypoint_descriptor import (
    ProjectEntrypointDescriptorError,
    build_project_entrypoint_descriptor,
    compose_project_entrypoint_lifecycle,
    parse_project_entrypoint_descriptor,
    parse_project_entrypoint_lifecycle,
)
from lunar_evolution.rsi_project_lifecycle import (
    PROJECT_LIFECYCLE_PROTOCOL,
    ProjectLifecycleProfile,
)

H = "a" * 64


def test_public_package_exports_descriptor_contract() -> None:
    for name in (
        "ProjectEntrypointDescriptor", "ProjectEntrypointDescriptorError",
        "build_project_entrypoint_descriptor", "compose_project_entrypoint_lifecycle",
        "parse_project_entrypoint_descriptor", "parse_project_entrypoint_lifecycle",
    ):
        assert name in lunar.__all__
        assert getattr(lunar, name)


def _profile(**overrides: object) -> ProjectLifecycleProfile:
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
    return ProjectLifecycleProfile.from_dict(value)


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


def _lifecycle() -> dict[str, object]:
    return build_producer_lifecycle_diagnostic({
        "startup": _phase(),
        "cancellation": _phase("cancelled"),
        "timeout": _phase("timeout"),
        "parent_loss": _phase("unknown", terminal_persisted=False),
        "cleanup": _phase(),
        "restart_recovery": _phase("unknown", terminal_persisted=False),
    })


def test_descriptor_binds_canonical_profile_and_roundtrips() -> None:
    profile = _profile()
    descriptor = build_project_entrypoint_descriptor(profile, profile_sha256=profile.digest())
    parsed = parse_project_entrypoint_descriptor(descriptor.to_json())
    assert parsed == descriptor
    assert parsed.argv == (profile.entrypoint,)
    assert parsed.to_dict()["descriptor_sha256"] == parsed.digest()


def test_descriptor_rejects_profile_pin_drift() -> None:
    profile = _profile()
    with pytest.raises(ProjectEntrypointDescriptorError, match="profile_digest_drift"):
        build_project_entrypoint_descriptor(profile, profile_sha256="9" * 64)


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("entrypoint", "../main.py", "entrypoint_invalid"),
        ("entrypoint", "project//main.py", "entrypoint_invalid"),
        ("working_directory", "a/./b", "working_directory_invalid"),
        ("request_filename", "nested/request.json", "result_filename_invalid"),
        ("argv", ["python", "-c", "print(1)"], "argv_invalid"),
    ],
)
def test_descriptor_rejects_open_ended_or_escaping_launch_fields(
    field: str, value: object, code: str,
) -> None:
    profile = _profile()
    descriptor = build_project_entrypoint_descriptor(profile, profile_sha256=profile.digest())
    wire = descriptor.to_dict()
    wire[field] = value
    wire["descriptor_sha256"] = descriptor.digest()
    with pytest.raises(ProjectEntrypointDescriptorError, match=code):
        parse_project_entrypoint_descriptor(wire)


def test_descriptor_parser_rejects_duplicate_and_noncanonical_json() -> None:
    with pytest.raises(ProjectEntrypointDescriptorError, match="duplicate_json_key"):
        parse_project_entrypoint_descriptor(b'{"schema_version":"1","schema_version":"1"}')
    profile = _profile()
    descriptor = build_project_entrypoint_descriptor(profile, profile_sha256=profile.digest())
    with pytest.raises(ProjectEntrypointDescriptorError, match="noncanonical_json"):
        parse_project_entrypoint_descriptor(json.dumps(descriptor.to_dict(), indent=2))


def test_composition_binds_profile_entrypoint_and_retained_lifecycle_but_stays_blocked() -> None:
    profile = _profile()
    descriptor = build_project_entrypoint_descriptor(profile, profile_sha256=profile.digest())
    report = compose_project_entrypoint_lifecycle(profile, descriptor, _lifecycle())
    assert report["status"] == "blocked"
    assert report["reason"] == "runtime_acceptance_required"
    assert report["descriptor_verified"] is True
    assert report["lifecycle_status"] == "offline_verified"
    assert report["missing_gates"] == [
        "accepted_runtime_profile", "trusted_project_entrypoint", "linux_acceptance_matrix",
    ]
    assert report["production_admission"] is False
    assert report["online_publication"] is False
    assert report["evaluator_invoked"] is False
    assert parse_project_entrypoint_lifecycle(report) == report


def test_composition_refuses_descriptor_or_profile_drift() -> None:
    profile = _profile()
    descriptor = build_project_entrypoint_descriptor(profile, profile_sha256=profile.digest())
    changed = _profile(project_id="other-project")
    with pytest.raises(ProjectEntrypointDescriptorError, match="profile_descriptor_drift"):
        compose_project_entrypoint_lifecycle(changed, descriptor, _lifecycle())

    wire = descriptor.to_dict()
    wire["entrypoint"] = "project/other.py"
    wire["argv"] = ["project/other.py"]
    wire["descriptor_sha256"] = "0" * 64
    with pytest.raises(ProjectEntrypointDescriptorError, match="descriptor_digest_invalid"):
        compose_project_entrypoint_lifecycle(profile, wire, _lifecycle())


def test_composition_refuses_modified_or_incomplete_lifecycle_report() -> None:
    profile = _profile()
    descriptor = build_project_entrypoint_descriptor(profile, profile_sha256=profile.digest())
    lifecycle = _lifecycle()
    lifecycle["production_admission"] = True
    with pytest.raises(ProjectEntrypointDescriptorError, match="lifecycle_invalid"):
        compose_project_entrypoint_lifecycle(profile, descriptor, lifecycle)

    incomplete = build_producer_lifecycle_diagnostic({"startup": _phase()})
    report = compose_project_entrypoint_lifecycle(profile, descriptor, incomplete)
    assert report["status"] == "blocked"
    assert report["lifecycle_status"] == "blocked"
    assert "runtime_lifecycle_acceptance" in report["missing_gates"]
    assert report["production_admission"] is False


