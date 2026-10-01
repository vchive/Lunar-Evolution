"""Fresh offline campaign audit: real native preparation, execution, scoring and delivery."""
from __future__ import annotations

import gc
import importlib.util
import json
import subprocess
from contextlib import closing, contextmanager, redirect_stdout
from io import StringIO
from pathlib import Path

import pytest
from test_acceptance_runtime_binding import _SOURCE, _contract, _registration

from lunar_evolution import cli
from lunar_evolution.acceptance_native_runner import _quiesce_native_database
from lunar_evolution.acceptance_observation_binding import publish_acceptance_observation_binding
from lunar_evolution.acceptance_registration import build_acceptance_registration
from lunar_evolution.acceptance_runtime_binding import prepare_acceptance_runtime_binding
from lunar_evolution.runtime import MockRuntime, RuntimeResult
from lunar_evolution.store import Store


def native_campaign(tmp_path, monkeypatch, *, fail_generation=False, quiesce_database=True):
    spec = importlib.util.spec_from_file_location(
        "audit_case", Path(__file__).resolve().parents[1]
        / "specs/142-automatic-solve-lifecycle/measurement/case.py",
    )
    case = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(case)
    raw = case.build_case_materials()
    materials = {case.MATERIAL_ROOT + "/" + name: data for name, data in raw.items()}
    registration = _registration(case.TASK_BYTES, case.INPUT_BYTES,
                                 raw["reference/evaluator-criteria.json"],
                                 raw["reference/profile-criteria.json"])
    registration = build_acceptance_registration({
        **{k: v for k, v in registration.items() if k != "registration_sha256"},
        **case.build_case_pins(),
    })
    campaign = tmp_path / registration["campaign_root"]
    campaign.mkdir(mode=0o700)
    staged = campaign / "materials"
    staged.mkdir()
    names = {"task_material": "task.bin", "input_material": "input.bin",
             "evaluator_material": "evaluator-criteria.bin",
             "evaluator_profile_material": "profile-criteria.bin"}
    for field, name in names.items():
        (staged / name).write_bytes(materials[registration[field]["path"]])
    for pin in registration["holdout_pins"]:
        for kind in ("input", "expected"):
            (staged / f"holdout-{pin['ordinal']:02d}-{kind}.bin").write_bytes(materials[pin[kind]["path"]])

    class Runtime(MockRuntime):
        name = "offline-campaign"

        def run_isolated(self, prompt, workspace, timeout=None):
            return self.run(prompt, workspace, timeout)

        def run(self, prompt, workspace, timeout=None, **kwargs):
            if "contract compiler" in prompt:
                return RuntimeResult(json.dumps({"status": "compiled", "contract": _contract().to_dict()}))
            suite = {
                "schema_version": "1", "constraint_coverage": ["valid-value"],
                "probes": [json.loads(raw[f"holdouts/{n:02d}/snapshot.json"]) for n in (1, 2, 0)],
                "score_order": [{"better": "limit-1-value-1", "worse": "limit-1-value-0"}],
            }
            if "frozen local evaluator bundle" in prompt:
                return RuntimeResult(json.dumps({**suite, "objective": "maximize valid value",
                                                 "evaluator_source": _SOURCE}))
            if "adversarial evaluator auditor" in prompt:
                return RuntimeResult(json.dumps(suite))
            if fail_generation:
                return RuntimeResult("invalid candidate")
            return RuntimeResult(json.dumps({
                "files": {"src/main.py": "import json\nfrom pathlib import Path\n"
                          "from helper import value\nPath('output').mkdir(exist_ok=True)\n"
                          "Path('output/result.json').write_text(json.dumps({'value': value()}))\n",
                          "src/helper.py": "def value():\n    return 3\n"},
                "entrypoint": "src/main.py",
            }), metadata={"candidate_tool_steps_used": "0", "candidate_tool_steps_remaining": "12",
                          "candidate_attempted_tool_calls": "0"})

    monkeypatch.setattr(cli, "build_runtime", lambda *_args, **_kwargs: Runtime())
    observed = {}

    def prepared(store, parent_id, contract, control):
        prepare_acceptance_runtime_binding(
            registration, store=store, parent_id=parent_id, materials=materials,
            contract=contract, workspace=campaign / "runtime-binding",
        )
        publish_acceptance_observation_binding(
            registration, store=store, parent_id=parent_id, materials=materials,
            contract=contract, workspace=campaign / "runtime-binding",
        )
        observed["parent_run_id"] = parent_id

    args = ["solve", case.TASK_BYTES.decode(), "--evolve", "--multi-file",
            "--runtime", "mock", "--workspace", str(campaign / "parent"),
            "--input", str(staged / "input.bin") + "=limit.json",
            "--max-rounds", "1", "--population-size", "1", "--offspring-per-iteration", "1",
            "--islands", "1", "--timeout", "600", "--evaluator-preparation-timeout", "900",
            "--evaluator-preparation-wall-timeout", "1860", "--solve-wall-timeout", "3000",
            "--candidate-generation-max-steps", "12", "--home", str(campaign / "native-home"), "--json"]
    with redirect_stdout(StringIO()):
        code = cli.main(args, _acceptance_preparation_hook=prepared)
    # `solve` reports a completed run with a failed evolution as an execution
    # failure (exit 1); argument and admission errors remain exit 2.
    assert code == (1 if fail_generation else 0)
    database = campaign / "native-home/state.db"
    if quiesce_database:
        # Match the registered native runner's seal boundary before taking any inventory.
        _quiesce_native_database(database)
    return registration, campaign, database, observed["parent_run_id"]


def test_native_campaign_audits_all_candidates_and_is_read_only(tmp_path, monkeypatch):
    from lunar_evolution import acceptance_campaign_audit as audit

    registration, campaign, database, parent_id = native_campaign(tmp_path, monkeypatch)
    store = Store(database)
    child = next(e["payload"]["evolution_run_id"] for e in store.list_events(parent_id)
                 if e["type"] == "evolution_linked")
    assert len([e for e in store.list_events(child) if e["type"] == "agent_candidate_generation"]) == 2
    # The source Store reads reopen WAL mode, so finish them before sealing the inventory.
    _quiesce_native_database(database)
    before = {p.relative_to(campaign): p.read_bytes() for p in campaign.rglob("*") if p.is_file()}
    original_snapshot = audit.audit_snapshot

    @contextmanager
    def collect_after_inventory(source):
        gc.collect()
        with original_snapshot(source) as snapshot:
            yield snapshot

    monkeypatch.setattr(audit, "audit_snapshot", collect_after_inventory)
    monkeypatch.setattr(subprocess, "Popen", lambda *_a, **_k: pytest.fail("audit executed a process"))
    report = audit.audit_native_campaign(registration, campaign_root=campaign, database=database, parent_run_id=parent_id)
    assert report["status"] == "verified", json.dumps(report, sort_keys=True)
    assert report["preparation_success"] == report["primary_success"] == report["joint_success"] == "1/1"
    assert report["candidate_counts"] == {"observed": 2, "parser_complete": 2, "executed": 2, "scored": 2}
    assert report["holdout_counts"] == {"passed": 8, "failed": 0, "unknown": 0, "missing": 0}
    assert report["provider_called_during_audit"] is False
    assert before == {p.relative_to(campaign): p.read_bytes() for p in campaign.rglob("*") if p.is_file()}


def test_unquiesced_campaign_fails_closed_when_source_connections_are_collected(tmp_path, monkeypatch):
    from lunar_evolution import acceptance_campaign_audit as audit

    automatic_gc = gc.isenabled()
    gc.disable()
    try:
        registration, campaign, database, parent_id = native_campaign(
            tmp_path, monkeypatch, quiesce_database=False,
        )
        wal = database.with_name(database.name + "-wal")
        shm = database.with_name(database.name + "-shm")
        assert wal.is_file() and shm.is_file()
        database_before = database.read_bytes()
        original_snapshot = audit.audit_snapshot

        @contextmanager
        def collect_after_inventory(source):
            gc.collect()
            with original_snapshot(source) as snapshot:
                yield snapshot

        monkeypatch.setattr(audit, "audit_snapshot", collect_after_inventory)
        monkeypatch.setattr(subprocess, "Popen", lambda *_a, **_k: pytest.fail("audit executed a process"))
        report = audit.audit_native_campaign(
            registration, campaign_root=campaign, database=database, parent_run_id=parent_id,
        )
        assert report["status"] == "failed", json.dumps(report, sort_keys=True)
        assert report["reason"] == "audit_inventory_changed"
        assert report["mutated_during_audit"] is True
        assert report["primary_success"] == "1/1"
        assert not wal.exists() and not shm.exists()
        assert database.read_bytes() != database_before
    finally:
        if automatic_gc:
            gc.enable()


def test_bad_retained_probe_cannot_inherit_native_success(tmp_path, monkeypatch):
    from lunar_evolution.acceptance_campaign_audit import audit_native_campaign

    registration, campaign, database, parent_id = native_campaign(tmp_path, monkeypatch)
    (campaign / "runtime-binding/00/actual.json").write_bytes(b"{}")
    report = audit_native_campaign(registration, campaign_root=campaign, database=database, parent_run_id=parent_id)
    assert report["status"] == "failed"
    assert report["primary_success"] == report["joint_success"] == "0/1"


def test_native_generation_failure_retains_preparation_only(tmp_path, monkeypatch):
    from lunar_evolution.acceptance_campaign_audit import audit_native_campaign

    registration, campaign, database, parent_id = native_campaign(tmp_path, monkeypatch, fail_generation=True)
    report = audit_native_campaign(registration, campaign_root=campaign, database=database, parent_run_id=parent_id)
    assert report["preparation_success"] == "1/1"
    assert report["primary_success"] == report["joint_success"] == "0/1"
    assert report["candidate_counts"]["parser_complete"] == 0


def test_missing_preparation_does_not_count_unrun_holdouts_as_failed(tmp_path, monkeypatch):
    from lunar_evolution.acceptance_campaign_audit import audit_native_campaign

    registration, campaign, database, parent_id = native_campaign(tmp_path, monkeypatch)
    with closing(Store(database)._connect()) as connection, connection:
        connection.execute("DELETE FROM events WHERE run_id = ? AND type = 'bundle_profile_prepared'", (parent_id,))
    _quiesce_native_database(database)
    report = audit_native_campaign(registration, campaign_root=campaign, database=database, parent_run_id=parent_id)
    assert report["status"] == "failed"
    assert report["preparation_success"] == "0/1"
    assert report["holdout_counts"] == {"passed": 0, "failed": 0, "unknown": 0, "missing": 8}


def test_published_audit_is_create_only_and_read_only_reaudit_detects_drift(tmp_path, monkeypatch):
    from lunar_evolution.acceptance_campaign_audit import (
        AcceptanceCampaignAuditError,
        publish_native_campaign_audit,
        verify_native_campaign_audit,
    )

    registration, campaign, database, parent_id = native_campaign(tmp_path, monkeypatch)
    evidence = tmp_path / "independent-audit"
    report = publish_native_campaign_audit(
        registration, campaign_root=campaign, database=database, parent_run_id=parent_id,
        output_directory=evidence,
    )
    assert report["joint_success"] == "1/1"
    assert verify_native_campaign_audit(campaign_root=campaign, output_directory=evidence)["status"] == "verified"
    with pytest.raises(AcceptanceCampaignAuditError, match="audit_publish_conflict"):
        publish_native_campaign_audit(registration, campaign_root=campaign, database=database,
                                      parent_run_id=parent_id, output_directory=evidence)
    (campaign / "unexpected.bin").write_bytes(b"drift")
    with pytest.raises(AcceptanceCampaignAuditError, match="audit_inventory_changed"):
        verify_native_campaign_audit(campaign_root=campaign, output_directory=evidence)


def test_published_failed_audit_remains_failed_when_inventory_is_intact(tmp_path, monkeypatch):
    from lunar_evolution.acceptance_campaign_audit import (
        _publish_native_campaign_audit_report,
        verify_native_campaign_audit,
    )

    _registration, campaign, _database, _parent_id = native_campaign(tmp_path, monkeypatch)
    evidence = tmp_path / "independent-audit"
    failed = {
        "schema_version": "1",
        "scope": "acceptance_campaign_audit",
        "status": "failed",
        "primary_success": "0/1",
        "joint_success": "0/1",
        "reason": "audit_inventory_changed",
    }
    _publish_native_campaign_audit_report(failed, campaign_root=campaign, output_directory=evidence)
    result = verify_native_campaign_audit(campaign_root=campaign, output_directory=evidence)
    assert result["status"] == "failed"
    assert result["joint_success"] == "0/1"
