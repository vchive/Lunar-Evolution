"""Explicit lifetime-history candidate tests with doubled custody observations.

The shared retained fixture uses synthetic, unexecuted sources and images. Its
custody boundary stays an explicit double; real report reconstruction, bounded
file readback, closure parsing and ELF checks remain active. Actual lifetime
raw/owner validation belongs to its separate focused file.
"""

from __future__ import annotations

import copy
import json
from dataclasses import replace

import pytest

from tests import test_static_python_retained_installation as retained_tests
from tests.test_static_python_retained_installation import (
    rewrite_history,
    sha,
    write,
)
from tools.static_python_rsi_fixture import build_dependency_consumer as consumer
from tools.static_python_rsi_fixture import podman_custody as custody
from tools.static_python_rsi_fixture import retained_installation as candidate
from tools.static_python_rsi_fixture.runtime_closure import canonical

BACKEND = "podman-snapshots-source-data-vfs-lifetime-v1"
_REAL_VALIDATOR = custody.validate_custody_observation_v5
retained_history = retained_tests.history


@pytest.fixture
def lifetime_history(retained_history, monkeypatch):
    history = retained_history
    original_double = custody.validate_custody_observation_v4
    controls = history["controls"]
    controls["lifetime_observations"] = 0

    def lifetime_observation(*args, **kwargs):
        controls["lifetime_observations"] += 1
        original_double(*args, **kwargs)

    monkeypatch.setattr(custody, "validate_custody_observation_v5", lifetime_observation)
    options, build = history["options"], history["build"]
    report_raw, _outputs = consumer._report_outputs(
        build.execution_report, history["wire"], BACKEND, version4=True,
        workspace=options["workspace"], checkpoint=lambda: None,
        vfs_roots=True, vfs_retained=True, vfs_lifetime=True,
    )
    write(options["workspace"], "report.json", report_raw)
    rewrite_history(history, "dependency-report.json", lambda row: row.update(
        schema="lunar-actual-build-dependency-consumer-v6", custody_backend=BACKEND,
        execution_report_sha256=sha(report_raw)))
    controls["observations"] = controls["lifetime_observations"] = 0
    return history


def prepare(history, **overrides):
    return candidate.prepare_lifetime_fixed_installation_description(
        history["build"], **{**history["options"], **overrides})


def snapshot(root):
    return {path.relative_to(root).as_posix(): (path.read_bytes(), path.stat().st_mode)
            for path in root.rglob("*") if path.is_file()}


@pytest.mark.parametrize("retained_history", ["openevolve", "shinka"], indirect=True)
def test_explicit_lifetime_history_produces_only_candidate_and_preserves_original_files(lifetime_history):
    history = lifetime_history
    before = snapshot(history["options"]["workspace"])
    result = prepare(history)
    value = result.to_dict()
    assert value["profile_version"] == "fixed-" + history["closure"]["solver"] + "-v1"
    assert len(value["frozen_modules"]) == len(history["closure"]["frozen"])
    assert len(value["native_units"]) == len(history["closure"]["native_units"])
    assert value["image"]["mode"] == 0o711
    assert all(flag is False for flag in value["claims"].values())
    assert result.production_admission is result.online_publication is False
    assert history["controls"]["lifetime_observations"] == 4
    assert result.dependency_report_sha256 == history["build"].evidence_sha256
    assert snapshot(history["options"]["workspace"]) == before


def test_new_entry_refuses_original_retained_history(retained_history):
    with pytest.raises(candidate.RetainedInstallationDescriptionError):
        prepare(retained_history)


def test_original_entry_refuses_lifetime_history(lifetime_history):
    with pytest.raises(candidate.RetainedInstallationDescriptionError):
        candidate.prepare_retained_fixed_installation_description(
            lifetime_history["build"], **lifetime_history["options"])


@pytest.mark.parametrize("field,value", [
    ("schema", "lunar-actual-build-dependency-consumer-v5"),
    ("custody_backend", "podman-snapshots-source-data-vfs-retained-v1"),
    ("execution_report_sha256", "a" * 64),
    ("dependency_path_profile", "source-inventory-directories-v2"),
    ("compilations", True), ("compilations", 1.0), ("links", 0),
    ("immutable_custody_verified", True), ("driver_inputs_verified", True),
    ("configured_closure_verified", True), ("installation_accepted", True),
    ("production_admission", True), ("online_publication", True),
])
def test_resigned_mixed_dependency_history_and_authority_claims_refuse(lifetime_history, field, value):
    rewrite_history(lifetime_history, "dependency-report.json", lambda row: row.update({field: value}))
    with pytest.raises(candidate.RetainedInstallationDescriptionError):
        prepare(lifetime_history)


def test_exact_persisted_execution_report_is_required(lifetime_history):
    root = lifetime_history["options"]["workspace"]
    raw = (root / "report.json").read_bytes()
    value = json.loads(raw)
    value["schema"] = "lunar-static-python-build-execution-report-v6"
    write(root, "report.json", canonical(value))
    rewrite_history(lifetime_history, "dependency-report.json", lambda row: row.update(
        execution_report_sha256=sha(canonical(value))))
    with pytest.raises(candidate.RetainedInstallationDescriptionError):
        prepare(lifetime_history)


def test_actual_validator_refuses_synthetic_observation_instead_of_falling_back(lifetime_history, monkeypatch):
    monkeypatch.setattr(custody, "validate_custody_observation_v5", _REAL_VALIDATOR)
    with pytest.raises(candidate.RetainedInstallationDescriptionError) as error:
        prepare(lifetime_history)
    assert str(error.value) == "retained_installation_description_readback_or_description"
    assert error.value.__cause__ is None


@pytest.mark.parametrize("control", ["deadline", "interrupted"])
def test_original_observation_control_refusal_precedes_any_custody_readback(lifetime_history, control):
    lifetime_history["controls"].update(now=100.0 if control == "deadline" else 10.0,
                                         interrupt=control == "interrupted")
    with pytest.raises(candidate.RetainedInstallationDescriptionError) as error:
        prepare(lifetime_history)
    assert str(error.value) == "retained_installation_description_" + control
    assert lifetime_history["controls"]["lifetime_observations"] == 0


def test_output_mutation_during_second_readback_refuses(lifetime_history, monkeypatch):
    original_read = candidate._read
    image_reads = 0

    def observed_read(root, path, *args, **kwargs):
        nonlocal image_reads
        raw = original_read(root, path, *args, **kwargs)
        if path.startswith("bin/lunar-"):
            image_reads += 1
            if image_reads == 1:
                output = next(row for row in lifetime_history["outputs"] if not row["executable"])
                target = lifetime_history["options"]["workspace"] / "work" / output["path"]
                target.write_bytes(target.read_bytes() + b"drift")
        return raw

    monkeypatch.setattr(candidate, "_read", observed_read)
    with pytest.raises(candidate.RetainedInstallationDescriptionError):
        prepare(lifetime_history)
    assert image_reads == 1


def test_build_authority_cannot_be_promoted_by_lifetime_entry(lifetime_history):
    build = replace(lifetime_history["build"], immutable_custody_verified=True)
    with pytest.raises(candidate.RetainedInstallationDescriptionError, match="_build$"):
        candidate.prepare_lifetime_fixed_installation_description(build, **lifetime_history["options"])


def test_lifetime_candidate_uses_existing_candidate_bytes_with_separate_history_pin(
    retained_history, lifetime_history,
):
    # The shared fixture has already been converted by lifetime_history. Restore
    # only the synthetic historical envelope for the old read-only API, keeping
    # every source, output and candidate byte fixed.
    current = prepare(lifetime_history)
    history = retained_history
    options, build = history["options"], history["build"]
    report_raw, _ = consumer._report_outputs(
        build.execution_report, history["wire"], candidate._BACKEND, version4=True,
        workspace=options["workspace"], checkpoint=lambda: None,
        vfs_roots=True, vfs_retained=True,
    )
    write(options["workspace"], "report.json", report_raw)
    rewrite_history(history, "dependency-report.json", lambda row: row.update(
        schema="lunar-actual-build-dependency-consumer-v5", custody_backend=candidate._BACKEND,
        execution_report_sha256=sha(report_raw)))
    original = candidate.prepare_retained_fixed_installation_description(history["build"], **options)
    assert current.candidate_bytes == original.candidate_bytes
    assert current.dependency_report_sha256 != original.dependency_report_sha256
    assert copy.deepcopy(current.to_dict()) == original.to_dict()
