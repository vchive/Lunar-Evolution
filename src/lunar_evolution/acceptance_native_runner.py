"""One-shot native automatic multi-file acceptance launch."""
from __future__ import annotations

import hashlib
import json
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from typing import Any

from ._benchmark_files import read_regular_file
from .acceptance_campaign_audit import (
    _publish_native_campaign_audit_report,
    audit_native_campaign,
)
from .acceptance_launch import _write_new
from .acceptance_launch_stage import stage_acceptance_attempt
from .acceptance_observation_binding import publish_acceptance_observation_binding
from .acceptance_registration import MAX_REGISTRATION_BYTES, parse_acceptance_registration
from .acceptance_request_budget import AcceptanceRequestBudget, own_request_budget
from .acceptance_runtime_binding import prepare_acceptance_runtime_binding
from .runtime import OpenAICompatibleRuntime


class AcceptanceNativeRunnerError(ValueError):
    """Fixed-code failure before or after the one-shot native invocation."""


def _fail(code: str) -> None:
    raise AcceptanceNativeRunnerError(code)


@contextmanager
def _native_environment() -> Iterator[None]:
    overrides = {"LUNAR_EVOLUTION_MAX_RETRIES": "1", "LUNAR_EVOLUTION_RUNTIME_TIMEOUT": "600"}
    previous = {name: os.environ.get(name) for name in overrides}
    try:
        os.environ.update(overrides)
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _material_bytes(registration: dict[str, Any], campaign: Path) -> dict[str, bytes]:
    names = {
        "task_material": "task.bin", "input_material": "input.bin",
        "evaluator_material": "evaluator-criteria.bin",
        "evaluator_profile_material": "profile-criteria.bin",
    }
    materials: dict[str, bytes] = {}
    for field, name in names.items():
        pin = registration[field]
        content = read_regular_file(campaign / "materials" / name, pin["size"])
        if len(content) != pin["size"] or hashlib.sha256(content).hexdigest() != pin["sha256"]:
            _fail("acceptance_material_changed")
        materials[pin["path"]] = content
    for holdout in registration["holdout_pins"]:
        for kind in ("input", "expected"):
            pin = holdout[kind]
            name = f"holdout-{holdout['ordinal']:02d}-{kind}.bin"
            content = read_regular_file(campaign / "materials" / name, pin["size"])
            if len(content) != pin["size"] or hashlib.sha256(content).hexdigest() != pin["sha256"]:
                _fail("acceptance_material_changed")
            materials[pin["path"]] = content
    return materials


def _native_args(registration: dict[str, Any], task: str, campaign: Path) -> list[str]:
    budgets = registration["budgets"]
    return [
        "solve", task, "--evolve", "--multi-file", "--strategy", "population",
        "--runtime", "openai-compatible", "--model", registration["model"],
        "--agent-loop", "--max-steps", str(registration["candidate_tool_steps"]),
        "--input", f"{campaign / 'materials' / 'input.bin'}=limit.json",
        "--max-rounds", str(registration["rounds"]),
        "--population-size", str(registration["population_size"]),
        "--offspring-per-iteration", str(registration["offspring_count"]),
        "--islands", str(registration["islands"]),
        "--timeout", str(budgets["request_timeout_seconds"]),
        "--evaluator-preparation-timeout", str(budgets["preparation_request_timeout_seconds"]),
        "--evaluator-preparation-wall-timeout", str(budgets["preparation_wall_seconds"]),
        "--solve-wall-timeout", str(budgets["solve_wall_seconds"]),
        "--candidate-generation-max-steps", str(registration["candidate_tool_steps"]),
        "--home", str(campaign / "native-home"), "--json",
    ]


def _write_record(campaign: Path, claim: dict[str, Any], name: str, record: dict[str, Any]) -> str:
    raw = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
    try:
        descriptor = os.open(campaign, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            held = os.fstat(descriptor)
            named = os.stat(campaign, follow_symlinks=False)
            if (not stat.S_ISDIR(held.st_mode) or stat.S_IMODE(held.st_mode) != 0o700
                    or (held.st_dev, held.st_ino) != (named.st_dev, named.st_ino)
                    or (held.st_dev, held.st_ino) != (claim["root_device"], claim["root_inode"])):
                _fail("acceptance_campaign_root_changed")
            _write_new(descriptor, name, raw)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise AcceptanceNativeRunnerError("acceptance_record_unavailable") from exc
    return hashlib.sha256(raw).hexdigest()


def run_registered_acceptance(
    registration_path: str | os.PathLike[str],
    seal_path: str | os.PathLike[str],
    *,
    checkout_root: str | os.PathLike[str],
    campaign_parent: str | os.PathLike[str],
) -> dict[str, Any]:
    """Claim one fresh campaign and invoke exactly one foreground native solve.

    A claimed root is never reused. Any launch, preparation, provider or audit failure
    preserves the retained evidence and returns a failed one-slot outcome.
    """
    registration = parse_acceptance_registration(
        read_regular_file(Path(registration_path), MAX_REGISTRATION_BYTES).decode("utf-8")
    )
    if (registration["provider"] != "openai-compatible"
            or registration["model"] != "glm-5.2"
            or registration["api_mode"] != "chat_completions"):
        _fail("acceptance_native_identity_unsupported")
    if not os.environ.get("LUNAR_EVOLUTION_MODEL_ENDPOINT") or not os.environ.get("LUNAR_EVOLUTION_API_KEY"):
        _fail("acceptance_provider_configuration_missing")
    runtime = OpenAICompatibleRuntime(model=registration["model"])
    if not runtime.endpoint.endswith("/chat/completions"):
        _fail("acceptance_api_mode_unsupported")
    budget = AcceptanceRequestBudget(
        registration["budgets"]["request_ceiling"],
        registration["budgets"]["observed_token_ceiling"],
    )
    with own_request_budget(budget), _native_environment():
        claim = stage_acceptance_attempt(
            registration_path, seal_path,
            checkout_root=checkout_root, campaign_parent=campaign_parent,
        )
        campaign = Path(campaign_parent) / claim["campaign_root"]
        materials = _material_bytes(registration, campaign)
        try:
            task = materials[registration["task_material"]["path"]].decode("utf-8")
        except UnicodeDecodeError:
            _fail("acceptance_task_encoding_invalid")
        if not task or task != task.strip():
            _fail("acceptance_task_bytes_invalid")
        args = _native_args(registration, task, campaign)
        binding: dict[str, Any] = {}
        binding_started = False

        def on_prepared(store: Any, parent_id: str, contract: Any, solve_control: Any) -> None:
            nonlocal binding_started
            if binding_started:
                _fail("acceptance_binding_reentered")
            binding_started = True
            if solve_control is None:
                _fail("acceptance_solve_control_missing")
            workspace = campaign / "runtime-binding"
            check_active = lambda: solve_control.check("preparation")
            remaining = lambda stage: solve_control.effective_timeout(stage=stage)
            receipt = prepare_acceptance_runtime_binding(
                registration, store=store, parent_id=parent_id,
                materials=materials, contract=contract, workspace=workspace,
                check_active=check_active, remaining_timeout=remaining,
            )
            observation = publish_acceptance_observation_binding(
                registration, store=store, parent_id=parent_id,
                materials=materials, contract=contract, workspace=workspace,
                check_active=check_active, remaining_timeout=remaining,
            )
            binding.update({
                "parent_run_id": parent_id,
                "runtime_binding_sha256": receipt["binding_sha256"],
                "observation_binding_sha256": observation["binding"]["observation_binding_sha256"],
            })

        launch = {
            "schema_version": "1", "scope": "acceptance_native_launch",
            "attempt_claim_sha256": claim["attempt_claim_sha256"],
            "registration_sha256": claim["registration_sha256"],
            "provider_call_made": False,
        }
        _write_record(campaign, claim, "native-launch.json", launch)
        from . import cli

        output = StringIO()
        try:
            with redirect_stdout(output), redirect_stderr(StringIO()):
                code = cli.main(args, _acceptance_preparation_hook=on_prepared)
        except Exception:  # noqa: BLE001 - retain a fixed failure result without provider prose
            code = 2
        try:
            native = json.loads(output.getvalue())
        except (TypeError, ValueError):
            native = {}
        native_succeeded = (
            isinstance(native, dict) and native.get("status") == "succeeded"
            and isinstance(native.get("evolution"), dict)
            and native["evolution"].get("status") == "succeeded"
        )
        audit_report = audit_native_campaign(
            registration,
            campaign_root=campaign,
            database=campaign / "native-home" / "state.db",
            parent_run_id=binding.get("parent_run_id", ""),
        )
        audit_verified = (
            audit_report.get("status") == "verified"
            and audit_report.get("joint_success") == "1/1"
        )
        snapshot = budget.snapshot()
        budget_record = {
            "schema_version": "1", "scope": "acceptance_native_budget",
            "attempt_claim_sha256": claim["attempt_claim_sha256"],
            "registration_sha256": claim["registration_sha256"],
            "request_ceiling": budget.max_requests,
            "observed_token_ceiling": budget.max_observed_tokens,
            **snapshot,
        }
        budget_digest = _write_record(campaign, claim, "native-budget.json", budget_record)
        result = {
            "schema_version": "1", "scope": "acceptance_native_result",
            # The CLI's self-reported success is necessary but never sufficient. The
            # independent retained-evidence audit owns the final acceptance decision.
            "status": "completed" if code == 0 and binding and native_succeeded and audit_verified else "failed",
            "exit_code": code, "attempt_claim_sha256": claim["attempt_claim_sha256"],
            "registration_sha256": claim["registration_sha256"],
            "request_ceiling": budget.max_requests,
            "observed_token_ceiling": budget.max_observed_tokens,
            "budget_receipt_sha256": budget_digest,
            "provider_call_made": snapshot["request_count"] > 0,
            "audit_status": audit_report.get("status", "failed"),
            "audit_primary_success": audit_report.get("primary_success", "0/1"),
            "audit_joint_success": audit_report.get("joint_success", "0/1"),
            "audit_reason": audit_report.get("reason"),
            "audit_report_sha256": hashlib.sha256(
                json.dumps(audit_report, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            **snapshot, **binding,
        }
        _write_record(campaign, claim, "native-result.json", result)
        audit_output = campaign.with_name(f"{campaign.name}-audit")
        _publish_native_campaign_audit_report(
            audit_report, campaign_root=campaign, output_directory=audit_output,
        )
        return result


# The isolated pinned loader uses a private name so the launch boundary cannot be
# confused with the public provider-free staging APIs.
_run_registered_acceptance = run_registered_acceptance

__all__ = ["AcceptanceNativeRunnerError", "run_registered_acceptance"]
