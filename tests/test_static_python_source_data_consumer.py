"""Consumer transport/refusal tests with explicit test-only runner observations.

These tests exercise real pinned file readback and depfile comparison. The runner
and OCI observation boundary are doubles; they establish no Podman execution,
static helper, isolation, CPython or installed-account acceptance.
"""

from __future__ import annotations

import json

import pytest

from tests.test_static_python_link_dependency_capture import base_recipe, instrument, record, sha
from tools.static_python_rsi_fixture import build_dependency_consumer as consumer
from tools.static_python_rsi_fixture import link_dependency_capture as capture
from tools.static_python_rsi_fixture import podman_custody as custody
from tools.static_python_rsi_fixture.execution_backend import (
    INPUT_PROJECTION_V4,
    BuildExecutionError,
    BuildExecutionReport,
)
from tools.static_python_rsi_fixture.runtime_closure import canonical


@pytest.fixture
def transport(tmp_path, monkeypatch):
    source_raw, tool_raw, crt_raw = b"inert source data", b"inert test-only tool", b"crt"
    source_records = [record("unit.c", source_raw, True)]
    tool_records = [record("lib/crt.o", crt_raw), record("zig", tool_raw, True)]
    base = instrument(monkeypatch, base_recipe(sha(b"prep"), source_records, tool_records))
    generated = capture._data_source_capture_successor(
        base, original_source_inventory_sha256=sha(canonical(source_records)),
    )
    wire, manifest = json.loads(generated.recipe_bytes), json.loads(generated.manifest_bytes)
    source, toolchain, workspace = tmp_path / "source", tmp_path / "tools", tmp_path / "attempt"
    source.mkdir()
    (toolchain / "lib").mkdir(parents=True)
    (source / "unit.c").write_bytes(source_raw)
    (source / "unit.c").chmod(0o500)
    (toolchain / "zig").write_bytes(tool_raw)
    (toolchain / "zig").chmod(0o500)
    (toolchain / "lib/crt.o").write_bytes(crt_raw)
    controls = {"now": 10.0, "interrupt": False, "calls": 0, "drift": None}
    observed = []

    def fake_observation(command, planned, stage, index, recipe_sha256, environment, *,
                         inputs, prior, workspace, checkpoint=None):
        assert command["custody"] == {"test_only_observation": True}
        assert recipe_sha256 == generated.sha256 and inputs == wire["inputs"]
        assert workspace == tmp_path / "attempt" and environment == wire["environment"]
        assert command["index"] == index
        if checkpoint is not None:
            checkpoint()
        observed.append((stage, index, [dict(item) for item in prior]))

    monkeypatch.setattr(custody, "validate_custody_observation_v2", fake_observation)

    def runner(preparation, **options):
        controls["calls"] += 1
        assert options["deadline"] == 100.0 and options["monotonic"] is kwargs["monotonic"]
        assert options["interrupted"] is kwargs["interrupted"]
        assert options["custody_backend"] == custody.SOURCE_DATA_BACKEND
        for role, original in (("source", source), ("toolchain", toolchain)):
            for item in wire["inputs"][role]:
                target = workspace / role / item["path"]
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((original / item["path"]).read_bytes())
                target.chmod(0o555 if item["executable"] else 0o444)
        artifacts = {}
        for item in manifest["compilations"]:
            artifacts[item["depfile"]] = (
                "/out/" + item["target"].removeprefix("@work/") + ": /source/unit.c\n"
            ).encode()
        for item in manifest["links"]:
            artifacts[item["depfile"]] = (
                "/out/" + item["target"].removeprefix("@work/") + ": "
                + " ".join("/work/" + name.removeprefix("@work/") for name in item["explicit_inputs"])
                + " /toolchain/lib/crt.o\n"
            ).encode()
        stages = []
        for group in wire["stages"]:
            commands, group_outputs = [], []
            for index, command in enumerate(group["commands"]):
                outputs = []
                for item in command["outputs"]:
                    raw = artifacts.get(item["path"], b"inert output")
                    target = workspace / "work" / item["path"]
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(raw)
                    target.chmod(0o700 if item["executable"] else 0o600)
                    outputs.append(record(item["path"], raw, item["executable"]))
                group_outputs.extend(outputs)
                commands.append({"index": index, "status": "complete", "returncode": 0,
                                 "direct_child_reaped": True, "outputs": outputs,
                                 "custody": {"test_only_observation": True}})
            stages.append({"stage": group["stage"], "status": "complete",
                           "commands": commands, "outputs": group_outputs})
        report = BuildExecutionReport(
            recipe_sha256=generated.sha256, completed_stages=("configure", "freeze", "compile", "link"),
            stage_evidence=tuple(stages), status="complete", reason=None,
        )
        raw_report = canonical({
            "schema": "lunar-static-python-build-execution-report-v4",
            "recipe_sha256": generated.sha256, "completed_stages": list(report.completed_stages),
            "stage_evidence": stages, "status": "complete", "reason": None,
            "configured_closure_verified": False, "installation_accepted": False,
            "runtime_execution_performed": False, "production_admission": False,
            "input_projection": INPUT_PROJECTION_V4, "immutable_custody_verified": False,
            "driver_inputs_verified": False, "implicit_link_inputs_verified": False,
            "online_publication": False,
        })
        (workspace / "report.json").write_bytes(raw_report)
        if controls["drift"] == "report":
            changed = json.loads(raw_report)
            changed["input_projection"] = "unreviewed-projection"
            (workspace / "report.json").write_bytes(canonical(changed))
        elif controls["drift"] == "source_mode":
            (source / "unit.c").chmod(0o400)
        elif controls["drift"] == "output":
            (workspace / "work/objects/target.o").write_bytes(b"replaced")
        elif controls["drift"] == "deadline":
            controls["now"] = 100.0
        elif controls["drift"] == "interrupt":
            controls["interrupt"] = True
        return report

    kwargs = {"recipe_bytes": generated.recipe_bytes, "expected_recipe_sha256": generated.sha256,
              "manifest_bytes": generated.manifest_bytes,
              "expected_manifest_sha256": sha(generated.manifest_bytes),
              "source_root": source, "toolchain_root": toolchain, "workspace": workspace,
              "deadline": 100.0, "monotonic": lambda: controls["now"],
              "interrupted": lambda: controls["interrupt"]}
    monkeypatch.setattr(consumer, "run_pinned_build_v4", runner)
    return kwargs, wire, controls, observed


def test_explicit_v4_consumer_uses_original_report_and_full_ordered_prior_groups(transport):
    kwargs, wire, controls, observed = transport
    result = consumer.run_dependency_checked_build_v4(object(), **kwargs)
    evidence = json.loads((kwargs["workspace"] / "dependency-report.json").read_bytes())
    assert controls["calls"] == 1
    assert evidence["schema"] == "lunar-actual-build-dependency-consumer-v2"
    assert evidence["input_projection"] == INPUT_PROJECTION_V4
    assert evidence["inputs_sha256"] == sha(canonical(wire["inputs"]))
    assert evidence["execution_report_sha256"] == sha((kwargs["workspace"] / "report.json").read_bytes())
    assert evidence["compilations"] == 3 and evidence["links"] == 2
    expected_prior = []
    for stage in result.execution_report.stage_evidence:
        for command in stage["commands"]:
            actual_stage, index, prior = observed.pop(0)
            assert actual_stage == stage["stage"] and index == command["index"]
            assert prior == expected_prior
            expected_prior.extend(command["outputs"])
    assert not observed
    for key in ("immutable_custody_verified", "driver_inputs_verified", "implicit_link_inputs_verified",
                "installation_accepted", "production_admission", "online_publication"):
        assert evidence[key] is False and getattr(result, key) is False
    assert json.loads((kwargs["workspace"] / "compiler-dependency-comparison.json").read_bytes())["input_projection"] == INPUT_PROJECTION_V4


@pytest.mark.parametrize("backend", [None, "podman", "podman-snapshots-v1", "host", True])
def test_v4_consumer_has_no_legacy_or_host_fallback(transport, backend):
    kwargs, _, controls, _ = transport
    with pytest.raises(consumer.BuildDependencyError, match="custody_backend"):
        consumer.run_dependency_checked_build_v4(object(), **kwargs, custody_backend=backend)
    assert controls["calls"] == 0 and not kwargs["workspace"].exists()


@pytest.mark.parametrize("drift,reason", [
    ("report", "file_pin"), ("source_mode", "file_pin"), ("output", "file_pin"),
    ("deadline", "deadline_expired"), ("interrupt", "interrupted"),
])
def test_v4_retains_original_report_without_new_budget_retry_or_authority(transport, drift, reason):
    kwargs, _, controls, _ = transport
    controls["drift"] = drift
    with pytest.raises(consumer.BuildDependencyError, match=reason) as failure:
        consumer.run_dependency_checked_build_v4(object(), **kwargs)
    assert controls["calls"] == 1 and failure.value.execution_report.status == "complete"
    assert (kwargs["workspace"] / "report.json").is_file()
    assert not (kwargs["workspace"] / "dependency-report.json").exists()


def test_v4_consumer_rejects_resigned_inventory_manifest_drift_before_execution(transport):
    kwargs, _, controls, _ = transport
    changed = json.loads(kwargs["manifest_bytes"])
    changed["source_inventory_sha256"] = sha(b"different original source inventory")
    kwargs.update(manifest_bytes=canonical(changed), expected_manifest_sha256=sha(canonical(changed)))
    with pytest.raises(ValueError, match="manifest"):
        consumer.run_dependency_checked_build_v4(object(), **kwargs)
    assert controls["calls"] == 0 and not kwargs["workspace"].exists()


def test_legacy_consumer_does_not_implicitly_upgrade_to_v4(transport):
    kwargs, _, controls, _ = transport
    with pytest.raises(BuildExecutionError, match="recipe"):
        consumer.run_dependency_checked_build(object(), **kwargs)
    assert controls["calls"] == 0 and not kwargs["workspace"].exists()


def test_detached_custody_refusal_keeps_original_execution_report(transport, monkeypatch):
    kwargs, _, controls, _ = transport

    def refuse(*args, **options):
        raise ValueError("podman_custody_original_observation_v2")

    monkeypatch.setattr(custody, "validate_custody_observation_v2", refuse)
    with pytest.raises(consumer.BuildDependencyError, match="readback_or_evidence_failure") as failure:
        consumer.run_dependency_checked_build_v4(object(), **kwargs)
    assert controls["calls"] == 1 and failure.value.execution_report.status == "complete"
    assert not (kwargs["workspace"] / "dependency-report.json").exists()
