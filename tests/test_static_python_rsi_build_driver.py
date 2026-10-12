from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tools.static_python_rsi_fixture import recipe
from tools.static_python_rsi_fixture.build_driver import (
    PREPARATION_SHA256,
    ControlledBuildError,
    MockBuildBackend,
    run_controlled_build,
)
from tools.static_python_rsi_fixture.installation_profile import (
    prepare_rsi_installation_profile,
)


@pytest.fixture
def preparation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source_root = tmp_path / "source-root"
    for name, _, _ in recipe._SOURCE_PINS:
        path = source_root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((recipe._ROOT / name).read_bytes())
    overlay_path = source_root / "tools/static_python_rsi_fixture/reviewed-profile-overlay.json"
    overlay_path.parent.mkdir(parents=True, exist_ok=True)
    overlay_path.write_bytes((recipe._ROOT / "tools/static_python_rsi_fixture/reviewed-profile-overlay.json").read_bytes())
    monkeypatch.setattr(recipe, "_ROOT", source_root)
    manifest = recipe.emit_rsi_launch_source_plan(tmp_path / "prepared")
    assets = {item.name: item.read_bytes() for item in manifest.parent.joinpath("assets").iterdir()}
    result = prepare_rsi_installation_profile(
        reviewed_build_inputs=(source_root / "tools/static_python_fixture/reviewed-build-inputs.json").read_bytes(),
        reviewed_overlay=(source_root / "tools/static_python_rsi_fixture/reviewed-profile-overlay.json").read_bytes(),
        source_plan=manifest.read_bytes(),
        expected_source_plan_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
        source_assets=assets,
    )
    assert result.sha256 == PREPARATION_SHA256
    return result


def test_mock_graph_is_fixed_and_never_claims_real_acceptance(preparation):
    backend = MockBuildBackend()
    report = run_controlled_build(preparation, backend=backend, environment={})
    assert report.completed_stages == ("configure", "freeze", "compile", "link")
    assert backend.calls == list(report.stages)
    assert report.simulated_closure is True
    assert report.configured_closure_verified is False
    assert report.compilation_performed is False
    assert report.freezer_performed is False
    assert report.link_performed is False
    assert report.installation_acceptance is False
    assert report.production_admission is False
    assert report.generated_header_count == 9


def test_preparation_pin_is_checked_before_backend(preparation):
    mutated = type(preparation)(preparation.wire_bytes.replace(b"pending-builder", b"pending-buildX", 1))
    backend = MockBuildBackend()
    with pytest.raises(ControlledBuildError, match="preparation_pin_mismatch"):
        run_controlled_build(mutated, backend=backend, environment={})
    assert backend.calls == []


@pytest.mark.parametrize("mutation", ["source_sha256", "object", "count", "generator", "header", "source_order"])
def test_candidate_and_header_mutations_refuse_before_backend(preparation, mutation):
    payload = json.loads(preparation.wire_bytes)
    candidate = payload["candidate_build_inputs"]
    if mutation == "source_sha256":
        candidate["target_units"][0]["source_sha256"] = "1" * 64
    elif mutation == "object":
        candidate["target_units"][0]["object"] = "foreign.o"
    elif mutation == "count":
        candidate["shared_units"].pop()
    elif mutation == "generator":
        candidate["freeze_tasks"][0]["generator_id"] = "foreign"
    elif mutation == "header":
        payload["pending_frozen_headers"][0]["state"] = "generated"
    else:
        candidate["freeze_tasks"].reverse()
    raw = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    backend = MockBuildBackend()
    with pytest.raises(ControlledBuildError):
        run_controlled_build(type(preparation)(raw), backend=backend, environment={})
    assert backend.calls == []


def test_unclosed_configure_blocks_later_stages(preparation):
    backend = MockBuildBackend(simulated_closure=False)
    with pytest.raises(ControlledBuildError, match="configured_closure_unverified") as caught:
        run_controlled_build(preparation, backend=backend, environment={})
    assert caught.value.report is not None
    assert caught.value.report.completed_stages == ()
    assert backend.calls == ["configure"]


def test_partial_stage_is_not_reported_as_completed(preparation):
    backend = MockBuildBackend(partial_stage="compile")
    with pytest.raises(ControlledBuildError, match="partial_stage") as caught:
        run_controlled_build(preparation, backend=backend, environment={})
    assert caught.value.report is not None
    assert caught.value.report.completed_stages == ("configure", "freeze")
    assert caught.value.report.partial is True
    assert backend.calls == ["configure", "freeze", "compile"]


def test_plan_is_detached_before_every_backend_call(preparation):
    class MutatingBackend(MockBuildBackend):
        def configure(self, plan):
            plan["freeze_tasks"].clear()
            return super().configure(plan)

    backend = MutatingBackend()
    report = run_controlled_build(preparation, backend=backend, environment={})
    assert report.completed_stages == ("configure", "freeze", "compile", "link")


def test_report_evidence_is_deep_detached_and_immutable(preparation):
    report = run_controlled_build(preparation, environment={})
    with pytest.raises(TypeError):
        report.stage_evidence["configure"] = {}  # type: ignore[index]
    with pytest.raises(TypeError):
        report.stage_evidence["freeze"]["headers"] = ()  # type: ignore[index]


def test_deadline_clock_and_interruption_types_are_strict(preparation):
    for clock in (lambda: True, lambda: float("nan"), lambda: float("inf"), lambda: "1"):
        with pytest.raises(ControlledBuildError, match="clock_invalid"):
            run_controlled_build(preparation, environment={}, deadline=2.0, monotonic=clock)
    with pytest.raises(ControlledBuildError, match="interruption_type_invalid"):
        run_controlled_build(preparation, environment={}, interrupted=lambda: 1)


def test_real_mode_and_environment_opt_in_refuse_before_backend(preparation):
    backend = MockBuildBackend()
    with pytest.raises(ControlledBuildError, match="real_execution_refused"):
        run_controlled_build(preparation, backend=backend, mode="real", environment={})
    with pytest.raises(ControlledBuildError, match="real_execution_refused"):
        run_controlled_build(preparation, backend=backend, environment={"LUNAR_STATIC_EXECUTE": "1"})
    assert backend.calls == []


def test_backend_exception_does_not_leak_cause_or_context(preparation):
    class ExplodingBackend(MockBuildBackend):
        def configure(self, plan):
            raise ValueError("secret backend path")

    with pytest.raises(ControlledBuildError, match="backend_failure") as caught:
        run_controlled_build(preparation, backend=ExplodingBackend(), environment={})
    assert str(caught.value) == "static_python_rsi_build_driver_backend_failure"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_non_mock_backend_refuses_before_stage(preparation):
    backend = MockBuildBackend()
    backend.mode = "real"
    with pytest.raises(ControlledBuildError, match="backend_not_mock"):
        run_controlled_build(preparation, backend=backend, environment={})
    assert backend.calls == []


@pytest.mark.parametrize("source", ["clock", "interruption", "backend_mode", "backend"])
def test_trusted_seam_failures_leave_no_caller_exception_context(preparation, source):
    def explode():
        raise ValueError("caller details must not enter the report")

    class Backend(MockBuildBackend):
        @property
        def mode(self):
            return explode() if source == "backend_mode" else "mock"

        def configure(self, plan):
            return explode() if source == "backend" else super().configure(plan)

    kwargs = {"backend": Backend(), "environment": {}}
    if source == "clock":
        kwargs["monotonic"] = explode
    elif source == "interruption":
        kwargs["interrupted"] = explode
    with pytest.raises(ControlledBuildError) as caught:
        run_controlled_build(preparation, **kwargs)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert "caller details" not in str(caught.value)


@pytest.mark.parametrize("mutation", ["extra", "claim", "object", "cycle", "wrong_label", "integer_closure"])
def test_mock_stage_evidence_is_bounded_before_serialization(preparation, mutation):
    class Backend(MockBuildBackend):
        def configure(self, plan):
            value = dict(super().configure(plan))
            if mutation == "extra":
                value["unbounded_metadata"] = "x" * 100_000
            elif mutation == "claim":
                value["production_admission"] = True
            elif mutation == "object":
                value["unbounded_metadata"] = object()
            elif mutation == "cycle":
                value["unbounded_metadata"] = value
            elif mutation == "wrong_label":
                value["evidence"] = "real-toolchain"
            else:
                value["simulated_closure"] = 1
            return value

    backend = Backend()
    with pytest.raises(ControlledBuildError, match="backend_result_invalid") as caught:
        run_controlled_build(preparation, backend=backend, environment={})
    assert backend.calls == ["configure"]
    assert not caught.value.report.stage_evidence
    assert caught.value.__context__ is None


@pytest.mark.parametrize("mutation", ["missing", "non_dict", "extra", "foreign_output", "reorder"])
def test_exact_header_receipts_are_required_before_compile(preparation, mutation):
    class Backend(MockBuildBackend):
        def freeze(self, plan):
            value = dict(super().freeze(plan))
            if mutation == "missing":
                value["headers"].pop()
            elif mutation == "non_dict":
                value["headers"][0] = None
            elif mutation == "extra":
                value["headers"][0]["code"] = "opaque blob"
            elif mutation == "foreign_output":
                value["headers"][0]["output"] = "other.h"
            else:
                value["headers"].reverse()
            return value

    backend = Backend()
    with pytest.raises(ControlledBuildError, match="backend_result_invalid") as caught:
        run_controlled_build(preparation, backend=backend, environment={})
    assert backend.calls == ["configure", "freeze"]
    assert caught.value.report.completed_stages == ("configure",)
    assert "freeze" not in caught.value.report.stage_evidence


def test_original_absolute_deadline_is_not_refreshed_after_stage(preparation):
    ticks = iter((1, 1, 2))
    backend = MockBuildBackend()
    with pytest.raises(ControlledBuildError, match="deadline_expired") as caught:
        run_controlled_build(preparation, backend=backend, environment={},
                             deadline=2, monotonic=lambda: next(ticks))
    assert backend.calls == ["configure"]
    assert caught.value.report.completed_stages == ("configure",)


def test_large_integer_deadline_preserves_precision(preparation):
    deadline = 10**400
    backend = MockBuildBackend()
    with pytest.raises(ControlledBuildError, match="deadline_expired"):
        run_controlled_build(preparation, backend=backend, environment={}, deadline=deadline,
                             monotonic=lambda: deadline)
    assert not backend.calls


@pytest.mark.parametrize("stage", ["configure", "freeze", "compile", "link"])
def test_partial_stages_never_enter_completed_inventory(preparation, stage):
    backend = MockBuildBackend(partial_stage=stage)
    with pytest.raises(ControlledBuildError, match="partial_stage") as caught:
        run_controlled_build(preparation, backend=backend, environment={})
    assert caught.value.report.completed_stages == tuple(backend.calls[:-1])
    assert caught.value.report.partial is True


def test_keyboard_interrupt_preserves_completed_stage_evidence(preparation):
    class Backend(MockBuildBackend):
        def compile(self, plan):
            self.calls.append("compile")
            raise KeyboardInterrupt("private caller detail")

    backend = Backend()
    with pytest.raises(ControlledBuildError, match="interrupted") as caught:
        run_controlled_build(preparation, backend=backend, environment={})
    assert caught.value.report.completed_stages == ("configure", "freeze")
    assert caught.value.__context__ is None
