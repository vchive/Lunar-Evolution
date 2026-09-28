"""Read-only audit of a retained native acceptance campaign.

The campaign auditor deliberately sits above the launcher.  It opens a private SQLite
snapshot, reads retained files, and never invokes a provider, subprocess, evaluator, or
publication path.  A campaign can therefore be audited repeatedly without changing the
evidence it is meant to assess.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ._audit_snapshot import AuditSnapshotError, audit_snapshot
from ._benchmark_files import BenchmarkFileError, read_regular_file
from .acceptance_observation_binding import (
    AcceptanceObservationBindingError,
    inspect_acceptance_observation_binding,
)
from .acceptance_registration import AcceptanceRegistrationError, parse_acceptance_registration
from .campaign_inventory import (
    CampaignInventoryError,
    audit_campaign_directory,
    inventory_campaign_directory,
)
from .candidate_generation_receipt import (
    CandidateGenerationReceiptError,
    inspect_candidate_generation_events,
)
from .controller import LocalController
from .evolution import CandidateArchive, EvolutionError


class AcceptanceCampaignAuditError(ValueError):
    """A campaign audit or an immutable audit publication failed."""

    def __init__(self, code: str) -> None:
        self.code = code if isinstance(code, str) else "invalid"
        super().__init__(self.code)


def _canonical(value: object) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise AcceptanceCampaignAuditError("audit_report_invalid") from exc


def _materials(registration: Mapping[str, Any], root: Path) -> dict[str, bytes]:
    """Load only the material files declared by the registration."""
    result: dict[str, bytes] = {}
    descriptors: list[Mapping[str, Any]] = []
    for key in ("task_material", "input_material", "evaluator_material", "evaluator_profile_material"):
        value = registration.get(key)
        if isinstance(value, Mapping):
            descriptors.append(value)
    pins = registration.get("holdout_pins", ())
    if isinstance(pins, list):
        for pin in pins:
            if isinstance(pin, Mapping):
                for key in ("input", "expected"):
                    value = pin.get(key)
                    if isinstance(value, Mapping):
                        descriptors.append(value)
    for descriptor in descriptors:
        path = descriptor.get("path")
        if not isinstance(path, str) or path in result:
            continue
        # Native campaigns stage registration material under these stable names.  The
        # registration path remains the lookup key used by the binding verifier.
        name = None
        for field, staged in (
            ("task_material", "task.bin"),
            ("input_material", "input.bin"),
            ("evaluator_material", "evaluator-criteria.bin"),
            ("evaluator_profile_material", "profile-criteria.bin"),
        ):
            if registration.get(field) is descriptor:
                name = staged
                break
        if name is None:
            ordinal = next((int(pin.get("ordinal")) for pin in pins
                            if isinstance(pin, Mapping) and pin.get("input") is descriptor), None)
            if ordinal is not None:
                name = f"holdout-{ordinal:02d}-input.bin"
            else:
                ordinal = next((int(pin.get("ordinal")) for pin in pins
                                if isinstance(pin, Mapping) and pin.get("expected") is descriptor), None)
                if ordinal is not None:
                    name = f"holdout-{ordinal:02d}-expected.bin"
        if name is None:
            continue
        try:
            raw = (root / "materials" / name).read_bytes()
        except (OSError, ValueError) as exc:
            raise AcceptanceCampaignAuditError("audit_material_missing") from exc
        if len(raw) != descriptor.get("size") or hashlib.sha256(raw).hexdigest() != descriptor.get("sha256"):
            raise AcceptanceCampaignAuditError("audit_material_mismatch")
        result[path] = raw
    return result


def _event_payloads(events: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [item["payload"] for item in events if item.get("type") == kind and isinstance(item.get("payload"), dict)]


def _count_candidates(store: Any, child: Any, events: list[dict[str, Any]]) -> dict[str, int]:
    generation = [item for item in events if item.get("type") == "agent_candidate_generation"]
    observed = len(generation)
    complete_ids: set[str] = set()
    parser_complete = 0
    for event in generation:
        try:
            summary = inspect_candidate_generation_events(
                [event], run_id=child.id, task_id=event.get("task_id"),
            )
            payload = event["payload"]
            if summary == {"receipt_count": 1, "completed": 1} and isinstance(payload.get("candidate_id"), str):
                complete_ids.add(payload["candidate_id"])
                parser_complete += 1
        except (CandidateGenerationReceiptError, TypeError, ValueError, KeyError):
            continue
    executed = scored = 0
    try:
        archive = CandidateArchive(child.workspace, requested_strategy="population", read_only=True)
        records = archive.records()
        by_id = {record.candidate_id: record for record in records}
        executed = sum(candidate_id in by_id for candidate_id in complete_ids)
        scored = sum(
            candidate_id in by_id
            and getattr(by_id[candidate_id], "evaluation", None) is not None
            for candidate_id in complete_ids
        )
    except (EvolutionError, OSError, ValueError, TypeError):
        pass
    return {"observed": observed, "parser_complete": parser_complete,
            "executed": executed, "scored": scored}


def audit_native_campaign(
    registration: Mapping[str, Any] | str,
    *,
    campaign_root: str | Path,
    database: str | Path,
    parent_run_id: str,
) -> dict[str, Any]:
    """Audit one native campaign without invoking its runtime or changing its files."""
    try:
        reg = parse_acceptance_registration(registration)
    except (AcceptanceRegistrationError, TypeError, ValueError) as exc:
        raise AcceptanceCampaignAuditError("audit_registration_invalid") from exc
    root = Path(campaign_root).expanduser().resolve()
    report: dict[str, Any] = {
        "schema_version": "1",
        "scope": "acceptance_campaign_audit",
        "status": "failed",
        "preparation_success": "0/1",
        "primary_success": "0/1",
        "joint_success": "0/1",
        "candidate_counts": {"observed": 0, "parser_complete": 0, "executed": 0, "scored": 0},
        "holdout_counts": {"passed": 0, "failed": 0, "unknown": 0, "missing": 8},
        "provider_called_during_audit": False,
        "executed_during_audit": False,
        "mutated_during_audit": False,
        "registration_sha256": reg.get("registration_sha256"),
    }
    try:
        if root.name != reg.get("campaign_root"):
            raise AcceptanceCampaignAuditError("audit_campaign_root_mismatch")
        before = inventory_campaign_directory(root)
    except (CampaignInventoryError, AcceptanceCampaignAuditError) as exc:
        report["reason"] = getattr(exc, "code", str(exc))
        return report
    prep_ok = False
    runtime_ok = False
    delivery_ok = False
    try:
        materials = _materials(reg, root)
        with audit_snapshot(database) as store:
            parent = store.get_run(parent_run_id)
            if parent is None:
                report["reason"] = "audit_parent_missing"
            else:
                controller = object.__new__(LocalController)
                controller.store = store
                contract = controller._algorithm_contract(parent)
                parent_events = store.list_events(parent.id)
                prep_ok = contract is not None and bool(_event_payloads(parent_events, "bundle_profile_prepared"))
                report["preparation_success"] = "1/1" if prep_ok else "0/1"
                if prep_ok:
                    observation = root / "runtime-binding" / "observation"
                    try:
                        inspect_acceptance_observation_binding(
                            reg, store=store, parent_id=parent.id, materials=materials,
                            contract=contract, workspace=root / "runtime-binding",
                        )
                        runtime_ok = True
                        report["holdout_counts"] = {"passed": 8, "failed": 0, "unknown": 0, "missing": 0}
                    except (AcceptanceObservationBindingError, TypeError, ValueError, KeyError, OSError):
                        if observation.exists():
                            report["holdout_counts"] = {"passed": 0, "failed": 8, "unknown": 0, "missing": 0}
                child_id = None
                for payload in _event_payloads(parent_events, "evolution_linked"):
                    if isinstance(payload.get("evolution_run_id"), str):
                        child_id = payload["evolution_run_id"]
                        break
                if child_id:
                    child = store.get_run(child_id)
                    if child is not None:
                        child_events = store.list_events(child.id)
                        report["candidate_counts"] = _count_candidates(store, child, child_events)
                        try:
                            controller._verified_bundle_evolution_delivery(child.id)
                            delivery_ok = True
                        except (EvolutionError, TypeError, ValueError, KeyError, OSError):
                            delivery_ok = False
    except (AuditSnapshotError, AcceptanceCampaignAuditError, OSError, TypeError, ValueError, KeyError, EvolutionError) as exc:
        report["reason"] = getattr(exc, "code", str(exc))
    try:
        audit_campaign_directory(root, before)
    except CampaignInventoryError:
        report["reason"] = "audit_inventory_changed"
        report["mutated_during_audit"] = True
    counts = report["candidate_counts"]
    primary = prep_ok and runtime_ok and counts["parser_complete"] == counts["observed"] and counts["observed"] > 0 and counts["executed"] == counts["observed"] and counts["scored"] == counts["observed"] and delivery_ok
    report["primary_success"] = "1/1" if primary else "0/1"
    report["joint_success"] = report["primary_success"]
    if primary and report.get("reason") is None:
        report["status"] = "verified"
    return report


def publish_native_campaign_audit(
    registration: Mapping[str, Any] | str,
    *, campaign_root: str | Path, database: str | Path, parent_run_id: str,
    output_directory: str | Path,
) -> dict[str, Any]:
    """Audit and publish a create-only report plus the campaign inventory."""
    report = audit_native_campaign(registration, campaign_root=campaign_root, database=database, parent_run_id=parent_run_id)
    return _publish_native_campaign_audit_report(report, campaign_root=campaign_root, output_directory=output_directory)


def _publish_native_campaign_audit_report(
    report: Mapping[str, Any], *, campaign_root: str | Path, output_directory: str | Path,
) -> dict[str, Any]:
    """Publish an already-computed report without rerunning the read-only audit.

    The native runner computes the audit before writing its final result record.  This
    helper lets it publish the resulting report after that record exists, so the
    immutable inventory covers the complete retained campaign exactly once.
    """
    try:
        inventory = inventory_campaign_directory(campaign_root)
        output = Path(output_directory).expanduser().resolve()
        output.mkdir(parents=True, exist_ok=False)
        (output / "report.json").write_bytes(_canonical(report))
        (output / "inventory.json").write_bytes(_canonical(inventory))
    except (FileExistsError, OSError, CampaignInventoryError) as exc:
        raise AcceptanceCampaignAuditError("audit_publish_conflict") from exc
    return report


def verify_native_campaign_audit(*, campaign_root: str | Path, output_directory: str | Path) -> dict[str, Any]:
    """Verify a published audit against retained native evidence and campaign bytes."""
    output = Path(output_directory).expanduser().resolve()
    try:
        report_bytes = read_regular_file(output / "report.json", 64 * 1024)
        report = json.loads(report_bytes)
        inventory = json.loads((output / "inventory.json").read_text(encoding="utf-8"))
        if not isinstance(report, dict) or not isinstance(inventory, dict):
            raise TypeError("invalid audit publication")
        if report.get("schema_version") != "1" or report.get("scope") != "acceptance_campaign_audit":
            raise ValueError("invalid audit report identity")
        if report.get("status") not in {"verified", "failed"}:
            raise ValueError("invalid audit report status")
        audit_campaign_directory(campaign_root, inventory)
        native_result = Path(campaign_root) / "native-result.json"
        if native_result.exists() or native_result.is_symlink():
            result = json.loads(read_regular_file(native_result, 64 * 1024))
            if (
                not isinstance(result, dict)
                or result.get("scope") != "acceptance_native_result"
                or result.get("audit_report_sha256") != hashlib.sha256(report_bytes).hexdigest()
                or result.get("audit_status") != report.get("status")
                or result.get("audit_primary_success") != report.get("primary_success")
                or result.get("audit_joint_success") != report.get("joint_success")
                or result.get("audit_reason") != report.get("reason")
            ):
                raise AcceptanceCampaignAuditError("audit_report_binding_mismatch")
    except CampaignInventoryError as exc:
        raise AcceptanceCampaignAuditError("audit_inventory_changed") from exc
    except AcceptanceCampaignAuditError:
        raise
    except (BenchmarkFileError, OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise AcceptanceCampaignAuditError("audit_publication_invalid") from exc
    # The native result binds the report itself. A standalone audit without that result
    # can only verify campaign inventory and should be treated as an unanchored report.
    return dict(report)


__all__ = [
    "AcceptanceCampaignAuditError",
    "audit_native_campaign",
    "publish_native_campaign_audit",
    "verify_native_campaign_audit",
]
