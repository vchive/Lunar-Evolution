"""Worker-view history candidates remain unaccepted, without process execution.

The existing synthetic retained fixture doubles custody. Original recipe/report
reconstruction, historical FD reads, closure parsing and ELF checks stay real.
Actual summary/raw-owner validation belongs to the separate worker-view tests.
"""

from __future__ import annotations

import json

import pytest

from tests import test_static_python_retained_installation as retained_tests
from tests.test_static_python_retained_installation import rewrite_history, sha, write
from tools.static_python_rsi_fixture import build_dependency_consumer as consumer
from tools.static_python_rsi_fixture import podman_custody as custody
from tools.static_python_rsi_fixture import podman_vfs_lifetime as lifetime
from tools.static_python_rsi_fixture import retained_installation as candidate
from tools.static_python_rsi_fixture.runtime_closure import canonical

BACKEND = "podman-snapshots-source-data-vfs-worker-input-view-v1"
_REAL_VALIDATOR = custody.validate_custody_observation_v6
retained_history = retained_tests.history


@pytest.fixture
def worker_history(retained_history, monkeypatch):
    history = retained_history
    original_double = custody.validate_custody_observation_v4
    controls = history["controls"]
    controls["worker_observations"] = []

    def observation(command, planned, stage, index, recipe_sha256, environment, **options):
        controls["worker_observations"].append((stage, index, list(options["prior"])))
        original_double(command, planned, stage, index, recipe_sha256, environment, **options)

    monkeypatch.setattr(custody, "validate_custody_observation_v6", observation)
    options, build = history["options"], history["build"]
    report_raw, _outputs = consumer._report_outputs(
        build.execution_report, history["wire"], BACKEND, version4=True,
        workspace=options["workspace"], checkpoint=lambda: None,
        vfs_roots=True, vfs_retained=True, vfs_lifetime=True, vfs_worker_input_view=True,
    )
    write(options["workspace"], "report.json", report_raw)
    rewrite_history(history, "dependency-report.json", lambda row: row.update(
        schema="lunar-actual-build-dependency-consumer-v7", custody_backend=BACKEND,
        execution_report_sha256=sha(report_raw)))
    controls["observations"] = 0
    controls["worker_observations"].clear()
    return history


def prepare(history, **overrides):
    return candidate.prepare_worker_input_view_fixed_installation_description(
        history["build"], **{**history["options"], **overrides})


def snapshot(root):
    return {path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mode)
            for path in root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("retained_history", ["openevolve", "shinka"], indirect=True)
def test_worker_history_emits_only_existing_candidate_bytes_without_writes(worker_history):
    history = worker_history
    before = snapshot(history["options"]["workspace"])
    result = prepare(history)
    value = result.to_dict()
    assert type(result) is candidate.RetainedFixedInstallationDescription
    assert value["profile_version"] == "fixed-" + history["closure"]["solver"] + "-v1"
    assert value["image"]["mode"] == 0o711
    assert all(flag is False for flag in value["claims"].values())
    assert result.production_admission is result.online_publication is False
    assert result.dependency_report_sha256 == history["build"].evidence_sha256
    prior = []
    for stage, observed in zip(history["build"].execution_report.stage_evidence,
                               history["controls"]["worker_observations"], strict=True):
        assert observed == (stage["stage"], 0, prior)
        prior = [*prior, *stage["commands"][0]["outputs"]]
    assert snapshot(history["options"]["workspace"]) == before


def test_new_candidate_reader_refuses_original_retained_history(retained_history):
    with pytest.raises(candidate.RetainedInstallationDescriptionError):
        prepare(retained_history)


@pytest.mark.parametrize("reader", [candidate.prepare_retained_fixed_installation_description,
                                    candidate.prepare_lifetime_fixed_installation_description])
def test_older_candidate_readers_refuse_worker_view_history(worker_history, reader):
    with pytest.raises(candidate.RetainedInstallationDescriptionError):
        reader(worker_history["build"], **worker_history["options"])


@pytest.mark.parametrize("field,value", [
    ("schema", "lunar-actual-build-dependency-consumer-v5"),
    ("schema", "lunar-actual-build-dependency-consumer-v6"),
    ("custody_backend", "podman-snapshots-source-data-vfs-retained-v1"),
    ("custody_backend", "podman-snapshots-source-data-vfs-lifetime-v1"),
    ("execution_report_sha256", "a" * 64),
    ("driver_inputs_verified", True), ("installation_accepted", True),
])
def test_resigned_mixed_or_promoted_worker_dependency_history_refuses(worker_history, field, value):
    rewrite_history(worker_history, "dependency-report.json", lambda row: row.update({field: value}))
    with pytest.raises(candidate.RetainedInstallationDescriptionError):
        prepare(worker_history)


@pytest.mark.parametrize("version", [6, 7])
def test_original_execution_report_v8_is_required_even_with_resigned_dependency_pin(worker_history, version):
    root = worker_history["options"]["workspace"]
    report = json.loads((root / "report.json").read_bytes())
    report["schema"] = "lunar-static-python-build-execution-report-v" + str(version)
    raw = canonical(report)
    write(root, "report.json", raw)
    rewrite_history(worker_history, "dependency-report.json", lambda row: row.update(
        execution_report_sha256=sha(raw)))
    with pytest.raises(candidate.RetainedInstallationDescriptionError):
        prepare(worker_history)


def test_original_worker_summary_refusal_cannot_fall_back_to_older_history(worker_history, monkeypatch):
    history = worker_history
    first = history["build"].execution_report.stage_evidence[0]["commands"][0]
    first["custody"] = {
        "schema": "lunar-podman-build-command-observation-v6", "input_layout": BACKEND,
        "lifetime_profile": lifetime.WORKER_INPUT_SCHEMA,
        "worker_input_profile": lifetime.WORKER_INPUT_PROFILE,
        "runtime_policy": {"root_acquisition": {}, "execution_view": {},
                           "root_acquisition_sha256": "a" * 64},
        "container_id": "b" * 64, "image_id": "c" * 64,
        "vfs_lifetime": {"synthetic": True}, "vfs_snapshots": {"synthetic": True}, "operations": [],
    }
    seen = []

    def refuse_summary(*args, **options):
        seen.append(options)
        assert options["inputs"] == history["wire"]["inputs"] and options["prior"] == []
        args[-1]()  # The original checkpoint reaches the summary verifier.
        raise ValueError("original_worker_summary_refusal")

    monkeypatch.setattr(custody, "validate_custody_observation_v6", _REAL_VALIDATOR)
    monkeypatch.setattr(custody, "validate_custody_observation_v4", lambda *_args, **_options: None)
    monkeypatch.setattr(lifetime, "verify_worker_input_lifetime", refuse_summary)
    with pytest.raises(candidate.RetainedInstallationDescriptionError, match="_readback_or_description$"):
        prepare(history)
    assert len(seen) == 1


@pytest.mark.parametrize("control", ["deadline", "interrupted"])
def test_original_control_refusal_precedes_worker_history_readback(worker_history, control):
    worker_history["controls"].update(now=100.0 if control == "deadline" else 10.0,
                                      interrupt=control == "interrupted")
    with pytest.raises(candidate.RetainedInstallationDescriptionError, match="_" + control + "$"):
        prepare(worker_history)
    assert worker_history["controls"]["worker_observations"] == []


@pytest.mark.parametrize("pin", ["expected_dependency_report_sha256", "expected_runtime_closure_sha256"])
def test_original_external_pins_precede_worker_observation_validation(worker_history, pin):
    with pytest.raises(candidate.RetainedInstallationDescriptionError):
        prepare(worker_history, **{pin: "a" * 64})
    assert worker_history["controls"]["worker_observations"] == []


def test_original_second_readback_still_rejects_output_drift(worker_history, monkeypatch):
    original_read = candidate._read
    changed = False

    def read(root, path, *args, **options):
        nonlocal changed
        result = original_read(root, path, *args, **options)
        if path.startswith("bin/lunar-") and not changed:
            changed = True
            output = next(row for row in worker_history["outputs"] if not row["executable"])
            target = worker_history["options"]["workspace"] / "work" / output["path"]
            target.write_bytes(target.read_bytes() + b"drift")
        return result

    monkeypatch.setattr(candidate, "_read", read)
    with pytest.raises(candidate.RetainedInstallationDescriptionError):
        prepare(worker_history)
    assert changed


def test_worker_candidate_bytes_match_existing_lifetime_reader_with_separate_history_pin(worker_history, monkeypatch):
    history = worker_history
    current = prepare(history)
    monkeypatch.setattr(custody, "validate_custody_observation_v5", custody.validate_custody_observation_v4)
    report_raw, _outputs = consumer._report_outputs(
        history["build"].execution_report, history["wire"], candidate._LIFETIME_BACKEND, version4=True,
        workspace=history["options"]["workspace"], checkpoint=lambda: None,
        vfs_roots=True, vfs_retained=True, vfs_lifetime=True,
    )
    write(history["options"]["workspace"], "report.json", report_raw)
    rewrite_history(history, "dependency-report.json", lambda row: row.update(
        schema="lunar-actual-build-dependency-consumer-v6", custody_backend=candidate._LIFETIME_BACKEND,
        execution_report_sha256=sha(report_raw)))
    older = candidate.prepare_lifetime_fixed_installation_description(history["build"], **history["options"])
    assert current.candidate_bytes == older.candidate_bytes
    assert current.runtime_closure == older.runtime_closure
    assert current.dependency_report_sha256 != older.dependency_report_sha256
